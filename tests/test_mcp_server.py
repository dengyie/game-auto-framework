"""Tests for Model Context Protocol (MCP) server, tool dispatches, and JSON-RPC 2.0 protocol."""

import json
import subprocess
import sys
from server.mcp import NativeMCPServer, TOOLS_SPEC
from cluster.instance_pool import InstancePool


def test_mcp_initialize_and_ping():
    server = NativeMCPServer()

    # 1. Initialize
    init_req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test-agent", "version": "1.0"},
        },
    }
    resp = server.handle_request(init_req)
    assert resp["jsonrpc"] == "2.0"
    assert resp["id"] == 1
    assert resp["result"]["protocolVersion"] == "2024-11-05"
    assert resp["result"]["serverInfo"]["name"] == "game-auto-framework-mcp"
    assert "tools" in resp["result"]["capabilities"]

    # 2. Notification initialized
    notif = {"jsonrpc": "2.0", "method": "notifications/initialized"}
    assert server.handle_request(notif) is None
    assert server.is_initialized is True

    # 3. Ping
    ping_resp = server.handle_request({"jsonrpc": "2.0", "id": 2, "method": "ping"})
    assert ping_resp["id"] == 2
    assert ping_resp["result"] == {}


def test_mcp_tools_list():
    server = NativeMCPServer()
    req = {"jsonrpc": "2.0", "id": 10, "method": "tools/list", "params": {}}
    resp = server.handle_request(req)
    assert resp["id"] == 10
    tools = resp["result"]["tools"]
    tool_names = [t["name"] for t in tools]

    expected = [
        "list_instances",
        "get_screenshot",
        "start_routine",
        "stop_task",
        "get_account_status",
        "query_health",
        "list_plugins",
    ]
    for exp in expected:
        assert exp in tool_names

    # Verify schema definition
    for t in tools:
        assert "description" in t
        assert "inputSchema" in t
        assert t["inputSchema"]["type"] == "object"


def test_mcp_tool_calls_execution():
    server = NativeMCPServer()

    # 1. list_plugins
    res = server.handle_request({
        "jsonrpc": "2.0",
        "id": 20,
        "method": "tools/call",
        "params": {"name": "list_plugins", "arguments": {}},
    })
    assert res["id"] == 20
    assert res["result"]["isError"] is False
    content_text = res["result"]["content"][0]["text"]
    data = json.loads(content_text)
    assert data["total_plugins"] >= 2
    plugin_ids = [p["id"] for p in data["plugins"]]
    assert "mhxy_mobile" in plugin_ids
    assert "yys_mobile" in plugin_ids

    # 2. query_health
    res = server.handle_request({
        "jsonrpc": "2.0",
        "id": 21,
        "method": "tools/call",
        "params": {"name": "query_health", "arguments": {}},
    })
    assert res["id"] == 21
    data = json.loads(res["result"]["content"][0]["text"])
    assert "cluster" in data
    assert "proxy" in data
    assert "assets" in data
    assert "supervisor" in data

    # 3. list_instances
    res = server.handle_request({
        "jsonrpc": "2.0",
        "id": 22,
        "method": "tools/call",
        "params": {"name": "list_instances", "arguments": {}},
    })
    assert res["id"] == 22
    data = json.loads(res["result"]["content"][0]["text"])
    assert "total" in data

    # 4. get_screenshot (virtual device fallback)
    res = server.handle_request({
        "jsonrpc": "2.0",
        "id": 23,
        "method": "tools/call",
        "params": {"name": "get_screenshot", "arguments": {}},
    })
    assert res["id"] == 23
    data = json.loads(res["result"]["content"][0]["text"])
    assert "format" in data
    assert data["format"] == "jpeg"
    assert "base64_full" in data
    assert len(data["base64_full"]) > 100

    # 5. get_account_status
    res = server.handle_request({
        "jsonrpc": "2.0",
        "id": 24,
        "method": "tools/call",
        "params": {"name": "get_account_status", "arguments": {}},
    })
    assert res["id"] == 24
    data = json.loads(res["result"]["content"][0]["text"])
    assert "total_assets" in data

    # 6. Unknown tool error
    res = server.handle_request({
        "jsonrpc": "2.0",
        "id": 25,
        "method": "tools/call",
        "params": {"name": "non_existent_tool", "arguments": {}},
    })
    assert "error" in res
    assert res["error"]["code"] == -32601


def test_mcp_start_routine_and_stop_task():
    server = NativeMCPServer()
    pool = InstancePool.get_pool()
    inst = pool.register_instance("mcp_test_inst_01", device_type="virtual")

    # Start routine on specific instance
    res = server.handle_request({
        "jsonrpc": "2.0",
        "id": 30,
        "method": "tools/call",
        "params": {
            "name": "start_routine",
            "arguments": {
                "instance_id": "mcp_test_inst_01",
                "routine_name": "mcp_routine_01",
                "pipelines": ["yuhun_farm"],
                "plugin": "yys_mobile",
            },
        },
    })
    assert res["id"] == 30
    data = json.loads(res["result"]["content"][0]["text"])
    assert data["status"] == "started"
    assert data["instance_id"] == "mcp_test_inst_01"
    assert data["plugin"] == "yys_mobile"

    # Stop task on instance
    stop_res = server.handle_request({
        "jsonrpc": "2.0",
        "id": 31,
        "method": "tools/call",
        "params": {
            "name": "stop_task",
            "arguments": {"instance_id": "mcp_test_inst_01"},
        },
    })
    assert stop_res["id"] == 31
    stop_data = json.loads(stop_res["result"]["content"][0]["text"])
    assert stop_data["status"] == "stopped"

    # Cleanup
    pool.unregister_instance("mcp_test_inst_01")


def test_mcp_cli_stdio_subprocess():
    """Verify python main.py mcp stdio subprocess pipes JSON-RPC cleanly."""
    cmd = [sys.executable, "main.py", "mcp", "--transport", "stdio"]
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    init_line = json.dumps({"jsonrpc": "2.0", "id": 100, "method": "initialize", "params": {}}) + "\n"
    tools_line = json.dumps({"jsonrpc": "2.0", "id": 101, "method": "tools/list", "params": {}}) + "\n"

    stdout, _ = proc.communicate(input=init_line + tools_line, timeout=5.0)

    lines = [l.strip() for l in stdout.strip().split("\n") if l.strip()]
    assert len(lines) >= 2

    resp1 = json.loads(lines[0])
    assert resp1["id"] == 100
    assert resp1["result"]["serverInfo"]["name"] == "game-auto-framework-mcp"

    resp2 = json.loads(lines[1])
    assert resp2["id"] == 101
    assert len(resp2["result"]["tools"]) >= 7
