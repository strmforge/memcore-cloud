#!/usr/bin/env python3
"""Bounded, read-only recoverability evidence for retained raw records."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Callable
try:
    from source_system_runtime_declarations import source_system_raw_validation_kind
except ImportError:  # pragma: no cover
    from src.source_system_runtime_declarations import source_system_raw_validation_kind


DEFAULT_LOST_SOURCE_RECOVERABILITY_RECORD_LIMIT = 80
DEFAULT_LOST_SOURCE_RECOVERABILITY_FILE_BYTES = 32 * 1024 * 1024
DEFAULT_LOST_SOURCE_RECOVERABILITY_ROUND_BYTES = 64 * 1024 * 1024
DEFAULT_RECOVERABILITY_CACHE_ENTRY_LIMIT = 256
RECOVERABILITY_CACHE: dict[tuple[Any, ...], dict[str, Any]] = {}
RECOVERABILITY_CLASS_COMPLETE = "conversation_complete"
RECOVERABILITY_CLASS_ONE_SIDED = "conversation_one_sided"
RECOVERABILITY_CLASS_NON_CONVERSATION = "non_conversation_structurally_valid"
RECOVERABILITY_CLASS_UNRECOVERABLE = "structurally_unrecoverable"
RECOVERABILITY_CLASS_NOT_MEASURED = "not_measured"
CLAUDE_DESKTOP_AUTHORIZED_LOCAL_STORE = "claude_desktop_authorized_local_store_jsonl"


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _count(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except Exception:
        return 0


def lost_source_triage(summary: dict[str, Any]) -> tuple[int, int, int, int]:
    """Return total/recoverable/unrecoverable/not-measured, failing closed."""
    total = _count(summary.get("lost_source_count"))
    keys = {
        "lost_source_recoverable_count",
        "lost_source_unrecoverable_count",
        "lost_source_not_measured_count",
    }
    if not keys.issubset(summary):
        return total, 0, total, 0
    recoverable = _count(summary.get("lost_source_recoverable_count"))
    unrecoverable = _count(summary.get("lost_source_unrecoverable_count"))
    not_measured = _count(summary.get("lost_source_not_measured_count"))
    triaged_total = recoverable + unrecoverable + not_measured
    if triaged_total != total:
        fallback_total = max(total, triaged_total)
        return fallback_total, 0, fallback_total, 0
    return total, recoverable, unrecoverable, not_measured


def nullable_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None


def nullable_bool(value: Any) -> int | None:
    if value is None:
        return None
    return 1 if bool(value) else 0


def preserve_measured_recoverability(
    item: dict[str, Any],
    previous_payload_json: str,
) -> dict[str, Any]:
    if item.get("recoverable_from_raw") is not None or not previous_payload_json:
        return item
    try:
        previous = json.loads(previous_payload_json)
    except Exception:
        return item
    if not isinstance(previous, dict):
        return item
    previous_evidence = previous.get("recoverability_evidence")
    previous_evidence = previous_evidence if isinstance(previous_evidence, dict) else {}
    previous_value = previous.get("recoverable_from_raw")
    if previous_value not in {True, False}:
        return item
    previous_identity = previous_evidence.get("file_identity")
    previous_identity = previous_identity if isinstance(previous_identity, dict) else {}
    raw_scan = item.get("raw_scan") if isinstance(item.get("raw_scan"), dict) else {}
    current_identity = raw_scan.get("file_identity")
    current_identity = current_identity if isinstance(current_identity, dict) else {}
    required = {"device", "inode", "size_bytes", "mtime_ns"}
    if not required.issubset(previous_identity) or not required.issubset(current_identity):
        return item
    if any(int(previous_identity[key]) != int(current_identity[key]) for key in required):
        return item

    previous_class = _safe_str(previous_evidence.get("recoverability_class"))
    if previous_value is False and not previous_class:
        # Legacy negative evidence used conversation shape as a universal ruler.
        # Re-measure it under the artifact-aware contract instead of preserving it.
        return item
    merged = dict(item)
    merged["recoverable_from_raw"] = previous_value
    merged["recoverability_class"] = previous_class or RECOVERABILITY_CLASS_COMPLETE
    merged["raw_scan"] = {
        **raw_scan,
        "has_user_and_assistant": merged["recoverability_class"] == RECOVERABILITY_CLASS_COMPLETE,
    }
    merged["recoverability_status"] = recoverability_status(previous_value, merged["recoverability_class"])
    merged["recoverability_evidence"] = {
        **previous_evidence,
        "method": "canonical_record_identity_cache",
        "bytes_read": 0,
    }
    return merged


def text_from_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
                continue
            if not isinstance(item, dict):
                continue
            for key in ("text", "content", "value", "markdown"):
                value = item.get(key)
                if isinstance(value, str):
                    parts.append(value)
                    break
                if isinstance(value, list):
                    nested = text_from_content(value)
                    if nested:
                        parts.append(nested)
                        break
        return "\n".join(part for part in parts if part)
    if isinstance(content, dict):
        for key in ("text", "content", "value", "markdown"):
            value = content.get(key)
            if isinstance(value, str):
                return value
            if isinstance(value, list):
                return text_from_content(value)
    return ""


def _role_and_content_from_record(source_system: str, record: dict[str, Any]) -> tuple[str, bool]:
    validation_kind = source_system_raw_validation_kind(source_system)
    if validation_kind == "response_item_payload_message":
        payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
        role = _safe_str(payload.get("role") or record.get("role"))
        content = payload.get("content") if "content" in payload else record.get("content")
        nested = payload.get("message") if isinstance(payload.get("message"), dict) else {}
        if not role and nested:
            role = _safe_str(nested.get("role"))
        if content is None and nested:
            content = nested.get("content")
        return role, bool(text_from_content(content).strip())

    if validation_kind == "message_envelope_content_blocks":
        rec_type = _safe_str(record.get("type"))
        message = record.get("message") if isinstance(record.get("message"), dict) else {}
        role = _safe_str(message.get("role") or rec_type)
        content = message.get("content")
        if role == "user" and isinstance(content, list) and content and all(
            isinstance(item, dict) and _safe_str(item.get("type")) == "tool_result"
            for item in content
        ):
            role = "tool"
        return role, bool(text_from_content(content).strip())

    message = record.get("message") if isinstance(record.get("message"), dict) else {}
    payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
    role = _safe_str(record.get("role") or message.get("role") or payload.get("role"))
    content = record.get("content")
    if content is None:
        content = message.get("content")
    if content is None:
        content = payload.get("content")
    return role, bool(text_from_content(content).strip())


def role_content_pairs_from_record(source_system: str, record: dict[str, Any]) -> list[tuple[str, bool]]:
    if source_system_raw_validation_kind(source_system) == "message_snapshot_batch":
        data = record.get("data") if isinstance(record.get("data"), dict) else {}
        messages = data.get("messagesSnapshot")
        if not isinstance(messages, list):
            messages = record.get("messages")
        pairs: list[tuple[str, bool]] = []
        if isinstance(messages, list):
            for message in messages:
                if not isinstance(message, dict):
                    continue
                role = _safe_str(message.get("role") or message.get("type"))
                if role == "custom":
                    continue
                content_present = bool(text_from_content(message.get("content")).strip())
                if role and content_present:
                    pairs.append((role, content_present))
            if pairs:
                return pairs
        final_prompt = data.get("finalPromptText")
        if isinstance(final_prompt, str) and final_prompt.strip():
            return [("user", True)]
    return [_role_and_content_from_record(source_system, record)]


def _recoverability_class_from_scan(
    raw_scan: dict[str, Any],
    *,
    source_system: str,
    artifact_type: str,
) -> str:
    if not raw_scan.get("exists"):
        return RECOVERABILITY_CLASS_NOT_MEASURED if raw_scan.get("targeted_structural_only") else RECOVERABILITY_CLASS_UNRECOVERABLE
    if raw_scan.get("fast_stat_only"):
        return RECOVERABILITY_CLASS_NOT_MEASURED
    if raw_scan.get("health_status") in {"read_error", "corrupt_jsonl"}:
        return RECOVERABILITY_CLASS_NOT_MEASURED
    if raw_scan.get("bad_json_line_count"):
        return RECOVERABILITY_CLASS_NOT_MEASURED
    user_turns = nullable_int(raw_scan.get("user_turn_count"))
    assistant_turns = nullable_int(raw_scan.get("assistant_turn_count"))
    if raw_scan.get("has_user_and_assistant") is True or (
        (user_turns or 0) > 0 and (assistant_turns or 0) > 0
    ):
        return RECOVERABILITY_CLASS_COMPLETE
    if (user_turns or 0) > 0 or (assistant_turns or 0) > 0:
        return RECOVERABILITY_CLASS_ONE_SIDED
    valid_records = nullable_int(raw_scan.get("valid_json_line_count"))
    if (
        _safe_str(source_system) == "claude_desktop"
        and _safe_str(artifact_type) == CLAUDE_DESKTOP_AUTHORIZED_LOCAL_STORE
        and (valid_records or 0) > 0
    ):
        return RECOVERABILITY_CLASS_NON_CONVERSATION
    if raw_scan.get("has_user_and_assistant") is False:
        return RECOVERABILITY_CLASS_UNRECOVERABLE
    return RECOVERABILITY_CLASS_NOT_MEASURED


def _recoverability_value_from_class(recoverability_class: str) -> bool | None:
    if recoverability_class in {
        RECOVERABILITY_CLASS_COMPLETE,
        RECOVERABILITY_CLASS_ONE_SIDED,
        RECOVERABILITY_CLASS_NON_CONVERSATION,
    }:
        return True
    if recoverability_class == RECOVERABILITY_CLASS_UNRECOVERABLE:
        return False
    return None


def _recoverability_value_from_scan(
    raw_scan: dict[str, Any],
    *,
    source_system: str = "",
    artifact_type: str = "",
) -> bool | None:
    return _recoverability_value_from_class(_recoverability_class_from_scan(
        raw_scan,
        source_system=source_system,
        artifact_type=artifact_type,
    ))


def recoverability_status(value: bool | None, recoverability_class: str = "") -> str:
    if recoverability_class == RECOVERABILITY_CLASS_ONE_SIDED:
        return "measured_recoverable_one_sided"
    if recoverability_class == RECOVERABILITY_CLASS_NON_CONVERSATION:
        return "measured_recoverable_non_conversation"
    if value is True:
        return "measured_recoverable"
    if value is False:
        return "measured_unrecoverable"
    return "not_measured"


def _bounded_jsonl_recoverability_scan(
    path: str | Path,
    *,
    source_system: str,
    artifact_type: str = "",
    max_bytes: int,
) -> dict[str, Any]:
    raw_path = Path(path).expanduser()
    try:
        stat_before = raw_path.stat()
    except OSError:
        return {
            "exists": False,
            "has_user_and_assistant": None,
            "health_status": "missing_during_targeted_scan",
            "bytes_read": 0,
            "targeted_structural_only": True,
        }
    identity_before = {
        "device": int(stat_before.st_dev),
        "inode": int(stat_before.st_ino),
        "size_bytes": int(stat_before.st_size),
        "mtime_ns": int(getattr(stat_before, "st_mtime_ns", int(stat_before.st_mtime * 1_000_000_000))),
    }
    if stat_before.st_size > max(0, int(max_bytes)):
        return {
            "exists": True,
            "file_identity": identity_before,
            "has_user_and_assistant": None,
            "health_status": "byte_limit_exceeded",
            "bytes_read": 0,
            "targeted_structural_only": True,
        }

    user_seen = False
    assistant_seen = False
    bad_json_line_count = 0
    valid_json_line_count = 0
    bytes_read = 0
    try:
        with raw_path.open("rb") as handle:
            while bytes_read < stat_before.st_size:
                raw_line = handle.readline(stat_before.st_size - bytes_read)
                if not raw_line:
                    break
                bytes_read += len(raw_line)
                if not raw_line.strip():
                    continue
                try:
                    record = json.loads(raw_line.decode("utf-8"))
                except Exception:
                    bad_json_line_count += 1
                    continue
                if not isinstance(record, dict):
                    continue
                valid_json_line_count += 1
                for role, content_present in role_content_pairs_from_record(source_system, record):
                    if not content_present:
                        continue
                    if role in {"user", "human"}:
                        user_seen = True
                    elif role in {"assistant", "ai", "model"}:
                        assistant_seen = True
                if user_seen and assistant_seen:
                    break
    except OSError:
        return {
            "exists": True,
            "file_identity": identity_before,
            "has_user_and_assistant": None,
            "health_status": "read_error",
            "bytes_read": bytes_read,
            "targeted_structural_only": True,
        }

    try:
        stat_after = raw_path.stat()
        identity_after = {
            "device": int(stat_after.st_dev),
            "inode": int(stat_after.st_ino),
            "size_bytes": int(stat_after.st_size),
            "mtime_ns": int(getattr(stat_after, "st_mtime_ns", int(stat_after.st_mtime * 1_000_000_000))),
        }
    except OSError:
        identity_after = {}
    scan = {
        "exists": True,
        "file_identity": identity_before,
        "has_user_and_assistant": bool(user_seen and assistant_seen),
        "bad_json_line_count": bad_json_line_count,
        "valid_json_line_count": valid_json_line_count,
        "user_turn_count": int(user_seen),
        "assistant_turn_count": int(assistant_seen),
        "bytes_read": bytes_read,
        "targeted_structural_only": True,
    }
    if identity_after != identity_before:
        recoverability_class = RECOVERABILITY_CLASS_NOT_MEASURED
        health_status = "identity_changed_during_scan"
    elif bad_json_line_count:
        recoverability_class = RECOVERABILITY_CLASS_NOT_MEASURED
        health_status = "targeted_structure_incomplete_due_to_bad_json"
    elif user_seen and assistant_seen:
        recoverability_class = RECOVERABILITY_CLASS_COMPLETE
        health_status = "targeted_structure_recoverable"
    elif bytes_read != stat_before.st_size:
        recoverability_class = RECOVERABILITY_CLASS_NOT_MEASURED
        health_status = "targeted_structure_incomplete"
    else:
        recoverability_class = _recoverability_class_from_scan(
            scan,
            source_system=source_system,
            artifact_type=artifact_type,
        )
        health_status = {
            RECOVERABILITY_CLASS_COMPLETE: "targeted_structure_recoverable",
            RECOVERABILITY_CLASS_ONE_SIDED: "targeted_structure_one_sided",
            RECOVERABILITY_CLASS_NON_CONVERSATION: "targeted_structure_non_conversation",
            RECOVERABILITY_CLASS_UNRECOVERABLE: "targeted_structure_unrecoverable",
        }.get(recoverability_class, "targeted_structure_incomplete")
    scan["recoverability_class"] = recoverability_class
    scan["recoverable_from_raw"] = _recoverability_value_from_class(recoverability_class)
    scan["health_status"] = health_status
    return scan


def _evidence(
    raw_scan: dict[str, Any],
    *,
    method: str,
    source_system: str = "",
    artifact_type: str = "",
    reason: str = "",
    bytes_read: int = 0,
) -> dict[str, Any]:
    recoverability_class = _safe_str(raw_scan.get("recoverability_class")) or _recoverability_class_from_scan(
        raw_scan,
        source_system=source_system,
        artifact_type=artifact_type,
    )
    value = _recoverability_value_from_class(recoverability_class)
    return {
        "status": recoverability_status(value, recoverability_class),
        "recoverable_from_raw": value,
        "recoverability_class": recoverability_class,
        "method": method,
        "reason": reason,
        "file_identity": dict(raw_scan.get("file_identity") or {}),
        "bytes_read": max(0, int(bytes_read or 0)),
        "semantic_completeness_claimed": False,
    }


def _apply(item: dict[str, Any], evidence: dict[str, Any]) -> None:
    value = evidence.get("recoverable_from_raw")
    value = value if value in {True, False} else None
    recoverability_class = _safe_str(evidence.get("recoverability_class")) or RECOVERABILITY_CLASS_NOT_MEASURED
    item["recoverable_from_raw"] = value
    item["recoverability_class"] = recoverability_class
    item["recoverability_status"] = recoverability_status(value, recoverability_class)
    item["recoverability_evidence"] = dict(evidence)
    raw_scan = item.get("raw_scan") if isinstance(item.get("raw_scan"), dict) else {}
    if raw_scan:
        if recoverability_class == RECOVERABILITY_CLASS_COMPLETE:
            raw_scan["has_user_and_assistant"] = True
        elif recoverability_class in {
            RECOVERABILITY_CLASS_ONE_SIDED,
            RECOVERABILITY_CLASS_NON_CONVERSATION,
            RECOVERABILITY_CLASS_UNRECOVERABLE,
        }:
            raw_scan["has_user_and_assistant"] = False


def _cache_key(item: dict[str, Any]) -> tuple[Any, ...] | None:
    raw_scan = item.get("raw_scan") if isinstance(item.get("raw_scan"), dict) else {}
    identity = raw_scan.get("file_identity") if isinstance(raw_scan.get("file_identity"), dict) else {}
    required = ("device", "inode", "size_bytes", "mtime_ns")
    if any(identity.get(key) is None for key in required):
        return None
    return (
        _safe_str(item.get("source_system")),
        _safe_str(item.get("raw_path")),
        *(int(identity[key]) for key in required),
    )


def _cache_put(
    cache: dict[tuple[Any, ...], dict[str, Any]],
    key: tuple[Any, ...] | None,
    evidence: dict[str, Any],
    *,
    entry_limit: int,
) -> None:
    if key is None or entry_limit <= 0:
        return
    cache.pop(key, None)
    while len(cache) >= entry_limit:
        cache.pop(next(iter(cache)))
    cache[key] = dict(evidence)


def _persisted_evidence_map(
    items: list[dict[str, Any]],
    *,
    record_id_fn: Callable[[dict[str, Any]], str],
    db_path: Path,
) -> tuple[dict[str, dict[str, Any]], str]:
    if not db_path.exists():
        return {}, "records_db_missing"
    item_by_record_id = {
        record_id_fn(item): item
        for item in items
        if _cache_key(item) is not None
    }
    if not item_by_record_id:
        return {}, "no_identity_eligible_candidates"
    try:
        conn = sqlite3.connect(
            f"{db_path.resolve().as_uri()}?mode=ro",
            uri=True,
            timeout=0.25,
        )
    except sqlite3.Error as exc:
        return {}, f"sqlite_open_failed:{type(exc).__name__}"
    try:
        record_ids = list(item_by_record_id)
        placeholders = ",".join("?" for _ in record_ids)
        payloads: list[tuple[str, str]] = []
        for table in ("records", "canonical_sessions"):
            try:
                rows = conn.execute(
                    f"select record_id, payload_json from {table} where record_id in ({placeholders})",
                    record_ids,
                ).fetchall()
            except sqlite3.Error as exc:
                if "no such table" in str(exc).lower():
                    continue
                return {}, f"sqlite_read_failed:{type(exc).__name__}"
            payloads.extend(
                (str(row[0]), str(row[1]))
                for row in rows
                if row and row[0] and row[1]
            )
    finally:
        conn.close()

    evidence_by_record_id: dict[str, dict[str, Any]] = {}
    for record_id, payload_json in payloads:
        item = item_by_record_id.get(record_id)
        if item is None or record_id in evidence_by_record_id:
            continue
        try:
            payload = json.loads(payload_json)
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        if isinstance(payload.get("guardian_record"), dict):
            payload = payload["guardian_record"]
        evidence = payload.get("recoverability_evidence")
        evidence = evidence if isinstance(evidence, dict) else {}
        value = payload.get("recoverable_from_raw")
        persisted_class = _safe_str(evidence.get("recoverability_class"))
        if value is False and not persisted_class:
            continue
        identity = evidence.get("file_identity") if isinstance(evidence.get("file_identity"), dict) else {}
        required = ("device", "inode", "size_bytes", "mtime_ns")
        if value not in {True, False} or any(identity.get(key) is None for key in required):
            continue
        persisted_key = (
            _safe_str(payload.get("source_system")),
            _safe_str(payload.get("raw_path")),
            *(int(identity[key]) for key in required),
        )
        if persisted_key != _cache_key(item):
            continue
        evidence_by_record_id[record_id] = {
            **evidence,
            "status": recoverability_status(value, persisted_class),
            "recoverable_from_raw": value,
            "recoverability_class": persisted_class or (
                RECOVERABILITY_CLASS_COMPLETE if value else RECOVERABILITY_CLASS_UNRECOVERABLE
            ),
            "method": "canonical_record_identity_cache",
            "bytes_read": 0,
        }
    return evidence_by_record_id, "available"


def _missing_source_status(item: dict[str, Any], authorized_desktop_formats: set[str]) -> str:
    value = item.get("recoverable_from_raw")
    recoverability_class = _safe_str(item.get("recoverability_class"))
    authorized_desktop = (
        item.get("source_system") == "claude_desktop"
        and item.get("artifact_type") in authorized_desktop_formats
    )
    if authorized_desktop:
        if recoverability_class == RECOVERABILITY_CLASS_ONE_SIDED:
            return "authorized_raw_one_sided_source_missing"
        if recoverability_class == RECOVERABILITY_CLASS_NON_CONVERSATION:
            return "authorized_raw_non_conversation_source_missing"
        if value is True:
            return "authorized_raw_recoverable_source_missing"
        if value is False:
            return "authorized_raw_unrecoverable_source_missing"
        return "authorized_raw_source_recoverability_unmeasured"
    if value is True:
        return "source_missing_recoverable_from_raw"
    if value is False:
        return "source_missing_unrecoverable_from_raw"
    return "source_missing_recoverability_unmeasured"


def _apply_missing_source_status(item: dict[str, Any], authorized_desktop_formats: set[str]) -> None:
    item["guard_status"] = _missing_source_status(item, authorized_desktop_formats)
    if item.get("recoverable_from_raw") is True:
        item["raw_current"] = True


def prepare_recoverability_evidence(
    records: list[dict[str, Any]],
    *,
    scan_mode: str,
    authorized_desktop_formats: set[str],
    record_id_fn: Callable[[dict[str, Any]], str],
    records_db: str | Path,
    cache: dict[tuple[Any, ...], dict[str, Any]] = RECOVERABILITY_CACHE,
    candidate_limit: int = DEFAULT_LOST_SOURCE_RECOVERABILITY_RECORD_LIMIT,
    per_file_byte_limit: int = DEFAULT_LOST_SOURCE_RECOVERABILITY_FILE_BYTES,
    round_byte_limit: int = DEFAULT_LOST_SOURCE_RECOVERABILITY_ROUND_BYTES,
    cache_entry_limit: int = DEFAULT_RECOVERABILITY_CACHE_ENTRY_LIMIT,
) -> dict[str, Any]:
    raw_failure_statuses = {
        "raw_missing",
        "raw_corrupt",
        "raw_metadata_incomplete",
        "raw_lagging",
        "raw_catching_up",
        "source_regression_raw_retained",
        "source_divergence_raw_retained",
        "raw_monotonic_probe_incomplete",
    }
    for item in records:
        raw_scan = item.get("raw_scan") if isinstance(item.get("raw_scan"), dict) else {}
        source_scan = item.get("source_scan") if isinstance(item.get("source_scan"), dict) else {}
        method = "fast_stat_only" if scan_mode == "fast" else "full_structural_scan"
        evidence = _evidence(
            raw_scan,
            method=method,
            source_system=_safe_str(item.get("source_system")),
            artifact_type=_safe_str(item.get("artifact_type")),
        )
        if source_scan.get("exists") and evidence.get("recoverability_class") in {
            RECOVERABILITY_CLASS_ONE_SIDED,
            RECOVERABILITY_CLASS_NON_CONVERSATION,
        }:
            evidence = {
                **evidence,
                "status": "measured_unrecoverable",
                "recoverable_from_raw": False,
                "recoverability_class": RECOVERABILITY_CLASS_UNRECOVERABLE,
            }
        _apply(item, evidence)
        if (
            not source_scan.get("exists")
            and raw_scan.get("exists")
            and item.get("guard_status") not in raw_failure_statuses
        ):
            _apply_missing_source_status(item, authorized_desktop_formats)

    candidates = [
        item for item in records
        if isinstance(item.get("source_scan"), dict)
        and isinstance(item.get("raw_scan"), dict)
        and not item["source_scan"].get("exists")
        and item["raw_scan"].get("exists")
        and item.get("recoverable_from_raw") is None
        and item.get("guard_status") not in raw_failure_statuses
    ]
    result = {
        "read_only": True,
        "write_performed": False,
        "candidate_count": len(candidates),
        "candidate_limit": candidate_limit,
        "per_file_byte_limit": per_file_byte_limit,
        "round_byte_limit": round_byte_limit,
        "cache_entry_limit": cache_entry_limit,
        "targeted_scan_count": 0,
        "cache_hit_count": 0,
        "canonical_cache_hit_count": 0,
        "canonical_cache_status": "not_applicable",
        "measured_count": 0,
        "not_measured_count": len(candidates),
        "bytes_read": 0,
        "budget_exhausted_count": 0,
        "one_sided_count": 0,
        "non_conversation_count": 0,
    }
    if scan_mode != "fast" or not candidates:
        if not candidates:
            result["canonical_cache_status"] = "not_needed"
        return result

    eligible = candidates[:max(0, candidate_limit)]
    persisted_evidence, cache_status = _persisted_evidence_map(
        eligible,
        record_id_fn=record_id_fn,
        db_path=Path(records_db).expanduser(),
    )
    result["canonical_cache_status"] = cache_status

    for index, item in enumerate(candidates):
        raw_scan = item["raw_scan"]
        if index >= candidate_limit:
            _apply(item, _evidence(
                raw_scan,
                method="targeted_structural_scan",
                source_system=_safe_str(item.get("source_system")),
                artifact_type=_safe_str(item.get("artifact_type")),
                reason="candidate_limit_exhausted",
            ))
            result["budget_exhausted_count"] += 1
            _apply_missing_source_status(item, authorized_desktop_formats)
            continue

        cache_key = _cache_key(item)
        persisted = persisted_evidence.get(record_id_fn(item))
        if persisted:
            _apply(item, persisted)
            result["canonical_cache_hit_count"] += 1
            result["measured_count"] += 1
            _cache_put(cache, cache_key, persisted, entry_limit=cache_entry_limit)
            _apply_missing_source_status(item, authorized_desktop_formats)
            continue
        cached = cache.get(cache_key) if cache_key is not None else None
        if (
            cached
            and cached.get("recoverable_from_raw") is False
            and not _safe_str(cached.get("recoverability_class"))
        ):
            cached = None
        if cached:
            evidence = {**cached, "method": "in_process_identity_cache", "bytes_read": 0}
            _apply(item, evidence)
            result["cache_hit_count"] += 1
            result["measured_count"] += int(item.get("recoverable_from_raw") is not None)
            _apply_missing_source_status(item, authorized_desktop_formats)
            continue

        size_bytes = int(raw_scan.get("size_bytes", 0) or 0)
        remaining = round_byte_limit - int(result["bytes_read"])
        if size_bytes > per_file_byte_limit:
            _apply(item, _evidence(
                raw_scan,
                method="targeted_structural_scan",
                source_system=_safe_str(item.get("source_system")),
                artifact_type=_safe_str(item.get("artifact_type")),
                reason="per_file_byte_limit_exceeded",
            ))
            result["budget_exhausted_count"] += 1
            _apply_missing_source_status(item, authorized_desktop_formats)
            continue
        if size_bytes > remaining:
            _apply(item, _evidence(
                raw_scan,
                method="targeted_structural_scan",
                source_system=_safe_str(item.get("source_system")),
                artifact_type=_safe_str(item.get("artifact_type")),
                reason="round_byte_limit_exhausted",
            ))
            result["budget_exhausted_count"] += 1
            _apply_missing_source_status(item, authorized_desktop_formats)
            continue

        measured_scan = _bounded_jsonl_recoverability_scan(
            item.get("raw_path", ""),
            source_system=_safe_str(item.get("source_system")),
            artifact_type=_safe_str(item.get("artifact_type")),
            max_bytes=min(per_file_byte_limit, remaining),
        )
        measured_bytes = int(measured_scan.get("bytes_read", 0) or 0)
        evidence = _evidence(
            measured_scan,
            method="targeted_structural_scan",
            source_system=_safe_str(item.get("source_system")),
            artifact_type=_safe_str(item.get("artifact_type")),
            reason="lost_source_bounded_structural_check",
            bytes_read=measured_bytes,
        )
        _apply(item, evidence)
        result["targeted_scan_count"] += 1
        result["bytes_read"] += measured_bytes
        if item.get("recoverable_from_raw") is not None:
            result["measured_count"] += 1
            _cache_put(cache, cache_key, evidence, entry_limit=cache_entry_limit)
        _apply_missing_source_status(item, authorized_desktop_formats)

    result["not_measured_count"] = sum(
        1 for item in candidates if item.get("recoverable_from_raw") is None
    )
    result["one_sided_count"] = sum(
        1 for item in candidates if item.get("recoverability_class") == RECOVERABILITY_CLASS_ONE_SIDED
    )
    result["non_conversation_count"] = sum(
        1 for item in candidates if item.get("recoverability_class") == RECOVERABILITY_CLASS_NON_CONVERSATION
    )
    return result
