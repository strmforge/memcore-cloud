import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


def _load_p0():
    if str(SRC) not in sys.path:
        sys.path.insert(0, str(SRC))
    sys.modules.pop("memcore_cloud_p0_under_test", None)
    spec = importlib.util.spec_from_file_location("memcore_cloud_p0_under_test", SRC / "memcore-cloud.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_p0_claude_desktop_scan_can_be_explicitly_disabled(monkeypatch):
    p0 = _load_p0()

    monkeypatch.setattr(p0, "config_get", lambda path, default=None: False)
    result = p0.scan_claude_desktop_raw(dry_run=False)

    assert result["status"] == "disabled"
    assert result["reason"] == "claude_desktop_raw_ingest_explicitly_disabled"
    assert result["memory_write_performed"] is False
    assert result["platform_write_performed"] is False


def test_p0_load_checkpoint_recovers_corrupt_file(tmp_path):
    p0 = _load_p0()
    checkpoint = tmp_path / ".checkpoint"
    checkpoint.write_bytes(b"\x00\x00not-json")
    p0.CHECKPOINT_FILE = str(checkpoint)

    assert p0.load_checkpoint() == {}
    assert not checkpoint.exists()
    backups = list(tmp_path.glob(".checkpoint.corrupt-backup-*"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == b"\x00\x00not-json"

    p0.save_checkpoint({"source.jsonl": {"offset": 12}})
    assert p0.load_checkpoint()["source.jsonl"]["offset"] == 12


def test_p0_save_checkpoint_retries_transient_windows_replace_lock(tmp_path, monkeypatch):
    p0 = _load_p0()
    checkpoint = tmp_path / ".checkpoint"
    p0.CHECKPOINT_FILE = str(checkpoint)
    real_replace = p0.os.replace
    calls = []
    sleeps = []

    def flaky_replace(source, target):
        calls.append((source, target))
        if len(calls) < 8:
            raise PermissionError("transient Windows file lock")
        real_replace(source, target)

    monkeypatch.setattr(p0.os, "replace", flaky_replace)
    monkeypatch.setattr(p0.time, "sleep", sleeps.append)

    p0.save_checkpoint({"source.jsonl": {"offset": 12}})

    assert len(calls) == 8
    assert sleeps == [0.25] * 7
    assert p0.load_checkpoint()["source.jsonl"]["offset"] == 12
    assert list(tmp_path.glob(".checkpoint.*.tmp")) == []


def test_p0_save_checkpoint_persistent_replace_lock_fails_closed(tmp_path, monkeypatch):
    p0 = _load_p0()
    checkpoint = tmp_path / ".checkpoint"
    p0.CHECKPOINT_FILE = str(checkpoint)
    calls = []
    sleeps = []

    def locked_replace(source, target):
        calls.append((source, target))
        raise PermissionError("persistent Windows file lock")

    monkeypatch.setattr(p0.os, "replace", locked_replace)
    monkeypatch.setattr(p0.time, "sleep", sleeps.append)

    with pytest.raises(PermissionError, match="persistent Windows file lock"):
        p0.save_checkpoint({"source.jsonl": {"offset": 12}})

    assert len(calls) == 20
    assert sleeps == [0.25] * 19
    assert not checkpoint.exists()
    assert list(tmp_path.glob(".checkpoint.*.tmp")) == []


def test_p0_claude_desktop_raw_ingest_defaults_to_continuous_local_capture(monkeypatch):
    p0 = _load_p0()
    calls = []

    fake_connector = SimpleNamespace(
        raw_ingest_dry_run=lambda body, public=True: calls.append(("dry_run", body, public)) or {
            "ok": True,
            "candidate_count": 1,
            "write_performed": False,
            "memory_write_performed": False,
            "platform_write_performed": False,
        },
        ingest_authorized_raw=lambda body, public=True: calls.append(("apply", body, public)) or {
            "ok": True,
            "candidate_count": 1,
            "raw_write": {"records_written": 2},
            "write_performed": True,
            "memory_write_performed": True,
            "platform_write_performed": False,
        },
    )
    monkeypatch.setitem(sys.modules, "claude_desktop_connector", fake_connector)
    monkeypatch.setattr(p0, "config_get", lambda path, default=None: default)

    result = p0.scan_claude_desktop_raw(dry_run=False, limit=3)

    assert result["ok"] is True
    assert result["status"] == "ingested"
    assert result["authorized_by"] == "memcore_default_claude_desktop_continuous_raw_ingest"
    assert result["raw_write"]["records_written"] == 2
    assert result["memory_write_performed"] is True
    assert result["platform_write_performed"] is False
    assert len(calls) == 1
    mode, body, public = calls[0]
    assert mode == "apply"
    assert public is True
    assert body["limit"] == 3
    assert body["apply"] is True
    assert body["confirm_authorized_parser"] is True
    assert body["confirm_user_owns_claude_desktop_data"] is True
    assert body["confirm_write_time_library_raw"] is True
    assert body["confirm_no_claude_platform_write"] is True


def test_p0_claude_desktop_scan_calls_authorized_raw_ingest(monkeypatch):
    p0 = _load_p0()
    calls = []

    fake_connector = SimpleNamespace(
        raw_ingest_dry_run=lambda body, public=True: {
            "ok": True,
            "candidate_count": 2,
            "write_performed": False,
            "memory_write_performed": False,
            "platform_write_performed": False,
        },
        ingest_authorized_raw=lambda body, public=True: calls.append((body, public)) or {
            "ok": True,
            "candidate_count": 2,
            "raw_write": {"records_written": 4},
            "write_performed": True,
            "memory_write_performed": True,
            "platform_write_performed": False,
        },
    )
    monkeypatch.setitem(sys.modules, "claude_desktop_connector", fake_connector)
    monkeypatch.setattr(
        p0,
        "config_get",
        lambda path, default=None: {
            "integrations.claude_desktop.raw_ingest.enabled": True,
            "integrations.claude_desktop.raw_ingest.limit": 9,
        }.get(path, default),
    )

    result = p0.scan_claude_desktop_raw(dry_run=False)

    assert result["ok"] is True
    assert result["status"] == "ingested"
    assert result["authorized_by"] == "memcore_config_integrations.claude_desktop.raw_ingest"
    assert result["raw_write"]["records_written"] == 4
    assert result["memory_write_performed"] is True
    assert result["platform_write_performed"] is False
    assert len(calls) == 1
    body, public = calls[0]
    assert public is True
    assert body["limit"] == 9
    assert body["apply"] is True
    assert body["confirm_authorized_parser"] is True
    assert body["confirm_user_owns_claude_desktop_data"] is True
    assert body["confirm_write_time_library_raw"] is True
    assert body["confirm_no_claude_platform_write"] is True


def test_p0_claude_desktop_source_uses_event_watcher_when_available(monkeypatch):
    p0 = _load_p0()
    called = []
    args = SimpleNamespace(source="claude_desktop")

    monkeypatch.setattr(p0, "watch_file_events", lambda received: called.append(("events", received)) or "events")
    monkeypatch.setattr(p0, "watch_poll", lambda received: called.append(("poll", received)) or "poll")

    assert p0.cmd_watch(args) == "events"
    assert called == [("events", args)]


def test_p0_kiro_source_falls_back_to_poll_when_event_watcher_unavailable(monkeypatch):
    p0 = _load_p0()
    called = []
    args = SimpleNamespace(source="kiro")

    monkeypatch.setattr(p0, "watch_file_events", lambda received: called.append(("events", received)) or None)
    monkeypatch.setattr(p0, "watch_poll", lambda received: called.append(("poll", received)) or "poll")

    assert p0.cmd_watch(args) == "poll"
    assert called == [("events", args), ("poll", args)]


def test_p0_watch_root_candidates_include_existing_codex_claude_code_and_kiro_roots(tmp_path, monkeypatch):
    p0 = _load_p0()
    codex_root = tmp_path / "codex-sessions"
    claude_code_root = tmp_path / "claude-projects"
    claude_desktop_code_root = tmp_path / "claude-code-sessions"
    kiro_root = tmp_path / "kiro-sessions"
    codex_root.mkdir()
    claude_code_root.mkdir()
    claude_desktop_code_root.mkdir()
    kiro_root.mkdir()
    args = SimpleNamespace(source="all")

    monkeypatch.setattr(p0, "OPENCLAW_ROOT", str(tmp_path / "openclaw"))
    monkeypatch.setitem(
        sys.modules,
        "codex_local_connector",
        SimpleNamespace(codex_sessions_root=lambda: codex_root),
    )
    monkeypatch.setitem(
        sys.modules,
        "claude_code_local_connector",
        SimpleNamespace(
            claude_code_projects_root=lambda: claude_code_root,
            claude_desktop_code_sessions_root=lambda: claude_desktop_code_root,
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "kiro_local_connector",
        SimpleNamespace(_kiro_workspace_session_roots=lambda: [kiro_root]),
    )
    monkeypatch.setattr(p0, "claude_desktop_raw_ingest_enabled", lambda: False)

    roots = {(source, path) for source, path in p0._watch_root_candidates(args)}

    assert ("openclaw", tmp_path / "openclaw") in roots
    assert ("codex", codex_root) in roots
    assert ("claude_code_cli", claude_code_root) in roots
    assert ("claude_code_cli", claude_desktop_code_root) in roots
    assert ("kiro", kiro_root) in roots


def test_p0_claude_desktop_relay_metadata_is_not_a_raw_ingest_trigger(tmp_path, monkeypatch):
    p0 = _load_p0()
    relay_db = tmp_path / "relay" / "local-relay.db"
    relay_db.parent.mkdir()
    relay_db.write_bytes(b"relay metadata")
    leveldb = tmp_path / "Claude" / "IndexedDB" / "https_claude.ai_0.indexeddb.leveldb"
    leveldb.mkdir(parents=True)
    leveldb_log = leveldb / "000001.log"
    leveldb_log.write_bytes(b"source bytes")

    connector = SimpleNamespace(
        discover_artifacts=lambda limit=80: [
            {
                "artifact_type": "local_relay_proxy_request_logs_db",
                "source_path": str(relay_db),
            },
            {
                "artifact_type": "claude_desktop_indexeddb_leveldb_dir",
                "source_path": str(leveldb),
            },
        ],
    )
    monkeypatch.setitem(sys.modules, "claude_desktop_connector", connector)
    monkeypatch.setattr(p0, "claude_desktop_raw_ingest_enabled", lambda: True)

    signatures = dict(p0._claude_desktop_store_signatures())
    roots = set(p0._watch_root_candidates(SimpleNamespace(source="claude_desktop")))

    assert str(relay_db) not in signatures
    assert ("claude_desktop", relay_db.parent) not in roots
    assert str(leveldb_log) in signatures
    assert ("claude_desktop", leveldb) in roots


def test_p0_claude_desktop_idle_signature_checks_reuse_discovered_paths(tmp_path, monkeypatch):
    p0 = _load_p0()
    leveldb = tmp_path / "Claude" / "IndexedDB" / "https_claude.ai_0.indexeddb.leveldb"
    leveldb.mkdir(parents=True)
    leveldb_log = leveldb / "000001.log"
    leveldb_log.write_bytes(b"first")
    calls = []

    connector = SimpleNamespace(
        discover_artifacts=lambda limit=80: calls.append(limit) or [
            {
                "artifact_type": "claude_desktop_indexeddb_leveldb_dir",
                "source_path": str(leveldb),
            },
        ],
    )
    monkeypatch.setitem(sys.modules, "claude_desktop_connector", connector)

    first = p0._claude_desktop_store_signatures()
    second = p0._claude_desktop_store_signatures()
    leveldb_log.write_bytes(b"second payload")
    changed = p0._claude_desktop_store_signatures()
    refreshed = p0._claude_desktop_store_signatures(force_refresh=True)

    assert calls == [80, 80]
    assert first == second
    assert changed != second
    assert refreshed == changed


def test_p0_claude_desktop_change_refreshes_discovered_paths_once(tmp_path, monkeypatch):
    p0 = _load_p0()
    store = tmp_path / "Claude" / "Session Storage"
    store.mkdir(parents=True)
    source = store / "000001.log"
    source.write_bytes(b"first")
    discoveries = []
    scans = []

    connector = SimpleNamespace(
        discover_artifacts=lambda limit=80: discoveries.append(limit) or [
            {
                "artifact_type": "claude_desktop_session_storage_dir",
                "source_path": str(store),
            },
        ],
    )
    monkeypatch.setitem(sys.modules, "claude_desktop_connector", connector)
    monkeypatch.setattr(p0, "claude_desktop_raw_ingest_enabled", lambda: True)
    monkeypatch.setattr(
        p0,
        "scan_claude_desktop_raw",
        lambda **kwargs: scans.append(kwargs) or {
            "ok": True,
            "candidate_count": 0,
            "raw_write": {"records_written": 0},
        },
    )
    args = SimpleNamespace(source="claude_desktop", claude_desktop_limit=0)
    signature_cache = {}

    assert p0._run_claude_desktop_sync_once(args, signature_cache=signature_cache) is False
    source.write_bytes(b"second payload")
    assert p0._run_claude_desktop_sync_once(args, signature_cache=signature_cache) is False
    assert p0._run_claude_desktop_sync_once(args, signature_cache=signature_cache) is False

    assert len(scans) == 2
    assert discoveries == [80, 80]


def test_p0_claude_desktop_candidate_only_scan_is_not_source_work(monkeypatch):
    p0 = _load_p0()
    result = {
        "ok": True,
        "candidate_count": 17,
        "raw_write": {"records_written": 0},
    }
    monkeypatch.setattr(p0, "scan_claude_desktop_raw", lambda **kwargs: result)

    args = SimpleNamespace(source="claude_desktop", claude_desktop_limit=0)
    assert p0._run_claude_desktop_sync_once(args, force=True) is False

    result["raw_write"]["records_written"] = 1
    assert p0._run_claude_desktop_sync_once(args, force=True) is True


def test_p0_watch_event_relevance_filters_checkpoint_and_accepts_dest_path():
    p0 = _load_p0()

    assert p0._watch_event_relevant(SimpleNamespace(is_directory=True)) is True
    assert p0._watch_event_relevant(SimpleNamespace(is_directory=False, src_path="/tmp/session.jsonl")) is True
    assert p0._watch_event_relevant(SimpleNamespace(is_directory=False, src_path="/tmp/a.checkpoint.jsonl")) is False
    assert p0._watch_event_relevant(SimpleNamespace(is_directory=False, src_path="", dest_path="/tmp/session.json")) is True


def test_p0_claude_desktop_default_raw_ingest_interval_is_low_resource(monkeypatch):
    p0 = _load_p0()

    monkeypatch.delenv("MEMCORE_CLAUDE_DESKTOP_RAW_INGEST_INTERVAL_MS", raising=False)
    monkeypatch.delenv("MEMCORE_CLAUDE_DESKTOP_RAW_INGEST_INTERVAL_SECONDS", raising=False)
    monkeypatch.setattr(p0, "config_get", lambda path, default=None: default)

    assert p0.claude_desktop_raw_ingest_interval_milliseconds() == 5000
    assert p0.claude_desktop_raw_ingest_interval_seconds() == 5.0


def test_p0_claude_desktop_legacy_seconds_interval_is_still_supported(monkeypatch):
    p0 = _load_p0()

    monkeypatch.delenv("MEMCORE_CLAUDE_DESKTOP_RAW_INGEST_INTERVAL_MS", raising=False)
    monkeypatch.setenv("MEMCORE_CLAUDE_DESKTOP_RAW_INGEST_INTERVAL_SECONDS", "2")
    monkeypatch.setattr(p0, "config_get", lambda path, default=None: default)

    assert p0.claude_desktop_raw_ingest_interval_milliseconds() == 2000


def test_p0_claude_desktop_legacy_config_seconds_does_not_override_low_resource_default(monkeypatch):
    p0 = _load_p0()

    monkeypatch.delenv("MEMCORE_CLAUDE_DESKTOP_RAW_INGEST_INTERVAL_MS", raising=False)
    monkeypatch.delenv("MEMCORE_CLAUDE_DESKTOP_RAW_INGEST_INTERVAL_SECONDS", raising=False)
    monkeypatch.setattr(
        p0,
        "config_get",
        lambda path, default=None: 30 if path == "integrations.claude_desktop.raw_ingest.interval_seconds" else default,
    )

    assert p0.claude_desktop_raw_ingest_interval_milliseconds() == 5000
    assert p0.claude_desktop_raw_ingest_interval_seconds() == 5.0


def test_p0_default_watcher_interval_is_low_resource(monkeypatch):
    p0 = _load_p0()

    monkeypatch.delenv("MEMCORE_WATCHER_INTERVAL_MS", raising=False)
    monkeypatch.delenv("MEMCORE_WATCHER_POLL_INTERVAL_SECONDS", raising=False)
    monkeypatch.setattr(p0, "config_get", lambda path, default=None: default)

    assert p0.watcher_poll_interval_milliseconds() == 5000
    assert p0.watcher_poll_interval_seconds() == 5.0


def test_p0_source_choices_include_kiro_and_hermes():
    p0 = _load_p0()
    choices = None
    for action in p0.argparse.ArgumentParser()._actions:
        if action.dest == "source":
            choices = action.choices
    # The production parser is built in main(); this guards the source list in code
    # without starting the CLI.
    assert choices is None
    text = (SRC / "memcore-cloud.py").read_text(encoding="utf-8")
    assert 'choices=["all", "openclaw", "codex", "claude_code_cli", "claude_desktop", "kiro", "hermes"]' in text
