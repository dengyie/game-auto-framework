"""
Declarative DAG Pipeline State Machine.
Inspired by MaaFramework v2 & Alas, featuring conditional branching,
dynamic interrupt handlers (anti-bot popups), context flow, and watchdog integration.
"""

from __future__ import annotations

import time
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
from pydantic import BaseModel, Field
from loguru import logger

from core.cv.matcher import TemplateMatcher
from core.cv.battle import BattleDetector
from core.ocr.engine import OCREngine
from scheduler.escape import SelfHealingEscapeManager


class PipelineStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    TIMEOUT = "timeout"
    FAILED = "failed"
    ESCAPING = "escaping"


class NodeRecognition(BaseModel):
    type: str = "custom"  # "template", "ocr", "battle", "custom", "always"
    target: Optional[str] = None
    roi: Optional[List[int]] = None  # [x, y, w, h]
    threshold: float = 0.8
    custom_func: Optional[str] = None
    condition: Optional[str] = None  # Optional expression evaluating against ctx.variables


class NodeAction(BaseModel):
    type: str = "none"  # "click", "swipe", "key", "wait", "custom", "set_var", "none"
    target_pos: Optional[List[int]] = None  # [x, y]
    swipe_end: Optional[List[int]] = None  # [x, y]
    key_code: Optional[str] = None  # "ESC", "BACK", etc.
    duration: float = 0.0
    var_key: Optional[str] = None
    var_value: Optional[Any] = None
    custom_func: Optional[str] = None


class NodeBranch(BaseModel):
    condition: str  # Context variable expression, e.g. "shimen_rounds >= 20"
    next: str


class DAGNode(BaseModel):
    name: str
    recognition: NodeRecognition
    action: NodeAction = Field(default_factory=NodeAction)
    next_nodes: List[str] = Field(default_factory=list, alias="next")
    branches: List[NodeBranch] = Field(default_factory=list)
    timeout_sec: float = 15.0
    is_interrupt: bool = False
    is_terminal: bool = False
    max_retries: int = 15


class PipelineContext:
    """Runtime execution context holding state variables, device drivers, and custom operators."""

    def __init__(
        self,
        device: Optional[Any] = None,
        controller: Optional[Any] = None,
        escape_manager: Optional[SelfHealingEscapeManager] = None,
    ) -> None:
        self.device = device
        self.controller = controller
        self.escape_manager = escape_manager
        self.variables: Dict[str, Any] = {}
        self.recognition_handlers: Dict[str, Callable[..., bool]] = {}
        self.action_handlers: Dict[str, Callable[..., None]] = {}
        self.history: List[str] = []

    def register_recognition(self, name: str, handler: Callable[..., bool]) -> None:
        self.recognition_handlers[name] = handler

    def register_action(self, name: str, handler: Callable[..., None]) -> None:
        self.action_handlers[name] = handler

    def eval_condition(self, expr: str) -> bool:
        """Safely evaluate simple variable condition expressions against context variables."""
        if not expr:
            return True
        try:
            # Provide self.variables as local namespace for the expression
            safe_globals = {"__builtins__": {}}
            return bool(eval(expr, safe_globals, self.variables))
        except Exception as e:
            logger.debug(f"Condition evaluation error for '{expr}': {e}")
            return False


class DAGPipeline:
    """Executes a Directed Acyclic Graph / Finite State Machine workflow with perception and self-healing."""

    def __init__(self, name: str, nodes: List[DAGNode], entry_node: str) -> None:
        self.name = name
        self.nodes: Dict[str, DAGNode] = {node.name: node for node in nodes}
        self.entry_node_name = entry_node
        self.current_node_name = entry_node
        self.status = PipelineStatus.IDLE
        self.node_entered_time = 0.0
        self.retry_count = 0

        # Separate regular nodes from high-priority interrupts (anti-bot)
        self.interrupt_nodes: List[DAGNode] = [n for n in nodes if n.is_interrupt]
        self._battle_detector = BattleDetector()

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> DAGPipeline:
        name = data.get("name", "unnamed_pipeline")
        raw_nodes = data.get("nodes", [])
        nodes = [DAGNode.model_validate(n) for n in raw_nodes]
        entry = data.get("entry", nodes[0].name if nodes else "")
        return cls(name, nodes, entry)

    def start(self) -> None:
        self.status = PipelineStatus.RUNNING
        self.current_node_name = self.entry_node_name
        self.node_entered_time = time.time()
        self.retry_count = 0
        logger.info(f"Pipeline [{self.name}] started at entry node [{self.entry_node_name}]")

    def _eval_recognition(self, node: DAGNode, ctx: PipelineContext, frame: Any) -> bool:
        rec = node.recognition

        # Check variable precondition if specified
        if rec.condition and not ctx.eval_condition(rec.condition):
            return False

        if rec.type == "always":
            return True

        if rec.type == "battle":
            if frame is not None and self._battle_detector.is_in_battle(frame):
                return True
            return False

        if rec.type == "template" and rec.target and frame is not None:
            roi_tuple = tuple(rec.roi) if rec.roi else None
            match_res = TemplateMatcher.match(frame, rec.target, threshold=rec.threshold, roi=roi_tuple)
            if match_res.found:
                ctx.variables["last_match_point"] = match_res.center
                ctx.variables["last_match_bbox"] = match_res.bbox
                return True
            return False

        if rec.type == "ocr" and rec.target and frame is not None:
            roi_tuple = tuple(rec.roi) if rec.roi else None
            ocr_res = OCREngine.get_instance().find_text(frame, rec.target, roi=roi_tuple, threshold=rec.threshold)
            if ocr_res is not None:
                ctx.variables["last_text_point"] = ocr_res.center
                ctx.variables["last_text_bbox"] = ocr_res.bbox
                ctx.variables["last_text_raw"] = ocr_res.text
                return True
            return False

        if rec.type == "custom" and rec.custom_func:
            handler = ctx.recognition_handlers.get(rec.custom_func)
            if handler:
                return handler(ctx, frame, rec)

        return False

    def _execute_action(self, node: DAGNode, ctx: PipelineContext) -> None:
        act = node.action
        if act.type == "none":
            return

        if act.type == "custom" and act.custom_func:
            handler = ctx.action_handlers.get(act.custom_func)
            if handler:
                handler(ctx, act)
            return

        if act.type == "wait" and act.duration > 0:
            time.sleep(act.duration)
            return

        if act.type == "set_var" and act.var_key:
            ctx.variables[act.var_key] = act.var_value
            return

        if act.type == "click":
            target_pos = None
            if act.target_pos:
                target_pos = (act.target_pos[0], act.target_pos[1])
            elif "last_match_point" in ctx.variables:
                target_pos = ctx.variables["last_match_point"]
            elif "last_text_point" in ctx.variables:
                target_pos = ctx.variables["last_text_point"]

            if target_pos:
                cx, cy = target_pos
                if ctx.controller:
                    ctx.controller.human_click(cx, cy)
                elif ctx.device:
                    ctx.device.click(cx, cy)
                else:
                    logger.debug(f"Simulated click at ({cx}, {cy})")
            return

        if act.type == "swipe" and act.target_pos and act.swipe_end:
            sx, sy = act.target_pos
            ex, ey = act.swipe_end
            if ctx.controller:
                ctx.controller.human_swipe(sx, sy, ex, ey)
            elif ctx.device:
                ctx.device.swipe(sx, sy, ex, ey)
            return

        if act.type == "key" and act.key_code and ctx.device:
            # Send key code if device supports it
            if hasattr(ctx.device, "key_event"):
                ctx.device.key_event(act.key_code)

    def tick(self, ctx: PipelineContext, frame: Any = None) -> PipelineStatus:
        """Single execution tick. Priority: 1) Watchdog, 2) Interrupts, 3) DAG evaluation."""
        if self.status != PipelineStatus.RUNNING:
            return self.status

        now = time.time()

        # 1. Heartbeat Watchdog & Self-Healing Escape
        if ctx.escape_manager:
            escape_level = ctx.escape_manager.check_and_heal()
            if escape_level is not None:
                ctx.history.append(f"ESCAPE:{escape_level.name}")
                self.node_entered_time = now

        # 2. Check Global High-Priority Interrupts (e.g. Anti-Bot Captcha Popups)
        for interrupt in self.interrupt_nodes:
            if self._eval_recognition(interrupt, ctx, frame):
                logger.warning(f"Interrupt triggered: [{interrupt.name}]")
                self._execute_action(interrupt, ctx)
                ctx.history.append(f"INTERRUPT:{interrupt.name}")
                if ctx.escape_manager:
                    ctx.escape_manager.record_progress()
                self.node_entered_time = now
                return self.status

        current_node = self.nodes.get(self.current_node_name)
        if not current_node:
            self.status = PipelineStatus.FAILED
            logger.error(f"Node [{self.current_node_name}] not found in pipeline")
            return self.status

        # 3. Check Timeout on Current Node
        if now - self.node_entered_time > current_node.timeout_sec:
            logger.warning(f"Node [{current_node.name}] timed out (> {current_node.timeout_sec}s)")
            self.status = PipelineStatus.TIMEOUT
            return self.status

        # 4. Check Current Node Recognition & Action
        if self._eval_recognition(current_node, ctx, frame):
            self._execute_action(current_node, ctx)
            ctx.history.append(current_node.name)
            if ctx.escape_manager:
                ctx.escape_manager.record_progress()

            if current_node.is_terminal:
                self.status = PipelineStatus.COMPLETED
                logger.info(f"Pipeline [{self.name}] completed at terminal node [{current_node.name}]")
                return self.status

            # Check conditional dynamic branches first
            branch_transitioned = False
            for branch in current_node.branches:
                if ctx.eval_condition(branch.condition):
                    next_node = self.nodes.get(branch.next)
                    if next_node:
                        self.current_node_name = branch.next
                        self.node_entered_time = now
                        self.retry_count = 0
                        logger.debug(f"Branch Transitioned: [{current_node.name}] -> [{branch.next}] via '{branch.condition}'")
                        branch_transitioned = True
                        break

            if branch_transitioned:
                return self.status

            # Standard candidate next transitions
            for next_name in current_node.next_nodes:
                next_node = self.nodes.get(next_name)
                if next_node and self._eval_recognition(next_node, ctx, frame):
                    self.current_node_name = next_name
                    self.node_entered_time = now
                    self.retry_count = 0
                    logger.debug(f"Transitioned: [{current_node.name}] -> [{next_name}]")
                    return self.status

            # If default next_nodes specified, advance to first next node
            if current_node.next_nodes:
                self.current_node_name = current_node.next_nodes[0]
                self.node_entered_time = now
                self.retry_count = 0

        return self.status
