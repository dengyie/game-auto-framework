"""Tests for Web Dashboard REST endpoints, plugin discovery, and cluster management APIs."""

import pytest
from fastapi.testclient import TestClient
from server.app import app


@pytest.fixture
def client():
    return TestClient(app)


def test_dashboard_html_rendering(client):
    """Verify embedded Web Dashboard HTML is served at / and /dashboard."""
    for path in ["/", "/dashboard"]:
        res = client.get(path)
        assert res.status_code == 200
        assert "text/html" in res.headers["content-type"]
        assert "Game Auto Framework" in res.text
        assert "kpi-grid" in res.text
        assert "pane-instances" in res.text
        assert "pane-soak" in res.text
        assert "24h 极限压测与时序遥测" in res.text


def test_plugin_discovery_endpoints(client):
    """Verify GET /api/v1/plugins and GET /api/v1/plugins/{id}/pipelines."""
    res = client.get("/api/v1/plugins")
    assert res.status_code == 200
    data = res.json()
    assert "plugins" in data
    assert data["total"] >= 2
    plugin_ids = [p["id"] for p in data["plugins"]]
    assert "mhxy_mobile" in plugin_ids
    assert "yys_mobile" in plugin_ids

    # Query yys_mobile pipelines
    yys_res = client.get("/api/v1/plugins/yys_mobile/pipelines")
    assert yys_res.status_code == 200
    yys_data = yys_res.json()
    assert yys_data["plugin_id"] == "yys_mobile"
    assert yys_data["total"] >= 3
    pipe_names = [p["name"] for p in yys_data["pipelines"]]
    assert "yuhun_farm" in pipe_names
    assert "jiejie_raid" in pipe_names

    # Non-existent plugin
    err_res = client.get("/api/v1/plugins/non_existent_game/pipelines")
    assert err_res.status_code == 404


def test_cluster_team_and_proxy_and_account_lifecycle(client):
    """Verify team, proxy unbind/delete, and account rest APIs."""
    # 1. Register test instances
    client.post("/api/v1/cluster/instances/register", json={"instance_id": "test_inst_dash_01", "device_type": "virtual"})
    client.post("/api/v1/cluster/instances/register", json={"instance_id": "test_inst_dash_02", "device_type": "virtual"})

    # 2. Assemble Team
    team_payload = {
        "team_id": "dash_team_01",
        "leader_id": "test_inst_dash_01",
        "member_ids": ["test_inst_dash_02"],
        "target_activity": "test_activity",
    }
    t_res = client.post("/api/v1/cluster/team/create", json=team_payload)
    assert t_res.status_code == 200

    # 3. List Teams
    teams_res = client.get("/api/v1/cluster/teams")
    assert teams_res.status_code == 200
    teams_data = teams_res.json()
    assert any(t["team_id"] == "dash_team_01" for t in teams_data["teams"])

    # 4. Dissolve Team
    dis_res = client.delete("/api/v1/cluster/teams/dash_team_01")
    assert dis_res.status_code == 200
    assert dis_res.json()["status"] == "dissolved"

    # 5. Register Proxy & Bind
    p_reg = client.post(
        "/api/v1/cluster/proxies/register",
        json={"proxy_id": "dash_proxy_01", "host": "127.0.0.1", "port": 8888, "protocol": "socks5"},
    )
    assert p_reg.status_code == 200

    b_res = client.post(
        "/api/v1/cluster/proxies/bind",
        json={"instance_id": "test_inst_dash_01", "proxy_id": "dash_proxy_01"},
    )
    assert b_res.status_code == 200

    # 6. Unbind Proxy
    unb_res = client.post(
        "/api/v1/cluster/proxies/unbind",
        json={"instance_id": "test_inst_dash_01"},
    )
    assert unb_res.status_code == 200
    assert unb_res.json()["status"] == "unbound"

    # 7. Delete Proxy
    del_p_res = client.delete("/api/v1/cluster/proxies/dash_proxy_01")
    assert del_p_res.status_code == 200
    assert del_p_res.json()["status"] == "unregistered"

    # 8. Register Account and trigger rest
    a_res = client.post(
        "/api/v1/cluster/accounts/register",
        json={
            "account_id": "dash_acc_01",
            "username": "dash_user",
            "password": "pwd",
            "server_name": "东海湾",
            "sect": "方寸山",
        },
    )
    assert a_res.status_code == 200

    rest_res = client.post("/api/v1/cluster/accounts/dash_acc_01/rest")
    assert rest_res.status_code == 200
    assert rest_res.json()["status"] == "resting"
    assert rest_res.json()["account"]["status"] == "resting"

    # 9. Unregister instance
    del_i_res = client.delete("/api/v1/cluster/instances/test_inst_dash_01")
    assert del_i_res.status_code == 200
    assert del_i_res.json()["status"] == "unregistered"
    client.delete("/api/v1/cluster/instances/test_inst_dash_02")


def test_video_stream_and_device_action_endpoints(client):
    """Verify GET /api/v1/stream, instance stream, and POST /api/v1/cluster/instances/{id}/action."""
    # 1. Register test instance
    client.post("/api/v1/cluster/instances/register", json={"instance_id": "stream_test_inst", "device_type": "virtual"})

    # 2. Test HEAD and GET /
    head_res = client.head("/")
    assert head_res.status_code == 200

    head_health = client.head("/health")
    assert head_health.status_code == 200

    # 3. Test virtual action dispatch (tap, swipe, key)
    tap_res = client.post(
        "/api/v1/cluster/instances/stream_test_inst/action",
        json={"action": "tap", "x": 640, "y": 360},
    )
    assert tap_res.status_code == 200
    assert tap_res.json()["status"] == "ok"
    assert tap_res.json()["action"] == "tap"

    swipe_res = client.post(
        "/api/v1/cluster/instances/stream_test_inst/action",
        json={"action": "swipe", "x": 100, "y": 200, "x2": 500, "y2": 200},
    )
    assert swipe_res.status_code == 200
    assert swipe_res.json()["action"] == "swipe"

    key_res = client.post(
        "/api/v1/cluster/instances/stream_test_inst/action",
        json={"action": "key", "keycode": 4},
    )
    assert key_res.status_code == 200
    assert key_res.json()["keycode"] == 4

    # 4. Test instance screenshot
    shot_res = client.get("/api/v1/cluster/instances/stream_test_inst/screenshot")
    assert shot_res.status_code == 200
    assert "image/jpeg" in shot_res.headers["content-type"]
    assert len(shot_res.content) > 0

    # 5. Clean up
    client.delete("/api/v1/cluster/instances/stream_test_inst")

