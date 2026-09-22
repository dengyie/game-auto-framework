"""
Declarative DAG Pipeline State Machine.
Inspired by MaaFramework v2 & Alas, featuring conditional branching,
dynamic interrupt handlers (anti-bot popups), and timeout handling.
"""

from __future__ import annotations
import time
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set
from pydantic import BaseModel, Field
from loguru import logger


class PipelineStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    TIMEOUT = "timeout"
    FAILED = "failed"
    ESCAPING = "escaping"


class NodeRecognition(BaseModel):
    type: str = "custom"  # "template", "ocr", "custom", "always"
    target: Optional[str] = None
    roi: Optional[List[int]] = None  # [x, y, w, h]
    threshold: float = 0.8
    custom_func: Optional[str] = None


class NodeAction(BaseModel):
    type: str = "none"  # "click", "swipe", "key", "wait", "custom", "none"
    target_pos: Optional[List[int]] = None  # [x, y]
    duration: float = 0.0
    custom_func: Optional[str] = None


class DAGNode(BaseModel):
    name: str
    recognition: NodeRecognition
    action: NodeAction = Field(default_factory=NodeAction)
    next_nodes: List[str] = Field(default_factory=list, alias="next")
    timeout_sec: float = 15.0
    is_interrupt: bool = False
    is_terminal: bool = False


class PipelineContext:
    """Runtime execution context holding state variables and custom operators."""

    def __init__(self) -> None:
        self.variables: Dict[str, Any] = {}
        self.recognition_handlers: Dict[str, Callable[..., bool]] = {}
        self.action_handlers: Dict[str, Callable[..., None]] = {}
        self.history: List[str] = []

    def register_recognition(self, name: str, handler: Callable[..., bool]) -> None:
        self.recognition_handlers[name] = handler

    def register_action(self, name: str, handler: Callable[..., None]) -> None:
        self.action_handlers[name] = handler


class DAGPipeline:
    """Executes a Directed Acyclic Graph / Finite State Machine workflow."""

    def __init__(self, name: str, nodes: List[DAGNode], entry_node: str) -> None:
        self.name = name
        self.nodes: Dict[str, DAGNode] = {node.name: node for node in nodes}
        self.entry_node_name = entry_node
        self.current_node_name = entry_node
        self.status = PipelineStatus.IDLE
        self.node_entered_time = 0.0

        # Separate regular nodes from high-priority interrupts (anti-bot)
        self.interrupt_nodes: List[DAGNode] = [n for n in nodes if n.is_interrupt]

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
        logger.info(f"Pipeline [{self.name}] started at entry node [{self.entry_node_name}]")

    def _eval_recognition(self, node: DAGNode, ctx: PipelineContext, frame: Any) -> bool:
        rec = node.recognition
        if rec.type == "always":
            return True
        if rec.type == "custom" and rec.custom_func:
            handler = ctx.recognition_handlers.get(rec.custom_func)
            if handler:
                return handler(ctx, frame, rec)
        return False

    def _execute_action(self, node: DAGNode, ctx: PipelineContext) -> None:
        act = node.action
        if act.type == "custom" and act.custom_func:
            handler = ctx.action_handlers.get(act.custom_func)
            if handler:
                handler(ctx, act)
        elif act.type == "wait" and act.duration > 0:
            time.sleep(act.duration)

    def tick(self, ctx: PipelineContext, frame: Any = None) -> PipelineStatus:
        """Single execution tick. Priority: 1) Global Interrupts, 2) Current/Next DAG branches."""
        if self.status != PipelineStatus.RUNNING:
            return self.status

        now = time.time()

        # 1. Check Global High-Priority Interrupts (e.g. Anti-Bot Captcha Popups)
        for interrupt in self.interrupt_nodes:
            if self._eval_recognition(interrupt, ctx, frame):
                logger.warning(f"Interrupt triggered: [{interrupt.name}]")
                self._execute_action(interrupt, ctx)
                ctx.history.append(f"INTERRUPT:{interrupt.name}")
                # Reset current node timeout when interrupt handled
                self.node_entered_time = now
                return self.status

        current_node = self.nodes.get(self.current_node_name)
        if not current_node:
            self.status = PipelineStatus.FAILED
            logger.error(f"Node [{self.current_node_name}] not found in pipeline")
            return self.status

        # 2. Check Timeout on Current Node
        if now - self.node_entered_time > current_node.timeout_sec:
            logger.warning(f"Node [{current_node.name}] timed out (> {current_node.timeout_sec}s)")
            self.status = PipelineStatus.TIMEOUT
            return self.status

        # 3. Check Current Node Recognition & Action
        if self._eval_recognition(current_node, ctx, frame):
            self._execute_action(current_node, ctx)
            ctx.history.append(current_node.name)

            if current_node.is_terminal:
                self.status = PipelineStatus.COMPLETED
                logger.info(f"Pipeline [{self.name}] completed at terminal node [{current_node.name}]")
                return self.status

            # Transition to candidate next nodes
            for next_name in current_node.next_nodes:
                next_node = self.nodes.get(next_name)
                if next_node and self._eval_recognition(next_node, ctx, frame):
                    self.current_node_name = next_name
                    self.node_entered_time = now
                    logger.debug(f"Transitioned: [{current_node.name}] -> [{next_name}]")
                    return self.status

            # If next_nodes specified but none matched yet, stay on current node and await next tick
            if current_node.next_nodes:
                self.current_node_name = current_node.next_nodes[0]
                self.node_entered_time = now

        return self.status
