"""
Game Plugin Registry and Dynamic Factory.
Manages automatic discovery, registration, and instantiation of game plugins.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Type
from loguru import logger

from core.device.base import BaseDevice
from plugins.base import BaseGamePlugin


class GamePluginRegistry:
    """Central registry and dynamic factory for all game plugins."""

    _registry: Dict[str, Type[BaseGamePlugin]] = {}
    _manifests: Dict[str, Dict[str, Any]] = {}
    _discovered: bool = False

    @classmethod
    def register(cls, plugin_id: str):
        """Decorator to explicitly register a plugin class."""
        def decorator(subclass: Type[BaseGamePlugin]):
            cls._registry[plugin_id] = subclass
            return subclass
        return decorator

    @classmethod
    def discover_plugins(cls, plugins_dir: Optional[Path] = None) -> None:
        """Scan plugins directory, inspect manifests, and auto-load plugin modules."""
        if cls._discovered:
            return

        base_dir = plugins_dir or (Path(__file__).parent)
        if not base_dir.exists():
            return

        for item in sorted(base_dir.iterdir()):
            if not item.is_dir() or item.name.startswith(("_", ".")):
                continue

            manifest_path = item / "manifest.json"
            if not manifest_path.exists():
                continue

            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    manifest = json.load(f)
                plugin_id = manifest.get("id", item.name)
                cls._manifests[plugin_id] = manifest

                # Dynamically import plugin module (e.g. plugins.mhxy_mobile.plugin)
                module_name = f"plugins.{item.name}.plugin"
                mod = importlib.import_module(module_name)

                # Look for BaseGamePlugin subclass in the module
                for attr_name in dir(mod):
                    attr = getattr(mod, attr_name)
                    if (
                        isinstance(attr, type)
                        and issubclass(attr, BaseGamePlugin)
                        and attr is not BaseGamePlugin
                    ):
                        cls._registry[plugin_id] = attr
                        logger.debug(f"Discovered and registered game plugin: [{plugin_id}] -> {attr_name}")
                        break
            except Exception as e:
                logger.error(f"Failed to auto-discover plugin from {item}: {e}")

        cls._discovered = True

    @classmethod
    def get_plugin_class(cls, plugin_id: str) -> Optional[Type[BaseGamePlugin]]:
        cls.discover_plugins()
        return cls._registry.get(plugin_id)

    @classmethod
    def create(cls, plugin_id: str, device: BaseDevice, **kwargs: Any) -> BaseGamePlugin:
        cls.discover_plugins()
        plugin_cls = cls._registry.get(plugin_id)
        if not plugin_cls:
            available = list(cls._registry.keys())
            raise ValueError(f"Game plugin [{plugin_id}] is not registered. Available: {available}")
        return plugin_cls(device=device, **kwargs)

    @classmethod
    def list_plugins(cls) -> List[Dict[str, Any]]:
        cls.discover_plugins()
        result: List[Dict[str, Any]] = []
        for pid, meta in cls._manifests.items():
            # Scan pipeline directory for pipeline names
            pipelines: List[str] = []
            plugin_dir = Path(__file__).parent / pid
            pipelines_dir = plugin_dir / "pipelines"
            if pipelines_dir.exists():
                for pf in sorted(pipelines_dir.glob("*.json")):
                    try:
                        with open(pf, "r", encoding="utf-8") as f:
                            pdata = json.load(f)
                        pipelines.append(pdata.get("name", pf.stem))
                    except Exception:
                        pipelines.append(pf.stem)
            elif "pipelines" in meta:
                pipelines = [Path(p).stem for p in meta.get("pipelines", [])]

            result.append({
                "id": pid,
                "name": meta.get("name", pid),
                "version": meta.get("version", "1.0.0"),
                "description": meta.get("description", ""),
                "resolution": meta.get("resolution", {"width": 1280, "height": 720}),
                "aliases": meta.get("aliases", {}),
                "pipelines": pipelines,
            })
        return result

    @classmethod
    def get_pipelines(cls, plugin_id: str) -> List[Dict[str, Any]]:
        """List detailed pipeline information for a specific plugin."""
        cls.discover_plugins()
        plugin_dir = Path(__file__).parent / plugin_id
        pipelines_dir = plugin_dir / "pipelines"
        results: List[Dict[str, Any]] = []
        if not pipelines_dir.exists():
            return results

        for pf in sorted(pipelines_dir.glob("*.json")):
            try:
                with open(pf, "r", encoding="utf-8") as f:
                    pdata = json.load(f)
                results.append({
                    "name": pdata.get("name", pf.stem),
                    "entry": pdata.get("entry", ""),
                    "node_count": len(pdata.get("nodes", [])),
                    "file": pf.name,
                })
            except Exception as e:
                logger.warning(f"Failed to read pipeline {pf}: {e}")
        return results
