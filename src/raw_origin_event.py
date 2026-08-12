#!/usr/bin/env python3
"""Raw origin event helpers.
时间起源 is the raw layer's first witnessed event for a local source stream.
This module is deliberately pure: it builds auditable descriptors and never
writes raw, platform config, or memory by itself.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from tiandao.memory_routing import (
        TIANDAO_TIME_ORIGIN_CONTRACT,
        TIANDAO_TIME_RIVER_CONTRACT,
    )
except ImportError:  # pragma: no cover
    from src.tiandao.memory_routing import (
        TIANDAO_TIME_ORIGIN_CONTRACT,
        TIANDAO_TIME_RIVER_CONTRACT,
    )

RAW_ORIGIN_EVENT_CONTRACT = "raw_origin_event.v1"
TIME_ORIGIN_LAYER = "raw"
ORIGIN_STATUS_WITNESSED = "origin_witnessed"
ORIGIN_STATUS_LOST_SOURCE = "lost_source"
ORIGIN_STATUS_LOST_RAW = "lost_raw"
ORIGIN_STATUS_UNAVAILABLE = "origin_unavailable"
ORIGIN_LOST_SOURCE_LABEL = "遗失源"
ORIGIN_LOST_RAW_LABEL = "遗失 raw"


def ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _stable_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except Exception:
        return str(value)


def classify_origin_status(*, source_exists: bool, raw_exists: bool) -> str:
    if source_exists and raw_exists:
        return ORIGIN_STATUS_WITNESSED
    if source_exists and not raw_exists:
        return ORIGIN_STATUS_LOST_RAW
    if raw_exists and not source_exists:
        return ORIGIN_STATUS_LOST_SOURCE
    return ORIGIN_STATUS_UNAVAILABLE


def origin_status_label(origin_status: str) -> str:
    if origin_status == ORIGIN_STATUS_LOST_SOURCE:
        return ORIGIN_LOST_SOURCE_LABEL
    if origin_status == ORIGIN_STATUS_LOST_RAW:
        return ORIGIN_LOST_RAW_LABEL
    if origin_status == ORIGIN_STATUS_WITNESSED:
        return "起源已见证"
    return "起源不可用"


def _fingerprint_from_scan(path: str, scan: dict[str, Any]) -> str:
    basis = "|".join([
        _safe_str(path),
        str(scan.get("size_bytes", "")),
        _safe_str(scan.get("mtime") or scan.get("mtime_epoch")),
        _safe_str(scan.get("line_count")),
        _safe_str(scan.get("message_count")),
    ])
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def build_raw_origin_event(
    *,
    source_system: str,
    computer_id: str = "",
    native_session_key: str = "",
    source_path: str = "",
    raw_path: str = "",
    source_exists: bool = False,
    raw_exists: bool = False,
    event_time: str = "",
    captured_at: str = "",
    audit_time: str = "",
    content_hash: str = "",
    byte_offset: int | None = None,
    line_no: int | None = None,
    source_refs: dict[str, Any] | None = None,
    origin_status: str = "",
) -> dict[str, Any]:
    status = origin_status or classify_origin_status(
        source_exists=bool(source_exists),
        raw_exists=bool(raw_exists),
    )
    refs = dict(source_refs or {})
    if source_path and "source_path" not in refs:
        refs["source_path"] = source_path
    if raw_path and "raw_session_path" not in refs:
        refs["raw_session_path"] = raw_path
    if source_system and "source_system" not in refs:
        refs["source_system"] = source_system
    digest = content_hash or hashlib.sha256(
        "|".join([
            _safe_str(source_system),
            _safe_str(computer_id),
            _safe_str(native_session_key),
            _safe_str(source_path),
            _safe_str(raw_path),
            _stable_json(refs),
        ]).encode("utf-8")
    ).hexdigest()
    origin_id_basis = "|".join([
        _safe_str(source_system),
        _safe_str(computer_id),
        _safe_str(native_session_key),
        _safe_str(raw_path or source_path),
        digest,
        str(byte_offset if byte_offset is not None else ""),
        str(line_no if line_no is not None else ""),
    ])
    origin_id = "origin_" + hashlib.sha256(origin_id_basis.encode("utf-8")).hexdigest()[:32]
    return {
        "ok": status == ORIGIN_STATUS_WITNESSED,
        "contract": RAW_ORIGIN_EVENT_CONTRACT,
        "origin_contract": TIANDAO_TIME_ORIGIN_CONTRACT,
        "time_river_contract": TIANDAO_TIME_RIVER_CONTRACT,
        "origin_id": origin_id,
        "origin_layer": TIME_ORIGIN_LAYER,
        "origin_status": status,
        "origin_label": origin_status_label(status),
        "origin_seen": status == ORIGIN_STATUS_WITNESSED,
        "source_exists": bool(source_exists),
        "raw_exists": bool(raw_exists),
        "source_system": _safe_str(source_system),
        "computer_id": _safe_str(computer_id),
        "native_session_key": _safe_str(native_session_key),
        "source_path": _safe_str(source_path),
        "raw_path": _safe_str(raw_path),
        "event_time": _safe_str(event_time),
        "captured_at": _safe_str(captured_at),
        "audit_time": _safe_str(audit_time or ts()),
        "content_hash": digest,
        "byte_offset": byte_offset,
        "line_no": line_no,
        "source_refs": refs,
        "no_raw_no_river": True,
        "derived_sediment_policy": "derived_sediment_must_reference_origin",
        "multi_machine_policy": "source_streams_merge_not_overwrite",
        "platform_policy": "platforms_are_inlets_not_origin",
        "river_endpoint_policy": "time_river_has_no_endpoint",
        "write_performed": False,
        "platform_write_performed": False,
        "memory_write_performed": False,
    }


def build_raw_origin_event_from_guardian_item(
    item: dict[str, Any],
    *,
    computer_id: str = "",
) -> dict[str, Any]:
    source_scan = item.get("source_scan") if isinstance(item.get("source_scan"), dict) else {}
    raw_scan = item.get("raw_scan") if isinstance(item.get("raw_scan"), dict) else {}
    source_path = _safe_str(item.get("source_path") or source_scan.get("path"))
    raw_path = _safe_str(item.get("raw_path") or raw_scan.get("path"))
    source_exists = bool(source_scan.get("exists")) if source_scan else bool(source_path and Path(source_path).expanduser().exists())
    raw_exists = bool(raw_scan.get("exists")) if raw_scan else bool(raw_path and Path(raw_path).expanduser().exists())
    fingerprint = _fingerprint_from_scan(raw_path, raw_scan) if raw_exists else _fingerprint_from_scan(source_path, source_scan)
    source_refs = {
        "source_system": item.get("source_system", ""),
        "session_id": item.get("session_id", ""),
        "canonical_window_id": item.get("canonical_window_id", ""),
        "raw_artifact_id": item.get("raw_artifact_id", ""),
        "artifact_type": item.get("artifact_type", ""),
        "source_path": source_path,
        "raw_session_path": raw_path,
        "project_id": item.get("project_id", ""),
        "project_root": item.get("project_root", ""),
        "thread_name": item.get("thread_name", ""),
    }
    return build_raw_origin_event(
        source_system=_safe_str(item.get("source_system")),
        computer_id=computer_id,
        native_session_key=_safe_str(
            item.get("session_id")
            or item.get("raw_artifact_id")
            or item.get("canonical_window_id")
        ),
        source_path=source_path,
        raw_path=raw_path,
        source_exists=source_exists,
        raw_exists=raw_exists,
        event_time=_safe_str(source_scan.get("mtime") or raw_scan.get("mtime")),
        captured_at=_safe_str(raw_scan.get("mtime")),
        content_hash=fingerprint,
        byte_offset=0,
        line_no=1,
        source_refs=source_refs,
    )


def attach_origin_events(
    records: list[dict[str, Any]],
    *,
    computer_id: str = "",
) -> list[dict[str, Any]]:
    for item in records:
        if not isinstance(item, dict):
            continue
        event = build_raw_origin_event_from_guardian_item(item, computer_id=computer_id)
        item["origin_event"] = event
        item["origin_id"] = event["origin_id"]
        item["origin_status"] = event["origin_status"]
        item["origin_label"] = event["origin_label"]
        item["origin_seen"] = event["origin_seen"]
        item["lost_source"] = event["origin_status"] == ORIGIN_STATUS_LOST_SOURCE
        item["lost_raw"] = event["origin_status"] == ORIGIN_STATUS_LOST_RAW
    return records


def _origin_order_key(event: dict[str, Any]) -> tuple[str, str, str]:
    return (
        _safe_str(event.get("event_time")) or "9999-12-31T23:59:59Z",
        _safe_str(event.get("audit_time")) or "9999-12-31T23:59:59Z",
        _safe_str(event.get("origin_id")),
    )


def _local_runtime_key(event: dict[str, Any]) -> tuple[str, str]:
    return (
        _safe_str(event.get("computer_id")) or "unknown_computer",
        _safe_str(event.get("source_system")) or "unknown_source_system",
    )


def first_witnessed_raw_by_local_runtime(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return the first witnessed raw origin for each observed local runtime.

    This is a read-only repository summary. It groups only the records present
    in the caller-provided list and does not claim global or multi-machine
    completeness.
    """
    first_by_runtime: dict[tuple[str, str], dict[str, Any]] = {}
    for item in records:
        if not isinstance(item, dict) or not isinstance(item.get("origin_event"), dict):
            continue
        event = item["origin_event"]
        if event.get("origin_status") != ORIGIN_STATUS_WITNESSED:
            continue
        if event.get("origin_layer") != TIME_ORIGIN_LAYER:
            continue
        runtime_key = _local_runtime_key(event)
        current = first_by_runtime.get(runtime_key)
        if current is None or _origin_order_key(event) < _origin_order_key(current):
            first_by_runtime[runtime_key] = event

    first_events: list[dict[str, Any]] = []
    for computer_id, source_system in sorted(first_by_runtime):
        event = first_by_runtime[(computer_id, source_system)]
        first_events.append({
            "local_runtime_key": f"{computer_id}:{source_system}",
            "computer_id": computer_id,
            "source_system": source_system,
            "origin_id": event.get("origin_id", ""),
            "origin_layer": event.get("origin_layer", ""),
            "origin_status": event.get("origin_status", ""),
            "origin_seen": bool(event.get("origin_seen")),
            "native_session_key": event.get("native_session_key", ""),
            "event_time": event.get("event_time", ""),
            "audit_time": event.get("audit_time", ""),
            "source_refs": dict(event.get("source_refs") or {}),
        })
    return first_events


def origin_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    events = [
        item.get("origin_event")
        for item in records
        if isinstance(item, dict) and isinstance(item.get("origin_event"), dict)
    ]
    witnessed = [event for event in events if event.get("origin_status") == ORIGIN_STATUS_WITNESSED]
    lost_sources = [event for event in events if event.get("origin_status") == ORIGIN_STATUS_LOST_SOURCE]
    lost_raw = [event for event in events if event.get("origin_status") == ORIGIN_STATUS_LOST_RAW]
    unavailable = [event for event in events if event.get("origin_status") == ORIGIN_STATUS_UNAVAILABLE]
    source_without_origin = [
        event for event in events
        if event.get("source_exists") and not event.get("origin_seen")
    ]
    raw_without_source = [
        event for event in events
        if event.get("raw_exists") and not event.get("source_exists")
    ]
    max_lag_ms = max((
        int(((item.get("sync") or {}).get("raw_archive_lag_milliseconds", 0)) or 0)
        for item in records
        if isinstance(item, dict)
    ), default=0)
    recoverable_origin = [
        item for item in records
        if isinstance(item, dict)
        and item.get("origin_status") == ORIGIN_STATUS_LOST_SOURCE
        and item.get("recoverable_from_raw") is True
    ]
    unrecoverable_origin = [
        item for item in records
        if isinstance(item, dict)
        and item.get("origin_status") == ORIGIN_STATUS_LOST_SOURCE
        and item.get("recoverable_from_raw") is False
    ]
    not_measured_origin = [
        item for item in records
        if isinstance(item, dict)
        and item.get("origin_status") == ORIGIN_STATUS_LOST_SOURCE
        and item.get("recoverable_from_raw") is None
    ]
    one_sided_origin = [
        item for item in records
        if isinstance(item, dict)
        and item.get("origin_status") == ORIGIN_STATUS_LOST_SOURCE
        and item.get("recoverability_class") == "conversation_one_sided"
    ]
    non_conversation_origin = [
        item for item in records
        if isinstance(item, dict)
        and item.get("origin_status") == ORIGIN_STATUS_LOST_SOURCE
        and item.get("recoverability_class") == "non_conversation_structurally_valid"
    ]
    first_by_runtime = first_witnessed_raw_by_local_runtime(records)
    return {
        "contract": TIANDAO_TIME_ORIGIN_CONTRACT,
        "raw_origin_event_contract": RAW_ORIGIN_EVENT_CONTRACT,
        "origin_layer": TIME_ORIGIN_LAYER,
        "origin_event_count": len(witnessed),
        "origin_witnessed_count": len(witnessed),
        "lost_source_count": len(lost_sources),
        "lost_raw_count": len(lost_raw),
        "source_without_origin_count": len(source_without_origin),
        "origin_without_raw_count": len(lost_raw),
        "raw_without_origin_count": len(raw_without_source),
        "raw_without_source_count": len(raw_without_source),
        "origin_unavailable_count": len(unavailable),
        "recoverable_origin_count": len(recoverable_origin),
        "unrecoverable_origin_count": len(unrecoverable_origin),
        "not_measured_origin_count": len(not_measured_origin),
        "lost_source_recoverable_count": len(recoverable_origin),
        "lost_source_unrecoverable_count": len(unrecoverable_origin),
        "lost_source_not_measured_count": len(not_measured_origin),
        "lost_source_one_sided_count": len(one_sided_origin),
        "lost_source_non_conversation_count": len(non_conversation_origin),
        "max_origin_lag_milliseconds": max_lag_ms,
        "local_runtime_policy": "each_runtime_has_first_witnessed_raw_event",
        "local_runtime_first_witnessed_raw_count": len(first_by_runtime),
        "local_runtime_first_witnessed_raw": first_by_runtime,
        "local_runtime_grouping": ["computer_id", "source_system"],
        "local_runtime_order": ["event_time", "audit_time", "origin_id"],
        "local_runtime_scope": "observed_repository_records_only",
        "lost_labels": {
            "lost_source": ORIGIN_LOST_SOURCE_LABEL,
            "lost_raw": ORIGIN_LOST_RAW_LABEL,
        },
        "no_raw_no_river": True,
        "time_river_has_no_endpoint": True,
        "multi_machine_policy": "source_streams_merge_not_overwrite",
    }
