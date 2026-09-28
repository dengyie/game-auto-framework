"""
Unit tests for the zero-token local quiz engine (quiz_solver.py) and its
daily_dailies DAG integration (classify_screen quiz flag + handle_quiz operator).

Bank lineage: four vendored upstream sources (MHXYExamAssistant / Maa_MHXY_MG /
mhxy_exam_answer / XYQQuiz), deduped by normalized question.
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from plugins.mhxy_mobile.custom import daily_handlers as dh
from plugins.mhxy_mobile.custom.quiz_solver import (
    QuizBank,
    QuizSolver,
    clean_question_text,
    fix_ocr_noise,
    get_default_solver,
    normalize_text,
)
from scheduler.dag import NodeAction, PipelineContext


class DummyOCRItem:
    def __init__(self, text: str, center: tuple, confidence: float = 0.95):
        self.text = text
        self.center = center
        self.confidence = confidence


class DummyDevice:
    def __init__(self):
        self.clicks = []
        self.keys = []

    def click(self, x: float, y: float):
        self.clicks.append((float(x), float(y)))

    def press_key(self, keycode):
        self.keys.append(keycode)

    def screencap(self, raw: bool = False):
        return b""


@pytest.fixture()
def bank_db(tmp_path) -> Path:
    return tmp_path / "quiz_bank_test.db"


@pytest.fixture()
def solver(bank_db) -> QuizSolver:
    """Solver seeded from the four vendored upstream sources into a temp DB."""
    return QuizSolver(db_path=bank_db)


# --- text normalization --------------------------------------------------------

def test_normalize_text_strips_punct_and_width():
    assert normalize_text("大唐官府 的门派师傅是谁？") == normalize_text("大唐官府的门派师傅是谁")
    assert normalize_text("《西游时讯》不包括哪条内容？") == normalize_text("西游时讯不包括哪条内容")


def test_clean_question_text_strips_markers():
    assert clean_question_text("第12题：三界奇缘（3/10）谁是小柔的意中人？") == "三界奇缘谁是小柔的意中人？"


def test_fix_ocr_noise_applies_upstream_table():
    assert fix_ocr_noise("三味真火是魔王寨技能") == "三昧真火是魔王寨技能"


# --- engine: matching ------------------------------------------------------------

def test_exact_hit_and_option_mapping(solver):
    d = solver.answer("抓鬼任务需在长安找到何人？", ["李靖", "魏征", "钟馗", "秦琼"])
    assert d.bank_hit and d.source == "exact"
    assert d.option_index == 2 and d.option_text == "钟馗"
    assert d.confidence >= 0.9
    assert d.elapsed_ms < 50.0


def test_fuzzy_hit_with_ocr_noise(solver):
    # OCR noise: stray spaces + punctuation retained + one wrong char kept below 82
    d = solver.answer("下列哪种宝石可以增加法术防御", ["黑宝石", "翡翠石", "红纹石"])
    assert d.bank_hit and d.option_text == "翡翠石"
    assert d.confidence >= 0.6


def test_multi_answer_bank_entry(solver):
    # From Maa_MHXY_MG tiku: both answers are valid, either option must map
    q = "以下谁有可能是骨精灵的师父？"
    d1 = solver.answer(q, ["地藏王", "牛魔王", "观音菩萨", "太白金星"])
    d2 = solver.answer(q, ["大大王", "牛魔王", "观音菩萨", "太白金星"])
    assert d1.bank_hit and d1.option_text == "地藏王"
    assert d2.bank_hit and d2.option_text == "大大王"


def test_miss_returns_unmapped_decision(solver):
    d = solver.answer("Xylophone完全不在题库里的奇怪问题", ["金", "银", "铜"])
    assert not d.bank_hit and d.source == "miss" and d.option_index == -1 and d.confidence == 0.0


def test_miss_legacy_solve_falls_back_to_first_option(solver):
    idx, text, conf = solver.solve("完全不在题库里的奇怪问题", ["甲", "乙", "丙", "丁"])
    assert (idx, text, conf) == (0, "甲", 0.25)


def test_low_band_match_flagged_not_confident(bank_db):
    tuned = QuizSolver(db_path=bank_db, question_threshold=95.0, low_band_threshold=50.0)
    # drop the leading 下列 and append 呀: indel distance 3 -> similarity ~88.9 (50..95 band)
    d = tuned.answer("哪种宝石可以增加法术防御呀", ["翡翠石"])
    assert d.bank_hit and d.source == "fuzzy_low"
    # legacy API still returns the mapped option, but confidence stays below exact band
    assert d.confidence < 0.98


# --- engine: bank persistence & import -------------------------------------------

def test_bank_dedup_and_persistence(bank_db):
    bank = QuizBank(db_path=bank_db, auto_seed=False)
    assert bank.add_question("抓鬼任务需在长安找到何人?", ["钟馗"], source="t1")
    assert not bank.add_question("抓鬼任务需在长安找到何人？", ["钟馗"], source="t2")  # dup by q_norm
    bank.add_question("下列哪种宝石可以增加法术防御?", ["翡翠石"], source="t1")
    assert bank.count() == 2

    # persistence: a fresh instance on the same file sees the rows
    bank2 = QuizBank(db_path=bank_db, auto_seed=False)
    assert bank2.count() == 2

    bank.close()
    bank2.close()


def test_add_many_batch_dedup(bank_db):
    bank = QuizBank(db_path=bank_db, auto_seed=False)
    added, skipped = bank.add_many([
        ("问题一是什么", ["甲"], "general", "batch"),
        ("问题一是什么", ["甲"], "general", "batch"),  # in-batch dup
        ("问题二是什么", ["乙"], "general", "batch"),
        ("", ["空题"], "general", "batch"),            # empty question
        ("问题三是什么", [], "general", "batch"),       # empty answers
    ])
    assert added == 2 and bank.count() == 2
    bank.close()


def test_import_bank_external_json(bank_db, tmp_path):
    solver = QuizSolver(db_path=bank_db)
    ext = tmp_path / "external.json"
    ext.write_text(json.dumps([
        {"question": "自定义导入题一", "answer": "答案一"},
        {"question": "自定义导入题二", "answer": "答案二"},
        {"question": "自定义导入题一", "answer": "答案一"},  # dup
    ], ensure_ascii=False), encoding="utf-8")
    added, skipped = solver.import_bank(ext)
    assert added == 2
    d = solver.answer("自定义导入题二", ["答案一", "答案二"])
    assert d.bank_hit and d.option_text == "答案二"


def test_vendored_sources_all_imported(solver):
    # 838 + 393 + 446 + 2586 raw = 4263; cross-source dedup keeps ~3850 unique
    assert solver.size >= 3700
    sources = solver.bank.count_by_source()
    assert set(sources) == {"exam_assistant", "maa_mhxy_mg", "mhxy_exam_answer", "xyq_quiz"}


def test_latency_budget_on_real_bank(solver):
    queries = []
    for q in ["抓鬼任务需在长安找到何人？", "下列哪种宝石可以增加法术防御？", "打造装备需要什么道具？"]:
        queries.append(q)                                   # exact
        queries.append(q.replace("？", "") + "呀呀")        # fuzzy band
    queries.extend(["与题库无关的问题%d号" % i for i in range(24)])  # worst case: full scans
    times = [solver.answer(q, ["甲", "乙", "丙", "丁"]).elapsed_ms for q in queries]
    p95 = sorted(times)[int(0.95 * len(times))]
    assert p95 < 15.0, f"p95={p95:.1f}ms exceeds the 15ms zero-token budget"


def test_default_singleton_and_seed():
    s1 = get_default_solver()
    s2 = get_default_solver()
    assert s1 is s2
    assert s1.size >= 3700


# --- screen classification & handler wiring --------------------------------------

QUIZ_SCREEN_ITEMS = [
    DummyOCRItem("三界奇缘", (640.0, 45.0)),
    DummyOCRItem("下列哪种宝石可以增加法术防御?", (700.0, 95.0)),
    DummyOCRItem("黑宝石", (500.0, 300.0)),
    DummyOCRItem("翡翠石", (800.0, 300.0)),
    DummyOCRItem("红纹石", (500.0, 380.0)),
    DummyOCRItem("太阳石", (800.0, 380.0)),
]


def _ctx_with(device=None) -> PipelineContext:
    ctx = PipelineContext(device=device or DummyDevice())
    ctx.variables["daily_queue"] = ["师门任务", "宝图任务", "运镖"]
    ctx.variables["completed_tasks"] = []
    return ctx


def test_classify_screen_detects_quiz_open():
    ctx = _ctx_with()
    with patch.object(dh, "_ocr_items", return_value=QUIZ_SCREEN_ITEMS):
        assert dh.classify_screen(ctx, None) is True
    assert ctx.variables["quiz_open"] is True
    assert ctx.variables["need_open_panel"] is False


def test_classify_screen_dialog_not_quiz():
    ctx = _ctx_with()
    items = [
        DummyOCRItem("请选择要做的事", (300.0, 400.0)),
        DummyOCRItem("师门任务", (900.0, 450.0)),
        DummyOCRItem("跳过", (900.0, 520.0)),
    ]
    with patch.object(dh, "_ocr_items", return_value=items):
        assert dh.classify_screen(ctx, None) is True
    assert ctx.variables["dialog_open"] is True
    assert ctx.variables["quiz_open"] is False


def test_classify_screen_main_city_not_quiz():
    """主城 HUD（指引/挂机/社群/直播录像 + 玩家名 + 活动横幅）绝不能误判成答题界面。"""
    ctx = _ctx_with()
    city_items = [
        # main-city top bar buttons (world HUD markers)
        DummyOCRItem("指引", (270.0, 63.0)),
        DummyOCRItem("活动", (352.0, 63.0)),
        DummyOCRItem("排行", (430.0, 63.0)),
        DummyOCRItem("挂机", (505.0, 63.0)),
        DummyOCRItem("社群", (580.0, 63.0)),
        DummyOCRItem("直播录像", (660.0, 63.0)),
        # event banner text inside question ROI (long enough to look like a question)
        DummyOCRItem("神秘礼物时空交织，溢彩流光来自超级神蛇服务器的花火", (700.0, 100.0)),
        # player name tags inside option ROI
        DummyOCRItem("灵狐栖梦", (500.0, 300.0)),
        DummyOCRItem("天阶夜色", (760.0, 330.0)),
        DummyOCRItem("入间大帅", (900.0, 280.0)),
    ]
    with patch.object(dh, "_ocr_items", return_value=city_items):
        assert dh.classify_screen(ctx, None) is True
    v = ctx.variables
    assert v["quiz_open"] is False
    # city idle -> the pipeline should open the activity panel instead of "answering"
    assert v["need_open_panel"] is True


def test_handle_quiz_clicks_bank_answer():
    device = DummyDevice()
    ctx = _ctx_with(device)
    with patch.object(dh, "_ocr_items", return_value=QUIZ_SCREEN_ITEMS):
        dh.classify_screen(ctx, None)
    dh.handle_quiz(ctx, NodeAction(type="custom", custom_func="handle_quiz"))
    assert ctx.variables["quiz_bank_hit"] is True
    assert ctx.variables["quiz_source"] in ("exact", "fuzzy")
    # clicked the 翡翠石 option button (800, 300)
    assert any(abs(x - 800.0) < 1 and abs(y - 300.0) < 1 for x, y in device.clicks)


def test_handle_quiz_miss_clicks_first_option():
    device = DummyDevice()
    ctx = _ctx_with(device)
    items = [
        DummyOCRItem("与题库无关的稀奇古怪问题?", (700.0, 95.0)),
        DummyOCRItem("甲选项", (500.0, 300.0)),
        DummyOCRItem("乙选项", (800.0, 300.0)),
    ]
    with patch.object(dh, "_ocr_items", return_value=items):
        dh.classify_screen(ctx, None)
    dh.handle_quiz(ctx, NodeAction(type="custom", custom_func="handle_quiz"))
    assert ctx.variables["quiz_bank_hit"] is False
    assert device.clicks == [(500.0, 300.0)]  # upstream policy: first option on miss


def test_handle_quiz_done_screen_presses_back():
    device = DummyDevice()
    ctx = _ctx_with(device)
    items = [DummyOCRItem("今日答题已完成", (640.0, 300.0)), DummyOCRItem("明日再来", (640.0, 380.0))]
    with patch.object(dh, "_ocr_items", return_value=items):
        dh.classify_screen(ctx, None)
    # Tick 1: no 已获得奖励 label on this screen -> gift falls back to fixed coords
    dh.handle_quiz(ctx, NodeAction(type="custom", custom_func="handle_quiz"))
    assert device.clicks == [(330.0, 320.0)]
    # Tick 2: gift stage done -> leave via back key
    dh.handle_quiz(ctx, NodeAction(type="custom", custom_func="handle_quiz"))
    assert device.keys == [4]
    assert "三界奇缘" in ctx.variables["completed_tasks"]
    assert ctx.variables["current_task_done"] is True


def test_handle_quiz_feedback_interstitial_dismissed():
    device = DummyDevice()
    ctx = _ctx_with(device)
    items = [
        DummyOCRItem("回答正确", (640.0, 200.0)),
        DummyOCRItem("确定", (640.0, 450.0)),
    ]
    with patch.object(dh, "_ocr_items", return_value=items):
        dh.classify_screen(ctx, None)
    dh.handle_quiz(ctx, NodeAction(type="custom", custom_func="handle_quiz"))
    assert any(abs(x - 640.0) < 1 and abs(y - 450.0) < 1 for x, y in device.clicks)


def test_daily_dag_has_quiz_branch():
    pipeline_path = Path(__file__).parent.parent / "plugins" / "mhxy_mobile" / "pipelines" / "daily_dailies.json"
    dag = json.loads(pipeline_path.read_text(encoding="utf-8"))
    branch = next(b for b in dag["nodes"][0]["branches"] if b["condition"] == "quiz_open")
    assert branch["next"] == "quiz_answer"
    node = next(n for n in dag["nodes"] if n["name"] == "quiz_answer")
    assert node["action"]["custom_func"] == "handle_quiz"
    assert "sense" in node["next"]


def test_handle_quiz_done_screen_live_wording():
    """实机完成页文案「恭喜少侠完成所有题目！」必须识别为已答完：退回并标记完成。"""
    device = DummyDevice()
    ctx = _ctx_with(device)
    items = [
        DummyOCRItem("三界奇缘", (160.0, 300.0)),
        DummyOCRItem("准确率", (270.0, 97.0)),
        DummyOCRItem("9/10", (380.0, 97.0)),
        DummyOCRItem("恭喜少侠完成所有题目！", (800.0, 430.0)),
        DummyOCRItem("已获得奖励", (300.0, 508.0)),
    ]
    ctx.variables["_last_frame_items"] = items

    dh.handle_quiz(ctx, None)  # tick 1: collect the gift first
    assert device.clicks == [(330.0, 320.0)]

    dh.handle_quiz(ctx, None)  # tick 2: no reward popup -> leave via back key
    assert 4 in device.keys  # back key pressed to leave the done screen
    assert "三界奇缘" in ctx.variables["completed_tasks"]
    assert ctx.variables.get("current_task_done") is True

    # The completion screen must classify as a quiz screen so the DAG routes it
    # into quiz_answer (its vertical title sits outside the header band).
    ctx2 = _ctx_with()
    with patch.object(dh, "_ocr_items", return_value=items):
        dh.classify_screen(ctx2, None)
    assert ctx2.variables["quiz_open"] is True


def test_handle_quiz_done_collects_gift_before_leaving():
    """完成页的礼盒必须先点击领取（一次点击机会），处理领奖弹窗后再退出。"""
    device = DummyDevice()
    ctx = _ctx_with(device)
    items = [
        DummyOCRItem("准确率", (270.0, 97.0)),
        DummyOCRItem("恭喜少侠完成所有题目！", (800.0, 430.0)),
        DummyOCRItem("已获得奖励", (300.0, 508.0)),
        DummyOCRItem("147012", (300.0, 557.0)),
    ]
    ctx.variables["_last_frame_items"] = items

    # Tick 1: click the gift box (fixed offset above the 已获得奖励 label) — no back yet
    dh.handle_quiz(ctx, None)
    assert device.clicks == [(330.0, 320.0)]
    assert 4 not in device.keys
    assert ctx.variables.get("quiz_gift_clicked") is True

    # Tick 2: no reward popup -> now leave via back key and mark completed
    dh.handle_quiz(ctx, None)
    assert 4 in device.keys
    assert "三界奇缘" in ctx.variables["completed_tasks"]
    assert ctx.variables.get("quiz_gift_clicked") is False


def test_handle_quiz_confirm_gift_popup_then_leave():
    """礼盒点击后弹出的领奖确认（确定）：先点确定，下一 tick 再退出。"""
    device = DummyDevice()
    ctx = _ctx_with(device)
    base = [
        DummyOCRItem("恭喜少侠完成所有题目！", (800.0, 430.0)),
        DummyOCRItem("已获得奖励", (300.0, 508.0)),
    ]
    ctx.variables["_last_frame_items"] = base + [
        DummyOCRItem("获得 银币×5000", (640.0, 350.0)),
        DummyOCRItem("确定", (640.0, 470.0)),
    ]
    ctx.variables["quiz_gift_clicked"] = True

    dh.handle_quiz(ctx, None)
    assert ctx.device.clicks == [(640.0, 470.0)]
    assert 4 not in device.keys  # leave happens on the next tick


def test_handle_quiz_dismisses_covering_popup():
    """答题中被弹窗遮挡（无可解析题目但有 ×）：关闭弹窗，绝不盲点。"""
    device = DummyDevice()
    ctx = _ctx_with(device)
    ctx.variables["_last_frame_items"] = [
        DummyOCRItem("×", (1143.0, 113.0)),
        DummyOCRItem("系统公告", (640.0, 300.0)),
    ]

    dh.handle_quiz(ctx, None)
    assert ctx.device.clicks == [(1143.0, 113.0)]


def test_handle_quiz_rejects_guide_garbage_question():
    """指引/推荐配置页被行分组拼成假题干：识别为遮挡弹窗并关闭，不点首选项。"""
    device = DummyDevice()
    ctx = _ctx_with(device)
    ctx.variables["_last_frame_items"] = [
        DummyOCRItem("通关推荐配置：咨询专家", (620.0, 90.0)),
        DummyOCRItem("前往提升", (1006.0, 359.0)),
        DummyOCRItem("×", (1143.0, 113.0)),
    ]

    dh.handle_quiz(ctx, None)
    assert ctx.device.clicks == [(1143.0, 113.0)]
