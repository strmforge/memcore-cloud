import json
import os
import sqlite3
import sys
import time
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _legacy_local_relay_token() -> str:
    return "cc" + "switch"


def _legacy_local_relay_dashed() -> str:
    return "cc" + "-switch"


def _legacy_local_relay_display() -> str:
    return "CC" + " Switch"


def _legacy_local_relay_raw_format() -> str:
    return f"{_legacy_local_relay_token()}_claude_provider_projects_jsonl"


def _append_jsonl(path, records):
    with path.open("a", encoding="utf-8") as f:
        for record in records:
            if isinstance(record, str):
                f.write(record + "\n")
            else:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _write_codex_session(tmp_path, *, assistant=True, bad_line=False, oversize=False):
    sessions = tmp_path / "codex-sessions" / "2026" / "06" / "07"
    sessions.mkdir(parents=True)
    session_path = sessions / "rollout-2026-06-07T10-00-00-019e-test-raw-guardian.jsonl"
    records = [
        {
            "timestamp": "2026-06-07T10:00:00Z",
            "type": "session_meta",
            "payload": {
                "id": "019e-test-raw-guardian",
                "cwd": str(tmp_path / "project"),
            },
        },
        {
            "timestamp": "2026-06-07T10:00:01Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "守住原始记录。"}],
            },
        },
    ]
    if bad_line:
        records.append('{"type":"response_item","payload":')
    if assistant:
        records.append({
            "timestamp": "2026-06-07T10:00:02Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "已镜像 raw，并可回源。"}],
            },
        })
    if oversize:
        records.append({
            "timestamp": "2026-06-07T10:00:03Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "x" * 2048}],
            },
        })
    _append_jsonl(session_path, records)
    session_index = tmp_path / "session_index.jsonl"
    session_index.write_text(json.dumps({
        "id": "019e-test-raw-guardian",
        "thread_name": "Raw Guardian",
    }, ensure_ascii=False) + "\n", encoding="utf-8")
    return sessions.parent.parent.parent, session_index, session_path


def _configure_env(monkeypatch, tmp_path, codex_sessions, session_index):
    memcore_root = tmp_path / "memcore"
    monkeypatch.setenv("MEMCORE_ROOT", str(memcore_root))
    monkeypatch.setenv("MEMCORE_CONFIG", str(ROOT / "config" / "memcore.json"))
    monkeypatch.setenv("CODEX_SESSIONS_DIR", str(codex_sessions))
    monkeypatch.setenv("CODEX_SESSION_INDEX", str(session_index))
    monkeypatch.setenv("CLAUDE_CODE_PROJECTS_DIR", str(tmp_path / "missing-claude-projects"))
    monkeypatch.setenv("OPENCLAW_AGENTS_DIR", str(tmp_path / "missing-openclaw-agents"))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "missing-hermes-home"))
    monkeypatch.setenv("MEMCORE_RECORDS_DB", str(tmp_path / "records.db"))
    return memcore_root


def _write_kiro_session(path, messages):
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "workspace": {"name": path.parent.name},
        "messages": [
            {
                "message": {
                    "id": item["id"],
                    "role": item["role"],
                    "content": item["content"],
                    "createdAt": item.get("created_at", "2026-06-08T01:00:00Z"),
                }
            }
            for item in messages
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _configure_kiro_guardian_env(monkeypatch, tmp_path, session_root):
    memcore_root = tmp_path / "memcore"
    monkeypatch.setenv("MEMCORE_ROOT", str(memcore_root))
    monkeypatch.setenv("MEMCORE_CONFIG", str(ROOT / "config" / "memcore.json"))
    monkeypatch.setenv("MEMCORE_RECORDS_DB", str(tmp_path / "records.db"))
    monkeypatch.setenv("CODEX_SESSIONS_DIR", str(tmp_path / "missing-codex-sessions"))
    monkeypatch.setenv("CODEX_SESSION_INDEX", str(tmp_path / "missing-codex-index.jsonl"))
    monkeypatch.setenv("CLAUDE_CODE_PROJECTS_DIR", str(tmp_path / "missing-claude-projects"))
    monkeypatch.setenv("CLAUDE_DESKTOP_HOME", str(tmp_path / "missing-claude-desktop"))
    monkeypatch.setenv("CLAUDE_DESKTOP_LOG_HOME", str(tmp_path / "missing-claude-logs"))
    monkeypatch.setenv("CLAUDE_EXPORT_DIR", str(tmp_path / "missing-claude-exports"))
    monkeypatch.setenv("LOCAL_RELAY_HOME", str(tmp_path / "missing-local_relay"))
    monkeypatch.setenv("OPENCLAW_AGENTS_DIR", str(tmp_path / "missing-openclaw-agents"))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "missing-hermes-home"))
    monkeypatch.setenv("KIRO_WORKSPACE_SESSIONS_DIR", str(session_root))
    monkeypatch.setenv("APPDATA", str(tmp_path / "home" / "AppData" / "Roaming"))
    return memcore_root


def _write_claude_desktop_authorized_raw(tmp_path, monkeypatch, *, assistant=True, source_exists=True):
    memcore_root = tmp_path / "memcore"
    monkeypatch.setenv("MEMCORE_ROOT", str(memcore_root))
    monkeypatch.setenv("MEMCORE_CONFIG", str(ROOT / "config" / "memcore.json"))
    monkeypatch.setenv("MEMCORE_RECORDS_DB", str(tmp_path / "records.db"))
    monkeypatch.setenv("CODEX_SESSIONS_DIR", str(tmp_path / "missing-codex-sessions"))
    monkeypatch.setenv("CODEX_SESSION_INDEX", str(tmp_path / "missing-codex-index.jsonl"))
    monkeypatch.setenv("CLAUDE_CODE_PROJECTS_DIR", str(tmp_path / "missing-claude-projects"))
    monkeypatch.setenv("OPENCLAW_AGENTS_DIR", str(tmp_path / "missing-openclaw-agents"))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "missing-hermes-home"))
    monkeypatch.setenv("KIRO_WORKSPACE_SESSIONS_DIR", str(tmp_path / "missing-kiro-workspace-sessions"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "missing-appdata"))
    monkeypatch.setenv("COMPUTERNAME", "DESKTOP-CLAUDE-TEST")

    source_path = tmp_path / "Claude" / "IndexedDB" / "https_claude.ai_0.indexeddb.leveldb" / "000001.log"
    if source_exists:
        source_path.parent.mkdir(parents=True)
        source_path.write_bytes(b"authorized parser source fragment")

    raw_path = (
        memcore_root
        / "memory"
        / "DESKTOP-CLAUDE-TEST"
        / "claude_desktop"
        / "claude_desktop_authorized_local_store_jsonl"
        / "claude-official-guardian"
        / "claude-official-guardian.jsonl"
    )
    raw_path.parent.mkdir(parents=True)
    records = [
        {
            "timestamp": "2026-06-07T10:10:00Z",
            "id": "msg-user-1",
            "type": "response_item",
            "source_system": "claude_desktop",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "Claude Desktop raw user"}],
            },
            "source_refs": {
                "source_system": "claude_desktop",
                "source_path": str(source_path),
                "canonical_window_id": "claude-official-guardian",
                "session_id": "claude-official-guardian",
                "raw_session_path": str(raw_path),
                "native_artifact_format": "claude_desktop_authorized_local_store_jsonl",
            },
        },
    ]
    if assistant:
        records.append({
            "timestamp": "2026-06-07T10:10:01Z",
            "id": "msg-assistant-1",
            "type": "response_item",
            "source_system": "claude_desktop",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "Claude Desktop raw assistant"}],
            },
            "source_refs": {
                "source_system": "claude_desktop",
                "source_path": str(source_path),
                "canonical_window_id": "claude-official-guardian",
                "session_id": "claude-official-guardian",
                "raw_session_path": str(raw_path),
                "native_artifact_format": "claude_desktop_authorized_local_store_jsonl",
            },
        })
    _append_jsonl(raw_path, records)
    return raw_path, source_path


def _write_claude_desktop_projects_jsonl_raw(
    tmp_path,
    monkeypatch,
    *,
    raw_format="claude_projects_jsonl_desktop_entrypoint",
    session_id="desktop-entrypoint-visible-session",
):
    memcore_root = tmp_path / "memcore"
    monkeypatch.setenv("MEMCORE_ROOT", str(memcore_root))
    monkeypatch.setenv("MEMCORE_CONFIG", str(ROOT / "config" / "memcore.json"))
    monkeypatch.setenv("MEMCORE_RECORDS_DB", str(tmp_path / "records.db"))
    monkeypatch.setenv("CODEX_SESSIONS_DIR", str(tmp_path / "missing-codex-sessions"))
    monkeypatch.setenv("CODEX_SESSION_INDEX", str(tmp_path / "missing-codex-index.jsonl"))
    monkeypatch.setenv("CLAUDE_CODE_PROJECTS_DIR", str(tmp_path / "missing-claude-projects"))
    monkeypatch.setenv("OPENCLAW_AGENTS_DIR", str(tmp_path / "missing-openclaw-agents"))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "missing-hermes-home"))
    monkeypatch.setenv("KIRO_WORKSPACE_SESSIONS_DIR", str(tmp_path / "missing-kiro-workspace-sessions"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "missing-appdata"))
    monkeypatch.setenv("COMPUTERNAME", "DESKTOP-CLAUDE-PROJECTS")

    source_path = tmp_path / ".claude" / "projects" / "-Users-example-orchestration_system" / f"{session_id}.jsonl"
    source_path.parent.mkdir(parents=True)
    records = [
        {
            "type": "user",
            "entrypoint": "claude-desktop",
            "sessionId": session_id,
            "message": {"role": "user", "content": "Claude projects JSONL source user"},
        },
        {
            "type": "assistant",
            "entrypoint": "claude-desktop",
            "sessionId": session_id,
            "message": {"role": "assistant", "content": "Claude projects JSONL source assistant"},
        },
    ]
    _append_jsonl(source_path, records)
    raw_path = (
        memcore_root
        / "memory"
        / "DESKTOP-CLAUDE-PROJECTS"
        / "claude_desktop"
        / raw_format
        / session_id
        / f"{session_id}.jsonl"
    )
    raw_path.parent.mkdir(parents=True)
    raw_path.write_text(source_path.read_text(encoding="utf-8"), encoding="utf-8")
    meta = {
        "source_system": "claude_desktop",
        "source_path": str(source_path),
        "archived_to": str(raw_path),
        "native_artifact_format": raw_format,
        "raw_archive_layout": "computer_first",
        "session_id": session_id,
        "canonical_window_id": session_id,
        "body_storage_owner": "claude_code_session_store",
        "conversation_origin": "claude_desktop_entrypoint_claude_code_session",
        "runtime_consumer": "claude_desktop_managed_claude_code_runtime",
        "desktop_entrypoint_detected": True,
        "desktop_metadata_is_conversation_body": False,
    }
    Path(str(raw_path) + ".meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return raw_path, source_path, session_id


def _write_local_relay_claude_desktop_proxy_db(tmp_path, monkeypatch):
    local_relay_home = tmp_path / "local-relay"
    local_relay_home.mkdir()
    db_path = local_relay_home / "local-relay.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE proxy_request_logs (
                request_id TEXT PRIMARY KEY,
                app_type TEXT NOT NULL,
                model TEXT NOT NULL,
                request_model TEXT,
                status_code INTEGER NOT NULL,
                session_id TEXT,
                created_at INTEGER NOT NULL,
                data_source TEXT NOT NULL DEFAULT 'proxy'
            )
            """
        )
        conn.execute(
            """
            INSERT INTO proxy_request_logs
                (request_id, app_type, model, request_model, status_code, session_id, created_at, data_source)
            VALUES
                ('desktop-ok', 'claude-desktop', 'claude-3-5-sonnet', 'claude-3-5-sonnet', 200, 'desktop-session-a', 1780000000, 'proxy'),
                ('desktop-error', 'claude-desktop', 'claude-3-5-sonnet', 'claude-3-7-sonnet', 502, 'desktop-session-a', 1780000010, 'proxy'),
                ('claude-code-unrelated', 'claude', 'claude-3-5-sonnet', 'claude-3-5-sonnet', 200, 'code-session-a', 1780000020, 'proxy')
            """
        )
        conn.commit()
    finally:
        conn.close()
    monkeypatch.setenv("CLAUDE_DESKTOP_HOME", str(tmp_path / "missing-claude-desktop"))
    monkeypatch.setenv("CLAUDE_DESKTOP_LOG_HOME", str(tmp_path / "missing-claude-logs"))
    monkeypatch.setenv("CLAUDE_EXPORT_DIR", str(tmp_path / "missing-claude-exports"))
    monkeypatch.setenv("LOCAL_RELAY_HOME", str(local_relay_home))
    monkeypatch.delenv("LOCAL_RELAY_DB", raising=False)
    return db_path


def _write_claude_desktop_entrypoint_code_session(tmp_path, monkeypatch):
    memcore_root = tmp_path / "memcore"
    projects_root = tmp_path / "claude-projects"
    project_dir = projects_root / "-Users-example-orchestration_system"
    project_dir.mkdir(parents=True)
    session_id = "9ae36939-9285-4683-a229-e9a1665a3cfe"
    source_path = project_dir / f"{session_id}.jsonl"
    _append_jsonl(
        source_path,
        [
            {
                "type": "user",
                "entrypoint": "claude-desktop",
                "sessionId": session_id,
                "uuid": "desktop-user-guardian",
                "cwd": str(tmp_path / "Projects" / "orchestration_system"),
                "timestamp": "2026-06-01T02:41:55Z",
                "message": {
                    "role": "user",
                    "content": "Claude Desktop entrypoint user body in Claude Code JSONL.",
                },
            },
            {
                "type": "assistant",
                "entrypoint": "claude-desktop",
                "sessionId": session_id,
                "uuid": "desktop-assistant-guardian",
                "parentUuid": "desktop-user-guardian",
                "cwd": str(tmp_path / "Projects" / "orchestration_system"),
                "timestamp": "2026-06-01T02:48:44Z",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Claude Desktop entrypoint assistant body in Claude Code JSONL."}],
                },
            },
        ],
    )
    monkeypatch.setenv("MEMCORE_ROOT", str(memcore_root))
    monkeypatch.setenv("MEMCORE_CONFIG", str(ROOT / "config" / "memcore.json"))
    monkeypatch.setenv("MEMCORE_RECORDS_DB", str(tmp_path / "records.db"))
    monkeypatch.setenv("CODEX_SESSIONS_DIR", str(tmp_path / "missing-codex-sessions"))
    monkeypatch.setenv("CODEX_SESSION_INDEX", str(tmp_path / "missing-codex-index.jsonl"))
    monkeypatch.setenv("CLAUDE_CODE_PROJECTS_DIR", str(projects_root))
    monkeypatch.setenv("CLAUDE_DESKTOP_CODE_SESSIONS_DIR", str(tmp_path / "missing-claude-code-sessions"))
    monkeypatch.setenv("OPENCLAW_AGENTS_DIR", str(tmp_path / "missing-openclaw-agents"))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "missing-hermes-home"))
    monkeypatch.setenv("COMPUTERNAME", "DESKTOP-ENTRYPOINT-TEST")
    return source_path, session_id


def _write_openclaw_source_and_raw(tmp_path, monkeypatch, *, raw=True):
    memcore_root = tmp_path / "memcore"
    openclaw_agents = tmp_path / "openclaw" / "agents"
    sessions_dir = openclaw_agents / "main" / "sessions"
    sessions_dir.mkdir(parents=True)
    source_path = sessions_dir / "openclaw-guardian.jsonl"
    records = [
        {
            "traceSchema": "openclaw-trajectory",
            "type": "model.completed",
            "sessionId": "openclaw-guardian",
            "data": {
                "messagesSnapshot": [
                    {"role": "user", "content": [{"type": "text", "text": "OpenClaw user"}]},
                    {"role": "assistant", "content": [{"type": "text", "text": "OpenClaw assistant"}]},
                ]
            },
        }
    ]
    _append_jsonl(source_path, records)
    monkeypatch.setenv("MEMCORE_ROOT", str(memcore_root))
    monkeypatch.setenv("MEMCORE_CONFIG", str(ROOT / "config" / "memcore.json"))
    monkeypatch.setenv("OPENCLAW_AGENTS_DIR", str(openclaw_agents))
    monkeypatch.setenv("CODEX_SESSIONS_DIR", str(tmp_path / "missing-codex-sessions"))
    monkeypatch.setenv("CODEX_SESSION_INDEX", str(tmp_path / "missing-codex-index.jsonl"))
    monkeypatch.setenv("CLAUDE_CODE_PROJECTS_DIR", str(tmp_path / "missing-claude-projects"))
    raw_path = (
        memcore_root
        / "memory"
        / "local"
        / "openclaw"
        / "openclaw_session_jsonl"
        / "main"
        / "openclaw-guardian.jsonl"
    )
    if raw:
        raw_path.parent.mkdir(parents=True)
        _append_jsonl(raw_path, records)
    return source_path, raw_path


def _write_hermes_state_db(tmp_path, monkeypatch):
    memcore_root = tmp_path / "memcore"
    hermes_home = tmp_path / "hermes"
    hermes_home.mkdir()
    state_db = hermes_home / "state.db"
    con = sqlite3.connect(state_db)
    try:
        con.execute(
            "CREATE TABLE sessions (id TEXT PRIMARY KEY, source TEXT, user_id TEXT, model TEXT, model_config TEXT, system_prompt TEXT, parent_session_id TEXT, started_at REAL)"
        )
        con.execute(
            "CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, role TEXT NOT NULL, content TEXT, tool_call_id TEXT, tool_calls TEXT, timestamp INTEGER)"
        )
        con.execute(
            "INSERT INTO sessions (id, source, started_at) VALUES ('hermes-guardian', 'cli', 1)"
        )
        con.execute(
            "INSERT INTO messages (session_id, role, content, timestamp) VALUES ('hermes-guardian', 'user', 'Hermes user', 1)"
        )
        con.execute(
            "INSERT INTO messages (session_id, role, content, timestamp) VALUES ('hermes-guardian', 'assistant', 'Hermes assistant', 2)"
        )
        con.execute(
            "INSERT INTO sessions (id, source, started_at) VALUES ('hermes-second', 'cli', 3)"
        )
        con.execute(
            "INSERT INTO messages (session_id, role, content, timestamp) VALUES ('hermes-second', 'user', 'Hermes second user', 3)"
        )
        con.execute(
            "INSERT INTO messages (session_id, role, content, timestamp) VALUES ('hermes-second', 'assistant', 'Hermes second assistant', 4)"
        )
        con.commit()
    finally:
        con.close()
    monkeypatch.setenv("MEMCORE_ROOT", str(memcore_root))
    monkeypatch.setenv("MEMCORE_CONFIG", str(ROOT / "config" / "memcore.json"))
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setenv("CODEX_SESSIONS_DIR", str(tmp_path / "missing-codex-sessions"))
    monkeypatch.setenv("CODEX_SESSION_INDEX", str(tmp_path / "missing-codex-index.jsonl"))
    monkeypatch.setenv("CLAUDE_CODE_PROJECTS_DIR", str(tmp_path / "missing-claude-projects"))
    return state_db


def test_scan_jsonl_record_detects_codex_user_and_assistant(tmp_path):
    from raw_record_guardian import scan_jsonl_record

    codex_sessions, _, session_path = _write_codex_session(tmp_path)
    assert codex_sessions.exists()

    result = scan_jsonl_record(session_path, source_system="codex")

    assert result["health_status"] == "ok"
    assert result["metadata_ok"] is True
    assert result["has_user_and_assistant"] is True
    assert result["user_turn_count"] == 1
    assert result["assistant_turn_count"] == 1
    assert result["bad_json_line_count"] == 0


def test_scan_jsonl_record_detects_openclaw_messages_snapshot_roles(tmp_path):
    from raw_record_guardian import scan_jsonl_record

    path = tmp_path / "openclaw.jsonl"
    _append_jsonl(path, [
        {
            "traceSchema": "openclaw-trajectory",
            "type": "model.completed",
            "data": {
                "messagesSnapshot": [
                    {"role": "user", "content": [{"type": "text", "text": "hello"}]},
                    {"role": "assistant", "content": [{"type": "text", "text": "world"}]},
                ]
            },
        }
    ])

    result = scan_jsonl_record(path, source_system="openclaw")

    assert result["health_status"] == "ok"
    assert result["user_turn_count"] == 1
    assert result["assistant_turn_count"] == 1
    assert result["has_user_and_assistant"] is True


def test_raw_record_guardian_counts_claude_desktop_authorized_raw_as_guarded(tmp_path, monkeypatch):
    import raw_record_guardian

    raw_path, source_path = _write_claude_desktop_authorized_raw(tmp_path, monkeypatch)

    report = raw_record_guardian.build_guardian_status(limit=20, include_gaps=True, public=False)

    claude_items = [item for item in report["records"] if item["source_system"] == "claude_desktop"]
    assert len(claude_items) == 1
    item = claude_items[0]
    assert item["artifact_type"] == "claude_desktop_authorized_local_store_jsonl"
    assert item["guard_status"] == "record_guarded"
    assert item["raw_current"] is True
    assert item["recoverable_from_raw"] is True
    assert item["source_path"] == str(source_path)
    assert item["raw_path"] == str(raw_path)
    assert item["source_scan"]["source_evidence_kind"] == "source_refs_in_authorized_claude_desktop_raw"
    assert item["raw_scan"]["user_turn_count"] == 1
    assert item["raw_scan"]["assistant_turn_count"] == 1
    assert "claude_desktop" in report["guarded_sources"]
    assert "claude_desktop" not in report["gap_sources"]


def test_raw_record_guardian_counts_claude_desktop_projects_jsonl_as_guarded(tmp_path, monkeypatch):
    import raw_record_guardian

    raw_path, source_path, session_id = _write_claude_desktop_projects_jsonl_raw(tmp_path, monkeypatch)

    report = raw_record_guardian.build_guardian_status(limit=20, include_gaps=True, public=False)

    claude_items = [
        item for item in report["records"]
        if item["source_system"] == "claude_desktop"
        and item["artifact_type"] == "claude_projects_jsonl_desktop_entrypoint"
    ]
    assert len(claude_items) == 1
    item = claude_items[0]
    assert item["session_id"] == session_id
    assert item["guard_status"] == "record_guarded"
    assert item["raw_current"] is True
    assert item["recoverable_from_raw"] is True
    assert item["source_path"] == str(source_path)
    assert item["raw_path"] == str(raw_path)
    assert item["source_scan"]["source_evidence_kind"] == "source_refs_in_authorized_claude_desktop_raw"
    assert item["raw_scan"]["user_turn_count"] == 1
    assert item["raw_scan"]["assistant_turn_count"] == 1
    assert "claude_desktop" in report["guarded_sources"]
    assert "claude_desktop" not in report["gap_sources"]
    evidence = report["claude_desktop_evidence"]
    assert evidence["body_guarded"] is True
    assert evidence["authorized_raw_guarded_count"] == 1


def test_raw_record_guardian_keeps_legacy_claude_desktop_projects_jsonl_as_guarded(tmp_path, monkeypatch):
    import raw_record_guardian

    raw_path, source_path, session_id = _write_claude_desktop_projects_jsonl_raw(
        tmp_path,
        monkeypatch,
        raw_format=_legacy_local_relay_raw_format(),
        session_id="legacy-desktop-entrypoint-session",
    )

    report = raw_record_guardian.build_guardian_status(limit=20, include_gaps=True, public=False)

    claude_items = [
        item for item in report["records"]
        if item["source_system"] == "claude_desktop"
        and item["artifact_type"] == _legacy_local_relay_raw_format()
    ]
    assert len(claude_items) == 1
    item = claude_items[0]
    assert item["session_id"] == session_id
    assert item["guard_status"] == "record_guarded"
    assert item["raw_current"] is True
    assert item["recoverable_from_raw"] is True
    assert item["source_path"] == str(source_path)
    assert item["raw_path"] == str(raw_path)
    assert "claude_desktop" in report["guarded_sources"]

    public_report = raw_record_guardian.build_guardian_status(limit=20, include_gaps=True, public=True)
    public_payload = json.dumps(public_report, ensure_ascii=False)
    assert _legacy_local_relay_display() not in public_payload
    assert _legacy_local_relay_dashed() not in public_payload
    assert _legacy_local_relay_token() not in public_payload

    public_index = raw_record_guardian.build_guardian_status(
        limit=20,
        include_gaps=False,
        write_index=True,
        public=True,
    )
    public_query = raw_record_guardian.query_records_index(
        source_system="claude_desktop",
        session_id=session_id,
        db_path=public_index["index_update"]["db_path"],
        public=True,
    )
    public_index_payload = json.dumps(public_query, ensure_ascii=False)
    assert _legacy_local_relay_token() not in public_index_payload
    assert _legacy_local_relay_raw_format() not in public_index_payload
    assert "claude_projects_jsonl_desktop_entrypoint" in public_index_payload


def test_raw_record_guardian_keeps_claude_desktop_user_only_raw_partial(tmp_path, monkeypatch):
    import raw_record_guardian

    _write_claude_desktop_authorized_raw(tmp_path, monkeypatch, assistant=False)

    report = raw_record_guardian.build_guardian_status(limit=20, include_gaps=True, public=False)

    item = next(item for item in report["records"] if item["source_system"] == "claude_desktop")
    assert item["guard_status"] == "raw_partial_conversation"
    assert item["raw_current"] is False
    assert item["recoverable_from_raw"] is False
    assert item["raw_scan"]["user_turn_count"] == 1
    assert item["raw_scan"]["assistant_turn_count"] == 0
    assert "claude_desktop" in report["guarded_sources"]
    assert "claude_desktop" not in report["gap_sources"]


def test_raw_record_guardian_marks_authorized_raw_with_missing_source_as_lost_source(tmp_path, monkeypatch):
    import raw_record_guardian

    _write_claude_desktop_authorized_raw(tmp_path, monkeypatch, source_exists=False)

    report = raw_record_guardian.build_guardian_status(limit=20, include_gaps=True, public=False)

    item = next(item for item in report["records"] if item["source_system"] == "claude_desktop")
    assert item["guard_status"] == "authorized_raw_recoverable_source_missing"
    assert item["origin_status"] == "lost_source"
    assert item["origin_label"] == "遗失源"
    assert item["origin_seen"] is False
    assert item["recoverable_from_raw"] is True
    assert report["summary"]["lost_source_count"] == 1
    assert report["summary"]["raw_without_origin_count"] == 1
    assert report["summary"]["recoverable_origin_count"] == 1


def test_full_guardian_treats_retained_raw_after_platform_source_deletion_as_recoverable(tmp_path, monkeypatch):
    import raw_record_guardian

    source_path, _raw_path = _write_openclaw_source_and_raw(tmp_path, monkeypatch, raw=True)
    source_path.unlink()
    monkeypatch.setattr(
        raw_record_guardian,
        "_openclaw_source_artifacts",
        lambda _limit: [{
            "source_system": "openclaw",
            "artifact_type": "openclaw_session_jsonl",
            "session_id": "openclaw-guardian",
            "canonical_window_id": "main",
            "agent_id": "main",
            "source_path": str(source_path),
        }],
    )

    report = raw_record_guardian.build_guardian_status(
        limit=20,
        include_gaps=False,
        scan_mode="fast",
        public=False,
        source_systems=["openclaw"],
    )

    item = next(item for item in report["records"] if item["source_system"] == "openclaw")
    assert item["origin_status"] == "lost_source"
    assert item["guard_status"] == "source_missing_recoverable_from_raw"
    assert item["recoverable_from_raw"] is True
    assert report["summary"]["lost_source_recoverable_count"] == 1
    assert report["summary"]["lost_source_unrecoverable_count"] == 0
    assert report["summary"]["raw_attention_count"] == 0
    assert report["ok"] is True


def test_raw_record_guardian_leaves_claude_desktop_gap_without_authorized_raw(tmp_path, monkeypatch):
    import raw_record_guardian

    monkeypatch.setenv("MEMCORE_ROOT", str(tmp_path / "memcore"))
    monkeypatch.setenv("MEMCORE_CONFIG", str(ROOT / "config" / "memcore.json"))
    monkeypatch.setenv("CODEX_SESSIONS_DIR", str(tmp_path / "missing-codex-sessions"))
    monkeypatch.setenv("CODEX_SESSION_INDEX", str(tmp_path / "missing-codex-index.jsonl"))
    monkeypatch.setenv("CLAUDE_CODE_PROJECTS_DIR", str(tmp_path / "missing-claude-projects"))
    monkeypatch.setenv("CLAUDE_DESKTOP_HOME", str(tmp_path / "missing-claude-desktop"))
    monkeypatch.setenv("CLAUDE_DESKTOP_LOG_HOME", str(tmp_path / "missing-claude-logs"))
    monkeypatch.setenv("CLAUDE_EXPORT_DIR", str(tmp_path / "missing-claude-exports"))
    monkeypatch.setenv("LOCAL_RELAY_HOME", str(tmp_path / "missing-local-relay"))
    monkeypatch.delenv("LOCAL_RELAY_DB", raising=False)

    report = raw_record_guardian.build_guardian_status(limit=20, include_gaps=True, public=False)

    assert not [item for item in report["records"] if item["source_system"] == "claude_desktop"]
    gap = next(item for item in report["gaps"] if item["source_system"] == "claude_desktop")
    assert gap["guard_status"] == "entry_detected_body_unverified"
    assert gap["reason"] == "ordinary_desktop_chat_body_not_verified"
    assert gap["relay_gateway_request_log_detected"] is False
    assert gap["relay_gateway_request_count"] == 0
    assert "claude_desktop" in report["gap_sources"]


def test_raw_record_guardian_reports_local_relay_proxy_log_as_entry_evidence_not_guarded_body(tmp_path, monkeypatch):
    import raw_record_guardian

    monkeypatch.setenv("MEMCORE_ROOT", str(tmp_path / "memcore"))
    monkeypatch.setenv("MEMCORE_CONFIG", str(ROOT / "config" / "memcore.json"))
    monkeypatch.setenv("CODEX_SESSIONS_DIR", str(tmp_path / "missing-codex-sessions"))
    monkeypatch.setenv("CODEX_SESSION_INDEX", str(tmp_path / "missing-codex-index.jsonl"))
    monkeypatch.setenv("CLAUDE_CODE_PROJECTS_DIR", str(tmp_path / "missing-claude-projects"))
    _write_local_relay_claude_desktop_proxy_db(tmp_path, monkeypatch)

    report = raw_record_guardian.build_guardian_status(limit=20, include_gaps=True, public=False)

    assert not [item for item in report["records"] if item["source_system"] == "claude_desktop"]
    gap = next(item for item in report["gaps"] if item["source_system"] == "claude_desktop")
    assert gap["guard_status"] == "entry_detected_body_unverified"
    assert gap["reason"] == "ordinary_desktop_chat_body_not_verified"
    assert gap["raw_body_readiness"] == "no_conversation_body_candidate_found"
    assert gap["relay_gateway_request_log_detected"] is True
    assert gap["relay_gateway_request_count"] == 2
    assert gap["relay_gateway_latest_status_code"] == 502
    assert gap["relay_gateway_visibility_boundary"] == "request_metadata_not_chat_body"
    assert "claude_desktop" in report["gap_sources"]
    evidence = report["claude_desktop_evidence"]
    assert evidence["body_guarded"] is False
    assert evidence["body_guarded_count"] == 0
    assert evidence["proxy_request_evidence_detected"] is True
    assert evidence["proxy_request_evidence_count"] == 2
    assert evidence["proxy_request_log_is_conversation_body"] is False


def test_raw_record_guardian_counts_claude_desktop_entrypoint_code_jsonl_as_desktop_guarded(tmp_path, monkeypatch):
    import claude_code_local_connector
    import raw_record_guardian

    source_path, session_id = _write_claude_desktop_entrypoint_code_session(tmp_path, monkeypatch)
    scan = claude_code_local_connector.scan_sessions(dry_run=False, limit=20)
    assert scan["changed"] == 1

    report = raw_record_guardian.build_guardian_status(limit=20, include_gaps=True, public=False)

    item = next(item for item in report["records"] if item["source_system"] == "claude_code_cli")
    assert item["session_id"] == session_id
    assert item["source_path"] == str(source_path)
    assert item["guard_status"] == "record_guarded"
    assert item["raw_current"] is True
    assert item["recoverable_from_raw"] is True
    assert item["co_source_systems"] == ["claude_desktop"]
    assert item["conversation_origin"] == "claude_desktop_entrypoint_claude_code_session"
    assert item["desktop_entrypoint_detected"] is True
    assert item["desktop_metadata_is_conversation_body"] is False
    assert item["source_scan"]["user_turn_count"] == 1
    assert item["source_scan"]["assistant_turn_count"] == 1
    assert "claude_desktop" in report["guarded_sources"]
    assert "claude_desktop" not in report["gap_sources"]
    evidence = report["claude_desktop_evidence"]
    assert evidence["body_guarded"] is True
    assert evidence["body_guarded_count"] == 1
    assert evidence["entrypoint_jsonl_guarded_count"] == 1
    assert evidence["entrypoint_jsonl_is_full_body"] is True
    assert evidence["metadata_is_conversation_body"] is False
    assert evidence["proxy_request_log_is_conversation_body"] is False


def test_raw_record_guardian_guards_openclaw_source_raw_pair(tmp_path, monkeypatch):
    import raw_record_guardian

    source_path, raw_path = _write_openclaw_source_and_raw(tmp_path, monkeypatch, raw=True)

    report = raw_record_guardian.build_guardian_status(limit=20, include_gaps=True, public=False)

    item = next(item for item in report["records"] if item["source_system"] == "openclaw")
    assert item["guard_status"] == "record_guarded"
    assert item["source_path"] == str(source_path)
    assert item["raw_path"] == str(raw_path)
    assert item["raw_archive_layout"] == "computer_first"
    assert item["source_scan"]["user_turn_count"] == 1
    assert item["source_scan"]["assistant_turn_count"] == 1
    assert "openclaw" not in report["gap_sources"]


def test_raw_record_guardian_reports_openclaw_raw_missing_as_record_gap(tmp_path, monkeypatch):
    import raw_record_guardian

    _write_openclaw_source_and_raw(tmp_path, monkeypatch, raw=False)

    report = raw_record_guardian.build_guardian_status(limit=20, include_gaps=True, public=False)

    item = next(item for item in report["records"] if item["source_system"] == "openclaw")
    assert item["guard_status"] == "raw_missing"
    assert item["origin_status"] == "lost_raw"
    assert item["origin_label"] == "遗失 raw"
    assert item["origin_seen"] is False
    assert item["sync"]["raw_missing"] is True
    assert item["backfill_recommended"] is True
    assert report["summary"]["lost_raw_count"] >= 1
    assert report["summary"]["origin_without_raw_count"] >= 1
    assert "openclaw" not in report["gap_sources"]


def test_openclaw_backfill_retains_raw_after_source_truncation(tmp_path, monkeypatch):
    import raw_record_guardian

    source_path, raw_path = _write_openclaw_source_and_raw(tmp_path, monkeypatch, raw=False)
    first = raw_record_guardian.run_raw_backfill(limit=20, source_systems=["openclaw"])
    assert first["ok"] is True
    archived_bytes = raw_path.read_bytes()
    source_path.write_bytes(b"")

    second = raw_record_guardian.run_raw_backfill(limit=20, source_systems=["openclaw"])
    item = second["results"][0]["result"]["items"][0]

    assert item["status"] == "source_regression_raw_retained"
    assert item["source_regression"] is True
    assert item["raw_shrink_performed"] is False
    assert item["write_performed"] is False
    assert raw_path.read_bytes() == archived_bytes


def test_openclaw_backfill_retains_raw_after_source_divergence_without_generation(tmp_path, monkeypatch):
    import raw_record_guardian

    source_path, raw_path = _write_openclaw_source_and_raw(tmp_path, monkeypatch, raw=True)
    archived_bytes = raw_path.read_bytes()
    source_bytes = source_path.read_bytes()
    source_path.write_bytes(source_bytes.replace(b"OpenClaw assistant", b"Rewritten assistant"))

    second = raw_record_guardian.run_raw_backfill(limit=20, source_systems=["openclaw"])
    item = second["results"][0]["result"]["items"][0]

    assert item["status"] == "source_divergence_raw_retained"
    assert item["source_regression"] is False
    assert item["write_performed"] is False
    assert raw_path.read_bytes() == archived_bytes
    assert not list(raw_path.parent.glob(f"{raw_path.stem}.seg*{raw_path.suffix}"))


def test_raw_record_guardian_compact_records_include_lost_detail_fields(tmp_path, monkeypatch):
    import raw_record_guardian

    source_path, raw_path = _write_openclaw_source_and_raw(tmp_path, monkeypatch, raw=False)

    report = raw_record_guardian.build_guardian_status(
        limit=20,
        include_gaps=True,
        compact=True,
        public=True,
    )

    item = next(item for item in report["records"] if item["source_system"] == "openclaw")
    assert item["guard_status"] == "raw_missing"
    assert item["origin_status"] == "lost_raw"
    assert item["origin_label"] == "遗失 raw"
    assert item["backfill_recommended"] is True
    assert item["recoverable_from_raw"] is False
    assert item["source_exists"] is True
    assert item["raw_exists"] is False
    assert item["source_path_label"] == raw_record_guardian._public_path_label(source_path)
    assert item["raw_path_label"] == raw_record_guardian._public_path_label(raw_path)
    assert item["source_health_status"] in {"ok", "stat_only"}
    assert item["raw_health_status"] == "missing_file"
    assert item["sync"]["raw_missing"] is True


def test_raw_record_guardian_reports_hermes_state_db_source_with_raw_missing(tmp_path, monkeypatch):
    import raw_record_guardian

    state_db = _write_hermes_state_db(tmp_path, monkeypatch)

    report = raw_record_guardian.build_guardian_status(limit=20, include_gaps=True, public=False)

    items = [item for item in report["records"] if item["source_system"] == "hermes"]
    assert len(items) == 2
    item = next(item for item in items if item["session_id"] == "hermes-guardian")
    assert item["guard_status"] == "raw_missing"
    assert item["source_path"] == str(state_db)
    assert item["source_scan"]["source_evidence_kind"] == "sqlite_state_db_read_only_session_counts"
    assert item["source_scan"]["user_turn_count"] == 1
    assert item["source_scan"]["assistant_turn_count"] == 1
    assert item["sync"]["source_storage"] == "sqlite_state_db"
    assert item["backfill_recommended"] is True
    assert "hermes" not in report["gap_sources"]


def test_raw_record_guardian_hermes_backfill_exports_state_db_messages_to_raw(tmp_path, monkeypatch):
    import raw_record_guardian

    _write_hermes_state_db(tmp_path, monkeypatch)

    result = raw_record_guardian.run_raw_backfill(limit=20, source_systems=["hermes"])

    assert result["ok"] is True
    assert result["source_systems"] == ["hermes"]
    assert result["results"][0]["platform_write_performed"] is False
    assert result["results"][0]["changed"] == 2
    first = next(item for item in result["results"][0]["result"]["items"] if item["session_id"] == "hermes-guardian")
    raw_path = Path(first["raw_path"])
    assert raw_path.exists()
    records = [json.loads(line) for line in raw_path.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 2
    assert records[0]["source_system"] == "hermes"
    assert records[0]["payload"]["role"] == "user"
    assert records[0]["source_refs"]["source_storage"] == "sqlite_state_db"
    assert records[0]["source_refs"]["native_artifact_format"] == raw_record_guardian.HERMES_STATE_DB_RAW_FORMAT

    report = raw_record_guardian.build_guardian_status(limit=20, include_gaps=True, public=False)
    item = next(item for item in report["records"] if item["source_system"] == "hermes" and item["session_id"] == "hermes-guardian")
    assert item["guard_status"] == "record_guarded"
    assert item["raw_current"] is True
    assert item["recoverable_from_raw"] is True
    assert item["raw_scan"]["user_turn_count"] == 1
    assert item["raw_scan"]["assistant_turn_count"] == 1


def test_raw_record_guardian_hermes_backfill_is_idempotent_without_new_messages(tmp_path, monkeypatch):
    import raw_record_guardian

    _write_hermes_state_db(tmp_path, monkeypatch)

    first = raw_record_guardian.run_raw_backfill(limit=20, source_systems=["hermes"])
    assert first["ok"] is True
    assert first["results"][0]["changed"] == 2
    first_item = next(
        item for item in first["results"][0]["result"]["items"]
        if item["session_id"] == "hermes-guardian"
    )
    raw_path = Path(first_item["raw_path"])
    first_payload = raw_path.read_text(encoding="utf-8")

    second = raw_record_guardian.run_raw_backfill(limit=20, source_systems=["hermes"])

    assert second["ok"] is True
    assert second["results"][0]["changed"] == 0
    assert raw_path.read_text(encoding="utf-8") == first_payload


def test_hermes_backfill_retains_raw_after_source_messages_are_removed(tmp_path, monkeypatch):
    import raw_record_guardian

    state_db = _write_hermes_state_db(tmp_path, monkeypatch)
    first = raw_record_guardian.run_raw_backfill(limit=20, source_systems=["hermes"])
    item = next(
        value for value in first["results"][0]["result"]["items"]
        if value["session_id"] == "hermes-guardian"
    )
    raw_path = Path(item["raw_path"])
    archived_bytes = raw_path.read_bytes()
    con = sqlite3.connect(state_db)
    try:
        con.execute("DELETE FROM messages WHERE session_id='hermes-guardian' AND role='assistant'")
        con.commit()
    finally:
        con.close()

    second = raw_record_guardian.run_raw_backfill(limit=20, source_systems=["hermes"])
    item = next(
        value for value in second["results"][0]["result"]["items"]
        if value["session_id"] == "hermes-guardian"
    )

    assert item["status"] == "source_regression_raw_retained"
    assert item["source_regression"] is True
    assert item["raw_shrink_performed"] is False
    assert item["write_performed"] is False
    assert raw_path.read_bytes() == archived_bytes


def test_raw_record_backfill_dispatch_reads_runtime_declarations(monkeypatch):
    import raw_record_backfill

    calls = []

    class FakeGuardian:
        GUARDED_CONNECTORS = ()

    monkeypatch.setattr(raw_record_backfill, "_guardian_module", lambda: FakeGuardian)
    monkeypatch.setattr(
        raw_record_backfill,
        "declared_raw_backfill_source_systems",
        lambda: (("declared_source", "declared_kind"),),
    )

    def fake_handler(*, limit, target_raw_paths=None):
        calls.append(limit)
        return {"source_system": "declared_source", "ok": True, "changed": 0}

    monkeypatch.setattr(raw_record_backfill, "RAW_BACKFILL_HANDLERS", {"declared_kind": fake_handler})
    result = raw_record_backfill.run_raw_backfill(limit=7, source_systems=["declared_source"])

    assert calls == [7]
    assert result["ok"] is True
    assert result["source_systems"] == ["declared_source"]


def test_raw_record_backfill_target_allowlist_writes_only_requested_raw(tmp_path, monkeypatch):
    import raw_record_guardian

    source_path, requested_raw = _write_openclaw_source_and_raw(tmp_path, monkeypatch, raw=False)
    extra_source = source_path.with_name("openclaw-extra.jsonl")
    extra_source.write_bytes(source_path.read_bytes().replace(b"openclaw-guardian", b"openclaw-extra"))
    extra_raw = requested_raw.with_name("openclaw-extra.jsonl")

    result = raw_record_guardian.run_raw_backfill(
        limit=20,
        source_systems=["openclaw"],
        target_raw_paths=[str(requested_raw)],
    )

    assert result["ok"] is True
    assert result["targeted_backfill"] is True
    assert result["requested_target_count"] == 1
    assert result["matched_target_count"] == 1
    assert result["unmatched_target_raw_paths"] == []
    assert requested_raw.exists()
    assert not extra_raw.exists()


def test_targeted_connector_backfill_counts_generation_start_as_write(tmp_path, monkeypatch):
    import raw_record_backfill

    source = tmp_path / "source.jsonl"
    source.write_text('{}\n', encoding="utf-8")
    raw = tmp_path / "raw.jsonl"
    connector = type(sys)("generation_connector")
    connector.discover_sessions = lambda *, limit: [{
        "source_path": str(source),
        "session_id": "session-1",
    }]
    connector._raw_dest_for_artifact = lambda _artifact: raw
    connector.archive_session_incremental = lambda *_args, **_kwargs: (
        str(raw.with_name("raw.seg1.jsonl")),
        "generation_started(generation=1,base=3,bytes=0)",
    )
    monkeypatch.setitem(sys.modules, "generation_connector", connector)

    result = raw_record_backfill._connector_backfill(
        "codex",
        "generation_connector",
        limit=20,
        target_raw_paths={str(raw)},
    )

    assert result["ok"] is True
    assert result["changed"] == 1
    assert result["result"]["write_performed"] is True
    assert result["result"]["items"][0]["changed"] is True


def test_raw_record_guardian_jsonl_atomic_writer_uses_lf_bytes(tmp_path):
    import raw_record_guardian

    raw_path = tmp_path / "records.jsonl"
    records = [
        {
            "timestamp": "2026-06-07T10:00:00Z",
            "type": "response_item",
            "payload": {"role": "user", "content": [{"text": "稳定换行"}]},
        }
    ]

    first_changed, first_hash = raw_record_guardian._write_jsonl_atomic(raw_path, records)
    second_changed, second_hash = raw_record_guardian._write_jsonl_atomic(raw_path, records)

    assert first_changed is True
    assert second_changed is False
    assert first_hash == second_hash
    assert b"\r\n" not in raw_path.read_bytes()
    assert raw_path.read_bytes().endswith(b"\n")


def test_raw_record_guardian_lightweight_status_does_not_call_active_generation_stale(monkeypatch):
    import raw_record_guardian

    monkeypatch.setattr(raw_record_guardian, "build_guardian_status", lambda **_kwargs: {
        "ok": True,
        "summary": {
            "record_count": 1,
            "record_guarded_count": 1,
            "raw_not_current_count": 0,
            "raw_attention_count": 1,
            "raw_divergence_generation_active_count": 1,
            "backfill_recommended_count": 0,
        },
        "recoverability_probe": {
            "candidate_count": 2,
            "candidate_limit": 80,
            "per_file_byte_limit": 32 * 1024 * 1024,
            "round_byte_limit": 64 * 1024 * 1024,
            "targeted_scan_count": 1,
            "cache_hit_count": 0,
            "canonical_cache_hit_count": 1,
            "measured_count": 2,
            "not_measured_count": 0,
            "bytes_read": 4096,
            "budget_exhausted_count": 0,
            "one_sided_count": 1,
            "non_conversation_count": 0,
            "canonical_cache_status": "available",
        },
        "guarded_sources": ["codex"],
        "gap_sources": [],
        "summary_scope": {"population_complete": True},
    })

    snapshot = raw_record_guardian.status()

    assert snapshot["raw_attention_count"] == 1
    assert snapshot["raw_divergence_generation_active_count"] == 1
    assert snapshot["raw_not_current_count"] == 0
    assert snapshot["raw_sync"]["missing_or_stale_count"] == 0
    assert snapshot["raw_sync"]["status"] == "ok"
    assert snapshot["recoverability_probe"]["schema"] == "recoverability_probe.v1"
    assert snapshot["recoverability_probe"]["targeted_scan_count"] == 1
    assert snapshot["recoverability_probe"]["canonical_cache_hit_count"] == 1


def test_public_recoverability_probe_is_bounded_and_fails_closed():
    import raw_record_guardian

    valid = {
        field: 0
        for field in raw_record_guardian._RECOVERABILITY_PROBE_INT_FIELDS
    }
    valid["canonical_cache_status"] = "sqlite_open_failed:PrivatePath"

    projected = raw_record_guardian._safe_recoverability_probe(valid)

    assert projected["schema"] == "recoverability_probe.v1"
    assert projected["canonical_cache_status"] == "unavailable"
    assert "PrivatePath" not in json.dumps(projected)
    invalid = dict(valid)
    invalid["bytes_read"] = -1
    assert raw_record_guardian._safe_recoverability_probe(invalid) is None
    invalid["bytes_read"] = 0
    invalid["canonical_cache_status"] = ""
    assert raw_record_guardian._safe_recoverability_probe(invalid) is None


def test_raw_record_guardian_reports_record_guarded_after_raw_mirror(tmp_path, monkeypatch):
    import codex_local_connector
    import raw_record_guardian

    codex_sessions, session_index, _ = _write_codex_session(tmp_path)
    memcore_root = _configure_env(monkeypatch, tmp_path, codex_sessions, session_index)

    scan = codex_local_connector.scan_sessions(dry_run=False, limit=20)
    assert scan["changed"] == 1

    report = raw_record_guardian.build_guardian_status(limit=20, include_gaps=False, write_index=True, public=False)

    assert report["summary"]["record_count"] == 1
    assert report["summary"]["record_guarded_count"] == 1
    assert report["summary"]["recoverable_from_raw_count"] == 1
    assert report["time_origin_contract"] == "tiandao_time_origin.v1"
    assert report["raw_origin_event_contract"] == "raw_origin_event.v1"
    assert report["summary"]["origin_event_count"] == 1
    assert report["summary"]["lost_source_count"] == 0
    assert report["summary"]["lost_raw_count"] == 0
    item = report["records"][0]
    assert item["guard_status"] == "record_guarded"
    assert item["origin_status"] == "origin_witnessed"
    assert item["origin_label"] == "起源已见证"
    assert item["origin_seen"] is True
    assert item["origin_event"]["origin_layer"] == "raw"
    assert item["origin_event"]["no_raw_no_river"] is True
    assert item["raw_current"] is True
    assert item["recoverable_from_raw"] is True
    assert Path(item["raw_path"]).exists()
    assert report["index_update"]["records_upserted"] == 1
    assert report["index_update"]["canonical_sessions_upserted"] == 1
    assert report["index_update"]["canonical_messages_upserted"] == 2
    assert report["index_update"]["canonical_chunks_upserted"] == 2
    assert report["index_update"]["canonical_raw_offset_coverage_count"] == 2
    assert report["index_update"]["origin_events_upserted"] == 1
    assert report["index_update"]["origin_events_total"] == 1
    assert Path(report["index_update"]["db_path"]).exists()
    assert (memcore_root / "memory").exists()


def test_raw_record_guardian_reuses_existing_codex_archive_after_computer_id_change(tmp_path, monkeypatch):
    import codex_local_connector
    import raw_record_guardian

    codex_sessions, session_index, session_path = _write_codex_session(tmp_path)
    memcore_root = _configure_env(monkeypatch, tmp_path, codex_sessions, session_index)
    monkeypatch.setattr(codex_local_connector, "node_id", lambda: "renamed-host")
    artifact = codex_local_connector.artifact_from_path(session_path)
    existing = (
        memcore_root
        / "memory"
        / "local"
        / "codex"
        / "codex_session_jsonl"
        / artifact["canonical_window_id"]
        / f"{artifact['session_id']}.jsonl"
    )
    existing.parent.mkdir(parents=True)
    existing.write_bytes(session_path.read_bytes())

    report = raw_record_guardian.build_guardian_status(
        limit=20,
        include_gaps=False,
        public=False,
    )

    assert report["summary"]["record_guarded_count"] == 1
    assert report["summary"]["lost_raw_count"] == 0
    assert report["records"][0]["raw_path"] == str(existing)
    assert report["records"][0]["guard_status"] == "record_guarded"


def test_canonical_record_index_stores_codex_offsets_and_chunks(tmp_path, monkeypatch):
    import codex_local_connector
    import raw_record_guardian

    monkeypatch.setenv("MEMCORE_CANONICAL_INDEX_CHUNK_CHARS", "512")
    codex_sessions, session_index, session_path = _write_codex_session(tmp_path, oversize=True)
    expected_session_id = "019e-test-raw-guardian"
    expected_project_id = codex_local_connector.project_id_from_cwd(str(tmp_path / "project"))
    _configure_env(monkeypatch, tmp_path, codex_sessions, session_index)
    codex_local_connector.scan_sessions(dry_run=False, limit=20)

    report = raw_record_guardian.build_guardian_status(
        limit=20,
        include_gaps=False,
        write_index=True,
        public=False,
    )

    db_path = Path(report["index_update"]["db_path"])
    conn = sqlite3.connect(db_path)
    try:
        sessions = conn.execute(
            """
            select session_id, canonical_window_id, project_id,
                   indexed_message_count, raw_offset_coverage_count, index_status
            from canonical_sessions
            """
        ).fetchall()
        messages = conn.execute(
            """
            select role, canonical_window_id, project_id, line_no, raw_line_no, source_offset_start,
                   source_offset_end, raw_offset_start, raw_offset_end,
                   content_preview, raw_available
            from canonical_messages
            order by line_no
            """
        ).fetchall()
        chunks = conn.execute(
            """
            select role, canonical_window_id, chunk_index, chunk_start_char,
                   chunk_end_char, chunk_text
            from canonical_chunks
            order by role, chunk_index
            """
        ).fetchall()
        index_names = {
            row[0]
            for row in conn.execute(
                "select name from sqlite_master where type='index' and tbl_name='canonical_messages'"
            ).fetchall()
        }
    finally:
        conn.close()

    item = report["records"][0]
    assert item["session_id"] == expected_session_id
    assert item["canonical_window_id"] == expected_session_id
    assert item["project_id"] == expected_project_id
    assert sessions == [(expected_session_id, expected_session_id, expected_project_id, 3, 3, "raw_offsets_complete")]
    assert "idx_canonical_messages_source_session_time" in index_names
    assert "idx_canonical_messages_source_window_time" in index_names
    assert [row[0] for row in messages] == ["user", "assistant", "assistant"]
    assert {row[1] for row in messages} == {expected_session_id}
    assert {row[2] for row in messages} == {expected_project_id}
    assert all(row[5] < row[6] for row in messages)
    assert all(row[7] is not None and row[7] < row[8] for row in messages)
    assert all(row[10] == 1 for row in messages)
    assert any("守住原始记录" in row[9] for row in messages)
    assert len(chunks) >= 3
    assert {row[1] for row in chunks} == {expected_session_id}
    assert session_path.exists()

    query = raw_record_guardian.query_records_index(
        source_system="codex",
        query="守住原始记录",
        db_path=db_path,
        public=False,
    )
    assert query["ok"] is True
    assert query["totals"]["canonical_messages"] == 3
    assert query["totals"]["origin_events"] == 1
    assert len(query["origin_events"]) == 1
    assert query["origin_events"][0]["origin_contract"] == "tiandao_time_origin.v1"
    assert query["origin_events"][0]["origin_status"] == "origin_witnessed"
    assert len(query["messages"]) == 1
    assert query["messages"][0]["role"] == "user"


def test_origin_events_remain_orderable_by_event_time_and_audit_time(tmp_path):
    import raw_record_guardian

    db_path = tmp_path / "records.db"
    conn = sqlite3.connect(db_path)
    try:
        raw_record_guardian._ensure_index_schema(conn)
        for origin_id, event_time, audit_time, updated_at in [
            ("origin-newer-event", "2026-06-08T10:00:01Z", "2026-06-08T10:00:01Z", "2026-06-08T10:00:01Z"),
            ("origin-same-event-later-audit", "2026-06-08T10:00:00Z", "2026-06-08T10:00:03Z", "2026-06-08T10:00:00Z"),
            ("origin-same-event-earlier-audit", "2026-06-08T10:00:00Z", "2026-06-08T10:00:02Z", "2026-06-08T10:00:09Z"),
        ]:
            conn.execute(
                """
                insert into origin_events (
                    origin_id, record_id, origin_contract, origin_event_contract,
                    time_river_contract, origin_layer, origin_status, origin_label,
                    origin_seen, source_system, session_id, event_time, audit_time,
                    updated_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    origin_id,
                    f"record-{origin_id}",
                    "tiandao_time_origin.v1",
                    "raw_origin_event.v1",
                    "tiandao_time_river.v1",
                    "raw",
                    "origin_witnessed",
                    "起源已见证",
                    1,
                    "codex",
                    "session-order",
                    event_time,
                    audit_time,
                    updated_at,
                ),
            )
        conn.commit()
    finally:
        conn.close()

    query = raw_record_guardian.query_records_index(
        source_system="codex",
        session_id="session-order",
        db_path=db_path,
        public=False,
    )

    assert query["ok"] is True
    assert [event["origin_id"] for event in query["origin_events"]] == [
        "origin-newer-event",
        "origin-same-event-later-audit",
        "origin-same-event-earlier-audit",
    ]
    assert [event["event_time"] for event in query["origin_events"]] == [
        "2026-06-08T10:00:01Z",
        "2026-06-08T10:00:00Z",
        "2026-06-08T10:00:00Z",
    ]
    assert [event["audit_time"] for event in query["origin_events"]] == [
        "2026-06-08T10:00:01Z",
        "2026-06-08T10:00:03Z",
        "2026-06-08T10:00:02Z",
    ]


def test_canonical_record_index_repairs_codex_session_window_identity_drift(tmp_path):
    import raw_record_guardian

    db_path = tmp_path / "records.db"
    conn = sqlite3.connect(db_path)
    try:
        raw_record_guardian._ensure_index_schema(conn)
        conn.execute(
            """
            insert into records (
                record_id, source_system, session_id, canonical_window_id,
                project_id, source_path, raw_path
            ) values (?, ?, ?, ?, ?, ?, ?)
            """,
            ("record-codex", "codex", "session-a", "workspace-old", "", "/source.jsonl", "/raw.jsonl"),
        )
        conn.execute(
            """
            insert into canonical_sessions (
                record_id, source_system, session_id, canonical_window_id,
                project_id, source_path, raw_path
            ) values (?, ?, ?, ?, ?, ?, ?)
            """,
            ("record-codex", "codex", "session-a", "workspace-old", "", "/source.jsonl", "/raw.jsonl"),
        )
        conn.execute(
            """
            insert into canonical_messages (
                message_id, record_id, source_system, session_id,
                canonical_window_id, project_id, content_preview
            ) values (?, ?, ?, ?, ?, ?, ?)
            """,
            ("msg-codex", "record-codex", "codex", "session-a", "workspace-old", "", "preview"),
        )
        conn.execute(
            """
            insert into canonical_chunks (
                chunk_id, message_id, record_id, source_system,
                session_id, canonical_window_id, role, chunk_index, chunk_text
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("chunk-codex", "msg-codex", "record-codex", "codex", "session-a", "workspace-old", "assistant", 0, "preview"),
        )
        conn.execute(
            """
            insert into origin_events (
                origin_id, record_id, origin_contract, origin_event_contract,
                source_system, session_id, canonical_window_id
            ) values (?, ?, ?, ?, ?, ?, ?)
            """,
            ("origin-codex", "record-codex", "tiandao_time_origin.v1", "raw_origin_event.v1", "codex", "session-a", "workspace-old"),
        )
        conn.execute(
            """
            insert into records (
                record_id, source_system, session_id, canonical_window_id,
                project_id, source_path, raw_path
            ) values (?, ?, ?, ?, ?, ?, ?)
            """,
            ("record-openclaw", "openclaw", "openclaw-session", "openclaw-window", "", "/oc-source.jsonl", "/oc-raw.jsonl"),
        )

        repaired = raw_record_guardian._repair_session_window_identity_drift(conn)

        assert repaired == 5
        for table in ("records", "canonical_sessions", "canonical_messages"):
            row = conn.execute(
                f"select canonical_window_id, project_id from {table} where source_system='codex'"
            ).fetchone()
            assert row == ("session-a", "workspace-old")
        for table in ("canonical_chunks", "origin_events"):
            row = conn.execute(
                f"select canonical_window_id from {table} where source_system='codex'"
            ).fetchone()
            assert row == ("session-a",)
        assert conn.execute(
            "select canonical_window_id from records where source_system='openclaw'"
        ).fetchone() == ("openclaw-window",)
    finally:
        conn.close()


def test_canonical_record_index_stores_claude_desktop_authorized_raw(tmp_path, monkeypatch):
    import raw_record_guardian

    raw_path, _ = _write_claude_desktop_authorized_raw(tmp_path, monkeypatch)

    report = raw_record_guardian.build_guardian_status(
        limit=20,
        include_gaps=False,
        write_index=True,
        public=False,
    )

    assert report["index_update"]["canonical_sessions_upserted"] == 1
    assert report["index_update"]["canonical_messages_upserted"] == 2
    result = report["index_update"]["canonical_results"][0]
    assert result["source_system"] == "claude_desktop"
    assert result["index_status"] == "raw_offsets_complete"

    query = raw_record_guardian.query_records_index(
        source_system="claude_desktop",
        query="Claude Desktop raw",
        db_path=report["index_update"]["db_path"],
        public=False,
    )

    assert query["ok"] is True
    assert query["totals"]["canonical_sessions"] == 1
    assert [message["role"] for message in query["messages"]] == ["assistant", "user"]
    assert all(message["raw_available"] == 1 for message in query["messages"])
    assert all(message["source_path"] == str(raw_path) for message in query["messages"])
    assert any("Claude Desktop raw user" in message["content_preview"] for message in query["messages"])
    assert any("Claude Desktop raw assistant" in message["content_preview"] for message in query["messages"])


def test_canonical_record_index_stores_claude_desktop_projects_jsonl(tmp_path, monkeypatch):
    import raw_record_guardian

    raw_path, _, session_id = _write_claude_desktop_projects_jsonl_raw(tmp_path, monkeypatch)

    report = raw_record_guardian.build_guardian_status(
        limit=20,
        include_gaps=False,
        write_index=True,
        public=False,
    )

    query = raw_record_guardian.query_records_index(
        source_system="claude_desktop",
        session_id=session_id,
        db_path=report["index_update"]["db_path"],
        public=False,
    )

    assert query["ok"] is True
    assert len(query["sessions"]) == 1
    assert query["sessions"][0]["index_status"] == "raw_offsets_complete"
    assert [message["role"] for message in query["messages"]] == ["assistant", "user"]
    assert all(message["raw_path"] == str(raw_path) for message in query["messages"])
    assert any("Claude projects JSONL source user" in message["content_preview"] for message in query["messages"])
    assert any("Claude projects JSONL source assistant" in message["content_preview"] for message in query["messages"])


def test_canonical_record_index_covers_openclaw_hermes_and_kiro_sessions(tmp_path, monkeypatch):
    import kiro_local_connector
    import raw_record_guardian

    _write_openclaw_source_and_raw(tmp_path, monkeypatch, raw=True)

    session_root = tmp_path / "kiro-workspace-sessions"
    kiro_session_path = session_root / "workspace-alpha" / "session.json"
    _write_kiro_session(
        kiro_session_path,
        [
            {"id": "kiro-u1", "role": "user", "content": "Kiro canonical user"},
            {"id": "kiro-a1", "role": "assistant", "content": "Kiro canonical assistant"},
        ],
    )
    monkeypatch.setenv("KIRO_WORKSPACE_SESSIONS_DIR", str(session_root))
    kiro_local_connector.scan_sessions(dry_run=False, limit=20)

    _write_hermes_state_db(tmp_path, monkeypatch)
    raw_record_guardian.run_raw_backfill(limit=20, source_systems=["hermes"])

    report = raw_record_guardian.build_guardian_status(
        limit=20,
        include_gaps=False,
        write_index=True,
        public=False,
    )

    assert report["index_update"]["canonical_sessions_upserted"] >= 4
    assert report["index_update"]["canonical_messages_total"] >= 8
    assert {
        result["source_system"]
        for result in report["index_update"]["canonical_results"]
        if result.get("sessions_indexed")
    } >= {"openclaw", "hermes", "kiro"}

    db_path = report["index_update"]["db_path"]
    openclaw = raw_record_guardian.query_records_index(
        source_system="openclaw",
        query="OpenClaw",
        db_path=db_path,
        public=False,
    )
    hermes = raw_record_guardian.query_records_index(
        source_system="hermes",
        query="Hermes",
        db_path=db_path,
        public=False,
    )
    kiro = raw_record_guardian.query_records_index(
        source_system="kiro",
        query="Kiro canonical",
        db_path=db_path,
        public=False,
    )

    assert [message["role"] for message in openclaw["messages"]] == ["user", "assistant"]
    assert all(message["raw_available"] == 1 for message in openclaw["messages"])
    assert any("OpenClaw user" in message["content_preview"] for message in openclaw["messages"])
    assert any("OpenClaw assistant" in message["content_preview"] for message in openclaw["messages"])

    assert hermes["totals"]["canonical_sessions"] >= 4
    assert len(hermes["sessions"]) == 2
    assert sorted(message["role"] for message in hermes["messages"]) == ["assistant", "assistant", "user", "user"]
    assert all(message["raw_available"] == 1 for message in hermes["messages"])

    assert len(kiro["sessions"]) == 1
    assert sorted(message["role"] for message in kiro["messages"]) == ["assistant", "user"]
    assert all(message["raw_available"] == 1 for message in kiro["messages"])
    assert all(message["source_path"] == message["raw_path"] for message in kiro["messages"])


def test_canonical_record_index_appends_codex_tail_without_rebuilding_existing_rows(tmp_path, monkeypatch):
    import codex_local_connector
    import raw_record_guardian

    monkeypatch.setenv("MEMCORE_CANONICAL_INDEX_CHUNK_CHARS", "512")
    codex_sessions, session_index, session_path = _write_codex_session(tmp_path)
    _configure_env(monkeypatch, tmp_path, codex_sessions, session_index)
    codex_local_connector.scan_sessions(dry_run=False, limit=20)

    first = raw_record_guardian.build_guardian_status(
        limit=20,
        include_gaps=False,
        write_index=True,
        public=False,
    )
    db_path = Path(first["index_update"]["db_path"])
    conn = sqlite3.connect(db_path)
    try:
        before = conn.execute(
            "select message_id, line_no from canonical_messages order by line_no"
        ).fetchall()
    finally:
        conn.close()

    _append_jsonl(session_path, [{
        "timestamp": "2026-06-07T10:00:03Z",
        "type": "response_item",
        "payload": {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "增量追尾，不重扫旧行。"}],
        },
    }])
    codex_local_connector.scan_sessions(dry_run=False, limit=20)

    second = raw_record_guardian.build_guardian_status(
        limit=20,
        include_gaps=False,
        write_index=True,
        public=False,
    )

    conn = sqlite3.connect(db_path)
    try:
        session = conn.execute(
            """
            select indexed_message_count, raw_offset_coverage_count,
                   source_size_bytes, raw_size_bytes, index_status
            from canonical_sessions
            """
        ).fetchone()
        after = conn.execute(
            "select message_id, line_no, content_preview from canonical_messages order by line_no"
        ).fetchall()
    finally:
        conn.close()

    assert second["index_update"]["canonical_messages_upserted"] == 1
    assert session[0] == 3
    assert session[1] == 3
    assert session[2] == session[3]
    assert session[4] == "raw_offsets_complete"
    assert [row[0] for row in after[:2]] == [row[0] for row in before]
    assert after[-1][1] == 4
    assert "增量追尾" in after[-1][2]


def test_guardian_and_canonical_index_follow_divergence_generation_lineage(tmp_path, monkeypatch):
    import codex_local_connector
    import raw_record_guardian

    codex_sessions, session_index, session_path = _write_codex_session(tmp_path)
    _configure_env(monkeypatch, tmp_path, codex_sessions, session_index)
    first_scan = codex_local_connector.scan_sessions(dry_run=False, limit=20)
    original_raw = Path(first_scan["items"][0]["dest"])
    raw_record_guardian.build_guardian_status(
        limit=20,
        include_gaps=False,
        write_index=True,
        public=False,
        source_systems=["codex"],
    )

    source_lines = [json.loads(line) for line in session_path.read_text(encoding="utf-8").splitlines()]
    source_lines[0]["payload"]["model"] = "rewritten-session-metadata"
    source_lines[2]["payload"]["content"][0]["text"] = "改写后的回复应作为独立内容版本保留。"
    source_lines.extend([
        {
            "timestamp": "2026-06-07T10:00:03Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "分代后的新问题。"}],
            },
        },
        {
            "timestamp": "2026-06-07T10:00:04Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "分代后的新回复。"}],
            },
        },
    ])
    session_path.write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in source_lines),
        encoding="utf-8",
    )
    second_scan = codex_local_connector.scan_sessions(dry_run=False, limit=20)
    generation_raw = Path(second_scan["items"][0]["dest"])

    report = raw_record_guardian.build_guardian_status(
        limit=20,
        include_gaps=False,
        write_index=True,
        public=False,
        source_systems=["codex"],
    )
    item = report["records"][0]
    db_path = Path(report["index_update"]["db_path"])
    conn = sqlite3.connect(db_path)
    try:
        messages = conn.execute(
            """
            select content_preview, raw_path, source_offset_start, raw_offset_start, payload_json
            from canonical_messages
            where source_system='codex'
            order by timestamp, content_preview
            """
        ).fetchall()
    finally:
        conn.close()

    previews = [row[0] for row in messages]
    assert generation_raw != original_raw
    assert item["guard_status"] == "source_divergence_generation_active"
    assert item["raw_current"] is True
    assert item["raw_scan"]["generation_lineage_complete"] is True
    assert item["raw_scan"]["generation_lineage_count"] == 2
    assert item["raw_scan"]["has_user_and_assistant"] is True
    assert item["sync"]["raw_covered_source_bytes"] == session_path.stat().st_size
    assert item["sync"]["raw_archive_lag_bytes"] == 0
    assert item["backfill_recommended"] is False
    assert report["summary"]["record_guarded_count"] == 1
    assert report["summary"]["raw_not_current_count"] == 0
    assert report["summary"]["raw_attention_count"] == 1
    assert report["summary"]["raw_source_divergence_count"] == 1
    assert report["summary"]["raw_divergence_generation_active_count"] == 1
    assert previews.count("守住原始记录。") == 1
    assert previews.count("已镜像 raw，并可回源。") == 1
    assert previews.count("改写后的回复应作为独立内容版本保留。") == 1
    assert previews.count("分代后的新问题。") == 1
    assert previews.count("分代后的新回复。") == 1
    assert len(messages) == 5
    overlap = next(row for row in messages if row[0] == "守住原始记录。")
    old_version = next(row for row in messages if row[0] == "已镜像 raw，并可回源。")
    new_version = next(row for row in messages if row[0] == "改写后的回复应作为独立内容版本保留。")
    assert overlap[1] == str(generation_raw)
    assert old_version[1] == str(original_raw)
    assert new_version[1] == str(generation_raw)
    assert overlap[2] >= 0 and overlap[3] >= 0
    overlap_payload = json.loads(overlap[4])
    assert overlap_payload["raw_generation"] == 1
    assert overlap_payload["predecessor_raw_path"] == str(original_raw)


def test_guardian_generation_lineage_prevents_suffix_only_partial_false_positive(tmp_path, monkeypatch):
    import codex_local_connector
    import raw_record_guardian

    codex_sessions, session_index, session_path = _write_codex_session(tmp_path)
    _configure_env(monkeypatch, tmp_path, codex_sessions, session_index)
    first_scan = codex_local_connector.scan_sessions(dry_run=False, limit=20)
    original_raw = Path(first_scan["items"][0]["dest"])
    lines = session_path.read_text(encoding="utf-8").splitlines(keepends=True)
    rewritten_assistant = json.loads(lines[2])
    rewritten_assistant["payload"]["content"][0]["text"] = "只改写 assistant，suffix 本身没有 user。"
    session_path.write_bytes(
        "".join(lines[:2]).encode("utf-8")
        + (json.dumps(rewritten_assistant, ensure_ascii=False) + "\n").encode("utf-8")
    )
    second_scan = codex_local_connector.scan_sessions(dry_run=False, limit=20)
    generation_raw = Path(second_scan["items"][0]["dest"])
    suffix_scan = raw_record_guardian.scan_jsonl_record(generation_raw, source_system="codex")

    report = raw_record_guardian.build_guardian_status(
        limit=20,
        include_gaps=False,
        scan_mode="full",
        public=False,
        source_systems=["codex"],
    )
    item = report["records"][0]

    assert generation_raw != original_raw
    assert suffix_scan["has_user_and_assistant"] is False
    assert suffix_scan["assistant_turn_count"] == 1
    assert item["raw_scan"]["has_user_and_assistant"] is True
    assert item["raw_scan"]["generation_lineage_count"] == 2
    assert item["guard_status"] == "source_divergence_generation_active"
    assert item["raw_current"] is True
    assert item["backfill_recommended"] is False


def test_invalid_generation_descriptor_fails_closed_across_connector_and_guardian(tmp_path, monkeypatch):
    import codex_local_connector
    import raw_archive_monotonic
    import raw_record_guardian

    codex_sessions, session_index, session_path = _write_codex_session(tmp_path)
    _configure_env(monkeypatch, tmp_path, codex_sessions, session_index)
    first_scan = codex_local_connector.scan_sessions(dry_run=False, limit=20)
    original_raw = Path(first_scan["items"][0]["dest"])
    original_bytes = original_raw.read_bytes()
    lines = session_path.read_text(encoding="utf-8").splitlines(keepends=True)
    rewritten_assistant = json.loads(lines[2])
    rewritten_assistant["payload"]["content"][0]["text"] = "建立分代后再损坏 descriptor。"
    session_path.write_bytes(
        "".join(lines[:2]).encode("utf-8")
        + (json.dumps(rewritten_assistant, ensure_ascii=False) + "\n").encode("utf-8")
    )
    second_scan = codex_local_connector.scan_sessions(dry_run=False, limit=20)
    generation_raw = Path(second_scan["items"][0]["dest"])
    generation_bytes = generation_raw.read_bytes()
    descriptor_path = raw_archive_monotonic.generation_descriptor_path(generation_raw)
    descriptor_path.write_text("{}", encoding="utf-8")
    artifact = codex_local_connector.artifact_from_path(session_path)

    sync_item = codex_local_connector._raw_sync_item(artifact)
    blocked_dest, blocked_status = codex_local_connector.archive_session_incremental(
        str(session_path),
        artifact=artifact,
    )
    report = raw_record_guardian.build_guardian_status(
        limit=20,
        include_gaps=False,
        scan_mode="fast",
        public=False,
        source_systems=["codex"],
    )
    item = report["records"][0]

    assert sync_item["raw_generation_descriptor_incomplete"] is True
    assert sync_item["raw_monotonic_probe_ok"] is False
    assert sync_item["raw_monotonic_status"] == "raw_generation_descriptor_incomplete"
    assert blocked_dest == str(generation_raw)
    assert blocked_status.startswith("source_divergence_generation_fail_closed")
    assert item["guard_status"] == "raw_monotonic_probe_incomplete"
    assert item["sync"]["raw_generation_descriptor_incomplete"] is True
    assert item["sync"]["raw_body_read_performed"] is False
    assert item["backfill_recommended"] is False
    assert report["summary"]["raw_monotonic_probe_incomplete_count"] == 1
    assert report["summary"]["raw_attention_count"] == 1
    assert original_raw.read_bytes() == original_bytes
    assert generation_raw.read_bytes() == generation_bytes
    assert not (generation_raw.parent / generation_raw.name.replace(".seg1.", ".seg2.")).exists()


def test_canonical_record_index_skips_unchanged_records_on_repeat_build(tmp_path, monkeypatch):
    import codex_local_connector
    import raw_record_guardian

    codex_sessions, session_index, _ = _write_codex_session(tmp_path)
    _configure_env(monkeypatch, tmp_path, codex_sessions, session_index)
    codex_local_connector.scan_sessions(dry_run=False, limit=20)

    first = raw_record_guardian.build_guardian_status(
        limit=20,
        include_gaps=False,
        write_index=True,
        public=False,
    )
    second = raw_record_guardian.build_guardian_status(
        limit=20,
        include_gaps=False,
        write_index=True,
        public=False,
    )

    assert first["index_update"]["records_upserted"] == 1
    assert second["index_update"]["records_upserted"] == 0
    assert second["index_update"]["records_skipped_unchanged"] == 1
    assert second["index_update"]["canonical_messages_upserted"] == 0
    assert second["index_update"]["canonical_chunks_upserted"] == 0


def test_canonical_record_index_ignores_clock_only_lag_drift_on_repeat_build(tmp_path, monkeypatch):
    import codex_local_connector
    import raw_record_guardian

    codex_sessions, session_index, session_path = _write_codex_session(tmp_path)
    _configure_env(monkeypatch, tmp_path, codex_sessions, session_index)
    codex_local_connector.scan_sessions(dry_run=False, limit=20)

    raw_root = tmp_path / "memcore" / "memory" / "local" / "codex"
    raw_files = list(raw_root.rglob("*.jsonl"))
    assert raw_files
    raw_path = raw_files[0]

    _append_jsonl(session_path, [{
        "timestamp": "2026-06-07T10:00:03Z",
        "type": "response_item",
        "payload": {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "让 raw 暂时落后一个字节。"}],
        },
    }])
    raw_bytes = raw_path.read_bytes()
    raw_path.write_bytes(raw_bytes[:-1])

    first = raw_record_guardian.build_guardian_status(
        limit=20,
        include_gaps=False,
        write_index=True,
        public=False,
        source_systems=["codex"],
    )
    second = raw_record_guardian.build_guardian_status(
        limit=20,
        include_gaps=False,
        write_index=True,
        public=False,
        source_systems=["codex"],
    )

    assert first["index_update"]["records_upserted"] == 1
    assert second["index_update"]["records_upserted"] == 0
    assert second["index_update"]["records_skipped_unchanged"] == 1


def test_canonical_index_refresh_due_detects_tracked_source_change(tmp_path, monkeypatch):
    import codex_local_connector
    import raw_record_canonical_index
    import raw_record_guardian

    codex_sessions, session_index, session_path = _write_codex_session(tmp_path)
    _configure_env(monkeypatch, tmp_path, codex_sessions, session_index)
    codex_local_connector.scan_sessions(dry_run=False, limit=20)
    raw_record_guardian.build_guardian_status(
        limit=20,
        include_gaps=False,
        write_index=True,
        public=False,
    )

    unchanged = raw_record_canonical_index.canonical_index_refresh_due()
    assert unchanged["refresh_needed"] is False
    assert unchanged["reason"] == "tracked_sources_unchanged"

    _append_jsonl(session_path, [{
        "timestamp": "2026-06-07T10:00:03Z",
        "type": "response_item",
        "payload": {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "source 文件长了，gate 应该看见。"}],
        },
    }])

    changed = raw_record_canonical_index.canonical_index_refresh_due()
    assert changed["refresh_needed"] is True
    assert changed["reason"] == "tracked_source_stat_changed"
    assert changed["changed_records"] == 1


def test_changed_record_refresh_drains_due_without_catalog_rediscovery(tmp_path, monkeypatch):
    import canonical_index_delta_refresh
    import codex_local_connector
    import raw_record_canonical_index
    import raw_record_guardian

    codex_sessions, session_index, session_path = _write_codex_session(tmp_path)
    _configure_env(monkeypatch, tmp_path, codex_sessions, session_index)
    codex_local_connector.scan_sessions(dry_run=False, limit=20)
    raw_record_guardian.build_guardian_status(
        limit=20,
        include_gaps=False,
        write_index=True,
        public=False,
        source_systems=["codex"],
    )
    _append_jsonl(session_path, [{
        "timestamp": "2026-06-07T10:00:04Z",
        "type": "response_item",
        "payload": {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "只刷新变更记录。"}],
        },
    }])
    artifact = codex_local_connector.artifact_from_path(session_path)
    _dest, status = codex_local_connector.archive_session_incremental(
        str(session_path),
        artifact=artifact,
    )
    assert status.startswith("appended")

    public_due = raw_record_canonical_index.canonical_index_refresh_due(
        source_systems=["codex"],
    )
    internal_due = raw_record_canonical_index.canonical_index_refresh_due(
        source_systems=["codex"],
        include_internal_targets=True,
    )

    assert public_due["changed_records"] == 1
    assert "_internal_changed_record_ids" not in public_due
    assert len(internal_due["_internal_changed_record_ids"]) == 1

    refreshed = canonical_index_delta_refresh.refresh_changed_records_index(
        internal_due["_internal_changed_record_ids"],
    )
    after = raw_record_canonical_index.canonical_index_refresh_due(
        source_systems=["codex"],
    )

    assert refreshed["records_upserted"] == 1
    assert refreshed["canonical_records_refreshed"] == 1
    assert refreshed["canonical_messages_upserted"] == 1
    assert after["refresh_needed"] is False


def test_changed_record_refresh_preserves_index_when_source_is_missing(tmp_path, monkeypatch):
    import canonical_index_delta_refresh
    import codex_local_connector
    import raw_record_canonical_index
    import raw_record_guardian

    codex_sessions, session_index, session_path = _write_codex_session(tmp_path)
    _configure_env(monkeypatch, tmp_path, codex_sessions, session_index)
    scan = codex_local_connector.scan_sessions(dry_run=False, limit=20)
    raw_path = Path(scan["items"][0]["dest"])
    raw_record_guardian.build_guardian_status(
        limit=20,
        include_gaps=False,
        write_index=True,
        public=False,
        source_systems=["codex"],
    )
    db_path = Path(os.environ["MEMCORE_RECORDS_DB"])
    conn = sqlite3.connect(db_path)
    try:
        messages_before = conn.execute("select count(*) from canonical_messages").fetchone()[0]
    finally:
        conn.close()

    session_path.unlink()
    with raw_path.open("ab") as handle:
        handle.write(b'{"type":"retained-raw-tail"}\n')
    due = raw_record_canonical_index.canonical_index_refresh_due(
        source_systems=["codex"],
        include_internal_targets=True,
    )
    refreshed = canonical_index_delta_refresh.refresh_changed_records_index(
        due["_internal_changed_record_ids"],
    )

    conn = sqlite3.connect(db_path)
    try:
        messages_after = conn.execute("select count(*) from canonical_messages").fetchone()[0]
    finally:
        conn.close()

    assert refreshed["records_upserted"] == 1
    assert refreshed["canonical_records_refreshed"] == 0
    assert refreshed["source_missing_index_preserved"] == 1
    assert messages_after == messages_before
    assert raw_record_canonical_index.canonical_index_refresh_due(
        source_systems=["codex"],
    )["refresh_needed"] is False


def test_canonical_index_refresh_due_can_ignore_stale_non_active_sources(tmp_path, monkeypatch):
    import codex_local_connector
    import raw_record_canonical_index
    import raw_record_guardian

    codex_sessions, session_index, _session_path = _write_codex_session(tmp_path)
    _configure_env(monkeypatch, tmp_path, codex_sessions, session_index)
    codex_local_connector.scan_sessions(dry_run=False, limit=20)
    raw_record_guardian.build_guardian_status(
        limit=20,
        include_gaps=False,
        write_index=True,
        public=False,
        source_systems=["codex"],
    )

    db_path = Path(os.environ["MEMCORE_RECORDS_DB"])
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("select record_id from records where source_system='codex' limit 1").fetchone()
        assert row is not None
        source_record_id = row[0]
        stale_record_id = "stale-claude-record"
        conn.execute(
            "insert into records select ?, ?, session_id, raw_artifact_id, canonical_window_id, project_id, source_path, raw_path, source_mtime, raw_mtime, source_size_bytes, raw_size_bytes, user_turn_count, assistant_turn_count, bad_json_line_count, oversize_record_count, metadata_ok, has_user_and_assistant, raw_current, recoverable_from_raw, guard_status, updated_at, payload_json from records where record_id=?",
            (stale_record_id, "claude_code_cli", source_record_id),
        )
        conn.execute(
            "insert into canonical_sessions select ?, ?, session_id, raw_artifact_id, canonical_window_id, project_id, project_root, thread_name, source_path, raw_path, source_mtime, raw_mtime, source_size_bytes, raw_size_bytes, source_line_count, raw_line_count, indexed_message_count, indexed_chunk_count, raw_indexed_message_count, raw_offset_coverage_count, bad_json_line_count, oversized_line_count, index_status, updated_at, payload_json from canonical_sessions where record_id=?",
            (stale_record_id, "claude_code_cli", source_record_id),
        )
        conn.execute(
            "insert into origin_events select ?, ?, origin_contract, origin_event_contract, time_river_contract, origin_layer, origin_status, origin_label, origin_seen, ?, computer_id, native_session_key, session_id, canonical_window_id, source_path, raw_path, event_time, captured_at, audit_time, content_hash, byte_offset, line_no, source_refs_json, payload_json, updated_at from origin_events where record_id=?",
            ("stale-claude-origin", stale_record_id, "claude_code_cli", source_record_id),
        )
        conn.execute(
            "update records set source_mtime=?, raw_mtime=? where record_id=?",
            ("1970-01-01T00:00:00Z", "1970-01-01T00:00:00Z", stale_record_id),
        )
        conn.execute(
            "update canonical_sessions set source_mtime=?, raw_mtime=? where record_id=?",
            ("1970-01-01T00:00:00Z", "1970-01-01T00:00:00Z", stale_record_id),
        )
        conn.commit()
    finally:
        conn.close()

    full = raw_record_canonical_index.canonical_index_refresh_due()
    scoped = raw_record_canonical_index.canonical_index_refresh_due(source_systems=["codex"])

    assert full["refresh_needed"] is True
    assert full["changed_records"] == 1
    assert scoped["refresh_needed"] is False
    assert scoped["reason"] == "tracked_sources_unchanged"


def test_canonical_index_refresh_due_ignores_stale_duplicate_record_ids_for_same_session(tmp_path, monkeypatch):
    import codex_local_connector
    import raw_record_canonical_index
    import raw_record_guardian

    codex_sessions, session_index, _session_path = _write_codex_session(tmp_path)
    _configure_env(monkeypatch, tmp_path, codex_sessions, session_index)
    codex_local_connector.scan_sessions(dry_run=False, limit=20)
    raw_record_guardian.build_guardian_status(
        limit=20,
        include_gaps=False,
        write_index=True,
        public=False,
        source_systems=["codex"],
    )

    db_path = Path(os.environ["MEMCORE_RECORDS_DB"])
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "select record_id, session_id, canonical_window_id from records where source_system='codex' limit 1"
        ).fetchone()
        assert row is not None
        source_record_id, session_id, canonical_window_id = row
        duplicate_record_id = "older-duplicate-record"
        conn.execute(
            "insert into records select ?, source_system, session_id, raw_artifact_id, canonical_window_id, project_id, source_path, raw_path, source_mtime, raw_mtime, source_size_bytes, raw_size_bytes, user_turn_count, assistant_turn_count, bad_json_line_count, oversize_record_count, metadata_ok, has_user_and_assistant, raw_current, recoverable_from_raw, guard_status, ?, payload_json from records where record_id=?",
            (duplicate_record_id, "2026-01-01T00:00:00Z", source_record_id),
        )
        conn.execute(
            "insert into canonical_sessions select ?, source_system, session_id, raw_artifact_id, canonical_window_id, project_id, project_root, thread_name, source_path, raw_path, source_mtime, raw_mtime, source_size_bytes, raw_size_bytes, source_line_count, raw_line_count, indexed_message_count, indexed_chunk_count, raw_indexed_message_count, raw_offset_coverage_count, bad_json_line_count, oversized_line_count, index_status, ?, payload_json from canonical_sessions where record_id=?",
            (duplicate_record_id, "2026-01-01T00:00:00Z", source_record_id),
        )
        conn.execute(
            "insert into origin_events select ?, ?, origin_contract, origin_event_contract, time_river_contract, origin_layer, origin_status, origin_label, origin_seen, source_system, computer_id, native_session_key, session_id, canonical_window_id, source_path, raw_path, event_time, captured_at, audit_time, content_hash, byte_offset, line_no, source_refs_json, payload_json, ? from origin_events where record_id=?",
            ("older-duplicate-origin", duplicate_record_id, "2026-01-01T00:00:00Z", source_record_id),
        )
        conn.execute(
            "update records set source_mtime=?, raw_mtime=?, source_size_bytes=0, raw_size_bytes=0 where record_id=?",
            ("1970-01-01T00:00:00Z", "1970-01-01T00:00:00Z", duplicate_record_id),
        )
        conn.execute(
            "update canonical_sessions set source_mtime=?, raw_mtime=?, source_size_bytes=0, raw_size_bytes=0 where record_id=?",
            ("1970-01-01T00:00:00Z", "1970-01-01T00:00:00Z", duplicate_record_id),
        )
        conn.commit()
    finally:
        conn.close()

    result = raw_record_canonical_index.canonical_index_refresh_due(source_systems=["codex"])

    assert result["refresh_needed"] is False
    assert result["tracked_records"] == 1
    assert result["tracked_records_raw"] == 2
    assert result["duplicate_records_ignored"] == 1


def test_canonical_index_refresh_due_treats_persisted_missing_raw_as_unchanged(tmp_path, monkeypatch):
    import codex_local_connector
    import raw_record_canonical_index
    import raw_record_guardian

    codex_sessions, session_index, _session_path = _write_codex_session(tmp_path)
    _configure_env(monkeypatch, tmp_path, codex_sessions, session_index)
    codex_local_connector.scan_sessions(dry_run=False, limit=20)
    raw_record_guardian.build_guardian_status(
        limit=20,
        include_gaps=False,
        write_index=True,
        public=False,
        source_systems=["codex"],
    )

    db_path = Path(os.environ["MEMCORE_RECORDS_DB"])
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("select record_id from records where source_system='codex' limit 1").fetchone()
        assert row is not None
        record_id = row[0]
        conn.execute("update records set raw_path=?, raw_mtime='', raw_size_bytes=0 where record_id=?", (str(tmp_path / 'missing-raw.jsonl'), record_id))
        conn.execute("update canonical_sessions set raw_path=?, raw_mtime='', raw_size_bytes=0 where record_id=?", (str(tmp_path / 'missing-raw.jsonl'), record_id))
        conn.commit()
    finally:
        conn.close()

    result = raw_record_canonical_index.canonical_index_refresh_due(source_systems=["codex"])

    assert result["refresh_needed"] is False
    assert result["changed_records"] == 0


def test_canonical_index_refresh_due_ignores_terminal_both_missing_probe_rows(tmp_path, monkeypatch):
    import codex_local_connector
    import raw_record_canonical_index
    import raw_record_guardian

    codex_sessions, session_index, _session_path = _write_codex_session(tmp_path)
    _configure_env(monkeypatch, tmp_path, codex_sessions, session_index)
    codex_local_connector.scan_sessions(dry_run=False, limit=20)
    raw_record_guardian.build_guardian_status(
        limit=20,
        include_gaps=False,
        write_index=True,
        public=False,
        source_systems=["codex"],
    )

    db_path = Path(os.environ["MEMCORE_RECORDS_DB"])
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("select record_id from records where source_system='codex' limit 1").fetchone()
        assert row is not None
        record_id = row[0]
        missing_source = tmp_path / "deleted-source.jsonl"
        missing_raw = tmp_path / "deleted-raw.jsonl"
        conn.execute(
            "update records set source_path=?, raw_path=?, source_mtime='2026-07-01T00:00:00Z', raw_mtime='2026-07-01T00:00:00Z', source_size_bytes=503, raw_size_bytes=503 where record_id=?",
            (str(missing_source), str(missing_raw), record_id),
        )
        conn.execute(
            "update canonical_sessions set source_path=?, raw_path=?, source_mtime='2026-07-01T00:00:00Z', raw_mtime='2026-07-01T00:00:00Z', source_size_bytes=503, raw_size_bytes=503 where record_id=?",
            (str(missing_source), str(missing_raw), record_id),
        )
        conn.commit()
    finally:
        conn.close()

    result = raw_record_canonical_index.canonical_index_refresh_due(source_systems=["codex"])

    assert result["refresh_needed"] is False
    assert result["changed_records"] == 0
    assert result["terminal_missing_records_ignored"] == 1


def test_canonical_index_refresh_due_ignores_source_drift_for_raw_preferred_sources(tmp_path, monkeypatch):
    import codex_local_connector
    import raw_record_canonical_index
    import raw_record_guardian

    codex_sessions, session_index, _session_path = _write_codex_session(tmp_path)
    _configure_env(monkeypatch, tmp_path, codex_sessions, session_index)
    codex_local_connector.scan_sessions(dry_run=False, limit=20)
    raw_record_guardian.build_guardian_status(
        limit=20,
        include_gaps=False,
        write_index=True,
        public=False,
        source_systems=["codex"],
    )

    db_path = Path(os.environ["MEMCORE_RECORDS_DB"])
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("select record_id from records where source_system='codex' limit 1").fetchone()
        assert row is not None
        record_id = row[0]
        conn.execute("update records set source_system='hermes' where record_id=?", (record_id,))
        conn.execute("update canonical_sessions set source_system='hermes' where record_id=?", (record_id,))
        conn.execute("update origin_events set source_system='hermes' where record_id=?", (record_id,))
        conn.execute(
            "update records set source_mtime='1970-01-01T00:00:00Z', source_size_bytes=0 where record_id=?",
            (record_id,),
        )
        conn.execute(
            "update canonical_sessions set source_mtime='1970-01-01T00:00:00Z', source_size_bytes=0 where record_id=?",
            (record_id,),
        )
        conn.commit()
    finally:
        conn.close()

    result = raw_record_canonical_index.canonical_index_refresh_due(source_systems=["hermes"])

    assert result["refresh_needed"] is False
    assert result["changed_records"] == 0
    assert result["raw_preferred_source_drift_ignored"] == 1


def test_canonical_index_refresh_due_tracks_active_divergence_generation(tmp_path, monkeypatch):
    import codex_local_connector
    import raw_record_canonical_index
    import raw_record_guardian

    codex_sessions, session_index, session_path = _write_codex_session(tmp_path)
    _configure_env(monkeypatch, tmp_path, codex_sessions, session_index)
    first_scan = codex_local_connector.scan_sessions(dry_run=False, limit=20)
    raw_path = Path(first_scan["items"][0]["dest"])
    original_raw = raw_path.read_bytes()

    raw_record_guardian.build_guardian_status(
        limit=20,
        include_gaps=False,
        write_index=True,
        public=False,
        source_systems=["codex"],
    )
    source_bytes = session_path.read_bytes()
    rewritten = source_bytes.replace("守".encode("utf-8"), "改".encode("utf-8"), 1)
    assert len(rewritten) == len(source_bytes)
    session_path.write_bytes(rewritten)
    artifact = codex_local_connector.artifact_from_path(session_path)
    generation_dest, status = codex_local_connector.archive_session_incremental(
        str(session_path),
        artifact=artifact,
    )
    generation_raw = Path(generation_dest)
    assert status.startswith("generation_started")
    assert generation_raw != raw_path

    divergence = raw_record_guardian.build_guardian_status(
        limit=20,
        include_gaps=False,
        write_index=True,
        public=False,
        source_systems=["codex"],
    )
    assert divergence["records"][0]["guard_status"] == "source_divergence_generation_active"
    assert raw_path.read_bytes() == original_raw

    with session_path.open("ab") as handle:
        handle.write(b'{"type":"source-only-tail"}\n')

    source_only = raw_record_canonical_index.canonical_index_refresh_due(
        source_systems=["codex"],
    )
    assert source_only["refresh_needed"] is True
    assert source_only["reason"] == "tracked_source_stat_changed"
    assert source_only["changed_records"] == 1
    assert raw_path.read_bytes() == original_raw

    generation_before = generation_raw.read_bytes()
    appended_dest, appended_status = codex_local_connector.archive_session_incremental(
        str(session_path),
        artifact=artifact,
    )
    assert appended_dest == str(generation_raw)
    assert appended_status.startswith("appended_generation")
    assert generation_raw.read_bytes().startswith(generation_before)

    raw_changed = raw_record_canonical_index.canonical_index_refresh_due(
        source_systems=["codex"],
    )
    assert raw_changed["refresh_needed"] is True
    assert raw_changed["changed_records"] == 1


def test_canonical_index_refresh_due_ignores_missing_source_when_raw_still_exists(tmp_path, monkeypatch):
    import codex_local_connector
    import raw_record_canonical_index
    import raw_record_guardian

    codex_sessions, session_index, session_path = _write_codex_session(tmp_path)
    _configure_env(monkeypatch, tmp_path, codex_sessions, session_index)
    codex_local_connector.scan_sessions(dry_run=False, limit=20)
    raw_record_guardian.build_guardian_status(
        limit=20,
        include_gaps=False,
        write_index=True,
        public=False,
        source_systems=["codex"],
    )

    session_path.unlink()
    result = raw_record_canonical_index.canonical_index_refresh_due(source_systems=["codex"])

    assert result["refresh_needed"] is False
    assert result["changed_records"] == 0
    assert result["missing_source_with_raw_ignored"] == 1


def test_canonical_record_index_repairs_codex_raw_offsets_after_raw_catches_up(tmp_path, monkeypatch):
    import codex_local_connector
    import raw_record_guardian

    codex_sessions, session_index, session_path = _write_codex_session(tmp_path)
    _configure_env(monkeypatch, tmp_path, codex_sessions, session_index)
    codex_local_connector.scan_sessions(dry_run=False, limit=20)

    first = raw_record_guardian.build_guardian_status(
        limit=20,
        include_gaps=False,
        write_index=True,
        public=False,
    )
    db_path = Path(first["index_update"]["db_path"])

    _append_jsonl(session_path, [{
        "timestamp": "2026-06-07T10:00:03Z",
        "type": "response_item",
        "payload": {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "raw 稍后才追上。"}],
        },
    }])

    partial = raw_record_guardian.build_guardian_status(
        limit=20,
        include_gaps=False,
        write_index=True,
        public=False,
    )
    assert partial["index_update"]["canonical_raw_offset_coverage_count"] == 0
    conn = sqlite3.connect(db_path)
    try:
        partial_session = conn.execute(
            "select indexed_message_count, raw_offset_coverage_count, index_status from canonical_sessions"
        ).fetchone()
    finally:
        conn.close()
    assert partial_session == (3, 2, "raw_offsets_partial")

    codex_local_connector.scan_sessions(dry_run=False, limit=20)
    repaired = raw_record_guardian.build_guardian_status(
        limit=20,
        include_gaps=False,
        write_index=True,
        public=False,
    )

    conn = sqlite3.connect(db_path)
    try:
        repaired_session = conn.execute(
            "select indexed_message_count, raw_offset_coverage_count, index_status from canonical_sessions"
        ).fetchone()
        repaired_message = conn.execute(
            """
            select raw_available, raw_line_no, raw_offset_start, raw_offset_end
            from canonical_messages
            where content_preview like '%raw 稍后才追上%'
            """
        ).fetchone()
    finally:
        conn.close()

    assert repaired["index_update"]["canonical_messages_upserted"] == 0
    assert repaired["index_update"]["canonical_raw_offset_coverage_count"] == 1
    assert repaired["index_update"]["canonical_results"][0]["raw_offset_repairs_count"] == 1
    assert repaired_session == (3, 3, "raw_offsets_complete")
    assert repaired_message[0] == 1
    assert repaired_message[1] == 4
    assert repaired_message[2] < repaired_message[3]


def test_fast_canonical_record_index_defers_old_raw_offset_repairs(tmp_path, monkeypatch):
    import codex_local_connector
    import raw_record_guardian

    codex_sessions, session_index, session_path = _write_codex_session(tmp_path)
    _configure_env(monkeypatch, tmp_path, codex_sessions, session_index)
    codex_local_connector.scan_sessions(dry_run=False, limit=20)

    first = raw_record_guardian.build_guardian_status(
        limit=20,
        include_gaps=False,
        write_index=True,
        public=False,
    )
    db_path = Path(first["index_update"]["db_path"])

    _append_jsonl(session_path, [{
        "timestamp": "2026-06-07T10:00:03Z",
        "type": "response_item",
        "payload": {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "fast watcher 先别补旧 offset。"}],
        },
    }])

    partial = raw_record_guardian.build_guardian_status(
        limit=20,
        include_gaps=False,
        write_index=True,
        public=False,
    )
    assert partial["index_update"]["canonical_raw_offset_coverage_count"] == 0

    codex_local_connector.scan_sessions(dry_run=False, limit=20)
    fast = raw_record_guardian.build_guardian_status(
        limit=20,
        include_gaps=False,
        write_index=True,
        public=False,
        scan_mode="fast",
    )

    assert fast["index_update"]["canonical_messages_upserted"] == 0
    assert fast["index_update"]["canonical_raw_offset_coverage_count"] == 0
    assert fast["index_update"]["canonical_raw_offset_repairs_deferred_count"] == 1
    assert fast["index_update"]["identity_drift_repair_skipped"] is True
    assert fast["index_update"]["canonical_results"][0]["raw_offset_repairs_deferred"] is True

    conn = sqlite3.connect(db_path)
    try:
        fast_session = conn.execute(
            "select indexed_message_count, raw_offset_coverage_count, index_status, payload_json from canonical_sessions"
        ).fetchone()
        fast_message = conn.execute(
            """
            select raw_available
            from canonical_messages
            where content_preview like '%fast watcher 先别补旧 offset%'
            """
        ).fetchone()
    finally:
        conn.close()

    assert fast_session[0:3] == (3, 2, "raw_offsets_partial")
    assert json.loads(fast_session[3])["incremental"]["raw_offset_repairs_deferred"] is True
    assert fast_message[0] == 0

    repaired = raw_record_guardian.build_guardian_status(
        limit=20,
        include_gaps=False,
        write_index=True,
        public=False,
    )

    conn = sqlite3.connect(db_path)
    try:
        repaired_session = conn.execute(
            "select indexed_message_count, raw_offset_coverage_count, index_status, payload_json from canonical_sessions"
        ).fetchone()
        repaired_message = conn.execute(
            """
            select raw_available, raw_line_no, raw_offset_start, raw_offset_end
            from canonical_messages
            where content_preview like '%fast watcher 先别补旧 offset%'
            """
        ).fetchone()
    finally:
        conn.close()

    assert repaired["index_update"]["canonical_messages_upserted"] == 0
    assert repaired["index_update"]["canonical_raw_offset_coverage_count"] == 1
    assert repaired["index_update"]["identity_drift_repair_skipped"] is False
    assert repaired["index_update"]["canonical_results"][0]["raw_offset_repairs_count"] == 1
    assert repaired["index_update"]["canonical_results"][0]["raw_offset_repairs_deferred"] is False
    assert repaired_session[0:3] == (3, 3, "raw_offsets_complete")
    assert json.loads(repaired_session[3])["incremental"]["raw_offset_repairs_deferred"] is False
    assert repaired_message[0] == 1
    assert repaired_message[1] == 4
    assert repaired_message[2] < repaired_message[3]


def test_canonical_record_index_keeps_bad_codex_line_health(tmp_path, monkeypatch):
    import codex_local_connector
    import raw_record_guardian

    codex_sessions, session_index, _ = _write_codex_session(tmp_path, bad_line=True)
    _configure_env(monkeypatch, tmp_path, codex_sessions, session_index)
    codex_local_connector.scan_sessions(dry_run=False, limit=20)

    report = raw_record_guardian.build_guardian_status(
        limit=20,
        include_gaps=False,
        write_index=True,
        public=False,
    )

    db_path = Path(report["index_update"]["db_path"])
    conn = sqlite3.connect(db_path)
    try:
        health = conn.execute(
            "select file_side, health_status, line_no, offset_start, offset_end from canonical_line_health order by file_side, line_no"
        ).fetchall()
        session = conn.execute(
            "select bad_json_line_count, index_status from canonical_sessions"
        ).fetchone()
    finally:
        conn.close()

    assert session[0] >= 2
    assert session[1] == "raw_offsets_complete"
    assert [row[1] for row in health].count("bad_json_line") == 2
    assert all(row[3] < row[4] for row in health)


def test_raw_record_guardian_fast_mode_uses_stat_guard_without_body_scan(tmp_path, monkeypatch):
    import codex_local_connector
    import raw_record_guardian

    codex_sessions, session_index, _ = _write_codex_session(tmp_path)
    _configure_env(monkeypatch, tmp_path, codex_sessions, session_index)
    codex_local_connector.scan_sessions(dry_run=False, limit=20)

    report = raw_record_guardian.build_guardian_status(
        limit=20,
        include_gaps=False,
        scan_mode="fast",
        public=False,
    )

    assert report["scan_mode"] == "fast"
    assert report["fast_status_only"] is True
    assert report["summary"]["record_count"] == 1
    assert report["summary"]["record_guarded_count"] == 1
    assert report["summary"]["record_stat_guarded_count"] == 1
    assert report["summary"]["recoverable_from_raw_count"] == 0
    item = report["records"][0]
    assert item["guard_status"] == "record_stat_guarded"
    assert item["raw_current"] is True
    assert item["scan_mode"] == "fast"
    assert item["source_scan"]["fast_stat_only"] is True
    assert item["raw_scan"]["fast_stat_only"] is True
    assert item["source_scan"]["health_status"] == "stat_only"
    assert item["raw_scan"]["message_count"] is None
    assert item["recoverable_from_raw"] is None
    assert item["recoverability_status"] == "not_measured"


def test_fast_lost_source_uses_bounded_structural_recoverability_check(tmp_path, monkeypatch):
    import raw_record_guardian

    raw_path, _source_path = _write_claude_desktop_authorized_raw(
        tmp_path,
        monkeypatch,
        source_exists=False,
    )
    raw_record_guardian._RECOVERABILITY_CACHE.clear()

    report = raw_record_guardian.build_guardian_status(
        limit=20,
        include_gaps=False,
        scan_mode="fast",
        compact=True,
        public=False,
    )

    item = report["records"][0]
    assert item["origin_status"] == "lost_source"
    assert item["recoverable_from_raw"] is True
    assert item["recoverability_status"] == "measured_recoverable"
    assert item["recoverability_evidence"]["method"] == "targeted_structural_scan"
    assert report["summary"]["lost_source_recoverable_count"] == 1
    assert report["summary"]["lost_source_unrecoverable_count"] == 0
    assert report["summary"]["lost_source_not_measured_count"] == 0
    assert report["recoverability_probe"]["targeted_scan_count"] == 1
    assert report["recoverability_probe"]["bytes_read"] == raw_path.stat().st_size


def test_fast_lost_source_budget_exhaustion_stays_not_measured(tmp_path, monkeypatch):
    import raw_record_guardian

    _write_claude_desktop_authorized_raw(tmp_path, monkeypatch, source_exists=False)
    raw_record_guardian._RECOVERABILITY_CACHE.clear()
    monkeypatch.setattr(raw_record_guardian, "DEFAULT_LOST_SOURCE_RECOVERABILITY_FILE_BYTES", 1)

    report = raw_record_guardian.build_guardian_status(
        limit=20,
        include_gaps=False,
        scan_mode="fast",
        compact=True,
        public=False,
    )

    item = report["records"][0]
    assert item["recoverable_from_raw"] is None
    assert item["recoverability_status"] == "not_measured"
    assert item["recoverability_evidence"]["reason"] == "per_file_byte_limit_exceeded"
    assert report["summary"]["lost_source_not_measured_count"] == 1
    assert report["summary"]["lost_source_unrecoverable_count"] == 0
    assert report["recoverability_probe"]["budget_exhausted_count"] == 1


def test_raw_identity_change_invalidates_recoverability_cache(tmp_path, monkeypatch):
    import raw_record_guardian

    raw_path, _source_path = _write_claude_desktop_authorized_raw(
        tmp_path,
        monkeypatch,
        source_exists=False,
    )
    raw_record_guardian._RECOVERABILITY_CACHE.clear()
    first = raw_record_guardian.build_guardian_status(
        limit=20,
        include_gaps=False,
        scan_mode="fast",
        public=False,
    )
    assert first["summary"]["lost_source_recoverable_count"] == 1

    first_record = json.loads(raw_path.read_text(encoding="utf-8").splitlines()[0])
    raw_path.write_text(json.dumps(first_record, ensure_ascii=False) + "\n", encoding="utf-8")
    second = raw_record_guardian.build_guardian_status(
        limit=20,
        include_gaps=False,
        scan_mode="fast",
        public=False,
    )

    assert second["recoverability_probe"]["cache_hit_count"] == 0
    assert second["recoverability_probe"]["targeted_scan_count"] == 1
    assert second["summary"]["lost_source_recoverable_count"] == 1
    assert second["summary"]["lost_source_unrecoverable_count"] == 0
    assert second["records"][0]["recoverable_from_raw"] is True
    assert second["records"][0]["recoverability_class"] == "conversation_one_sided"


def test_fast_index_write_preserves_prior_measured_recoverability(tmp_path, monkeypatch):
    import codex_local_connector
    import raw_record_guardian

    codex_sessions, session_index, _ = _write_codex_session(tmp_path)
    _configure_env(monkeypatch, tmp_path, codex_sessions, session_index)
    codex_local_connector.scan_sessions(dry_run=False, limit=20)
    raw_record_guardian.build_guardian_status(
        limit=20,
        include_gaps=False,
        write_index=True,
        public=False,
    )
    fast = raw_record_guardian.build_guardian_status(
        limit=20,
        include_gaps=False,
        scan_mode="fast",
        write_index=True,
        public=False,
    )

    conn = sqlite3.connect(os.environ["MEMCORE_RECORDS_DB"])
    try:
        row = conn.execute(
            "select user_turn_count, assistant_turn_count, has_user_and_assistant, recoverable_from_raw from records"
        ).fetchone()
    finally:
        conn.close()

    assert fast["records"][0]["recoverable_from_raw"] is None
    assert row == (1, 1, 1, 1)


def test_fast_lost_source_prefers_matching_canonical_recoverability_evidence(tmp_path, monkeypatch):
    import raw_record_guardian

    _raw_path, source_path = _write_claude_desktop_authorized_raw(
        tmp_path,
        monkeypatch,
        source_exists=True,
    )
    raw_record_guardian._RECOVERABILITY_CACHE.clear()
    raw_record_guardian.build_guardian_status(
        limit=20,
        include_gaps=False,
        write_index=True,
        public=False,
    )
    source_path.unlink()
    raw_record_guardian._RECOVERABILITY_CACHE.clear()

    report = raw_record_guardian.build_guardian_status(
        limit=20,
        include_gaps=False,
        scan_mode="fast",
        public=False,
    )

    assert report["summary"]["lost_source_recoverable_count"] == 1
    assert report["recoverability_probe"]["canonical_cache_hit_count"] == 1
    assert report["recoverability_probe"]["targeted_scan_count"] == 0
    assert report["recoverability_probe"]["bytes_read"] == 0
    assert report["records"][0]["recoverability_evidence"]["method"] == "canonical_record_identity_cache"


def test_raw_record_guardian_flags_bad_jsonl(tmp_path, monkeypatch):
    import codex_local_connector
    import raw_record_guardian

    codex_sessions, session_index, _ = _write_codex_session(tmp_path, bad_line=True)
    _configure_env(monkeypatch, tmp_path, codex_sessions, session_index)
    codex_local_connector.scan_sessions(dry_run=False, limit=20)

    report = raw_record_guardian.build_guardian_status(limit=20, include_gaps=False, public=False)

    assert report["summary"]["corrupt_record_count"] == 1
    item = report["records"][0]
    assert item["guard_status"] in {"source_corrupt", "raw_corrupt"}
    assert item["source_scan"]["bad_json_line_count"] == 1


def test_raw_record_guardian_flags_user_only_as_partial(tmp_path, monkeypatch):
    import codex_local_connector
    import raw_record_guardian

    codex_sessions, session_index, _ = _write_codex_session(tmp_path, assistant=False)
    _configure_env(monkeypatch, tmp_path, codex_sessions, session_index)
    codex_local_connector.scan_sessions(dry_run=False, limit=20)

    report = raw_record_guardian.build_guardian_status(limit=20, include_gaps=False, public=False)

    assert report["summary"]["partial_record_count"] == 1
    item = report["records"][0]
    assert item["guard_status"] == "source_partial_conversation"
    assert item["source_scan"]["user_turn_count"] == 1
    assert item["source_scan"]["assistant_turn_count"] == 0
    assert item["recoverable_from_raw"] is False


def test_raw_record_guardian_treats_oversize_as_warning_not_lagging(tmp_path, monkeypatch):
    import codex_local_connector
    import raw_record_guardian

    codex_sessions, session_index, _ = _write_codex_session(tmp_path, oversize=True)
    _configure_env(monkeypatch, tmp_path, codex_sessions, session_index)
    codex_local_connector.scan_sessions(dry_run=False, limit=20)

    report = raw_record_guardian.build_guardian_status(
        limit=20,
        include_gaps=False,
        oversize_bytes=1024,
        public=False,
    )

    item = report["records"][0]
    assert item["guard_status"] == "record_guarded"
    assert item["raw_current"] is True
    assert "source_oversized" in item["health_warnings"]
    assert "raw_oversized" in item["health_warnings"]
    assert report["summary"]["oversized_record_count"] == 1
    assert report["summary"]["raw_lagging_or_missing_count"] == 0
    assert report["summary"]["raw_not_current_count"] == 0


def test_raw_record_guardian_surfaces_raw_catching_up_and_auto_backfills(tmp_path, monkeypatch):
    import codex_local_connector
    import raw_record_guardian

    codex_sessions, session_index, session_path = _write_codex_session(tmp_path)
    _configure_env(monkeypatch, tmp_path, codex_sessions, session_index)
    first_scan = codex_local_connector.scan_sessions(dry_run=False, limit=20)
    assert first_scan["changed"] == 1

    _append_jsonl(session_path, [
        {
            "timestamp": "2026-06-07T10:00:04Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "继续追尾这条大会话。"}],
            },
        },
        {
            "timestamp": "2026-06-07T10:00:05Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "已补扫新增尾部。"}],
            },
        },
    ])

    lag_report = raw_record_guardian.build_guardian_status(limit=20, include_gaps=False, public=False)
    lag_item = lag_report["records"][0]
    assert lag_item["guard_status"] == "raw_catching_up"
    assert lag_item["backfill_recommended"] is False
    assert lag_item["sync"]["raw_stale"] is True
    assert lag_report["summary"]["raw_not_current_count"] == 1
    assert lag_report["summary"]["raw_lagging_or_missing_count"] == 0
    assert lag_report["summary"]["raw_catching_up_count"] == 1
    assert lag_report["summary"]["raw_active_catching_up_count"] == 1
    assert lag_report["summary"]["raw_attention_count"] == 0
    assert lag_report["summary"]["backfill_recommended_count"] == 0
    assert lag_report["summary"]["max_raw_lag_bytes"] > 0

    backfilled = raw_record_guardian.build_guardian_status(
        limit=20,
        include_gaps=False,
        auto_backfill=True,
        public=False,
    )

    assert backfilled["read_only"] is False
    assert backfilled["write_performed"] is True
    assert backfilled["memory_write_performed"] is True
    assert backfilled["backfill"]["contract"] == raw_record_guardian.RAW_BACKFILL_CONTRACT
    assert backfilled["backfill"]["results"][0]["changed"] >= 1
    assert backfilled["records"][0]["guard_status"] == "record_guarded"
    assert backfilled["records"][0]["raw_current"] is True
    assert backfilled["summary"]["raw_not_current_count"] == 0


def test_raw_record_guardian_fast_mode_surfaces_stale_raw_without_deep_scan(tmp_path, monkeypatch):
    import codex_local_connector
    import raw_record_guardian

    codex_sessions, session_index, session_path = _write_codex_session(tmp_path)
    _configure_env(monkeypatch, tmp_path, codex_sessions, session_index)
    codex_local_connector.scan_sessions(dry_run=False, limit=20)

    _append_jsonl(session_path, [
        {
            "timestamp": "2026-06-07T10:00:04Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "fast mode 也要看见源文件变长。"}],
            },
        },
    ])

    report = raw_record_guardian.build_guardian_status(
        limit=20,
        include_gaps=False,
        scan_mode="fast",
        public=False,
    )

    assert report["scan_mode"] == "fast"
    assert report["fast_status_only"] is True
    assert report["summary"]["raw_not_current_count"] == 1
    assert report["summary"]["raw_lagging_or_missing_count"] == 0
    assert report["summary"]["raw_attention_count"] == 0
    assert report["summary"]["backfill_recommended_count"] == 0
    item = report["records"][0]
    assert item["guard_status"] == "raw_catching_up"
    assert item["backfill_recommended"] is False
    assert item["sync"]["raw_stale"] is True
    assert item["source_scan"]["fast_stat_only"] is True
    assert item["raw_scan"]["fast_stat_only"] is True


def test_raw_record_guardian_compact_mode_keeps_summary_and_problem_records(tmp_path, monkeypatch):
    import codex_local_connector
    import raw_record_guardian

    codex_sessions, session_index, session_path = _write_codex_session(tmp_path)
    _configure_env(monkeypatch, tmp_path, codex_sessions, session_index)
    codex_local_connector.scan_sessions(dry_run=False, limit=20)

    _append_jsonl(session_path, [
        {
            "timestamp": "2026-06-07T10:00:04Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "compact 只保留追尾摘要。"}],
            },
        },
    ])

    report = raw_record_guardian.build_guardian_status(
        limit=20,
        include_gaps=False,
        scan_mode="fast",
        compact=True,
        public=False,
    )

    assert report["compact"] is True
    assert report["record_details_truncated"] is True
    assert report["record_detail_count"] == 1
    assert report["summary"]["raw_catching_up_count"] == 1
    assert report["summary"]["raw_active_catching_up_count"] == 1
    assert report["summary"]["raw_attention_count"] == 0
    assert report["summary"]["backfill_recommended_count"] == 0
    assert len(report["records"]) == 1
    item = report["records"][0]
    assert item["guard_status"] == "raw_catching_up"
    assert "source_scan" not in item
    assert "raw_scan" not in item


def test_raw_record_guardian_lagging_waits_before_recommending_backfill(tmp_path, monkeypatch):
    import codex_local_connector
    import raw_record_guardian

    codex_sessions, session_index, session_path = _write_codex_session(tmp_path)
    _configure_env(monkeypatch, tmp_path, codex_sessions, session_index)
    codex_local_connector.scan_sessions(dry_run=False, limit=20)
    _append_jsonl(session_path, [
        {
            "timestamp": "2026-06-07T10:00:04Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "短暂 lag 不要吓人。"}],
            },
        },
    ])

    original_sync_item = codex_local_connector._raw_sync_item

    def short_lag_sync_item(artifact):
        item = original_sync_item(artifact)
        item["raw_archive_lag_milliseconds"] = 2000
        return item

    monkeypatch.setattr(codex_local_connector, "_raw_sync_item", short_lag_sync_item)

    report = raw_record_guardian.build_guardian_status(
        limit=20,
        include_gaps=False,
        scan_mode="fast",
        public=False,
    )

    item = report["records"][0]
    assert item["guard_status"] == "raw_lagging"
    assert item["sync"]["raw_lag_sla_breach"] is True
    assert item["sync"]["backfill_recommend_after_milliseconds"] == 5000
    assert item["backfill_recommended"] is False
    assert report["summary"]["backfill_recommended_count"] == 0
    assert report["summary"]["raw_lagging_or_missing_count"] == 1
    assert report["summary"]["raw_attention_count"] == 0


def test_raw_record_guardian_recommends_backfill_after_extended_lag(tmp_path, monkeypatch):
    import codex_local_connector
    import raw_record_guardian

    codex_sessions, session_index, session_path = _write_codex_session(tmp_path)
    _configure_env(monkeypatch, tmp_path, codex_sessions, session_index)
    codex_local_connector.scan_sessions(dry_run=False, limit=20)
    _append_jsonl(session_path, [
        {
            "timestamp": "2026-06-07T10:00:04Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "超过去抖阈值才建议回填。"}],
            },
        },
    ])

    original_sync_item = codex_local_connector._raw_sync_item

    def long_lag_sync_item(artifact):
        item = original_sync_item(artifact)
        item["raw_archive_lag_milliseconds"] = 6000
        return item

    monkeypatch.setattr(codex_local_connector, "_raw_sync_item", long_lag_sync_item)

    report = raw_record_guardian.build_guardian_status(
        limit=20,
        include_gaps=False,
        scan_mode="fast",
        public=False,
    )

    item = report["records"][0]
    assert item["guard_status"] == "raw_lagging"
    assert item["sync"]["raw_lag_sla_breach"] is True
    assert item["sync"]["backfill_recommend_after_milliseconds"] == 5000
    assert item["backfill_recommended"] is True
    assert report["summary"]["backfill_recommended_count"] == 1
    assert report["summary"]["raw_lagging_or_missing_count"] == 1
    assert report["summary"]["raw_attention_count"] == 1


def test_fast_guardian_keeps_unproven_rewrite_fail_closed_without_body_scan(tmp_path, monkeypatch):
    import codex_local_connector
    import raw_record_guardian

    codex_sessions, session_index, session_path = _write_codex_session(tmp_path)
    _configure_env(monkeypatch, tmp_path, codex_sessions, session_index)
    first_scan = codex_local_connector.scan_sessions(dry_run=False, limit=20)
    raw_path = Path(first_scan["items"][0]["dest"])
    raw_before = raw_path.read_bytes()

    rewritten = session_path.read_text(encoding="utf-8").replace(
        "守住原始记录。",
        "上游改写了这条源记录；旧 raw 必须保留并显式报告分歧。",
    )
    session_path.write_text(rewritten, encoding="utf-8")
    old = time.time() - 10
    os.utime(session_path, (old, old))

    report = raw_record_guardian.build_guardian_status(
        limit=20,
        include_gaps=False,
        scan_mode="fast",
        public=False,
    )

    item = report["records"][0]
    assert item["guard_status"] == "raw_catching_up"
    assert item["sync"]["raw_source_divergence"] is False
    assert item["sync"]["raw_continuity_not_measured"] is True
    assert item["sync"]["raw_monotonic_status"] == "raw_continuity_not_measured_fast"
    assert item["sync"]["raw_body_read_performed"] is False
    assert item["backfill_recommended"] is False
    assert report["summary"]["raw_not_current_count"] == 1
    assert report["summary"]["raw_lagging_or_missing_count"] == 0
    assert report["summary"]["raw_attention_count"] == 0
    assert report["summary"]["raw_source_divergence_count"] == 0
    assert report["summary"]["raw_continuity_not_measured_count"] == 1
    assert report["ok"] is False
    assert report["summary"]["backfill_recommended_count"] == 0
    snapshot = codex_local_connector.raw_sync_snapshot(limit=20)
    assert snapshot["status"] == "source_divergence_raw_retained"
    assert snapshot["raw_source_divergence_count"] == 1
    assert snapshot["raw_lag_sla_breach_count"] == 0
    assert snapshot["raw_catching_up_count"] == 0
    assert raw_path.read_bytes() == raw_before


def test_fast_guardian_summary_uses_population_beyond_detail_limit(tmp_path, monkeypatch):
    import codex_local_connector
    import raw_record_guardian

    codex_sessions, session_index, session_path = _write_codex_session(tmp_path)
    _configure_env(monkeypatch, tmp_path, codex_sessions, session_index)
    original = session_path.read_text(encoding="utf-8")
    index_rows = [json.loads(session_index.read_text(encoding="utf-8"))]
    for index in (2, 3):
        session_id = f"019e-test-raw-guardian-{index}"
        sibling = session_path.with_name(
            f"rollout-2026-06-07T10-00-0{index}-{session_id}.jsonl"
        )
        sibling.write_text(
            original.replace("019e-test-raw-guardian", session_id),
            encoding="utf-8",
        )
        index_rows.append({"id": session_id, "thread_name": f"Raw Guardian {index}"})
    session_index.write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in index_rows),
        encoding="utf-8",
    )
    archived = codex_local_connector.scan_sessions(dry_run=False, limit=0)
    assert archived["changed"] == 3

    report = raw_record_guardian.build_guardian_status(
        limit=1,
        include_gaps=False,
        scan_mode="fast",
        public=False,
        source_systems=["codex"],
    )

    assert report["summary"]["record_count"] == 3
    assert report["summary"]["physical_record_count"] == 3
    assert report["summary"]["logical_record_count"] == 3
    assert report["summary_scope"]["population_complete"] is True
    assert report["summary_scope"]["detail_limit"] == 1
    assert report["summary_scope"]["summary_is_sample"] is False
    assert report["record_detail_count"] == 1
    assert report["record_details_truncated"] is True
    assert len(report["records"]) == 1


def test_fast_guardian_scales_to_full_population_without_body_or_prefix_reads(tmp_path, monkeypatch):
    import codex_local_connector
    import raw_archive_monotonic
    import raw_record_guardian

    codex_sessions, _session_index, session_path = _write_codex_session(tmp_path)
    _configure_env(monkeypatch, tmp_path, codex_sessions, tmp_path / "missing-index.jsonl")
    template = session_path.read_bytes()
    artifact = codex_local_connector.artifact_from_path(session_path)
    raw_path = codex_local_connector._raw_dest_for_artifact(artifact)
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_bytes(template)
    source_stat = session_path.stat()
    Path(str(raw_path) + ".meta.json").write_text(
        json.dumps({
            "source_inode": source_stat.st_ino,
            "source_mtime": source_stat.st_mtime,
            "file_offset": source_stat.st_size,
        }),
        encoding="utf-8",
    )
    artifacts = [artifact] * 1251
    original_iterdir = Path.iterdir
    archive_directory_scans = 0

    def count_archive_directory_scans(path):
        nonlocal archive_directory_scans
        if path == raw_path.parent:
            archive_directory_scans += 1
        return original_iterdir(path)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("fast Guardian read a source/raw body or invoked prefix append")

    monkeypatch.setattr(Path, "iterdir", count_archive_directory_scans)
    monkeypatch.setattr(codex_local_connector, "select_archive_segment", forbidden)
    monkeypatch.setattr(codex_local_connector, "append_source_file", forbidden)
    monkeypatch.setattr(codex_local_connector, "cached_divergence_witness_visible", forbidden)
    monkeypatch.setattr(codex_local_connector, "_metadata_only_divergence_probe", forbidden)
    monkeypatch.setattr(raw_archive_monotonic, "_prefix_matches", forbidden)

    report = raw_record_guardian.build_guardian_status(
        limit=1,
        include_gaps=False,
        scan_mode="fast",
        public=False,
        source_systems=["codex"],
        connector_artifacts={"codex": artifacts},
    )

    assert report["summary"]["record_count"] == 1251
    assert report["summary"]["record_stat_guarded_count"] == 1251
    assert report["summary"]["raw_continuity_not_measured_count"] == 0
    assert report["summary_scope"]["population_complete"] is False
    assert report["summary_scope"]["summary_is_sample"] is True
    assert report["summary_scope"]["sources"]["codex"]["included_count"] == 1251
    assert report["summary_scope"]["sources"]["codex"]["targeted"] is True
    assert report["record_detail_count"] == 1
    assert report["records"][0]["sync"]["raw_body_read_performed"] is False
    assert archive_directory_scans == 1


def test_fast_guardian_full_discovery_population_over_detail_limit_remains_complete(tmp_path, monkeypatch):
    import codex_local_connector
    import raw_record_guardian

    codex_sessions, _session_index, session_path = _write_codex_session(tmp_path)
    _configure_env(monkeypatch, tmp_path, codex_sessions, tmp_path / "missing-index.jsonl")
    artifact = codex_local_connector.artifact_from_path(session_path)
    raw_path = codex_local_connector._raw_dest_for_artifact(artifact)
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_bytes(session_path.read_bytes())
    source_stat = session_path.stat()
    Path(str(raw_path) + ".meta.json").write_text(
        json.dumps({
            "source_inode": source_stat.st_ino,
            "source_mtime": source_stat.st_mtime,
            "file_offset": source_stat.st_size,
        }),
        encoding="utf-8",
    )
    artifacts = [artifact] * 1251
    discovery_calls = []

    def discover_sessions(*, limit, scan_mode):
        discovery_calls.append({"limit": limit, "scan_mode": scan_mode})
        return artifacts[:limit]

    monkeypatch.setattr(codex_local_connector, "discover_sessions", discover_sessions)

    report = raw_record_guardian.build_guardian_status(
        limit=1,
        include_gaps=False,
        scan_mode="fast",
        public=False,
        source_systems=["codex"],
    )

    assert report["summary"]["record_count"] == 1251
    assert report["summary_scope"]["population_complete"] is True
    assert report["summary_scope"]["summary_is_sample"] is False
    assert report["summary_scope"]["detail_limit"] == 1
    assert report["summary_scope"]["population_limit_per_source"] == 2000
    assert report["record_detail_count"] == 1
    assert discovery_calls == [{"limit": 2001, "scan_mode": "fast"}]


def test_fast_guardian_keeps_unproven_legacy_pairing_fail_closed(tmp_path, monkeypatch):
    import codex_local_connector
    import raw_record_guardian

    codex_sessions, _session_index, session_path = _write_codex_session(tmp_path)
    _configure_env(monkeypatch, tmp_path, codex_sessions, tmp_path / "missing-index.jsonl")
    artifact = codex_local_connector.artifact_from_path(session_path)
    raw_path = codex_local_connector._raw_dest_for_artifact(artifact)
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_bytes(session_path.read_bytes())

    report = raw_record_guardian.build_guardian_status(
        limit=20,
        include_gaps=False,
        scan_mode="fast",
        public=False,
        source_systems=["codex"],
    )

    item = report["records"][0]
    assert item["guard_status"] == "raw_continuity_not_measured"
    assert item["raw_current"] is False
    assert item["sync"]["raw_continuity_not_measured"] is True
    assert item["sync"]["raw_monotonic_probe_ok"] is None
    assert item["sync"]["raw_body_read_performed"] is False
    assert item["backfill_recommended"] is False
    assert report["summary"]["record_stat_guarded_count"] == 0
    assert report["summary"]["raw_continuity_not_measured_count"] == 1
    assert report["summary"]["raw_attention_count"] == 0
    assert report["ok"] is False


@pytest.mark.parametrize(
    ("archived_provider", "rewritten_provider"),
    [("token", "custom"), ("custom", "x")],
)
def test_codex_inode_drift_metadata_only_rewrite_is_not_raw_lag(
    tmp_path,
    monkeypatch,
    archived_provider,
    rewritten_provider,
):
    import codex_local_connector
    import raw_record_guardian

    codex_sessions, session_index, session_path = _write_codex_session(tmp_path)
    _configure_env(monkeypatch, tmp_path, codex_sessions, session_index)
    records = [json.loads(line) for line in session_path.read_text(encoding="utf-8").splitlines()]
    records[0]["payload"]["model_provider"] = archived_provider
    session_path.write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in records),
        encoding="utf-8",
    )
    first_scan = codex_local_connector.scan_sessions(dry_run=False, limit=20)
    raw_path = Path(first_scan["items"][0]["dest"])
    raw_before = raw_path.read_bytes()
    old_inode = session_path.stat().st_ino

    records[0]["payload"]["model_provider"] = rewritten_provider
    replacement = session_path.with_suffix(".replacement")
    replacement.write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in records),
        encoding="utf-8",
    )
    os.replace(replacement, session_path)
    assert session_path.stat().st_ino != old_inode

    report = raw_record_guardian.build_guardian_status(
        limit=20,
        include_gaps=False,
        scan_mode="full",
        public=False,
        source_systems=["codex"],
    )

    item = report["records"][0]
    assert item["guard_status"] == "source_divergence_metadata_only_raw_retained"
    assert item["sync"]["raw_source_divergence"] is True
    assert item["sync"]["raw_metadata_only_divergence"] is True
    assert item["sync"]["raw_archive_lag_bytes"] == 0
    assert item["sync"]["raw_size_delta_bytes"] == abs(
        len(rewritten_provider) - len(archived_provider)
    )
    assert item["sync"]["raw_source_regression"] is False
    assert item["sync"]["metadata_only_fields"] == ["payload.model_provider"]
    assert item["backfill_recommended"] is False
    assert report["summary"]["raw_lagging_or_missing_count"] == 0
    assert report["summary"]["raw_metadata_only_divergence_count"] == 1
    assert report["summary"]["max_raw_lag_bytes"] == 0
    assert report["summary"]["raw_attention_count"] == 0
    assert raw_path.read_bytes() == raw_before

    snapshot = codex_local_connector.raw_sync_snapshot(limit=20)
    assert snapshot["status"] == "raw_current_metadata_divergence_retained"
    assert snapshot["raw_source_divergence_count"] == 0
    assert snapshot["raw_metadata_only_divergence_count"] == 1
    assert snapshot["raw_overrun_count"] == 0
    assert snapshot["missing_or_stale_count"] == 0


def test_codex_fast_guardian_reuses_persisted_metadata_only_witness_without_body_read(
    tmp_path,
    monkeypatch,
):
    import codex_local_connector
    import raw_record_guardian

    codex_sessions, session_index, session_path = _write_codex_session(tmp_path)
    _configure_env(monkeypatch, tmp_path, codex_sessions, session_index)
    records = [json.loads(line) for line in session_path.read_text(encoding="utf-8").splitlines()]
    records[0]["payload"]["model_provider"] = "custom-provider"
    session_path.write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in records),
        encoding="utf-8",
    )
    first_scan = codex_local_connector.scan_sessions(dry_run=False, limit=20)
    raw_path = Path(first_scan["items"][0]["dest"])
    raw_before = raw_path.read_bytes()

    records[0]["payload"]["model_provider"] = "x"
    session_path.write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in records),
        encoding="utf-8",
    )
    artifact = codex_local_connector.artifact_from_path(session_path)
    dest, status = codex_local_connector.archive_session_incremental(
        str(session_path),
        artifact=artifact,
    )
    witness_path = Path(
        str(dest) + codex_local_connector.METADATA_DIVERGENCE_WITNESS_SUFFIX
    )

    assert status.startswith("source_divergence_metadata_only_raw_retained")
    assert Path(dest) == raw_path
    assert witness_path.is_file()
    witness_text = witness_path.read_text(encoding="ascii")
    assert str(session_path) not in witness_text
    assert "custom-provider" not in witness_text
    assert raw_path.read_bytes() == raw_before
    checkpoint = codex_local_connector.load_checkpoint()
    assert checkpoint[codex_local_connector._checkpoint_key(str(session_path))]["archived_to"] == str(raw_path)

    def body_probe_must_not_run(*_args, **_kwargs):
        raise AssertionError("fast Guardian reran the metadata body probe")

    monkeypatch.setattr(
        codex_local_connector,
        "_metadata_only_divergence_probe",
        body_probe_must_not_run,
    )
    report = raw_record_guardian.build_guardian_status(
        limit=20,
        include_gaps=False,
        scan_mode="fast",
        public=False,
        source_systems=["codex"],
    )
    item = report["records"][0]

    assert item["guard_status"] == "source_divergence_metadata_only_raw_retained"
    assert item["sync"]["raw_metadata_only_divergence"] is True
    assert item["sync"]["raw_source_regression"] is False
    assert item["sync"]["raw_archive_lag_bytes"] == 0
    assert item["sync"]["raw_body_read_performed"] is False
    assert item["sync"]["metadata_divergence_probe"]["witness_hit"] is True
    assert item["backfill_recommended"] is False
    assert report["summary"]["raw_metadata_only_divergence_count"] == 1
    assert report["summary"]["raw_source_regression_count"] == 0
    assert report["summary"]["raw_attention_count"] == 0


def test_codex_metadata_only_cached_probe_can_still_persist_witness(tmp_path):
    import codex_local_connector

    source = tmp_path / "source.jsonl"
    archive = tmp_path / "archive.jsonl"
    source.write_text(
        '{"payload":{"model_provider":"new","text":"same"}}\n',
        encoding="utf-8",
    )
    archive.write_text(
        '{"payload":{"model_provider":"archived-provider","text":"same"}}\n',
        encoding="utf-8",
    )
    codex_local_connector._METADATA_DIVERGENCE_CACHE.clear()

    first = codex_local_connector._metadata_only_divergence_probe(source, archive)
    assert first["matched"] is True
    assert not codex_local_connector._metadata_divergence_witness_path(archive).exists()

    second = codex_local_connector._metadata_only_divergence_probe(
        source,
        archive,
        persist_witness=True,
    )

    assert second["cache_hit"] is True
    assert second["witness_written"] is True
    witness = codex_local_connector._load_metadata_divergence_witness(source, archive)
    assert witness["matched"] is True
    assert witness["witness_hit"] is True


def test_codex_metadata_only_witness_rejects_non_regression_pair(tmp_path):
    import codex_local_connector

    source = tmp_path / "source.jsonl"
    archive = tmp_path / "archive.jsonl"
    source.write_text(
        '{"payload":{"model_provider":"longer-provider","text":"same"}}\n',
        encoding="utf-8",
    )
    archive.write_text(
        '{"payload":{"model_provider":"x","text":"same"}}\n',
        encoding="utf-8",
    )

    result = codex_local_connector._metadata_only_divergence_probe(
        source,
        archive,
        persist_witness=True,
    )

    assert result["matched"] is True
    assert result["witness_written"] is False
    assert not codex_local_connector._metadata_divergence_witness_path(archive).exists()


def test_codex_fast_guardian_rejects_stale_metadata_only_witness(tmp_path, monkeypatch):
    import codex_local_connector

    source = tmp_path / "source.jsonl"
    archive = tmp_path / "archive.jsonl"
    source.write_text(
        json.dumps({"payload": {"model_provider": "x", "value": 1}}) + "\n",
        encoding="utf-8",
    )
    archive.write_text(
        json.dumps({"payload": {"model_provider": "long", "value": 1}}) + "\n",
        encoding="utf-8",
    )
    probe = codex_local_connector._metadata_only_divergence_probe(
        source,
        archive,
        persist_witness=True,
    )
    assert probe["matched"] is True
    assert probe["witness_written"] is True

    source.write_text(
        json.dumps({"payload": {"model_provider": "x", "value": 2}}) + "\n",
        encoding="utf-8",
    )
    witness = codex_local_connector._load_metadata_divergence_witness(source, archive)

    assert witness["matched"] is False
    assert witness["status"] == "witness_stale_or_invalid"


def test_lost_source_non_conversation_layout_variants_are_one_logical_record(tmp_path, monkeypatch):
    import raw_record_guardian

    raw_path, _source_path = _write_claude_desktop_authorized_raw(
        tmp_path,
        monkeypatch,
        source_exists=False,
    )
    source_ref = json.loads(raw_path.read_text(encoding="utf-8").splitlines()[0])["source_refs"]
    non_conversation = [
        {
            "type": "response_item",
            "payload": {"type": "authorized_local_store_record", "record_id": f"item-{index}"},
            "source_refs": source_ref,
        }
        for index in (1, 2)
    ]
    raw_path.write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in non_conversation),
        encoding="utf-8",
    )
    legacy_path = raw_path.parents[1] / "claude_desktop" / raw_path.name
    legacy_path.parent.mkdir(parents=True)
    legacy_path.write_bytes(raw_path.read_bytes())
    raw_record_guardian._RECOVERABILITY_CACHE.clear()

    report = raw_record_guardian.build_guardian_status(
        limit=20,
        include_gaps=False,
        scan_mode="fast",
        public=False,
        source_systems=["claude_desktop"],
    )

    assert report["summary"]["physical_record_count"] == 2
    assert report["summary"]["logical_record_count"] == 1
    assert report["summary"]["layout_variant_count"] == 1
    assert report["summary"]["lost_source_count"] == 1
    assert report["summary"]["lost_source_recoverable_count"] == 1
    assert report["summary"]["lost_source_non_conversation_count"] == 1
    assert report["summary"]["lost_source_unrecoverable_count"] == 0
    assert report["summary"]["raw_attention_count"] == 0
    assert len(report["records"]) == 2
    assert {item["logical_variant_count"] for item in report["records"]} == {2}
    assert {item["recoverability_class"] for item in report["records"]} == {
        "non_conversation_structurally_valid"
    }
    assert all(item["recoverable_from_raw"] is True for item in report["records"])


def test_lost_source_user_only_entrypoint_is_measured_one_sided_not_unrecoverable(tmp_path, monkeypatch):
    import raw_record_guardian

    raw_path, source_path, _session_id = _write_claude_desktop_projects_jsonl_raw(
        tmp_path,
        monkeypatch,
    )
    first_line = raw_path.read_text(encoding="utf-8").splitlines()[0]
    raw_path.write_text(first_line + "\n", encoding="utf-8")
    source_path.unlink()
    raw_record_guardian._RECOVERABILITY_CACHE.clear()

    report = raw_record_guardian.build_guardian_status(
        limit=20,
        include_gaps=False,
        scan_mode="fast",
        public=False,
        source_systems=["claude_desktop"],
    )

    item = report["records"][0]
    assert item["recoverability_class"] == "conversation_one_sided"
    assert item["recoverability_status"] == "measured_recoverable_one_sided"
    assert item["recoverable_from_raw"] is True
    assert item["guard_status"] == "authorized_raw_one_sided_source_missing"
    assert report["summary"]["lost_source_count"] == 1
    assert report["summary"]["lost_source_one_sided_count"] == 1
    assert report["summary"]["lost_source_unrecoverable_count"] == 0
    assert report["summary"]["raw_attention_count"] == 0


def test_targeted_guardian_reuses_fresh_divergence_witness_without_discovery(tmp_path, monkeypatch):
    import codex_local_connector
    import raw_record_guardian

    codex_sessions, session_index, session_path = _write_codex_session(tmp_path)
    _configure_env(monkeypatch, tmp_path, codex_sessions, session_index)
    first_scan = codex_local_connector.scan_sessions(dry_run=False, limit=20)
    raw_path = Path(first_scan["items"][0]["dest"])
    raw_before = raw_path.read_bytes()
    artifact = codex_local_connector.artifact_from_path(session_path)

    original = session_path.read_bytes()
    assert "守".encode("utf-8") in original
    rewritten = original.replace("守".encode("utf-8"), "改".encode("utf-8"), 1)
    assert len(rewritten) == len(original)
    session_path.write_bytes(rewritten)

    generation_dest, status = codex_local_connector.archive_session_incremental(
        str(session_path),
        artifact=artifact,
    )
    generation_raw = Path(generation_dest)
    assert status.startswith("generation_started")
    assert generation_raw != raw_path
    sync_item = codex_local_connector._raw_sync_item(artifact)
    assert sync_item["raw_source_divergence"] is True
    assert sync_item["raw_divergence_generation_active"] is True
    assert sync_item["raw_monotonic_status"] == "source_divergence_generation_active"

    def discovery_must_not_run(*_args, **_kwargs):
        raise AssertionError("targeted guardian performed full session discovery")

    monkeypatch.setattr(codex_local_connector, "discover_sessions", discovery_must_not_run)
    report = raw_record_guardian.build_guardian_status(
        limit=20,
        include_gaps=False,
        scan_mode="fast",
        public=False,
        source_systems=["codex"],
        connector_artifacts={"codex": [artifact]},
    )

    assert len(report["records"]) == 1
    assert report["records"][0]["guard_status"] == "source_divergence_generation_active"
    assert report["records"][0]["sync"]["raw_body_read_performed"] is False
    assert report["summary"]["raw_source_divergence_count"] == 1
    assert report["summary"]["raw_divergence_generation_active_count"] == 1
    assert report["summary"]["backfill_recommended_count"] == 0
    assert raw_path.read_bytes() == raw_before


def test_raw_record_guardian_guards_kiro_json_source_after_connector_scan(tmp_path, monkeypatch):
    import kiro_local_connector
    import raw_record_guardian

    session_root = tmp_path / "kiro-workspace-sessions"
    session_path = session_root / "workspace-alpha" / "session.json"
    _write_kiro_session(
        session_path,
        [
            {"id": "u1", "role": "user", "content": "Kiro 源 JSON 里的用户消息要进入 raw。"},
            {"id": "a1", "role": "assistant", "content": "Kiro 助手回复也要被 Guardian 证明。"},
        ],
    )
    _configure_kiro_guardian_env(monkeypatch, tmp_path, session_root)

    scanned = kiro_local_connector.scan_sessions(dry_run=False, limit=20)
    assert scanned["changed"] == 1

    report = raw_record_guardian.build_guardian_status(
        limit=20,
        include_gaps=True,
        scan_mode="full",
        public=False,
    )

    kiro_records = [item for item in report["records"] if item.get("source_system") == "kiro"]
    assert len(kiro_records) == 1
    item = kiro_records[0]
    assert item["guard_status"] == "record_guarded"
    assert item["raw_current"] is True
    assert item["source_scan"]["native_artifact_format"] == "kiro_workspace_sessions_json"
    assert item["source_scan"]["has_user_and_assistant"] is True
    assert item["raw_scan"]["has_user_and_assistant"] is True
    assert item["sync"]["raw_missing"] is False
    assert item["sync"]["raw_stale"] is False
    assert item["backfill_recommended"] is False
    assert "kiro" not in report["gap_sources"]
    assert "kiro" in report["guarded_sources"]


def test_raw_record_guardian_treats_kiro_without_local_sample_as_inactive_not_gap(tmp_path, monkeypatch):
    import raw_record_guardian

    _configure_kiro_guardian_env(monkeypatch, tmp_path, tmp_path / "missing-kiro-workspace-sessions")

    report = raw_record_guardian.build_guardian_status(
        limit=20,
        include_gaps=True,
        scan_mode="fast",
        public=False,
    )

    assert "kiro" in report["guarded_sources"]
    assert "kiro" not in report["gap_sources"]
    assert "kiro" in report["inactive_sources"]
    assert report["summary"]["gap_source_count"] == len(report["gaps"])
    assert report["summary"]["inactive_source_count"] >= 1
    inactive = next(item for item in report["inactive_source_details"] if item["source_system"] == "kiro")
    assert inactive["guard_status"] == "no_live_source_sample"


def test_raw_record_guardian_treats_implemented_platforms_without_samples_as_inactive(tmp_path, monkeypatch):
    import raw_record_guardian

    _configure_kiro_guardian_env(monkeypatch, tmp_path, tmp_path / "missing-kiro-workspace-sessions")

    report = raw_record_guardian.build_guardian_status(
        limit=20,
        include_gaps=True,
        scan_mode="fast",
        public=False,
    )

    for source in ("openclaw", "hermes", "kiro"):
        assert source in report["guarded_sources"]
        assert source not in report["gap_sources"]
        assert source in report["inactive_sources"]
        detail = next(item for item in report["inactive_source_details"] if item["source_system"] == source)
        assert detail["guard_status"] == "no_live_source_sample"
