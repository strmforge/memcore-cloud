"""Bounded canonical-index refresh for records selected by the stat gate."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

try:
    from raw_record_canonical_index import (
        CANONICAL_RECORD_INDEX_CONTRACT,
        _canonical_index_record,
        _connect_records_db,
        _ensure_index_schema,
        _path_state_signature,
        _record_id,
        _safe_str,
        records_db_path,
        ts,
    )
    from source_system_runtime_declarations import source_system_uses_raw_path_as_canonical_source
except ImportError:  # pragma: no cover
    from src.raw_record_canonical_index import (
        CANONICAL_RECORD_INDEX_CONTRACT,
        _canonical_index_record,
        _connect_records_db,
        _ensure_index_schema,
        _path_state_signature,
        _record_id,
        _safe_str,
        records_db_path,
        ts,
    )
    from src.source_system_runtime_declarations import source_system_uses_raw_path_as_canonical_source


def refresh_changed_records_index(
    record_ids: list[str] | tuple[str, ...] | set[str],
    *,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Refresh changed records without rediscovering the recent catalog."""
    ordered_ids = list(dict.fromkeys(
        _safe_str(record_id) for record_id in record_ids if _safe_str(record_id)
    ))[:500]
    path = Path(db_path).expanduser() if db_path else records_db_path()
    if not ordered_ids or not path.exists():
        return {
            "ok": True,
            "contract": CANONICAL_RECORD_INDEX_CONTRACT,
            "records_upserted": 0,
            "records_skipped_unchanged": 0,
            "canonical_records_refreshed": 0,
            "source_missing_index_preserved": 0,
            "canonical_messages_upserted": 0,
            "canonical_chunks_upserted": 0,
            "write_performed": False,
        }

    conn = _connect_records_db(path)
    try:
        _ensure_index_schema(conn)
        placeholders = ",".join("?" for _ in ordered_ids)
        rows = conn.execute(
            f"""
            select record_id, source_system, source_path, raw_path, payload_json
            from records
            where record_id in ({placeholders})
            """,
            ordered_ids,
        ).fetchall()
        rows_by_id = {_safe_str(row[0]): row for row in rows}
        refreshed = 0
        canonical_refreshed = 0
        source_missing_preserved = 0
        messages_upserted = 0
        chunks_upserted = 0
        updated_at = ts()
        for record_id in ordered_ids:
            row = rows_by_id.get(record_id)
            if row is None:
                continue
            source_system = _safe_str(row[1])
            source_path = _safe_str(row[2])
            raw_path = _safe_str(row[3])
            source_exists, source_mtime, source_size = _path_state_signature(source_path)
            raw_exists, raw_mtime, raw_size = _path_state_signature(raw_path)

            item: dict[str, Any] = {}
            payload_loaded = False
            try:
                loaded = json.loads(_safe_str(row[4]) or "{}")
                if isinstance(loaded, dict):
                    item = loaded
                    payload_loaded = True
            except (TypeError, ValueError):
                pass
            item["source_system"] = source_system
            item["source_path"] = source_path
            item["raw_path"] = raw_path

            identity_matches = payload_loaded and _record_id(item) == record_id
            canonical_source_available = (
                raw_exists
                if source_system_uses_raw_path_as_canonical_source(source_system)
                else source_exists or (not source_path and raw_exists)
            )
            if identity_matches and canonical_source_available:
                canonical_result = _canonical_index_record(
                    conn,
                    item,
                    updated_at=updated_at,
                    repair_missing_raw_offsets=False,
                )
                canonical_refreshed += int(canonical_result.get("sessions_indexed", 0) or 0)
                messages_upserted += int(
                    canonical_result.get("new_messages_indexed")
                    if canonical_result.get("new_messages_indexed") is not None
                    else (canonical_result.get("messages_indexed", 0) or 0)
                )
                chunks_upserted += int(
                    canonical_result.get("new_chunks_indexed")
                    if canonical_result.get("new_chunks_indexed") is not None
                    else (canonical_result.get("chunks_indexed", 0) or 0)
                )
            elif not source_exists and raw_exists:
                source_missing_preserved += 1

            conn.execute(
                """
                update records
                set source_mtime=?, raw_mtime=?, source_size_bytes=?,
                    raw_size_bytes=?, updated_at=?
                where record_id=?
                """,
                (source_mtime, raw_mtime, source_size, raw_size, updated_at, record_id),
            )
            refreshed += 1
        conn.commit()
    finally:
        conn.close()

    return {
        "ok": True,
        "contract": CANONICAL_RECORD_INDEX_CONTRACT,
        "records_upserted": refreshed,
        "records_skipped_unchanged": max(0, len(ordered_ids) - refreshed),
        "canonical_records_refreshed": canonical_refreshed,
        "source_missing_index_preserved": source_missing_preserved,
        "canonical_messages_upserted": messages_upserted,
        "canonical_chunks_upserted": chunks_upserted,
        "write_performed": refreshed > 0,
    }


__all__ = ["refresh_changed_records_index"]
