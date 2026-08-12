#!/usr/bin/env python3
"""Divergence-generation evidence helpers for the raw record guardian."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

try:
    from raw_archive_monotonic import generation_descriptor_path, load_generation_descriptor
except ImportError:  # pragma: no cover
    from src.raw_archive_monotonic import generation_descriptor_path, load_generation_descriptor


UTC = timezone.utc
RecordScanner = Callable[..., dict[str, Any]]
PathLabeler = Callable[[Any], str]


def _text(value: Any) -> str:
    return str(value or "").strip()


def fast_jsonl_stat(
    path: str | Path,
    *,
    source_system: str,
    path_label: PathLabeler,
) -> dict[str, Any]:
    raw_path = Path(path).expanduser()
    try:
        stat = raw_path.stat()
    except OSError:
        return {
            "ok": False,
            "path": str(raw_path),
            "path_label": path_label(raw_path),
            "exists": False,
            "health_status": "missing_file",
            "metadata_ok": None,
            "has_user_and_assistant": None,
            "fast_stat_only": True,
        }
    return {
        "ok": True,
        "path": str(raw_path),
        "path_label": path_label(raw_path),
        "exists": True,
        "file_identity": {
            "device": int(stat.st_dev),
            "inode": int(stat.st_ino),
            "size_bytes": int(stat.st_size),
            "mtime_ns": int(getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000))),
        },
        "size_bytes": stat.st_size,
        "mtime_epoch": stat.st_mtime,
        "mtime": datetime.fromtimestamp(stat.st_mtime, UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "health_status": "stat_only",
        "metadata_ok": None,
        "has_user_and_assistant": None,
        "bad_json_line_count": None,
        "oversize_record_count": None,
        "user_turn_count": None,
        "assistant_turn_count": None,
        "message_count": None,
        "fast_stat_only": True,
        "source_system": source_system,
    }


def generation_lineage(raw_path: str | Path) -> tuple[list[Path], bool, str]:
    current = Path(raw_path).expanduser()
    descriptor = load_generation_descriptor(current)
    if not descriptor:
        return [current], True, "not_applicable"
    newest_to_oldest: list[Path] = []
    seen: set[str] = set()
    for _ in range(64):
        key = os.path.normcase(os.path.abspath(current))
        if key in seen:
            return list(reversed(newest_to_oldest)), False, "generation_lineage_cycle"
        seen.add(key)
        newest_to_oldest.append(current)
        if not current.is_file():
            return list(reversed(newest_to_oldest)), False, "generation_predecessor_missing"
        descriptor = load_generation_descriptor(current)
        if not descriptor:
            if generation_descriptor_path(current).exists():
                return list(reversed(newest_to_oldest)), False, "generation_descriptor_invalid"
            return list(reversed(newest_to_oldest)), True, "complete"
        predecessor = _text(descriptor.get("predecessor"))
        if not predecessor:
            return list(reversed(newest_to_oldest)), False, "generation_predecessor_unspecified"
        current = Path(predecessor).expanduser()
    return list(reversed(newest_to_oldest)), False, "generation_lineage_limit_exceeded"


def scan_generation_lineage(
    raw_path: str | Path,
    *,
    source_system: str,
    oversize_bytes: int,
    scan_record: RecordScanner,
    fast_stat: RecordScanner,
) -> dict[str, Any]:
    lineage, complete, lineage_status = generation_lineage(raw_path)
    if len(lineage) == 1 and not load_generation_descriptor(lineage[0]):
        return scan_record(lineage[0], source_system=source_system, oversize_bytes=oversize_bytes)
    scans = [
        scan_record(path, source_system=source_system, oversize_bytes=oversize_bytes)
        for path in lineage
    ]
    current = dict(scans[-1]) if scans else fast_stat(raw_path, source_system=source_system)
    complete = bool(complete and scans and all(scan.get("exists") for scan in scans))
    user_turn_count = sum(int(scan.get("user_turn_count", 0) or 0) for scan in scans)
    assistant_turn_count = sum(int(scan.get("assistant_turn_count", 0) or 0) for scan in scans)
    bad_json_line_count = sum(int(scan.get("bad_json_line_count", 0) or 0) for scan in scans)
    oversize_record_count = sum(int(scan.get("oversize_record_count", 0) or 0) for scan in scans)
    metadata_scan = next((scan for scan in scans if scan.get("metadata_ok")), {})
    metadata_ok = bool(metadata_scan)
    has_user_and_assistant = bool(user_turn_count and assistant_turn_count)
    health_status = "ok"
    if not complete:
        health_status = "generation_lineage_incomplete"
    elif bad_json_line_count:
        health_status = "corrupt_jsonl"
    elif oversize_record_count:
        health_status = "oversized_records"
    elif not metadata_ok:
        health_status = "metadata_incomplete"
    elif user_turn_count and not assistant_turn_count:
        health_status = "user_only"
    elif assistant_turn_count and not user_turn_count:
        health_status = "assistant_only"
    elif not has_user_and_assistant:
        health_status = "no_complete_conversation"
    current.update({
        "ok": health_status == "ok",
        "health_status": health_status,
        "metadata_ok": metadata_ok,
        "metadata_rule": metadata_scan.get("metadata_rule", "generation_lineage_aggregate"),
        "missing_session_meta": not metadata_ok,
        "line_count": sum(int(scan.get("line_count", 0) or 0) for scan in scans),
        "valid_json_line_count": sum(int(scan.get("valid_json_line_count", 0) or 0) for scan in scans),
        "bad_json_line_count": bad_json_line_count,
        "oversize_record_count": oversize_record_count,
        "max_line_bytes": max((int(scan.get("max_line_bytes", 0) or 0) for scan in scans), default=0),
        "user_turn_count": user_turn_count,
        "assistant_turn_count": assistant_turn_count,
        "tool_turn_count": sum(int(scan.get("tool_turn_count", 0) or 0) for scan in scans),
        "content_message_count": sum(int(scan.get("content_message_count", 0) or 0) for scan in scans),
        "message_count": user_turn_count + assistant_turn_count,
        "has_user_and_assistant": has_user_and_assistant,
        "generation_lineage_complete": complete,
        "generation_lineage_status": lineage_status,
        "generation_lineage_count": len(lineage),
        "generation_lineage_paths": [str(path) for path in lineage],
        "generation_lineage_physical_size_bytes": sum(
            int(scan.get("size_bytes", 0) or 0) for scan in scans
        ),
    })
    return current


def apply_sync_evidence(
    sync_item: dict[str, Any],
    source_scan: dict[str, Any],
    raw_path: str | Path,
) -> None:
    descriptor = load_generation_descriptor(raw_path) if raw_path else {}
    generation_active = bool(descriptor)
    if sync_item.get("raw_divergence_generation_active") and not generation_active:
        sync_item["raw_monotonic_probe_ok"] = False
        sync_item["raw_monotonic_status"] = "raw_generation_descriptor_incomplete"
    if not generation_active:
        return
    try:
        physical_raw_size = Path(raw_path).expanduser().stat().st_size
    except OSError:
        physical_raw_size = 0
    source_base_offset = int(descriptor.get("source_base_offset", 0) or 0)
    source_size = int(source_scan.get("size_bytes", 0) or 0)
    covered_source_bytes = source_base_offset + physical_raw_size
    sync_item.update({
        "raw_divergence_generation_active": True,
        "raw_source_divergence": True,
        "raw_generation": int(descriptor.get("generation", 0) or 0),
        "raw_generation_predecessor": _text(descriptor.get("predecessor")),
        "raw_source_base_offset": source_base_offset,
        "raw_physical_size_bytes": physical_raw_size,
        "raw_covered_source_bytes": covered_source_bytes,
        "raw_stale": covered_source_bytes < source_size,
        "raw_stale_authoritative": True,
        "raw_archive_lag_bytes": max(0, source_size - covered_source_bytes),
        "raw_size_delta_bytes": abs(source_size - covered_source_bytes),
    })


def active_guard_status(
    source_scan: dict[str, Any],
    raw_scan: dict[str, Any],
    sync_item: dict[str, Any],
    *,
    validate_content: bool,
) -> str | None:
    if not sync_item.get("raw_divergence_generation_active"):
        return None
    if sync_item.get("raw_monotonic_probe_ok") is False:
        return "raw_monotonic_probe_incomplete"
    if sync_item.get("raw_lag_sla_breach"):
        return "raw_lagging"
    if sync_item.get("raw_stale"):
        return "raw_catching_up"
    if validate_content:
        if source_scan.get("bad_json_line_count"):
            return "source_corrupt"
        if raw_scan.get("bad_json_line_count") or raw_scan.get("generation_lineage_complete") is False:
            return "raw_corrupt"
        if not source_scan.get("metadata_ok"):
            return "source_metadata_incomplete"
        if not source_scan.get("has_user_and_assistant"):
            return "source_partial_conversation"
        if not raw_scan.get("has_user_and_assistant"):
            return "raw_partial_conversation"
    return "source_divergence_generation_active"


def sync_payload(sync_item: dict[str, Any]) -> dict[str, Any]:
    return {
        "raw_divergence_generation_active": bool(sync_item.get("raw_divergence_generation_active")),
        "raw_generation_descriptor_incomplete": bool(sync_item.get("raw_generation_descriptor_incomplete")),
        "raw_generation": int(sync_item.get("raw_generation", 0) or 0),
        "raw_generation_predecessor": _text(sync_item.get("raw_generation_predecessor")),
        "raw_source_base_offset": int(sync_item.get("raw_source_base_offset", 0) or 0),
        "raw_physical_size_bytes": int(sync_item.get("raw_physical_size_bytes", 0) or 0),
        "raw_covered_source_bytes": int(sync_item.get("raw_covered_source_bytes", 0) or 0),
    }
