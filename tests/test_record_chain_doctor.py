import importlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _module():
    sys.modules.pop("record_chain_doctor", None)
    return importlib.import_module("record_chain_doctor")


def _guardian_report(**summary_overrides):
    summary = {
        "record_count": 1,
        "record_guarded_count": 1,
        "record_stat_guarded_count": 0,
        "raw_not_current_count": 0,
        "raw_attention_count": 0,
        "backfill_recommended_count": 0,
        "lost_source_count": 0,
        "lost_raw_count": 0,
        "corrupt_record_count": 0,
        "origin_event_count": 1,
    }
    summary.update(summary_overrides)
    return {
        "ok": True,
        "contract": "raw_record_guardian.v1",
        "time_origin_contract": "raw_origin_event_summary.v1",
        "summary": summary,
        "records": [
            {
                "record_id": "rec-1",
                "source_system": "codex",
                "session_id": "session-1",
                "thread_name": "Doctor Session",
                "guard_status": "record_guarded",
                "raw_current": True,
                "source_exists": True,
                "raw_exists": True,
                "source_path_label": "~/source.jsonl",
                "raw_path_label": "~/raw.jsonl",
                "source_health_status": "ok",
                "raw_health_status": "ok",
            }
        ],
    }


def _canonical_index(ok=True):
    return {
        "ok": ok,
        "contract": "canonical_record_index.v2",
        "totals": {
            "canonical_sessions": 1,
            "canonical_messages": 2,
            "canonical_chunks": 2,
        },
        "sessions": [
            {
                "record_id": "rec-1",
                "source_system": "codex",
                "session_id": "session-1",
                "thread_name": "Doctor Session",
                "source_path_label": "~/source.jsonl",
                "raw_path_label": "~/raw.jsonl",
                "indexed_message_count": 2,
                "raw_offset_coverage_count": 2,
                "updated_at": "2026-06-14T00:00:00Z",
            }
        ],
        "messages": [
            {
                "message_id": "msg-u",
                "record_id": "rec-1",
                "source_system": "codex",
                "session_id": "session-1",
                "role": "user",
                "timestamp": "2026-06-14T00:00:01Z",
                "content_preview": "keep raw records",
                "raw_available": 1,
            },
            {
                "message_id": "msg-a",
                "record_id": "rec-1",
                "source_system": "codex",
                "session_id": "session-1",
                "role": "assistant",
                "timestamp": "2026-06-14T00:00:02Z",
                "content_preview": "record chain guarded",
                "raw_available": 1,
            },
        ],
        "origin_events": [],
    }


def test_record_doctor_reports_guarded_chain_without_writes():
    doctor = _module()

    payload = doctor.build_record_doctor(
        guardian_report=_guardian_report(),
        canonical_index=_canonical_index(),
    )

    assert payload["ok"] is True
    assert payload["contract"] == "record_chain_doctor.v1"
    assert payload["parent_tiandao_contract"] == "tiandao_time_river.v1"
    assert payload["doctor_status"] == "records_guarded"
    assert payload["record_chain_mode"] == "source_to_raw_to_canonical_to_memory_experience"
    assert payload["not_memory_wall"] is True
    assert payload["read_only"] is True
    assert payload["write_performed"] is False
    assert payload["raw_write_performed"] is False
    assert payload["memory_write_performed"] is False
    assert payload["platform_write_performed"] is False
    assert payload["summary"]["canonical_messages"] == 2
    assert all("ok" in item for item in payload["checks"])


def test_record_doctor_surfaces_active_divergence_generation_without_backfill():
    doctor = _module()

    payload = doctor.build_record_doctor(
        guardian_report=_guardian_report(
            raw_attention_count=1,
            raw_divergence_generation_active_count=1,
            backfill_recommended_count=0,
        ),
        canonical_index=_canonical_index(),
    )

    assert payload["doctor_status"] == "attention"
    assert payload["summary"]["raw_divergence_generation_active_count"] == 1
    assert payload["summary"]["backfill_recommended_count"] == 0
    assert "continuation is guarded" in " ".join(payload["next_actions"])


def test_record_doctor_escalates_lost_source_and_lost_raw():
    doctor = _module()

    payload = doctor.build_record_doctor(
        guardian_report=_guardian_report(lost_source_count=1, lost_raw_count=1, raw_attention_count=1),
        canonical_index=_canonical_index(),
    )

    assert payload["ok"] is False
    assert payload["doctor_status"] == "attention"
    assert payload["summary"]["lost_source_count"] == 1
    assert payload["summary"]["lost_raw_count"] == 1
    actions = " ".join(payload["next_actions"])
    assert "backfill" in actions
    assert "recovery evidence" in actions


def test_record_doctor_does_not_fail_recoverable_lost_source():
    doctor = _module()

    payload = doctor.build_record_doctor(
        guardian_report=_guardian_report(
            lost_source_count=1,
            lost_source_recoverable_count=1,
            lost_source_unrecoverable_count=0,
            lost_source_not_measured_count=0,
        ),
        canonical_index=_canonical_index(),
    )

    assert payload["ok"] is True
    assert payload["doctor_status"] == "records_guarded"
    assert payload["summary"]["lost_source_recoverable_count"] == 1
    assert payload["checks"][3]["ok"] is True


def test_record_doctor_observes_unmeasured_lost_source_without_false_red():
    doctor = _module()

    payload = doctor.build_record_doctor(
        guardian_report=_guardian_report(
            lost_source_count=1,
            lost_source_recoverable_count=0,
            lost_source_unrecoverable_count=0,
            lost_source_not_measured_count=1,
        ),
        canonical_index=_canonical_index(),
    )

    assert payload["ok"] is True
    assert payload["doctor_status"] == "recoverability_evidence_incomplete"
    assert "not treat unmeasured as lost" in " ".join(payload["next_actions"])


def test_record_doctor_fails_closed_when_lost_source_triage_is_inconsistent():
    doctor = _module()

    payload = doctor.build_record_doctor(
        guardian_report=_guardian_report(
            lost_source_count=2,
            lost_source_recoverable_count=1,
            lost_source_unrecoverable_count=0,
            lost_source_not_measured_count=0,
        ),
        canonical_index=_canonical_index(),
    )

    assert payload["ok"] is False
    assert payload["doctor_status"] == "attention"
    assert payload["summary"]["lost_source_unrecoverable_count"] == 2


def test_record_chain_timeline_uses_source_raw_index_memory_experience_stages():
    doctor = _module()

    payload = doctor.build_record_chain_timeline(
        guardian_report=_guardian_report(),
        canonical_index=_canonical_index(),
    )

    assert payload["ok"] is True
    assert payload["contract"] == "record_chain_timeline.v1"
    assert payload["timeline_kind"] == "record_chain"
    assert payload["not_memory_wall"] is True
    stages = payload["record_chains"][0]["stages"]
    assert [item["id"] for item in stages] == [
        "source_record",
        "raw_mirror",
        "canonical_index",
        "memory_experience",
    ]
    assert stages[2]["status"] == "indexed"
    assert payload["recent_messages"][0]["raw_available"] is True


def test_record_chain_timeline_treats_recoverable_retained_raw_as_guarded():
    doctor = _module()
    guardian = _guardian_report(
        lost_source_count=1,
        lost_source_recoverable_count=1,
        lost_source_unrecoverable_count=0,
        lost_source_not_measured_count=0,
    )
    guardian["records"][0].update({
        "guard_status": "source_missing_recoverable_from_raw",
        "raw_current": False,
        "source_exists": False,
    })

    payload = doctor.build_record_chain_timeline(
        guardian_report=guardian,
        canonical_index=_canonical_index(),
    )

    chain = payload["record_chains"][0]
    assert chain["chain_status"] == "guarded"
    assert chain["stages"][1]["status"] == "guarded"


def test_record_chain_replay_is_preview_not_raw_replacement():
    doctor = _module()

    payload = doctor.build_record_chain_replay(
        guardian_report=_guardian_report(),
        canonical_index=_canonical_index(),
        session_id="session-1",
    )

    assert payload["ok"] is True
    assert payload["contract"] == "record_chain_replay.v1"
    assert payload["replay_kind"] == "record_chain"
    assert payload["not_memory_wall"] is True
    assert payload["message_count"] == 2
    assert "not full raw replacement" in payload["notes"][0]


def test_internal_capability_matrix_is_test_only_and_not_product_ui():
    matrix_path = ROOT / "tests" / "fixtures" / "internal_ai_tool_capability_matrix.json"
    payload = json.loads(matrix_path.read_text(encoding="utf-8"))

    assert payload["contract"] == "memcore_internal_ai_tool_capability_matrix.v1"
    assert payload["audience"] == "maintainer_test_only_not_product_ui"
    assert payload["public_wording_boundary"].startswith("Public copy says local AI tool integration")
    assert {item["surface"] for item in payload["surfaces"]} >= {
        "hooks",
        "mcp",
        "rest",
        "local_collectors",
        "record_doctor_and_chain",
    }
    assert all(item["public_docs_expose_matrix"] is False for item in payload["surfaces"])
