#!/usr/bin/env python3
"""
Codex local source connector.

Read-only source side:
- discovers local Codex rollout JSONL files under ~/.codex/sessions
- reads session metadata and thread names from Codex's official thread index
  (~/.codex/state_5.sqlite) when present, with session_index.jsonl as fallback

Write side:
- archives an independent raw copy into memory/<node>/codex/codex_session_jsonl/<project>/<session>.jsonl
- uses the shared memcore checkpoint for incremental appends
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import time
from collections import OrderedDict
from datetime import datetime, timezone
from itertools import zip_longest
from pathlib import Path
from typing import Any, Dict, List, Optional

from config_loader import checkpoint_file, memory_root, node_id
try:
    from src.raw_archive_layout import existing_or_preferred_raw_archive_path, preferred_raw_archive_path
except ImportError:
    from raw_archive_layout import existing_or_preferred_raw_archive_path, preferred_raw_archive_path
try:
    from src.raw_archive_monotonic import (
        archive_generation_chain,
        append_source_file,
        cached_divergence_witness_visible,
        latest_archive_segment,
        load_generation_descriptor,
        select_archive_segment,
        select_archive_segment_metadata_only,
    )
except ImportError:
    from raw_archive_monotonic import (
        archive_generation_chain,
        append_source_file,
        cached_divergence_witness_visible,
        latest_archive_segment,
        load_generation_descriptor,
        select_archive_segment,
        select_archive_segment_metadata_only,
    )
try:
    from src.window_binding_registry import register_current_window
except ImportError:
    from window_binding_registry import register_current_window
try:
    from src.canonical_dialogue_runtime import (
        canonical_dialogue_sidecar_path,
        forensic_runtime_manifest_path,
        materialize_canonical_dialogue,
    )
except ImportError:
    from canonical_dialogue_runtime import (
        canonical_dialogue_sidecar_path,
        forensic_runtime_manifest_path,
        materialize_canonical_dialogue,
    )

UTC = timezone.utc
SOURCE_SYSTEM = "codex"
NATIVE_ARTIFACT_FORMAT = "codex_session_jsonl"
SESSION_GLOB = "*.jsonl"
DEFAULT_SYNC_INTERVAL_MS = 250
MIN_SYNC_INTERVAL_MS = 50
MAX_SYNC_INTERVAL_MS = 3_600_000
DEFAULT_WATCH_SCAN_LIMIT = 8
STATUS_SCAN_LIMIT = 20
DEFAULT_TAIL_CATCHUP_BUDGET_MS = 900
DEFAULT_TAIL_CATCHUP_MAX_PASSES = 6
DEFAULT_RAW_LAG_SLA_MS = 1000
DEFAULT_BACKFILL_RECOMMEND_AFTER_MS = 5000
METADATA_DIVERGENCE_MAX_FILE_BYTES = 16 * 1024 * 1024
METADATA_DIVERGENCE_CACHE_LIMIT = 256
_METADATA_DIVERGENCE_CACHE: OrderedDict[tuple[Any, ...], dict[str, Any]] = OrderedDict()


def ts() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def codex_sessions_root() -> Path:
    override = os.environ.get("CODEX_SESSIONS_DIR", "").strip()
    return Path(override).expanduser() if override else Path.home() / ".codex" / "sessions"


def codex_home_root() -> Path:
    override = os.environ.get("CODEX_HOME", "").strip()
    return Path(override).expanduser() if override else Path.home() / ".codex"


def codex_session_index_path() -> Path:
    override = os.environ.get("CODEX_SESSION_INDEX", "").strip()
    return Path(override).expanduser() if override else Path.home() / ".codex" / "session_index.jsonl"


def codex_state_db_path() -> Path:
    override = os.environ.get("CODEX_STATE_DB", "").strip()
    return Path(override).expanduser() if override else codex_home_root() / "state_5.sqlite"


def _safe_segment(value: str, fallback: str = "unknown") -> str:
    text = str(value or "").strip() or fallback
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip(".-_")
    return text[:80] or fallback


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


def watch_scan_limit() -> int:
    raw = os.environ.get("MEMCORE_CODEX_WATCH_SCAN_LIMIT")
    try:
        value = int(raw if raw is not None else DEFAULT_WATCH_SCAN_LIMIT)
    except Exception:
        value = DEFAULT_WATCH_SCAN_LIMIT
    return max(1, min(value, 200))


def status_scan_limit() -> int:
    return STATUS_SCAN_LIMIT


def tail_catchup_budget_milliseconds() -> int:
    return _milliseconds_setting(
        "MEMCORE_CODEX_TAIL_CATCHUP_BUDGET_MS",
        DEFAULT_TAIL_CATCHUP_BUDGET_MS,
        minimum=0,
        maximum=30_000,
    )


def tail_catchup_max_passes() -> int:
    raw = os.environ.get("MEMCORE_CODEX_TAIL_CATCHUP_MAX_PASSES")
    try:
        value = int(raw if raw is not None else DEFAULT_TAIL_CATCHUP_MAX_PASSES)
    except Exception:
        value = DEFAULT_TAIL_CATCHUP_MAX_PASSES
    return max(1, min(value, 100))


def raw_lag_sla_milliseconds() -> int:
    return _milliseconds_setting(
        "MEMCORE_CODEX_RAW_LAG_SLA_MS",
        DEFAULT_RAW_LAG_SLA_MS,
        minimum=0,
        maximum=3_600_000,
    )


def project_id_from_cwd(cwd: str) -> str:
    if not cwd:
        return "no-cwd"
    expanded = os.path.expanduser(cwd)
    name = Path(expanded).name or "project"
    digest = hashlib.sha1(expanded.encode("utf-8")).hexdigest()[:8]
    return _safe_segment(f"{name}-{digest}", "project")


def _clean_path_text(value: Any) -> str:
    text = str(value or "").strip()
    if text.startswith("\\\\?\\"):
        return text[4:]
    if text.startswith("//?/"):
        return text[4:]
    return text


def _path_key(value: Any) -> str:
    text = _clean_path_text(value).replace("\\", "/").rstrip("/")
    return text.lower()


def _epoch_to_iso(value: Any) -> str:
    try:
        ts_value = float(value)
    except Exception:
        return str(value or "")
    if ts_value <= 0:
        return ""
    return datetime.fromtimestamp(ts_value, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _file_hash(path: Path) -> str:
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    if size > 50 * 1024 * 1024:
        return f"sha256_skipped_large_file:{size}"
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_session_index() -> Dict[str, dict]:
    index_path = codex_session_index_path()
    result: Dict[str, dict] = {}
    if not index_path.exists():
        return result
    try:
        with index_path.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                except Exception:
                    continue
                sid = str(item.get("id") or "")
                if sid:
                    result[sid] = item
    except OSError:
        return result
    return result


def _sqlite_ro_uri(path: Path) -> str:
    try:
        return path.resolve().as_uri() + "?mode=ro"
    except Exception:
        return f"file:{path}?mode=ro"


def _load_state_thread_index() -> Dict[str, Any]:
    """Read Codex Desktop/CLI's official thread table without touching chat bodies."""
    state_path = codex_state_db_path()
    result: Dict[str, Any] = {
        "by_id": {},
        "by_path": {},
        "state_db_path": str(state_path),
        "read_ok": False,
        "error": "",
    }
    if not state_path.exists():
        return result
    try:
        conn = sqlite3.connect(_sqlite_ro_uri(state_path), uri=True, timeout=1)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        columns = {row[1] for row in cur.execute("pragma table_info(threads)").fetchall()}
        wanted = [
            name
            for name in (
                "id",
                "rollout_path",
                "created_at",
                "updated_at",
                "source",
                "model_provider",
                "cwd",
                "title",
                "cli_version",
                "thread_source",
                "model",
                "reasoning_effort",
                "archived",
                "has_user_event",
            )
            if name in columns
        ]
        if not wanted or "id" not in wanted:
            conn.close()
            return result
        rows = cur.execute(f"select {','.join(wanted)} from threads").fetchall()
        conn.close()
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result

    for row in rows:
        item = dict(row)
        sid = str(item.get("id") or "").strip()
        rollout_path = _clean_path_text(item.get("rollout_path"))
        normalized = {
            "id": sid,
            "session_id": sid,
            "native_thread_id": sid,
            "rollout_path": rollout_path,
            "thread_name": str(item.get("title") or ""),
            "thread_updated_at": _epoch_to_iso(item.get("updated_at")),
            "thread_created_at": _epoch_to_iso(item.get("created_at")),
            "codex_source": str(item.get("source") or ""),
            "model_provider": str(item.get("model_provider") or ""),
            "project_root": _clean_path_text(item.get("cwd")),
            "cli_version": str(item.get("cli_version") or ""),
            "thread_source": str(item.get("thread_source") or ""),
            "model": str(item.get("model") or ""),
            "reasoning_effort": str(item.get("reasoning_effort") or ""),
            "archived": bool(item.get("archived")) if item.get("archived") is not None else False,
            "has_user_event": bool(item.get("has_user_event")) if item.get("has_user_event") is not None else False,
            "state_db_path": str(state_path),
            "index_source": "codex_state_5_threads",
        }
        if sid:
            result["by_id"][sid] = normalized
        if rollout_path:
            result["by_path"][_path_key(rollout_path)] = normalized
    result["read_ok"] = True
    return result


def _read_session_meta(path: Path) -> dict:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for _ in range(80):
                line = f.readline()
                if not line:
                    break
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                if obj.get("type") == "session_meta" and isinstance(obj.get("payload"), dict):
                    return obj["payload"]
    except OSError:
        return {}
    return {}


def _session_id_from_path(path: Path, meta: dict) -> str:
    sid = str(meta.get("id") or "").strip()
    if sid:
        return sid
    stem = path.stem
    if stem.startswith("rollout-"):
        match = re.match(
            r"^rollout-\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}-(.+)$",
            stem,
        )
        if match and match.group(1):
            return match.group(1)
        parts = stem.split("-")
        if len(parts) >= 6:
            return "-".join(parts[-5:])
    return stem


def _raw_archive_path_index() -> Dict[str, List[Path]]:
    root = Path(memory_root())
    candidates: Dict[str, List[Path]] = {}
    patterns = (
        "*/codex/codex_session_jsonl/*/*.jsonl",
        "codex/*/*/*.jsonl",
    )
    for pattern in patterns:
        for path in root.glob(pattern):
            if not path.is_file():
                continue
            if path.name.endswith(".canonical_dialogue.jsonl") or re.search(
                r"\.seg\d+\.jsonl$", path.name
            ):
                continue
            candidates.setdefault(path.stem, []).append(path)
    return {
        session_id: paths
        for session_id, paths in candidates.items()
        if paths
    }


def artifact_from_path(
    path: Path,
    index: Optional[Dict[str, dict]] = None,
    thread_index: Optional[Dict[str, Any]] = None,
    raw_archive_index: Optional[Dict[str, List[Path]]] = None,
    scan_mode: str = "full",
) -> dict:
    path = path.expanduser()
    scan_mode = "fast" if str(scan_mode or "").lower() in {"fast", "stat", "quick"} else "full"
    meta = {} if scan_mode == "fast" else _read_session_meta(path)
    session_id = _session_id_from_path(path, meta)
    index = index if index is not None else _load_session_index()
    thread_index = thread_index if thread_index is not None else _load_state_thread_index()
    thread_by_id = thread_index.get("by_id", {}) if isinstance(thread_index, dict) else {}
    thread_by_path = thread_index.get("by_path", {}) if isinstance(thread_index, dict) else {}
    official_thread = thread_by_id.get(session_id) or thread_by_path.get(_path_key(path))
    indexed = index.get(session_id, {})
    cwd = _clean_path_text(meta.get("cwd") or (official_thread or {}).get("project_root") or indexed.get("cwd") or "")
    raw_candidates = (
        list(raw_archive_index.get(session_id, []))
        if isinstance(raw_archive_index, dict)
        else []
    )
    raw_archive_path_hint = raw_candidates[0] if len(raw_candidates) == 1 else None
    project_id = (
        raw_archive_path_hint.parent.name
        if not cwd and raw_archive_path_hint is not None
        else project_id_from_cwd(cwd)
    )
    stat = path.stat()
    mtime = datetime.fromtimestamp(stat.st_mtime, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "source_system": SOURCE_SYSTEM,
        "artifact_type": "codex_session_jsonl",
        "source_path": str(path),
        "filename": path.name,
        "session_id": session_id,
        "native_thread_id": session_id,
        "canonical_window_id": project_id,
        "project_id": project_id,
        "project_root": cwd,
        "thread_name": (official_thread or {}).get("thread_name") or indexed.get("thread_name", ""),
        "thread_updated_at": (official_thread or {}).get("thread_updated_at") or indexed.get("updated_at", ""),
        "thread_index_source": (official_thread or {}).get("index_source") or ("session_index_jsonl" if indexed else ""),
        "codex_source": meta.get("source") or (official_thread or {}).get("codex_source", ""),
        "thread_source": meta.get("thread_source") or (official_thread or {}).get("thread_source", ""),
        "model_provider": meta.get("model_provider") or (official_thread or {}).get("model_provider", ""),
        "cli_version": meta.get("cli_version") or (official_thread or {}).get("cli_version", ""),
        "codex_model": (official_thread or {}).get("model", ""),
        "reasoning_effort": (official_thread or {}).get("reasoning_effort", ""),
        "official_thread_index_detected": bool(official_thread),
        "state_db_path": (official_thread or {}).get("state_db_path", ""),
        "computer_name": node_id(),
        "size_bytes": stat.st_size,
        "size_mb": round(stat.st_size / 1024 / 1024, 3),
        "mtime": mtime,
        "capture_classification": "SHADOW",
        "scope_level": "project",
        "read_only_probe": True,
        "discovery_scan_mode": scan_mode,
        "session_meta_body_read_performed": scan_mode == "full",
        "raw_archive_path_hint": str(raw_archive_path_hint or ""),
        "raw_archive_identity_status": (
            "matched_unique"
            if raw_archive_path_hint is not None
            else "ambiguous"
            if len(raw_candidates) > 1
            else "not_indexed"
        ),
    }


def discover_sessions(limit: int = 0, scan_mode: str = "full") -> List[dict]:
    scan_mode = "fast" if str(scan_mode or "").lower() in {"fast", "stat", "quick"} else "full"
    root = codex_sessions_root()
    if not root.exists():
        return []
    index = _load_session_index()
    thread_index = _load_state_thread_index()
    files = [p for p in root.rglob(SESSION_GLOB) if p.is_file()]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    if limit and limit > 0:
        files = files[:limit]
    raw_archive_index = _raw_archive_path_index() if scan_mode == "fast" else {}
    artifacts = []
    for path in files:
        try:
            artifacts.append(
                artifact_from_path(
                    path,
                    index=index,
                    thread_index=thread_index,
                    raw_archive_index=raw_archive_index,
                    scan_mode=scan_mode,
                )
            )
        except OSError:
            continue
    return artifacts


def source_refs_from_artifact(artifact: dict) -> dict:
    return {
        "source_system": SOURCE_SYSTEM,
        "computer_name": artifact.get("computer_name") or node_id(),
        "canonical_window_id": artifact.get("canonical_window_id", ""),
        "session_id": artifact.get("session_id", ""),
        "source_path": artifact.get("source_path", ""),
        "msg_ids": artifact.get("msg_ids", []) or [],
        "artifact_type": artifact.get("artifact_type", "codex_session_jsonl"),
        "captured_at": ts(),
        "project_root": artifact.get("project_root", ""),
        "project_id": artifact.get("project_id", artifact.get("canonical_window_id", "")),
        "thread_name": artifact.get("thread_name", ""),
        "native_thread_id": artifact.get("native_thread_id", artifact.get("session_id", "")),
        "thread_index_source": artifact.get("thread_index_source", ""),
    }


def public_artifact(artifact: dict) -> dict:
    """Return status-safe metadata without full local paths."""
    return {
        "source_system": SOURCE_SYSTEM,
        "artifact_type": artifact.get("artifact_type", "codex_session_jsonl"),
        "filename": artifact.get("filename", ""),
        "session_id": artifact.get("session_id", ""),
        "canonical_window_id": artifact.get("canonical_window_id", ""),
        "project_id": artifact.get("project_id", ""),
        "computer_name": artifact.get("computer_name", ""),
        "size_bytes": artifact.get("size_bytes", 0),
        "size_mb": artifact.get("size_mb", 0),
        "mtime": artifact.get("mtime", ""),
        "capture_classification": artifact.get("capture_classification", "SHADOW"),
        "scope_level": artifact.get("scope_level", "project"),
        "thread_index_source": artifact.get("thread_index_source", ""),
        "official_thread_index_detected": bool(artifact.get("official_thread_index_detected")),
        "read_only_probe": True,
    }


def _iso_to_epoch(value: str) -> float:
    text = str(value or "").strip()
    if not text:
        return 0.0
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text).timestamp()
    except Exception:
        return 0.0


def _file_mtime_iso(path: Path) -> str:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    except OSError:
        return ""


def _stat_mtime_ms(stat_result: Optional[os.stat_result]) -> int:
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


def _file_identity(path: Path) -> tuple[int, int, int, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return (
        int(stat.st_dev),
        int(stat.st_ino),
        int(stat.st_size),
        int(getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000))),
    )


def _metadata_only_line_difference(source_record: Any, archive_record: Any) -> bool:
    if not isinstance(source_record, dict) or not isinstance(archive_record, dict):
        return False
    source_payload = source_record.get("payload")
    archive_payload = archive_record.get("payload")
    if not isinstance(source_payload, dict) or not isinstance(archive_payload, dict):
        return False
    if "model_provider" not in source_payload or "model_provider" not in archive_payload:
        return False
    if source_payload.get("model_provider") == archive_payload.get("model_provider"):
        return False
    source_copy = dict(source_record)
    archive_copy = dict(archive_record)
    source_payload_copy = dict(source_payload)
    archive_payload_copy = dict(archive_payload)
    source_payload_copy.pop("model_provider", None)
    archive_payload_copy.pop("model_provider", None)
    source_copy["payload"] = source_payload_copy
    archive_copy["payload"] = archive_payload_copy
    return source_copy == archive_copy


def _metadata_only_divergence_probe(source: Path, archive: Path) -> dict[str, Any]:
    """Prove a bounded Codex rewrite changed only non-conversation metadata."""
    source_identity = _file_identity(source)
    archive_identity = _file_identity(archive)
    base = {
        "matched": False,
        "status": "not_measured",
        "metadata_only_fields": [],
        "compared_line_count": 0,
        "changed_line_count": 0,
        "bytes_read": 0,
    }
    if source_identity is None or archive_identity is None:
        return {**base, "status": "file_unavailable"}
    cache_key = (*source_identity, *archive_identity)
    cached = _METADATA_DIVERGENCE_CACHE.get(cache_key)
    if cached is not None:
        _METADATA_DIVERGENCE_CACHE.move_to_end(cache_key)
        return {**cached, "cache_hit": True}
    if max(source_identity[2], archive_identity[2]) > METADATA_DIVERGENCE_MAX_FILE_BYTES:
        return {**base, "status": "byte_limit_exceeded"}

    changed_line_count = 0
    compared_line_count = 0
    bytes_read = 0
    status = "semantic_mismatch"
    try:
        with source.open("rb") as source_handle, archive.open("rb") as archive_handle:
            for source_line, archive_line in zip_longest(source_handle, archive_handle):
                if source_line is None or archive_line is None:
                    status = "line_count_mismatch"
                    break
                compared_line_count += 1
                bytes_read += len(source_line) + len(archive_line)
                if source_line == archive_line:
                    continue
                try:
                    source_record = json.loads(source_line.decode("utf-8"))
                    archive_record = json.loads(archive_line.decode("utf-8"))
                except Exception:
                    status = "json_parse_failed"
                    break
                if not _metadata_only_line_difference(source_record, archive_record):
                    status = "non_metadata_difference"
                    break
                changed_line_count += 1
            else:
                status = "metadata_only" if changed_line_count else "identical"
    except OSError:
        status = "read_error"

    identities_stable = (
        source_identity == _file_identity(source)
        and archive_identity == _file_identity(archive)
    )
    matched = status == "metadata_only" and identities_stable
    if not identities_stable:
        status = "identity_changed_during_probe"
    result = {
        **base,
        "matched": matched,
        "status": status,
        "metadata_only_fields": ["payload.model_provider"] if matched else [],
        "compared_line_count": compared_line_count,
        "changed_line_count": changed_line_count,
        "bytes_read": bytes_read,
        "cache_hit": False,
    }
    if identities_stable:
        _METADATA_DIVERGENCE_CACHE[cache_key] = dict(result)
        _METADATA_DIVERGENCE_CACHE.move_to_end(cache_key)
        while len(_METADATA_DIVERGENCE_CACHE) > METADATA_DIVERGENCE_CACHE_LIMIT:
            _METADATA_DIVERGENCE_CACHE.popitem(last=False)
    return result


def _raw_sync_item(artifact: dict, scan_mode: str = "full") -> dict:
    scan_mode = "fast" if str(scan_mode or "").lower() in {"fast", "stat", "quick"} else "full"
    src = Path(artifact.get("source_path", "")).expanduser()
    src_stat = None
    observed_at_ms = int(time.time() * 1000)
    try:
        src_stat = src.stat()
        source_size = src_stat.st_size
        source_mtime = datetime.fromtimestamp(src_stat.st_mtime, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    except OSError:
        src_stat = None
        source_size = 0
        source_mtime = artifact.get("mtime", "")
    base_dest = _raw_dest_for_artifact(artifact)
    if scan_mode == "fast":
        selection = select_archive_segment_metadata_only(
            base_dest,
            src_stat.st_ino if src_stat is not None else None,
        )
        selected_dest = Path(selection["archive_path"])
        generation_blockers = [selection] if selection.get("generation_descriptor_incomplete") else []
    else:
        selection = {
            "selection_status": "full_connector_selection",
            "selection_proven_by_metadata": True,
            "source_inode_match": True,
            "body_read_performed": True,
        }
        generation_chain = archive_generation_chain(base_dest)
        generation_blockers = [
            item
            for item in generation_chain
            if item.get("pending_present")
            or (item.get("descriptor_present") and not item.get("descriptor_valid"))
        ]
        selected_dest = (
            select_archive_segment(base_dest, src_stat.st_ino, src)
            if src_stat is not None
            else latest_archive_segment(base_dest)
        )
    retained_dest = latest_archive_segment(base_dest)
    metadata_divergence = {
        "matched": False,
        "status": "not_applicable",
        "metadata_only_fields": [],
    }
    dest = selected_dest
    generation_descriptor = load_generation_descriptor(dest)
    generation_descriptor_incomplete = bool(generation_blockers)
    if generation_descriptor_incomplete:
        dest = Path(str(generation_blockers[-1].get("archive_path") or selected_dest))
        generation_descriptor = {}
    if (
        scan_mode == "full"
        and src_stat is not None
        and not selected_dest.exists()
        and retained_dest.exists()
    ):
        metadata_divergence = _metadata_only_divergence_probe(src, retained_dest)
        if metadata_divergence.get("matched"):
            dest = retained_dest
            generation_descriptor = load_generation_descriptor(dest)
    dest_stat = None
    try:
        dest_stat = dest.stat()
        physical_raw_size = dest_stat.st_size
        raw_mtime = datetime.fromtimestamp(dest_stat.st_mtime, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    except OSError:
        physical_raw_size = 0
        raw_mtime = ""
    source_base_offset = int(generation_descriptor.get("source_base_offset", 0) or 0)
    raw_covered_source_bytes = (
        source_base_offset + physical_raw_size
        if generation_descriptor
        else physical_raw_size
    )
    raw_size = raw_covered_source_bytes
    missing = not dest.exists()
    overrun = bool(dest.exists()) and raw_size > source_size
    stale = bool(dest.exists()) and raw_size < source_size
    source_regression = overrun
    source_mtime_ms = _stat_mtime_ms(src_stat)
    raw_mtime_ms = _stat_mtime_ms(dest_stat)
    raw_mtime_gap_ms = max(0, source_mtime_ms - raw_mtime_ms) if stale and source_mtime_ms and raw_mtime_ms else 0
    lag_ms = max(0, observed_at_ms - source_mtime_ms) if stale and source_mtime_ms else 0
    raw_size_delta_bytes = abs(source_size - raw_size)
    lag_bytes = max(0, source_size - raw_size)
    generation_active = bool(generation_descriptor)
    source_divergence = bool(metadata_divergence.get("matched"))
    metadata_only_divergence = bool(metadata_divergence.get("matched"))
    selection_meta = selection.get("metadata") if isinstance(selection.get("metadata"), dict) else {}
    try:
        metadata_offset = int(selection_meta.get("file_offset", -1))
        metadata_mtime = float(selection_meta.get("source_mtime", -1.0))
    except (TypeError, ValueError):
        metadata_offset = -1
        metadata_mtime = -1.0
    metadata_continuity_proven = bool(
        scan_mode == "full"
        or generation_active
        or (
            src_stat is not None
            and selection.get("source_inode_match")
            and metadata_offset == source_size == raw_covered_source_bytes
            and metadata_mtime == float(src_stat.st_mtime)
        )
    )
    continuity_not_measured = bool(
        scan_mode == "fast"
        and not missing
        and not generation_descriptor_incomplete
        and not generation_active
        and not metadata_continuity_proven
    )
    monotonic_probe_ok: bool | None = None if continuity_not_measured else not generation_descriptor_incomplete
    monotonic_status = (
        "raw_generation_descriptor_incomplete"
        if generation_descriptor_incomplete
        else "raw_continuity_not_measured_fast"
        if continuity_not_measured
        else "source_divergence_metadata_only_raw_retained"
        if metadata_only_divergence
        else "source_regression_raw_retained" if source_regression else ""
    )
    recommend_after_ms = max(DEFAULT_BACKFILL_RECOMMEND_AFTER_MS, raw_lag_sla_milliseconds() * 5)
    if generation_descriptor_incomplete:
        source_divergence = True
        metadata_only_divergence = False
    elif generation_active:
        source_divergence = True
        monotonic_status = "source_divergence_generation_active"
        lag_ms = max(0, observed_at_ms - source_mtime_ms) if stale and source_mtime_ms else 0
        lag_bytes = max(0, source_size - raw_covered_source_bytes)
    elif metadata_only_divergence:
        stale = False
        overrun = False
        source_regression = False
        lag_ms = 0
        lag_bytes = 0
    elif scan_mode == "full" and raw_size and cached_divergence_witness_visible(src, dest, raw_size):
        source_divergence = True
        monotonic_status = "source_divergence_raw_retained"
    elif scan_mode == "full" and stale and lag_ms > recommend_after_ms and src_stat is not None:
        try:
            monotonic_probe = append_source_file(
                src,
                base_dest,
                dry_run=True,
                source_inode=src_stat.st_ino,
                continue_on_divergence=True,
            )
        except OSError:
            monotonic_probe_ok = False
            monotonic_status = "raw_monotonic_probe_incomplete"
        else:
            monotonic_status = str(monotonic_probe.get("status") or "")
            source_divergence = bool(monotonic_probe.get("source_divergence"))
            if source_divergence:
                metadata_divergence = _metadata_only_divergence_probe(src, dest)
                metadata_only_divergence = bool(metadata_divergence.get("matched"))
                if metadata_only_divergence:
                    monotonic_status = "source_divergence_metadata_only_raw_retained"
                    stale = False
                    lag_ms = 0
                    lag_bytes = 0
    return {
        "session_id": artifact.get("session_id", ""),
        "project_id": artifact.get("project_id", ""),
        "thread_name": artifact.get("thread_name", ""),
        "source_mtime": source_mtime,
        "source_mtime_ms": source_mtime_ms,
        "source_mtime_precise": _epoch_ms_to_iso(source_mtime_ms),
        "source_size_bytes": source_size,
        "raw_mtime": raw_mtime,
        "raw_mtime_ms": raw_mtime_ms,
        "raw_mtime_precise": _epoch_ms_to_iso(raw_mtime_ms),
        "raw_size_bytes": raw_size,
        "raw_physical_size_bytes": physical_raw_size,
        "raw_covered_source_bytes": raw_covered_source_bytes,
        "raw_source_base_offset": source_base_offset,
        "raw_path": str(dest),
        "raw_exists": dest.exists(),
        "raw_missing": missing,
        "raw_stale": stale,
        "raw_overrun": overrun,
        "raw_rebuild_recommended": False,
        "raw_source_regression": source_regression,
        "raw_source_divergence": source_divergence,
        "raw_metadata_only_divergence": metadata_only_divergence,
        "raw_divergence_generation_active": generation_active,
        "raw_generation_descriptor_incomplete": generation_descriptor_incomplete,
        "raw_generation": int(generation_descriptor.get("generation", 0) or 0),
        "raw_generation_predecessor": str(generation_descriptor.get("predecessor") or ""),
        "metadata_only_fields": list(metadata_divergence.get("metadata_only_fields") or []),
        "metadata_divergence_probe": metadata_divergence,
        "raw_monotonic_status": monotonic_status,
        "raw_monotonic_probe_ok": monotonic_probe_ok,
        "raw_continuity_not_measured": continuity_not_measured,
        "raw_continuity_evidence": str(selection.get("selection_status") or ""),
        "raw_sync_scan_mode": scan_mode,
        "raw_body_read_performed": bool(selection.get("body_read_performed")),
        "raw_archive_lag_bytes": lag_bytes,
        "raw_size_delta_bytes": raw_size_delta_bytes,
        "raw_archive_lag_milliseconds": lag_ms,
        "backfill_recommend_after_milliseconds": recommend_after_ms,
        "raw_source_mtime_gap_milliseconds": raw_mtime_gap_ms,
        "lag_observed_at_ms": observed_at_ms,
        "lag_observed_at": _epoch_ms_to_iso(observed_at_ms),
        "source_path_label": _public_path_label(str(src)),
        "raw_path_label": _public_path_label(str(dest)),
    }


def raw_sync_snapshot(limit: int = 20) -> dict:
    """Compare Codex source records with Time Library raw archives without writing.

    This is deliberately independent from Codex Skill/MCP state. Skill/MCP is a
    consumption path; local session capture reads the Codex files directly.
    """
    artifacts = discover_sessions(limit=limit)
    items = [_raw_sync_item(artifact) for artifact in artifacts]
    missing_or_stale = [
        item for item in items
        if (item.get("raw_missing") or item.get("raw_stale"))
        and not item.get("raw_source_regression")
        and (
            not item.get("raw_source_divergence")
            or item.get("raw_divergence_generation_active")
        )
    ]
    regression_items = [item for item in items if item.get("raw_source_regression")]
    metadata_only_divergence_items = [
        item for item in items if item.get("raw_metadata_only_divergence")
    ]
    divergence_items = [
        item for item in items
        if item.get("raw_source_divergence")
        and not item.get("raw_metadata_only_divergence")
        and not item.get("raw_divergence_generation_active")
    ]
    generation_items = [
        item for item in items if item.get("raw_divergence_generation_active")
    ]
    missing_items = [item for item in items if item.get("raw_missing")]
    lagging_items = [item for item in items if item.get("raw_stale")]
    max_lag_bytes = max((int(item.get("raw_archive_lag_bytes", 0) or 0) for item in lagging_items), default=0)
    max_lag_ms = max((int(item.get("raw_archive_lag_milliseconds", 0) or 0) for item in lagging_items), default=0)
    total_lag_bytes = sum(int(item.get("raw_archive_lag_bytes", 0) or 0) for item in lagging_items)
    sla_ms = raw_lag_sla_milliseconds()
    sla_breaches = [
        item for item in lagging_items
        if not item.get("raw_source_regression")
        and (
            not item.get("raw_source_divergence")
            or item.get("raw_divergence_generation_active")
        )
        and item.get("raw_monotonic_probe_ok", True)
        and (
            int(item.get("raw_archive_lag_milliseconds", 0) or 0) > sla_ms
            or (sla_ms == 0 and int(item.get("raw_archive_lag_bytes", 0) or 0) > 0)
        )
    ]
    probe_incomplete_items = [
        item for item in items
        if item.get("raw_monotonic_probe_ok") is False
    ]
    catch_up_actionable_items = [
        item for item in missing_or_stale
        if item.get("raw_monotonic_probe_ok", True)
    ]
    catching_up_items = [
        item for item in lagging_items
        if not item.get("raw_source_regression")
        and (
            not item.get("raw_source_divergence")
            or item.get("raw_divergence_generation_active")
        )
        and item.get("raw_monotonic_probe_ok", True)
        and item not in sla_breaches
    ]
    source_epochs = [_iso_to_epoch(item.get("source_mtime", "")) for item in items]
    raw_epochs = [_iso_to_epoch(item.get("raw_mtime", "")) for item in items if item.get("raw_mtime")]
    latest_source_epoch = max(source_epochs) if source_epochs else 0.0
    latest_raw_epoch = max(raw_epochs) if raw_epochs else 0.0
    latest_source_mtime = datetime.fromtimestamp(latest_source_epoch, UTC).strftime("%Y-%m-%dT%H:%M:%SZ") if latest_source_epoch else ""
    latest_raw_mtime = datetime.fromtimestamp(latest_raw_epoch, UTC).strftime("%Y-%m-%dT%H:%M:%SZ") if latest_raw_epoch else ""
    lag_seconds = (
        int(max(0, latest_source_epoch - latest_raw_epoch))
        if latest_source_epoch and latest_raw_epoch
        else None
    )
    if not codex_sessions_root().exists():
        status_text = "source_unreachable"
    elif not artifacts:
        status_text = "no_source_records"
    elif missing_items:
        status_text = "raw_missing"
    elif regression_items:
        status_text = "source_regression_raw_retained"
    elif probe_incomplete_items:
        status_text = "raw_monotonic_probe_incomplete"
    elif divergence_items:
        status_text = "source_divergence_raw_retained"
    elif sla_breaches:
        status_text = "raw_lagging_sla_breach"
    elif missing_or_stale:
        status_text = "raw_catching_up"
    elif metadata_only_divergence_items:
        status_text = "raw_current_metadata_divergence_retained"
    elif generation_items:
        status_text = "raw_current_divergence_generation_active"
    else:
        status_text = "raw_current"
    return {
        "ok": status_text != "source_unreachable",
        "read_only": True,
        "source_system": SOURCE_SYSTEM,
        "artifact_type": NATIVE_ARTIFACT_FORMAT,
        "status": status_text,
        "independent_of_mcp": True,
        "consumer_connection_required": False,
        "source_root_reachable": codex_sessions_root().exists(),
        "source_count_sample": len(artifacts),
        "latest_source_mtime": latest_source_mtime,
        "latest_raw_mtime": latest_raw_mtime,
        "raw_archive_lag_seconds": lag_seconds,
        "raw_archive_max_lag_bytes": max_lag_bytes,
        "raw_archive_total_lag_bytes": total_lag_bytes,
        "raw_archive_max_lag_milliseconds": max_lag_ms,
        "raw_lag_sla_milliseconds": sla_ms,
        "raw_lag_sla_breach_count": len(sla_breaches),
        "raw_missing_count": len(missing_items),
        "raw_overrun_count": len(regression_items),
        "raw_source_regression_count": len(regression_items),
        "raw_source_divergence_count": len(divergence_items),
        "raw_metadata_only_divergence_count": len(metadata_only_divergence_items),
        "raw_divergence_generation_active_count": len(generation_items),
        "raw_monotonic_probe_incomplete_count": len(probe_incomplete_items),
        "raw_rebuild_recommended_count": 0,
        "raw_catching_up_count": len(catching_up_items),
        "raw_catch_up_actionable_count": len(catch_up_actionable_items),
        "missing_or_stale_count": len(missing_or_stale) + len(regression_items) + len(divergence_items),
        "latest_missing_or_stale": (regression_items + divergence_items + missing_or_stale)[:5],
        "latest_metadata_only_divergence": metadata_only_divergence_items[:5],
    }


def catch_up_latest_sessions(
    *,
    limit: Optional[int] = None,
    budget_ms: Optional[int] = None,
    max_passes: Optional[int] = None,
) -> dict:
    """Bounded chase loop for the most recent Codex JSONL records."""
    scan_limit = limit if limit is not None else watch_scan_limit()
    budget = tail_catchup_budget_milliseconds() if budget_ms is None else max(0, int(budget_ms))
    passes_cap = tail_catchup_max_passes() if max_passes is None else max(1, int(max_passes))
    deadline = time.monotonic() + (budget / 1000.0)
    passes = 0
    changed = 0
    items: list[dict[str, Any]] = []
    final_snapshot: dict[str, Any] = {}

    while passes < passes_cap:
        passes += 1
        result = scan_sessions(dry_run=False, limit=scan_limit, public=False)
        changed += int(result.get("changed", 0) or 0)
        items.extend(result.get("items", []))
        final_snapshot = raw_sync_snapshot(limit=scan_limit)
        actionable = final_snapshot.get("raw_catch_up_actionable_count")
        if actionable is None:
            terminal = sum(int(final_snapshot.get(key, 0) or 0) for key in (
                "raw_source_regression_count",
                "raw_source_divergence_count",
                "raw_monotonic_probe_incomplete_count",
            ))
            actionable = max(0, int(final_snapshot.get("missing_or_stale_count", 0) or 0) - terminal)
        if int(actionable or 0) == 0:
            break
        if time.monotonic() >= deadline:
            break
        time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))

    return {
        "ok": final_snapshot.get("missing_or_stale_count", 0) == 0 if final_snapshot else True,
        "source_system": SOURCE_SYSTEM,
        "limit": scan_limit,
        "budget_ms": budget,
        "max_passes": passes_cap,
        "passes": passes,
        "changed": changed,
        "items": items,
        "raw_sync": final_snapshot,
    }


def load_checkpoint() -> dict:
    path = checkpoint_file()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return {}


def save_checkpoint(data: dict) -> None:
    path = checkpoint_file()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.{time.monotonic_ns()}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        for attempt in range(6):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                if attempt == 5:
                    raise
                time.sleep(0.05 * (attempt + 1))
    finally:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass


def _checkpoint_key(source_path: str) -> str:
    return f"{SOURCE_SYSTEM}:{os.path.abspath(os.path.expanduser(source_path))}"


def _raw_dest_for_artifact(artifact: dict) -> Path:
    project_id = _safe_segment(artifact.get("canonical_window_id") or artifact.get("project_id"), "project")
    session_id = _safe_segment(artifact.get("session_id"), "session")
    root = memory_root()
    hinted = Path(str(artifact.get("raw_archive_path_hint") or "")).expanduser()
    if str(hinted) not in {"", "."} and hinted.is_file():
        try:
            hinted.resolve().relative_to(Path(root).resolve())
        except (OSError, ValueError):
            pass
        else:
            return hinted
    preferred = preferred_raw_archive_path(
        root,
        computer_name=artifact.get("computer_name") or node_id(),
        source_system=SOURCE_SYSTEM,
        native_format=artifact.get("artifact_type") or NATIVE_ARTIFACT_FORMAT,
        native_scope=project_id,
        session_id=session_id,
    )
    return existing_or_preferred_raw_archive_path(root, preferred)


def _generation_meta(dest: Path) -> dict[str, Any]:
    descriptor = load_generation_descriptor(dest)
    return {
        "raw_generation_contract": descriptor.get("contract", ""),
        "raw_generation": int(descriptor.get("generation", 0) or 0),
        "source_base_offset": int(descriptor.get("source_base_offset", 0) or 0),
        "raw_generation_predecessor": str(descriptor.get("predecessor") or ""),
        "raw_generation_reason": str(descriptor.get("reason") or ""),
        "raw_generation_descriptor_path": str(Path(str(dest) + ".generation.json")) if descriptor else "",
    }


def _write_meta(dest: Path, artifact: dict, src_stat: os.stat_result, offset: int, raw_order: int) -> None:
    generation_meta = _generation_meta(dest)
    meta = {
        "source_system": SOURCE_SYSTEM,
        "source_path": artifact.get("source_path", ""),
        "source_inode": src_stat.st_ino,
        "source_mtime": src_stat.st_mtime,
        "source_checksum": _file_hash(Path(artifact["source_path"])),
        "file_offset": offset,
        "raw_order": raw_order,
        "archived_to": str(dest),
        "native_artifact_format": artifact.get("artifact_type") or NATIVE_ARTIFACT_FORMAT,
        "raw_archive_layout": "computer_first",
        "session_id": artifact.get("session_id", ""),
        "project_id": artifact.get("project_id", ""),
        "project_root": artifact.get("project_root", ""),
        "thread_name": artifact.get("thread_name", ""),
        "main_river_storage": "canonical_dialogue",
        "forensic_runtime_storage": "full_raw_archive_plus_manifest",
        "canonical_dialogue_path": str(dest) + ".canonical_dialogue.jsonl",
        "forensic_runtime_manifest_path": str(dest) + ".forensic_runtime.json",
        **generation_meta,
        "last_update": ts(),
    }
    with open(str(dest) + ".meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


def _meta_needs_update(dest: Path, artifact: dict, src_stat: os.stat_result, offset: int, raw_order: int) -> bool:
    meta_path = Path(str(dest) + ".meta.json")
    if not meta_path.exists():
        return True
    try:
        existing = json.loads(meta_path.read_text(encoding="utf-8-sig"))
    except Exception:
        return True
    wanted = {
        "source_system": SOURCE_SYSTEM,
        "source_path": artifact.get("source_path", ""),
        "source_inode": src_stat.st_ino,
        "source_mtime": src_stat.st_mtime,
        "file_offset": offset,
        "raw_order": raw_order,
        "archived_to": str(dest),
        "native_artifact_format": artifact.get("artifact_type") or NATIVE_ARTIFACT_FORMAT,
        "raw_archive_layout": "computer_first",
        "session_id": artifact.get("session_id", ""),
        "project_id": artifact.get("project_id", ""),
        "project_root": artifact.get("project_root", ""),
        "thread_name": artifact.get("thread_name", ""),
        "main_river_storage": "canonical_dialogue",
        "forensic_runtime_storage": "full_raw_archive_plus_manifest",
        "canonical_dialogue_path": str(dest) + ".canonical_dialogue.jsonl",
        "forensic_runtime_manifest_path": str(dest) + ".forensic_runtime.json",
        **_generation_meta(dest),
    }
    for key, value in wanted.items():
        if existing.get(key) != value:
            return True
    return False


def _register_current_window_for_artifact(artifact: dict, dest: str) -> dict:
    session_id = str(artifact.get("session_id") or "").strip()
    project_id = str(artifact.get("project_id") or artifact.get("canonical_window_id") or "").strip()
    return register_current_window(
        source_system=SOURCE_SYSTEM,
        consumer=SOURCE_SYSTEM,
        canonical_window_id=session_id or project_id,
        session_id=session_id,
        native_window_id=str(artifact.get("native_thread_id") or session_id),
        title=str(artifact.get("thread_name") or ""),
        source_path=str(dest or ""),
        binding_source="codex_session_jsonl_incremental_capture",
        confidence="observed_codex_session_change",
        metadata={
            "project_id": project_id,
            "project_root": artifact.get("project_root", ""),
            "source_refs_canonical_window_id": artifact.get("canonical_window_id", ""),
            "native_artifact_format": artifact.get("artifact_type") or NATIVE_ARTIFACT_FORMAT,
            "raw_archive_layout": "computer_first",
            "thread_index_source": artifact.get("thread_index_source", ""),
            "codex_source": artifact.get("codex_source", ""),
            "model_provider": artifact.get("model_provider", ""),
        },
    )


def archive_session_incremental(source_path: str, dry_run: bool = False, artifact: Optional[dict] = None) -> tuple[str, str]:
    src = Path(source_path).expanduser()
    if artifact is None:
        artifact = artifact_from_path(src)
    base_dest = _raw_dest_for_artifact(artifact)

    try:
        src_stat = src.stat()
    except OSError:
        report = append_source_file(src, base_dest, dry_run=dry_run, compute_sha256=False)
        if report.get("source_regression"):
            return str(report.get("archive_path") or base_dest), (
                "source_regression_raw_retained("
                f"source=missing,raw={report.get('archive_size_before', 0)})"
            )
        return str(base_dest), "error: cannot stat source"

    checkpoint = load_checkpoint()
    key = _checkpoint_key(str(src))
    prior = checkpoint.get(key, {})
    raw_order = max(1, int(prior.get("raw_order", 1) or 1))
    report = append_source_file(
        src,
        base_dest,
        dry_run=dry_run,
        source_inode=src_stat.st_ino,
        compute_sha256=False,
        continue_on_divergence=True,
    )
    dest = Path(str(report.get("archive_path") or base_dest))
    if (
        prior
        and int(prior.get("source_inode", 0) or 0) not in {0, src_stat.st_ino}
        and not report.get("source_identity_rebound")
    ):
        raw_order += 1
    report_status = str(report.get("status") or "")
    if report.get("generation_started"):
        raw_order = max(raw_order + 1, int(report.get("generation", 0) or 0) + 1)

    generation_started = bool(report.get("generation_started"))
    generation_active = bool(report.get("generation_active") or generation_started)
    if report_status == "source_divergence_generation_fail_closed":
        return str(dest), (
            "source_divergence_generation_fail_closed("
            f"reason={report.get('generation_failure', 'unknown')})"
        )
    if report.get("source_regression"):
        return str(dest), (
            "source_regression_raw_retained("
            f"source={report.get('source_size', 0)},raw={report.get('archive_size_before', 0)})"
        )
    if report.get("source_divergence") and not generation_active:
        return str(dest), (
            "source_divergence_raw_retained("
            f"source={report.get('source_size', 0)},raw={report.get('archive_size_before', 0)})"
        )
    if report_status == "waiting_for_complete_jsonl_line":
        return str(dest), (
            "generation_waiting_for_complete_jsonl_line("
            f"covered={report.get('source_covered_bytes', 0)},source={report.get('source_size', 0)})"
        )
    if dry_run:
        return str(dest), (
            f"dry_run_monotonic(status={report_status},"
            f"raw={report.get('archive_size_before', 0)},source={src_stat.st_size})"
        )

    covered_offset = int(report.get("source_covered_bytes", src_stat.st_size) or 0)
    checkpoint[key] = {
        "offset": covered_offset,
        "archived_to": str(dest),
        "source_inode": src_stat.st_ino,
        "source_size": src_stat.st_size,
        "source_mtime": src_stat.st_mtime,
        "raw_order": raw_order,
        "generation": int(report.get("generation") or load_generation_descriptor(dest).get("generation", 0) or 0),
        "source_base_offset": int(report.get("source_base_offset") or load_generation_descriptor(dest).get("source_base_offset", 0) or 0),
        "predecessor": str(report.get("predecessor") or load_generation_descriptor(dest).get("predecessor") or ""),
        "source_system": SOURCE_SYSTEM,
        "last_update": ts(),
        "raw_archive_contract": report.get("contract", ""),
    }
    save_checkpoint(checkpoint)

    dialogue_path = canonical_dialogue_sidecar_path(dest)
    forensic_path = forensic_runtime_manifest_path(dest)
    if (
        report_status in {"created", "appended", "source_divergence_generation_started", "appended_generation"}
        or not dialogue_path.exists()
        or not forensic_path.exists()
    ):
        materialize_canonical_dialogue(
            dest,
            source_system=SOURCE_SYSTEM,
            session_id=str(artifact.get("session_id") or ""),
            canonical_window_id=str(artifact.get("canonical_window_id") or ""),
            native_artifact_format=artifact.get("artifact_type") or NATIVE_ARTIFACT_FORMAT,
            reset=report_status in {"created", "source_divergence_generation_started"},
            raw_order=raw_order,
            native_source_path=str(src),
            source_base_offset=int(report.get("source_base_offset") or load_generation_descriptor(dest).get("source_base_offset", 0) or 0),
            generation=int(report.get("generation") or load_generation_descriptor(dest).get("generation", 0) or 0),
            predecessor=str(report.get("predecessor") or load_generation_descriptor(dest).get("predecessor") or ""),
        )
    if report_status == "up_to_date":
        if _meta_needs_update(dest, artifact, src_stat, src_stat.st_size, raw_order):
            _write_meta(dest, artifact, src_stat, src_stat.st_size, raw_order)
            return str(dest), f"metadata_updated(offset={src_stat.st_size})"
        if not prior:
            return str(dest), f"up_to_date(offset={src_stat.st_size}, checkpoint_recovered)"
        return str(dest), f"up_to_date(offset={src_stat.st_size})"

    _write_meta(dest, artifact, src_stat, covered_offset, raw_order)
    lines_written = int(report.get("lines_appended") or 0)
    bytes_written = int(report.get("bytes_appended") or 0)
    if report_status == "created":
        return str(dest), f"archived({lines_written} lines, {bytes_written} bytes)"
    if report_status == "source_divergence_generation_started":
        return str(dest), (
            f"generation_started(generation={report.get('generation', 0)},"
            f"base={report.get('source_base_offset', 0)},bytes={bytes_written})"
        )
    if report_status == "appended_generation":
        return str(dest), (
            f"appended_generation({lines_written} lines, {bytes_written} bytes,"
            f"{report.get('archive_size_before', 0)}->{report.get('archive_size_after', 0)})"
        )
    return str(dest), (
        f"appended({lines_written} lines, {bytes_written} bytes, "
        f"{report.get('archive_size_before', 0)}->{report.get('archive_size_after', 0)})"
    )


def scan_sessions(dry_run: bool = False, limit: int = 0, public: bool = False) -> dict:
    artifacts = discover_sessions(limit=limit)
    items = []
    changed = 0
    would_change = 0
    window_bindings = []
    window_binding_skipped = 0
    current_window_registered = False
    for artifact in artifacts:
        dest, status = archive_session_incremental(artifact["source_path"], dry_run=dry_run, artifact=artifact)
        changed_status = status.startswith(("archived", "appended", "generation_started", "rotation", "rebuilt", "metadata_updated"))
        if dry_run and status.startswith("dry_run"):
            would_change += 1
        elif changed_status:
            changed += 1
            if not current_window_registered:
                binding = _register_current_window_for_artifact(artifact, dest)
                if binding.get("ok"):
                    window_bindings.append(binding)
                    current_window_registered = True
                else:
                    window_binding_skipped += 1
        items.append({
            "source_path": _public_path_label(artifact["source_path"]) if public else artifact["source_path"],
            "dest": _public_path_label(dest) if public else dest,
            "status": status,
            "session_id": artifact.get("session_id", ""),
            "canonical_window_id": artifact.get("canonical_window_id", ""),
            "project_root": _public_path_label(artifact.get("project_root", "")) if public else artifact.get("project_root", ""),
            "thread_name": artifact.get("thread_name", ""),
        })
    return {
        "ok": True,
        "source_system": SOURCE_SYSTEM,
        "sessions_root": str(codex_sessions_root()),
        "discovered": len(artifacts),
        "changed": changed,
        "would_change": would_change,
        "window_bindings_registered": len(window_bindings),
        "window_bindings": window_bindings,
        "window_binding_skipped": window_binding_skipped,
        "dry_run": dry_run,
        "items": items,
    }


def status() -> dict:
    scan_limit = status_scan_limit()
    artifacts = discover_sessions(limit=scan_limit)
    state_index = _load_state_thread_index()
    interval_ms = watcher_interval_milliseconds()
    raw_sync = raw_sync_snapshot(limit=scan_limit)
    return {
        "ok": True,
        "source_system": SOURCE_SYSTEM,
        "sessions_root": _public_path_label(str(codex_sessions_root())),
        "session_index": _public_path_label(str(codex_session_index_path())),
        "state_thread_index": _public_path_label(str(codex_state_db_path())),
        "state_thread_index_reachable": bool(state_index.get("read_ok")),
        "state_thread_count": len(state_index.get("by_id", {})) if isinstance(state_index.get("by_id"), dict) else 0,
        "reachable": codex_sessions_root().exists(),
        "artifact_count_sample": len(artifacts),
        "latest": [public_artifact(item) for item in artifacts[:5]],
        "read_only": True,
        "source_kind": "codex_official_threads_and_session_records",
        "collector_status": "continuous_incremental",
        "capture_independent_of_mcp": True,
        "consumer_connection_required": False,
        "raw_sync": raw_sync,
        "event_driven_preferred": True,
        "poll_interval_milliseconds": interval_ms,
        "poll_interval_seconds": interval_ms / 1000.0,
        "target_latency_milliseconds": interval_ms,
        "millisecond_level": interval_ms < 1000,
        "watch_scan_limit": watch_scan_limit(),
        "tail_catchup_budget_milliseconds": tail_catchup_budget_milliseconds(),
        "tail_catchup_max_passes": tail_catchup_max_passes(),
        "raw_lag_sla_milliseconds": raw_lag_sla_milliseconds(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Codex local session connector")
    parser.add_argument("--discover", action="store_true")
    parser.add_argument("--scan", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--catch-up", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--budget-ms", type=int, default=None)
    parser.add_argument("--max-passes", type=int, default=None)
    args = parser.parse_args()
    if args.discover:
        print(json.dumps(discover_sessions(limit=args.limit), ensure_ascii=False, indent=2))
    elif args.catch_up:
        print(json.dumps(
            catch_up_latest_sessions(
                limit=args.limit or None,
                budget_ms=args.budget_ms,
                max_passes=args.max_passes,
            ),
            ensure_ascii=False,
            indent=2,
        ))
    elif args.scan:
        print(json.dumps(scan_sessions(dry_run=args.dry_run, limit=args.limit), ensure_ascii=False, indent=2))
    else:
        print(json.dumps(status(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
