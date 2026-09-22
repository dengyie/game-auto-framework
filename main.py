"""
Main CLI & Server Entrypoint for game-auto-framework.
Usage:
    python main.py server --host 0.0.0.0 --port 8000
    python main.py run --plugin mhxy_mobile --pipeline daily_shimen --device virtual
    python main.py test
"""

from __future__ import annotations
import argparse
import sys
import uvicorn
from loguru import logger

from core.device.factory import DeviceFactory
from plugins.mhxy_mobile.plugin import MHXYMobilePlugin
from scheduler.dag import PipelineStatus


def run_cli_pipeline(plugin_id: str, pipeline_name: str, device_type: str, serial: str | None) -> None:
    logger.info(f"Starting standalone pipeline [{pipeline_name}] with plugin [{plugin_id}] on [{device_type}]")
    device = DeviceFactory.create(device_type=device_type, serial=serial)
    if not device.connect():
        logger.error(f"Could not connect to device [{device.name}]")
        sys.exit(1)

    if plugin_id == "mhxy_mobile":
        plugin = MHXYMobilePlugin(device=device)
    else:
        logger.error(f"Unknown plugin [{plugin_id}]")
        sys.exit(1)

    logger.info(f"Executing pipeline [{pipeline_name}] step-by-step...")
    step_count = 0
    while step_count < 100:
        status = plugin.run_pipeline_step(pipeline_name)
        step_count += 1
        logger.debug(f"Step {step_count}: status = {status.value}")
        if status in (PipelineStatus.COMPLETED, PipelineStatus.FAILED, PipelineStatus.TIMEOUT):
            logger.info(f"Execution terminated with: {status.value}")
            break

    device.disconnect()


def main() -> None:
    parser = argparse.ArgumentParser(description="game-auto-framework Central Controller")
    subparsers = parser.add_subparsers(dest="subcommand", help="Available subcommands")

    # Subcommand: server (FastAPI daemon for VPS)
    server_parser = subparsers.add_parser("server", help="Run FastAPI daemon for VPS remote invocation")
    server_parser.add_argument("--host", default="0.0.0.0", help="Host IP to bind (default: 0.0.0.0)")
    server_parser.add_argument("--port", type=int, default=8000, help="Port to bind (default: 8000)")
    server_parser.add_argument("--reload", action="store_true", help="Auto-reload on code change")

    # Subcommand: run (Standalone CLI execution)
    run_parser = subparsers.add_parser("run", help="Run a specific game pipeline directly")
    run_parser.add_argument("--plugin", default="mhxy_mobile", help="Plugin identifier")
    run_parser.add_argument("--pipeline", default="daily_shimen", help="Pipeline name")
    run_parser.add_argument("--device", default="auto", help="Device type: auto, adb, virtual, windows, macos")
    run_parser.add_argument("--serial", default=None, help="ADB host:port or target serial")

    # Subcommand: test (Self-diagnostic unit tests)
    subparsers.add_parser("test", help="Run pytest suite")

    args = parser.parse_args()

    if args.subcommand == "server":
        logger.info(f"Starting VPS API Server on {args.host}:{args.port}")
        uvicorn.run("server.app:app", host=args.host, port=args.port, reload=args.reload)
    elif args.subcommand == "run":
        run_cli_pipeline(args.plugin, args.pipeline, args.device, args.serial)
    elif args.subcommand == "test":
        import pytest
        sys.exit(pytest.main(["tests"]))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
