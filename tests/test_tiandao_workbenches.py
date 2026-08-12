import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def test_tiandao_workbenches_contract_contains_five_read_only_modules():
    from tiandao_workbenches import get_tiandao_workbenches_contract

    contract = get_tiandao_workbenches_contract()

    assert contract["ok"] is True
    assert contract["contract"] == "tiandao_workbenches.v1"
    assert contract["zh_name"] == "五大工作台"
    assert contract["en_name"] == "Five Workbenches"
    assert contract["read_only"] is True
    assert contract["write_performed"] is False
    assert contract["raw_write_performed"] is False
    assert contract["memory_write_performed"] is False
    assert contract["platform_write_performed"] is False
    assert contract["model_call_performed"] is False
    assert contract["workbench_ids"] == [
        "origin_guard",
        "second_brain",
        "platform_guard",
        "experience_governance",
        "hermes_learning_observatory",
    ]
    assert contract["policies"]["lost_wording"] == {"source": "遗失源", "raw": "遗失 raw"}
    assert contract["policies"]["detection_is_not_capture"] is True


def test_tiandao_workbenches_dashboard_aggregates_without_writes(monkeypatch):
    import tiandao_workbenches as tw

    monkeypatch.setattr(tw, "build_guardian_status", lambda **kwargs: {
        "ok": True,
        "contract": "raw_record_guardian.v1",
        "time_origin_contract": "tiandao_time_origin.v1",
        "index_contract": "canonical_record_index.v2",
        "summary": {
            "record_count": 7,
            "record_guarded_count": 6,
            "raw_not_current_count": 1,
            "raw_divergence_generation_active_count": 2,
            "lost_source_count": 0,
            "lost_raw_count": 1,
            "backfill_recommended_count": 1,
            "origin_event_count": 6,
            "max_raw_lag_milliseconds": 250,
        },
        "gap_sources": ["claude_desktop"],
        "inactive_sources": [],
        "claude_desktop_evidence": {"body_guarded_count": 1},
    })
    monkeypatch.setattr(tw, "build_continuous_sync_status", lambda **kwargs: {
        "ok": True,
        "contract": "continuous_local_chat_sync.v1",
        "tiandao_contract": "tiandao_continuous_local_sync.v1",
        "summary": {
            "millisecond_level_source_count": 5,
            "collector_pending_count": 0,
        },
        "watcher": {
            "active": True,
            "target_latency_milliseconds": 250,
        },
    })
    monkeypatch.setattr(tw, "get_second_brain_contract", lambda: {
        "ok": True,
        "contract": "tiandao_second_brain.v1",
        "parent_tiandao_contract": "tiandao_time_river.v1",
        "orchestrated_modules": ["material_processing_pipeline", "time_river_sediment"],
        "network_call_performed": False,
    })
    monkeypatch.setattr(tw, "get_material_processing_pipeline_contract", lambda: {
        "ok": True,
        "contract": "zhixing_material_processing_pipeline.v1",
        "pipeline_stages": ["source_registration", "batch_level_screening"],
        "default_batch_size": 20,
        "default_wip_limit": 3,
        "network_call_performed": False,
        "raw_authority_preserved": True,
    })
    monkeypatch.setattr(tw, "build_platform_discovery_dashboard", lambda **kwargs: {
        "ok": True,
        "contract": "platform_discovery_dashboard.v1",
        "counts": {
            "detected": 4,
            "ready_for_capability_check": 3,
            "auto_connect_ready": 2,
            "other_local_tools": 1,
        },
        "items": [],
        "model_call_performed": False,
    })
    monkeypatch.setattr(tw, "library_manifest", lambda: {
        "enabled": True,
        "contract": "zhixing_library.v1",
        "raw_is_source_text": True,
        "shelves": {"raw": {}, "zhiyi": {}, "xingce": {}, "toolbook": {}, "errata": {}},
    })
    monkeypatch.setattr(tw, "replay_plan", lambda: {"contract": "zhixing_replay_plan.v1"})
    monkeypatch.setattr(tw, "benchmark_plan", lambda: {"contract": "zhixing_benchmark_plan.v1"})
    monkeypatch.setattr(tw, "zhixing_loop_manifest", lambda: {"contract": "zhixing_loop.v1"})

    result = tw.build_tiandao_workbenches_dashboard(
        watcher_active=True,
        governance_stats={"total_proposals": 9, "applied_count": 0, "dry_run_only": True},
        hermes_liveness={"ok": True, "contract": "hermes_native_learning_liveness.v1", "skill_snapshot": {"file_count": 2}},
        hermes_triggers={"items": [1]},
        hermes_probes={"items": [1, 2]},
        hermes_statuses={"items": [1, 2, 3]},
        hermes_diff_plan={"contract": "hermes_skill_experience_diff.v1"},
        hermes_report_plan={"contract": "hermes_self_review_report.v1"},
    )

    assert result["ok"] is True
    assert result["contract"] == "tiandao_workbenches.v1"
    assert result["read_only"] is True
    assert result["write_performed"] is False
    assert result["raw_write_performed"] is False
    assert result["memory_write_performed"] is False
    assert result["platform_write_performed"] is False
    assert result["summary"]["workbench_count"] == 5
    assert result["summary"]["record_count"] == 7
    assert result["summary"]["lost_raw_count"] == 1
    assert result["summary"]["record_first_ready"] is False
    ids = [item["id"] for item in result["workbenches"]]
    assert ids == [
        "origin_guard",
        "second_brain",
        "platform_guard",
        "experience_governance",
        "hermes_learning_observatory",
    ]
    origin = result["workbenches"][0]
    assert origin["summary"]["millisecond_level_source_count"] == 5
    assert origin["summary"]["raw_divergence_generation_active_count"] == 2
    assert origin["summary"]["time_twin_star_runtime_status"] == "source_runtime_route_present"
    assert origin["summary"]["time_twin_star_installed_runtime_status"] == "proven"
    assert origin["summary"]["time_twin_star_source_proven_count"] == 11
    assert origin["summary"]["time_twin_star_contract_only_count"] == 1
    assert origin["summary"]["time_twin_star_planned_count"] == 1
    assert "/api/v1/tiandao/time-twin-star/status" in origin["endpoints"]
    assert result["summary"]["time_twin_star_source_proven_count"] == 11
    assert result["summary"]["time_twin_star_installed_runtime_status"] == "proven"
    assert result["source_reports"]["time_twin_star"]["contract"] == "time_twin_star_runtime_status.v1"
    assert result["source_reports"]["time_twin_star"]["source_canon_lineage"] == "subordinate_projection_not_successor"
    assert result["source_reports"]["time_twin_star"]["source_canon_projection"]["surface_contract"] == "time_tiandao_surface.v1"
    assert result["source_reports"]["time_twin_star"]["source_canon_projection"]["projection_source"] == "src/tiandao/time_twin_star.py"
    assert origin["health"] == "lost_evidence_detected"
    assert result["workbenches"][2]["summary"]["discovered_is_not_captured"] is True
    assert result["workbenches"][3]["summary"]["total_proposals"] == 9
    assert result["workbenches"][4]["summary"]["skill_file_count"] == 2


def test_tiandao_workbenches_time_twin_star_slot_uses_first_class_surface():
    source = Path("src/tiandao_workbenches.py").read_text(encoding="utf-8")

    assert "from src.tiandao import time_twin_star_runtime_status" in source
    assert "def _time_twin_star_runtime_status" in source
    assert "time_twin_star_runtime_status()" in source
    assert "source_canon_lineage" in source
    assert "subordinate_projection_not_successor" in source


def test_tiandao_workbenches_treats_active_raw_catchup_as_non_blocking(monkeypatch):
    import tiandao_workbenches as tw

    monkeypatch.setattr(tw, "build_guardian_status", lambda **kwargs: {
        "ok": True,
        "contract": "raw_record_guardian.v1",
        "time_origin_contract": "tiandao_time_origin.v1",
        "index_contract": "canonical_record_index.v2",
        "summary": {
            "record_count": 64,
            "record_guarded_count": 63,
            "raw_not_current_count": 1,
            "raw_lagging_or_missing_count": 0,
            "raw_catching_up_count": 1,
            "raw_attention_count": 0,
            "lost_source_count": 0,
            "lost_raw_count": 0,
            "backfill_recommended_count": 0,
            "corrupt_record_count": 0,
            "origin_event_count": 64,
            "max_raw_lag_milliseconds": 250,
        },
        "gap_sources": [],
        "inactive_sources": [],
        "claude_desktop_evidence": {"body_guarded_count": 0},
    })
    monkeypatch.setattr(tw, "build_continuous_sync_status", lambda **kwargs: {
        "ok": True,
        "contract": "continuous_local_chat_sync.v1",
        "tiandao_contract": "tiandao_continuous_local_sync.v1",
        "summary": {
            "millisecond_level_source_count": 4,
            "collector_pending_count": 0,
        },
        "watcher": {
            "active": True,
            "target_latency_milliseconds": 250,
        },
    })
    monkeypatch.setattr(tw, "get_second_brain_contract", lambda: {
        "ok": True,
        "contract": "tiandao_second_brain.v1",
        "parent_tiandao_contract": "tiandao_time_river.v1",
        "orchestrated_modules": ["material_processing_pipeline"],
        "network_call_performed": False,
    })
    monkeypatch.setattr(tw, "get_material_processing_pipeline_contract", lambda: {
        "ok": True,
        "contract": "zhixing_material_processing_pipeline.v1",
        "pipeline_stages": ["source_registration"],
        "default_batch_size": 20,
        "default_wip_limit": 3,
        "network_call_performed": False,
        "raw_authority_preserved": True,
    })
    monkeypatch.setattr(tw, "build_platform_discovery_dashboard", lambda **kwargs: {
        "ok": True,
        "contract": "platform_discovery_dashboard.v1",
        "counts": {
            "detected": 4,
            "ready_for_capability_check": 4,
            "auto_connect_ready": 3,
            "other_local_tools": 0,
        },
        "items": [],
        "model_call_performed": False,
    })
    monkeypatch.setattr(tw, "library_manifest", lambda: {
        "enabled": True,
        "contract": "zhixing_library.v1",
        "raw_is_source_text": True,
        "shelves": {"raw": {}, "zhiyi": {}, "xingce": {}, "toolbook": {}, "errata": {}},
    })
    monkeypatch.setattr(tw, "replay_plan", lambda: {"contract": "zhixing_replay_plan.v1"})
    monkeypatch.setattr(tw, "benchmark_plan", lambda: {"contract": "zhixing_benchmark_plan.v1"})
    monkeypatch.setattr(tw, "zhixing_loop_manifest", lambda: {"contract": "zhixing_loop.v1"})

    result = tw.build_tiandao_workbenches_dashboard()

    assert result["summary"]["raw_not_current_count"] == 1
    assert result["summary"]["raw_attention_count"] == 0
    assert result["summary"]["raw_lagging_or_missing_count"] == 0
    assert result["summary"]["raw_catching_up_count"] == 1
    assert result["summary"]["max_raw_lag_milliseconds"] == 250
    assert result["summary"]["record_first_ready"] is True
    assert result["summary"]["needs_attention_count"] == 0
    origin = result["workbenches"][0]
    assert origin["health"] == "raw_catching_up"
    assert origin["ok"] is True
    assert "watch_active_tail_catchup_without_marking_record_lost" in origin["next_actions"]
