#!/usr/bin/env python3
"""Canonical dialogue capture sidecar for JSONL session archives.

Main river = canonical dialogue.
Cold layer = forensic runtime manifest over the full raw archive.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from src.raw_record_canonical_index import (
        _canonical_index_max_json_line_bytes,
        _stream_jsonl_canonical_entries,
    )
except ImportError:  # pragma: no cover
    from raw_record_canonical_index import (  # type: ignore
        _canonical_index_max_json_line_bytes,
        _stream_jsonl_canonical_entries,
    )


UTC = timezone.utc
CANONICAL_DIALOGUE_CAPTURE_CONTRACT = "time_library_canonical_dialogue_capture.v1"
FORENSIC_RUNTIME_MANIFEST_CONTRACT = "time_library_forensic_runtime_manifest.v1"
CANONICAL_DIALOGUE_RECORD_TYPE = "canonical_dialogue_message"
SEMANTIC_FILTER_VERSION = "canonical_dialogue_filter.v1"
CANONICAL_DIALOGUE_MIGRATION_REPORT_CONTRACT = "time_library_canonical_dialogue_migration_report.v1"

_RUNTIME_BLOB_MARKERS = (
    "data:image/",
    "base64,",
    "<environment_context>",
    "<filesystem>",
    "<current_date>",
    "# files mentioned by the user:",
    "files mentioned by the user",
)


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def canonical_dialogue_sidecar_path(raw_path: str | Path) -> Path:
    return Path(f"{Path(raw_path).expanduser()}.canonical_dialogue.jsonl")


def forensic_runtime_manifest_path(raw_path: str | Path) -> Path:
    return Path(f"{Path(raw_path).expanduser()}.forensic_runtime.json")


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{time.monotonic_ns()}.tmp")
    try:
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass


def _load_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _text(value: Any) -> str:
    return str(value or "")


def _source_ref_text(source_path: str | Path, start: int, end: int) -> str:
    return f"{Path(source_path).expanduser()}:{int(start)}-{int(end)}"


def _read_exact_bytes(source_path: str | Path, start: int, end: int) -> bytes:
    path = Path(source_path).expanduser()
    if not path.is_file() or start < 0 or end <= start:
        return b""
    try:
        with path.open("rb") as handle:
            handle.seek(int(start))
            return handle.read(max(0, int(end) - int(start)))
    except OSError:
        return b""


def _iter_sidecar_entries(dialogue_path: str | Path) -> list[dict[str, Any]]:
    path = Path(dialogue_path).expanduser()
    if not path.exists():
        return []
    entries: list[dict[str, Any]] = []
    offset = 0
    with path.open("rb") as handle:
        while True:
            start = offset
            raw_line = handle.readline()
            if not raw_line:
                break
            offset += len(raw_line)
            if not raw_line.strip():
                continue
            try:
                decoded = raw_line.decode("utf-8")
                item = json.loads(decoded)
            except Exception:
                continue
            if not isinstance(item, dict):
                continue
            item["_sidecar_offset_start"] = start
            item["_sidecar_offset_end"] = offset
            item["_sidecar_line_bytes"] = len(raw_line)
            entries.append(item)
    return entries


def _filter_reason(message: dict[str, Any]) -> str:
    role = _text(message.get("role")).strip().lower()
    native_type = _text(message.get("native_type")).strip().lower()
    content = _text(message.get("content"))
    if native_type in {"tool_result", "function_call_output"}:
        return "runtime_tool_event"
    if role not in {"user", "assistant"}:
        return "non_dialogue_role"
    if not content.strip():
        return "empty_content"
    lowered = content.lower()
    if any(marker in lowered for marker in _RUNTIME_BLOB_MARKERS):
        return "runtime_blob"
    if len(content) > 16384 and ("base64" in lowered or "data:" in lowered):
        return "oversized_runtime_blob"
    return ""


def _entry_for_message(
    message: dict[str, Any],
    *,
    source_system: str,
    session_id: str,
    canonical_window_id: str,
    raw_path: Path,
    native_artifact_format: str,
    native_source_path: str,
    source_base_offset: int,
    generation: int,
    predecessor: str,
) -> dict[str, Any]:
    content = _text(message.get("content"))
    native_id = _text(message.get("native_id"))
    content_hash = _text(message.get("content_hash")) or hashlib.sha256(content.encode("utf-8")).hexdigest()
    raw_offset_start = int(message.get("offset_start") or 0)
    raw_offset_end = int(message.get("offset_end") or 0)
    source_offset_start = int(source_base_offset) + raw_offset_start
    source_offset_end = int(source_base_offset) + raw_offset_end
    timestamp = _text(message.get("timestamp"))
    identity_anchor = (
        f"native:{native_id}"
        if native_id
        else f"timestamp:{timestamp}"
        if timestamp
        else f"source_offset:{source_offset_start}"
    )
    event_seed = "|".join(
        [
            source_system,
            session_id,
            canonical_window_id,
            identity_anchor,
            _text(message.get("role")).strip().lower(),
            content_hash,
            _text(message.get("message_index_in_record")),
        ]
    )
    return {
        "record_type": CANONICAL_DIALOGUE_RECORD_TYPE,
        "contract": CANONICAL_DIALOGUE_CAPTURE_CONTRACT,
        "source_system": source_system,
        "session_id": session_id,
        "canonical_window_id": canonical_window_id,
        "native_artifact_format": native_artifact_format,
        "message_id": native_id,
        "event_id": hashlib.sha256(event_seed.encode("utf-8")).hexdigest()[:24],
        "role": _text(message.get("role")).strip().lower(),
        "content": content,
        "timestamp": timestamp,
        "verbatim_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "origin_source_ref": {
            "source_path": str(raw_path),
            "byte_offsets": {
                "start": raw_offset_start,
                "end": raw_offset_end,
            },
            "native_source_path": native_source_path,
            "native_source_byte_offsets": {
                "start": source_offset_start,
                "end": source_offset_end,
            },
            "source_base_offset": int(source_base_offset),
            "generation": int(generation),
            "predecessor": predecessor,
            "native_type": _text(message.get("native_type")),
            "native_id": native_id,
            "message_index_in_record": int(message.get("message_index_in_record") or 0),
            "line_hash": _text(message.get("line_hash")),
            "content_hash": content_hash,
        },
    }


def _attach_sidecar_anchor(entry: dict[str, Any], *, dialogue_path: Path, offset_start: int, offset_end: int) -> dict[str, Any]:
    anchored = dict(entry)
    source_refs = {
        "source_system": str(entry.get("source_system") or ""),
        "source_path": str(dialogue_path),
        "byte_offsets": {
            "start": int(offset_start),
            "end": int(offset_end),
        },
        "source_role": str(entry.get("role") or ""),
        "source_author": str(entry.get("role") or ""),
        "session_id": str(entry.get("session_id") or ""),
        "canonical_window_id": str(entry.get("canonical_window_id") or ""),
        "message_id": str(entry.get("message_id") or ""),
        "event_id": str(entry.get("event_id") or ""),
        "native_artifact_format": "canonical_dialogue_jsonl",
        "main_river_storage": "canonical_dialogue",
        "record_type": CANONICAL_DIALOGUE_RECORD_TYPE,
    }
    anchored["source_ref"] = _source_ref_text(dialogue_path, offset_start, offset_end)
    anchored["source_refs"] = source_refs
    return anchored


def _serialize_anchored_entry(entry: dict[str, Any], *, dialogue_path: Path, offset_start: int) -> tuple[dict[str, Any], bytes]:
    current_end = int(offset_start)
    encoded = b""
    anchored: dict[str, Any] = dict(entry)
    for _ in range(6):
        anchored = _attach_sidecar_anchor(
            entry,
            dialogue_path=dialogue_path,
            offset_start=offset_start,
            offset_end=current_end,
        )
        encoded = (json.dumps(anchored, ensure_ascii=False) + "\n").encode("utf-8")
        next_end = int(offset_start) + len(encoded)
        if next_end == current_end:
            return anchored, encoded
        current_end = next_end
    anchored = _attach_sidecar_anchor(
        entry,
        dialogue_path=dialogue_path,
        offset_start=offset_start,
        offset_end=current_end,
    )
    encoded = (json.dumps(anchored, ensure_ascii=False) + "\n").encode("utf-8")
    return anchored, encoded


def materialize_canonical_dialogue(
    raw_path: str | Path,
    *,
    source_system: str,
    session_id: str = "",
    canonical_window_id: str = "",
    native_artifact_format: str = "",
    reset: bool = False,
    raw_order: int = 1,
    native_source_path: str | Path = "",
    source_base_offset: int = 0,
    generation: int = 0,
    predecessor: str = "",
) -> dict[str, Any]:
    raw_file = Path(raw_path).expanduser()
    dialogue_path = canonical_dialogue_sidecar_path(raw_file)
    manifest_path = forensic_runtime_manifest_path(raw_file)

    if not raw_file.exists():
        return {
            "ok": False,
            "error": "raw_path_missing",
            "raw_path": str(raw_file),
            "canonical_dialogue_path": str(dialogue_path),
            "forensic_runtime_manifest_path": str(manifest_path),
        }

    manifest = {} if reset else _load_manifest(manifest_path)
    manifest_valid = (
        bool(manifest)
        and "source_offset_processed" in manifest
        and "source_line_count_processed" in manifest
        and int(manifest.get("source_base_offset", 0) or 0) == int(source_base_offset or 0)
        and int(manifest.get("generation", 0) or 0) == int(generation or 0)
    )
    processed_offset = int(
        manifest.get("raw_offset_processed")
        if manifest.get("raw_offset_processed") is not None
        else manifest.get("source_offset_processed") or 0
    )
    processed_lines = int(manifest.get("source_line_count_processed") or 0)
    if reset or not dialogue_path.exists() or not manifest_valid or raw_file.stat().st_size < processed_offset:
        processed_offset = 0
        processed_lines = 0
        manifest = {}
        for path in (dialogue_path, manifest_path):
            try:
                if path.exists():
                    path.unlink()
            except OSError:
                pass

    parsed = _stream_jsonl_canonical_entries(
        raw_file,
        source_system=source_system,
        file_side="raw",
        max_json_line_bytes=_canonical_index_max_json_line_bytes(),
        start_offset=processed_offset,
        start_line_no=processed_lines,
    )

    kept = 0
    excluded_counts: dict[str, int] = {}
    dialogue_path.parent.mkdir(parents=True, exist_ok=True)
    with dialogue_path.open("ab") as handle:
        for message in parsed.get("messages", []):
            if not isinstance(message, dict):
                continue
            reason = _filter_reason(message)
            if reason:
                excluded_counts[reason] = int(excluded_counts.get(reason, 0) or 0) + 1
                continue
            entry = _entry_for_message(
                message,
                source_system=source_system,
                session_id=session_id,
                canonical_window_id=canonical_window_id,
                raw_path=raw_file,
                native_artifact_format=native_artifact_format,
                native_source_path=str(Path(native_source_path).expanduser()) if native_source_path else str(raw_file),
                source_base_offset=int(source_base_offset or 0),
                generation=int(generation or 0),
                predecessor=str(predecessor or ""),
            )
            offset_start = handle.tell()
            _anchored_entry, encoded = _serialize_anchored_entry(
                entry,
                dialogue_path=dialogue_path,
                offset_start=offset_start,
            )
            handle.write(encoded)
            kept += 1

    existing_counts = manifest.get("excluded_counts") if isinstance(manifest.get("excluded_counts"), dict) else {}
    merged_excluded = {str(key): int(value or 0) for key, value in existing_counts.items()}
    for key, value in excluded_counts.items():
        merged_excluded[key] = int(merged_excluded.get(key, 0) or 0) + int(value or 0)

    updated_manifest = {
        "ok": True,
        "contract": FORENSIC_RUNTIME_MANIFEST_CONTRACT,
        "canonical_dialogue_contract": CANONICAL_DIALOGUE_CAPTURE_CONTRACT,
        "main_river_record_type": CANONICAL_DIALOGUE_RECORD_TYPE,
        "semantic_filter_version": SEMANTIC_FILTER_VERSION,
        "source_system": source_system,
        "session_id": session_id,
        "canonical_window_id": canonical_window_id,
        "native_artifact_format": native_artifact_format,
        "raw_path": str(raw_file),
        "native_source_path": str(Path(native_source_path).expanduser()) if native_source_path else str(raw_file),
        "source_base_offset": int(source_base_offset or 0),
        "source_offset_processed": int(source_base_offset or 0) + int(parsed.get("size_bytes") or raw_file.stat().st_size),
        "generation": int(generation or 0),
        "predecessor": str(predecessor or ""),
        "canonical_dialogue_path": str(dialogue_path),
        "cold_layer_classification": "forensic_runtime",
        "main_river_classification": "canonical_dialogue",
        "origin_policy": "canonical_dialogue_is_main_river_forensic_runtime_is_cold_layer",
        "raw_offset_processed": int(parsed.get("size_bytes") or raw_file.stat().st_size),
        "source_line_count_processed": int(parsed.get("line_count") or 0),
        "dialogue_message_count": int(manifest.get("dialogue_message_count") or 0) + kept,
        "parsed_message_count": int(manifest.get("parsed_message_count") or 0) + len(parsed.get("messages", [])),
        "excluded_total": int(manifest.get("excluded_total") or 0) + sum(excluded_counts.values()),
        "excluded_counts": merged_excluded,
        "bad_json_line_count": int(manifest.get("bad_json_line_count") or 0) + int(parsed.get("bad_json_line_count") or 0),
        "oversized_line_count": int(manifest.get("oversized_line_count") or 0) + int(parsed.get("oversized_line_count") or 0),
        "raw_order": int(raw_order or 1),
        "materialized_at": _now(),
        "reset_applied": bool(reset),
    }
    _atomic_write_json(manifest_path, updated_manifest)
    return updated_manifest


def build_canonical_dialogue_migration_report(
    raw_path: str | Path,
    *,
    source_system: str,
    session_id: str = "",
    canonical_window_id: str = "",
    native_artifact_format: str = "",
    reset: bool = False,
    raw_order: int = 1,
) -> dict[str, Any]:
    raw_file = Path(raw_path).expanduser()
    before_size_bytes = raw_file.stat().st_size if raw_file.exists() else 0
    materialized = materialize_canonical_dialogue(
        raw_file,
        source_system=source_system,
        session_id=session_id,
        canonical_window_id=canonical_window_id,
        native_artifact_format=native_artifact_format,
        reset=reset,
        raw_order=raw_order,
    )
    if not materialized.get("ok"):
        return {
            "ok": False,
            "contract": CANONICAL_DIALOGUE_MIGRATION_REPORT_CONTRACT,
            "session_status": "migration_failed",
            "source_system": source_system,
            "session_id": session_id,
            "canonical_window_id": canonical_window_id,
            "native_artifact_format": native_artifact_format,
            "raw_path": str(raw_file),
            "canonical_dialogue_path": str(canonical_dialogue_sidecar_path(raw_file)),
            "error": materialized.get("error") or "materialize_failed",
            "needs_reanchor": [
                {
                    "raw_path": str(raw_file),
                    "reason": materialized.get("error") or "materialize_failed",
                    "status": "needs_reanchor",
                }
            ],
        }

    dialogue_path = canonical_dialogue_sidecar_path(raw_file)
    manifest_path = forensic_runtime_manifest_path(raw_file)
    after_size_bytes = dialogue_path.stat().st_size if dialogue_path.exists() else 0
    entries = _iter_sidecar_entries(dialogue_path)
    ref_map: list[dict[str, Any]] = []
    needs_reanchor: list[dict[str, Any]] = []
    message_id_ready = 0
    event_id_ready = 0
    verbatim_sha_ready = 0

    for item in entries:
        origin_ref = item.get("origin_source_ref") if isinstance(item.get("origin_source_ref"), dict) else {}
        source_refs = item.get("source_refs") if isinstance(item.get("source_refs"), dict) else {}
        old_start = int((origin_ref.get("byte_offsets") or {}).get("start") or 0)
        old_end = int((origin_ref.get("byte_offsets") or {}).get("end") or 0)
        new_start = int((source_refs.get("byte_offsets") or {}).get("start") or item.get("_sidecar_offset_start") or 0)
        new_end = int((source_refs.get("byte_offsets") or {}).get("end") or item.get("_sidecar_offset_end") or 0)
        old_source_ref = _source_ref_text(origin_ref.get("source_path") or raw_file, old_start, old_end)
        new_source_ref = str(item.get("source_ref") or _source_ref_text(dialogue_path, new_start, new_end))
        line_bytes = _read_exact_bytes(dialogue_path, new_start, new_end)
        line_sha = hashlib.sha256(line_bytes).hexdigest() if line_bytes else ""
        has_message_id = bool(str(item.get("message_id") or "").strip())
        has_event_id = bool(str(item.get("event_id") or "").strip())
        has_verbatim_sha = bool(str(item.get("verbatim_sha256") or "").strip())
        if has_message_id:
            message_id_ready += 1
        if has_event_id:
            event_id_ready += 1
        if has_verbatim_sha:
            verbatim_sha_ready += 1
        status = "ready"
        reason = ""
        if not line_bytes:
            status = "needs_reanchor"
            reason = "canonical_sidecar_source_ref_unreadable"
        elif not (has_message_id or has_event_id):
            status = "needs_reanchor"
            reason = "missing_message_and_event_id"
        elif not has_verbatim_sha:
            status = "needs_reanchor"
            reason = "missing_verbatim_sha256"
        mapping = {
            "message_id": str(item.get("message_id") or ""),
            "event_id": str(item.get("event_id") or ""),
            "role": str(item.get("role") or ""),
            "timestamp": str(item.get("timestamp") or ""),
            "old_source_ref": old_source_ref,
            "new_source_ref": new_source_ref,
            "verbatim_sha256": str(item.get("verbatim_sha256") or ""),
            "canonical_line_sha256": line_sha,
            "status": status,
        }
        ref_map.append(mapping)
        if status != "ready":
            needs_reanchor.append({**mapping, "reason": reason})

    parsed_message_count = int(materialized.get("parsed_message_count") or 0)
    dialogue_message_count = int(materialized.get("dialogue_message_count") or 0)
    excluded_total = int(materialized.get("excluded_total") or 0)
    retained_dialogue_content_bytes = sum(len(str(item.get("content") or "").encode("utf-8")) for item in entries)
    retained_message_ratio = (dialogue_message_count / parsed_message_count) if parsed_message_count else 0.0
    retained_bytes_ratio = (retained_dialogue_content_bytes / before_size_bytes) if before_size_bytes else 0.0
    canonical_dialogue_storage_ratio = (after_size_bytes / before_size_bytes) if before_size_bytes else 0.0
    return {
        "ok": True,
        "contract": CANONICAL_DIALOGUE_MIGRATION_REPORT_CONTRACT,
        "session_status": "materialized_for_reanchor" if not needs_reanchor else "materialized_with_needs_reanchor",
        "source_system": source_system,
        "session_id": session_id,
        "canonical_window_id": canonical_window_id,
        "native_artifact_format": native_artifact_format,
        "raw_path": str(raw_file),
        "canonical_dialogue_path": str(dialogue_path),
        "forensic_runtime_manifest_path": str(manifest_path),
        "before_after": {
            "raw_size_bytes": before_size_bytes,
            "canonical_dialogue_size_bytes": after_size_bytes,
            "retained_dialogue_content_bytes": retained_dialogue_content_bytes,
            "parsed_message_count": parsed_message_count,
            "dialogue_message_count": dialogue_message_count,
            "excluded_total": excluded_total,
            "retained_message_ratio": retained_message_ratio,
            "retained_bytes_ratio": retained_bytes_ratio,
            "canonical_dialogue_storage_ratio": canonical_dialogue_storage_ratio,
        },
        "reanchor_readiness": {
            "message_id_ready": message_id_ready,
            "event_id_ready": event_id_ready,
            "verbatim_sha_ready": verbatim_sha_ready,
            "fallback_only": max(0, dialogue_message_count - message_id_ready),
        },
        "old_ref_to_new_ref_map": ref_map,
        "needs_reanchor": needs_reanchor,
    }


__all__ = [
    "CANONICAL_DIALOGUE_CAPTURE_CONTRACT",
    "CANONICAL_DIALOGUE_MIGRATION_REPORT_CONTRACT",
    "CANONICAL_DIALOGUE_RECORD_TYPE",
    "FORENSIC_RUNTIME_MANIFEST_CONTRACT",
    "SEMANTIC_FILTER_VERSION",
    "build_canonical_dialogue_migration_report",
    "canonical_dialogue_sidecar_path",
    "forensic_runtime_manifest_path",
    "materialize_canonical_dialogue",
]
