"""Extensible Sect Combat Strategy Registry and Decision Engine.

Provides zero-token deterministic combat decision strategies for all 《梦幻西游》手游
sects (门派) and pets (召唤兽):
- Physical DPS: 月宫 (Moon Palace), 大唐官府, 狮驼岭, 花果山
- Magic DPS: 魔王寨 (Demon King), 龙宫, 小雷音
- Seal / Control: 方寸山 (Fangcun)
- Healer / Support: 普陀山 (Putuo), 化生寺, 阴曹地府
- Pets: 攻宠 (Physical Attack), 法宠 (Magic AoE), 血宠/配速 (Defense/Item)

Supports:
1. Dynamic multi-monster (>1) vs single-monster (<=1) skill branching.
2. OCR skill keyword recognition with geometric fallbacks.
3. Automatic sect detection from visible skill names.
4. Extensible registry pattern allowing custom sect plug-ins.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("mhxy.combat_strategy")

# Standard skill wheel coordinates (1280x720 base)
COORD_AOE_SKILL_FALLBACK = (1087.0, 315.0)      # Top-right slot on skill wheel (usually AoE)
COORD_SINGLE_SKILL_FALLBACK = (986.0, 315.0)    # Top-center/left slot on skill wheel (usually single burst)
COORD_SPECIAL_SKILL_FALLBACK = (950.0, 420.0)   # Auxiliary / buff slot
COORD_BOTTOM_ATTACK = (1138.0, 690.0)           # Basic attack shortcut
COORD_SPELL_MENU_BTN = (1045.0, 685.0)          # Spell menu button


@dataclass
class CombatContext:
    """Snapshot context of the current combat frame."""
    monster_count: int
    enemy_names: List[Tuple[str, Tuple[float, float]]] = field(default_factory=list)
    hp_bars: List[Tuple[float, float]] = field(default_factory=list)
    items: List[Any] = field(default_factory=list)
    frame: Any = None
    target_pos: Tuple[float, float] = (450.0, 320.0)
    round_index: int = 1
    variables: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SkillDecision:
    """The decision reached by a sect strategy for character action."""
    skill_name: str
    keywords: List[str]
    target_type: str = "primary_enemy"  # "primary_enemy", "lowest_hp_enemy", "boss", "ally", "self"
    fallback_coord: Tuple[float, float] = COORD_AOE_SKILL_FALLBACK
    priority: int = 0
    description: str = ""


@dataclass
class PetDecision:
    """The decision reached for pet (召唤灵) action."""
    pet_type: str  # "attack", "magic", "blood"
    action_name: str  # "攻击", "法术", "防御"
    keywords: List[str]
    fallback_coord: Tuple[float, float]
    target_type: str = "primary_enemy"
    description: str = ""


class BaseSectStrategy:
    """Base class for sect combat decisions."""
    sect_name: str = "未知门派"
    role_category: str = "dps"  # "physical_dps", "magic_dps", "seal", "healer", "support"
    known_skills: List[str] = []

    def decide(self, ctx: CombatContext) -> SkillDecision:
        raise NotImplementedError


class MoonPalaceStrategy(BaseSectStrategy):
    """月宫 (Moon Palace) - Physical DPS:
    - Multi-monster (>1) -> 月影瑶光 (AoE physical strike)
    - Single monster (<=1) -> 月刃 (2-hit single target physical burst)
    """
    sect_name = "月宫"
    role_category = "physical_dps"
    known_skills = ["月影瑶光", "月影摇光", "月刃", "桂花醉", "广寒清辉", "碎玉击"]

    def decide(self, ctx: CombatContext) -> SkillDecision:
        if ctx.monster_count > 1:
            return SkillDecision(
                skill_name="月影瑶光",
                keywords=["月影摇光", "月影瑶光", "摇光", "瑶光"],
                fallback_coord=COORD_AOE_SKILL_FALLBACK,
                description=f"多怪清场 (count={ctx.monster_count})，施放群体物理月影瑶光",
            )
        return SkillDecision(
            skill_name="月刃",
            keywords=["月刃"],
            fallback_coord=COORD_SINGLE_SKILL_FALLBACK,
            description="单体集火/残血收割，施放双段物理月刃",
        )


class MowangStrategy(BaseSectStrategy):
    """魔王寨 (Demon King) - Magic DPS:
    - Multi-monster (>1) -> 飞砂走石 (AoE fire magic)
    - Single monster (<=1) -> 三昧真火 (Single target high burst magic)
    """
    sect_name = "魔王寨"
    role_category = "magic_dps"
    known_skills = ["飞砂走石", "飞沙走石", "三昧真火", "魔王降临", "先祖庇佑", "守护印记", "烈焰印记", "飞星流火"]

    def decide(self, ctx: CombatContext) -> SkillDecision:
        if ctx.monster_count > 1:
            return SkillDecision(
                skill_name="飞砂走石",
                keywords=["飞砂走石", "飞沙走石", "飞砂", "走石"],
                fallback_coord=COORD_AOE_SKILL_FALLBACK,
                description=f"魔王多怪清场 (count={ctx.monster_count})，施放群体法术飞砂走石",
            )
        return SkillDecision(
            skill_name="三昧真火",
            keywords=["三昧真火", "三昧", "真火"],
            fallback_coord=COORD_SINGLE_SKILL_FALLBACK,
            description="魔王单体爆发，施放高伤法术三昧真火",
        )


class FangcunStrategy(BaseSectStrategy):
    """方寸山 (Fangcun) - Seal & Magic Control:
    - Routine multi-monster (>1) -> 五雷咒 (Routine AoE magic)
    - Single monster (<=1) or high-threat/boss -> 失心符 (Seal magic + reduce physical/magic defense)
    - Can be forced to seal via context variable 'force_seal' or 'focus_seal'
    """
    sect_name = "方寸山"
    role_category = "seal"
    known_skills = ["五雷咒", "失心符", "定身符", "离魂符", "催眠符", "神行飞步"]

    def decide(self, ctx: CombatContext) -> SkillDecision:
        force_seal = ctx.variables.get("force_seal") or ctx.variables.get("focus_seal")
        if force_seal or ctx.monster_count <= 1:
            return SkillDecision(
                skill_name="失心符",
                keywords=["失心符", "失心"],
                fallback_coord=COORD_SINGLE_SKILL_FALLBACK,
                description=f"方寸核心封印 (monsters={ctx.monster_count}, force={force_seal})，施放失心符封法降防",
            )
        return SkillDecision(
            skill_name="五雷咒",
            keywords=["五雷咒", "五雷"],
            fallback_coord=COORD_AOE_SKILL_FALLBACK,
            description=f"方寸日常群攻 (count={ctx.monster_count})，施放五雷咒输出",
        )


class PutuoStrategy(BaseSectStrategy):
    """普陀山 (Putuo) - Healer & Support:
    - Multi-monster (>1) -> 五行咒 (Fixed damage AoE, fast daily clear)
    - Single monster (<=1) or heal needed -> 普渡众生 (Double heal / HoT lamp) or 五行咒
    """
    sect_name = "普陀山"
    role_category = "healer"
    known_skills = ["五行咒", "日光华", "普渡众生", "灵动九天", "金刚定魄", "杨柳甘露", "自在心法"]

    def decide(self, ctx: CombatContext) -> SkillDecision:
        need_heal = ctx.variables.get("need_heal", False)
        support_mode = ctx.variables.get("support_mode", "auto")

        if support_mode == "buff":
            return SkillDecision(
                skill_name="灵动九天",
                keywords=["灵动九天", "灵动", "金刚定魄"],
                fallback_coord=COORD_SPECIAL_SKILL_FALLBACK,
                target_type="ally",
                description="普陀团队法伤法防增益，施放灵动九天",
            )
        if need_heal or (ctx.monster_count <= 1 and ctx.variables.get("prefer_sustain")):
            return SkillDecision(
                skill_name="普渡众生",
                keywords=["普渡众生", "普渡", "众生"],
                fallback_coord=COORD_SINGLE_SKILL_FALLBACK,
                target_type="ally",
                description="普陀回血续航，施放普渡众生点灯",
            )
        return SkillDecision(
            skill_name="五行咒",
            keywords=["五行咒", "五行", "日光华"],
            fallback_coord=COORD_AOE_SKILL_FALLBACK,
            description=f"普陀日常固伤群秒 (count={ctx.monster_count})，施放五行咒清场",
        )


class DragonPalaceStrategy(BaseSectStrategy):
    """龙宫 (Dragon Palace) - Magic DPS:
    - Multi-monster (>1) -> 龙卷雨击 (Wide AoE water magic)
    - Single monster (<=1) -> 龙腾 (Single target focused water magic)
    """
    sect_name = "龙宫"
    role_category = "magic_dps"
    known_skills = ["龙卷雨击", "龙卷", "龙腾", "龙吟", "二龙戏珠", "清心", "魔浪滔天"]

    def decide(self, ctx: CombatContext) -> SkillDecision:
        if ctx.monster_count > 1:
            return SkillDecision(
                skill_name="龙卷雨击",
                keywords=["龙卷雨击", "龙卷"],
                fallback_coord=COORD_AOE_SKILL_FALLBACK,
                description=f"龙宫大范围群攻 (count={ctx.monster_count})，施放龙卷雨击",
            )
        return SkillDecision(
            skill_name="龙腾",
            keywords=["龙腾"],
            fallback_coord=COORD_SINGLE_SKILL_FALLBACK,
            description="龙宫单体爆发点杀，施放龙腾",
        )


class DatingStrategy(BaseSectStrategy):
    """大唐官府 - Physical DPS:
    - Multi-monster (>1) -> 破釜沉舟 (Physical AoE)
    - Single monster (<=1) -> 横扫千军 (3-hit single burst)
    """
    sect_name = "大唐官府"
    role_category = "physical_dps"
    known_skills = ["横扫千军", "破釜沉舟", "翩鸿一击", "嗜血", "后发制人", "万剑归一"]

    def decide(self, ctx: CombatContext) -> SkillDecision:
        if ctx.monster_count > 1:
            return SkillDecision(
                skill_name="破釜沉舟",
                keywords=["破釜沉舟", "破釜"],
                fallback_coord=COORD_AOE_SKILL_FALLBACK,
                description=f"大唐多怪群攻 (count={ctx.monster_count})，施放破釜沉舟",
            )
        return SkillDecision(
            skill_name="横扫千军",
            keywords=["横扫千军", "横扫"],
            fallback_coord=COORD_SINGLE_SKILL_FALLBACK,
            description="大唐单体三刀爆发，施放横扫千军",
        )


class HuashengStrategy(BaseSectStrategy):
    """化生寺 - Healer & Buffer:
    - Multi-monster (>1) -> 唧唧歪歪 (AoE magic damage)
    - Single monster (<=1) or low HP -> 推气过宫 (Group heal)
    """
    sect_name = "化生寺"
    role_category = "healer"
    known_skills = ["唧唧歪歪", "推气过宫", "金刚护体", "一苇渡江", "我佛慈悲", "一元复始"]

    def decide(self, ctx: CombatContext) -> SkillDecision:
        if ctx.variables.get("need_heal") or (ctx.monster_count <= 1 and ctx.variables.get("prefer_sustain")):
            return SkillDecision(
                skill_name="推气过宫",
                keywords=["推气过宫", "推气"],
                fallback_coord=COORD_SINGLE_SKILL_FALLBACK,
                target_type="ally",
                description="化生寺群体加血，施放推气过宫",
            )
        return SkillDecision(
            skill_name="唧唧歪歪",
            keywords=["唧唧歪歪", "唧唧"],
            fallback_coord=COORD_AOE_SKILL_FALLBACK,
            description=f"化生寺日常群秒 (count={ctx.monster_count})，施放唧唧歪歪",
        )


class DifuStrategy(BaseSectStrategy):
    """阴曹地府 - Support & Debuffer:
    - Multi-monster (>1) -> 阎罗令 (AoE fixed damage + poison)
    - Single monster (<=1) -> 六道轮回 (Reduce enemy physical defense)
    """
    sect_name = "阴曹地府"
    role_category = "support"
    known_skills = ["阎罗令", "六道轮回", "尸腐毒", "幽冥鬼眼", "锁魂判官"]

    def decide(self, ctx: CombatContext) -> SkillDecision:
        if ctx.monster_count > 1:
            return SkillDecision(
                skill_name="阎罗令",
                keywords=["阎罗令", "阎罗"],
                fallback_coord=COORD_AOE_SKILL_FALLBACK,
                description=f"地府固伤群秒 (count={ctx.monster_count})，施放阎罗令",
            )
        return SkillDecision(
            skill_name="六道轮回",
            keywords=["六道轮回", "六道"],
            fallback_coord=COORD_SINGLE_SKILL_FALLBACK,
            description="地府群体降防辅攻，施放六道轮回",
        )


class ShituolingStrategy(BaseSectStrategy):
    """狮驼岭 - Physical AoE Burst:
    - Multi-monster (>1) -> 鹰击 (Flying AoE burst strike)
    - Single monster (<=1) -> 狮搏 (Single target bite)
    """
    sect_name = "狮驼岭"
    role_category = "physical_dps"
    known_skills = ["鹰击", "狮搏", "象形", "变身", "连环击", "逆势镇魔"]

    def decide(self, ctx: CombatContext) -> SkillDecision:
        if ctx.monster_count > 1:
            return SkillDecision(
                skill_name="鹰击",
                keywords=["鹰击"],
                fallback_coord=COORD_AOE_SKILL_FALLBACK,
                description=f"狮驼岭多目标爆发 (count={ctx.monster_count})，施放鹰击",
            )
        return SkillDecision(
            skill_name="狮搏",
            keywords=["狮搏"],
            fallback_coord=COORD_SINGLE_SKILL_FALLBACK,
            description="狮驼岭单体破防点杀，施放狮搏",
        )


class XiaoleiyinStrategy(BaseSectStrategy):
    """小雷音 - Magic Burst:
    - Multi-monster (>1) -> 一念成佛 (Multi-target magic AoE)
    - Single monster (<=1) -> 一劫为魔 (Single target high burst magic)
    """
    sect_name = "小雷音"
    role_category = "magic_dps"
    known_skills = ["一念成佛", "一劫为魔", "梵音破", "问心", "迷心障", "问天一战"]

    def decide(self, ctx: CombatContext) -> SkillDecision:
        if ctx.monster_count > 1:
            return SkillDecision(
                skill_name="一念成佛",
                keywords=["一念成佛", "成佛"],
                fallback_coord=COORD_AOE_SKILL_FALLBACK,
                description=f"小雷音多目标佛珠爆发 (count={ctx.monster_count})，施放一念成佛",
            )
        return SkillDecision(
            skill_name="一劫为魔",
            keywords=["一劫为魔", "为魔"],
            fallback_coord=COORD_SINGLE_SKILL_FALLBACK,
            description="小雷音单体魔珠收割，施放一劫为魔",
        )


class HuaguoshanStrategy(BaseSectStrategy):
    """花果山 - Physical Burst:
    - Multi-monster (>1) -> 泼天乱棒 (Multi-target physical strike)
    - Single monster (<=1) -> 当头一棒 (Heavy single target physical smash)
    """
    sect_name = "花果山"
    role_category = "physical_dps"
    known_skills = ["泼天乱棒", "当头一棒", "千变万化", "铜头铁臂", "如意金箍棒", "身外化身"]

    def decide(self, ctx: CombatContext) -> SkillDecision:
        if ctx.monster_count > 1:
            return SkillDecision(
                skill_name="泼天乱棒",
                keywords=["泼天乱棒", "泼天"],
                fallback_coord=COORD_AOE_SKILL_FALLBACK,
                description=f"花果山乱棒群攻 (count={ctx.monster_count})，施放泼天乱棒",
            )
        return SkillDecision(
            skill_name="当头一棒",
            keywords=["当头一棒", "当头"],
            fallback_coord=COORD_SINGLE_SKILL_FALLBACK,
            description="花果山强力单体暴击，施放当头一棒",
        )


class SectCombatRegistry:
    """Registry maintaining sect strategies with automatic detection and dispatch."""

    def __init__(self):
        self._strategies: Dict[str, BaseSectStrategy] = {}
        self._default_sect: str = "月宫"
        self._register_defaults()

    def _register_defaults(self):
        defaults = [
            MoonPalaceStrategy(),
            MowangStrategy(),
            FangcunStrategy(),
            PutuoStrategy(),
            DragonPalaceStrategy(),
            DatingStrategy(),
            HuashengStrategy(),
            DifuStrategy(),
            ShituolingStrategy(),
            XiaoleiyinStrategy(),
            HuaguoshanStrategy(),
        ]
        for s in defaults:
            self.register(s)

    def register(self, strategy: BaseSectStrategy) -> None:
        self._strategies[strategy.sect_name] = strategy

    def get(self, sect_name: str) -> Optional[BaseSectStrategy]:
        return self._strategies.get(sect_name)

    def list_sects(self) -> List[str]:
        return list(self._strategies.keys())

    def detect_sect_from_items(self, items: list) -> Optional[str]:
        """Auto-detect sect by matching visible skill labels on the screen/skill wheel."""
        if not items:
            return None
        texts = [getattr(it, "text", str(it)) for it in items]
        for sect_name, strat in self._strategies.items():
            for skill in strat.known_skills:
                if any(skill in t for t in texts):
                    logger.debug(f"[SectRegistry] Auto-detected sect [{sect_name}] via skill [{skill}]")
                    return sect_name
        return None

    def resolve_strategy(
        self,
        sect_hint: Optional[str] = None,
        items: Optional[list] = None,
    ) -> BaseSectStrategy:
        """Resolve the appropriate strategy based on hint, detection, or fallback."""
        if sect_hint and sect_hint in self._strategies:
            return self._strategies[sect_hint]

        if items:
            detected = self.detect_sect_from_items(items)
            if detected and detected in self._strategies:
                return self._strategies[detected]

        return self._strategies.get(self._default_sect, MoonPalaceStrategy())


class PetCombatEngine:
    """Engine handling pet (召唤灵/宠物) turn decisions."""

    @staticmethod
    def decide(pet_type: str = "attack", monster_count: int = 1) -> PetDecision:
        p_type = pet_type.lower()
        if p_type in ("magic", "fachong", "spell", "法宠"):
            return PetDecision(
                pet_type="magic",
                action_name="法术",
                keywords=["法术", "群法", "泰山压顶", "奔雷咒", "地狱烈火", "水漫金山"],
                fallback_coord=COORD_SPELL_MENU_BTN,
                description=f"法宠回合 (monsters={monster_count})，施放群体/单体法术攻击",
            )
        elif p_type in ("blood", "speed", "peisu", "血宠", "配速"):
            return PetDecision(
                pet_type="blood",
                action_name="防御",
                keywords=["防御"],
                fallback_coord=COORD_BOTTOM_ATTACK,
                description="血宠/配速回合，执行防御保全战力",
            )
        else:
            return PetDecision(
                pet_type="attack",
                action_name="攻击",
                keywords=["攻击"],
                fallback_coord=COORD_BOTTOM_ATTACK,
                description="物理攻宠回合，执行常规普通攻击",
            )


# Global default registry instance
global_sect_registry = SectCombatRegistry()
