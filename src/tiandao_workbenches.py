#!/usr/bin/env python3
"""Read-only Tiandao workbench aggregation.

This module does not create a new memory layer. It gathers existing evidence
from the record guardian, Second Brain, platform guard, Zhixing governance, and
Hermes learning surfaces so the console can show whether the current system is
coherent enough to keep working from.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

try:
    from raw_record_recoverability import lost_source_triage as _lost_source_triage
except ImportError:  # pragma: no cover
    from src.raw_record_recoverability import lost_source_triage as _lost_source_triage

try:
    from src.continuous_sync_status import build_continuous_sync_status
    from src.material_processing_pipeline import get_material_processing_pipeline_contract
    from src.platform_thin_adapter_registry import build_platform_discovery_dashboard
    from src.raw_record_guardian import build_guardian_status
    from src.second_brain import get_second_brain_contract
    from src.tiandao import time_twin_star_runtime_status
    from src.time_twin_star_source_canon import time_twin_star_source_canon_entry
    from src.zhixing_library import benchmark_plan, library_manifest, replay_plan, zhixing_loop_manifest
except Exception:  # pragma: no cover - direct script import fallback
    from continuous_sync_status import build_continuous_sync_status
    from material_processing_pipeline import get_material_processing_pipeline_contract
    from platform_thin_adapter_registry import build_platform_discovery_dashboard
    from raw_record_guardian import build_guardian_status
    from second_brain import get_second_brain_contract
    from tiandao import time_twin_star_runtime_status
    from time_twin_star_source_canon import time_twin_star_source_canon_entry
    from zhixing_library import benchmark_plan, library_manifest, replay_plan, zhixing_loop_manifest


TIANDAO_WORKBENCHES_VERSION = "2026.6.8"
TIANDAO_WORKBENCHES_CONTRACT = "tiandao_workbenches.v1"

WORKBENCH_IDS = (
    "origin_guard",
    "second_brain",
    "platform_guard",
    "experience_governance",
    "hermes_learning_observatory",
)


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "ok"}


def _safe_call(name: str, func: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    try:
        result = func()
        if isinstance(result, dict):
            return result
        return {"ok": False, "error": f"{name}_returned_non_object"}
    except Exception as exc:
        return {"ok": False, "error": f"{name}_failed:{type(exc).__name__}:{str(exc)[:180]}"}


def _read_only_boundary() -> dict[str, Any]:
    return {
        "read_only": True,
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "model_call_performed": False,
        "network_call_performed": False,
    }


def _time_twin_star_runtime_status() -> dict[str, Any]:
    """Return the first-class Time Twin Star status with source-canon lineage.

    The source-canon module is a subordinate projection for audit continuity; it
    must not replace the Time Twin Star surface/status route.
    """

    try:
        status = time_twin_star_runtime_status()
    except Exception:
        status = {}
    try:
        source_canon = time_twin_star_source_canon_entry()
    except Exception:
        source_canon = {}
    if isinstance(status, dict) and status:
        result = dict(status)
        result["source_canon_projection"] = source_canon if isinstance(source_canon, dict) else {}
        result["source_canon_lineage"] = "subordinate_projection_not_successor"
        result["not_runtime_proof"] = result.get("installed_runtime_status") != "installed_runtime_route_present"
        return result
    counts = source_canon.get("rule_status_counts_from_tiandao_v1") if isinstance(source_canon, dict) else {}
    return {
        "ok": False,
        "contract": "time_twin_star_runtime_status.v1",
        "projection_contract": str(source_canon.get("surface_contract") or "time_tiandao_surface.v1") if isinstance(source_canon, dict) else "time_tiandao_surface.v1",
        "runtime_status": "time_twin_star_runtime_status_unavailable",
        "installed_runtime_status": "not_proven",
        "rule_status_counts": counts if isinstance(counts, dict) else {},
        "source_canon_projection": source_canon if isinstance(source_canon, dict) else {},
        "source_canon_lineage": "subordinate_projection_not_successor",
        **_read_only_boundary(),
        "not_runtime_proof": True,
        "reason": "time_twin_star_runtime_status_unavailable_source_canon_projection_only",
    }


def _origin_guard(
    guardian: dict[str, Any],
    continuous_sync: dict[str, Any],
    time_twin_star: dict[str, Any],
) -> dict[str, Any]:
    summary = guardian.get("summary") if isinstance(guardian.get("summary"), dict) else {}
    summary_scope = guardian.get("summary_scope") if isinstance(guardian.get("summary_scope"), dict) else {}
    sync_summary = continuous_sync.get("summary") if isinstance(continuous_sync.get("summary"), dict) else {}
    watcher = continuous_sync.get("watcher") if isinstance(continuous_sync.get("watcher"), dict) else {}
    raw_not_current = _safe_int(summary.get("raw_not_current_count"))
    raw_lagging_or_missing = _safe_int(summary.get("raw_lagging_or_missing_count"))
    raw_catching_up = _safe_int(summary.get("raw_catching_up_count"))
    backfill = _safe_int(summary.get("backfill_recommended_count"))
    raw_attention = _safe_int(
        summary.get("raw_attention_count"),
        backfill,
    )
    lost_source, recoverable_source, unrecoverable_source, unmeasured_source = _lost_source_triage(summary)
    lost_raw = _safe_int(summary.get("lost_raw_count"))
    corrupt = _safe_int(summary.get("corrupt_record_count"))
    ok = (
        bool(guardian.get("ok"))
        and raw_attention == 0
        and backfill == 0
        and corrupt == 0
        and unrecoverable_source == 0
        and lost_raw == 0
    )
    health = "ok" if ok else "needs_attention"
    if unrecoverable_source or lost_raw:
        health = "lost_evidence_detected"
    elif raw_attention or backfill:
        health = "raw_not_current"
    elif unmeasured_source:
        health = "recoverability_unmeasured"
    elif raw_catching_up:
        health = "raw_catching_up"
    elif summary_scope.get("summary_is_sample"):
        health = "population_scope_incomplete"
        ok = False
    return {
        "id": "origin_guard",
        "zh_name": "时间起源守护",
        "en_name": "Origin Guard",
        "role": "prove_source_and_raw_are_current_before_any_memory_claim",
        "health": health,
        "ok": ok,
        **_read_only_boundary(),
        "contracts": [
            guardian.get("time_origin_contract") or "tiandao_time_origin.v1",
            time_twin_star.get("projection_contract") or "time_tiandao_surface.v1",
            time_twin_star.get("contract") or "time_twin_star_source_canon_status.v1",
            guardian.get("contract") or "raw_record_guardian.v1",
            guardian.get("index_contract") or "canonical_record_index.v2",
            continuous_sync.get("tiandao_contract") or continuous_sync.get("contract") or "continuous_local_chat_sync.v1",
        ],
        "summary": {
            "record_count": _safe_int(summary.get("record_count")),
            "physical_record_count": _safe_int(summary.get("physical_record_count")),
            "logical_record_count": _safe_int(summary.get("logical_record_count")),
            "layout_variant_count": _safe_int(summary.get("layout_variant_count")),
            "record_guarded_count": _safe_int(summary.get("record_guarded_count")),
            "raw_not_current_count": raw_not_current,
            "raw_attention_count": raw_attention,
            "raw_divergence_generation_active_count": _safe_int(
                summary.get("raw_divergence_generation_active_count")
            ),
            "raw_metadata_only_divergence_count": _safe_int(summary.get("raw_metadata_only_divergence_count")),
            "raw_lagging_or_missing_count": raw_lagging_or_missing,
            "raw_catching_up_count": raw_catching_up,
            "lost_source_count": lost_source,
            "lost_source_recoverable_count": recoverable_source,
            "lost_source_unrecoverable_count": unrecoverable_source,
            "lost_source_not_measured_count": unmeasured_source,
            "lost_source_one_sided_count": _safe_int(summary.get("lost_source_one_sided_count")),
            "lost_source_non_conversation_count": _safe_int(summary.get("lost_source_non_conversation_count")),
            "lost_raw_count": lost_raw,
            "backfill_recommended_count": backfill,
            "origin_event_count": _safe_int(summary.get("origin_event_count")),
            "max_raw_lag_milliseconds": _safe_int(summary.get("max_raw_lag_milliseconds")),
            "millisecond_level_source_count": _safe_int(sync_summary.get("millisecond_level_source_count")),
            "collector_pending_count": _safe_int(sync_summary.get("collector_pending_count")),
            "watcher_active": watcher.get("active"),
            "target_latency_milliseconds": _safe_int(watcher.get("target_latency_milliseconds")),
            "time_twin_star_runtime_status": time_twin_star.get("runtime_status"),
            "time_twin_star_installed_runtime_status": time_twin_star.get("installed_runtime_status"),
            "time_twin_star_source_proven_count": _safe_int(
                (time_twin_star.get("rule_status_counts") or {}).get("source_proven")
            ),
            "time_twin_star_contract_only_count": _safe_int(
                (time_twin_star.get("rule_status_counts") or {}).get("contract_only")
            ),
            "time_twin_star_planned_count": _safe_int(
                (time_twin_star.get("rule_status_counts") or {}).get("planned")
            ),
        },
        "evidence": {
            "guardian_summary": summary,
            "guardian_summary_scope": summary_scope,
            "continuous_sync_summary": sync_summary,
            "time_twin_star_status": time_twin_star,
            "gap_sources": guardian.get("gap_sources", []),
            "inactive_sources": guardian.get("inactive_sources", []),
            "claude_desktop_evidence": guardian.get("claude_desktop_evidence", {}),
        },
        "endpoints": [
            "/api/v1/records/guardian/status?limit=80&mode=fast&compact=1",
            "/api/v1/records/canonical-index",
            "/api/v1/source-systems/continuous-sync/status",
            "/api/v1/tiandao/time-twin-star/status",
        ],
        "next_actions": [
            "repair_unrecoverable_source_or_lost_raw_first" if (unrecoverable_source or lost_raw) else "",
            "complete_bounded_recoverability_evidence" if unmeasured_source else "",
            "run_explicit_backfill_if_raw_not_current" if backfill else "",
            "watch_active_tail_catchup_without_marking_record_lost" if (raw_catching_up and not raw_attention and not backfill) else "",
            "keep_canonical_index_as_ui_and_recovery_base",
        ],
    }


def _second_brain(contract: dict[str, Any], material_contract: dict[str, Any]) -> dict[str, Any]:
    ok = bool(contract.get("ok")) and bool(material_contract.get("ok"))
    return {
        "id": "second_brain",
        "zh_name": "第二大脑",
        "en_name": "Second Brain",
        "role": "turn_large_material_sets_into_reviewable_candidates_under_time_river",
        "health": "ready" if ok else "contract_missing",
        "ok": ok,
        **_read_only_boundary(),
        "contracts": [
            contract.get("contract") or "tiandao_second_brain.v1",
            material_contract.get("contract") or "zhixing_material_processing_pipeline.v1",
            contract.get("parent_tiandao_contract") or "tiandao_time_river.v1",
        ],
        "summary": {
            "orchestrated_module_count": len(contract.get("orchestrated_modules") or []),
            "pipeline_stage_count": len(material_contract.get("pipeline_stages") or []),
            "default_batch_size": _safe_int(material_contract.get("default_batch_size")),
            "default_wip_limit": _safe_int(material_contract.get("default_wip_limit")),
            "network_call_performed": bool(contract.get("network_call_performed") or material_contract.get("network_call_performed")),
            "raw_authority_preserved": bool(material_contract.get("raw_authority_preserved")),
        },
        "evidence": {
            "second_brain_contract": contract,
            "material_pipeline_contract": material_contract,
        },
        "endpoints": [
            "/api/v1/tiandao/second-brain/contract",
            "/api/v1/tiandao/second-brain/dry-run",
            "/api/v1/zhixing/material-processing-pipeline/contract",
        ],
        "next_actions": [
            "use_batch_screening_before_full_text_review",
            "promote_only_candidate_records_after_sample_check",
        ],
    }


def _platform_guard(discovery: dict[str, Any]) -> dict[str, Any]:
    counts = discovery.get("counts") if isinstance(discovery.get("counts"), dict) else {}
    items = discovery.get("items") if isinstance(discovery.get("items"), list) else []
    detected = _safe_int(counts.get("detected") or len([item for item in items if item.get("detected")]))
    ready = _safe_int(counts.get("ready_for_capability_check"))
    auto_ready = _safe_int(counts.get("auto_connect_ready"))
    other_tools = _safe_int(counts.get("other_local_tools"))
    return {
        "id": "platform_guard",
        "zh_name": "平台守护",
        "en_name": "Platform Guard",
        "role": "detect_local_ai_tools_without_confusing_detection_with_record_capture",
        "health": "detected" if detected else "no_local_tool_sample",
        "ok": bool(discovery.get("ok", True)),
        **_read_only_boundary(),
        "contracts": [
            discovery.get("contract") or "platform_discovery_dashboard.v1",
            "tiandao_thin_adapter_registry.v1",
        ],
        "summary": {
            "detected_tool_count": detected,
            "ready_for_capability_check_count": ready,
            "auto_connect_ready_count": auto_ready,
            "other_local_tool_count": other_tools,
            "record_capture_proven_count": 0,
            "discovered_is_not_captured": True,
            "model_call_performed": bool(discovery.get("model_call_performed")),
        },
        "evidence": {
            "counts": counts,
            "item_count": len(items),
        },
        "endpoints": [
            "/api/v1/platforms/discovery-dashboard",
            "/api/v1/platforms/thin-adapter-registry",
        ],
        "next_actions": [
            "capability_check_before_any_connection",
            "record_guardian_must_confirm_capture_after_detection",
        ],
    }


def _experience_governance(
    governance_stats: dict[str, Any],
    manifest: dict[str, Any],
    replay: dict[str, Any],
    benchmark: dict[str, Any],
    loop: dict[str, Any],
) -> dict[str, Any]:
    shelves = manifest.get("shelves") if isinstance(manifest.get("shelves"), dict) else {}
    return {
        "id": "experience_governance",
        "zh_name": "经验治理",
        "en_name": "Experience Governance",
        "role": "keep_zhiyi_xingce_toolbook_candidates_reviewable_replayable_and_source_backed",
        "health": "dry_run_governed" if governance_stats.get("dry_run_only", True) else "check_required",
        "ok": bool(manifest.get("enabled", True)),
        **_read_only_boundary(),
        "contracts": [
            manifest.get("contract") or "zhixing_library.v1",
            replay.get("contract") or "zhixing_replay_plan.v1",
            benchmark.get("contract") or "zhixing_benchmark_plan.v1",
            loop.get("contract") or "zhixing_loop.v1",
        ],
        "summary": {
            "shelf_count": len(shelves),
            "total_proposals": _safe_int(governance_stats.get("total_proposals")),
            "applied_count": _safe_int(governance_stats.get("applied_count")),
            "dry_run_only": governance_stats.get("dry_run_only", True),
            "replay_plan_present": bool(replay),
            "benchmark_plan_present": bool(benchmark),
            "raw_is_source_text": bool(manifest.get("raw_is_source_text", True)),
        },
        "evidence": {
            "library_manifest": manifest,
            "governance_stats": governance_stats,
            "replay_plan": replay,
            "benchmark_plan": benchmark,
            "loop_manifest": loop,
        },
        "endpoints": [
            "/api/v1/zhixing/library",
            "/api/v1/zhixing/replay/plan",
            "/api/v1/zhixing/benchmark/plan",
            "/api/v1/experience-service/stats",
        ],
        "next_actions": [
            "replay_before_adoption",
            "errata_or_supersession_when_experience_conflicts",
        ],
    }


def _count_items(payload: dict[str, Any]) -> int:
    if not isinstance(payload, dict):
        return 0
    for key in ("items", "triggers", "probes", "statuses", "receipts"):
        value = payload.get(key)
        if isinstance(value, list):
            return len(value)
    return _safe_int(payload.get("total") or payload.get("count"))


def _hermes_learning_observatory(
    liveness: dict[str, Any],
    triggers: dict[str, Any],
    probes: dict[str, Any],
    statuses: dict[str, Any],
    diff_plan: dict[str, Any],
    report_plan: dict[str, Any],
) -> dict[str, Any]:
    skill_snapshot = liveness.get("skill_snapshot") if isinstance(liveness.get("skill_snapshot"), dict) else {}
    latest_skill = liveness.get("latest_skill_file") if isinstance(liveness.get("latest_skill_file"), dict) else {}
    return {
        "id": "hermes_learning_observatory",
        "zh_name": "Hermes 学习观察台",
        "en_name": "Hermes Learning Observatory",
        "role": "observe_hermes_native_learning_receipts_without_mutating_hermes_skills",
        "health": "observable" if liveness.get("ok", True) else "check_required",
        "ok": bool(liveness.get("ok", True)),
        **_read_only_boundary(),
        "contracts": [
            liveness.get("contract") or "hermes_native_learning_liveness.v1",
            diff_plan.get("contract") or "hermes_skill_experience_diff.v1",
            report_plan.get("contract") or "hermes_self_review_report.v1",
        ],
        "summary": {
            "native_learning_observed": bool(liveness.get("native_learning_observed") or liveness.get("learning_signal_detected")),
            "skill_file_count": _safe_int(skill_snapshot.get("file_count") or latest_skill.get("skill_file_count")),
            "self_review_trigger_count": _count_items(triggers),
            "skill_generation_probe_count": _count_items(probes),
            "skill_artifact_status_count": _count_items(statuses),
            "time_library_does_not_write_hermes_skills": True,
        },
        "evidence": {
            "liveness": liveness,
            "self_review_triggers": triggers,
            "skill_generation_probes": probes,
            "skill_artifact_statuses": statuses,
            "skill_experience_diff_plan": diff_plan,
            "self_review_report_plan": report_plan,
        },
        "endpoints": [
            "/api/v1/hermes/native-learning/liveness",
            "/api/v1/hermes/native-learning/self-review/triggers",
            "/api/v1/hermes/native-learning/skill-generation/probes",
            "/api/v1/hermes/native-learning/skill-artifact-statuses",
        ],
        "next_actions": [
            "record_native_receipts_before_claiming_learning_effect",
            "compare_generated_skills_against_source_backed_experience",
        ],
    }


def _safe_default_governance_stats() -> dict[str, Any]:
    return {
        "total_proposals": 0,
        "by_type": {},
        "by_status": {"draft": 0},
        "dry_run_only": True,
        "applied_count": 0,
    }


def get_tiandao_workbenches_contract() -> dict[str, Any]:
    return {
        "ok": True,
        "version": TIANDAO_WORKBENCHES_VERSION,
        "contract": TIANDAO_WORKBENCHES_CONTRACT,
        "zh_name": "五大工作台",
        "en_name": "Five Workbenches",
        **_read_only_boundary(),
        "parent_contracts": [
            "tiandao_time_origin.v1",
            "tiandao_time_river.v1",
            "raw_record_guardian.v1",
            "tiandao_second_brain.v1",
        ],
        "workbench_ids": list(WORKBENCH_IDS),
        "required_workbenches": [
            {"id": "origin_guard", "zh_name": "时间起源守护", "en_name": "Origin Guard"},
            {"id": "second_brain", "zh_name": "第二大脑", "en_name": "Second Brain"},
            {"id": "platform_guard", "zh_name": "平台守护", "en_name": "Platform Guard"},
            {"id": "experience_governance", "zh_name": "经验治理", "en_name": "Experience Governance"},
            {"id": "hermes_learning_observatory", "zh_name": "Hermes 学习观察台", "en_name": "Hermes Learning Observatory"},
        ],
        "policies": {
            "raw_origin_first": True,
            "lost_wording": {"source": "遗失源", "raw": "遗失 raw"},
            "detection_is_not_capture": True,
            "second_brain_is_first_major_time_river_module": True,
            "external_tool_names_are_reference_only_not_public_dependency": True,
            "global_raw_pool_recall_requires_explicit_permission": True,
        },
        "endpoints": [
            "/api/v1/tiandao/workbenches/contract",
            "/api/v1/tiandao/workbenches/dashboard",
        ],
    }


def build_tiandao_workbenches_dashboard(
    *,
    watcher_active: bool | None = None,
    governance_stats: dict[str, Any] | None = None,
    hermes_liveness: dict[str, Any] | None = None,
    hermes_triggers: dict[str, Any] | None = None,
    hermes_probes: dict[str, Any] | None = None,
    hermes_statuses: dict[str, Any] | None = None,
    hermes_diff_plan: dict[str, Any] | None = None,
    hermes_report_plan: dict[str, Any] | None = None,
    guardian_limit: int = 80,
    scan_mode: str = "fast",
) -> dict[str, Any]:
    contract = get_tiandao_workbenches_contract()
    guardian = _safe_call(
        "record_guardian",
        lambda: build_guardian_status(
            limit=guardian_limit,
            include_gaps=True,
            write_index=False,
            scan_mode=scan_mode,
            compact=True,
            public=True,
        ),
    )
    continuous_sync = _safe_call(
        "continuous_sync",
        lambda: build_continuous_sync_status(watcher_active=watcher_active, include_generic=False),
    )
    time_twin_star = _safe_call("time_twin_star_runtime_status", _time_twin_star_runtime_status)
    second_brain_contract = _safe_call("second_brain_contract", get_second_brain_contract)
    material_contract = _safe_call("material_pipeline_contract", get_material_processing_pipeline_contract)
    discovery = _safe_call(
        "platform_discovery_dashboard",
        lambda: build_platform_discovery_dashboard(include_generic=False, public=True),
    )
    manifest = _safe_call("zhixing_library_manifest", library_manifest)
    replay = _safe_call("zhixing_replay_plan", replay_plan)
    benchmark = _safe_call("zhixing_benchmark_plan", benchmark_plan)
    loop = _safe_call("zhixing_loop_manifest", zhixing_loop_manifest)
    governance = governance_stats if isinstance(governance_stats, dict) else _safe_default_governance_stats()
    liveness = hermes_liveness if isinstance(hermes_liveness, dict) else {}
    triggers = hermes_triggers if isinstance(hermes_triggers, dict) else {}
    probes = hermes_probes if isinstance(hermes_probes, dict) else {}
    statuses = hermes_statuses if isinstance(hermes_statuses, dict) else {}
    diff_plan = hermes_diff_plan if isinstance(hermes_diff_plan, dict) else {}
    report_plan = hermes_report_plan if isinstance(hermes_report_plan, dict) else {}

    workbenches = [
        _origin_guard(guardian, continuous_sync, time_twin_star),
        _second_brain(second_brain_contract, material_contract),
        _platform_guard(discovery),
        _experience_governance(governance, manifest, replay, benchmark, loop),
        _hermes_learning_observatory(liveness, triggers, probes, statuses, diff_plan, report_plan),
    ]
    attention = [item for item in workbenches if item.get("health") not in {"ok", "ready", "detected", "dry_run_governed", "observable", "no_local_tool_sample", "raw_catching_up", "recoverability_unmeasured"}]
    origin = workbenches[0].get("summary", {})
    return {
        **contract,
        "generated_at": _ts(),
        "summary": {
            "workbench_count": len(workbenches),
            "ok_workbench_count": sum(1 for item in workbenches if _truthy(item.get("ok"))),
            "needs_attention_count": len(attention),
            "record_count": _safe_int(origin.get("record_count")),
            "record_guarded_count": _safe_int(origin.get("record_guarded_count")),
            "raw_not_current_count": _safe_int(origin.get("raw_not_current_count")),
            "raw_attention_count": _safe_int(origin.get("raw_attention_count")),
            "raw_lagging_or_missing_count": _safe_int(origin.get("raw_lagging_or_missing_count")),
            "raw_catching_up_count": _safe_int(origin.get("raw_catching_up_count")),
            "lost_source_count": _safe_int(origin.get("lost_source_count")),
            "lost_source_recoverable_count": _safe_int(origin.get("lost_source_recoverable_count")),
            "lost_source_unrecoverable_count": _safe_int(origin.get("lost_source_unrecoverable_count")),
            "lost_source_not_measured_count": _safe_int(origin.get("lost_source_not_measured_count")),
            "lost_raw_count": _safe_int(origin.get("lost_raw_count")),
            "backfill_recommended_count": _safe_int(origin.get("backfill_recommended_count")),
            "max_raw_lag_milliseconds": _safe_int(origin.get("max_raw_lag_milliseconds")),
            "millisecond_level_source_count": _safe_int(origin.get("millisecond_level_source_count")),
            "time_twin_star_source_proven_count": _safe_int(origin.get("time_twin_star_source_proven_count")),
            "time_twin_star_contract_only_count": _safe_int(origin.get("time_twin_star_contract_only_count")),
            "time_twin_star_planned_count": _safe_int(origin.get("time_twin_star_planned_count")),
            "time_twin_star_installed_runtime_status": origin.get("time_twin_star_installed_runtime_status"),
            "record_first_ready": _safe_int(origin.get("raw_attention_count")) == 0
            and _safe_int(origin.get("backfill_recommended_count")) == 0
            and _safe_int(origin.get("corrupt_record_count")) == 0
            and _safe_int(origin.get("lost_source_unrecoverable_count")) == 0
            and _safe_int(origin.get("lost_raw_count")) == 0,
        },
        "workbenches": workbenches,
        "source_reports": {
            "record_guardian": guardian,
            "continuous_sync": continuous_sync,
            "time_twin_star": time_twin_star,
            "platform_discovery": discovery,
        },
        "notes": [
            "This dashboard is a read-only aggregation of existing mechanisms.",
            "The first gate is record capture; derived memory is not trusted without source-backed raw evidence.",
            "Detected tools still need record guardian proof before being described as captured.",
        ],
    }
