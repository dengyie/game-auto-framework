"""
End-to-end integration tests for:
- 5-account registration, provisioning, and persistence in AccountMatrix.
- Novice & basic story tasks DAG pipeline (basic_tasks).
- 5-player team coordinated execution on InstancePool and TeamTopology.
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from cluster.account import AccountConfig, AccountMatrix, AccountStatus
from cluster.instance_pool import DeviceInstance, InstancePool, TeamRole, TeamTopology
from cluster.registration import AccountRegistrationManager
from core.device.virtual import VirtualDevice
from plugins.mhxy_mobile.plugin import MHXYMobilePlugin
from scheduler.dag import PipelineStatus


def test_5player_account_generation_and_matrix_persistence(tmp_path: Path):
    """Verify 5-player team account generation, attribute validity, and JSON persistence."""
    matrix = AccountMatrix()
    reg = AccountRegistrationManager(matrix=matrix)

    json_file = str(tmp_path / "test_accounts.json")
    team = reg.register_and_save_team(config_path=json_file, server_name="东海湾")

    assert len(team) == 5
    assert len(matrix.list_accounts()) == 5

    # Verify 1 Leader + 4 Members composition
    leaders = [a for a in team if a.team_role_preference == "leader"]
    members = [a for a in team if a.team_role_preference == "member"]
    assert len(leaders) == 1
    assert len(members) == 4

    # Verify Sects
    leader = leaders[0]
    assert leader.sect == "化生寺"
    assert "大队长" in (leader.role_name or "")
    member_sects = {m.sect for m in members}
    assert member_sects == {"普陀山", "阴曹地府", "龙宫", "狮驼岭"}

    # Verify JSON File was persisted correctly
    assert Path(json_file).exists()
    with open(json_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert len(data) == 5
    assert data[0]["username"] == team[0].username

    # Verify reload from JSON into a fresh matrix
    fresh_matrix = AccountMatrix()
    loaded_count = fresh_matrix.load_from_json(json_file)
    assert loaded_count == 5
    reloaded_acc = fresh_matrix.get_account(leader.account_id)
    assert reloaded_acc is not None
    assert reloaded_acc.role_name == leader.role_name


def test_device_registration_automation_flow():
    """Verify automated UI registration flow executes cleanly on device."""
    matrix = AccountMatrix()
    reg = AccountRegistrationManager(matrix=matrix)
    team = reg.generate_5player_team()
    leader_acc = team[0]

    dev = VirtualDevice(name="test_virtual_phone")
    result = reg.automate_device_registration(device=dev, account=leader_acc)

    assert result["status"] == "success"
    assert result["account_id"] == leader_acc.account_id
    assert len(result["steps"]) >= 4


def test_basic_tasks_pipeline_dag_execution():
    """Verify complete execution cycle of the basic_tasks novice story pipeline."""
    dev = VirtualDevice(name="test_virtual_phone")
    plugin = MHXYMobilePlugin(device=dev)
    assert "basic_tasks" in plugin.pipelines

    pipe = plugin.pipelines["basic_tasks"]
    pipe.start()
    assert pipe.status == PipelineStatus.RUNNING
    ctx = plugin.context
    ctx.variables["need_create_role"] = True
    ctx.variables["target_novice_steps"] = 3
    ctx.variables["leads_to_combat"] = True

    # 1. check_entry_screen
    status = pipe.tick(ctx)
    assert status == PipelineStatus.RUNNING
    assert ctx.variables.get("is_role_selection") is True

    # 2. create_or_select_role
    status = pipe.tick(ctx)
    assert status == PipelineStatus.RUNNING
    assert ctx.variables.get("role_created") is True
    assert ctx.variables.get("in_world") is True

    # 3. track_novice_quest
    status = pipe.tick(ctx)
    assert status == PipelineStatus.RUNNING
    assert ctx.variables.get("novice_quest_active") is True

    # 4. handle_story_dialog
    status = pipe.tick(ctx)
    assert status == PipelineStatus.RUNNING
    assert ctx.variables.get("novice_in_battle") is True

    # 5. novice_combat
    status = pipe.tick(ctx)
    assert status == PipelineStatus.RUNNING
    assert ctx.variables.get("novice_battle_auto_engaged") is True

    # 6. wait_novice_combat_end
    status = pipe.tick(ctx)
    assert status == PipelineStatus.RUNNING
    assert ctx.variables.get("novice_step") == 1

    # 7. claim_novice_level_rewards
    status = pipe.tick(ctx)
    assert status == PipelineStatus.RUNNING
    assert ctx.variables.get("level") >= 6

    # Execute remaining 2 steps to hit target_novice_steps (3)
    # Loop until novice_completed
    for _ in range(25):
        if pipe.status == PipelineStatus.COMPLETED:
            break
        pipe.tick(ctx)

    assert pipe.status == PipelineStatus.COMPLETED
    assert ctx.variables.get("basic_tasks_completed") is True
    assert ctx.variables.get("level") >= 15


def test_team_5player_basic_tasks_coordination():
    """Verify 5-player team coordinated execution of basic tasks on InstancePool."""
    pool = InstancePool()
    matrix = AccountMatrix()
    reg = AccountRegistrationManager(matrix=matrix)
    team_accounts = reg.register_and_save_team()

    instances: list[DeviceInstance] = []
    for i in range(1, 6):
        inst = pool.register_instance(
            instance_id=f"inst_sim_{i:02d}",
            device_type="virtual",
            name=f"SimDevice_{i:02d}",
        )
        assert inst.connect()
        instances.append(inst)

    # Bind 5 accounts to 5 instances
    for inst, acc in zip(instances, team_accounts):
        inst.assigned_account_id = acc.account_id
        acc.start_session(inst.instance_id)

    # Form 5-player team: 1 Leader (inst_01) + 4 Members (inst_02..inst_05)
    team_id = "team_novice_alpha"
    leader_inst = instances[0]
    member_insts = instances[1:]

    team = pool.create_team(
        team_id=team_id,
        leader_id=leader_inst.instance_id,
        member_ids=[m.instance_id for m in member_insts],
    )
    assert team is not None
    assert team.leader_instance_id == leader_inst.instance_id
    assert len(team.member_instance_ids) == 4
    assert team.is_full() is True

    # Concurrently launch basic_tasks across the team
    res_map = pool.start_team_routine(
        team_id=team_id,
        leader_pipelines=["basic_tasks"],
        member_pipelines=["basic_tasks"],
        run_in_background=False,
    )
    assert all(res_map.values()) is True

    # Advance ticks for all 5 instances
    for _ in range(10):
        for inst in instances:
            inst.tick()

    # Verify all 5 instances are actively running the basic_tasks pipeline
    for inst in instances:
        health = inst.get_health()
        assert health["status"] in ("busy", "idle")
        assert health["team_id"] == team_id
        assert health["assigned_account_id"] is not None

    # Cleanup
    for inst in instances:
        inst.stop()
        pool.unregister_instance(inst.instance_id)
