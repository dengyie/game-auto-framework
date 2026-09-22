"""
Base Game Plugin Specification.
Defines plugin lifecycle, pipeline loading, custom operator registration, and execution.
"""

from __future__ import annotations
import abc
import json
from pathlib import Path
from typing import Any, Dict, Optional
from loguru import logger

from core.device.base import BaseDevice
from scheduler.dag import DAGPipeline, PipelineContext, PipelineStatus


class BaseGamePlugin(abc.ABC):
    """Abstract base class for all game-specific automation packages."""

    def __init__(self, plugin_dir: Path, device: BaseDevice) -> None:
        self.plugin_dir = plugin_dir
        self.device = device
        self.manifest: Dict[str, Any] = self._load_json(plugin_dir / "manifest.json")
        self.plugin_id = self.manifest.get("id", plugin_dir.name)
        self.coordinates: Dict[str, Any] = self._load_json(plugin_dir / "config" / "coordinates.json")
        self.pipelines: Dict[str, DAGPipeline] = {}
        self.context = PipelineContext(device=self.device, controller=self.device.controller)

        # Bootstrap pipeline definitions
        self._load_all_pipelines()
        # Register plugin-specific recognition and action functions
        self.register_custom_operators(self.context)

    def _load_json(self, path: Path) -> Dict[str, Any]:
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def _load_all_pipelines(self) -> None:
        pipelines_dir = self.plugin_dir / "pipelines"
        if not pipelines_dir.exists():
            return
        for json_file in pipelines_dir.glob("*.json"):
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                pipeline = DAGPipeline.from_dict(data)
                self.pipelines[pipeline.name] = pipeline
                logger.info(f"Loaded pipeline [{pipeline.name}] for plugin [{self.plugin_id}]")
            except Exception as e:
                logger.error(f"Failed to load pipeline {json_file}: {e}")

    @abc.abstractmethod
    def register_custom_operators(self, context: PipelineContext) -> None:
        """Subclasses register domain-specific CV, OCR, AI answer, and combat operators."""
        pass

    def get_pipeline(self, name: str) -> Optional[DAGPipeline]:
        return self.pipelines.get(name)

    def run_pipeline_step(self, pipeline_name: str) -> PipelineStatus:
        """Execute a single tick of the requested pipeline."""
        pipeline = self.get_pipeline(pipeline_name)
        if not pipeline:
            logger.error(f"Pipeline [{pipeline_name}] not found in plugin [{self.plugin_id}]")
            return PipelineStatus.FAILED

        if pipeline.status == PipelineStatus.IDLE:
            pipeline.start()

        # Capture current frame from device
        try:
            frame = self.device.screencap()
        except Exception as e:
            logger.warning(f"Device capture failed during pipeline step: {e}")
            frame = None

        return pipeline.tick(self.context, frame=frame)
