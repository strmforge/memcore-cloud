#!/usr/bin/env python3
"""Logical-record and bounded-summary helpers for the raw record guardian."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


METADATA_ONLY_DIVERGENCE = "source_divergence_metadata_only_raw_retained"
GENERATION_ACTIVE_DIVERGENCE = "source_divergence_generation_active"
SAFE_RETAINED_STATUSES = {
    "record_guarded",
    "record_stat_guarded",
    METADATA_ONLY_DIVERGENCE,
    GENERATION_ACTIVE_DIVERGENCE,
    "authorized_raw_recoverable_source_missing",
    "authorized_raw_one_sided_source_missing",
    "authorized_raw_non_conversation_source_missing",
    "source_missing_recoverable_from_raw",
}
ATTENTION_STATUSES = {
    "raw_missing",
    "source_corrupt",
    "raw_corrupt",
    "source_regression_raw_retained",
    "source_divergence_raw_retained",
    GENERATION_ACTIVE_DIVERGENCE,
    "raw_monotonic_probe_incomplete",
    "source_missing_unrecoverable_from_raw",
    "authorized_raw_unrecoverable_source_missing",
}
RAW_NOT_CURRENT_STATUSES = {
    "raw_missing",
    "raw_lagging",
    "raw_catching_up",
    "source_regression_raw_retained",
    "source_divergence_raw_retained",
    "raw_monotonic_probe_incomplete",
    "raw_continuity_not_measured",
}
RECOVERABILITY_PROBE_INT_FIELDS = (
    "candidate_count",
    "candidate_limit",
    "per_file_byte_limit",
    "round_byte_limit",
    "targeted_scan_count",
    "cache_hit_count",
    "canonical_cache_hit_count",
    "measured_count",
    "not_measured_count",
    "bytes_read",
    "budget_exhausted_count",
    "one_sided_count",
    "non_conversation_count",
)
RECOVERABILITY_CACHE_STATUSES = frozenset({
    "available",
    "not_applicable",
    "not_needed",
})


def _text(value: Any) -> str:
    return str(value or "").strip()


def safe_recoverability_probe(probe: Any) -> dict[str, Any] | None:
    """Expose bounded recoverability evidence without cache errors or paths."""
    if not isinstance(probe, dict):
        return None
    safe: dict[str, Any] = {"schema": "recoverability_probe.v1"}
    for field in RECOVERABILITY_PROBE_INT_FIELDS:
        value = probe.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return None
        safe[field] = value
    cache_status = probe.get("canonical_cache_status")
    if not isinstance(cache_status, str) or not cache_status.strip():
        return None
    safe["canonical_cache_status"] = (
        cache_status if cache_status in RECOVERABILITY_CACHE_STATUSES else "unavailable"
    )
    return safe


def compact_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return status-page friendly records without heavy scan payloads."""
    compacted: list[dict[str, Any]] = []
    for item in records:
        guard_status = item.get("guard_status")
        if guard_status in {"record_guarded", "record_stat_guarded"} and not item.get("backfill_recommended"):
            continue
        source_scan = item.get("source_scan") if isinstance(item.get("source_scan"), dict) else {}
        raw_scan = item.get("raw_scan") if isinstance(item.get("raw_scan"), dict) else {}
        compacted.append({
            "source_system": item.get("source_system", ""),
            "artifact_type": item.get("artifact_type", ""),
            "session_id": item.get("session_id", ""),
            "raw_artifact_id": item.get("raw_artifact_id", ""),
            "canonical_window_id": item.get("canonical_window_id", ""),
            "project_id": item.get("project_id", ""),
            "thread_name": item.get("thread_name", ""),
            "guard_status": guard_status,
            "origin_id": item.get("origin_id", ""),
            "origin_status": item.get("origin_status", ""),
            "origin_label": item.get("origin_label", ""),
            "origin_seen": bool(item.get("origin_seen")),
            "raw_current": bool(item.get("raw_current")),
            "recoverable_from_raw": item.get("recoverable_from_raw"),
            "recoverability_status": item.get("recoverability_status", "not_measured"),
            "recoverability_class": item.get("recoverability_class", "not_measured"),
            "recoverability_evidence": item.get("recoverability_evidence") or {},
            "logical_record_id": item.get("logical_record_id", ""),
            "logical_variant_count": int(item.get("logical_variant_count", 1) or 1),
            "layout_variant": item.get("layout_variant", ""),
            "logical_variant_consistent": bool(item.get("logical_variant_consistent", True)),
            "backfill_recommended": bool(item.get("backfill_recommended")),
            "source_path_label": item.get("source_path_label", ""),
            "raw_path_label": item.get("raw_path_label", ""),
            "source_exists": bool(source_scan.get("exists")),
            "raw_exists": bool(raw_scan.get("exists")),
            "source_health_status": source_scan.get("health_status", ""),
            "raw_health_status": raw_scan.get("health_status", ""),
            "source_size_bytes": int(source_scan.get("size_bytes", 0) or 0),
            "raw_size_bytes": int(raw_scan.get("size_bytes", 0) or 0),
            "health_warnings": item.get("health_warnings", []),
            "sync": item.get("sync") or {},
            "scan_mode": item.get("scan_mode", ""),
        })
    return compacted


def _logical_key(
    item: dict[str, Any],
    physical_index: int,
    *,
    authorized_artifact_type: str,
) -> tuple[str, ...]:
    if (
        _text(item.get("source_system")) == "claude_desktop"
        and _text(item.get("artifact_type")) == authorized_artifact_type
    ):
        native_id = _text(
            item.get("session_id")
            or item.get("raw_artifact_id")
            or item.get("canonical_window_id")
        )
        if native_id:
            return ("layout_variants", "claude_desktop", authorized_artifact_type, native_id)
    return ("physical", str(physical_index))


def annotate_logical_records(
    records: list[dict[str, Any]],
    *,
    authorized_artifact_type: str,
) -> list[dict[str, Any]]:
    groups: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for index, item in enumerate(records):
        key = _logical_key(item, index, authorized_artifact_type=authorized_artifact_type)
        groups.setdefault(key, []).append(item)

    representatives: list[dict[str, Any]] = []
    for key, variants in groups.items():
        logical_id = hashlib.sha256("\x1f".join(key).encode("utf-8")).hexdigest()[:24]
        evidence_signatures = {
            (
                item.get("recoverable_from_raw"),
                _text(item.get("recoverability_class")),
                _text(item.get("guard_status")),
            )
            for item in variants
        }
        for item in variants:
            item["logical_record_id"] = logical_id
            item["logical_variant_count"] = len(variants)
            item["layout_variant"] = Path(_text(item.get("raw_path"))).parent.name
            item["logical_variant_consistent"] = len(evidence_signatures) == 1

        def representative_rank(item: dict[str, Any]) -> tuple[int, int]:
            value = item.get("recoverable_from_raw")
            evidence_rank = 0 if value is False else 1 if value is None else 2
            attention_rank = 0 if (
                _text(item.get("guard_status")) in ATTENTION_STATUSES
                or item.get("backfill_recommended")
            ) else 1
            return evidence_rank, attention_rank

        representatives.append(min(variants, key=representative_rank))
    return representatives


def record_population_scope(
    scope: dict[str, dict[str, Any]] | None,
    key: str,
    *,
    source_system: str,
    observed_count: int,
    included_count: int,
    truncated: bool,
    targeted: bool = False,
) -> None:
    if scope is None:
        return
    scope[key] = {
        "source_system": source_system,
        "observed_count": max(0, int(observed_count)),
        "observed_count_is_lower_bound": bool(truncated),
        "included_count": max(0, int(included_count)),
        "truncated": bool(truncated),
        "population_complete": not truncated and not targeted,
        "targeted": bool(targeted),
    }


def build_summary_scope(
    population_sources: dict[str, dict[str, Any]],
    *,
    scan_mode: str,
    source_filter: set[str],
    population_limit: int,
    detail_limit: int,
    targeted_refresh: bool,
) -> dict[str, Any]:
    population_complete = bool(population_sources) and all(
        item.get("population_complete") is True
        for item in population_sources.values()
    )
    signature = {
        "scan_mode": scan_mode,
        "source_system_filter": sorted(source_filter),
        "population_limit_per_source": population_limit,
        "targeted_refresh": targeted_refresh,
        "sources": [
            {
                "name": key,
                "population_complete": bool(value.get("population_complete")),
                "truncated": bool(value.get("truncated")),
                "targeted": bool(value.get("targeted")),
            }
            for key, value in sorted(population_sources.items())
        ],
    }
    return {
        "population_complete": population_complete,
        "summary_is_sample": not population_complete,
        "detail_limit": detail_limit,
        "population_limit_per_source": population_limit,
        "targeted_refresh": targeted_refresh,
        "sources": population_sources,
        "trend_comparison_key": hashlib.sha256(
            json.dumps(signature, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
    }


def summarize_records(
    records: list[dict[str, Any]],
    *,
    physical_record_count: int,
    time_origin: dict[str, Any],
    gap_source_count: int,
    inactive_source_count: int,
) -> tuple[bool, dict[str, Any]]:
    statuses = [_text(item.get("guard_status")) for item in records]
    count_status = lambda *wanted: sum(status in wanted for status in statuses)
    recoverable = sum(item.get("recoverable_from_raw") is True for item in records)
    unrecoverable = sum(item.get("recoverable_from_raw") is False for item in records)
    not_measured = sum(item.get("recoverable_from_raw") is None for item in records)
    unhealthy = sum(status not in SAFE_RETAINED_STATUSES for status in statuses)
    corrupt = count_status("source_corrupt", "raw_corrupt")
    oversized = sum(
        any("oversized" in warning for warning in item.get("health_warnings", []))
        for item in records
    )
    partial = sum(
        "partial" in status or status == "source_metadata_incomplete"
        for status in statuses
    )
    attention = sum(
        status in ATTENTION_STATUSES or bool(item.get("backfill_recommended"))
        for status, item in zip(statuses, records)
    )
    backfill = sum(bool(item.get("backfill_recommended")) for item in records)
    logical_count = len(records)
    summary = {
        "record_count": logical_count,
        "physical_record_count": physical_record_count,
        "logical_record_count": logical_count,
        "layout_variant_count": max(0, physical_record_count - logical_count),
        "record_guarded_count": count_status(
            "record_guarded",
            "record_stat_guarded",
            GENERATION_ACTIVE_DIVERGENCE,
        ),
        "record_stat_guarded_count": count_status("record_stat_guarded"),
        "unhealthy_record_count": unhealthy,
        "raw_not_current_count": sum(status in RAW_NOT_CURRENT_STATUSES for status in statuses),
        "raw_lagging_or_missing_count": count_status("raw_missing", "raw_lagging"),
        "raw_catching_up_count": count_status("raw_catching_up"),
        "raw_active_catching_up_count": count_status("raw_catching_up"),
        "raw_attention_count": attention,
        "raw_source_regression_count": count_status("source_regression_raw_retained"),
        "raw_source_divergence_count": count_status(
            "source_divergence_raw_retained",
            GENERATION_ACTIVE_DIVERGENCE,
        ),
        "raw_divergence_generation_active_count": count_status(GENERATION_ACTIVE_DIVERGENCE),
        "raw_metadata_only_divergence_count": count_status(METADATA_ONLY_DIVERGENCE),
        "raw_monotonic_probe_incomplete_count": count_status("raw_monotonic_probe_incomplete"),
        "raw_continuity_not_measured_count": sum(
            bool((item.get("sync") or {}).get("raw_continuity_not_measured"))
            for item in records
        ),
        "corrupt_record_count": corrupt,
        "oversized_record_count": oversized,
        "partial_record_count": partial,
        "recoverable_from_raw_count": recoverable,
        "unrecoverable_from_raw_count": unrecoverable,
        "recoverability_not_measured_count": not_measured,
        "gap_source_count": gap_source_count,
        "inactive_source_count": inactive_source_count,
        "backfill_recommended_count": backfill,
        "max_raw_lag_bytes": max((
            int(((item.get("sync") or {}).get("raw_archive_lag_bytes", 0)) or 0)
            for item in records
        ), default=0),
        "max_raw_lag_milliseconds": max((
            int(((item.get("sync") or {}).get("raw_archive_lag_milliseconds", 0)) or 0)
            for item in records
        ), default=0),
    }
    for key in (
        "origin_event_count",
        "origin_witnessed_count",
        "lost_source_count",
        "lost_raw_count",
        "source_without_origin_count",
        "origin_without_raw_count",
        "raw_without_origin_count",
        "recoverable_origin_count",
        "unrecoverable_origin_count",
        "not_measured_origin_count",
        "lost_source_recoverable_count",
        "lost_source_unrecoverable_count",
        "lost_source_not_measured_count",
        "lost_source_one_sided_count",
        "lost_source_non_conversation_count",
        "max_origin_lag_milliseconds",
    ):
        summary[key] = time_origin.get(key, 0)
    summary["lost_labels"] = time_origin.get("lost_labels", {})
    return (
        not corrupt
        and not attention
        and not summary["raw_continuity_not_measured_count"]
    ), summary
