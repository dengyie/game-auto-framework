# game-auto-framework

> 工业级通用游戏自动化与搬砖中台调度引擎 (General Game Automation & Farming Framework)

## 核心设计哲学
- **引擎与业务彻底解耦**：Core 引擎专注于高精度感知、低延迟屏幕抓取、三阶贝塞尔拟人化输入与 DAG 流水线调度；上层游戏通过独立的 Plugin 扩展包（切图、坐标、Pipeline JSON）热插拔接入。
- **双层防御与零 Token 架构 (Two-Tier Principle)**：
  - **第一层：本地确定性流水线 (Zero-Token Local Pipeline)**：重复日常活动（师门、宝图、挖宝、运镖、秘境降妖、科举三界答题、门派日常等）绝对零 Token 依赖，100% 运行在本地轻量 DAG 状态机、RapidOCR ONNX、OpenCV 模板与离线 SQLite 题库上。响应 30~300ms，0 外部 API 成本。
  - **第二层：储备大模型防御层 (Reserved VLM Tier)**：大模型/视觉语言模型严格保留在极低频特殊场景——节日新活动玩法探索、未收录的新型防挂机旋转/文字点选验证码破解以及题库未收录的长尾冷门问答。
- **现代化顶层技术体系借鉴**：
  - **Maa_MHXY_MG (227⭐) & MaaFramework (4.9k⭐)**：声明式 DAG 状态机流水线（节点跳转、重试自愈、全局中断拦截器），战斗状态解耦与多任务流转。
  - **haungwanjun/mhxy_fz (344⭐)**：局部 dHash 汉明距离差分事件驱动，**任务追踪栏优先寻路机制**（直接点击右侧追踪栏驱动游戏原生寻路，摒弃大地图与 NPC 点击）。
  - **0xn0ne/MHXYExamAssistant (20⭐)**：本地 20,000+ 条 SQLite 题库与 RapidFuzz 模糊匹配，离线 15ms 零 Token 秒答。
  - **wuliangyue/mhxy-escort (149⭐) & BestBurning/mhxy (304⭐)**：防挂机验证弹窗三级自愈防御与底层内核驱动级仿真。
  - **BetterGI (15.6k⭐)**：DirectX/WGC 零拷贝硬件抓屏、透明穿透 Overlay HUD 交互、ONNX 目标检测。
  - **March7thAssistant (11.5k⭐)**：现代 `uv` 工程体系、云游戏微端推流与 Docker 无头化 (Headless) 运行、全渠道异常推送。
  - **Alas (4.0k⭐)**：Cron+Priority 工业级调度器、集群池看门狗守护、三级自愈逃生链 (Escape Sequence)。

## 权威项目文档导航
- [系统架构设计文档 (docs/architecture.md)](docs/architecture.md)：五层解耦模型、双层零 Token 架构、集群双锁、家宽代理与防封技术体系。
- [梦手日常自动化与战斗策略开发指南 (docs/daily_automation.md)](docs/daily_automation.md)：日常全流程 SOP、50 活跃度门槛自愈跳过、宝箱动态领取、月宫/召唤兽战斗决策矩阵与实机测试指南。

## 架构拓扑
```
game-auto-framework/
├── core/                  # 通用核心引擎底座
│   ├── capture/           # 屏幕捕获 (WGC/DXGI, minicap, ADB, Socket流)
│   ├── cv/                # 视觉感知 (多尺度模板匹配, NMS, dHash 汉明帧差分, 战斗检测)
│   ├── ocr/               # 文本提取 (RapidOCR ONNX + RapidFuzz 模糊纠错与屏幕定位)
│   ├── input/             # 拟人仿生驱动 (三阶贝塞尔曲线, 高斯偏置点击, Dwell Time, 指腹微漂移)
│   └── device/            # 跨平台设备抽象与工厂 (Linux ADB / Win / Mac / Virtual)
├── scheduler/             # 调度与状态机
│   ├── dag.py             # 增强型 DAG Pipeline 引擎 (动态分支, 上下文流, 中断拦截)
│   ├── escape.py          # 三级看门狗自愈逃生机制 (45s/120s/300s 递进脱困)
│   └── routine.py         # 日常任务链编排器与防挂机熔断保护
├── plugins/               # 游戏业务扩展包
│   └── mhxy_mobile/       # 首发插件：《梦幻西游手游》
│       ├── manifest.json  # 插件清单与元数据
│       ├── config/        # 1280x720 基准分辨率坐标与热区
│       ├── pipelines/     # 师门20轮、打图挖宝、运镖、防挂机拦截 JSON
│       └── custom/        # 本地智能题库答题 (QuizSolver) 与业务算子
├── server/                # FastAPI 远程调用微服务中枢 (单任务/任务链/截图流)
└── tests/                 # 9 大测试套件 (31 项测试 100% 通过)
```

## 核心能力矩阵 (Milestone 1)

1. **四级级联视觉感知体系**：
   - `dHash` 差异哈希与汉明距离 (<3ms) 过滤静止画面，画面静止时休眠降低 70% CPU。
   - OpenCV 归一化互相关匹配与多尺度金字塔 (0.85~1.15x)，结合 NMS 非极大值抑制。
   - 自动战斗 UI 区域匹配与金色高光 HSV 掩模毫秒级脱战状态研判。
   - RapidOCR ONNX 轻量中文模型与 RapidFuzz 局部/词元模糊纠错，反向定位屏幕中心。
2. **拟人化仿生动力学防封**：
   - 2D 高斯正态分布随机点击偏置，杜绝像素几何中心连点。
   - 真实人体按压驻留时间 (55~120ms Dwell Time) 配合 1~2px 指腹接触微漂移 (Micro-Drift)。
   - 三阶贝塞尔曲线模拟启动加速 (Ease-in)、巡航与终点减速 (Ease-out)，叠加正弦微抖动。
3. **增强型 DAG 状态机与看门狗自愈**：
   - 声明式节点动态条件分支 (`branches: [{"condition": "...", "next": "..."}]`)。
   - 上下文瞬态坐标自动捕获与跨节点传递 (`last_match_point` / `last_text_point`)。
   - 全局高优先级中断机制实时阻断防挂机验证弹窗。
   - 45s (ESC后退) / 120s (长安回城) / 300s (进程硬重启) 三级递进式自愈脱困。
4. **首发业务落地：《梦幻西游手游》(mhxy_mobile)**：
   - `daily_shimen`: 20 轮自动计数闭环（接取/寻路/买药/上交/巡逻战斗）。
   - `daily_baotu`: 店小二接取、贼王战斗、10 轮计数与自动开包连续 10 张挖宝闭环。
   - `daily_yuntong`: 郑镖头领镖、巡航走图、遇敌战斗、送达结算闭环。
   - `quiz`: 本地离线答题引擎（`quiz_solver.py`）：四源开源真题库合并去重 3854 条 SQLite 题库 + RapidFuzz 模糊匹配，毫秒级零 Token 作答科举/三界奇缘。
   - `anti_bot_interceptor`: 弹窗全天候毫秒级拦截化解。
5. **日常任务链与熔断保护**：
   - `TaskRoutineExecutor` 顺序串联执行 `["shimen", "baotu", "yuntong"]`。
   - 防挂机连续识别失败自动触发 `CIRCUIT_BROKEN` 安全制动，坚决防范账号进苦行。
   - FastAPI 服务端提供 `POST /api/v1/tasks/start-routine` 与 `GET /api/v1/tasks/routine-status`。
6. **零 Token 确定性日常与多门派战斗扩展体系 (Milestone 7)**：
   - 统一日常 DAG (`daily_dailies.json`)：集成分类感知、活动面板调度、追踪栏寻路、对话选择与脱战结算。
   - 50 活跃度门槛动态提取与运镖**延迟补跑**：活跃度不足时保持未完成并在后续面板访问自动重试（默认队列 `师门→宝图→秘境→三界奇缘→运镖` 先积累活跃度），规避报错 Toast 与循环死锁，确保押镖真正被执行。
   - **秘境活跃度达标判据与仙玉安全（实机校准）**：秘境 +25 活跃按闯关进度累积（第6关=11/25），完成态面板无再入口——"完成"胶囊识别 + 活跃X/Y 计数如实告警缺口；主城 HUD 一票否决防答题误判；面板首屏之下先滚动补扫再决策；进度条气泡 OCR 盲区用绿色填充像素换算；含"仙玉"弹窗绝不自动确认（安全退出并阻断当日秘境）；终局如实告警未打满与活跃度缺口，杜绝假完成。
   - 活跃度阶段宝箱动态领取与物品奖励弹窗优先消除机制。
   - **多门派可扩展战斗架构 (`SectCombatRegistry`)**：彻底解耦单门派硬编码，提供统一门派策略注册表与引擎（`combat_strategy.py`），全量支持月宫、魔王寨（飞砂走石/三昧真火）、方寸山（五雷咒/失心符封印）、普陀山（五行咒/普渡众生/灵动九天）以及全 11 大主流门派。
   - **视觉 OCR 技能词条自适应识别**：在无配置时自动通过操作盘技能词条识别并绑定角色门派，零配置自愈运行。
   - **召唤兽分发与首回合防封**：攻宠普攻点杀、法宠法术群秒、血宠防御保全；首回合精确施法后自动开启“自动战斗”，避免战斗期间机械空点被风控特征检测。
   - **实机通关与单元测试**：真实 MuMu 模拟器实测连续通关秘境降妖 1~2 层全关卡（6~10关）；日常与战斗专项单测 100% 验证通过（受影响面 60 passed）。
   - **本地离线答题引擎 (`quiz_solver.py`)**：收割 MHXYExamAssistant / Maa_MHXY_MG / mhxy_exam_answer / XYQQuiz 四源真题 4263 条，按归一化题干去重合并 **3854 条** SQLite 题库；归一化精确索引 + RapidFuzz 0.82 阈值模糊匹配 + 多答案选项对映，实测 0~3ms 零 Token 作答；`daily_dailies` 挂载 `quiz_open` 感知与 `handle_quiz` 算子（ROI/行分组/`第n题`清洗/OCR 误读替换表借自上游 Maa `reco_sjqy`），未命中点首选项并可按需开启 Tier-2 VLM 兜底；22 项专项单测全绿（受影响面回归 51 passed）。

## 快速开始

```bash
# 1. 使用 uv 同步依赖
uv sync

# 2. 运行全链路自动化测试
uv run pytest tests/

# 3. 启动 FastAPI 远程中枢
uv run uvicorn server.app:app --host 0.0.0.0 --port 8000
```

