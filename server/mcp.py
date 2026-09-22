"""
Model Context Protocol (MCP) Server for game-auto-framework.
Exposes game automation, cluster orchestration, account matrix, and perception
capabilities to AI Agents (Claude, ZCode, Cursor) via standard JSON-RPC 2.0 stdio transport.
"""

from __future__ import annotations

import base64
import json
import sys
from typing import Any, Dict, List, Optional
from loguru import logger

from core.device.factory import DeviceFactory
from plugins.registry import GamePluginRegistry
from cluster.instance_pool import InstancePool, InstanceStatus
from cluster.proxy import ProxyManager
from cluster.account import AccountMatrix
from cluster.supervisor import ClusterSupervisor


# =====================================================================
# Tool Implementations (Shared Business Logic)
# =====================================================================

def tool_list_instances() -> Dict[str, Any]:
    """List all registered device instances in the cluster with diagnostic health metrics."""
    pool = InstancePool.get_pool()
    instances = [inst.get_health() for inst in pool.list_instances()]
    return {
        "total": len(instances),
        "instances": instances,
    }


def tool_get_screenshot(instance_id: Optional[str] = None) -> Dict[str, Any]:
    """Capture real-time screenshot from a target instance or virtual device."""
    pool = InstancePool.get_pool()
    dev = None
    target_id = instance_id or "default"

    if instance_id:
        inst = pool.get_instance(instance_id)
        if not inst:
            return {"error": f"Instance [{instance_id}] not found in cluster pool."}
        try:
            raw_bytes = inst.screencap()
        except Exception as e:
            return {"error": f"Failed to capture screencap from [{instance_id}]: {e}"}
    else:
        # Fallback to first available instance or ad-hoc device
        instances = pool.list_instances()
        if instances:
            try:
                raw_bytes = instances[0].screencap()
                target_id = instances[0].instance_id
            except Exception as e:
                return {"error": f"Failed to capture from cluster instance: {e}"}
        else:
            try:
                vdev = DeviceFactory.create("virtual")
                vdev.connect()
                raw_bytes = vdev.screencap()
                target_id = "virtual_adhoc"
            except Exception as e:
                return {"error": f"Failed to capture virtual screencap: {e}"}

    b64_data = base64.b64encode(raw_bytes).decode("ascii")
    return {
        "instance_id": target_id,
        "format": "jpeg",
        "size_bytes": len(raw_bytes),
        "base64_image": b64_data[:64] + "...[truncated]",
        "base64_full": b64_data,
    }


def tool_start_routine(
    routine_name: str,
    pipelines: List[str],
    instance_id: Optional[str] = None,
    plugin: str = "mhxy_mobile",
    variables: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Start an ordered routine task chain on a target instance or cluster pool."""
    pool = InstancePool.get_pool()
    vars_dict = variables or {}

    if instance_id:
        inst = pool.get_instance(instance_id)
        if not inst:
            return {"error": f"Instance [{instance_id}] not found."}
        success = inst.start_routine(
            routine_name=routine_name,
            pipelines=pipelines,
            variables=vars_dict,
            plugin_id=plugin,
        )
        if not success:
            return {"error": f"Instance [{instance_id}] failed to start routine (status: {inst.status.value})."}
        return {
            "status": "started",
            "instance_id": instance_id,
            "routine": routine_name,
            "pipelines": pipelines,
            "plugin": plugin,
        }
    else:
        # Allocate an idle instance
        inst = pool.allocate_instance()
        if not inst:
            return {"error": "No IDLE instance available in cluster pool."}
        success = inst.start_routine(
            routine_name=routine_name,
            pipelines=pipelines,
            variables=vars_dict,
            plugin_id=plugin,
        )
        return {
            "status": "started",
            "allocated_instance_id": inst.instance_id,
            "routine": routine_name,
            "pipelines": pipelines,
            "plugin": plugin,
        }


def tool_stop_task(instance_id: Optional[str] = None) -> Dict[str, Any]:
    """Stop active task/routine on a specific instance or all cluster instances."""
    pool = InstancePool.get_pool()
    if instance_id:
        inst = pool.get_instance(instance_id)
        if not inst:
            return {"error": f"Instance [{instance_id}] not found."}
        inst.stop()
        return {"status": "stopped", "instance_id": instance_id}
    else:
        stopped_instances = []
        for inst in pool.list_instances():
            if inst.status == InstanceStatus.BUSY:
                inst.stop()
                stopped_instances.append(inst.instance_id)
        return {"status": "stopped_all", "stopped_count": len(stopped_instances), "instances": stopped_instances}


def tool_get_account_status(account_id: Optional[str] = None) -> Dict[str, Any]:
    """Query account matrix assets, online fatigue gauges, and rest status."""
    matrix = AccountMatrix.get_instance()
    if account_id:
        acc = matrix.get_account(account_id)
        if not acc:
            return {"error": f"Account [{account_id}] not found in matrix."}
        return {"account": acc.to_dict()}
    else:
        return {
            "total_assets": matrix.get_total_assets(),
            "accounts": matrix.export_to_dict(),
        }


def tool_query_health() -> Dict[str, Any]:
    """Retrieve comprehensive health diagnostics for cluster, proxy pool, accounts, and watchdog."""
    pool = InstancePool.get_pool()
    proxy = ProxyManager.get_instance()
    matrix = AccountMatrix.get_instance()
    sup = ClusterSupervisor.get_instance()

    return {
        "cluster": pool.get_cluster_stats(),
        "proxy": proxy.get_proxy_stats(),
        "assets": matrix.get_total_assets(),
        "supervisor": sup.get_status(),
    }


def tool_list_plugins() -> Dict[str, Any]:
    """Enumerate all discovered game plugins and their declarative DAG pipelines."""
    plugins = GamePluginRegistry.list_plugins()
    return {
        "total_plugins": len(plugins),
        "plugins": plugins,
    }


# =====================================================================
# MCP Tool Metadata Specifications (JSON Schema)
# =====================================================================

TOOLS_SPEC = [
    {
        "name": "list_instances",
        "description": "List all registered game client/device instances with status, active pipelines, and assigned proxies.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_screenshot",
        "description": "Capture current screenshot frame (base64 JPEG) from an instance or default device.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "instance_id": {
                    "type": "string",
                    "description": "Target instance ID (optional, defaults to first active or virtual device)",
                }
            },
            "required": [],
        },
    },
    {
        "name": "start_routine",
        "description": "Schedule and execute an ordered task routine chain on a specific or auto-allocated instance.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "routine_name": {
                    "type": "string",
                    "description": "Descriptive routine name (e.g. 'daily_chain', 'yuhun_farm')",
                },
                "pipelines": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Ordered list of pipeline names to execute sequentially",
                },
                "instance_id": {
                    "type": "string",
                    "description": "Target instance ID (optional, auto-allocated if omitted)",
                },
                "plugin": {
                    "type": "string",
                    "description": "Game plugin ID: 'mhxy_mobile' or 'yys_mobile' (default: 'mhxy_mobile')",
                    "default": "mhxy_mobile",
                },
                "variables": {
                    "type": "object",
                    "description": "Initial context variables passed to DAG pipelines",
                },
            },
            "required": ["routine_name", "pipelines"],
        },
    },
    {
        "name": "stop_task",
        "description": "Stop running tasks on a target instance or stop all running tasks cluster-wide.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "instance_id": {
                    "type": "string",
                    "description": "Instance ID to stop (optional, stops all if omitted)",
                }
            },
            "required": [],
        },
    },
    {
        "name": "get_account_status",
        "description": "Query account matrix gold/silver assets, online time, and anti-bot fatigue resting status.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "Specific account ID to query (optional, returns all if omitted)",
                }
            },
            "required": [],
        },
    },
    {
        "name": "query_health",
        "description": "Retrieve comprehensive cluster, proxy pool, account matrix, and supervisor watchdog health status.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "list_plugins",
        "description": "Enumerate all dynamically discovered game plugins and their available DAG pipelines.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
]

TOOL_HANDLERS = {
    "list_instances": lambda args: tool_list_instances(),
    "get_screenshot": lambda args: tool_get_screenshot(args.get("instance_id")),
    "start_routine": lambda args: tool_start_routine(
        routine_name=args["routine_name"],
        pipelines=args["pipelines"],
        instance_id=args.get("instance_id"),
        plugin=args.get("plugin", "mhxy_mobile"),
        variables=args.get("variables"),
    ),
    "stop_task": lambda args: tool_stop_task(args.get("instance_id")),
    "get_account_status": lambda args: tool_get_account_status(args.get("account_id")),
    "query_health": lambda args: tool_query_health(),
    "list_plugins": lambda args: tool_list_plugins(),
}


# =====================================================================
# Native JSON-RPC 2.0 MCP Protocol Server
# =====================================================================

class NativeMCPServer:
    """
    Robust, zero-external-dependency Model Context Protocol (MCP) server.
    Implements standard JSON-RPC 2.0 over stdio transport.
    """

    PROTOCOL_VERSION = "2024-11-05"
    SERVER_NAME = "game-auto-framework-mcp"
    SERVER_VERSION = "0.1.0"

    def __init__(self) -> None:
        self.is_initialized = False

    def handle_request(self, req: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Process a single JSON-RPC request and produce the response."""
        req_id = req.get("id")
        method = req.get("method")
        params = req.get("params", {})

        # Handle notifications (requests without an id)
        if req_id is None:
            if method == "notifications/initialized":
                self.is_initialized = True
                logger.debug("MCP client initialized.")
            return None

        # 1. MCP initialize handshake
        if method == "initialize":
            self.is_initialized = True
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": self.PROTOCOL_VERSION,
                    "capabilities": {
                        "tools": {
                            "listChanged": False,
                        }
                    },
                    "serverInfo": {
                        "name": self.SERVER_NAME,
                        "version": self.SERVER_VERSION,
                    },
                },
            }

        # 2. Ping
        if method == "ping":
            return {"jsonrpc": "2.0", "id": req_id, "result": {}}

        # 3. tools/list
        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "tools": TOOLS_SPEC,
                },
            }

        # 4. tools/call
        if method == "tools/call":
            tool_name = params.get("name")
            arguments = params.get("arguments", {})
            handler = TOOL_HANDLERS.get(tool_name)

            if not handler:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {
                        "code": -32601,
                        "message": f"Tool [{tool_name}] not found.",
                    },
                }

            try:
                result_data = handler(arguments)
                text_content = json.dumps(result_data, ensure_ascii=False, indent=2)
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": text_content,
                            }
                        ],
                        "isError": "error" in result_data if isinstance(result_data, dict) else False,
                    },
                }
            except Exception as e:
                logger.error(f"Error executing MCP tool [{tool_name}]: {e}")
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": f"Error executing {tool_name}: {str(e)}",
                            }
                        ],
                        "isError": True,
                    },
                }

        # Method not found
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {
                "code": -32601,
                "message": f"Method [{method}] not found.",
            },
        }

    def run_stdio(self) -> None:
        """Run standard I/O communication loop for AI Agent connection."""
        logger.info(f"Starting {self.SERVER_NAME} v{self.SERVER_VERSION} on stdio...")
        # Write to stderr so stdout remains clean JSON-RPC
        sys.stderr.write(f"[{self.SERVER_NAME}] Ready for JSON-RPC 2.0 stdio communication.\n")
        sys.stderr.flush()

        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
                resp = self.handle_request(req)
                if resp is not None:
                    sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
                    sys.stdout.flush()
            except json.JSONDecodeError as e:
                err_resp = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {
                        "code": -32700,
                        "message": f"Parse error: {e}",
                    },
                }
                sys.stdout.write(json.dumps(err_resp) + "\n")
                sys.stdout.flush()
            except Exception as e:
                logger.error(f"Unexpected stdio loop error: {e}")


def run_mcp_server(transport: str = "stdio") -> None:
    """CLI Entrypoint to launch MCP server."""
    server = NativeMCPServer()
    server.run_stdio()
