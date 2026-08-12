import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def test_raw_origin_event_is_stable_and_raw_is_time_origin():
    from raw_origin_event import build_raw_origin_event

    first = build_raw_origin_event(
        source_system="codex",
        computer_id="machine-a",
        native_session_key="session-a",
        source_path="/tmp/source.jsonl",
        raw_path="/tmp/raw.jsonl",
        source_exists=True,
        raw_exists=True,
        event_time="2026-06-08T00:00:00Z",
        captured_at="2026-06-08T00:00:01Z",
        audit_time="2026-06-08T00:00:02Z",
        content_hash="hash-a",
        byte_offset=0,
        line_no=1,
    )
    second = build_raw_origin_event(
        source_system="codex",
        computer_id="machine-a",
        native_session_key="session-a",
        source_path="/tmp/source.jsonl",
        raw_path="/tmp/raw.jsonl",
        source_exists=True,
        raw_exists=True,
        event_time="2026-06-08T00:00:00Z",
        captured_at="2026-06-08T00:00:01Z",
        audit_time="2026-06-08T00:00:02Z",
        content_hash="hash-a",
        byte_offset=0,
        line_no=1,
    )

    assert first["origin_id"] == second["origin_id"]
    assert first["origin_contract"] == "tiandao_time_origin.v1"
    assert first["time_river_contract"] == "tiandao_time_river.v1"
    assert first["origin_layer"] == "raw"
    assert first["origin_status"] == "origin_witnessed"
    assert first["origin_seen"] is True
    assert first["no_raw_no_river"] is True
    assert first["platform_policy"] == "platforms_are_inlets_not_origin"
    assert first["river_endpoint_policy"] == "time_river_has_no_endpoint"


def test_raw_origin_event_uses_lost_source_and_lost_raw_labels():
    from raw_origin_event import (
        build_raw_origin_event,
        classify_origin_status,
        origin_status_label,
    )

    assert classify_origin_status(source_exists=True, raw_exists=False) == "lost_raw"
    assert classify_origin_status(source_exists=False, raw_exists=True) == "lost_source"
    assert origin_status_label("lost_raw") == "遗失 raw"
    assert origin_status_label("lost_source") == "遗失源"

    lost_raw = build_raw_origin_event(
        source_system="openclaw",
        source_path="/tmp/source.jsonl",
        source_exists=True,
        raw_exists=False,
    )
    lost_source = build_raw_origin_event(
        source_system="claude_desktop",
        raw_path="/tmp/raw.jsonl",
        source_exists=False,
        raw_exists=True,
    )

    assert lost_raw["origin_status"] == "lost_raw"
    assert lost_raw["origin_label"] == "遗失 raw"
    assert lost_raw["origin_seen"] is False
    assert lost_source["origin_status"] == "lost_source"
    assert lost_source["origin_label"] == "遗失源"


def test_origin_summary_splits_lost_source_recoverability_tri_state():
    from raw_origin_event import build_raw_origin_event, origin_summary

    records = []
    for index, value in enumerate((True, False, None), start=1):
        event = build_raw_origin_event(
            source_system="claude_desktop",
            native_session_key=f"session-{index}",
            raw_path=f"/tmp/raw-{index}.jsonl",
            source_exists=False,
            raw_exists=True,
            content_hash=f"hash-{index}",
        )
        records.append({
            "origin_event": event,
            "origin_status": "lost_source",
            "recoverable_from_raw": value,
            "sync": {},
        })

    summary = origin_summary(records)

    assert summary["lost_source_count"] == 3
    assert summary["lost_source_recoverable_count"] == 1
    assert summary["lost_source_unrecoverable_count"] == 1
    assert summary["lost_source_not_measured_count"] == 1
    assert (
        summary["lost_source_recoverable_count"]
        + summary["lost_source_unrecoverable_count"]
        + summary["lost_source_not_measured_count"]
    ) == summary["lost_source_count"]


def test_platform_source_system_is_inlet_not_time_origin():
    from raw_origin_event import build_raw_origin_event

    events = [
        build_raw_origin_event(
            source_system=source_system,
            computer_id="machine-a",
            native_session_key=f"{source_system}-session",
            source_path=f"/tmp/{source_system}.jsonl",
            raw_path=f"/tmp/{source_system}.raw.jsonl",
            source_exists=True,
            raw_exists=True,
            content_hash=f"hash-{source_system}",
        )
        for source_system in ("codex", "openclaw", "claude_desktop")
    ]

    assert {event["source_system"] for event in events} == {"codex", "openclaw", "claude_desktop"}
    assert {event["source_refs"]["source_system"] for event in events} == {"codex", "openclaw", "claude_desktop"}
    assert {event["origin_layer"] for event in events} == {"raw"}
    assert {event["origin_contract"] for event in events} == {"tiandao_time_origin.v1"}
    assert {event["platform_policy"] for event in events} == {"platforms_are_inlets_not_origin"}
    assert {event["origin_seen"] for event in events} == {True}
    assert {event["no_raw_no_river"] for event in events} == {True}
    assert {event["platform_write_performed"] for event in events} == {False}
    assert {event["memory_write_performed"] for event in events} == {False}


def test_origin_summary_reports_first_witnessed_raw_per_local_runtime():
    from raw_origin_event import build_raw_origin_event, origin_summary

    def record(event):
        return {"origin_event": event, "origin_status": event["origin_status"]}

    later_codex = build_raw_origin_event(
        source_system="codex",
        computer_id="machine-a",
        native_session_key="codex-later",
        source_path="/tmp/source-codex-later.jsonl",
        raw_path="/tmp/raw-codex-later.jsonl",
        source_exists=True,
        raw_exists=True,
        event_time="2026-06-22T09:00:00Z",
        audit_time="2026-06-22T09:00:02Z",
        content_hash="hash-codex-later",
    )
    first_codex = build_raw_origin_event(
        source_system="codex",
        computer_id="machine-a",
        native_session_key="codex-first",
        source_path="/tmp/source-codex-first.jsonl",
        raw_path="/tmp/raw-codex-first.jsonl",
        source_exists=True,
        raw_exists=True,
        event_time="2026-06-22T08:00:00Z",
        audit_time="2026-06-22T08:00:02Z",
        content_hash="hash-codex-first",
    )
    first_openclaw = build_raw_origin_event(
        source_system="openclaw",
        computer_id="machine-a",
        native_session_key="openclaw-first",
        source_path="/tmp/source-openclaw-first.jsonl",
        raw_path="/tmp/raw-openclaw-first.jsonl",
        source_exists=True,
        raw_exists=True,
        event_time="2026-06-22T07:00:00Z",
        audit_time="2026-06-22T07:00:02Z",
        content_hash="hash-openclaw-first",
    )
    first_other_machine = build_raw_origin_event(
        source_system="codex",
        computer_id="machine-b",
        native_session_key="codex-machine-b-first",
        source_path="/tmp/source-codex-machine-b.jsonl",
        raw_path="/tmp/raw-codex-machine-b.jsonl",
        source_exists=True,
        raw_exists=True,
        event_time="2026-06-22T06:00:00Z",
        audit_time="2026-06-22T06:00:02Z",
        content_hash="hash-codex-machine-b",
    )
    lost_source_is_not_first = build_raw_origin_event(
        source_system="codex",
        computer_id="machine-a",
        native_session_key="codex-lost-source",
        raw_path="/tmp/raw-codex-lost-source.jsonl",
        source_exists=False,
        raw_exists=True,
        event_time="2026-06-22T05:00:00Z",
        audit_time="2026-06-22T05:00:02Z",
        content_hash="hash-codex-lost-source",
    )

    summary = origin_summary([
        record(later_codex),
        record(first_codex),
        record(first_openclaw),
        record(first_other_machine),
        record(lost_source_is_not_first),
    ])

    first_by_key = {
        item["local_runtime_key"]: item for item in summary["local_runtime_first_witnessed_raw"]
    }

    assert summary["local_runtime_policy"] == "each_runtime_has_first_witnessed_raw_event"
    assert summary["local_runtime_scope"] == "observed_repository_records_only"
    assert summary["local_runtime_grouping"] == ["computer_id", "source_system"]
    assert summary["local_runtime_order"] == ["event_time", "audit_time", "origin_id"]
    assert summary["local_runtime_first_witnessed_raw_count"] == 3
    assert sorted(first_by_key) == [
        "machine-a:codex",
        "machine-a:openclaw",
        "machine-b:codex",
    ]
    assert first_by_key["machine-a:codex"]["origin_id"] == first_codex["origin_id"]
    assert first_by_key["machine-a:codex"]["event_time"] == "2026-06-22T08:00:00Z"
    assert first_by_key["machine-a:codex"]["origin_seen"] is True
    assert first_by_key["machine-a:openclaw"]["origin_id"] == first_openclaw["origin_id"]
    assert first_by_key["machine-b:codex"]["origin_id"] == first_other_machine["origin_id"]
    assert lost_source_is_not_first["origin_id"] not in {
        item["origin_id"] for item in summary["local_runtime_first_witnessed_raw"]
    }
    assert summary["raw_without_source_count"] == 1
    assert summary["no_raw_no_river"] is True
    assert summary["multi_machine_policy"] == "source_streams_merge_not_overwrite"
