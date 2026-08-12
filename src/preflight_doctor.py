#!/usr/bin/env python3
"""Read-only scored preflight doctor for Time Library.

The doctor does not create a new memory layer. It scores the already existing
connect doctor, hot-path work preflight, recall/experience benchmark, borrowing
receipts, and experience-evolution dry-run so an agent can see whether memory
is actually entering the work path before it starts changing code.
"""

from __future__ import annotations

import json
import math
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from src.port_discovery import resolve_client_url
except Exception:
    from port_discovery import resolve_client_url

try:
    from src.evidence_bound_model import (
        EVIDENCE_BOUND_MODEL_CONTRACT,
        EVIDENCE_BOUND_MODEL_GATING_CONTRACT,
        default_model_config,
    )
    from src.delivery_receipt import DELIVERY_RECEIPT_CONTRACT
    from src.evidence_atom_vocabulary import vocabulary_contract
    from src.public_metric_claim_gate import gate_public_metric_claim
    from src.productized_loops import build_productized_loops_doctor
    from src.search_think_contract import boundary_contract as search_think_boundary_contract
    from src.search_think_dry_run import dry_run_contract as search_think_dry_run_contract
except ImportError:  # pragma: no cover - direct script import fallback
    from evidence_bound_model import (
        EVIDENCE_BOUND_MODEL_CONTRACT,
        EVIDENCE_BOUND_MODEL_GATING_CONTRACT,
        default_model_config,
    )
    from delivery_receipt import DELIVERY_RECEIPT_CONTRACT
    from evidence_atom_vocabulary import vocabulary_contract
    from public_metric_claim_gate import gate_public_metric_claim
    from productized_loops import build_productized_loops_doctor
    from search_think_contract import boundary_contract as search_think_boundary_contract
    from search_think_dry_run import dry_run_contract as search_think_dry_run_contract


PREFLIGHT_DOCTOR_VERSION = "2026.6.17"
PREFLIGHT_DOCTOR_CONTRACT = "preflight_doctor.v2026.6.17"
PREFLIGHT_DOCTOR_SCORE_CONTRACT = "preflight_doctor_score_contract.v2026.6.17"
PREFLIGHT_ANSWER_DEBUG_CAPABILITY_CONTRACT = "preflight_answer_debug_capability.v2026.6.18"
DIALOG_ENTRY_ANSWER_DEBUG_CONTRACT = "dialog_entry_answer_debug.v2026.6.18"
LIVE_WORK_PREFLIGHT_SMOKE_CONTRACT = "preflight_doctor_live_work_preflight_smoke.v2026.6.18"
PREFLIGHT_DOCTOR_SMOKE_PROFILE_CONTRACT = "preflight_doctor_smoke_profile.v2026.6.18"
PREFLIGHT_DOCTOR_DEFAULT_WORK_ANCHOR_CONTRACT = "preflight_doctor_default_work_anchor.v2026.6.18"
PREFLIGHT_DOCTOR_WORK_ANCHOR_KEYS = (
    "session_id",
    "canonical_window_id",
    "project_id",
    "project_root",
    "workstream_id",
    "task_id",
)
PUBLIC_BENCHMARK_REFERENCE_SOURCES = {
    "locomo": {
        "project": "https://github.com/snap-research/locomo",
        "data_url": "https://raw.githubusercontent.com/snap-research/locomo/main/data/locomo10.json",
    },
    "longmemeval": {
        "project": "https://github.com/xiaowu0162/LongMemEval",
        "data_urls": {
            "oracle": "https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/main/longmemeval_oracle.json",
            "s": "https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/main/longmemeval_s_cleaned.json",
            "m": "https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/main/longmemeval_m_cleaned.json",
        },
    },
}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _items(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value in (None, ""):
        return default
    return str(value).strip().lower() not in {"0", "false", "no", "off"}


def _score(value: int | float) -> int:
    try:
        parsed = int(round(float(value)))
    except Exception:
        parsed = 0
    return max(0, min(parsed, 100))


def _positive_int(value: Any, default: int = 1, *, minimum: int = 1, maximum: int = 10) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = default
    return max(minimum, min(parsed, maximum))


def _score_item(
    score: int | float,
    *,
    status: str,
    signals: list[str] | None = None,
    attention: list[str] | None = None,
    next_actions: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "score": _score(score),
        "status": status,
        "signals": signals or [],
        "attention": attention or [],
        "next_actions": next_actions or [],
    }


def _write_boundary() -> dict[str, bool]:
    return {
        "read_only": True,
        "dry_run": True,
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "zhiyi_write_performed": False,
        "xingce_write_performed": False,
        "toolbook_write_performed": False,
        "errata_write_performed": False,
        "markdown_write_performed": False,
        "model_call_performed": False,
    }


def _default_work_anchor_disabled(body: dict[str, Any]) -> bool:
    return (
        _bool(body.get("disable_default_work_anchor"), False)
        or _bool(body.get("no_default_work_anchor"), False)
        or _bool(body.get("allow_scope_required_without_anchor"), False)
    )


def _apply_default_work_anchor(body: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    patched = dict(body)
    present = [
        key
        for key in PREFLIGHT_DOCTOR_WORK_ANCHOR_KEYS
        if patched.get(key) not in (None, "")
    ]
    disabled = _default_work_anchor_disabled(patched)
    if present:
        reason = "explicit_anchor_present"
    elif disabled:
        reason = "explicit_anchor_check_disabled_by_request"
    else:
        reason = "explicit_anchor_missing"
    applied = False
    return patched, {
        "contract": PREFLIGHT_DOCTOR_DEFAULT_WORK_ANCHOR_CONTRACT,
        "applied": applied,
        "disabled": disabled,
        "reason": reason,
        "canonical_window_id": str(patched.get("canonical_window_id") or ""),
        "anchor_keys_present": present,
        "policy": "platform_neutral_preflight_never_guesses_a_host_window",
        "scope_required_diagnostic_opt_out": "disable_default_work_anchor",
        "final_evidence_authority": "raw_source_refs",
    }


def _live_work_preflight_smoke(body: dict[str, Any]) -> dict[str, Any]:
    body, anchor_meta = _apply_default_work_anchor(body)
    configured_endpoint = str(body.get("live_work_preflight_endpoint") or "")
    try:
        endpoint = resolve_client_url("/api/v1/raw/query", endpoint=configured_endpoint)
    except RuntimeError:
        endpoint = configured_endpoint
    timeout = float(body.get("live_work_preflight_timeout_seconds") or 10)
    query = str(body.get("live_work_preflight_query") or body.get("query") or "继续，开工前先查已有机制")
    payload = {
        "mode": "work_preflight",
        "query": query,
        "consumer": str(body.get("consumer") or "preflight-doctor"),
        "source_system": str(body.get("source_system") or ""),
        "limit": int(body.get("live_work_preflight_limit") or body.get("limit") or 3),
        "excerpt_chars": int(body.get("live_work_preflight_excerpt_chars") or body.get("excerpt_chars") or 180),
    }
    for key in (
        "session_id",
        "canonical_window_id",
        "project_id",
        "project_root",
        "workstream_id",
        "task_id",
        "request_id",
    ):
        if body.get(key) not in (None, ""):
            payload[key] = str(body.get(key))
    if body.get("deep_work_preflight") not in (None, ""):
        payload["deep_work_preflight"] = _bool(body.get("deep_work_preflight"))

    started = time.perf_counter()
    result: dict[str, Any]
    try:
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
        elapsed_ms = round((time.perf_counter() - started) * 1000.0, 2)
        ok = bool(result.get("ok"))
        error = ""
    except Exception as exc:
        elapsed_ms = round((time.perf_counter() - started) * 1000.0, 2)
        result = {}
        ok = False
        error = str(exc)

    return {
        "contract": LIVE_WORK_PREFLIGHT_SMOKE_CONTRACT,
        "ok": ok,
        "read_only": True,
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "model_call_performed": False,
        "endpoint": endpoint,
        "timeout_seconds": timeout,
        "elapsed_ms": elapsed_ms,
        "request": {
            "mode": "work_preflight",
            "consumer": payload.get("consumer", ""),
            "source_system": payload.get("source_system", ""),
            "has_session_id": bool(payload.get("session_id")),
            "has_canonical_window_id": bool(payload.get("canonical_window_id")),
            "canonical_window_id": str(payload.get("canonical_window_id") or ""),
            "has_project_anchor": bool(payload.get("project_id") or payload.get("project_root")),
            "deep_work_preflight": bool(payload.get("deep_work_preflight", False)),
            "default_work_anchor_applied": bool(anchor_meta.get("applied")),
        },
        "default_work_anchor": anchor_meta,
        "response": {
            "ok": bool(result.get("ok")),
            "mode": result.get("mode", ""),
            "contract": result.get("contract", ""),
            "classification": result.get("classification", ""),
            "decision": result.get("decision", ""),
            "recall_status": result.get("recall_status", ""),
            "scope_missing": bool(result.get("scope_missing", False)),
            "fast_window_preflight": result.get("fast_window_preflight"),
            "fast_recall_path": result.get("fast_recall_path", ""),
            "fast_window_index_status": result.get("fast_window_index_status", ""),
            "zhiyi_layer_skipped_for_fast_preflight": result.get("zhiyi_layer_skipped_for_fast_preflight"),
            "library_index_projection_used": bool(result.get("library_index_projection_used", False)),
            "library_index_projection_refs_count": int(result.get("library_index_projection_refs_count") or 0),
            "library_index_projection_policy": result.get("library_index_projection_policy", ""),
            "library_index_projection_soft_weight_policy": result.get("library_index_projection_soft_weight_policy", ""),
            "library_index_projection_soft_weight": int(result.get("library_index_projection_soft_weight") or 0),
            "source_refs_count": int(result.get("source_refs_count") or result.get("consumer_receipt", {}).get("source_refs_count") or 0),
            "raw_items_count": int(result.get("raw_items_count") or result.get("consumer_receipt", {}).get("raw_items_count") or 0),
        },
        "error": error,
        "notes": [
            "live_work_preflight_smoke_measures_local_entry_latency_and_return_shape",
            "scope_required_without_window_anchor_is_not_a_recall_failure",
            "projection_fields_are_overlaid_only_when_the_live_response_contains_them",
        ],
    }


def _latency_values(samples: list[dict[str, Any]]) -> list[float]:
    values: list[float] = []
    for sample in samples:
        try:
            values.append(float(sample.get("elapsed_ms")))
        except Exception:
            pass
    return values


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(percentile * len(ordered)) - 1))
    return ordered[index]


def _brief_smoke_sample(sample: dict[str, Any], index: int) -> dict[str, Any]:
    response = _dict(sample.get("response"))
    return {
        "index": index,
        "ok": bool(sample.get("ok")),
        "elapsed_ms": sample.get("elapsed_ms"),
        "decision": response.get("decision", ""),
        "fast_window_preflight": response.get("fast_window_preflight"),
        "fast_recall_path": response.get("fast_recall_path", ""),
        "source_refs_count": int(response.get("source_refs_count") or 0),
        "raw_items_count": int(response.get("raw_items_count") or 0),
        "error": sample.get("error", ""),
    }


def _aggregate_live_work_preflight_smokes(samples: list[dict[str, Any]]) -> dict[str, Any]:
    if not samples:
        return _live_work_preflight_smoke({})

    ok_samples = [sample for sample in samples if bool(sample.get("ok"))]
    ordered_ok = sorted(ok_samples, key=lambda item: float(item.get("elapsed_ms") or 0))
    representative = ordered_ok[len(ordered_ok) // 2] if ordered_ok else samples[-1]
    latencies = _latency_values(samples)
    ok_latencies = _latency_values(ok_samples)
    median_ms = _median(ok_latencies or latencies)
    p95_ms = _percentile(latencies, 0.95)
    max_ms = max(latencies) if latencies else None
    slow_threshold_ms = 1000.0
    failed_count = len(samples) - len(ok_samples)
    slow_count = sum(1 for value in latencies if value > slow_threshold_ms)
    aggregate = dict(representative)
    aggregate["ok"] = len(ok_samples) >= max(1, math.ceil(len(samples) / 2))
    if median_ms is not None:
        aggregate["elapsed_ms"] = round(median_ms, 2)
    aggregate["sample_count"] = len(samples)
    aggregate["sample_success_count"] = len(ok_samples)
    aggregate["sample_failure_count"] = failed_count
    aggregate["latency_summary"] = {
        "sample_count": len(samples),
        "success_count": len(ok_samples),
        "failure_count": failed_count,
        "median_ms": round(median_ms, 2) if median_ms is not None else None,
        "p95_ms": round(p95_ms, 2) if p95_ms is not None else None,
        "max_ms": round(max_ms, 2) if max_ms is not None else None,
        "slow_threshold_ms": slow_threshold_ms,
        "slow_sample_count": slow_count,
        "scoring_latency": "median_success_ms" if ok_latencies else "median_all_ms",
    }
    aggregate["samples"] = [
        _brief_smoke_sample(sample, index + 1)
        for index, sample in enumerate(samples)
    ]
    aggregate["notes"] = list(aggregate.get("notes") or []) + [
        "multi_sample_smoke_scores_latency_by_median_and_keeps_outliers_visible",
    ]
    return aggregate


def _live_work_preflight_smoke_series(body: dict[str, Any]) -> dict[str, Any]:
    sample_count = _positive_int(body.get("live_work_preflight_smoke_samples") or 1, default=1, maximum=9)
    samples = []
    for index in range(sample_count):
        sample_body = dict(body)
        sample_body["_live_work_preflight_sample_index"] = index + 1
        samples.append(_live_work_preflight_smoke(sample_body))
    return _aggregate_live_work_preflight_smokes(samples)


def _overlay_measured_preflight(body: dict[str, Any], preflight: dict[str, Any]) -> dict[str, Any]:
    patched = dict(preflight)
    smoke = _dict(body.get("live_work_preflight_smoke"))
    smoke_response = _dict(smoke.get("response"))
    if smoke_response:
        patched["live_work_preflight_smoke_contract"] = smoke.get("contract", "")
        patched["live_work_preflight_smoke_ok"] = bool(smoke.get("ok", False))
        patched["live_work_preflight_elapsed_ms"] = smoke.get("elapsed_ms")
        if isinstance(smoke.get("latency_summary"), dict):
            patched["live_work_preflight_latency_summary"] = smoke.get("latency_summary")
        for key in (
            "fast_window_preflight",
            "fast_recall_path",
            "fast_window_index_status",
            "zhiyi_layer_skipped_for_fast_preflight",
            "library_index_projection_used",
            "library_index_projection_refs_count",
            "library_index_projection_policy",
            "library_index_projection_soft_weight_policy",
            "library_index_projection_soft_weight",
            "source_refs_count",
            "raw_items_count",
        ):
            if smoke_response.get(key) not in (None, ""):
                patched[key] = smoke_response.get(key)
        if smoke.get("elapsed_ms") not in (None, ""):
            patched["latency_ms"] = smoke.get("elapsed_ms")
    bool_keys = (
        "fast_window_preflight",
        "zhiyi_layer_skipped_for_fast_preflight",
        "library_index_projection_used",
        "answer_debug_available",
    )
    for key in bool_keys:
        if key in body:
            patched[key] = _bool(body.get(key))
    for key in (
        "fast_recall_path",
        "fast_window_index_status",
        "answer_debug_capability_contract",
        "dialog_entry_answer_debug_contract",
        "evidence_bound_model_contract",
        "evidence_bound_model_gating_contract",
        "answer_model_call_policy",
        "library_index_projection_policy",
        "library_index_projection_soft_weight_policy",
        "preflight_score_policy",
    ):
        if body.get(key) not in (None, ""):
            patched[key] = body.get(key)
    for key in (
        "library_index_projection_refs_count",
        "library_index_projection_soft_weight",
        "source_refs_count",
        "raw_items_count",
    ):
        if body.get(key) not in (None, ""):
            try:
                patched[key] = int(body.get(key))
            except Exception:
                pass
    return patched


def _live_smoke_default_work_anchor(body: dict[str, Any]) -> dict[str, Any]:
    return _dict(_dict(body.get("live_work_preflight_smoke")).get("default_work_anchor"))


def _answer_debug_capability(preflight: dict[str, Any]) -> dict[str, Any]:
    existing = _dict(preflight.get("answer_debug_capability"))
    config = default_model_config()
    api_key_env = str(existing.get("api_key_env") or getattr(config, "api_key_env", "") or "")
    api_key_present = bool(existing.get("api_key_present", getattr(config, "api_key_present", False)))
    model_name = str(existing.get("model_name") or getattr(config, "model", "") or "")
    base_url_present = bool(existing.get("base_url_present", bool(str(getattr(config, "base_url", "") or ""))))
    return {
        "contract": str(
            existing.get("contract")
            or preflight.get("answer_debug_capability_contract")
            or PREFLIGHT_ANSWER_DEBUG_CAPABILITY_CONTRACT
        ),
        "available": bool(existing.get("available", preflight.get("answer_debug_available", True))),
        "read_only": bool(existing.get("read_only", True)),
        "raw_write_performed": bool(existing.get("raw_write_performed", False)),
        "memory_write_performed": bool(existing.get("memory_write_performed", False)),
        "platform_write_performed": bool(existing.get("platform_write_performed", False)),
        "model_call_performed": bool(existing.get("model_call_performed", preflight.get("model_call_performed", False))),
        "request_sent": bool(existing.get("request_sent", False)),
        "requires_explicit_answer_debug": bool(existing.get("requires_explicit_answer_debug", True)),
        "requires_confirm_live_model_call": bool(existing.get("requires_confirm_live_model_call", True)),
        "dialog_entry_answer_debug_contract": str(
            existing.get("dialog_entry_answer_debug_contract")
            or preflight.get("dialog_entry_answer_debug_contract")
            or DIALOG_ENTRY_ANSWER_DEBUG_CONTRACT
        ),
        "evidence_bound_model_contract": str(
            existing.get("evidence_bound_model_contract")
            or preflight.get("evidence_bound_model_contract")
            or EVIDENCE_BOUND_MODEL_CONTRACT
        ),
        "evidence_bound_model_gating_contract": str(
            existing.get("evidence_bound_model_gating_contract")
            or preflight.get("evidence_bound_model_gating_contract")
            or EVIDENCE_BOUND_MODEL_GATING_CONTRACT
        ),
        "default_model_call_policy": str(
            existing.get("default_model_call_policy")
            or preflight.get("answer_model_call_policy")
            or "auto"
        ),
        "supported_model_call_policies": existing.get("supported_model_call_policies") or ["auto", "always", "never"],
        "provider": str(existing.get("provider") or getattr(config, "provider", "") or ""),
        "model_name": model_name,
        "base_url_present": base_url_present,
        "api_key_env": api_key_env,
        "api_key_present": api_key_present,
        "runtime_binding_ready": bool(api_key_present and model_name and base_url_present),
        "final_evidence_authority": str(existing.get("final_evidence_authority") or "raw_source_refs"),
        "draft_and_model_answer_policy": str(
            existing.get("draft_and_model_answer_policy")
            or "not_evidence_without_supporting_refs"
        ),
    }


def _memory_absorption_contracts(body: dict[str, Any]) -> dict[str, Any]:
    metric_claim = _dict(body.get("public_metric_claim"))
    metric_gate = gate_public_metric_claim(metric_claim) if metric_claim else {
        "contract": "public_metric_claim_gate.v2026.6.21",
        "status": "not_evaluated_no_public_metric_claim_supplied",
        "is_publication_ready": False,
        "official_leaderboard_score": False,
        "metric_boundary": "retrieval_recall_not_qa_accuracy",
        "read_only": True,
        "write_performed": False,
        "model_call_performed": False,
    }
    return {
        "ok": True,
        "contract": "memory_absorption_contracts.v2026.6.21",
        "read_only": True,
        "write_performed": False,
        "model_call_performed": False,
        "evidence_atom_vocabulary": vocabulary_contract(),
        "search_think_boundary": search_think_boundary_contract(),
        "search_think_dry_run": search_think_dry_run_contract(),
        "delivery_receipt_contract": DELIVERY_RECEIPT_CONTRACT,
        "public_metric_claim_gate": metric_gate,
        "next_action": "run_search_think_dry_run_with_controlled_evidence_before_frontend_delivery_receipt",
    }


def _score_connection(productized: dict[str, Any], preflight: dict[str, Any] | None = None) -> dict[str, Any]:
    loops = _dict(productized.get("loops"))
    statuses = _dict(productized.get("loop_statuses"))
    connect = _dict(loops.get("connect_doctor"))
    auto = _dict(connect.get("auto_connect"))
    record = _dict(connect.get("record_doctor"))
    connect_statuses = _dict(connect.get("statuses"))
    preflight = _dict(preflight)
    scan_mode = str(auto.get("scan_mode") or "")
    skipped = scan_mode == "skipped_by_request"
    all_read_only = statuses and all(bool(_dict(item).get("read_only", True)) for item in statuses.values())
    no_writes = statuses and not any(bool(_dict(item).get("write_performed", False)) for item in statuses.values())
    live_entry_validated = bool(
        preflight.get("live_work_preflight_smoke_ok")
        and preflight.get("fast_window_preflight")
        and str(preflight.get("fast_recall_path") or "") == "canonical_window_index"
        and int(preflight.get("source_refs_count") or 0) > 0
        and int(preflight.get("raw_items_count") or 0) > 0
    )

    score = 0
    signals: list[str] = []
    attention: list[str] = []
    if bool(productized.get("ok")):
        score += 22
        signals.append("productized_loops_ok")
    if all_read_only and no_writes:
        score += 18
        signals.append("all_loops_read_only")
    if bool(auto.get("ok")):
        score += 22
        signals.append("auto_connect_doctor_available")
    if str(record.get("doctor_status") or "") in {"ok", "healthy", "ready"}:
        score += 18
        signals.append("record_chain_healthy")
    elif record and live_entry_validated:
        score += 18
        signals.append("work_preflight_live_connection_validated")
        attention.append(f"record_doctor_status={record.get('doctor_status', '')}")
        attention.append("record_chain_attention_is_non_blocking_for_live_connection_score")
    elif record:
        score += 9
        attention.append(f"record_doctor_status={record.get('doctor_status', '')}")
    if int(connect_statuses.get("detected_connectable") or 0) > 0:
        score += 20
        signals.append("connectable_clients_detected")
    elif skipped:
        score += 10
        attention.append("platform_scan_skipped")
    elif int(auto.get("plan_count") or 0) > 0:
        score += 14
        signals.append("auto_connect_plans_available")
    else:
        attention.append("no_connectable_client_detected_in_this_run")

    return _score_item(
        score,
        status="ok" if score >= 80 else "partial" if score >= 55 else "attention",
        signals=signals,
        attention=attention,
        next_actions=[
            "run_without_skip_platform_scan_for_live_client_detection",
            "check_mcp_capability_and_current_client_binding_when_score_is_partial",
        ],
    )


def _score_binding(preflight: dict[str, Any]) -> dict[str, Any]:
    receipt = _dict(preflight.get("consumer_receipt"))
    active_layers = [str(item) for item in preflight.get("active_layers_used", [])]
    used_library_ids = receipt.get("used_library_ids") if isinstance(receipt.get("used_library_ids"), list) else []
    score = 0
    signals: list[str] = []
    attention: list[str] = []

    if str(preflight.get("memory_scope") or "") == "window":
        score += 30
        signals.append("window_memory_scope")
    else:
        attention.append(f"memory_scope={preflight.get('memory_scope', '')}")
    if "current_window" in active_layers:
        score += 30
        signals.append("current_window_layer_active")
    if "project" in active_layers:
        score += 10
        signals.append("project_layer_active")
    if bool(preflight.get("source_refs_required")) or int(receipt.get("source_refs_count") or 0) > 0:
        score += 15
        signals.append("source_refs_bound")
    if used_library_ids:
        score += 15
        signals.append("library_ids_bound_to_receipt")

    return _score_item(
        score,
        status="ok" if score >= 80 else "partial" if score >= 55 else "attention",
        signals=signals,
        attention=attention,
        next_actions=["ensure_window_or_session_id_is_passed_into_work_preflight"],
    )


def _score_fast_path(preflight: dict[str, Any]) -> dict[str, Any]:
    fast_value = preflight.get("fast_window_preflight")
    fast_path = str(preflight.get("fast_recall_path") or "")
    active_layers = [str(item) for item in preflight.get("active_layers_used", [])]
    signals: list[str] = []
    attention: list[str] = []
    score = 0

    if fast_value is True:
        score += 60
        signals.append("fast_window_preflight_true")
        if fast_path == "canonical_window_index":
            score += 25
            signals.append("canonical_window_index")
        if bool(preflight.get("zhiyi_layer_skipped_for_fast_preflight")):
            score += 10
            signals.append("deep_zhiyi_layer_skipped")
        fast_status = str(preflight.get("fast_window_index_status") or "")
        if fast_status.startswith("hit"):
            score += 5
            signals.append("fast_window_index_hit")
            if fast_status != "hit":
                signals.append(fast_status)
        status = "ok"
    elif fast_value is False:
        score = 15
        attention.append("fast_window_preflight_false")
        status = "attention"
    elif str(preflight.get("memory_scope") or "") == "window" and "current_window" in active_layers:
        score = 55
        signals.append("window_scoped_preflight_present")
        attention.append("fast_path_latency_not_measured_in_productized_demo")
        status = "partial"
    else:
        score = 30
        attention.append("fast_path_not_measured")
        status = "attention"

    return _score_item(
        score,
        status=status,
        signals=signals,
        attention=attention,
        next_actions=[
            "run_real_mcp_work_preflight_and_expect_fast_window_preflight_true",
            "use_deep_work_preflight_only_when_the_operator_explicitly_requests_a_cold_scan",
        ],
    )


def _score_latency(body: dict[str, Any], preflight: dict[str, Any]) -> dict[str, Any]:
    latency_summary = _dict(preflight.get("live_work_preflight_latency_summary") or body.get("latency_summary"))
    value = (
        latency_summary.get("median_ms")
        or body.get("latency_ms")
        or body.get("elapsed_ms")
        or preflight.get("latency_ms")
        or preflight.get("elapsed_ms")
    )
    seconds_value = (
        body.get("latency_seconds")
        or body.get("elapsed_seconds")
        or preflight.get("latency_seconds")
        or preflight.get("elapsed_seconds")
    )
    latency_ms: float | None = None
    try:
        if value not in (None, ""):
            latency_ms = float(value)
        elif seconds_value not in (None, ""):
            latency_ms = float(seconds_value) * 1000.0
    except Exception:
        latency_ms = None

    if latency_ms is None:
        return _score_item(
            45,
            status="not_measured",
            attention=["latency_not_measured_in_this_doctor_run"],
            next_actions=["pass_latency_ms_from_real_mcp_or_bridge_smoke_to_score_hot_path_latency"],
        )
    if latency_ms <= 100:
        score = 100
    elif latency_ms <= 500:
        score = 90
    elif latency_ms <= 1000:
        score = 80
    elif latency_ms <= 5000:
        score = 60
    elif latency_ms <= 12000:
        score = 35
    else:
        score = 10
    signals = [f"latency_ms={latency_ms:.2f}"]
    attention: list[str] = []
    if latency_summary:
        sample_count = int(latency_summary.get("sample_count") or 0)
        slow_count = int(latency_summary.get("slow_sample_count") or 0)
        failed_count = int(latency_summary.get("failure_count") or 0)
        if sample_count:
            signals.append(f"latency_samples={sample_count}")
        if latency_summary.get("p95_ms") not in (None, ""):
            signals.append(f"latency_p95_ms={float(latency_summary.get('p95_ms')):.2f}")
        if latency_summary.get("max_ms") not in (None, ""):
            signals.append(f"latency_max_ms={float(latency_summary.get('max_ms')):.2f}")
        if slow_count:
            attention.append(f"slow_latency_sample_count={slow_count}")
        if failed_count:
            attention.append(f"failed_latency_sample_count={failed_count}")
    return _score_item(
        score,
        status="ok" if score >= 80 else "partial" if score >= 55 else "attention",
        signals=signals,
        attention=attention,
        next_actions=["keep_work_preflight_on_canonical_window_index_for_hot_path_latency"],
    )


def _score_recall(productized: dict[str, Any]) -> dict[str, Any]:
    loops = _dict(productized.get("loops"))
    preflight = _dict(loops.get("hot_path_preflight"))
    benchmark = _dict(loops.get("recall_experience_benchmark"))
    borrowing = _dict(loops.get("borrowing_receipts"))
    benchmark_summary = _dict(benchmark.get("summary"))
    borrowing_receipt = _dict(borrowing.get("consumer_receipt"))
    preflight_receipt = _dict(preflight.get("consumer_receipt"))
    score = 0
    signals: list[str] = []

    if benchmark_summary.get("best_mode") == "zhiyi_plus_xingce":
        score += 35
        signals.append("best_mode_zhiyi_plus_xingce")
    if bool(benchmark_summary.get("xingce_signal_detected")):
        score += 20
        signals.append("xingce_signal_detected")
    if int(benchmark_summary.get("improvement_over_no_memory") or 0) > 0:
        score += 15
        signals.append("improves_over_no_memory")
    if int(preflight_receipt.get("source_refs_count") or 0) > 0:
        score += 15
        signals.append("preflight_source_refs_present")
    if int(borrowing_receipt.get("source_refs_count") or 0) > 0:
        score += 15
        signals.append("borrowing_receipts_source_backed")

    return _score_item(
        score,
        status="ok" if score >= 80 else "partial" if score >= 55 else "attention",
        signals=signals,
        next_actions=["run_official_memory_benchmark_diagnostic_for_dataset_level_recall"],
    )


def _score_source_backed(borrowing: dict[str, Any]) -> dict[str, Any]:
    receipts = _items(borrowing.get("demo_receipts"))
    receipt = _dict(borrowing.get("consumer_receipt"))
    source_refs_count = int(receipt.get("source_refs_count") or 0)
    raw_index_count = sum(1 for item in receipts if item.get("raw_evidence_status") == "raw_index")
    raw_excerpt_count = sum(1 for item in receipts if bool(item.get("raw_excerpt_available")))
    score = 0
    signals: list[str] = []
    attention: list[str] = []
    if source_refs_count > 0:
        score += 35
        signals.append("source_refs_present")
    if receipts and raw_index_count == len(receipts):
        score += 35
        signals.append("all_demo_receipts_have_raw_index")
    elif receipts:
        score += 18
        attention.append("some_receipts_missing_raw_index")
    if raw_excerpt_count > 0:
        score += 20
        signals.append("raw_excerpts_available")
    if receipt.get("used_library_ids"):
        score += 10
        signals.append("used_library_ids_recorded")

    return _score_item(
        score,
        status="ok" if score >= 80 else "partial" if score >= 55 else "attention",
        signals=signals,
        attention=attention,
        next_actions=["keep_final_answer_evidence_source_backed"],
    )


def _score_projection(preflight: dict[str, Any]) -> dict[str, Any]:
    used = bool(preflight.get("library_index_projection_used"))
    refs = int(preflight.get("library_index_projection_refs_count") or 0)
    policy = str(preflight.get("library_index_projection_policy") or "")
    soft_policy = str(preflight.get("library_index_projection_soft_weight_policy") or "")
    signals: list[str] = []
    attention: list[str] = []
    score = 0

    if used:
        score += 55
        signals.append("library_index_projection_used")
        if refs > 0:
            score += 20
            signals.append("projection_refs_present")
    else:
        score += 40
        attention.append("projection_not_triggered_for_this_query")
    if policy or soft_policy:
        score += 25
        signals.append("projection_policy_exposed")
    else:
        attention.append("projection_policy_empty_in_this_payload")

    return _score_item(
        score,
        status="ok" if score >= 80 else "partial" if score >= 45 else "attention",
        signals=signals,
        attention=attention,
        next_actions=["treat_projection_as_navigation_hint_only_and_require_raw_source_refs"],
    )


def _score_answer_debug(capability: dict[str, Any]) -> dict[str, Any]:
    score = 0
    signals: list[str] = []
    attention: list[str] = []

    if bool(capability.get("available")):
        score += 20
        signals.append("answer_debug_available")
    else:
        attention.append("answer_debug_not_available")
    if str(capability.get("dialog_entry_answer_debug_contract") or "") == DIALOG_ENTRY_ANSWER_DEBUG_CONTRACT:
        score += 20
        signals.append("dialog_entry_answer_debug_contract_exposed")
    else:
        attention.append("dialog_entry_answer_debug_contract_missing")
    if str(capability.get("evidence_bound_model_gating_contract") or "") == EVIDENCE_BOUND_MODEL_GATING_CONTRACT:
        score += 20
        signals.append("evidence_bound_model_gating_contract_exposed")
    else:
        attention.append("evidence_bound_model_gating_contract_missing")
    no_writes_or_calls = (
        bool(capability.get("read_only", True))
        and not bool(capability.get("raw_write_performed"))
        and not bool(capability.get("memory_write_performed"))
        and not bool(capability.get("platform_write_performed"))
        and not bool(capability.get("model_call_performed"))
        and not bool(capability.get("request_sent"))
    )
    if no_writes_or_calls:
        score += 20
        signals.append("debug_capability_read_only_no_model_call")
    else:
        attention.append("debug_capability_performed_write_or_model_call")
    if str(capability.get("default_model_call_policy") or "") == "auto":
        score += 10
        signals.append("default_model_call_policy_auto")
    else:
        attention.append(f"default_model_call_policy={capability.get('default_model_call_policy', '')}")
    if str(capability.get("final_evidence_authority") or "") == "raw_source_refs":
        score += 10
        signals.append("raw_source_refs_remain_final_authority")
    else:
        attention.append("final_evidence_authority_not_raw_source_refs")
    if not bool(capability.get("runtime_binding_ready")):
        attention.append("live_model_runtime_binding_not_ready_or_not_checked")

    return _score_item(
        score,
        status="ok" if score >= 80 else "partial" if score >= 55 else "attention",
        signals=signals,
        attention=attention,
        next_actions=[
            "use_answer_debug_true_on_entry_when_answer_quality_or_model_gating_needs_inspection",
            "keep_preflight_doctor_read_only_and_do_not_send_model_requests_from_the_doctor",
        ],
    )


def _score_experience(productized: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    loops = _dict(productized.get("loops"))
    preflight = _dict(loops.get("hot_path_preflight"))
    evolution = _dict(loops.get("experience_evolution_demo"))
    evolution_summary = _dict(evolution.get("summary"))
    changed_behavior = [str(item) for item in preflight.get("changed_behavior", [])]
    do_not_repeat = [str(item) for item in preflight.get("do_not_repeat", [])]
    acceptance_checks = [str(item) for item in preflight.get("acceptance_checks", [])]

    intervention_score = 0
    intervention_signals: list[str] = []
    if str(preflight.get("classification") or "") != "actually_missing":
        intervention_score += 20
        intervention_signals.append(f"classification={preflight.get('classification', '')}")
    if str(preflight.get("decision") or "") in {"surface", "intervene"} or bool(preflight.get("should_intervene")):
        intervention_score += 20
        intervention_signals.append("preflight_surfaces_before_work")
    if changed_behavior:
        intervention_score += 20
        intervention_signals.append("changed_behavior_present")
    if do_not_repeat:
        intervention_score += 10
        intervention_signals.append("do_not_repeat_present")
    if acceptance_checks:
        intervention_score += 10
        intervention_signals.append("acceptance_checks_present")
    if int(evolution_summary.get("candidate_count") or 0) > 0:
        intervention_score += 10
        intervention_signals.append("experience_candidates_available")
    if int(evolution_summary.get("hermes_upgrade_candidate_count") or 0) > 0:
        intervention_score += 10
        intervention_signals.append("hermes_skill_experience_candidates_available")

    behavior_score = 30 if changed_behavior else 0
    if str(preflight.get("classification") or "") in {"already_built_but_forgotten", "built_but_miswired", "diagnostic_gap"}:
        behavior_score += 25
    if do_not_repeat:
        behavior_score += 20
    if str(preflight.get("agent_instruction") or ""):
        behavior_score += 15
    if str(preflight.get("next_action") or ""):
        behavior_score += 10

    acceptance_score = 0
    acceptance_signals: list[str] = []
    if acceptance_checks:
        acceptance_score += 30
        acceptance_signals.append("preflight_acceptance_checks")
    if bool(_dict(evolution.get("validation_report")).get("report_passed")):
        acceptance_score += 30
        acceptance_signals.append("experience_validation_report_passed")
    if str(_dict(evolution.get("apply_gate")).get("status") or "") == "ready":
        acceptance_score += 20
        acceptance_signals.append("authorized_apply_gate_ready")
    if str(_dict(evolution.get("apply_package")).get("package_status") or "") == "ready":
        acceptance_score += 20
        acceptance_signals.append("apply_package_ready")

    return (
        _score_item(
            intervention_score,
            status="ok" if intervention_score >= 80 else "partial" if intervention_score >= 55 else "attention",
            signals=intervention_signals,
            next_actions=["surface_changed_behavior_before_planning_the_fix"],
        ),
        _score_item(
            behavior_score,
            status="ok" if behavior_score >= 80 else "partial" if behavior_score >= 55 else "attention",
            signals=changed_behavior,
            attention=[] if changed_behavior else ["changed_behavior_missing"],
            next_actions=["convert_recall_into_an_explicit_behavior_change_or_acceptance_check"],
        ),
        _score_item(
            acceptance_score,
            status="ok" if acceptance_score >= 80 else "partial" if acceptance_score >= 55 else "attention",
            signals=acceptance_signals,
            attention=[] if acceptance_checks else ["preflight_acceptance_checks_missing"],
            next_actions=["keep_experience_adoption_behind_review_and_validation_receipts"],
        ),
    )


def _benchmark_readiness(productized: dict[str, Any]) -> dict[str, Any]:
    loops = _dict(productized.get("loops"))
    benchmark = _dict(loops.get("recall_experience_benchmark"))
    has_productized_benchmark = bool(benchmark.get("ok")) and bool(benchmark.get("summary"))
    sources = dict(PUBLIC_BENCHMARK_REFERENCE_SOURCES)
    supported_targets = [
        target
        for target in ("locomo", "longmemeval")
        if target in sources
    ]
    score = 0
    signals: list[str] = []
    next_required = [
        "run full official data splits locally or in CI",
        "run generated QA trial artifacts through the official evaluator or LLM judge path",
        "publish dataset, split, model, prompt, and command lines with the score",
    ]
    if supported_targets:
        score += 25
        signals.append("public_benchmark_reference_sources_documented")
    if sources.get("locomo") and sources.get("longmemeval"):
        score += 15
        signals.append("official_download_sources_known")
    if has_productized_benchmark:
        score += 20
        signals.append("internal_recall_experience_benchmark_present")
    if bool(productized.get("read_only")) and not bool(productized.get("model_call_performed")):
        score += 10
        signals.append("diagnostic_boundary_is_read_only_no_model_call")
    score += 10
    signals.append("leaderboard_claim_explicitly_false")

    readiness_level = "ready_for_internal_retrieval_diagnostic"
    if score < 70:
        readiness_level = "partial"
    if score >= 90:
        readiness_level = "near_official_pipeline"

    return {
        "score": _score(score),
        "readiness_level": readiness_level,
        "official_leaderboard_score": False,
        "tiny_diagnostic_is_not_official_score": True,
        "internal_retrieval_diagnostic_available": True,
        "productized_recall_experience_benchmark_available": has_productized_benchmark,
        "supported_targets": supported_targets,
        "official_sources": sources,
        "full_qa_status": {
            "implemented": False,
            "qa_trial_available": False,
            "official_evaluator_preflight_available": False,
            "reason": "public package keeps benchmark evaluator adapters out of product src; official QA scoring should be run through a separate pinned evaluator workspace",
        },
        "signals": signals,
        "next_required": next_required,
        "notes": [
            "doctor_score_is_product_diagnostic_not_a_public_leaderboard_score",
            "LoCoMo_and_LongMemEval_scores_must_be_reported_only_after_running_their_required_evaluation_path",
        ],
    }


def _empty_score(name: str, *, score: int = 0, status: str = "skipped") -> dict[str, Any]:
    return _score_item(
        score,
        status=status,
        attention=[f"{name}_skipped_in_smoke_profile"],
        next_actions=["run_diagnostic_profile_full_for_heavy_productized_loop_scores"],
    )


def _build_smoke_profile_preflight_doctor(body: dict[str, Any]) -> dict[str, Any]:
    body = dict(body)
    if not isinstance(body.get("live_work_preflight_smoke"), dict):
        body["live_work_preflight_smoke"] = _live_work_preflight_smoke_series(body)
    preflight = _overlay_measured_preflight(body, {})
    default_anchor = _live_smoke_default_work_anchor(body)
    connection = _score_item(
        100 if bool(preflight.get("live_work_preflight_smoke_ok")) else 35,
        status="ok" if bool(preflight.get("live_work_preflight_smoke_ok")) else "attention",
        signals=["live_work_preflight_smoke_ok"] if bool(preflight.get("live_work_preflight_smoke_ok")) else [],
        attention=[] if bool(preflight.get("live_work_preflight_smoke_ok")) else ["live_work_preflight_smoke_failed"],
        next_actions=["run_diagnostic_profile_full_when_connection_or_record_chain_needs_diagnosis"],
    )
    binding = _score_item(
        100 if bool(preflight.get("source_refs_count")) and bool(preflight.get("raw_items_count")) else 55,
        status="ok" if bool(preflight.get("source_refs_count")) and bool(preflight.get("raw_items_count")) else "partial",
        signals=[
            f"source_refs_count={int(preflight.get('source_refs_count') or 0)}",
            f"raw_items_count={int(preflight.get('raw_items_count') or 0)}",
        ],
        attention=[] if bool(preflight.get("source_refs_count")) and bool(preflight.get("raw_items_count")) else ["raw_source_refs_missing_or_partial"],
        next_actions=["pass_window_or_session_anchor_for_current_work_preflight"],
    )
    fast_path = _score_fast_path(preflight)
    latency = _score_latency(body, preflight)
    projection = _score_projection(preflight)
    answer_debug_capability = _answer_debug_capability(preflight)
    answer_debug = _score_answer_debug(answer_debug_capability)
    absorption_contracts = _memory_absorption_contracts(body)
    recall = _empty_score("recall", score=65, status="not_measured")
    source_backed = _score_item(
        100 if bool(preflight.get("source_refs_count")) else 45,
        status="ok" if bool(preflight.get("source_refs_count")) else "attention",
        signals=[f"source_refs_count={int(preflight.get('source_refs_count') or 0)}"],
        attention=[] if bool(preflight.get("source_refs_count")) else ["source_refs_missing_in_smoke_profile"],
        next_actions=["require_raw_source_refs_before_final_answer"],
    )
    raw_traceability = _score_item(
        100 if bool(preflight.get("raw_items_count")) else 45,
        status="ok" if bool(preflight.get("raw_items_count")) else "attention",
        signals=[f"raw_items_count={int(preflight.get('raw_items_count') or 0)}"],
        attention=[] if bool(preflight.get("raw_items_count")) else ["raw_items_missing_in_smoke_profile"],
        next_actions=["require_raw_items_or_source_refs_before_final_answer"],
    )
    experience = _empty_score("experience_intervention", score=65, status="not_measured")
    behavior_change = _empty_score("behavior_change", score=65, status="not_measured")
    acceptance = _empty_score("acceptance_check", score=65, status="not_measured")
    benchmark = {
        "score": 0,
        "status": "non_blocking_skipped",
        "readiness_level": "skipped_in_smoke_profile",
        "official_leaderboard_score": False,
        "tiny_diagnostic_is_not_official_score": True,
        "signals": [],
        "next_required": ["run_diagnostic_profile_full_or_official_benchmark_for_benchmark_readiness"],
    }
    score_breakdown = {
        "connection_health_score": connection,
        "binding_health_score": binding,
        "fast_path_health_score": fast_path,
        "latency_score": latency,
        "recall_score": recall,
        "source_backed_score": source_backed,
        "raw_traceability_score": raw_traceability,
        "projection_explainability_score": projection,
        "answer_debug_score": answer_debug,
        "experience_intervention_score": experience,
        "behavior_change_score": behavior_change,
        "acceptance_check_score": acceptance,
        "benchmark_readiness": benchmark,
    }
    numeric_scores = [
        connection["score"],
        binding["score"],
        fast_path["score"],
        latency["score"],
        source_backed["score"],
        raw_traceability["score"],
        projection["score"],
        answer_debug["score"],
    ]
    overall = _score(sum(numeric_scores) / len(numeric_scores))
    critical_attention = [
        name
        for name, item in score_breakdown.items()
        if isinstance(item, dict)
        and int(item.get("score") or 0) < 55
        and str(item.get("status") or "") != "non_blocking_skipped"
    ]
    return {
        "ok": bool(preflight.get("live_work_preflight_smoke_ok")) and overall >= 55,
        "contract": PREFLIGHT_DOCTOR_CONTRACT,
        "profile_contract": PREFLIGHT_DOCTOR_SMOKE_PROFILE_CONTRACT,
        "version": PREFLIGHT_DOCTOR_VERSION,
        "generated_at": _now(),
        **_write_boundary(),
        "diagnostic_profile": "smoke",
        "heavy_diagnostics_skipped": True,
        "not_a_new_memory_layer": True,
        "under_tiandao_five_shelves": True,
        "doctor_score_contract": PREFLIGHT_DOCTOR_SCORE_CONTRACT,
        "overall_score": overall,
        "connection_health_score": connection["score"],
        "binding_health_score": binding["score"],
        "fast_path_health_score": fast_path["score"],
        "latency_score": latency["score"],
        "recall_score": recall["score"],
        "source_backed_score": source_backed["score"],
        "raw_traceability_score": raw_traceability["score"],
        "projection_explainability_score": projection["score"],
        "answer_debug_score": answer_debug["score"],
        "answer_debug_capability": answer_debug_capability,
        "memory_absorption_contracts": absorption_contracts,
        "live_work_preflight_smoke": _dict(body.get("live_work_preflight_smoke")),
        "experience_intervention_score": experience["score"],
        "behavior_change_score": behavior_change["score"],
        "acceptance_check_score": acceptance["score"],
        "benchmark_readiness_score": benchmark["score"],
        "benchmark_readiness": benchmark,
        "score_breakdown": score_breakdown,
        "critical_attention": critical_attention,
        "summary": {
            "classification": _dict(_dict(body.get("live_work_preflight_smoke")).get("response")).get("classification", ""),
            "official_leaderboard_score": False,
            "heavy_diagnostics_skipped": True,
            "default_work_anchor_applied": bool(default_anchor.get("applied", False)),
            "default_work_anchor": default_anchor,
        },
        "route_summary": {
            "entrypoint": "preflight_doctor",
            "diagnostic_profile": "smoke",
            "uses": ["live_work_preflight_smoke", "agent_work_preflight"],
            "contract_surfaces": [
                "memory_absorption_contracts",
                "evidence_atom_vocabulary",
                "search_think_boundary",
                "search_think_dry_run",
                "delivery_receipt_contract",
                "public_metric_claim_gate",
            ],
            "skips": ["productized_loops_doctor", "record_chain_doctor", "recall_experience_benchmark", "experience_evolution_demo"],
            "final_evidence_authority": "raw_source_refs",
            "projection_authority": "navigation_hint_only",
            "answer_debug_authority": "diagnostic_only_not_evidence",
            "search_think_authority": "local_search_only_model_owned_think",
            "public_metric_claim_authority": "source_gate_required_before_public_homepage",
            "live_work_preflight_smoke": "measured_overlay",
            "default_work_anchor": default_anchor,
        },
        "boundary": {
            "official_leaderboard_score": False,
            "doctor_score_is_product_diagnostic": True,
            "tiny_fixture_is_internal_diagnostic_only": True,
            "no_raw_or_memory_write": True,
            "no_platform_write": True,
            "preflight_doctor_sent_model_request": False,
            "answer_debug_requires_explicit_request": True,
            "think_answer_must_be_model_owned": True,
            "public_metric_claim_requires_source_gate": True,
            "live_work_preflight_smoke_read_only": True,
            "heavy_diagnostics_skipped": True,
            "default_work_anchor_applied": bool(default_anchor.get("applied", False)),
            "default_work_anchor_can_be_disabled_for_scope_required_diagnostics": True,
        },
        "productized_loops": {
            "status": "skipped_in_smoke_profile",
            "next_action": "run_diagnostic_profile_full_for_productized_loop_details",
        },
        "notes": [
            "smoke_profile_is_for_hot_path_pre_work_checks",
            "full_profile_remains_available_for_record_chain_and_benchmark_diagnostics",
            "source_backed_raw_refs_remain_the_evidence_authority",
        ],
    }


def build_preflight_doctor(
    body: dict[str, Any] | None = None,
    *,
    memcore_root: str | Path | None = None,
    home: str | Path | None = None,
) -> dict[str, Any]:
    """Build a scored read-only preflight report.

    ``body["productized_payload"]`` may be supplied by tests or a caller that
    already ran the five productized loops. Otherwise this function runs the
    read-only productized loops doctor and scores its payload.
    """

    body = body if isinstance(body, dict) else {}
    diagnostic_profile = str(body.get("diagnostic_profile") or body.get("profile") or "full").strip().lower()
    if diagnostic_profile in {"smoke", "light", "hot_path"}:
        return _build_smoke_profile_preflight_doctor(body)
    if _bool(body.get("live_work_preflight_smoke"), False) and not isinstance(body.get("live_work_preflight_smoke"), dict):
        body = dict(body)
        body["live_work_preflight_smoke"] = _live_work_preflight_smoke_series(body)
    default_anchor = _live_smoke_default_work_anchor(body)
    productized = _dict(body.get("productized_payload")) or build_productized_loops_doctor(
        body,
        memcore_root=memcore_root,
        home=home,
    )
    loops = _dict(productized.get("loops"))
    preflight = _overlay_measured_preflight(body, _dict(loops.get("hot_path_preflight")))
    borrowing = _dict(loops.get("borrowing_receipts"))

    connection = _score_connection(productized, preflight)
    binding = _score_binding(preflight)
    fast_path = _score_fast_path(preflight)
    latency = _score_latency(body, preflight)
    recall = _score_recall(productized)
    source_backed = _score_source_backed(borrowing)
    raw_traceability = _score_source_backed(borrowing)
    projection = _score_projection(preflight)
    answer_debug_capability = _answer_debug_capability(preflight)
    answer_debug = _score_answer_debug(answer_debug_capability)
    absorption_contracts = _memory_absorption_contracts(body)
    experience, behavior_change, acceptance = _score_experience(productized)
    benchmark = _benchmark_readiness(productized)

    score_breakdown = {
        "connection_health_score": connection,
        "binding_health_score": binding,
        "fast_path_health_score": fast_path,
        "latency_score": latency,
        "recall_score": recall,
        "source_backed_score": source_backed,
        "raw_traceability_score": raw_traceability,
        "projection_explainability_score": projection,
        "answer_debug_score": answer_debug,
        "experience_intervention_score": experience,
        "behavior_change_score": behavior_change,
        "acceptance_check_score": acceptance,
        "benchmark_readiness": benchmark,
    }
    numeric_scores = [
        connection["score"],
        binding["score"],
        fast_path["score"],
        latency["score"],
        recall["score"],
        source_backed["score"],
        raw_traceability["score"],
        projection["score"],
        answer_debug["score"],
        experience["score"],
        behavior_change["score"],
        acceptance["score"],
        benchmark["score"],
    ]
    overall = _score(sum(numeric_scores) / len(numeric_scores))
    critical_attention = [
        name
        for name, item in score_breakdown.items()
        if isinstance(item, dict) and int(item.get("score") or 0) < 55
    ]

    return {
        "ok": bool(productized.get("ok")),
        "contract": PREFLIGHT_DOCTOR_CONTRACT,
        "version": PREFLIGHT_DOCTOR_VERSION,
        "generated_at": _now(),
        **_write_boundary(),
        "not_a_new_memory_layer": True,
        "under_tiandao_five_shelves": True,
        "doctor_score_contract": PREFLIGHT_DOCTOR_SCORE_CONTRACT,
        "overall_score": overall,
        "connection_health_score": connection["score"],
        "binding_health_score": binding["score"],
        "fast_path_health_score": fast_path["score"],
        "latency_score": latency["score"],
        "recall_score": recall["score"],
        "source_backed_score": source_backed["score"],
        "raw_traceability_score": raw_traceability["score"],
        "projection_explainability_score": projection["score"],
        "answer_debug_score": answer_debug["score"],
        "answer_debug_capability": answer_debug_capability,
        "memory_absorption_contracts": absorption_contracts,
        "live_work_preflight_smoke": _dict(body.get("live_work_preflight_smoke")),
        "experience_intervention_score": experience["score"],
        "behavior_change_score": behavior_change["score"],
        "acceptance_check_score": acceptance["score"],
        "benchmark_readiness_score": benchmark["score"],
        "benchmark_readiness": benchmark,
        "score_breakdown": score_breakdown,
        "critical_attention": critical_attention,
        "summary": {
            "classification": _dict(productized.get("summary")).get("preflight_classification", ""),
            "best_recall_mode": _dict(productized.get("summary")).get("benchmark_best_mode", ""),
            "xingce_signal_detected": bool(
                _dict(productized.get("summary")).get("benchmark_xingce_signal_detected")
            ),
            "experience_candidates": int(_dict(productized.get("summary")).get("experience_candidate_count") or 0),
            "borrowing_receipts": int(_dict(productized.get("summary")).get("borrowing_demo_receipts") or 0),
            "hermes_skill_experience_candidates": int(
                _dict(productized.get("summary")).get("hermes_upgrade_candidate_count") or 0
            ),
            "official_leaderboard_score": False,
            "default_work_anchor_applied": bool(default_anchor.get("applied", False)),
            "default_work_anchor": default_anchor,
        },
        "route_summary": {
            "entrypoint": "preflight_doctor",
            "uses": [
                "productized_loops_doctor",
                "connect_doctor",
                "agent_work_preflight",
                "recall_experience_benchmark",
                "borrowing_receipts",
                "experience_evolution_demo",
                "dialog_entry_answer_debug",
                "evidence_bound_model_gating",
                "memory_absorption_contracts",
                "evidence_atom_vocabulary",
                "search_think_boundary",
                "search_think_dry_run",
                "delivery_receipt_contract",
                "public_metric_claim_gate",
                "official_memory_benchmark_adapters",
            ],
            "final_evidence_authority": "raw_source_refs",
            "projection_authority": "navigation_hint_only",
            "answer_debug_authority": "diagnostic_only_not_evidence",
            "search_think_authority": "local_search_only_model_owned_think",
            "public_metric_claim_authority": "source_gate_required_before_public_homepage",
            "live_work_preflight_smoke": (
                "measured_overlay"
                if body.get("live_work_preflight_smoke")
                else "not_run"
            ),
            "default_work_anchor": default_anchor,
        },
        "boundary": {
            "official_leaderboard_score": False,
            "doctor_score_is_product_diagnostic": True,
            "tiny_fixture_is_internal_diagnostic_only": True,
            "no_raw_or_memory_write": True,
            "no_platform_write": True,
            "preflight_doctor_sent_model_request": False,
            "answer_debug_requires_explicit_request": True,
            "think_answer_must_be_model_owned": True,
            "public_metric_claim_requires_source_gate": True,
            "live_work_preflight_smoke_read_only": True,
            "default_work_anchor_applied": bool(default_anchor.get("applied", False)),
            "default_work_anchor_can_be_disabled_for_scope_required_diagnostics": True,
        },
        "productized_loops": productized if _bool(body.get("include_productized_payload"), False) else {
            "contract": productized.get("contract"),
            "version": productized.get("version"),
            "ok": productized.get("ok"),
            "evidence_status": productized.get("evidence_status"),
            "loop_ids": productized.get("loop_ids"),
            "loop_statuses": productized.get("loop_statuses"),
            "summary": productized.get("summary"),
            "receipts": productized.get("receipts"),
        },
        "notes": [
            "preflight_doctor_scores_existing_paths_only",
            "source_backed_raw_refs_remain_the_evidence_authority",
            "benchmark_readiness_is_separate_from_official_benchmark_score",
        ],
    }


__all__ = [
    "PREFLIGHT_DOCTOR_CONTRACT",
    "PREFLIGHT_DOCTOR_SCORE_CONTRACT",
    "PREFLIGHT_DOCTOR_VERSION",
    "build_preflight_doctor",
]
