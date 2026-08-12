#!/usr/bin/env python3
"""Raw record backfill repair layer under Time Origin.

Tiandao contract: this module owns authorized raw backfill repair actions. It
may mirror source records into raw archives when explicitly invoked, but it is
not the raw origin and does not replace the guardian's read-only diagnostics.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from config_loader import node_id
except ImportError:  # pragma: no cover
    from src.config_loader import node_id
try:
    from src.raw_archive_monotonic import append_jsonl_records, append_source_file
except ImportError:  # pragma: no cover
    from raw_archive_monotonic import append_jsonl_records, append_source_file
try:
    from src.source_system_runtime_declarations import (
        declared_raw_backfill_source_systems,
        source_system_for_raw_backfill_kind,
        source_system_raw_backfill_kind,
    )
except ImportError:  # pragma: no cover
    from source_system_runtime_declarations import (
        declared_raw_backfill_source_systems,
        source_system_for_raw_backfill_kind,
        source_system_raw_backfill_kind,
    )

UTC = timezone.utc
RAW_BACKFILL_CONTRACT = "raw_record_backfill.v1"
RAW_RECORD_BACKFILL_REPAIR_CONTRACT = "tiandao_raw_record_backfill_repair.v1"
HERMES_STATE_DB_RAW_FORMAT = "hermes_state_db_messages_jsonl"
OPENCLAW_NATIVE_RAW_FORMAT = "openclaw_session_jsonl"
HERMES_SOURCE_SYSTEM = source_system_for_raw_backfill_kind("state_db_messages") or "hermes"
OPENCLAW_SOURCE_SYSTEM = source_system_for_raw_backfill_kind("source_artifact_copy") or "openclaw"
# Direct repair retains divergent raw; connector-owned ingestion must opt into generations.
DIRECT_OPENCLAW_BACKFILL_CONTINUE_ON_DIVERGENCE = False


def _guardian_module():
    names = (
        ("src.raw_record_guardian", "raw_record_guardian")
        if __name__.startswith("src.")
        else ("raw_record_guardian", "src.raw_record_guardian")
    )
    last_error: Exception | None = None
    for name in names:
        try:
            return importlib.import_module(name)
        except Exception as exc:  # pragma: no cover - fallback path
            last_error = exc
    if last_error:
        raise last_error
    raise ImportError("raw_record_guardian")


def ts() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def get_raw_record_backfill_contract() -> dict[str, Any]:
    return {
        "ok": True,
        "contract": RAW_RECORD_BACKFILL_REPAIR_CONTRACT,
        "backfill_contract": RAW_BACKFILL_CONTRACT,
        "parent_tiandao_contract": "tiandao_time_river.v1",
        "repair_layer": "raw_record_backfill",
        "source_authority": "raw_record_guardian",
        "not_raw_origin": True,
        "read_only_by_default": True,
        "write_capable": True,
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "authorization_required_for_write": True,
        "divergence_generation_policy": "connector_owned_ingest_only; direct_openclaw_backfill_retains_divergent_raw",
        "authorized_write_scopes": [
            "raw_archive_backfill",
            "raw_archive_meta_sidecar",
        ],
        "forbidden_write_scopes": [
            "source_platform_store",
            "platform_config",
            "memory_recall_summary",
        ],
        "raw_origin_policy": "backfill repairs raw archive continuity but never becomes Time Origin",
    }


def hermes_backfill_recommendation(*, limit: int = 80) -> dict[str, Any]:
    """Fast read-only check for Hermes sessions that still need raw export."""
    guardian = _guardian_module()
    records = guardian._hermes_records(
        limit=max(1, min(int(limit or 80), 200)),
        oversize_bytes=guardian.DEFAULT_JSONL_OVERSIZE_BYTES,
        scan_mode="fast",
    )
    recommended = [
        item for item in records
        if source_system_raw_backfill_kind(str(item.get("source_system") or "")) == "state_db_messages"
        and item.get("backfill_recommended")
    ]
    return {
        "ok": True,
        "source_system": HERMES_SOURCE_SYSTEM,
        "recommended_count": len(recommended),
        "session_ids": [item.get("session_id", "") for item in recommended[:20]],
        "write_performed": False,
        "platform_write_performed": False,
        "memory_write_performed": False,
    }


def _connector_backfill(
    source_system: str,
    module_name: str,
    *,
    limit: int,
    target_raw_paths: set[str] | None = None,
) -> dict[str, Any]:
    try:
        module = importlib.import_module(module_name)
    except Exception as exc:
        return {
            "source_system": source_system,
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    try:
        if target_raw_paths:
            if not all(hasattr(module, name) for name in ("discover_sessions", "archive_session_incremental", "_raw_dest_for_artifact")):
                return {
                    "source_system": source_system,
                    "ok": False,
                    "error": "connector_has_no_targeted_backfill_method",
                }
            artifacts = module.discover_sessions(limit=limit)
            selected = [
                artifact for artifact in artifacts
                if str(module._raw_dest_for_artifact(artifact)) in target_raw_paths
            ]
            items = []
            changed = 0
            for artifact in selected:
                dest, status = module.archive_session_incremental(
                    artifact["source_path"],
                    dry_run=False,
                    artifact=artifact,
                )
                wrote = status.startswith(("archived", "appended", "generation_started", "metadata_updated"))
                changed += int(wrote)
                items.append({
                    "session_id": artifact.get("session_id", ""),
                    "raw_path": str(dest),
                    "status": status,
                    "changed": wrote,
                    "write_performed": wrote,
                    "platform_write_performed": False,
                    "memory_write_performed": wrote,
                })
            result = {
                "ok": True,
                "changed": changed,
                "items": items,
                "write_performed": bool(changed),
                "platform_write_performed": False,
                "memory_write_performed": bool(changed),
                "targeted_backfill": True,
            }
        elif hasattr(module, "catch_up_latest_sessions"):
            result = module.catch_up_latest_sessions(limit=limit)
        elif hasattr(module, "scan_sessions"):
            result = module.scan_sessions(dry_run=False, limit=limit, public=False)
        else:
            return {
                "source_system": source_system,
                "ok": False,
                "error": "connector_has_no_backfill_method",
            }
    except Exception as exc:
        return {
            "source_system": source_system,
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    return {
        "source_system": source_system,
        "ok": bool(result.get("ok", True)),
        "changed": int(result.get("changed", 0) or 0),
        "raw_sync": result.get("raw_sync") or {},
        "result": result,
    }


def _openclaw_backfill(*, limit: int, target_raw_paths: set[str] | None = None) -> dict[str, Any]:
    guardian = _guardian_module()

    changed = 0
    items: list[dict[str, Any]] = []
    for artifact in guardian._openclaw_source_artifacts(limit):
        try:
            src = Path(str(artifact.get("source_path") or "")).expanduser()
            dest = guardian._openclaw_raw_path_for_artifact(artifact)
            if target_raw_paths and str(dest) not in target_raw_paths:
                continue
            try:
                src_stat = src.stat()
            except OSError:
                report = append_source_file(src, dest, continue_on_divergence=DIRECT_OPENCLAW_BACKFILL_CONTINUE_ON_DIVERGENCE)
                dest = Path(str(report.get("archive_path") or dest))
                wrote = False
                items.append({
                    "session_id": artifact.get("session_id", ""),
                    "raw_path": str(dest),
                    "status": report.get("status", ""),
                    "source_regression": bool(report.get("source_regression")),
                    "source_missing": bool(report.get("source_missing")),
                    "raw_shrink_performed": False,
                    "changed": False,
                    "write_performed": False,
                    "platform_write_performed": False,
                    "memory_write_performed": False,
                })
                continue
            report = append_source_file(src, dest, source_inode=src_stat.st_ino, continue_on_divergence=DIRECT_OPENCLAW_BACKFILL_CONTINUE_ON_DIVERGENCE)
            dest = Path(str(report.get("archive_path") or dest))
            wrote = bool(report.get("write_performed"))
            if wrote:
                meta = {
                    "source_system": OPENCLAW_SOURCE_SYSTEM,
                    "source_path": str(src),
                    "source_mtime": src_stat.st_mtime,
                    "source_inode": src_stat.st_ino,
                    "source_checksum": report.get("source_sha256") or _file_hash(src),
                    "raw_checksum": report.get("archive_sha256") or _file_hash(dest),
                    "archived_at": ts(),
                    "source_computer": node_id(),
                    "source_window": artifact.get("canonical_window_id", ""),
                    "source_session": artifact.get("session_id", ""),
                    "native_artifact_format": OPENCLAW_NATIVE_RAW_FORMAT,
                    "raw_archive_layout": "computer_first",
                    "raw_archive_contract": report.get("contract", ""),
                }
                with Path(str(dest) + ".meta.json").open("w", encoding="utf-8") as handle:
                    json.dump(meta, handle, ensure_ascii=False, indent=2)
            if wrote:
                changed += 1
            items.append({
                "session_id": artifact.get("session_id", ""),
                "raw_path": str(dest),
                "status": report.get("status", ""),
                "source_regression": bool(report.get("source_regression")),
                "source_divergence": bool(report.get("source_divergence")),
                "source_missing": bool(report.get("source_missing")),
                "raw_shrink_performed": False,
                "changed": wrote,
                "write_performed": wrote,
                "platform_write_performed": False,
                "memory_write_performed": wrote,
            })
        except Exception as exc:
            items.append({
                "session_id": artifact.get("session_id", ""),
                "ok": False,
                "error": f"{type(exc).__name__}: {str(exc)[:160]}",
                "platform_write_performed": False,
            })
    return {
        "source_system": OPENCLAW_SOURCE_SYSTEM,
        "ok": all(item.get("ok", True) is not False for item in items),
        "changed": changed,
        "raw_sync": {
            "status": "openclaw_source_jsonl_monotonic_archive",
            "items_checked": len(items),
            "missing_or_stale_count": len([item for item in items if item.get("changed")]),
            "source_regression_count": len([item for item in items if item.get("source_regression")]),
            "source_divergence_count": len([item for item in items if item.get("source_divergence")]),
        },
        "result": {
            "items": items,
            "write_performed": bool(changed),
            "platform_write_performed": False,
            "memory_write_performed": bool(changed),
        },
    }


def _json_text_or_value(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return value
    if text[0] not in "[{":
        return value
    try:
        return json.loads(text)
    except Exception:
        return value


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _iso_from_epochish(value: Any) -> str:
    if value in (None, ""):
        return ""
    try:
        stamp = float(value)
    except Exception:
        return str(value)
    if stamp > 10_000_000_000:
        stamp = stamp / 1000.0
    try:
        return datetime.fromtimestamp(stamp, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return str(value)


def _hermes_message_select_columns(conn: sqlite3.Connection) -> list[str]:
    columns = [row[1] for row in conn.execute("pragma table_info(messages)")]
    wanted = [
        "id",
        "session_id",
        "role",
        "content",
        "tool_call_id",
        "tool_calls",
        "tool_name",
        "timestamp",
        "token_count",
        "finish_reason",
        "reasoning",
        "reasoning_content",
        "reasoning_details",
        "codex_reasoning_items",
        "codex_message_items",
        "platform_message_id",
        "observed",
        "active",
    ]
    return [column for column in wanted if column in columns]


def _hermes_read_session_messages(conn: sqlite3.Connection, session_id: str) -> list[dict[str, Any]]:
    columns = _hermes_message_select_columns(conn)
    if not columns:
        return []
    order_column = "id" if "id" in columns else "timestamp"
    rows = conn.execute(
        f"select {', '.join(columns)} from messages where session_id=? order by {order_column} asc",
        (session_id,),
    ).fetchall()
    messages: list[dict[str, Any]] = []
    for row in rows:
        item = dict(zip(columns, row))
        for key in (
            "tool_calls",
            "reasoning_details",
            "codex_reasoning_items",
            "codex_message_items",
        ):
            if key in item:
                item[key] = _json_text_or_value(item.get(key))
        messages.append(item)
    return messages


def _hermes_session_metadata(conn: sqlite3.Connection, session_id: str) -> dict[str, Any]:
    columns = [row[1] for row in conn.execute("pragma table_info(sessions)")]
    wanted = [
        column for column in (
            "id",
            "source",
            "user_id",
            "model",
            "model_config",
            "parent_session_id",
            "started_at",
            "ended_at",
            "end_reason",
            "message_count",
            "title",
            "cwd",
        )
        if column in columns
    ]
    if not wanted:
        return {"id": session_id}
    row = conn.execute(
        f"select {', '.join(wanted)} from sessions where id=?",
        (session_id,),
    ).fetchone()
    if not row:
        return {"id": session_id}
    data = dict(zip(wanted, row))
    if "model_config" in data:
        data["model_config"] = _json_text_or_value(data.get("model_config"))
    return data


def _hermes_raw_record_from_message(
    *,
    db_path: Path,
    raw_path: Path,
    session_meta: dict[str, Any],
    message: dict[str, Any],
) -> dict[str, Any]:
    role = _safe_str(message.get("role"))
    message_id = _safe_str(message.get("id") or message.get("platform_message_id"))
    session_id = _safe_str(message.get("session_id") or session_meta.get("id"))
    content = message.get("content") or ""
    timestamp = (
        _iso_from_epochish(message.get("timestamp"))
        or _iso_from_epochish(session_meta.get("started_at"))
        or "1970-01-01T00:00:00Z"
    )
    text_type = "input_text" if role in {"user", "human"} else "output_text"
    payload_content = [{"type": text_type, "text": str(content)}] if content != "" else []
    record_id_basis = "|".join([
        "hermes",
        str(db_path),
        session_id,
        message_id,
        _safe_str(message.get("timestamp")),
    ])
    return {
        "timestamp": timestamp,
        "id": "hermes-" + hashlib.sha256(record_id_basis.encode("utf-8")).hexdigest()[:24],
        "type": "response_item",
        "source_system": HERMES_SOURCE_SYSTEM,
        "payload": {
            "type": "message",
            "role": role,
            "content": payload_content,
        },
        "hermes": {
            "message_id": message.get("id"),
            "platform_message_id": message.get("platform_message_id"),
            "tool_call_id": message.get("tool_call_id"),
            "tool_name": message.get("tool_name"),
            "tool_calls": message.get("tool_calls"),
            "token_count": message.get("token_count"),
            "finish_reason": message.get("finish_reason"),
            "reasoning": message.get("reasoning"),
            "reasoning_content": message.get("reasoning_content"),
            "reasoning_details": message.get("reasoning_details"),
            "codex_reasoning_items": message.get("codex_reasoning_items"),
            "codex_message_items": message.get("codex_message_items"),
            "observed": message.get("observed"),
            "active": message.get("active"),
            "session": session_meta,
        },
        "source_refs": {
            "source_system": HERMES_SOURCE_SYSTEM,
            "source_path": str(db_path),
            "source_table": "messages",
            "source_row_id": message.get("id"),
            "session_id": session_id,
            "canonical_window_id": session_id,
            "raw_session_path": str(raw_path),
            "native_artifact_format": HERMES_STATE_DB_RAW_FORMAT,
            "raw_archive_layout": "computer_first",
            "source_storage": "sqlite_state_db",
        },
    }


def _write_jsonl_atomic(path: Path, records: list[dict[str, Any]]) -> tuple[bool, str]:
    report = append_jsonl_records(path, records)
    checksum = _file_hash(path) if path.exists() else hashlib.sha256(b"").hexdigest()
    return bool(report.get("write_performed")), checksum


def _hermes_backfill(*, limit: int, target_raw_paths: set[str] | None = None) -> dict[str, Any]:
    guardian = _guardian_module()
    db_summary = guardian._hermes_state_db_summary()
    if not db_summary.get("exists"):
        return {
            "source_system": HERMES_SOURCE_SYSTEM,
            "ok": False,
            "changed": 0,
            "error": "hermes_state_db_missing",
            "write_performed": False,
            "platform_write_performed": False,
            "memory_write_performed": False,
        }
    db_path = Path(db_summary.get("path", "")).expanduser()
    session_summaries = [
        item for item in db_summary.get("session_summaries", [])
        if isinstance(item, dict) and item.get("session_id")
    ]
    session_ids = [
        _safe_str(item.get("session_id"))
        for item in session_summaries[: max(1, int(limit or 20))]
    ]
    if not session_ids and db_summary.get("session_id"):
        session_ids = [_safe_str(db_summary.get("session_id"))]
    changed = 0
    items: list[dict[str, Any]] = []
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=1)
        try:
            for session_id in session_ids:
                try:
                    raw_path = guardian._hermes_raw_paths_for_session(session_id)[0]
                    if target_raw_paths and str(raw_path) not in target_raw_paths:
                        continue
                    session_meta = _hermes_session_metadata(conn, session_id)
                    messages = _hermes_read_session_messages(conn, session_id)
                    records = [
                        _hermes_raw_record_from_message(
                            db_path=db_path,
                            raw_path=raw_path,
                            session_meta=session_meta,
                            message=message,
                        )
                        for message in messages
                    ]
                    append_report = append_jsonl_records(raw_path, records)
                    wrote = bool(append_report.get("write_performed"))
                    checksum = _file_hash(raw_path) if raw_path.exists() else hashlib.sha256(b"").hexdigest()
                    if wrote:
                        changed += 1
                        meta = {
                            "source_system": HERMES_SOURCE_SYSTEM,
                            "source_path": str(db_path),
                            "source_checksum": checksum,
                            "archived_at": ts(),
                            "source_computer": node_id(),
                            "source_session": session_id,
                            "native_artifact_format": HERMES_STATE_DB_RAW_FORMAT,
                            "raw_archive_layout": "computer_first",
                            "source_storage": "sqlite_state_db",
                            "message_count": len(messages),
                            "raw_archive_contract": append_report.get("contract", ""),
                            "platform_write_performed": False,
                        }
                        with Path(str(raw_path) + ".meta.json").open("w", encoding="utf-8") as handle:
                            json.dump(meta, handle, ensure_ascii=False, indent=2)
                    items.append({
                        "session_id": session_id,
                        "raw_path": str(raw_path),
                        "message_count": len(messages),
                        "status": append_report.get("status", ""),
                        "source_regression": bool(append_report.get("source_regression")),
                        "source_divergence": bool(append_report.get("source_divergence")),
                        "raw_shrink_performed": False,
                        "changed": wrote,
                        "write_performed": wrote,
                        "platform_write_performed": False,
                        "memory_write_performed": wrote,
                    })
                except Exception as exc:
                    items.append({
                        "session_id": session_id,
                        "ok": False,
                        "error": f"{type(exc).__name__}: {str(exc)[:160]}",
                        "platform_write_performed": False,
                    })
        finally:
            conn.close()
    except Exception as exc:
        return {
            "source_system": HERMES_SOURCE_SYSTEM,
            "ok": False,
            "changed": 0,
            "error": f"{type(exc).__name__}: {str(exc)[:160]}",
            "write_performed": False,
            "platform_write_performed": False,
            "memory_write_performed": False,
        }
    return {
        "source_system": HERMES_SOURCE_SYSTEM,
        "ok": all(item.get("ok", True) is not False for item in items),
        "changed": changed,
        "write_performed": bool(changed),
        "platform_write_performed": False,
        "memory_write_performed": bool(changed),
        "raw_sync": {
            "status": "hermes_state_db_messages_exported_to_raw",
            "items_checked": len(items),
            "missing_or_stale_count": len([item for item in items if item.get("changed")]),
            "source_storage": "sqlite_state_db",
        },
        "result": {
            "items": items,
            "write_performed": bool(changed),
            "platform_write_performed": False,
            "memory_write_performed": bool(changed),
        },
    }


RAW_BACKFILL_HANDLERS = {
    "source_artifact_copy": _openclaw_backfill,
    "state_db_messages": _hermes_backfill,
}


def run_raw_backfill(
    *,
    limit: int = 20,
    source_systems: list[str] | None = None,
    target_raw_paths: list[str] | None = None,
) -> dict[str, Any]:
    guardian = _guardian_module()
    requested = set(source_systems or [])
    requested_targets = {str(Path(path).expanduser()) for path in (target_raw_paths or []) if str(path).strip()}
    platform_backfills = dict(declared_raw_backfill_source_systems())
    supported = {source_system for source_system, _ in guardian.GUARDED_CONNECTORS} | set(platform_backfills)
    results = []
    for source_system, module_name in guardian.GUARDED_CONNECTORS:
        if requested and source_system not in requested:
            continue
        results.append(_connector_backfill(
            source_system,
            module_name,
            limit=limit,
            target_raw_paths=requested_targets or None,
        ))
    for source_system, backfill_kind in platform_backfills.items():
        if requested and source_system not in requested:
            continue
        handler = RAW_BACKFILL_HANDLERS.get(backfill_kind)
        if handler is not None:
            results.append(handler(limit=limit, target_raw_paths=requested_targets or None))
    for source_system in sorted(requested - supported):
        results.append({
            "source_system": source_system,
            "ok": False,
            "changed": 0,
            "error": "backfill_not_implemented_for_source_system",
            "write_performed": False,
            "platform_write_performed": False,
            "memory_write_performed": False,
        })
    matched_targets = {
        str(item.get("raw_path") or "")
        for result in results
        for item in ((result.get("result") or {}).get("items") or [])
        if str(item.get("raw_path") or "")
    }
    unmatched_targets = sorted(requested_targets - matched_targets)
    write_performed = any(bool(item.get("changed")) for item in results)
    return {
        "ok": all(item.get("ok") for item in results) and not unmatched_targets,
        "contract": RAW_BACKFILL_CONTRACT,
        "generated_at": ts(),
        "write_performed": write_performed,
        "platform_write_performed": False,
        "memory_write_performed": write_performed,
        "limit": limit,
        "targeted_backfill": bool(requested_targets),
        "requested_target_count": len(requested_targets),
        "matched_target_count": len(requested_targets & matched_targets),
        "unmatched_target_raw_paths": unmatched_targets,
        "source_systems": [item.get("source_system") for item in results],
        "results": results,
    }


__all__ = [
    "RAW_BACKFILL_CONTRACT",
    "RAW_RECORD_BACKFILL_REPAIR_CONTRACT",
    "get_raw_record_backfill_contract",
    "hermes_backfill_recommendation",
    "_connector_backfill",
    "_openclaw_backfill",
    "_json_text_or_value",
    "_hermes_message_select_columns",
    "_hermes_read_session_messages",
    "_hermes_session_metadata",
    "_hermes_raw_record_from_message",
    "_write_jsonl_atomic",
    "_hermes_backfill",
    "run_raw_backfill",
]
