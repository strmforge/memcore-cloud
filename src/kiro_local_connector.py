#!/usr/bin/env python3
"""Kiro local source connector.

The first verified Kiro source shape is the native Windows
`workspace-sessions/<workspace>/session.json` store. This connector treats that
store as a source system, converts saved user/assistant turns into Memcore raw
JSONL, and dedupes by stable message keys so the P0 watcher can poll it every
few seconds without duplicating records.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config_loader import checkpoint_file, memory_root, node_id
try:
    from src.raw_archive_layout import existing_or_preferred_raw_archive_path, preferred_raw_archive_path
except ImportError:
    from raw_archive_layout import existing_or_preferred_raw_archive_path, preferred_raw_archive_path
try:
    from src.raw_archive_monotonic import (
        latest_archive_segment,
        select_archive_segment,
        select_archive_segment_metadata_only,
    )
except ImportError:
    from raw_archive_monotonic import (
        latest_archive_segment,
        select_archive_segment,
        select_archive_segment_metadata_only,
    )
try:
    from src.window_binding_registry import register_current_window
except ImportError:
    from window_binding_registry import register_current_window
try:
    from src.tiandao.memory_routing import (
        DEFAULT_CONTINUOUS_SYNC_INTERVAL_MS,
        TIANDAO_CONVERSATION_EVIDENCE_CONTRACT,
        conversation_capture_verdict,
        is_complete_conversation_roles,
    )
except ImportError:
    from tiandao.memory_routing import (
        DEFAULT_CONTINUOUS_SYNC_INTERVAL_MS,
        TIANDAO_CONVERSATION_EVIDENCE_CONTRACT,
        conversation_capture_verdict,
        is_complete_conversation_roles,
    )

UTC = timezone.utc
SOURCE_SYSTEM = "kiro"
NATIVE_ARTIFACT_FORMAT = "kiro_workspace_sessions_json"
RAW_INGEST_SCHEMA_VERSION = "kiro_workspace_sessions_json.v1"
DEFAULT_SYNC_INTERVAL_MS = DEFAULT_CONTINUOUS_SYNC_INTERVAL_MS
MIN_SYNC_INTERVAL_MS = 50
MAX_SYNC_INTERVAL_MS = 3_600_000


def ts() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe_segment(value: str, fallback: str = "unknown") -> str:
    text = str(value or "").strip() or fallback
    text = re.sub(r"[^A-Za-z0-9._=-]+", "-", text).strip(".-_")
    return text[:96] or fallback


def _public_path_label(path: str) -> str:
    path = str(path or "")
    if not path:
        return ""
    try:
        p = Path(path).expanduser()
        home = Path.home().resolve()
        resolved = p.resolve()
        try:
            rel = resolved.relative_to(home)
            return "~/" + str(rel)
        except ValueError:
            return p.name or path
    except Exception:
        return Path(path).name or path


def _milliseconds_setting(
    env_ms_name: str,
    default_ms: int,
    *,
    legacy_env_seconds_name: str = "",
    minimum: int = MIN_SYNC_INTERVAL_MS,
    maximum: int = MAX_SYNC_INTERVAL_MS,
) -> int:
    raw = os.environ.get(env_ms_name)
    if raw is None and legacy_env_seconds_name:
        raw_seconds = os.environ.get(legacy_env_seconds_name)
        if raw_seconds is not None:
            try:
                raw = int(float(raw_seconds) * 1000)
            except Exception:
                raw = None
    try:
        value = int(float(raw if raw is not None else default_ms))
    except Exception:
        value = default_ms
    return max(minimum, min(value, maximum))


def watcher_interval_milliseconds() -> int:
    return _milliseconds_setting(
        "MEMCORE_WATCHER_INTERVAL_MS",
        DEFAULT_SYNC_INTERVAL_MS,
        legacy_env_seconds_name="MEMCORE_WATCHER_POLL_INTERVAL_SECONDS",
    )


def _text_from_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                value = item.get("text") or item.get("content") or item.get("value")
                if value:
                    parts.append(_text_from_content(value))
            elif item:
                parts.append(str(item))
        return "\n".join(part for part in parts if part)
    if isinstance(content, dict):
        for key in ("text", "content", "value", "markdown"):
            if key in content:
                return _text_from_content(content.get(key))
        return json.dumps(content, ensure_ascii=False)
    return str(content) if content else ""


def _kiro_workspace_session_roots() -> list[Path]:
    roots: list[Path] = []
    explicit = os.environ.get("KIRO_WORKSPACE_SESSIONS_DIR", "").strip()
    for item in explicit.split(os.pathsep):
        if item.strip():
            roots.append(Path(item).expanduser())

    home = Path.home()
    appdata = os.environ.get("APPDATA", "").strip()
    if appdata:
        roots.append(Path(appdata) / "Kiro" / "User" / "globalStorage" / "kiro.kiroagent" / "workspace-sessions")
    roots.append(home / "AppData" / "Roaming" / "Kiro" / "User" / "globalStorage" / "kiro.kiroagent" / "workspace-sessions")
    roots.append(home / ".kiro" / "workspace-sessions")

    unique: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        text = str(root)
        if text not in seen:
            unique.append(root)
            seen.add(text)
    return unique


def _safe_stat(path: Path) -> os.stat_result | None:
    try:
        return path.stat()
    except OSError:
        return None


def _file_hash(path: Path) -> str:
    h = hashlib.sha256()
    try:
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
    except OSError:
        return ""
    return h.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _candidate_session_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    if root.is_file() and root.name == "session.json":
        return [root]
    files: list[Path] = []
    try:
        for path in root.rglob("session.json"):
            if path.is_file():
                files.append(path)
    except OSError:
        return []
    return files


def _native_id_from_message(container: dict[str, Any], msg: dict[str, Any], index: int) -> str:
    for key in ("id", "messageId", "message_id", "turnId", "turn_id", "uuid"):
        value = msg.get(key) or container.get(key)
        if value:
            return str(value)
    return f"msg_{index + 1:04d}"


def _timestamp_from_message(container: dict[str, Any], msg: dict[str, Any]) -> str:
    for key in ("createdAt", "created_at", "timestamp", "time", "date"):
        value = msg.get(key) or container.get(key)
        if value:
            return str(value)
    return ts()


def _message_from_obj(value: Any, index: int) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    msg = value.get("message") if isinstance(value.get("message"), dict) else value
    if not isinstance(msg, dict):
        return None
    role = str(msg.get("role") or value.get("role") or "").strip().lower()
    if role in {"human"}:
        role = "user"
    if role in {"ai", "agent", "bot"}:
        role = "assistant"
    if role not in {"user", "assistant"}:
        return None
    content = _text_from_content(
        msg.get("content")
        if "content" in msg
        else msg.get("text") or value.get("content") or value.get("text")
    ).strip()
    if not content:
        return None
    return {
        "role": role,
        "content": content,
        "native_id": _native_id_from_message(value, msg, index),
        "created_at": _timestamp_from_message(value, msg),
    }


def _extract_messages(data: dict[str, Any]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []

    def visit(value: Any) -> None:
        if isinstance(value, list):
            for item in value:
                visit(item)
            return
        if not isinstance(value, dict):
            return
        msg = _message_from_obj(value, len(messages))
        if msg:
            messages.append(msg)
            return
        for key in ("history", "messages", "turns", "entries", "items", "children"):
            if key in value:
                visit(value.get(key))

    visit(data)
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for msg in messages:
        key = (
            str(msg.get("native_id") or ""),
            str(msg.get("role") or ""),
            hashlib.sha256(str(msg.get("content") or "").encode("utf-8")).hexdigest(),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(msg)
    return deduped


def artifact_from_path(path: Path) -> dict[str, Any]:
    path = path.expanduser()
    stat = path.stat()
    workspace_id = _safe_segment(path.parent.name, "workspace")
    return {
        "source_system": SOURCE_SYSTEM,
        "artifact_type": NATIVE_ARTIFACT_FORMAT,
        "source_path": str(path),
        "filename": path.name,
        "session_id": workspace_id,
        "native_thread_id": workspace_id,
        "canonical_window_id": workspace_id,
        "workspace_id": workspace_id,
        "computer_name": node_id(),
        "size_bytes": stat.st_size,
        "mtime": datetime.fromtimestamp(stat.st_mtime, UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "capture_classification": "SHADOW",
        "scope_level": "workspace_session",
        "read_only_probe": True,
    }


def discover_sessions(limit: int = 0) -> list[dict[str, Any]]:
    files: list[Path] = []
    for root in _kiro_workspace_session_roots():
        files.extend(_candidate_session_files(root))
    unique = {str(path): path for path in files}
    ordered = sorted(unique.values(), key=lambda p: (_safe_stat(p).st_mtime if _safe_stat(p) else 0), reverse=True)
    if limit and limit > 0:
        ordered = ordered[:limit]
    artifacts: list[dict[str, Any]] = []
    for path in ordered:
        try:
            artifacts.append(artifact_from_path(path))
        except OSError:
            continue
    return artifacts


def _raw_dest_for_artifact(artifact: dict[str, Any]) -> Path:
    root = memory_root()
    preferred = preferred_raw_archive_path(
        root,
        computer_name=artifact.get("computer_name") or node_id(),
        source_system=SOURCE_SYSTEM,
        native_format=NATIVE_ARTIFACT_FORMAT,
        native_scope=_safe_segment(artifact.get("canonical_window_id"), "workspace"),
        session_id=_safe_segment(artifact.get("session_id"), "session"),
    )
    return existing_or_preferred_raw_archive_path(root, preferred)


def load_checkpoint() -> dict[str, Any]:
    path = checkpoint_file()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8-sig") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_checkpoint(data: dict[str, Any]) -> None:
    path = checkpoint_file()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)


def _checkpoint_key(source_path: str) -> str:
    return f"{SOURCE_SYSTEM}:{os.path.abspath(os.path.expanduser(source_path))}"


def _message_content_hash(content: str) -> str:
    return hashlib.sha256(str(content or "").encode("utf-8")).hexdigest()


def _message_dedupe_key(artifact: dict[str, Any], message: dict[str, Any], index: int) -> str:
    basis = {
        "source_system": SOURCE_SYSTEM,
        "session_id": artifact.get("session_id", ""),
        "native_id": message.get("native_id") or f"msg_{index + 1:04d}",
        "role": message.get("role", ""),
        "content_hash": _message_content_hash(message.get("content", "")),
    }
    return hashlib.sha256(json.dumps(basis, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _record_dedupe_key(record: dict[str, Any]) -> str:
    raw_ingest = record.get("raw_ingest") if isinstance(record.get("raw_ingest"), dict) else {}
    return str(raw_ingest.get("message_dedupe_key") or "")


def _existing_dedupe_keys(path: Path) -> set[str]:
    keys: set[str] = set()
    if not path.exists():
        return keys
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                text = line.strip()
                if not text:
                    continue
                try:
                    obj = json.loads(text)
                except Exception:
                    obj = {}
                if isinstance(obj, dict):
                    key = _record_dedupe_key(obj)
                    if key:
                        keys.add(key)
    except OSError:
        pass
    return keys


def _record_from_message(artifact: dict[str, Any], message: dict[str, Any], index: int, raw_path: Path) -> dict[str, Any]:
    native_id = str(message.get("native_id") or f"msg_{index + 1:04d}")
    role = str(message.get("role") or "unknown")
    content = str(message.get("content") or "")
    refs = {
        "source_system": SOURCE_SYSTEM,
        "computer_name": artifact.get("computer_name") or node_id(),
        "canonical_window_id": artifact.get("canonical_window_id", ""),
        "session_id": artifact.get("session_id", ""),
        "native_thread_id": artifact.get("native_thread_id", artifact.get("session_id", "")),
        "source_path": artifact.get("source_path", ""),
        "raw_session_path": str(raw_path),
        "msg_ids": [native_id],
        "artifact_type": NATIVE_ARTIFACT_FORMAT,
        "native_artifact_format": NATIVE_ARTIFACT_FORMAT,
        "raw_archive_layout": "computer_first",
        "captured_at": ts(),
    }
    return {
        "timestamp": message.get("created_at") or ts(),
        "id": native_id,
        "type": "response_item",
        "source_system": SOURCE_SYSTEM,
        "payload": {
            "type": "message",
            "role": role,
            "content": [
                {
                    "type": "output_text" if role == "assistant" else "input_text",
                    "text": content,
                }
            ],
        },
        "source_refs": refs,
        "_source_refs": refs,
        "raw_ingest": {
            "schema_version": RAW_INGEST_SCHEMA_VERSION,
            "parser_kind": "kiro_workspace_sessions_json_collector",
            "message_index": index,
            "native_id": native_id,
            "message_content_hash": _message_content_hash(content),
            "message_dedupe_key": _message_dedupe_key(artifact, message, index),
            "saved_content_preserved_verbatim": True,
            "redaction_performed": False,
        },
    }


def _write_meta(dest: Path, artifact: dict[str, Any], src_stat: os.stat_result, message_count: int, fingerprint: str) -> None:
    meta = {
        "source_system": SOURCE_SYSTEM,
        "source_path": artifact.get("source_path", ""),
        "source_inode": getattr(src_stat, "st_ino", 0),
        "source_mtime": src_stat.st_mtime,
        "source_size": src_stat.st_size,
        "source_checksum": fingerprint,
        "archived_to": str(dest),
        "native_artifact_format": NATIVE_ARTIFACT_FORMAT,
        "raw_archive_layout": "computer_first",
        "session_id": artifact.get("session_id", ""),
        "canonical_window_id": artifact.get("canonical_window_id", ""),
        "message_count": message_count,
        "last_update": ts(),
    }
    with open(str(dest) + ".meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


def _stat_mtime_ms(stat_result: os.stat_result | None) -> int:
    if stat_result is None:
        return 0
    try:
        return int(stat_result.st_mtime_ns // 1_000_000)
    except Exception:
        return int(float(getattr(stat_result, "st_mtime", 0.0) or 0.0) * 1000)


def _epoch_ms_to_iso(value: int) -> str:
    if not value:
        return ""
    return datetime.fromtimestamp(value / 1000.0, UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _load_raw_meta(dest: Path) -> dict[str, Any]:
    try:
        data = json.loads(Path(str(dest) + ".meta.json").read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _raw_sync_item(artifact: dict[str, Any], scan_mode: str = "full") -> dict[str, Any]:
    scan_mode = "fast" if str(scan_mode or "").lower() in {"fast", "stat", "quick"} else "full"
    src = Path(artifact.get("source_path", "")).expanduser()
    src_stat = _safe_stat(src)
    base_dest = _raw_dest_for_artifact(artifact)
    if scan_mode == "fast":
        selection = select_archive_segment_metadata_only(
            base_dest,
            src_stat.st_ino if src_stat is not None else None,
        )
        dest = Path(selection["archive_path"])
    else:
        selection = {
            "selection_status": "full_connector_selection",
            "selection_proven_by_metadata": True,
            "generation_descriptor_incomplete": False,
            "body_read_performed": True,
        }
        dest = (
            select_archive_segment(base_dest, src_stat.st_ino, src)
            if src_stat is not None
            else latest_archive_segment(base_dest)
        )
    dest_stat = _safe_stat(dest)
    observed_at_ms = int(time.time() * 1000)
    source_size = int(src_stat.st_size if src_stat else artifact.get("size_bytes", 0) or 0)
    source_mtime_ms = _stat_mtime_ms(src_stat)
    raw_size = int(dest_stat.st_size if dest_stat else 0)
    raw_mtime_ms = _stat_mtime_ms(dest_stat)
    meta = _load_raw_meta(dest) if dest.exists() else {}
    source_checksum = _file_hash(src) if src_stat and scan_mode == "full" else ""
    meta_checksum = str(meta.get("source_checksum") or "")
    meta_source_size = int(meta.get("source_size", 0) or 0)
    missing = not dest.exists()
    try:
        metadata_mtime = float(meta.get("source_mtime", -1.0))
    except (TypeError, ValueError):
        metadata_mtime = -1.0
    metadata_identity_proven = bool(
        scan_mode == "full"
        or (
            src_stat is not None
            and selection.get("source_inode_match")
            and metadata_mtime == float(src_stat.st_mtime)
        )
    )
    metadata_available = bool(meta_checksum and meta_source_size)
    continuity_not_measured = bool(
        scan_mode == "fast"
        and not missing
        and not selection.get("generation_descriptor_incomplete")
        and (not metadata_identity_proven or not metadata_available)
    )
    stale = bool(
        not missing
        and (
            (source_checksum and meta_checksum and source_checksum != meta_checksum)
            or (source_size and meta_source_size and source_size != meta_source_size)
            or (source_size and not meta_source_size)
        )
    )
    source_regression = bool(source_size and meta_source_size and source_size < meta_source_size)
    raw_mtime_gap_ms = max(0, source_mtime_ms - raw_mtime_ms) if stale and source_mtime_ms and raw_mtime_ms else 0
    lag_ms = max(0, observed_at_ms - source_mtime_ms) if stale and source_mtime_ms else 0
    lag_bytes = max(0, source_size - meta_source_size) if stale else (source_size if missing else 0)
    return {
        "session_id": artifact.get("session_id", ""),
        "project_id": artifact.get("workspace_id", ""),
        "source_mtime": artifact.get("mtime", ""),
        "source_mtime_ms": source_mtime_ms,
        "source_mtime_precise": _epoch_ms_to_iso(source_mtime_ms),
        "source_size_bytes": source_size,
        "raw_mtime": _epoch_ms_to_iso(raw_mtime_ms),
        "raw_mtime_ms": raw_mtime_ms,
        "raw_mtime_precise": _epoch_ms_to_iso(raw_mtime_ms),
        "raw_size_bytes": raw_size,
        "raw_exists": dest.exists(),
        "raw_missing": missing,
        "raw_stale": stale,
        "raw_stale_authoritative": True,
        "raw_source_regression": source_regression,
        "raw_generation_descriptor_incomplete": bool(selection.get("generation_descriptor_incomplete")),
        "raw_monotonic_probe_ok": (
            None
            if continuity_not_measured
            else not selection.get("generation_descriptor_incomplete")
        ),
        "raw_monotonic_status": (
            "raw_generation_descriptor_incomplete"
            if selection.get("generation_descriptor_incomplete")
            else "source_regression_raw_retained"
            if source_regression
            else "raw_continuity_not_measured_fast"
            if continuity_not_measured
            else ""
        ),
        "raw_continuity_not_measured": continuity_not_measured,
        "raw_continuity_evidence": str(selection.get("selection_status") or ""),
        "raw_sync_scan_mode": scan_mode,
        "raw_body_read_performed": bool(selection.get("body_read_performed")),
        "raw_archive_lag_bytes": lag_bytes,
        "raw_archive_lag_milliseconds": lag_ms,
        "raw_source_mtime_gap_milliseconds": raw_mtime_gap_ms,
        "lag_observed_at_ms": observed_at_ms,
        "lag_observed_at": _epoch_ms_to_iso(observed_at_ms),
        "source_checksum": source_checksum,
        "raw_meta_source_checksum": meta_checksum,
        "raw_meta_source_size_bytes": meta_source_size,
        "source_path_label": _public_path_label(str(src)),
        "raw_path_label": _public_path_label(str(dest)),
        "raw_freshness_basis": (
            "source_json_checksum_meta"
            if scan_mode == "full"
            else "source_and_raw_stat_plus_existing_sidecars"
        ),
    }


def _register_current_window_for_artifact(artifact: dict[str, Any], dest: str) -> dict[str, Any]:
    workspace_id = str(artifact.get("workspace_id") or artifact.get("canonical_window_id") or "").strip()
    session_id = str(artifact.get("session_id") or workspace_id).strip()
    return register_current_window(
        source_system=SOURCE_SYSTEM,
        consumer=SOURCE_SYSTEM,
        canonical_window_id=workspace_id or session_id,
        session_id=session_id,
        native_window_id=str(artifact.get("native_thread_id") or session_id),
        title=workspace_id,
        source_path=str(dest or ""),
        binding_source="kiro_workspace_sessions_json_complete_capture",
        confidence="observed_kiro_complete_conversation_change",
        metadata={
            "workspace_id": workspace_id,
            "project_id": workspace_id,
            "native_artifact_format": NATIVE_ARTIFACT_FORMAT,
            "raw_archive_layout": "computer_first",
        },
    )


def archive_session(source_path: str, dry_run: bool = False, artifact: dict[str, Any] | None = None) -> tuple[str, str, dict[str, Any]]:
    src = Path(source_path).expanduser()
    if artifact is None:
        artifact = artifact_from_path(src)
    base_dest = _raw_dest_for_artifact(artifact)
    stat = _safe_stat(src)
    if stat is None:
        dest = latest_archive_segment(base_dest)
        if dest.exists():
            return str(dest), "source_regression_raw_retained(source=missing)", {
                "records_written": 0,
                "source_regression": True,
                "source_missing": True,
                "raw_shrink_performed": False,
            }
        return str(base_dest), "error: cannot stat source", {"records_written": 0}
    dest = select_archive_segment(base_dest, stat.st_ino, src)
    fingerprint = _file_hash(src)
    checkpoint = load_checkpoint()
    key = _checkpoint_key(str(src))
    prior = checkpoint.get(key, {}) if isinstance(checkpoint.get(key), dict) else {}
    if (
        prior
        and prior.get("fingerprint") == fingerprint
        and prior.get("source_size") == stat.st_size
        and dest.exists()
        and not dry_run
    ):
        return str(dest), "up_to_date(fingerprint)", {"records_written": 0}

    data = _load_json(src)
    messages = _extract_messages(data)
    roles = sorted({str(item.get("role") or "") for item in messages if item.get("role")})
    capture_verdict = conversation_capture_verdict(roles, candidate_count=1 if messages else 0)
    complete = is_complete_conversation_roles(roles)
    existing = _existing_dedupe_keys(dest)
    records = [
        _record_from_message(artifact, message, index, dest)
        for index, message in enumerate(messages)
    ]
    new_records = [record for record in records if _record_dedupe_key(record) not in existing]
    if dry_run:
        return str(dest), f"dry_run(records={len(new_records)})", {
            "records_written": 0,
            "would_write": len(new_records),
            "message_count": len(messages),
            "roles": roles,
            "complete_conversation_candidate": complete,
            "tiandao_conversation_evidence_contract": TIANDAO_CONVERSATION_EVIDENCE_CONTRACT,
            "conversation_capture_verdict": capture_verdict,
        }

    if new_records:
        existed_before = dest.exists()
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("a", encoding="utf-8") as f:
            for record in new_records:
                f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        status = f"appended({len(new_records)} records)" if existed_before else f"archived({len(new_records)} records)"
    else:
        status = "up_to_date(messages_deduped)"

    checkpoint[key] = {
        "fingerprint": fingerprint,
        "source_size": stat.st_size,
        "source_mtime": stat.st_mtime,
        "archived_to": str(dest),
        "source_system": SOURCE_SYSTEM,
        "message_count": len(messages),
        "roles": roles,
        "complete_conversation_candidate": complete,
        "tiandao_conversation_evidence_contract": TIANDAO_CONVERSATION_EVIDENCE_CONTRACT,
        "conversation_capture_verdict": capture_verdict,
        "last_update": ts(),
    }
    save_checkpoint(checkpoint)
    _write_meta(dest, artifact, stat, len(messages), fingerprint)
    return str(dest), status, {
        "records_written": len(new_records),
        "message_count": len(messages),
        "roles": roles,
        "complete_conversation_candidate": complete,
        "tiandao_conversation_evidence_contract": TIANDAO_CONVERSATION_EVIDENCE_CONTRACT,
        "conversation_capture_verdict": capture_verdict,
    }


def scan_sessions(dry_run: bool = False, limit: int = 0, public: bool = False) -> dict[str, Any]:
    artifacts = discover_sessions(limit=limit)
    items: list[dict[str, Any]] = []
    changed = 0
    would_change = 0
    complete_count = 0
    window_bindings: list[dict[str, Any]] = []
    window_binding_skipped = 0
    current_window_registered = False
    for artifact in artifacts:
        dest, status_value, detail = archive_session(
            artifact["source_path"],
            dry_run=dry_run,
            artifact=artifact,
        )
        if dry_run:
            would_change += int(detail.get("would_write") or 0)
        elif status_value.startswith(("archived", "appended")):
            changed += 1
        if detail.get("complete_conversation_candidate"):
            complete_count += 1
            if not dry_run and status_value.startswith(("archived", "appended")) and not current_window_registered:
                binding = _register_current_window_for_artifact(artifact, dest)
                if binding.get("ok"):
                    window_bindings.append(binding)
                    current_window_registered = True
                else:
                    window_binding_skipped += 1
        items.append({
            "source_path": _public_path_label(artifact["source_path"]) if public else artifact["source_path"],
            "dest": _public_path_label(dest) if public else dest,
            "status": status_value,
            "session_id": artifact.get("session_id", ""),
            "canonical_window_id": artifact.get("canonical_window_id", ""),
            "message_count": int(detail.get("message_count") or 0),
            "roles": detail.get("roles", []),
            "complete_conversation_candidate": bool(detail.get("complete_conversation_candidate")),
            "tiandao_conversation_evidence_contract": detail.get("tiandao_conversation_evidence_contract", TIANDAO_CONVERSATION_EVIDENCE_CONTRACT),
            "conversation_capture_verdict": detail.get("conversation_capture_verdict", {}),
            "records_written": int(detail.get("records_written") or 0),
        })
    return {
        "ok": True,
        "source_system": SOURCE_SYSTEM,
        "native_artifact_format": NATIVE_ARTIFACT_FORMAT,
        "roots": [str(root) for root in _kiro_workspace_session_roots()],
        "discovered": len(artifacts),
        "changed": changed,
        "would_change": would_change,
        "complete_conversation_candidates": complete_count,
        "window_bindings_registered": len(window_bindings),
        "window_bindings": window_bindings,
        "window_binding_skipped": window_binding_skipped,
        "dry_run": dry_run,
        "items": items,
    }


def status() -> dict[str, Any]:
    artifacts = discover_sessions(limit=20)
    interval_ms = watcher_interval_milliseconds()
    return {
        "ok": True,
        "source_system": SOURCE_SYSTEM,
        "native_artifact_format": NATIVE_ARTIFACT_FORMAT,
        "tiandao_conversation_evidence_contract": TIANDAO_CONVERSATION_EVIDENCE_CONTRACT,
        "reachable": bool(artifacts),
        "roots": [_public_path_label(str(root)) for root in _kiro_workspace_session_roots()],
        "artifact_count_sample": len(artifacts),
        "latest": [
            {
                "source_system": SOURCE_SYSTEM,
                "artifact_type": NATIVE_ARTIFACT_FORMAT,
                "session_id": item.get("session_id", ""),
                "canonical_window_id": item.get("canonical_window_id", ""),
                "computer_name": item.get("computer_name", ""),
                "size_bytes": item.get("size_bytes", 0),
                "mtime": item.get("mtime", ""),
                "read_only_probe": True,
            }
            for item in artifacts[:5]
        ],
        "read_only": True,
        "collector_status": "continuous_incremental_json_snapshot",
        "event_driven_preferred": True,
        "poll_interval_milliseconds": interval_ms,
        "poll_interval_seconds": interval_ms / 1000.0,
        "target_latency_milliseconds": interval_ms,
        "millisecond_level": interval_ms < 1000,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Kiro local session connector")
    parser.add_argument("--discover", action="store_true")
    parser.add_argument("--scan", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    if args.discover:
        print(json.dumps(discover_sessions(limit=args.limit), ensure_ascii=False, indent=2))
    elif args.scan:
        print(json.dumps(scan_sessions(dry_run=args.dry_run, limit=args.limit), ensure_ascii=False, indent=2))
    else:
        print(json.dumps(status(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
