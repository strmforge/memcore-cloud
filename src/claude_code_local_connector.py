#!/usr/bin/env python3
"""
Claude Code CLI local source connector.

Read-only source side:
- discovers Claude Code session JSONL files under ~/.claude/projects
- links Claude Desktop local-agent metadata under the Claude app support
  claude-code-sessions directory when present
- keeps user-installed PATH CLI, Claude Desktop, and Desktop-managed local-agent
  runtime attribution separate

Write side:
- archives an independent raw copy into
  memory/<node>/claude_code_cli/claude_code_session_jsonl/<project>/<session>.jsonl
- uses the shared memcore checkpoint for incremental appends
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from config_loader import checkpoint_file, memory_root, node_id
try:
    from src.raw_archive_layout import existing_or_preferred_raw_archive_path, preferred_raw_archive_path
except ImportError:
    from raw_archive_layout import existing_or_preferred_raw_archive_path, preferred_raw_archive_path
try:
    from src.raw_archive_monotonic import (
        append_source_file,
        latest_archive_segment,
        load_generation_descriptor,
        select_archive_segment,
        select_archive_segment_metadata_only,
    )
except ImportError:
    from raw_archive_monotonic import (
        append_source_file,
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
SOURCE_SYSTEM = "claude_code_cli"
NATIVE_ARTIFACT_FORMAT = "claude_code_session_jsonl"
RAW_ARTIFACT_ID_SCHEMA = "claude_code_raw_artifact_id.v2"
SESSION_GLOB = "*.jsonl"
DEFAULT_SYNC_INTERVAL_MS = 250
MIN_SYNC_INTERVAL_MS = 50
MAX_SYNC_INTERVAL_MS = 3_600_000
SESSION_SUMMARY_HEAD_LINES = 20
SESSION_SUMMARY_TAIL_LINES = 80
DESKTOP_SESSION_GLOB = "local_*.json"
DESKTOP_INSTALLER_INCLUDES_CLI = False
CLI_INSTALLATION_BOUNDARY = "claude_cli_is_independent_and_may_be_installed_after_claude_desktop"
DESKTOP_CLI_RELATIONSHIP = "user_installed_cli_independent_but_desktop_may_manage_local_agent_runtime"
DESKTOP_MANAGED_RUNTIME_CONSUMER = "claude_desktop_managed_claude_code_runtime"
DESKTOP_MANAGED_RUNTIME_OWNER = "claude_desktop"
DESKTOP_MANAGED_RUNTIME_POLICY = "desktop_managed_runtime_is_distinct_from_user_installed_path_cli"
DESKTOP_METADATA_POLICY = "metadata_only_links_desktop_session_to_claude_code_jsonl_body"
BODY_STORAGE_OWNER = "claude_code_session_store"
DESKTOP_ENTRYPOINT_VALUES = {"claude-desktop", "claude_desktop", "claudedesktop"}
DESKTOP_ENTRYPOINT_ORIGIN = "claude_desktop_entrypoint_claude_code_session"
DESKTOP_ENTRYPOINT_POLICY = "entrypoint_marks_claude_desktop_shell_but_body_is_claude_code_jsonl"
COVERAGE_BOUNDARY = "captures_claude_code_session_jsonl_records_including_claude_desktop_entrypoint_and_desktop_managed_local_agent_metadata_not_ordinary_desktop_browser_store_history"
LEGACY_LOCAL_RELAY_DASHED = "cc" + "-switch"


def ts() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _local_relay_settings_paths() -> list[Path]:
    for name in ("LOCAL_RELAY_SETTINGS_PATH", "CC" + "_SWITCH_SETTINGS_PATH"):
        explicit = os.environ.get(name, "").strip()
        if explicit:
            return [Path(explicit).expanduser()]
    roots: list[Path] = []
    for name in ("LOCAL_RELAY_HOME", "LOCAL_RELAY_ROOT", "CC" + "_SWITCH_HOME", "CC" + "SWITCH_HOME"):
        value = os.environ.get(name, "").strip()
        if value:
            roots.append(Path(value).expanduser())
    roots.append(Path.home() / ".local-relay")
    roots.append(Path.home() / f".{LEGACY_LOCAL_RELAY_DASHED}")
    paths: list[Path] = []
    for root in roots:
        path = root if root.name == "settings.json" else root / "settings.json"
        if path not in paths:
            paths.append(path)
    return paths


def _local_relay_claude_config_dir() -> Path | None:
    for path in _local_relay_settings_paths():
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        value = data.get("claudeConfigDir")
        if value is None:
            value = data.get("claude_config_dir")
        text = str(value or "").strip()
        if text:
            return Path(text).expanduser()
    return None


def claude_code_config_dir() -> Path:
    for name in ("CLAUDE_CODE_CONFIG_DIR", "CLAUDE_CONFIG_DIR"):
        value = os.environ.get(name, "").strip()
        if value:
            return Path(value).expanduser()
    local_relay_dir = _local_relay_claude_config_dir()
    if local_relay_dir:
        return local_relay_dir
    return Path.home() / ".claude"


def claude_code_projects_root() -> Path:
    for name in ("CLAUDE_CODE_PROJECTS_DIR", "CLAUDE_CODE_SESSIONS_DIR", "CLAUDE_PROJECTS_DIR"):
        value = os.environ.get(name, "").strip()
        if value:
            return Path(value).expanduser()
    config_dir = claude_code_config_dir()
    if config_dir.name == "projects":
        return config_dir
    return config_dir / "projects"


def claude_code_config_dir_source() -> str:
    for name in ("CLAUDE_CODE_PROJECTS_DIR", "CLAUDE_CODE_SESSIONS_DIR", "CLAUDE_PROJECTS_DIR"):
        if os.environ.get(name, "").strip():
            return f"env:{name}"
    for name in ("CLAUDE_CODE_CONFIG_DIR", "CLAUDE_CONFIG_DIR"):
        if os.environ.get(name, "").strip():
            return f"env:{name}"
    if _local_relay_claude_config_dir():
        return "local_relay_settings"
    return "default_home"


def _first_existing_or_first(candidates: list[Path]) -> Path:
    for path in candidates:
        if path.exists():
            return path
    return candidates[0]


def claude_desktop_code_sessions_root() -> Path:
    return _first_existing_or_first(claude_desktop_code_session_roots())


def claude_desktop_code_session_roots() -> list[Path]:
    for name in ("CLAUDE_DESKTOP_CODE_SESSIONS_DIR", "CLAUDE_CODE_DESKTOP_SESSIONS_DIR"):
        value = os.environ.get(name, "").strip()
        if value:
            return [Path(value).expanduser()]
    platform = os.environ.get("MEMCORE_PLATFORM", "").strip().lower()
    candidates: list[Path] = []
    if platform in {"windows", "win32"} or os.name == "nt":
        appdata = os.environ.get("APPDATA", "").strip()
        if appdata:
            candidates.append(Path(appdata) / "Claude" / "claude-code-sessions")
        localappdata = os.environ.get("LOCALAPPDATA", "").strip()
        if localappdata:
            local = Path(localappdata)
            candidates.extend([
                local / "Claude" / "claude-code-sessions",
                local / "Claude-3p" / "claude-code-sessions",
            ])
            try:
                for candidate in local.glob("Claude*"):
                    if candidate.is_dir():
                        candidates.append(candidate / "claude-code-sessions")
            except OSError:
                pass
        userprofile = os.environ.get("USERPROFILE", "").strip()
        base = Path(userprofile).expanduser() if userprofile else Path.home()
        candidates.extend([
            base / "AppData" / "Roaming" / "Claude" / "claude-code-sessions",
            base / "AppData" / "Local" / "Claude" / "claude-code-sessions",
            base / "AppData" / "Local" / "Claude-3p" / "claude-code-sessions",
        ])
    elif platform in {"darwin", "mac", "macos"} or sys.platform == "darwin":
        candidates.append(Path.home() / "Library" / "Application Support" / "Claude" / "claude-code-sessions")
    else:
        candidates.append(Path.home() / ".config" / "Claude" / "claude-code-sessions")
    unique: list[Path] = []
    for candidate in candidates:
        if candidate not in unique:
            unique.append(candidate)
    return unique


def claude_desktop_code_runtime_root() -> Path:
    for name in ("CLAUDE_DESKTOP_CODE_RUNTIME_DIR", "CLAUDE_CODE_DESKTOP_RUNTIME_DIR"):
        value = os.environ.get(name, "").strip()
        if value:
            return Path(value).expanduser()
    platform = os.environ.get("MEMCORE_PLATFORM", "").strip().lower()
    if platform in {"windows", "win32"} or os.name == "nt":
        appdata = os.environ.get("APPDATA", "").strip()
        if appdata:
            return Path(appdata) / "Claude" / "claude-code"
        return Path.home() / "AppData" / "Roaming" / "Claude" / "claude-code"
    if platform in {"darwin", "mac", "macos"} or sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Claude" / "claude-code"
    return Path.home() / ".config" / "Claude" / "claude-code"


def desktop_managed_runtime_detected() -> bool:
    root = claude_desktop_code_runtime_root()
    if not root.exists():
        return False
    try:
        return any(root.iterdir())
    except OSError:
        return True


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


def _truncate_text(text: str, max_chars: int = 80) -> str:
    trimmed = str(text or "").strip()
    if not trimmed:
        return ""
    if len(trimmed) <= max_chars:
        return trimmed
    return trimmed[:max_chars].rstrip() + "..."


def _normalise_entrypoint(value: Any) -> str:
    return str(value or "").strip().lower()


def _read_head_tail_lines(path: Path, head_n: int = SESSION_SUMMARY_HEAD_LINES, tail_n: int = SESSION_SUMMARY_TAIL_LINES) -> tuple[list[str], list[str], bool]:
    try:
        size = path.stat().st_size
    except OSError:
        return [], [], False
    if size < 64 * 1024:
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return [], [], False
        tail_start = max(0, len(lines) - tail_n)
        return lines[:head_n], lines[tail_start:], False

    head: list[str] = []
    tail: list[str] = []
    try:
        with path.open("rb") as f:
            for _ in range(head_n):
                line = f.readline()
                if not line:
                    break
                head.append(line.decode("utf-8", errors="replace").rstrip("\r\n"))
            seek_pos = max(0, size - 64 * 1024)
            f.seek(seek_pos)
            if seek_pos:
                f.readline()
            tail_bytes = f.read()
        tail_lines = tail_bytes.decode("utf-8", errors="replace").splitlines()
        tail = tail_lines[-tail_n:]
    except OSError:
        pass
    return head, tail, True


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


def _short_path_digest(path: Path) -> str:
    text = str(path).replace("\\", "/")
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]


def _raw_artifact_id_from_path(path: Path, session_id: str) -> str:
    """Return a stable raw archive id for one source JSONL file.

    Claude Code subagents share the parent sessionId, so sessionId alone is not
    a safe raw filename. Keep the parent session id for routing, but make the
    raw artifact id source-file-specific.
    """
    sid = _safe_segment(session_id or path.stem, "session")
    stem = _safe_segment(path.stem, "source")
    try:
        rel_parts = path.expanduser().resolve().relative_to(claude_code_projects_root().expanduser().resolve()).parts
    except Exception:
        rel_parts = path.parts
    if "subagents" in rel_parts:
        return _safe_segment(f"{sid}__subagent__{stem}", sid)
    if stem and stem != sid:
        return _safe_segment(f"{sid}__{stem}__{_short_path_digest(path)}", sid)
    return sid


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


def _meta_payload(dest: Path, artifact: dict[str, Any], src_stat: os.stat_result, offset: int, raw_order: int) -> dict[str, Any]:
    return {
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
        "raw_artifact_id": artifact.get("raw_artifact_id", artifact.get("session_id", "")),
        "raw_artifact_id_schema": artifact.get("raw_artifact_id_schema", RAW_ARTIFACT_ID_SCHEMA),
        "project_id": artifact.get("project_id", ""),
        "project_root": artifact.get("project_root", ""),
        "thread_name": artifact.get("thread_name", ""),
        "storage_owner": artifact.get("storage_owner", BODY_STORAGE_OWNER),
        "body_storage_owner": artifact.get("body_storage_owner", BODY_STORAGE_OWNER),
        "conversation_origin": artifact.get("conversation_origin", "claude_code_cli"),
        "runtime_consumer": artifact.get("runtime_consumer", "claude_code_cli"),
        "desktop_installer_includes_cli": DESKTOP_INSTALLER_INCLUDES_CLI,
        "cli_installation_boundary": CLI_INSTALLATION_BOUNDARY,
        "desktop_cli_relationship": DESKTOP_CLI_RELATIONSHIP,
        "user_installed_cli_independent": True,
        "user_installed_path_cli_required": False,
        "desktop_managed_runtime_detected": bool(artifact.get("desktop_managed_runtime_detected")),
        "desktop_managed_runtime_owner": artifact.get("desktop_managed_runtime_owner", ""),
        "desktop_managed_runtime_policy": artifact.get("desktop_managed_runtime_policy", ""),
        "desktop_managed_runtime_is_user_installed_cli": False if artifact.get("desktop_managed_runtime_detected") else None,
        "desktop_shell_owner": artifact.get("desktop_shell_owner", ""),
        "desktop_session_id": artifact.get("desktop_session_id", ""),
        "desktop_metadata_path": artifact.get("desktop_metadata_path", ""),
        "desktop_metadata_owner": artifact.get("desktop_metadata_owner", ""),
        "desktop_metadata_policy": artifact.get("desktop_metadata_policy", ""),
        "desktop_metadata_is_conversation_body": False,
        "entrypoint": artifact.get("entrypoint", ""),
        "entrypoint_counts": artifact.get("entrypoint_counts", {}),
        "desktop_entrypoint_detected": bool(artifact.get("desktop_entrypoint_detected")),
        "desktop_entrypoint_policy": artifact.get("desktop_entrypoint_policy", ""),
        "co_source_systems": artifact.get("co_source_systems", []),
        "main_river_storage": "canonical_dialogue",
        "forensic_runtime_storage": "full_raw_archive_plus_manifest",
        "canonical_dialogue_path": str(dest) + ".canonical_dialogue.jsonl",
        "forensic_runtime_manifest_path": str(dest) + ".forensic_runtime.json",
        **_generation_meta(dest),
        "last_update": ts(),
    }


def _meta_needs_update(dest: Path, artifact: dict[str, Any], src_stat: os.stat_result, offset: int, raw_order: int) -> bool:
    meta_path = Path(str(dest) + ".meta.json")
    if not meta_path.exists():
        return True
    try:
        existing = json.loads(meta_path.read_text(encoding="utf-8-sig"))
    except Exception:
        return True
    wanted = _meta_payload(dest, artifact, src_stat, offset, raw_order)
    for key in (
        "source_system",
        "source_path",
        "source_inode",
        "source_mtime",
        "file_offset",
        "raw_order",
        "archived_to",
        "native_artifact_format",
        "raw_archive_layout",
        "session_id",
        "raw_artifact_id",
        "raw_artifact_id_schema",
        "project_id",
        "project_root",
        "thread_name",
        "main_river_storage",
        "forensic_runtime_storage",
        "canonical_dialogue_path",
        "forensic_runtime_manifest_path",
        "raw_generation_contract",
        "raw_generation",
        "source_base_offset",
        "raw_generation_predecessor",
        "raw_generation_reason",
        "raw_generation_descriptor_path",
        "storage_owner",
        "body_storage_owner",
        "conversation_origin",
        "runtime_consumer",
        "desktop_installer_includes_cli",
        "cli_installation_boundary",
        "desktop_cli_relationship",
        "user_installed_cli_independent",
        "user_installed_path_cli_required",
        "desktop_managed_runtime_detected",
        "desktop_managed_runtime_owner",
        "desktop_managed_runtime_policy",
        "desktop_managed_runtime_is_user_installed_cli",
        "desktop_shell_owner",
        "desktop_session_id",
        "desktop_metadata_path",
        "desktop_metadata_owner",
        "desktop_metadata_policy",
        "desktop_metadata_is_conversation_body",
        "entrypoint",
        "entrypoint_counts",
        "desktop_entrypoint_detected",
        "desktop_entrypoint_policy",
        "co_source_systems",
    ):
        if existing.get(key) != wanted.get(key):
            return True
    return False


def _text_from_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                for key in ("text", "content", "value"):
                    value = item.get(key)
                    if isinstance(value, str) and value:
                        parts.append(value)
                        break
                nested = item.get("content")
                if isinstance(nested, list):
                    nested_text = _text_from_content(nested)
                    if nested_text:
                        parts.append(nested_text)
        return "\n".join(part for part in parts if part)
    if isinstance(content, dict):
        for key in ("text", "content", "value"):
            value = content.get(key)
            if isinstance(value, str):
                return value
        nested = content.get("content")
        if isinstance(nested, list):
            return _text_from_content(nested)
    return ""


def _content_is_all_tool_results(content: Any) -> bool:
    if not isinstance(content, list) or not content:
        return False
    return all(
        isinstance(item, dict) and str(item.get("type") or "") == "tool_result"
        for item in content
    )


def _message_from_record(record: dict[str, Any]) -> dict[str, Any] | None:
    rec_type = str(record.get("type") or "").strip()
    if rec_type not in {"user", "assistant"}:
        return None
    message = record.get("message")
    if not isinstance(message, dict):
        return None
    content = message.get("content")
    role = str(message.get("role") or rec_type).strip()
    if role == "user" and _content_is_all_tool_results(content):
        role = "tool"
    if role not in {"user", "assistant"}:
        if role == "tool":
            text = _text_from_content(content)
            return {
                "role": role,
                "content_present": bool(text.strip()),
                "text": text,
                "uuid": str(record.get("uuid") or record.get("id") or ""),
                "parent_uuid": str(record.get("parentUuid") or message.get("parentUuid") or ""),
            }
        return None
    text = _text_from_content(content)
    return {
        "role": role,
        "content_present": bool(text.strip()),
        "text": text,
        "uuid": str(record.get("uuid") or record.get("id") or ""),
        "parent_uuid": str(record.get("parentUuid") or message.get("parentUuid") or ""),
    }


def _read_session_summary(path: Path) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "session_id": "",
        "project_root": "",
        "first_user_message": "",
        "custom_title": "",
        "user_message_count": 0,
        "assistant_message_count": 0,
        "tool_result_message_count": 0,
        "content_message_count": 0,
        "first_message_uuid": "",
        "latest_message_uuid": "",
        "line_count_sample": 0,
        "sample_truncated": False,
        "parse_errors": 0,
        "summary_scan_mode": "head_tail",
        "entrypoint": "",
        "entrypoint_counts": {},
        "desktop_entrypoint_detected": False,
    }
    head, tail, truncated = _read_head_tail_lines(path)
    summary["sample_truncated"] = truncated
    lines = head + tail
    seen: set[str] = set()
    for line in lines:
        line = line.strip()
        if not line:
            continue
        line_key = hashlib.sha1(line.encode("utf-8", errors="replace")).hexdigest()
        if line_key in seen:
            continue
        seen.add(line_key)
        summary["line_count_sample"] += 1
        try:
            record = json.loads(line)
        except Exception:
            summary["parse_errors"] += 1
            continue
        entrypoint = _normalise_entrypoint(record.get("entrypoint"))
        if entrypoint:
            counts = summary["entrypoint_counts"]
            counts[entrypoint] = int(counts.get(entrypoint, 0) or 0) + 1
            if not summary["entrypoint"]:
                summary["entrypoint"] = entrypoint
            if entrypoint in DESKTOP_ENTRYPOINT_VALUES:
                summary["desktop_entrypoint_detected"] = True
        if not summary["session_id"] and record.get("sessionId"):
            summary["session_id"] = str(record.get("sessionId") or "")
        if not summary["project_root"] and record.get("cwd"):
            summary["project_root"] = _clean_path_text(record.get("cwd"))
        if record.get("type") == "custom-title" and not summary["custom_title"]:
            title = str(record.get("customTitle") or "").strip()
            if title:
                summary["custom_title"] = title
        message = _message_from_record(record)
        if not message:
            continue
        if not summary["first_message_uuid"]:
            summary["first_message_uuid"] = message.get("uuid", "")
        summary["latest_message_uuid"] = message.get("uuid", "")
        if message.get("role") == "user":
            summary["user_message_count"] += 1
            if not summary["first_user_message"]:
                text = str(message.get("text") or "").strip()
                if text and "<local-command-caveat>" not in text and not text.startswith("<command-name>"):
                    summary["first_user_message"] = text
        elif message.get("role") == "assistant":
            summary["assistant_message_count"] += 1
        elif message.get("role") == "tool":
            summary["tool_result_message_count"] += 1
        if message.get("content_present"):
            summary["content_message_count"] += 1
    return summary


def _session_id_from_path(path: Path, summary: dict[str, Any]) -> str:
    sid = str(summary.get("session_id") or "").strip()
    return sid or path.stem


def _millis_to_iso(value: Any) -> str:
    try:
        millis = float(value)
    except Exception:
        return ""
    if millis <= 0:
        return ""
    return datetime.fromtimestamp(millis / 1000.0, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _desktop_session_item(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    cli_session_id = str(data.get("cliSessionId") or "").strip()
    if not cli_session_id:
        return None
    try:
        stat = path.stat()
        mtime = datetime.fromtimestamp(stat.st_mtime, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    except OSError:
        stat = None
        mtime = ""
    return {
        "source_system": "claude_desktop",
        "artifact_type": "claude_desktop_code_session_metadata_json",
        "source_path": str(path),
        "filename": path.name,
        "desktop_session_id": str(data.get("sessionId") or path.stem),
        "cli_session_id": cli_session_id,
        "project_root": _clean_path_text(data.get("cwd") or data.get("originCwd") or ""),
        "origin_cwd": _clean_path_text(data.get("originCwd") or ""),
        "title": str(data.get("title") or ""),
        "title_source": str(data.get("titleSource") or ""),
        "model": str(data.get("model") or ""),
        "permission_mode": str(data.get("permissionMode") or ""),
        "is_archived": bool(data.get("isArchived")) if data.get("isArchived") is not None else False,
        "completed_turns": int(data.get("completedTurns") or 0),
        "created_at": _millis_to_iso(data.get("createdAt")),
        "last_activity_at": _millis_to_iso(data.get("lastActivityAt")),
        "last_focused_at": _millis_to_iso(data.get("lastFocusedAt")),
        "mtime": mtime,
        "size_bytes": stat.st_size if stat else 0,
        "read_only_probe": True,
        "message_text_returned": False,
        "raw_excerpt_returned": False,
        "complete_conversation_candidate": False,
        "metadata_only": True,
        "desktop_installer_includes_cli": DESKTOP_INSTALLER_INCLUDES_CLI,
        "cli_installation_boundary": CLI_INSTALLATION_BOUNDARY,
        "desktop_metadata_policy": DESKTOP_METADATA_POLICY,
    }


def load_desktop_session_index() -> dict[str, dict[str, Any]]:
    root = claude_desktop_code_sessions_root()
    if not root.exists():
        return {}
    items: dict[str, dict[str, Any]] = {}
    try:
        files = [p for p in root.rglob(DESKTOP_SESSION_GLOB) if p.is_file()]
        files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return {}
    for path in files:
        item = _desktop_session_item(path)
        if not item:
            continue
        cli_session_id = str(item.get("cli_session_id") or "")
        prior = items.get(cli_session_id)
        if not prior or str(item.get("last_focused_at") or item.get("mtime") or "") >= str(prior.get("last_focused_at") or prior.get("mtime") or ""):
            items[cli_session_id] = item
    return items


def _desktop_public_metadata(item: dict[str, Any] | None) -> dict[str, Any]:
    data = item or {}
    if not data:
        return {}
    return {
        "source_system": "claude_desktop",
        "artifact_type": "claude_desktop_code_session_metadata_json",
        "filename": data.get("filename", ""),
        "desktop_session_id": data.get("desktop_session_id", ""),
        "cli_session_id": data.get("cli_session_id", ""),
        "title": data.get("title", ""),
        "title_source": data.get("title_source", ""),
        "model": data.get("model", ""),
        "permission_mode": data.get("permission_mode", ""),
        "is_archived": bool(data.get("is_archived")),
        "completed_turns": data.get("completed_turns", 0),
        "last_focused_at": data.get("last_focused_at", ""),
        "last_activity_at": data.get("last_activity_at", ""),
        "metadata_only": True,
        "message_text_returned": False,
        "raw_excerpt_returned": False,
        "desktop_installer_includes_cli": DESKTOP_INSTALLER_INCLUDES_CLI,
        "cli_installation_boundary": CLI_INSTALLATION_BOUNDARY,
        "desktop_metadata_policy": DESKTOP_METADATA_POLICY,
    }


def artifact_from_path(path: Path, desktop_index: Optional[dict[str, dict[str, Any]]] = None) -> dict[str, Any]:
    path = path.expanduser()
    summary = _read_session_summary(path)
    session_id = _session_id_from_path(path, summary)
    raw_artifact_id = _raw_artifact_id_from_path(path, session_id)
    desktop_index = desktop_index if desktop_index is not None else load_desktop_session_index()
    desktop_meta = desktop_index.get(session_id, {})
    desktop_entrypoint_detected = bool(summary.get("desktop_entrypoint_detected"))
    desktop_managed = bool(desktop_meta) or desktop_entrypoint_detected
    cwd = _clean_path_text(summary.get("project_root", "") or desktop_meta.get("project_root", ""))
    project_id = project_id_from_cwd(cwd)
    stat = path.stat()
    mtime = datetime.fromtimestamp(stat.st_mtime, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    complete = bool(summary.get("user_message_count") and summary.get("assistant_message_count"))
    title = str(
        desktop_meta.get("title")
        or summary.get("custom_title")
        or _truncate_text(str(summary.get("first_user_message") or ""))
        or path.parent.name
    )
    if desktop_entrypoint_detected:
        conversation_origin = DESKTOP_ENTRYPOINT_ORIGIN
    elif desktop_meta:
        conversation_origin = "claude_desktop_managed_claude_code_session"
    else:
        conversation_origin = "claude_code_cli"
    return {
        "source_system": SOURCE_SYSTEM,
        "artifact_type": NATIVE_ARTIFACT_FORMAT,
        "source_path": str(path),
        "filename": path.name,
        "session_id": session_id,
        "raw_artifact_id": raw_artifact_id,
        "raw_artifact_id_schema": RAW_ARTIFACT_ID_SCHEMA,
        "native_thread_id": session_id,
        "canonical_window_id": project_id,
        "project_id": project_id,
        "project_root": cwd,
        "thread_name": title,
        "desktop_session_metadata_detected": bool(desktop_meta),
        "desktop_session_metadata": _desktop_public_metadata(desktop_meta),
        "desktop_session_id": desktop_meta.get("desktop_session_id", ""),
        "desktop_metadata_path": desktop_meta.get("source_path", ""),
        "desktop_metadata_owner": "claude_desktop" if desktop_meta else "",
        "co_source_systems": ["claude_desktop"] if desktop_managed else [],
        "entrypoint": summary.get("entrypoint", ""),
        "entrypoint_counts": summary.get("entrypoint_counts", {}),
        "desktop_entrypoint_detected": desktop_entrypoint_detected,
        "desktop_entrypoint_policy": DESKTOP_ENTRYPOINT_POLICY if desktop_entrypoint_detected else "",
        "computer_name": node_id(),
        "size_bytes": stat.st_size,
        "size_mb": round(stat.st_size / 1024 / 1024, 3),
        "mtime": mtime,
        "capture_classification": "SHADOW",
        "scope_level": "project",
        "read_only_probe": True,
        "storage_owner": BODY_STORAGE_OWNER,
        "body_storage_owner": BODY_STORAGE_OWNER,
        "conversation_origin": conversation_origin,
        "runtime_consumer": DESKTOP_MANAGED_RUNTIME_CONSUMER if desktop_managed else "claude_code_cli",
        "desktop_installer_includes_cli": DESKTOP_INSTALLER_INCLUDES_CLI,
        "cli_installation_boundary": CLI_INSTALLATION_BOUNDARY,
        "desktop_cli_relationship": DESKTOP_CLI_RELATIONSHIP,
        "user_installed_cli_independent": True,
        "user_installed_path_cli_required": False,
        "desktop_managed_runtime_detected": desktop_managed,
        "desktop_managed_runtime_owner": DESKTOP_MANAGED_RUNTIME_OWNER if desktop_managed else "",
        "desktop_managed_runtime_policy": DESKTOP_MANAGED_RUNTIME_POLICY if desktop_managed else "",
        "desktop_managed_runtime_is_user_installed_cli": False if desktop_managed else None,
        "desktop_shell_owner": DESKTOP_MANAGED_RUNTIME_OWNER if desktop_managed else "",
        "desktop_metadata_policy": DESKTOP_METADATA_POLICY if desktop_meta else "",
        "desktop_metadata_is_conversation_body": False,
        "complete_conversation_candidate": complete,
        "assistant_reply_persistence": "verified" if complete else "unverified",
        "user_message_count": int(summary.get("user_message_count", 0) or 0),
        "assistant_message_count": int(summary.get("assistant_message_count", 0) or 0),
        "tool_result_message_count": int(summary.get("tool_result_message_count", 0) or 0),
        "content_message_count": int(summary.get("content_message_count", 0) or 0),
        "sample_truncated": bool(summary.get("sample_truncated")),
        "summary_scan_mode": summary.get("summary_scan_mode", "head_tail"),
        "parse_errors": int(summary.get("parse_errors", 0) or 0),
    }


def discover_sessions(limit: int = 0) -> List[dict[str, Any]]:
    root = claude_code_projects_root()
    if not root.exists():
        return []
    desktop_index = load_desktop_session_index()
    files = [p for p in root.rglob(SESSION_GLOB) if p.is_file() and ".checkpoint." not in p.name]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    if limit and limit > 0:
        files = files[:limit]
    artifacts: list[dict[str, Any]] = []
    for path in files:
        try:
            artifacts.append(artifact_from_path(path, desktop_index=desktop_index))
        except OSError:
            continue
    return artifacts


def public_artifact(artifact: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_system": SOURCE_SYSTEM,
        "artifact_type": artifact.get("artifact_type", NATIVE_ARTIFACT_FORMAT),
        "filename": artifact.get("filename", ""),
        "session_id": artifact.get("session_id", ""),
        "raw_artifact_id": artifact.get("raw_artifact_id", artifact.get("session_id", "")),
        "raw_artifact_id_schema": artifact.get("raw_artifact_id_schema", RAW_ARTIFACT_ID_SCHEMA),
        "canonical_window_id": artifact.get("canonical_window_id", ""),
        "project_id": artifact.get("project_id", ""),
        "computer_name": artifact.get("computer_name", ""),
        "size_bytes": artifact.get("size_bytes", 0),
        "size_mb": artifact.get("size_mb", 0),
        "mtime": artifact.get("mtime", ""),
        "capture_classification": artifact.get("capture_classification", "SHADOW"),
        "scope_level": artifact.get("scope_level", "project"),
        "complete_conversation_candidate": bool(artifact.get("complete_conversation_candidate")),
        "assistant_reply_persistence": artifact.get("assistant_reply_persistence", "unverified"),
        "user_message_count": artifact.get("user_message_count", 0),
        "assistant_message_count": artifact.get("assistant_message_count", 0),
        "storage_owner": artifact.get("storage_owner", BODY_STORAGE_OWNER),
        "body_storage_owner": artifact.get("body_storage_owner", BODY_STORAGE_OWNER),
        "conversation_origin": artifact.get("conversation_origin", "claude_code_cli"),
        "runtime_consumer": artifact.get("runtime_consumer", "claude_code_cli"),
        "desktop_session_metadata_detected": bool(artifact.get("desktop_session_metadata_detected")),
        "entrypoint": artifact.get("entrypoint", ""),
        "entrypoint_counts": artifact.get("entrypoint_counts", {}),
        "desktop_entrypoint_detected": bool(artifact.get("desktop_entrypoint_detected")),
        "desktop_entrypoint_policy": artifact.get("desktop_entrypoint_policy", ""),
        "desktop_session_metadata": artifact.get("desktop_session_metadata", {}),
        "desktop_installer_includes_cli": DESKTOP_INSTALLER_INCLUDES_CLI,
        "cli_installation_boundary": CLI_INSTALLATION_BOUNDARY,
        "desktop_cli_relationship": DESKTOP_CLI_RELATIONSHIP,
        "user_installed_cli_independent": True,
        "user_installed_path_cli_required": False,
        "desktop_managed_runtime_detected": bool(artifact.get("desktop_managed_runtime_detected")),
        "desktop_managed_runtime_owner": artifact.get("desktop_managed_runtime_owner", ""),
        "desktop_managed_runtime_policy": artifact.get("desktop_managed_runtime_policy", ""),
        "desktop_managed_runtime_is_user_installed_cli": artifact.get("desktop_managed_runtime_is_user_installed_cli"),
        "desktop_metadata_policy": artifact.get("desktop_metadata_policy", ""),
        "desktop_metadata_is_conversation_body": False,
        "co_source_systems": artifact.get("co_source_systems", []),
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


def _raw_dest_for_artifact(artifact: dict[str, Any]) -> Path:
    project_id = _safe_segment(artifact.get("canonical_window_id") or artifact.get("project_id"), "project")
    session_id = _safe_segment(artifact.get("raw_artifact_id") or artifact.get("session_id"), "session")
    root = memory_root()
    preferred = preferred_raw_archive_path(
        root,
        computer_name=artifact.get("computer_name") or node_id(),
        source_system=SOURCE_SYSTEM,
        native_format=artifact.get("artifact_type") or NATIVE_ARTIFACT_FORMAT,
        native_scope=project_id,
        session_id=session_id,
    )
    return existing_or_preferred_raw_archive_path(root, preferred)


def _raw_sync_item(artifact: dict[str, Any], scan_mode: str = "full") -> dict[str, Any]:
    scan_mode = "fast" if str(scan_mode or "").lower() in {"fast", "stat", "quick"} else "full"
    src = Path(artifact.get("source_path", "")).expanduser()
    src_stat = None
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
    generation_descriptor = load_generation_descriptor(dest)
    try:
        dest_stat = dest.stat()
        raw_size = dest_stat.st_size
        raw_mtime = datetime.fromtimestamp(dest_stat.st_mtime, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    except OSError:
        raw_size = 0
        raw_mtime = ""
    source_base_offset = int(generation_descriptor.get("source_base_offset", 0) or 0)
    covered_source_bytes = source_base_offset + raw_size if generation_descriptor else raw_size
    generation_descriptor_incomplete = bool(selection.get("generation_descriptor_incomplete"))
    selection_meta = selection.get("metadata") if isinstance(selection.get("metadata"), dict) else {}
    try:
        metadata_offset = int(selection_meta.get("file_offset", -1))
        metadata_mtime = float(selection_meta.get("source_mtime", -1.0))
    except (TypeError, ValueError):
        metadata_offset = -1
        metadata_mtime = -1.0
    metadata_continuity_proven = bool(
        scan_mode == "full"
        or generation_descriptor
        or (
            src_stat is not None
            and selection.get("source_inode_match")
            and metadata_offset == source_size == covered_source_bytes
            and metadata_mtime == float(src_stat.st_mtime)
        )
    )
    continuity_not_measured = bool(
        scan_mode == "fast"
        and dest.exists()
        and not generation_descriptor
        and not generation_descriptor_incomplete
        and not metadata_continuity_proven
    )
    source_regression = bool(dest.exists() and covered_source_bytes > source_size)
    return {
        "session_id": artifact.get("session_id", ""),
        "raw_artifact_id": artifact.get("raw_artifact_id", artifact.get("session_id", "")),
        "raw_artifact_id_schema": artifact.get("raw_artifact_id_schema", RAW_ARTIFACT_ID_SCHEMA),
        "project_id": artifact.get("project_id", ""),
        "source_mtime": source_mtime,
        "source_size_bytes": source_size,
        "raw_mtime": raw_mtime,
        "raw_size_bytes": raw_size,
        "raw_exists": dest.exists(),
        "raw_missing": not dest.exists(),
        "raw_stale": bool(dest.exists()) and covered_source_bytes < source_size,
        "raw_source_regression": source_regression,
        "raw_generation_descriptor_incomplete": generation_descriptor_incomplete,
        "raw_monotonic_probe_ok": (
            None if continuity_not_measured else not generation_descriptor_incomplete
        ),
        "raw_monotonic_status": (
            "raw_generation_descriptor_incomplete"
            if generation_descriptor_incomplete
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
        "raw_archive_lag_bytes": max(0, source_size - covered_source_bytes),
        "raw_generation": int(generation_descriptor.get("generation", 0) or 0),
        "raw_source_base_offset": source_base_offset,
        "raw_covered_source_bytes": covered_source_bytes,
        "raw_generation_predecessor": str(generation_descriptor.get("predecessor") or ""),
        "source_path_label": _public_path_label(str(src)),
        "raw_path_label": _public_path_label(str(dest)),
    }


def raw_sync_snapshot(limit: int = 20) -> dict[str, Any]:
    artifacts = discover_sessions(limit=limit)
    items = [_raw_sync_item(artifact) for artifact in artifacts]
    missing_or_stale = [item for item in items if item.get("raw_missing") or item.get("raw_stale")]
    source_epochs = [_iso_to_epoch(item.get("source_mtime", "")) for item in items]
    raw_epochs = [_iso_to_epoch(item.get("raw_mtime", "")) for item in items if item.get("raw_mtime")]
    latest_source_epoch = max(source_epochs) if source_epochs else 0.0
    latest_raw_epoch = max(raw_epochs) if raw_epochs else 0.0
    latest_source_mtime = datetime.fromtimestamp(latest_source_epoch, UTC).strftime("%Y-%m-%dT%H:%M:%SZ") if latest_source_epoch else ""
    latest_raw_mtime = datetime.fromtimestamp(latest_raw_epoch, UTC).strftime("%Y-%m-%dT%H:%M:%SZ") if latest_raw_epoch else ""
    lag_seconds = int(max(0, latest_source_epoch - latest_raw_epoch)) if latest_source_epoch and latest_raw_epoch else None
    if not claude_code_projects_root().exists():
        status_text = "source_unreachable"
    elif not artifacts:
        status_text = "no_source_records"
    elif missing_or_stale:
        status_text = "raw_lagging"
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
        "source_root_reachable": claude_code_projects_root().exists(),
        "source_count_sample": len(artifacts),
        "latest_source_mtime": latest_source_mtime,
        "latest_raw_mtime": latest_raw_mtime,
        "raw_archive_lag_seconds": lag_seconds,
        "missing_or_stale_count": len(missing_or_stale),
        "latest_missing_or_stale": missing_or_stale[:5],
    }


def load_checkpoint() -> dict[str, Any]:
    path = checkpoint_file()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f)
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


def _write_meta(dest: Path, artifact: dict[str, Any], src_stat: os.stat_result, offset: int, raw_order: int) -> None:
    meta = _meta_payload(dest, artifact, src_stat, offset, raw_order)
    with open(str(dest) + ".meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


def _register_current_window_for_artifact(artifact: dict[str, Any], dest: str) -> dict[str, Any]:
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
        binding_source="claude_code_session_jsonl_incremental_capture",
        confidence="observed_claude_code_session_change",
        metadata={
            "project_id": project_id,
            "project_root": artifact.get("project_root", ""),
            "source_refs_canonical_window_id": artifact.get("canonical_window_id", ""),
            "native_artifact_format": artifact.get("artifact_type") or NATIVE_ARTIFACT_FORMAT,
            "raw_archive_layout": "computer_first",
            "storage_owner": artifact.get("storage_owner", BODY_STORAGE_OWNER),
            "body_storage_owner": artifact.get("body_storage_owner", BODY_STORAGE_OWNER),
            "conversation_origin": artifact.get("conversation_origin", "claude_code_cli"),
            "runtime_consumer": artifact.get("runtime_consumer", "claude_code_cli"),
            "desktop_installer_includes_cli": DESKTOP_INSTALLER_INCLUDES_CLI,
            "cli_installation_boundary": CLI_INSTALLATION_BOUNDARY,
            "desktop_cli_relationship": DESKTOP_CLI_RELATIONSHIP,
            "user_installed_cli_independent": True,
            "user_installed_path_cli_required": False,
            "desktop_managed_runtime_detected": bool(artifact.get("desktop_managed_runtime_detected")),
            "desktop_managed_runtime_owner": artifact.get("desktop_managed_runtime_owner", ""),
            "desktop_managed_runtime_policy": artifact.get("desktop_managed_runtime_policy", ""),
            "desktop_managed_runtime_is_user_installed_cli": artifact.get("desktop_managed_runtime_is_user_installed_cli"),
            "desktop_shell_owner": artifact.get("desktop_shell_owner", ""),
            "desktop_session_id": artifact.get("desktop_session_id", ""),
            "desktop_metadata_owner": artifact.get("desktop_metadata_owner", ""),
            "desktop_metadata_policy": artifact.get("desktop_metadata_policy", ""),
            "desktop_metadata_is_conversation_body": False,
            "entrypoint": artifact.get("entrypoint", ""),
            "entrypoint_counts": artifact.get("entrypoint_counts", {}),
            "desktop_entrypoint_detected": bool(artifact.get("desktop_entrypoint_detected")),
            "desktop_entrypoint_policy": artifact.get("desktop_entrypoint_policy", ""),
            "co_source_systems": artifact.get("co_source_systems", []),
        },
    )


def archive_session_incremental(
    source_path: str,
    dry_run: bool = False,
    artifact: Optional[dict[str, Any]] = None,
) -> tuple[str, str]:
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
    descriptor = load_generation_descriptor(dest)
    checkpoint[key] = {
        "offset": covered_offset,
        "archived_to": str(dest),
        "source_inode": src_stat.st_ino,
        "source_size": src_stat.st_size,
        "source_mtime": src_stat.st_mtime,
        "raw_order": raw_order,
        "generation": int(report.get("generation") or descriptor.get("generation", 0) or 0),
        "source_base_offset": int(report.get("source_base_offset") or descriptor.get("source_base_offset", 0) or 0),
        "predecessor": str(report.get("predecessor") or descriptor.get("predecessor") or ""),
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
            source_base_offset=int(report.get("source_base_offset") or descriptor.get("source_base_offset", 0) or 0),
            generation=int(report.get("generation") or descriptor.get("generation", 0) or 0),
            predecessor=str(report.get("predecessor") or descriptor.get("predecessor") or ""),
        )
    if report_status == "up_to_date":
        if _meta_needs_update(dest, artifact, src_stat, src_stat.st_size, raw_order):
            _write_meta(dest, artifact, src_stat, src_stat.st_size, raw_order)
            return str(dest), f"metadata_updated(offset={src_stat.st_size})"
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


def scan_sessions(dry_run: bool = False, limit: int = 0, public: bool = False) -> dict[str, Any]:
    artifacts = discover_sessions(limit=limit)
    items: list[dict[str, Any]] = []
    changed = 0
    would_change = 0
    window_bindings: list[dict[str, Any]] = []
    window_binding_skipped = 0
    current_window_registered = False
    for artifact in artifacts:
        dest, status = archive_session_incremental(artifact["source_path"], dry_run=dry_run, artifact=artifact)
        changed_status = status.startswith(("archived", "appended", "generation_started", "rotation", "metadata_updated"))
        if dry_run and status.startswith("dry_run"):
            would_change += 1
        elif changed_status:
            changed += 1

        if not dry_run and artifact.get("complete_conversation_candidate") and not current_window_registered:
            binding = _register_current_window_for_artifact(artifact, dest)
            if binding.get("ok"):
                window_bindings.append(binding)
                current_window_registered = True
            else:
                window_binding_skipped += 1
        elif changed_status and not artifact.get("complete_conversation_candidate"):
            window_binding_skipped += 1
        items.append({
            "source_path": _public_path_label(artifact["source_path"]) if public else artifact["source_path"],
            "dest": _public_path_label(dest) if public else dest,
            "status": status,
            "session_id": artifact.get("session_id", ""),
            "raw_artifact_id": artifact.get("raw_artifact_id", artifact.get("session_id", "")),
            "raw_artifact_id_schema": artifact.get("raw_artifact_id_schema", RAW_ARTIFACT_ID_SCHEMA),
            "canonical_window_id": artifact.get("canonical_window_id", ""),
            "project_root": _public_path_label(artifact.get("project_root", "")) if public else artifact.get("project_root", ""),
            "thread_name": artifact.get("thread_name", ""),
            "complete_conversation_candidate": bool(artifact.get("complete_conversation_candidate")),
            "assistant_reply_persistence": artifact.get("assistant_reply_persistence", "unverified"),
            "desktop_session_metadata_detected": bool(artifact.get("desktop_session_metadata_detected")),
            "desktop_session_id": artifact.get("desktop_session_id", ""),
            "entrypoint": artifact.get("entrypoint", ""),
            "entrypoint_counts": artifact.get("entrypoint_counts", {}),
            "desktop_entrypoint_detected": bool(artifact.get("desktop_entrypoint_detected")),
            "desktop_entrypoint_policy": artifact.get("desktop_entrypoint_policy", ""),
            "desktop_installer_includes_cli": DESKTOP_INSTALLER_INCLUDES_CLI,
            "cli_installation_boundary": CLI_INSTALLATION_BOUNDARY,
            "desktop_cli_relationship": DESKTOP_CLI_RELATIONSHIP,
            "desktop_managed_runtime_detected": bool(artifact.get("desktop_managed_runtime_detected")),
            "desktop_managed_runtime_owner": artifact.get("desktop_managed_runtime_owner", ""),
            "desktop_managed_runtime_policy": artifact.get("desktop_managed_runtime_policy", ""),
            "desktop_managed_runtime_is_user_installed_cli": artifact.get("desktop_managed_runtime_is_user_installed_cli"),
            "runtime_consumer": artifact.get("runtime_consumer", "claude_code_cli"),
            "body_storage_owner": artifact.get("body_storage_owner", BODY_STORAGE_OWNER),
            "conversation_origin": artifact.get("conversation_origin", "claude_code_cli"),
            "desktop_metadata_policy": artifact.get("desktop_metadata_policy", ""),
            "desktop_metadata_is_conversation_body": False,
            "co_source_systems": artifact.get("co_source_systems", []),
        })
    return {
        "ok": True,
        "source_system": SOURCE_SYSTEM,
        "sessions_root": str(claude_code_projects_root()),
        "discovered": len(artifacts),
        "changed": changed,
        "would_change": would_change,
        "window_bindings_registered": len(window_bindings),
        "window_bindings": window_bindings,
        "window_binding_skipped": window_binding_skipped,
        "dry_run": dry_run,
        "items": items,
    }


def status() -> dict[str, Any]:
    artifacts = discover_sessions(limit=20)
    interval_ms = watcher_interval_milliseconds()
    complete_count = sum(1 for item in artifacts if item.get("complete_conversation_candidate"))
    desktop_metadata_count = sum(1 for item in artifacts if item.get("desktop_session_metadata_detected"))
    desktop_entrypoint_count = sum(1 for item in artifacts if item.get("desktop_entrypoint_detected"))
    desktop_entrypoint_complete_count = sum(
        1
        for item in artifacts
        if item.get("desktop_entrypoint_detected") and item.get("complete_conversation_candidate")
    )
    desktop_runtime_detected = desktop_managed_runtime_detected()
    user_only_count = sum(
        1
        for item in artifacts
        if item.get("user_message_count") and not item.get("assistant_message_count")
    )
    raw_sync = raw_sync_snapshot(limit=20)
    return {
        "ok": True,
        "source_system": SOURCE_SYSTEM,
        "sessions_root": _public_path_label(str(claude_code_projects_root())),
        "reachable": claude_code_projects_root().exists(),
        "artifact_count_sample": len(artifacts),
        "latest": [public_artifact(item) for item in artifacts[:5]],
        "read_only": True,
        "source_kind": "claude_code_cli_session_records",
        "collector_status": "continuous_incremental",
        "capture_independent_of_mcp": True,
        "consumer_connection_required": False,
        "storage_owner": "claude_code_cli",
        "body_storage_owner": BODY_STORAGE_OWNER,
        "conversation_origin": "claude_code_cli_or_desktop_managed_claude_code_session",
        "runtime_consumer": "claude_code_cli_or_desktop_managed_claude_code_runtime",
        "desktop_installer_includes_cli": DESKTOP_INSTALLER_INCLUDES_CLI,
        "cli_installation_boundary": CLI_INSTALLATION_BOUNDARY,
        "desktop_cli_relationship": DESKTOP_CLI_RELATIONSHIP,
        "user_installed_cli_independent": True,
        "user_installed_path_cli_required": False,
        "desktop_shell_owner": "claude_desktop" if (desktop_metadata_count or desktop_entrypoint_count) else "",
        "desktop_code_sessions_root": _public_path_label(str(claude_desktop_code_sessions_root())),
        "desktop_session_metadata_count": desktop_metadata_count,
        "desktop_entrypoint_session_count": desktop_entrypoint_count,
        "desktop_entrypoint_complete_conversation_count": desktop_entrypoint_complete_count,
        "desktop_entrypoint_policy": DESKTOP_ENTRYPOINT_POLICY,
        "desktop_managed_runtime_root": _public_path_label(str(claude_desktop_code_runtime_root())),
        "desktop_managed_runtime_detected": desktop_runtime_detected,
        "desktop_managed_runtime_owner": DESKTOP_MANAGED_RUNTIME_OWNER if desktop_runtime_detected else "",
        "desktop_managed_runtime_policy": DESKTOP_MANAGED_RUNTIME_POLICY,
        "desktop_managed_runtime_is_user_installed_cli": False if desktop_runtime_detected else None,
        "desktop_metadata_policy": DESKTOP_METADATA_POLICY,
        "desktop_metadata_is_conversation_body": False,
        "coverage_boundary": COVERAGE_BOUNDARY,
        "raw_body_readiness": "complete_conversation_verified" if complete_count else "no_complete_conversation_candidate_found",
        "complete_conversation_candidate_count": complete_count,
        "user_only_candidate_count": user_only_count,
        "assistant_reply_persistence": "verified" if complete_count else "unverified",
        "current_window_memory_registerable": bool(complete_count),
        "raw_sync": raw_sync,
        "event_driven_preferred": True,
        "poll_interval_milliseconds": interval_ms,
        "poll_interval_seconds": interval_ms / 1000.0,
        "target_latency_milliseconds": interval_ms,
        "millisecond_level": interval_ms < 1000,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Claude Code CLI local session connector")
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
