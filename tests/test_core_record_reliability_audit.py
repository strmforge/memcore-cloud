import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "core_record_reliability_audit.py"


def _load_audit():
    spec = importlib.util.spec_from_file_location("core_record_reliability_audit_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _guardian_report(records, **summary_overrides):
    summary = {
        "record_count": len(records),
        "record_guarded_count": len([
            item for item in records
            if item.get("guard_status") in {"record_guarded", "record_stat_guarded"}
        ]),
        "raw_not_current_count": len([
            item for item in records
            if item.get("guard_status") in {"raw_missing", "raw_lagging", "raw_catching_up"}
        ]),
        "raw_catching_up_count": len([
            item for item in records
            if item.get("guard_status") == "raw_catching_up"
        ]),
        "raw_attention_count": len([
            item for item in records
            if item.get("guard_status") in {"raw_missing", "raw_lagging", "source_corrupt", "raw_corrupt"}
            or item.get("backfill_recommended")
        ]),
        "backfill_recommended_count": len([item for item in records if item.get("backfill_recommended")]),
        "lost_source_count": 0,
        "lost_raw_count": 0,
        "inactive_source_count": 0,
        "gap_source_count": 0,
        "corrupt_record_count": len([
            item for item in records
            if item.get("guard_status") in {"source_corrupt", "raw_corrupt"}
        ]),
        "partial_record_count": 0,
        "max_raw_lag_bytes": 0,
        "max_raw_lag_milliseconds": 0,
    }
    summary.update(summary_overrides)
    return {
        "ok": not summary["raw_attention_count"],
        "contract": "raw_record_guardian.v1",
        "index_contract": "canonical_record_index.v2",
        "time_origin_contract": "raw_origin_event_summary.v1",
        "summary": summary,
        "records": records,
        "inactive_sources": [],
        "gap_sources": [],
    }


def _record(source, status="record_stat_guarded", *, backfill=False, co_sources=None):
    return {
        "source_system": source,
        "co_source_systems": co_sources or [],
        "artifact_type": f"{source}_artifact",
        "session_id": f"{source}-session",
        "canonical_window_id": f"{source}-window",
        "thread_name": f"{source} thread",
        "guard_status": status,
        "backfill_recommended": backfill,
        "recoverable_from_raw": status in {"record_guarded", "record_stat_guarded"},
        "source_scan": {"exists": True, "health_status": "stat_only"},
        "raw_scan": {"exists": status != "raw_missing", "health_status": "stat_only"},
    }


def test_core_record_reliability_audit_passes_when_core_sources_are_guarded():
    audit = _load_audit()
    records = [_record(source) for source in audit.DEFAULT_FOCUS_SOURCES]

    result = audit.classify_report(_guardian_report(records))

    assert result["ok"] is True
    assert result["contract"] == "memcore_core_record_reliability_audit.v1"
    assert result["audience"] == "maintainer_only_not_product_ui"
    assert result["audit_status"] == "pass"
    assert result["record_chain_proven"] is True
    assert result["write_performed"] is False
    assert result["service_call_performed"] is False


def test_core_record_reliability_audit_observes_short_catching_up_without_failure():
    audit = _load_audit()
    records = [
        _record("codex", "raw_catching_up"),
        _record("claude_desktop"),
    ]

    result = audit.classify_report(_guardian_report(records), focus_sources=("codex", "claude_desktop"))

    assert result["ok"] is True
    assert result["audit_status"] == "observe"
    assert result["attention_required"] is False
    assert "Re-sample after the active append window" in " ".join(result["action_items"])


def test_core_record_reliability_audit_keeps_active_divergence_generation_visible():
    audit = _load_audit()
    records = [_record("codex", "source_divergence_generation_active")]

    result = audit.classify_report(
        _guardian_report(
            records,
            raw_attention_count=1,
            raw_divergence_generation_active_count=1,
        ),
        focus_sources=("codex",),
    )

    assert result["ok"] is False
    assert result["audit_status"] == "attention"
    assert result["source_statuses"][0]["state"] == "attention"
    assert result["summary"]["raw_divergence_generation_active_count"] == 1
    assert result["summary"]["backfill_recommended_count"] == 0


def test_core_record_reliability_audit_treats_source_partial_as_observation():
    audit = _load_audit()
    records = [
        _record("hermes", "source_partial_conversation"),
        _record("claude_code_cli", "record_guarded"),
    ]

    result = audit.classify_report(
        _guardian_report(records, partial_record_count=1),
        focus_sources=("hermes", "claude_code_cli"),
    )

    assert result["ok"] is True
    assert result["audit_status"] == "observe"
    assert result["attention_required"] is False
    by_source = {item["source_system"]: item for item in result["source_statuses"]}
    assert by_source["hermes"]["state"] == "source_partial_samples"
    assert by_source["hermes"]["partial_sample_count"] == 1


def test_core_record_reliability_audit_escalates_backfill_recommendation():
    audit = _load_audit()
    records = [
        _record("codex", "raw_missing", backfill=True),
        _record("claude_desktop"),
    ]

    result = audit.classify_report(_guardian_report(records), focus_sources=("codex", "claude_desktop"))

    assert result["ok"] is False
    assert result["audit_status"] == "needs_backfill"
    assert result["attention_required"] is True
    assert result["issue_sources"] == ["codex"]
    assert result["issue_samples"][0]["guard_status"] == "raw_missing"
    assert "explicit raw backfill" in " ".join(result["action_items"])


def test_core_record_reliability_audit_treats_inactive_sample_as_non_failure():
    audit = _load_audit()
    report = _guardian_report(
        [],
        inactive_source_count=2,
    )
    report["inactive_sources"] = ["openclaw", "hermes"]

    result = audit.classify_report(report, focus_sources=("openclaw", "hermes"))

    assert result["ok"] is True
    assert result["audit_status"] == "needs_samples"
    assert result["attention_required"] is False
    by_source = {item["source_system"]: item for item in result["source_statuses"]}
    assert by_source["openclaw"]["state"] == "inactive_no_live_source_sample"
    assert by_source["hermes"]["state"] == "inactive_no_live_source_sample"


def test_core_record_reliability_audit_treats_lost_source_and_lost_raw_as_attention():
    audit = _load_audit()

    result = audit.classify_report(
        _guardian_report([_record("codex")], lost_source_count=1, lost_raw_count=1),
        focus_sources=("codex",),
    )

    assert result["ok"] is False
    assert result["audit_status"] == "attention"
    actions = " ".join(result["action_items"])
    assert "遗失 raw" in actions
    assert "遗失源" in actions


def test_core_record_reliability_audit_passes_recoverable_lost_source():
    audit = _load_audit()
    record = _record("claude_desktop", "source_missing_recoverable_from_raw")
    record["recoverable_from_raw"] = True

    result = audit.classify_report(
        _guardian_report(
            [record],
            lost_source_count=1,
            lost_source_recoverable_count=1,
            lost_source_unrecoverable_count=0,
            lost_source_not_measured_count=0,
        ),
        focus_sources=("claude_desktop",),
    )

    assert result["ok"] is True
    assert result["audit_status"] == "pass"
    assert result["attention_required"] is False


def test_core_record_reliability_audit_observes_unmeasured_lost_source():
    audit = _load_audit()
    record = _record("claude_desktop", "source_missing_recoverability_unmeasured")
    record["recoverable_from_raw"] = None

    result = audit.classify_report(
        _guardian_report(
            [record],
            lost_source_count=1,
            lost_source_recoverable_count=0,
            lost_source_unrecoverable_count=0,
            lost_source_not_measured_count=1,
        ),
        focus_sources=("claude_desktop",),
    )

    assert result["ok"] is True
    assert result["audit_status"] == "observe"
    assert result["attention_required"] is False


def test_core_record_reliability_audit_contract_only_mode_is_release_gate_safe():
    audit = _load_audit()

    result = audit.build_audit(contract_only=True)

    assert result["ok"] is True
    assert result["audit_status"] == "contract_only"
    assert result["read_only"] is True
    assert result["service_call_performed"] is False
    assert "Contract-only mode" in result["notes"][0]


def test_core_record_reliability_audit_ignores_invalid_env_root_when_install_root_exists(tmp_path, monkeypatch):
    audit = _load_audit()
    invalid_root = tmp_path / "ProgramData" / "memcore-cloud"
    install_root = tmp_path / "LocalAppData" / "memcore-cloud"
    (install_root / "config").mkdir(parents=True)
    (install_root / "config" / "memcore.json").write_text("{}", encoding="utf-8")
    invalid_root.mkdir(parents=True)
    monkeypatch.setenv("MEMCORE_ROOT", str(invalid_root))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    monkeypatch.delenv("MEMCORE_CONFIG", raising=False)
    monkeypatch.setattr(audit.platform, "system", lambda: "Windows")

    runtime = audit.prepare_runtime_environment("auto")

    assert runtime["runtime_root"] == str(install_root)
    assert runtime["runtime_root_source"] == "auto_install_root_ignored_invalid_env_MEMCORE_ROOT"
    assert runtime["runtime_config_exists"] is True
    assert runtime["ignored_invalid_env_root"] == str(invalid_root)
