import importlib.util
import json
import sys
import queue
import time
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _load_memcore_cloud():
    path = SRC / "memcore-cloud.py"
    spec = importlib.util.spec_from_file_location("memcore_cloud_p0_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_memcore_cloud_watch_defaults_to_all_sources(monkeypatch):
    module = _load_memcore_cloud()
    monkeypatch.delenv("MEMCORE_WATCHER_SOURCE_DEFAULT", raising=False)
    monkeypatch.setattr(module, "config_get", lambda path, default=None: default)

    assert module.watcher_source_default() == "all"
    assert module.watcher_resource_profile() == "light"
    assert module.watcher_poll_interval_milliseconds() == 5000


def test_memcore_cloud_canonical_idle_fallback_defaults_to_one_minute(monkeypatch):
    module = _load_memcore_cloud()
    monkeypatch.delenv("MEMCORE_CANONICAL_RECORD_INDEX_INTERVAL_MS", raising=False)
    monkeypatch.delenv("MEMCORE_CANONICAL_RECORD_INDEX_INTERVAL_SECONDS", raising=False)

    assert module.canonical_index_interval_seconds() == 60.0

    monkeypatch.setenv("MEMCORE_CANONICAL_RECORD_INDEX_INTERVAL_SECONDS", "17")
    assert module.canonical_index_interval_seconds() == 17.0

    monkeypatch.setenv("MEMCORE_CANONICAL_RECORD_INDEX_INTERVAL_MS", "invalid")
    assert module.canonical_index_interval_seconds() == 60.0


def test_hermes_backfill_recheck_uses_independent_bounded_interval(monkeypatch):
    module = _load_memcore_cloud()
    monkeypatch.delenv("MEMCORE_HERMES_RAW_BACKFILL_RECHECK_INTERVAL_SECONDS", raising=False)
    monkeypatch.setattr(module, "config_get", lambda path, default=None: default)

    assert module.hermes_raw_backfill_recheck_interval_seconds() == 900

    monkeypatch.setenv("MEMCORE_HERMES_RAW_BACKFILL_RECHECK_INTERVAL_SECONDS", "17")
    assert module.hermes_raw_backfill_recheck_interval_seconds() == 30

    monkeypatch.setenv("MEMCORE_HERMES_RAW_BACKFILL_RECHECK_INTERVAL_SECONDS", "999999")
    assert module.hermes_raw_backfill_recheck_interval_seconds() == 86_400


def test_raw_archive_diagnostics_log_contains_only_bounded_counters(monkeypatch, capsys):
    module = _load_memcore_cloud()
    module._RAW_ARCHIVE_DIAGNOSTIC_LAST = None
    module._RAW_ARCHIVE_DIAGNOSTIC_LAST_EMITTED_AT = 0.0
    monkeypatch.setattr(module.time, "monotonic", lambda: 10.0)
    monkeypatch.setattr(
        module,
        "_raw_archive_diagnostics_snapshot",
        lambda: {
            "contract": "time_library_raw_archive_io_diagnostics.v1",
            "matched_prefix_cache_hit_count": 3,
            "matched_prefix_cache_miss_count": 4,
            "verified_prefix_rehash_hit_count": 5,
            "verified_prefix_rehash_miss_count": 6,
            "verified_prefix_rehash_source_bytes": 7,
            "divergence_witness_hit_count": 8,
            "full_prefix_scan_count": 9,
            "full_prefix_source_bytes": 10,
            "full_prefix_archive_bytes": 11,
            "full_prefix_total_bytes": 21,
            "source_path": "must-not-leak",
            "content": "must-not-leak",
        },
    )

    assert module._emit_raw_archive_diagnostics() is True
    output = capsys.readouterr().out

    assert "matched_hit=3" in output
    assert "matched_miss=4" in output
    assert "verified_rehash_hit=5" in output
    assert "verified_rehash_miss=6" in output
    assert "verified_rehash_source_bytes=7" in output
    assert "divergence_hit=8" in output
    assert "full_scans=9" in output
    assert "full_total_bytes=21" in output
    assert "must-not-leak" not in output


def test_raw_archive_diagnostics_reads_the_connector_module_instance(monkeypatch):
    module = _load_memcore_cloud()
    expected = {
        "contract": "time_library_raw_archive_io_diagnostics.v1",
        "full_prefix_scan_count": 9,
    }
    connector_module = SimpleNamespace(raw_archive_diagnostics_snapshot=lambda: expected)
    monkeypatch.setitem(sys.modules, "src.raw_archive_monotonic", connector_module)
    monkeypatch.delitem(sys.modules, "raw_archive_monotonic", raising=False)

    assert module._raw_archive_diagnostics_snapshot() is expected


def test_watcher_phase_io_measures_only_fixed_bounded_counters(monkeypatch, capsys):
    module = _load_memcore_cloud()
    readings = iter([100, 175])
    monkeypatch.setattr(module, "_process_read_transfer_bytes", lambda: next(readings))
    monkeypatch.setattr(module.time, "monotonic", lambda: 10.0)

    assert module._measure_watcher_phase_io(
        "codex_event_archive",
        lambda value: value + 1,
        4,
    ) == 5
    module._WATCHER_PHASE_IO["source_path"] = {
        "call_count": 99,
        "measured_call_count": 99,
        "read_bytes": 99,
    }

    snapshot = module._watcher_phase_io_snapshot()
    assert snapshot["phases"]["codex_event_archive"] == {
        "call_count": 1,
        "measured_call_count": 1,
        "read_bytes": 75,
    }
    assert "source_path" not in snapshot["phases"]
    assert module._emit_watcher_phase_io_diagnostics(force=True) is True
    output = capsys.readouterr().out
    assert "unit=calls/measured/read_bytes" in output
    assert "codex_event_archive=1/1/75" in output
    assert "source_path" not in output


def test_watcher_phase_io_records_unmeasured_calls_without_guessing_bytes(monkeypatch):
    module = _load_memcore_cloud()
    monkeypatch.setattr(module, "_process_read_transfer_bytes", lambda: None)

    assert module._measure_watcher_phase_io(
        "openclaw_sync",
        lambda: "ok",
    ) == "ok"

    assert module._watcher_phase_io_snapshot()["phases"]["openclaw_sync"] == {
        "call_count": 1,
        "measured_call_count": 0,
        "read_bytes": 0,
    }
    assert module._emit_watcher_phase_io_diagnostics(force=True) is False


def test_watcher_phase_io_unknown_phase_does_not_change_callback_control_flow(monkeypatch):
    module = _load_memcore_cloud()
    monkeypatch.setattr(module, "_process_read_transfer_bytes", lambda: 0)

    assert module._measure_watcher_phase_io("unknown", lambda: "returned") == "returned"

    def fail():
        raise RuntimeError("callback failure")

    try:
        module._measure_watcher_phase_io("unknown", fail)
    except RuntimeError as exc:
        assert str(exc) == "callback failure"
    else:
        raise AssertionError("unknown diagnostic phase must not swallow callback errors")


def test_openclaw_watcher_declares_delivery_capability_in_request(monkeypatch):
    module = _load_memcore_cloud()
    captured = {}
    event = {
        "event_key": "session-1:event-1",
        "event_id": "event-1",
        "event": {"id": "event-1", "type": "message", "message": {"role": "user"}},
        "agent_id": "main",
        "source_session_id": "session-1",
    }

    monkeypatch.setattr(module, "_checkpoint_delivered_ids", lambda _path: set())
    monkeypatch.setattr(module, "_iter_pending_openclaw_user_events", lambda _path: [])
    monkeypatch.setattr(module, "_iter_openclaw_user_events", lambda *_args, **_kwargs: [event])
    monkeypatch.setattr(module, "_mark_checkpoint_delivered", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "_clear_checkpoint_pending", lambda *_args, **_kwargs: None)

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"status":"ok","chain":"F3_zhiyi_direct"}'

    def fake_urlopen(request, timeout):
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr(module.urllib.request, "urlopen", fake_urlopen)

    result = module.deliver_openclaw_native_events("ignored.jsonl", status="append", timeout=9)
    delivery = captured["payload"]["platform_delivery"]

    assert result["delivered"] == 1
    assert captured["timeout"] == 9
    assert delivery == {
        "enabled": True,
        "authorized": True,
        "platform": "openclaw",
        "delivery_runtime_kind": "ws_rpc_forward",
        "session_binding": "native_event",
        "mode": "same_chat",
        "idempotency_key": "memcore-openclaw-event-event-1",
    }


def test_openclaw_pending_retry_skips_unchanged_sessions_without_pending(tmp_path, monkeypatch):
    module = _load_memcore_cloud()
    sources = [tmp_path / "one.jsonl", tmp_path / "two.jsonl"]
    for source in sources:
        source.write_text("{}\n", encoding="utf-8")
    signatures = {str(source): module._file_signature(source) for source in sources}
    signature_cache = {f"openclaw:{path}": signature for path, signature in signatures.items()}
    load_calls = []
    delivery_calls = []

    monkeypatch.setattr(
        module,
        "_iter_openclaw_session_files",
        lambda: [("agent", source.stem, str(source)) for source in sources],
    )
    monkeypatch.setattr(module, "load_checkpoint", lambda: load_calls.append(True) or {})
    monkeypatch.setattr(
        module,
        "deliver_openclaw_native_events",
        lambda *args, **kwargs: delivery_calls.append((args, kwargs)) or {},
    )

    result = module._run_openclaw_sync_once(
        SimpleNamespace(source="all"),
        signature_cache=signature_cache,
        retry_pending=True,
    )

    assert result is False
    assert len(load_calls) == 1
    assert delivery_calls == []


def test_openclaw_pending_retry_calls_only_session_with_pending_event(tmp_path, monkeypatch):
    module = _load_memcore_cloud()
    sources = [tmp_path / "one.jsonl", tmp_path / "two.jsonl"]
    for source in sources:
        source.write_text("{}\n", encoding="utf-8")
    signatures = {str(source): module._file_signature(source) for source in sources}
    signature_cache = {f"openclaw:{path}": signature for path, signature in signatures.items()}
    pending_path = str(sources[1])
    checkpoint = {
        pending_path: {
            "offset": 3,
            module.OPENCLAW_EVENT_PENDING_KEY: [{"event_id": "pending-1"}],
        }
    }
    delivery_calls = []

    monkeypatch.setattr(
        module,
        "_iter_openclaw_session_files",
        lambda: [("agent", source.stem, str(source)) for source in sources],
    )
    monkeypatch.setattr(module, "load_checkpoint", lambda: checkpoint)
    monkeypatch.setattr(
        module,
        "deliver_openclaw_native_events",
        lambda path, prior_offset, status: delivery_calls.append((path, prior_offset, status)) or {
            "attempted": 0,
            "delivered": 0,
            "errors": [],
        },
    )

    result = module._run_openclaw_sync_once(
        SimpleNamespace(source="all"),
        signature_cache=signature_cache,
        retry_pending=True,
    )

    assert result is False
    assert delivery_calls == [(pending_path, 3, "pending_retry")]


def test_openclaw_changed_source_still_archives_and_delivers(tmp_path, monkeypatch):
    module = _load_memcore_cloud()
    source = tmp_path / "changed.jsonl"
    source.write_text("{}\n", encoding="utf-8")
    current_signature = module._file_signature(source)
    signature_cache = {f"openclaw:{source}": (0, 0, 0)}
    archive_calls = []
    delivery_calls = []
    extract_calls = []

    monkeypatch.setattr(
        module,
        "_iter_openclaw_session_files",
        lambda: [("agent", "changed", str(source))],
    )
    monkeypatch.setattr(
        module,
        "load_checkpoint",
        lambda: {str(source): {"offset": 2}},
    )
    monkeypatch.setattr(
        module,
        "archive_session",
        lambda path: archive_calls.append(path) or ("raw.jsonl", "appended(1 line)"),
    )
    monkeypatch.setattr(
        module,
        "deliver_openclaw_native_events",
        lambda path, prior_offset, status: delivery_calls.append((path, prior_offset, status)) or {
            "attempted": 1,
            "delivered": 1,
            "errors": [],
            "responses": [{"status": "ok"}],
        },
    )
    monkeypatch.setattr(
        module,
        "incremental_extract_session",
        lambda path: extract_calls.append(path) or (0, 0, 0),
    )

    result = module._run_openclaw_sync_once(
        SimpleNamespace(source="all"),
        signature_cache=signature_cache,
        retry_pending=True,
    )

    assert current_signature != (0, 0, 0)
    assert result is True
    assert archive_calls == [str(source)]
    assert delivery_calls == [(str(source), 2, "appended(1 line)")]
    assert extract_calls == ["raw.jsonl"]


def test_memcore_cloud_watch_source_default_can_be_overridden(monkeypatch):
    module = _load_memcore_cloud()
    monkeypatch.setenv("MEMCORE_WATCHER_SOURCE_DEFAULT", "all")
    monkeypatch.setenv("MEMCORE_WATCHER_RESOURCE_PROFILE", "heavy")
    monkeypatch.setenv("MEMCORE_WATCHER_INTERVAL_MS", "250")
    monkeypatch.setattr(module, "config_get", lambda path, default=None: default)

    assert module.watcher_source_default() == "all"
    assert module.watcher_resource_profile() == "heavy"
    assert module.watcher_poll_interval_milliseconds() == 250


def test_codex_watcher_startup_covers_status_window_then_returns_to_hot_limit(monkeypatch):
    module = _load_memcore_cloud()
    calls = []
    signatures = iter([("startup",), ("steady",)])

    connector = SimpleNamespace(
        catch_up_latest_sessions=lambda *, limit: calls.append(("catch_up", limit)) or {
            "changed": 0,
            "items": [],
            "raw_sync": {"missing_or_stale_count": 0},
        },
        status_scan_limit=lambda: 20,
        watch_scan_limit=lambda: 8,
    )
    monkeypatch.setitem(sys.modules, "codex_local_connector", connector)
    monkeypatch.setattr(module, "_codex_session_signatures", lambda: next(signatures))

    cache = {}
    args = SimpleNamespace(source="codex")
    assert module._run_codex_sync_once(args, signature_cache=cache, force=False) is False
    assert module._run_codex_sync_once(args, signature_cache=cache, force=False) is False

    assert calls == [
        ("catch_up", 20),
        ("catch_up", 8),
    ]


def test_codex_watcher_routes_generation_start_to_incremental_extract(monkeypatch, tmp_path):
    module = _load_memcore_cloud()
    raw = tmp_path / "session.seg1.jsonl"
    raw.write_text('{}\n', encoding="utf-8")
    connector = SimpleNamespace(
        catch_up_latest_sessions=lambda *, limit: {
            "changed": 1,
            "items": [{
                "status": "generation_started(generation=1,base=7,bytes=3)",
                "dest": str(raw),
                "canonical_window_id": "project-1",
                "session_id": "session-1",
            }],
            "raw_sync": {"missing_or_stale_count": 0},
        },
        status_scan_limit=lambda: 20,
        watch_scan_limit=lambda: 8,
    )
    monkeypatch.setitem(sys.modules, "codex_local_connector", connector)
    extracted = []
    monkeypatch.setattr(
        module,
        "incremental_extract_session",
        lambda path: extracted.append(path) or (0, 0, 0),
    )

    assert module._run_codex_sync_once(
        SimpleNamespace(source="codex"),
        signature_cache=None,
        force=True,
    ) is True
    assert extracted == [str(raw)]


def test_claude_code_watcher_routes_generation_start_to_incremental_extract(monkeypatch, tmp_path):
    module = _load_memcore_cloud()
    raw = tmp_path / "session.seg1.jsonl"
    raw.write_text('{}\n', encoding="utf-8")
    connector = SimpleNamespace(
        scan_sessions=lambda *, dry_run: {
            "changed": 1,
            "items": [{
                "status": "generation_started(generation=1,base=7,bytes=3)",
                "dest": str(raw),
                "canonical_window_id": "project-1",
                "session_id": "session-1",
            }],
        },
    )
    monkeypatch.setitem(sys.modules, "claude_code_local_connector", connector)
    extracted = []
    monkeypatch.setattr(
        module,
        "incremental_extract_session",
        lambda path: extracted.append(path) or (0, 0, 0),
    )

    assert module._run_claude_code_sync_once(
        SimpleNamespace(source="claude_code_cli"),
        signature_cache=None,
        force=True,
    ) is True
    assert extracted == [str(raw)]


def test_memcore_cloud_watch_supports_hermes_state_db_backfill(tmp_path, monkeypatch):
    module = _load_memcore_cloud()
    state_db = tmp_path / "hermes" / "state.db"
    state_db.parent.mkdir(parents=True)
    state_db.write_bytes(b"sqlite fixture")

    monkeypatch.setattr(module, "config_get", lambda path, default=None: default)
    monkeypatch.setattr(module, "hermes_raw_backfill_enabled", lambda: True)
    monkeypatch.setattr(module, "hermes_raw_backfill_limit", lambda: 7)

    hermes_paths = SimpleNamespace(hermes_state_db_path=lambda: state_db)
    monkeypatch.setitem(sys.modules, "hermes_paths", hermes_paths)

    calls = []

    def fake_backfill(*, limit, source_systems):
        calls.append((limit, source_systems))
        return {
            "ok": True,
            "results": [
                {
                    "source_system": "hermes",
                    "changed": 1,
                    "raw_sync": {
                        "status": "hermes_state_db_messages_exported_to_raw",
                        "items_checked": 1,
                    },
                }
            ],
        }

    raw_record_guardian = SimpleNamespace(run_raw_backfill=fake_backfill)
    monkeypatch.setitem(sys.modules, "raw_record_guardian", raw_record_guardian)

    args = SimpleNamespace(source="hermes")

    roots = module._watch_root_candidates(args)
    assert ("hermes", state_db.parent) in roots

    did_work = module._run_hermes_sync_once(args, signature_cache={}, force=True)

    assert did_work is True
    assert calls == [(7, ["hermes"])]


def test_hermes_shm_churn_does_not_retrigger_backfill_but_wal_change_does(tmp_path, monkeypatch):
    module = _load_memcore_cloud()
    state_db = tmp_path / "hermes" / "state.db"
    state_db.parent.mkdir(parents=True)
    state_db.write_bytes(b"db")
    wal_path = Path(str(state_db) + "-wal")
    shm_path = Path(str(state_db) + "-shm")
    wal_path.write_bytes(b"wal")
    shm_path.write_bytes(b"shm")

    monkeypatch.setattr(module, "hermes_raw_backfill_enabled", lambda: True)
    monkeypatch.setattr(module, "hermes_raw_backfill_limit", lambda: 7)
    monkeypatch.setitem(
        sys.modules,
        "hermes_paths",
        SimpleNamespace(hermes_state_db_path=lambda: state_db),
    )

    calls = []

    def fake_backfill(**kwargs):
        calls.append(kwargs)
        return {
            "ok": True,
            "results": [{
                "source_system": "hermes",
                "changed": 1,
                "raw_sync": {"status": "hermes_state_db_messages_exported_to_raw"},
            }],
        }

    monkeypatch.setitem(
        sys.modules,
        "raw_record_guardian",
        SimpleNamespace(run_raw_backfill=fake_backfill),
    )
    args = SimpleNamespace(source="hermes")
    signature_cache = {}

    assert module._run_hermes_sync_once(args, signature_cache=signature_cache) is True
    shm_path.write_bytes(b"shm changed by a reader")
    assert module._run_hermes_sync_once(args, signature_cache=signature_cache) is False
    wal_path.write_bytes(b"wal durable change")
    assert module._run_hermes_sync_once(args, signature_cache=signature_cache) is True

    assert calls == [
        {"limit": 7, "source_systems": ["hermes"]},
        {"limit": 7, "source_systems": ["hermes"]},
    ]
    signature_paths = {Path(path).name for path, _signature in module._hermes_state_db_signatures()}
    assert signature_paths == {"state.db", "state.db-wal"}


def test_memcore_cloud_watch_skips_hermes_when_state_db_signature_unchanged_without_backfill_recommendation(tmp_path, monkeypatch):
    module = _load_memcore_cloud()
    state_db = tmp_path / "hermes" / "state.db"
    state_db.parent.mkdir(parents=True)
    state_db.write_bytes(b"sqlite fixture")

    monkeypatch.setattr(module, "hermes_raw_backfill_enabled", lambda: True)
    hermes_paths = SimpleNamespace(hermes_state_db_path=lambda: state_db)
    monkeypatch.setitem(sys.modules, "hermes_paths", hermes_paths)

    calls = []

    def fake_backfill(**kwargs):
        calls.append(kwargs)
        return {
            "ok": True,
            "results": [
                {
                    "source_system": "hermes",
                    "changed": 1,
                    "raw_sync": {"status": "hermes_state_db_messages_exported_to_raw"},
                }
            ],
        }

    recommendation_calls = []

    def fake_recommendation(**kwargs):
        recommendation_calls.append(kwargs)
        return {
            "ok": True,
            "source_system": "hermes",
            "recommended_count": 0,
            "write_performed": False,
            "platform_write_performed": False,
            "memory_write_performed": False,
        }

    raw_record_guardian = SimpleNamespace(
        run_raw_backfill=fake_backfill,
        hermes_backfill_recommendation=fake_recommendation,
    )
    monkeypatch.setitem(sys.modules, "raw_record_guardian", raw_record_guardian)

    args = SimpleNamespace(source="hermes")
    signature_cache = {}

    assert module._run_hermes_sync_once(args, signature_cache=signature_cache, force=False) is True
    assert module._run_hermes_sync_once(
        args,
        signature_cache=signature_cache,
        force=False,
        retry_pending=True,
    ) is False
    assert len(calls) == 1
    assert recommendation_calls == [{"limit": 80}]


def test_memcore_cloud_watch_backfills_hermes_when_signature_unchanged_but_guardian_recommends(tmp_path, monkeypatch):
    module = _load_memcore_cloud()
    state_db = tmp_path / "hermes" / "state.db"
    state_db.parent.mkdir(parents=True)
    state_db.write_bytes(b"sqlite fixture")

    monkeypatch.setattr(module, "hermes_raw_backfill_enabled", lambda: True)
    monkeypatch.setattr(module, "hermes_raw_backfill_limit", lambda: 80)
    hermes_paths = SimpleNamespace(hermes_state_db_path=lambda: state_db)
    monkeypatch.setitem(sys.modules, "hermes_paths", hermes_paths)

    calls = []

    def fake_backfill(**kwargs):
        calls.append(kwargs)
        return {
            "ok": True,
            "results": [
                {
                    "source_system": "hermes",
                    "changed": 7,
                    "raw_sync": {
                        "status": "hermes_state_db_messages_exported_to_raw",
                        "items_checked": 27,
                    },
                }
            ],
        }

    recommendation_calls = []

    def fake_recommendation(**kwargs):
        recommendation_calls.append(kwargs)
        return {
            "ok": True,
            "source_system": "hermes",
            "recommended_count": 7,
            "session_ids": ["20260525_122249_732cba"],
            "write_performed": False,
            "platform_write_performed": False,
            "memory_write_performed": False,
        }

    raw_record_guardian = SimpleNamespace(
        run_raw_backfill=fake_backfill,
        hermes_backfill_recommendation=fake_recommendation,
    )
    monkeypatch.setitem(sys.modules, "raw_record_guardian", raw_record_guardian)

    args = SimpleNamespace(source="hermes")
    signature_cache = {}

    assert module._run_hermes_sync_once(args, signature_cache=signature_cache, force=False) is True
    assert module._run_hermes_sync_once(
        args,
        signature_cache=signature_cache,
        force=False,
        retry_pending=True,
    ) is True
    assert calls == [
        {"limit": 80, "source_systems": ["hermes"]},
        {"limit": 80, "source_systems": ["hermes"]},
    ]
    assert recommendation_calls == [{"limit": 80}]


def test_global_retry_tick_does_not_rescan_hermes_before_its_own_interval(monkeypatch):
    module = _load_memcore_cloud()
    clock = {"now": 100.0}
    openclaw_retries = []
    hermes_retries = []

    monkeypatch.setattr(module.time, "time", lambda: clock["now"])
    monkeypatch.setattr(module, "hermes_raw_backfill_recheck_interval_seconds", lambda: 900)
    monkeypatch.setattr(
        module,
        "_run_openclaw_sync_once",
        lambda *args, **kwargs: openclaw_retries.append(kwargs["retry_pending"]) or False,
    )
    monkeypatch.setattr(module, "_run_codex_sync_once", lambda *args, **kwargs: False)
    monkeypatch.setattr(module, "_run_claude_code_sync_once", lambda *args, **kwargs: False)
    monkeypatch.setattr(module, "_run_claude_desktop_sync_once", lambda *args, **kwargs: False)
    monkeypatch.setattr(module, "_run_kiro_sync_once", lambda *args, **kwargs: False)
    monkeypatch.setattr(
        module,
        "_run_hermes_sync_once",
        lambda *args, **kwargs: hermes_retries.append(kwargs["retry_pending"]) or False,
    )
    monkeypatch.setattr(module, "claude_desktop_raw_ingest_interval_seconds", lambda: 60.0)
    monkeypatch.setattr(module, "canonical_index_enabled", lambda: False)
    monkeypatch.setattr(module, "_emit_raw_archive_diagnostics", lambda: False)
    monkeypatch.setattr(module, "_emit_watcher_phase_io_diagnostics", lambda: False)

    state = {}
    args = SimpleNamespace(source="all")
    module._run_sync_once(args, signature_cache={}, state=state, retry_pending=True)
    clock["now"] = 105.0
    module._run_sync_once(args, signature_cache={}, state=state, retry_pending=True)
    clock["now"] = 1000.0
    module._run_sync_once(args, signature_cache={}, state=state, retry_pending=True)

    assert openclaw_retries == [True, True, True]
    assert hermes_retries == [True, False, True]
    assert state["last_hermes_backfill_recheck"] == 1000.0


def test_memcore_cloud_watch_refreshes_canonical_index_after_source_work(monkeypatch):
    module = _load_memcore_cloud()
    monkeypatch.setattr(module, "_run_openclaw_sync_once", lambda *args, **kwargs: False)
    monkeypatch.setattr(module, "_run_codex_sync_once", lambda *args, **kwargs: True)
    monkeypatch.setattr(module, "_run_claude_code_sync_once", lambda *args, **kwargs: False)
    monkeypatch.setattr(module, "_run_claude_desktop_sync_once", lambda *args, **kwargs: False)
    monkeypatch.setattr(module, "_run_kiro_sync_once", lambda *args, **kwargs: False)
    monkeypatch.setattr(module, "_run_hermes_sync_once", lambda *args, **kwargs: False)
    monkeypatch.setattr(module, "claude_desktop_raw_ingest_interval_seconds", lambda: 60.0)
    monkeypatch.setattr(module, "canonical_index_enabled", lambda: True)
    monkeypatch.setattr(module, "canonical_index_limit", lambda: 13)
    monkeypatch.setattr(module, "canonical_index_interval_seconds", lambda: 30.0)

    refresh_calls = []

    def fake_refresh(**kwargs):
        refresh_calls.append(kwargs)
        return {"ok": True, "index_update": {"records_upserted": 1}}

    monkeypatch.setattr(module, "_refresh_canonical_record_index", fake_refresh)

    state = {"last_canonical_record_index": 9999999999.0}
    did_work = module._run_sync_once(
        SimpleNamespace(source="all"),
        signature_cache={},
        state=state,
        force=False,
    )

    assert did_work is True
    assert refresh_calls == [{"limit": 13, "scan_mode": "fast"}]
    assert state["last_canonical_record_index"] != 9999999999.0


def test_memcore_cloud_watch_bounds_idle_canonical_refreshes(monkeypatch):
    module = _load_memcore_cloud()
    monkeypatch.setattr(module, "_run_openclaw_sync_once", lambda *args, **kwargs: False)
    monkeypatch.setattr(module, "_run_codex_sync_once", lambda *args, **kwargs: False)
    monkeypatch.setattr(module, "_run_claude_code_sync_once", lambda *args, **kwargs: False)
    monkeypatch.setattr(module, "_run_claude_desktop_sync_once", lambda *args, **kwargs: False)
    monkeypatch.setattr(module, "_run_kiro_sync_once", lambda *args, **kwargs: False)
    monkeypatch.setattr(module, "_run_hermes_sync_once", lambda *args, **kwargs: False)
    monkeypatch.setattr(module, "claude_desktop_raw_ingest_interval_seconds", lambda: 60.0)
    monkeypatch.setattr(module, "canonical_index_enabled", lambda: True)
    monkeypatch.setattr(module, "canonical_index_limit", lambda: 13)
    monkeypatch.setattr(module, "canonical_index_interval_seconds", lambda: 60.0)

    clock = {"now": 100.0}
    monkeypatch.setattr(module.time, "time", lambda: clock["now"])
    refresh_calls = []
    monkeypatch.setattr(
        module,
        "_refresh_canonical_record_index",
        lambda **kwargs: refresh_calls.append(kwargs) or {"ok": True},
    )

    state = {}
    args = SimpleNamespace(source="all")
    assert module._run_sync_once(args, signature_cache={}, state=state) is False
    clock["now"] = 105.0
    assert module._run_sync_once(args, signature_cache={}, state=state) is False
    clock["now"] = 159.0
    assert module._run_sync_once(args, signature_cache={}, state=state) is False
    clock["now"] = 160.0
    assert module._run_sync_once(args, signature_cache={}, state=state) is False

    assert refresh_calls == [
        {"limit": 13, "scan_mode": "fast"},
        {"limit": 13, "scan_mode": "fast"},
    ]
    assert state["last_canonical_record_index"] == 160.0


def test_memcore_cloud_watch_skips_canonical_index_when_disabled(monkeypatch):
    module = _load_memcore_cloud()
    monkeypatch.setattr(module, "_run_openclaw_sync_once", lambda *args, **kwargs: False)
    monkeypatch.setattr(module, "_run_codex_sync_once", lambda *args, **kwargs: True)
    monkeypatch.setattr(module, "_run_claude_code_sync_once", lambda *args, **kwargs: False)
    monkeypatch.setattr(module, "_run_claude_desktop_sync_once", lambda *args, **kwargs: False)
    monkeypatch.setattr(module, "_run_kiro_sync_once", lambda *args, **kwargs: False)
    monkeypatch.setattr(module, "_run_hermes_sync_once", lambda *args, **kwargs: False)
    monkeypatch.setattr(module, "claude_desktop_raw_ingest_interval_seconds", lambda: 60.0)
    monkeypatch.setattr(module, "canonical_index_enabled", lambda: False)

    refresh_calls = []
    monkeypatch.setattr(module, "_refresh_canonical_record_index", lambda **kwargs: refresh_calls.append(kwargs))

    did_work = module._run_sync_once(
        SimpleNamespace(source="all"),
        signature_cache={},
        state={},
        force=False,
    )

    assert did_work is True
    assert refresh_calls == []


def test_memcore_cloud_scan_refreshes_canonical_index_only_after_non_dry_run(monkeypatch):
    module = _load_memcore_cloud()
    monkeypatch.setattr(module, "OPENCLAW_ROOT", "/path/that/does/not/exist")
    monkeypatch.setattr(module.os.path, "exists", lambda path: False)
    monkeypatch.setattr(module.os, "listdir", lambda path: [])
    monkeypatch.setattr(module, "_run_hermes_sync_once", lambda *args, **kwargs: False)
    monkeypatch.setattr(module, "canonical_index_limit", lambda: 17)

    refresh_calls = []

    def fake_refresh(**kwargs):
        refresh_calls.append(kwargs)
        return {"ok": True}

    monkeypatch.setattr(module, "_refresh_canonical_record_index", fake_refresh)

    module.cmd_scan(SimpleNamespace(source="none", dry_run=True))
    module.cmd_scan(SimpleNamespace(source="none", dry_run=False))

    assert refresh_calls == [{"limit": 17, "scan_mode": "fast"}]


def test_memcore_cloud_scan_counts_generation_start_as_codex_work(monkeypatch, tmp_path, capsys):
    module = _load_memcore_cloud()
    raw = tmp_path / "session.seg1.jsonl"
    raw.write_text('{}\n', encoding="utf-8")
    connector = SimpleNamespace(
        scan_sessions=lambda *, dry_run: {
            "changed": 1,
            "items": [{
                "status": "generation_started(generation=1,base=7,bytes=3)",
                "dest": str(raw),
                "canonical_window_id": "project-1",
                "session_id": "session-1",
            }],
        },
    )
    monkeypatch.setitem(sys.modules, "codex_local_connector", connector)
    extracted = []
    monkeypatch.setattr(
        module,
        "incremental_extract_session",
        lambda path: extracted.append(path) or (0, 0, 0),
    )
    monkeypatch.setattr(module, "canonical_index_limit", lambda: 17)
    monkeypatch.setattr(module, "_refresh_canonical_record_index", lambda **_kwargs: {"ok": True})

    module.cmd_scan(SimpleNamespace(source="codex", dry_run=False))

    assert extracted == [str(raw)]
    assert "archived/updated 1 sessions" in capsys.readouterr().out


def test_memcore_cloud_scan_counts_generation_start_as_claude_code_work(monkeypatch, tmp_path, capsys):
    module = _load_memcore_cloud()
    raw = tmp_path / "session.seg1.jsonl"
    raw.write_text('{}\n', encoding="utf-8")
    connector = SimpleNamespace(
        scan_sessions=lambda *, dry_run: {
            "changed": 1,
            "items": [{
                "status": "generation_started(generation=1,base=7,bytes=3)",
                "dest": str(raw),
                "canonical_window_id": "project-1",
                "session_id": "session-1",
            }],
        },
    )
    monkeypatch.setitem(sys.modules, "claude_code_local_connector", connector)
    extracted = []
    monkeypatch.setattr(
        module,
        "incremental_extract_session",
        lambda path: extracted.append(path) or (0, 0, 0),
    )
    monkeypatch.setattr(module, "canonical_index_limit", lambda: 17)
    monkeypatch.setattr(module, "_refresh_canonical_record_index", lambda **_kwargs: {"ok": True})

    module.cmd_scan(SimpleNamespace(source="claude_code_cli", dry_run=False))

    assert extracted == [str(raw)]
    assert "archived/updated 1 sessions" in capsys.readouterr().out


def test_memcore_cloud_canonical_refresh_writes_from_full_guardian_records(monkeypatch):
    module = _load_memcore_cloud()
    monkeypatch.setattr(module, "canonical_index_enabled", lambda: True)
    monkeypatch.setattr(module, "canonical_index_limit", lambda: 19)
    monkeypatch.setattr(module, "_canonical_index_refresh_due", lambda **kwargs: {"refresh_needed": True})

    guardian_calls = []

    def fake_guardian(**kwargs):
        guardian_calls.append(kwargs)
        return {
            "ok": True,
            "index_update": {
                "records_upserted": 1,
                "canonical_messages_upserted": 2,
                "canonical_chunks_upserted": 3,
            },
        }

    monkeypatch.setitem(sys.modules, "raw_record_guardian", SimpleNamespace(build_guardian_status=fake_guardian))

    result = module._refresh_canonical_record_index(quiet=True, source_systems=["codex"])

    assert result["ok"] is True
    assert guardian_calls == [
        {
            "limit": 19,
            "include_gaps": False,
            "scan_mode": "fast",
            "write_index": True,
            "compact": False,
            "public": True,
            "source_systems": ["codex"],
        }
    ]


def test_memcore_cloud_targeted_canonical_refresh_skips_full_due_scan(monkeypatch):
    module = _load_memcore_cloud()
    monkeypatch.setattr(module, "canonical_index_enabled", lambda: True)

    def full_due_scan_must_not_run(**_kwargs):
        raise AssertionError("targeted event refresh performed a full due scan")

    monkeypatch.setattr(module, "_canonical_index_refresh_due", full_due_scan_must_not_run)
    guardian_calls = []

    def fake_guardian(**kwargs):
        guardian_calls.append(kwargs)
        return {"ok": True, "index_update": {"records_upserted": 1}}

    monkeypatch.setitem(sys.modules, "raw_record_guardian", SimpleNamespace(build_guardian_status=fake_guardian))
    artifact = {"source_path": "/tmp/active.jsonl", "session_id": "active"}

    result = module._refresh_canonical_record_index(
        limit=7,
        quiet=True,
        source_systems=["codex"],
        connector_artifacts={"codex": [artifact]},
    )

    assert result["ok"] is True
    assert guardian_calls == [{
        "limit": 7,
        "include_gaps": False,
        "scan_mode": "fast",
        "write_index": True,
        "compact": False,
        "public": True,
        "source_systems": ["codex"],
        "connector_artifacts": {"codex": [artifact]},
    }]


def test_memcore_cloud_canonical_refresh_skips_when_sources_unchanged(monkeypatch):
    module = _load_memcore_cloud()
    monkeypatch.setattr(module, "canonical_index_enabled", lambda: True)
    monkeypatch.setattr(
        module,
        "_canonical_index_refresh_due",
        lambda **kwargs: {
            "ok": True,
            "contract": "canonical_record_index.v2",
            "refresh_needed": False,
            "reason": "tracked_sources_unchanged",
            "tracked_records": 95,
        },
    )

    def fake_guardian(**kwargs):
        raise AssertionError("guardian must not run when canonical sources are unchanged")

    monkeypatch.setitem(sys.modules, "raw_record_guardian", SimpleNamespace(build_guardian_status=fake_guardian))

    result = module._refresh_canonical_record_index(quiet=True)

    assert result["ok"] is True
    assert result["refresh_skipped"] is True
    assert result["write_performed"] is False
    assert result["index_update"]["records_upserted"] == 0
    assert result["index_update"]["records_skipped_unchanged"] == 95
    assert result["refresh_due"]["reason"] == "tracked_sources_unchanged"


def test_memcore_cloud_periodic_refresh_targets_due_record_ids(monkeypatch):
    module = _load_memcore_cloud()
    monkeypatch.setattr(module, "canonical_index_enabled", lambda: True)
    monkeypatch.setattr(
        module,
        "_canonical_index_refresh_due",
        lambda **kwargs: {
            "ok": True,
            "contract": "canonical_record_index.v2",
            "refresh_needed": True,
            "reason": "tracked_source_stat_changed",
            "tracked_records": 1647,
            "changed_records": 2,
            "_internal_changed_record_ids": ["record-a", "record-b"],
        },
    )
    refresh_calls = []

    def fake_targeted_refresh(record_ids):
        refresh_calls.append(record_ids)
        return {
            "ok": True,
            "records_upserted": 2,
            "canonical_messages_upserted": 3,
            "canonical_chunks_upserted": 4,
            "write_performed": True,
        }

    monkeypatch.setitem(
        sys.modules,
        "canonical_index_delta_refresh",
        SimpleNamespace(refresh_changed_records_index=fake_targeted_refresh),
    )

    def full_guardian_must_not_run(**_kwargs):
        raise AssertionError("periodic stat delta must not rediscover the recent-session catalog")

    monkeypatch.setitem(
        sys.modules,
        "raw_record_guardian",
        SimpleNamespace(build_guardian_status=full_guardian_must_not_run),
    )

    result = module._refresh_canonical_record_index(quiet=True)

    assert result["ok"] is True
    assert refresh_calls == [["record-a", "record-b"]]
    assert result["index_update"]["records_upserted"] == 2
    assert "_internal_changed_record_ids" not in result["refresh_due"]


def test_memcore_cloud_canonical_refresh_expands_limit_to_cover_scoped_changed_records(monkeypatch):
    module = _load_memcore_cloud()
    monkeypatch.setattr(module, "canonical_index_enabled", lambda: True)
    monkeypatch.setattr(module, "canonical_index_limit", lambda: 20)
    monkeypatch.setattr(
        module,
        "_canonical_index_refresh_due",
        lambda **kwargs: {
            "ok": True,
            "contract": "canonical_record_index.v2",
            "refresh_needed": True,
            "tracked_records": 62,
            "changed_records": 26,
        },
    )

    guardian_calls = []

    def fake_guardian(**kwargs):
        guardian_calls.append(kwargs)
        return {"ok": True, "index_update": {"records_upserted": 26}}

    monkeypatch.setitem(sys.modules, "raw_record_guardian", SimpleNamespace(build_guardian_status=fake_guardian))

    result = module._refresh_canonical_record_index(quiet=True, source_systems=["codex"])

    assert result["ok"] is True
    assert guardian_calls[0]["limit"] == 62
    assert guardian_calls[0]["source_systems"] == ["codex"]


def test_memcore_cloud_watch_refreshes_canonical_index_scoped_to_active_source(monkeypatch):
    module = _load_memcore_cloud()
    monkeypatch.setattr(module, "_run_openclaw_sync_once", lambda *args, **kwargs: False)
    monkeypatch.setattr(module, "_run_codex_sync_once", lambda *args, **kwargs: True)
    monkeypatch.setattr(module, "_run_claude_code_sync_once", lambda *args, **kwargs: False)
    monkeypatch.setattr(module, "_run_claude_desktop_sync_once", lambda *args, **kwargs: False)
    monkeypatch.setattr(module, "_run_kiro_sync_once", lambda *args, **kwargs: False)
    monkeypatch.setattr(module, "_run_hermes_sync_once", lambda *args, **kwargs: False)
    monkeypatch.setattr(module, "claude_desktop_raw_ingest_interval_seconds", lambda: 60.0)
    monkeypatch.setattr(module, "canonical_index_enabled", lambda: True)
    monkeypatch.setattr(module, "canonical_index_limit", lambda: 13)
    monkeypatch.setattr(module, "canonical_index_interval_seconds", lambda: 30.0)

    refresh_calls = []

    def fake_refresh(**kwargs):
        refresh_calls.append(kwargs)
        return {"ok": True, "index_update": {"records_upserted": 1}}

    monkeypatch.setattr(module, "_refresh_canonical_record_index", fake_refresh)

    state = {"last_canonical_record_index": 9999999999.0}
    did_work = module._run_sync_once(
        SimpleNamespace(source="codex"),
        signature_cache={},
        state=state,
        force=False,
    )

    assert did_work is True
    assert refresh_calls == [{"limit": 13, "scan_mode": "fast", "source_systems": ["codex"]}]


def test_memcore_cloud_event_watch_runs_signature_sync_on_fallback_tick(monkeypatch, tmp_path):
    module = _load_memcore_cloud()

    class FakeQueue:
        def get(self, timeout=None):
            raise queue.Empty

        def get_nowait(self):
            raise queue.Empty

        def put_nowait(self, item):
            pass

    class FakeObserver:
        def __init__(self):
            self.started = False

        def schedule(self, handler, root, recursive=True):
            assert recursive is True

        def start(self):
            self.started = True

        def stop(self):
            pass

        def join(self):
            pass

    class FakeHandler:
        pass

    roots = [("codex", tmp_path)]
    monkeypatch.setattr(module, "_watch_root_candidates", lambda args: roots)
    monkeypatch.setattr(module.queue, "Queue", lambda: FakeQueue())
    monkeypatch.setattr(module, "watcher_poll_interval_seconds", lambda: 0.01)
    monkeypatch.setattr(module, "watcher_poll_interval_milliseconds", lambda: 10)
    monotonic_values = iter([10.0, 10.02])
    monkeypatch.setattr(module.time, "monotonic", lambda: next(monotonic_values))

    calls = []

    def fake_run_sync_once(*args, **kwargs):
        calls.append(kwargs)
        if len(calls) >= 2:
            raise KeyboardInterrupt
        return False

    monkeypatch.setattr(module, "_run_sync_once", fake_run_sync_once)
    monkeypatch.setitem(
        sys.modules,
        "watchdog.events",
        SimpleNamespace(FileSystemEventHandler=FakeHandler),
    )
    monkeypatch.setitem(
        sys.modules,
        "watchdog.observers",
        SimpleNamespace(Observer=FakeObserver),
    )

    try:
        module.watch_file_events(SimpleNamespace(source="all"))
    except KeyboardInterrupt:
        pass

    assert len(calls) == 2
    assert calls[0]["retry_pending"] is True
    assert calls[1]["force"] is False
    assert calls[1]["retry_pending"] is False


def test_codex_event_advances_fallback_signature_only_for_fully_processed_changes(monkeypatch, tmp_path):
    module = _load_memcore_cloud()
    source = tmp_path / "active.jsonl"
    source.write_text("{}\n", encoding="utf-8")
    old_signature = (1, 1, 1)
    current_signature = module._file_signature(source)
    cache = {"codex": ((str(source), old_signature),)}
    monkeypatch.setattr(
        module,
        "_codex_session_signatures",
        lambda: ((str(source), current_signature),),
    )

    assert module._advance_codex_signature_cache_after_event(
        cache,
        {"processed_signatures": {str(source): current_signature}},
    ) is True
    assert cache["codex"] == ((str(source), current_signature),)


def test_codex_generation_segment_uses_absolute_file_offset_for_signature_coverage(tmp_path):
    module = _load_memcore_cloud()
    segment = tmp_path / "active.seg1.jsonl"
    segment.write_bytes(b"tail\n")
    source_signature = (7, 25, 11)
    meta_path = Path(str(segment) + ".meta.json")
    meta_path.write_text(json.dumps({"file_offset": 25}), encoding="utf-8")

    assert module._codex_archive_covers_source_signature(segment, source_signature) is True

    meta_path.write_text(json.dumps({"file_offset": 24}), encoding="utf-8")
    assert module._codex_archive_covers_source_signature(segment, source_signature) is False


def test_codex_event_keeps_old_fallback_signature_when_another_path_changed(monkeypatch, tmp_path):
    module = _load_memcore_cloud()
    handled = tmp_path / "handled.jsonl"
    missed = tmp_path / "missed.jsonl"
    handled.write_text("{}\n", encoding="utf-8")
    missed.write_text("{}\n", encoding="utf-8")
    old_handled = (1, 1, 1)
    old_missed = (2, 1, 1)
    current_handled = module._file_signature(handled)
    current_missed = module._file_signature(missed)
    original = ((str(handled), old_handled), (str(missed), old_missed))
    cache = {"codex": original}
    monkeypatch.setattr(
        module,
        "_codex_session_signatures",
        lambda: ((str(handled), current_handled), (str(missed), current_missed)),
    )

    assert module._advance_codex_signature_cache_after_event(
        cache,
        {"processed_signatures": {str(handled): current_handled}},
    ) is False
    assert cache["codex"] is original


def test_memcore_cloud_event_watch_routes_codex_event_paths_before_fallback(monkeypatch, tmp_path):
    module = _load_memcore_cloud()

    class FakeQueue:
        def __init__(self):
            self._first = True

        def get(self, timeout=None):
            if self._first:
                self._first = False
                return (time.time(), "modified", str(tmp_path / "watch.jsonl"), "")
            raise KeyboardInterrupt

        def get_nowait(self):
            raise queue.Empty

        def put_nowait(self, item):
            pass

    class FakeObserver:
        def schedule(self, handler, root, recursive=True):
            assert recursive is True

        def start(self):
            pass

        def stop(self):
            pass

        def join(self):
            pass

    class FakeHandler:
        pass

    watched = tmp_path / "watch.jsonl"
    watched.write_text('{"type":"session_meta","payload":{"id":"sess-1"}}\n', encoding="utf-8")

    monkeypatch.setattr(module, "_watch_root_candidates", lambda args: [("codex", tmp_path)])
    monkeypatch.setattr(module.queue, "Queue", lambda: FakeQueue())
    monkeypatch.setattr(module, "watcher_poll_interval_seconds", lambda: 0.01)
    monkeypatch.setattr(module, "watcher_poll_interval_milliseconds", lambda: 10)
    monotonic_values = iter([10.0, 10.02])
    monkeypatch.setattr(module.time, "monotonic", lambda: next(monotonic_values))

    event_calls = []
    refresh_calls = []
    sync_calls = []
    sync_invocations = {"count": 0}

    def fake_event_sync(args, event_paths):
        event_calls.append(list(event_paths))
        artifact = {"source_path": str(watched), "session_id": "sess-1"}
        return {
            "handled_sources": {"codex"},
            "work_sources": {"codex"},
            "index_artifacts": {"codex": [artifact]},
            "codex": {"handled_paths": 1, "changed_paths": 1},
        }

    def fake_refresh(**kwargs):
        refresh_calls.append(kwargs)
        return {"ok": True}

    def fake_run_sync_once(*args, **kwargs):
        sync_invocations["count"] += 1
        sync_calls.append(kwargs)
        if sync_invocations["count"] >= 2:
            raise KeyboardInterrupt
        return False

    monkeypatch.setattr(module, "_run_event_driven_sync_once", fake_event_sync)
    monkeypatch.setattr(module, "_refresh_canonical_record_index", fake_refresh)
    monkeypatch.setattr(module, "_run_sync_once", fake_run_sync_once)
    monkeypatch.setattr(module, "canonical_index_limit", lambda: 21)
    monkeypatch.setitem(sys.modules, "watchdog.events", SimpleNamespace(FileSystemEventHandler=FakeHandler))
    monkeypatch.setitem(sys.modules, "watchdog.observers", SimpleNamespace(Observer=FakeObserver))

    try:
        module.watch_file_events(SimpleNamespace(source="all"))
    except KeyboardInterrupt:
        pass

    assert event_calls == [[str(watched)]]
    assert refresh_calls == [{
        "limit": 21,
        "scan_mode": "fast",
        "source_systems": ["codex"],
        "connector_artifacts": {
            "codex": [{"source_path": str(watched), "session_id": "sess-1"}],
        },
    }]
    assert sync_calls[0]["retry_pending"] is True
    assert sync_calls[1]["skip_sources"] == {"codex"}


def test_memcore_cloud_event_watch_does_not_run_global_fallback_for_each_event_batch(
    monkeypatch,
    tmp_path,
):
    module = _load_memcore_cloud()

    class FakeQueue:
        def __init__(self):
            self._first = True

        def get(self, timeout=None):
            if self._first:
                self._first = False
                return (time.time(), "modified", str(tmp_path / "watch.jsonl"), "")
            raise KeyboardInterrupt

        def get_nowait(self):
            raise queue.Empty

        def put_nowait(self, item):
            pass

    class FakeObserver:
        def schedule(self, handler, root, recursive=True):
            assert recursive is True

        def start(self):
            pass

        def stop(self):
            pass

        def join(self):
            pass

    class FakeHandler:
        pass

    watched = tmp_path / "watch.jsonl"
    watched.write_text('{}\n', encoding="utf-8")
    monkeypatch.setattr(module, "_watch_root_candidates", lambda args: [("codex", tmp_path)])
    monkeypatch.setattr(module.queue, "Queue", lambda: FakeQueue())
    monkeypatch.setattr(module, "watcher_poll_interval_seconds", lambda: 5.0)
    monkeypatch.setattr(module, "watcher_poll_interval_milliseconds", lambda: 5000)
    monotonic_values = iter([10.0, 10.01])
    monkeypatch.setattr(module.time, "monotonic", lambda: next(monotonic_values))
    sync_calls = []
    event_calls = []
    monkeypatch.setattr(
        module,
        "_run_sync_once",
        lambda *args, **kwargs: sync_calls.append(kwargs) or False,
    )
    monkeypatch.setattr(
        module,
        "_run_event_driven_sync_once",
        lambda args, paths: event_calls.append(list(paths)) or {
            "handled_sources": {"codex"},
            "work_sources": {"codex"},
            "index_artifacts": {},
        },
    )
    monkeypatch.setitem(
        sys.modules,
        "watchdog.events",
        SimpleNamespace(FileSystemEventHandler=FakeHandler),
    )
    monkeypatch.setitem(
        sys.modules,
        "watchdog.observers",
        SimpleNamespace(Observer=FakeObserver),
    )

    try:
        module.watch_file_events(SimpleNamespace(source="all"))
    except KeyboardInterrupt:
        pass

    assert event_calls == [[str(watched)]]
    assert len(sync_calls) == 1
    assert sync_calls[0]["retry_pending"] is True


def test_codex_event_sync_returns_exact_artifact_for_targeted_index(monkeypatch, tmp_path):
    module = _load_memcore_cloud()
    source = tmp_path / "active.jsonl"
    source.write_text('{"type":"session_meta","payload":{"id":"sess-1"}}\n', encoding="utf-8")
    artifact = {
        "source_path": str(source),
        "session_id": "sess-1",
        "canonical_window_id": "project-1",
    }
    raw = tmp_path / "raw.jsonl"

    def fake_archive(*_args, **_kwargs):
        raw.write_bytes(source.read_bytes())
        return str(raw), "appended(1 line)"

    connector = SimpleNamespace(
        codex_sessions_root=lambda: tmp_path,
        artifact_from_path=lambda path: {**artifact, "source_path": str(path)},
        archive_session_incremental=fake_archive,
        _register_current_window_for_artifact=lambda *_args, **_kwargs: {"ok": True},
    )
    monkeypatch.setitem(sys.modules, "codex_local_connector", connector)
    monkeypatch.setattr(module, "incremental_extract_session", lambda _path: (0, 0, 0))

    result = module._run_codex_event_sync_once(
        SimpleNamespace(source="codex"),
        [str(source)],
    )

    assert result["handled_paths"] == 1
    assert result["changed_paths"] == 1
    assert result["index_artifacts"] == [artifact]
    assert result["processed_signatures"] == {str(source.resolve()): module._file_signature(source)}


def test_codex_event_generation_start_runs_downstream_and_advances_signature(monkeypatch, tmp_path):
    module = _load_memcore_cloud()
    source = tmp_path / "active.jsonl"
    source.write_text('{"type":"session_meta","payload":{"id":"sess-1"}}\n', encoding="utf-8")
    artifact = {
        "source_path": str(source),
        "session_id": "sess-1",
        "canonical_window_id": "project-1",
    }
    generation = tmp_path / "raw.seg1.jsonl"

    def fake_archive(*_args, **_kwargs):
        generation.write_bytes(b"tail\n")
        Path(str(generation) + ".meta.json").write_text(
            json.dumps({"file_offset": source.stat().st_size}),
            encoding="utf-8",
        )
        return str(generation), "generation_started(generation=1,base=49,bytes=5)"

    registered = []
    connector = SimpleNamespace(
        codex_sessions_root=lambda: tmp_path,
        artifact_from_path=lambda path: {**artifact, "source_path": str(path)},
        archive_session_incremental=fake_archive,
        _register_current_window_for_artifact=lambda item, dest: registered.append((item, dest)) or {"ok": True},
    )
    monkeypatch.setitem(sys.modules, "codex_local_connector", connector)
    extracted = []
    monkeypatch.setattr(
        module,
        "incremental_extract_session",
        lambda path: extracted.append(path) or (0, 0, 0),
    )

    result = module._run_codex_event_sync_once(
        SimpleNamespace(source="codex"),
        [str(source)],
    )

    assert result["changed_paths"] == 1
    assert result["work_sources"] == {"codex"}
    assert result["index_artifacts"] == [artifact]
    assert result["processed_signatures"] == {
        str(source.resolve()): module._file_signature(source),
    }
    assert registered == [(artifact, str(generation))]
    assert extracted == [str(generation)]


def test_codex_terminal_attention_stays_visible_without_reindexing_unchanged_raw(
    monkeypatch,
    tmp_path,
    capsys,
):
    module = _load_memcore_cloud()
    source = tmp_path / "divergent.jsonl"
    source.write_text('{}\n', encoding="utf-8")
    artifact = {
        "source_path": str(source),
        "session_id": "sess-divergent",
        "canonical_window_id": "project-divergent",
    }

    def must_not_run(*_args, **_kwargs):
        raise AssertionError("terminal attention without raw change triggered downstream work")

    connector = SimpleNamespace(
        codex_sessions_root=lambda: tmp_path,
        artifact_from_path=lambda path: {**artifact, "source_path": str(path)},
        archive_session_incremental=lambda *_args, **_kwargs: (
            str(tmp_path / "raw.jsonl"),
            "source_divergence_raw_retained(source=9,raw=9)",
        ),
        _register_current_window_for_artifact=must_not_run,
    )
    monkeypatch.setitem(sys.modules, "codex_local_connector", connector)
    monkeypatch.setattr(module, "incremental_extract_session", must_not_run)

    result = module._run_codex_event_sync_once(
        SimpleNamespace(source="codex"),
        [str(source)],
    )

    assert result["handled_paths"] == 1
    assert result["changed_paths"] == 0
    assert result["index_artifacts"] == []
    assert "[codex event source_divergence_raw_retained]" in capsys.readouterr().out


def test_codex_generation_fail_closed_does_not_advance_or_run_downstream(
    monkeypatch,
    tmp_path,
    capsys,
):
    module = _load_memcore_cloud()
    source = tmp_path / "divergent.jsonl"
    source.write_text('{}\n', encoding="utf-8")
    raw = tmp_path / "raw.seg1.jsonl"
    raw.write_bytes(source.read_bytes())
    Path(str(raw) + ".meta.json").write_text(
        json.dumps({"file_offset": source.stat().st_size}),
        encoding="utf-8",
    )
    artifact = {
        "source_path": str(source),
        "session_id": "sess-divergent",
        "canonical_window_id": "project-divergent",
    }

    def must_not_run(*_args, **_kwargs):
        raise AssertionError("fail-closed generation triggered downstream work")

    connector = SimpleNamespace(
        codex_sessions_root=lambda: tmp_path,
        artifact_from_path=lambda path: {**artifact, "source_path": str(path)},
        archive_session_incremental=lambda *_args, **_kwargs: (
            str(raw),
            "source_divergence_generation_fail_closed(reason=descriptor_invalid)",
        ),
        _register_current_window_for_artifact=must_not_run,
    )
    monkeypatch.setitem(sys.modules, "codex_local_connector", connector)
    monkeypatch.setattr(module, "incremental_extract_session", must_not_run)

    result = module._run_codex_event_sync_once(
        SimpleNamespace(source="codex"),
        [str(source)],
    )

    assert result["changed_paths"] == 0
    assert result["index_artifacts"] == []
    assert result["processed_signatures"] == {}
    assert "[codex event source_divergence_generation_fail_closed]" in capsys.readouterr().out


def test_memcore_cloud_run_sync_once_skips_sources_already_handled_by_event_path(monkeypatch):
    module = _load_memcore_cloud()

    calls = []

    monkeypatch.setattr(module, "_run_openclaw_sync_once", lambda *args, **kwargs: calls.append("openclaw") or False)
    monkeypatch.setattr(module, "_run_codex_sync_once", lambda *args, **kwargs: calls.append("codex") or True)
    monkeypatch.setattr(module, "_run_claude_code_sync_once", lambda *args, **kwargs: calls.append("claude_code_cli") or False)
    monkeypatch.setattr(module, "_run_claude_desktop_sync_once", lambda *args, **kwargs: calls.append("claude_desktop") or False)
    monkeypatch.setattr(module, "_run_kiro_sync_once", lambda *args, **kwargs: calls.append("kiro") or False)
    monkeypatch.setattr(module, "_run_hermes_sync_once", lambda *args, **kwargs: calls.append("hermes") or False)
    monkeypatch.setattr(module, "claude_desktop_raw_ingest_interval_seconds", lambda: 60.0)
    monkeypatch.setattr(module, "canonical_index_enabled", lambda: False)

    did_work = module._run_sync_once(
        SimpleNamespace(source="all"),
        signature_cache={},
        state={},
        force=False,
        skip_sources={"codex"},
    )

    assert did_work is False
    assert "codex" not in calls
    assert calls == ["openclaw", "claude_code_cli", "claude_desktop", "kiro", "hermes"]
