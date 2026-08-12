#!/usr/bin/env python3
"""
memcore-cloud P0: 主入口
支持两种模式：
  --scan    批量扫描（已有 session 归档）
  --watch   inotify 实时监听新 session
"""
import os, sys, json, glob, argparse, shutil, time, signal, queue
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from p2_extract import incremental_extract_session
from config_loader import base_path, openclaw_agents, memory_root, checkpoint_file, alias_map, node_id, get as config_get
try:
    from src.raw_archive_layout import preferred_raw_archive_path
except ImportError:
    from raw_archive_layout import preferred_raw_archive_path

UTC = timezone.utc
DEFAULT_SYNC_INTERVAL_MS = 5_000
DEFAULT_CANONICAL_INDEX_INTERVAL_SECONDS = 60.0
DEFAULT_HERMES_RECHECK_INTERVAL_SECONDS = 900
CLAUDE_DESKTOP_SIGNATURE_DISCOVERY_INTERVAL_SECONDS = 900.0
MIN_SYNC_INTERVAL_MS = 50
MAX_SYNC_INTERVAL_MS = 3_600_000
MAX_SIGNATURE_FILES_PER_DIR = 256
CLAUDE_SIGNATURE_FILE_SUFFIXES = {".log", ".ldb", ".sst", ".json", ".jsonl", ".txt"}
WATCH_EVENT_FILE_SUFFIXES = {".jsonl", ".json", ".log", ".ldb", ".sst", ".txt"}
RAW_ARCHIVE_DIAGNOSTIC_LOG_INTERVAL_SECONDS = 5.0
WATCHER_PHASE_IO_LOG_INTERVAL_SECONDS = 5.0
WATCHER_PHASE_IO_KEYS = (
    "codex_event_archive",
    "targeted_canonical_index",
    "openclaw_sync",
    "codex_fallback_sync",
    "claude_code_sync",
    "claude_desktop_sync",
    "kiro_sync",
    "hermes_sync",
    "periodic_canonical_index",
)
CLAUDE_DESKTOP_NON_RAW_TRIGGER_ARTIFACT_TYPES = {
    "local_relay_proxy_request_logs_db",
}

OPENCLAW_ROOT = openclaw_agents()
INSTALL_ROOT = base_path()
MEMCORE_ROOT = memory_root()
CHECKPOINT_FILE = checkpoint_file()
ALIAS_MAP_FILE = alias_map()

SOURCE_SYSTEM = "openclaw"
NATIVE_ARTIFACT_FORMAT = "openclaw_session_jsonl"
HOSTNAME = node_id()
_RAW_ARCHIVE_DIAGNOSTIC_LAST = None
_RAW_ARCHIVE_DIAGNOSTIC_LAST_EMITTED_AT = 0.0
_WATCHER_PHASE_IO = {
    phase: {"call_count": 0, "measured_call_count": 0, "read_bytes": 0}
    for phase in WATCHER_PHASE_IO_KEYS
}
_WATCHER_PHASE_IO_LAST = None
_WATCHER_PHASE_IO_LAST_EMITTED_AT = 0.0
_CLAUDE_DESKTOP_SIGNATURE_ARTIFACTS = None
_CLAUDE_DESKTOP_SIGNATURE_DISCOVERED_AT = 0.0
DIALOG_ENTRY_OPENCLAW_EVENT_URL = os.environ.get(
    "MEMCORE_DIALOG_ENTRY_OPENCLAW_EVENT_URL",
    "http://127.0.0.1:19600/entry/openclaw-event",
)
try:
    OPENCLAW_EVENT_DELIVERY_TIMEOUT = max(
        5,
        min(int(os.environ.get("MEMCORE_OPENCLAW_EVENT_DELIVERY_TIMEOUT", "180")), 300),
    )
except ValueError:
    OPENCLAW_EVENT_DELIVERY_TIMEOUT = 180
OPENCLAW_EVENT_DELIVERED_KEY = "openclaw_entry_delivered_event_ids"
OPENCLAW_EVENT_PENDING_KEY = "openclaw_entry_pending_events"
OPENCLAW_EVENT_FRESH_ARCHIVE_SECONDS = 30


def _truthy(value):
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _int_setting(env_name, config_path, default, minimum=1, maximum=3600):
    raw = os.environ.get(env_name)
    if raw is None:
        raw = config_get(config_path, default)
    try:
        value = int(raw)
    except Exception:
        value = default
    return max(minimum, min(value, maximum))


def _milliseconds_setting(
    env_ms_name,
    config_ms_path,
    default_ms,
    *,
    legacy_env_seconds_name="",
    legacy_config_seconds_path="",
    minimum=MIN_SYNC_INTERVAL_MS,
    maximum=MAX_SYNC_INTERVAL_MS,
):
    raw = os.environ.get(env_ms_name)
    if raw is None:
        raw = config_get(config_ms_path, None)
    if raw is None and legacy_env_seconds_name:
        raw_seconds = os.environ.get(legacy_env_seconds_name)
        if raw_seconds is not None:
            try:
                raw = int(float(raw_seconds) * 1000)
            except Exception:
                raw = None
    if raw is None and legacy_config_seconds_path:
        raw_seconds = config_get(legacy_config_seconds_path, None)
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


def watcher_poll_interval_milliseconds():
    return _milliseconds_setting(
        "MEMCORE_WATCHER_INTERVAL_MS",
        "services.p0_watcher_interval_milliseconds",
        DEFAULT_SYNC_INTERVAL_MS,
        legacy_env_seconds_name="MEMCORE_WATCHER_POLL_INTERVAL_SECONDS",
    )


def watcher_poll_interval_seconds():
    return watcher_poll_interval_milliseconds() / 1000.0


def watcher_resource_profile():
    raw = os.environ.get("MEMCORE_WATCHER_RESOURCE_PROFILE")
    if raw is None:
        raw = config_get("services.p0_watcher_resource_profile", "light")
    value = str(raw or "light").strip().lower()
    return value if value in {"light", "balanced", "heavy"} else "light"


def watcher_source_default():
    raw = os.environ.get("MEMCORE_WATCHER_SOURCE_DEFAULT")
    if raw is None:
        raw = config_get("services.p0_watcher_source_default", "all")
    value = str(raw or "all").strip().lower()
    allowed = {"all", "openclaw", "codex", "claude_code_cli", "claude_desktop", "kiro", "hermes"}
    return value if value in allowed else "all"


def watcher_pid_path():
    configured = os.environ.get("MEMCORE_P0_WATCHER_PID_PATH")
    if configured:
        return Path(configured).expanduser()
    return Path(INSTALL_ROOT) / "runtime" / "p0-watcher.pid"


def _write_watcher_pid_file():
    path = watcher_pid_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        tmp.write_text(f"{os.getpid()}\n", encoding="ascii")
        os.replace(tmp, path)
    except Exception as exc:
        print(f"[memcore-cloud] watcher pid write skipped: {type(exc).__name__}:{str(exc)[:120]}")


def _clear_watcher_pid_file():
    path = watcher_pid_path()
    try:
        current = path.read_text(encoding="ascii", errors="ignore").strip()
        if current == str(os.getpid()):
            path.unlink()
    except FileNotFoundError:
        pass
    except Exception as exc:
        print(f"[memcore-cloud] watcher pid cleanup skipped: {type(exc).__name__}:{str(exc)[:120]}")


def claude_desktop_raw_ingest_enabled():
    if "MEMCORE_CLAUDE_DESKTOP_RAW_INGEST_ENABLED" in os.environ:
        return _truthy(os.environ.get("MEMCORE_CLAUDE_DESKTOP_RAW_INGEST_ENABLED"))
    configured = config_get("integrations.claude_desktop.raw_ingest.enabled", None)
    if configured is None:
        return True
    return _truthy(configured)


def claude_desktop_raw_ingest_authorized_by():
    if "MEMCORE_CLAUDE_DESKTOP_RAW_INGEST_ENABLED" in os.environ:
        return "memcore_env_MEMCORE_CLAUDE_DESKTOP_RAW_INGEST_ENABLED"
    configured = config_get("integrations.claude_desktop.raw_ingest.enabled", None)
    if configured is None:
        return "memcore_default_claude_desktop_continuous_raw_ingest"
    return "memcore_config_integrations.claude_desktop.raw_ingest"


def claude_desktop_raw_ingest_limit():
    return _int_setting(
        "MEMCORE_CLAUDE_DESKTOP_RAW_INGEST_LIMIT",
        "integrations.claude_desktop.raw_ingest.limit",
        20,
        minimum=1,
        maximum=100,
    )


def claude_desktop_raw_ingest_interval_seconds():
    return claude_desktop_raw_ingest_interval_milliseconds() / 1000.0


def claude_desktop_raw_ingest_interval_milliseconds():
    return _milliseconds_setting(
        "MEMCORE_CLAUDE_DESKTOP_RAW_INGEST_INTERVAL_MS",
        "integrations.claude_desktop.raw_ingest.interval_milliseconds",
        DEFAULT_SYNC_INTERVAL_MS,
        legacy_env_seconds_name="MEMCORE_CLAUDE_DESKTOP_RAW_INGEST_INTERVAL_SECONDS",
    )


def claude_desktop_raw_ingest_interval_seconds_legacy():
    return _int_setting(
        "MEMCORE_CLAUDE_DESKTOP_RAW_INGEST_INTERVAL_SECONDS",
        "integrations.claude_desktop.raw_ingest.interval_seconds",
        5,
        minimum=5,
        maximum=3600,
    )


def hermes_raw_backfill_enabled():
    if "MEMCORE_HERMES_RAW_BACKFILL_ENABLED" in os.environ:
        return _truthy(os.environ.get("MEMCORE_HERMES_RAW_BACKFILL_ENABLED"))
    configured = config_get("integrations.hermes.raw_backfill.enabled", None)
    if configured is None:
        return True
    return _truthy(configured)


def hermes_raw_backfill_limit():
    return _int_setting(
        "MEMCORE_HERMES_RAW_BACKFILL_LIMIT",
        "integrations.hermes.raw_backfill.limit",
        80,
        minimum=1,
        maximum=200,
    )


def hermes_raw_backfill_recheck_interval_seconds():
    return _int_setting(
        "MEMCORE_HERMES_RAW_BACKFILL_RECHECK_INTERVAL_SECONDS",
        "integrations.hermes.raw_backfill.recheck_interval_seconds",
        DEFAULT_HERMES_RECHECK_INTERVAL_SECONDS,
        minimum=30,
        maximum=86_400,
    )


def _file_signature(path):
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (getattr(st, "st_ino", 0), st.st_size, getattr(st, "st_mtime_ns", int(st.st_mtime * 1_000_000_000)))


def _signature_changed(cache, key, signature):
    if signature is None:
        return False
    previous = cache.get(key)
    cache[key] = signature
    return previous != signature


def _raw_archive_diagnostics_snapshot():
    snapshot_fn = None
    for module_name in ("src.raw_archive_monotonic", "raw_archive_monotonic"):
        module = sys.modules.get(module_name)
        candidate = getattr(module, "raw_archive_diagnostics_snapshot", None)
        if callable(candidate):
            snapshot_fn = candidate
            break
    if snapshot_fn is None:
        try:
            from src.raw_archive_monotonic import raw_archive_diagnostics_snapshot as snapshot_fn
        except Exception:
            try:
                from raw_archive_monotonic import raw_archive_diagnostics_snapshot as snapshot_fn
            except Exception:
                return {}
    try:
        return snapshot_fn()
    except Exception:
        return {}


def _emit_raw_archive_diagnostics(force=False):
    global _RAW_ARCHIVE_DIAGNOSTIC_LAST, _RAW_ARCHIVE_DIAGNOSTIC_LAST_EMITTED_AT
    snapshot = _raw_archive_diagnostics_snapshot()
    keys = (
        "matched_prefix_cache_hit_count",
        "matched_prefix_cache_miss_count",
        "verified_prefix_rehash_hit_count",
        "verified_prefix_rehash_miss_count",
        "verified_prefix_rehash_source_bytes",
        "divergence_witness_hit_count",
        "full_prefix_scan_count",
        "full_prefix_source_bytes",
        "full_prefix_archive_bytes",
        "full_prefix_total_bytes",
    )
    try:
        signature = tuple(int(snapshot.get(key, 0) or 0) for key in keys)
    except (TypeError, ValueError):
        return False
    if not any(signature) or signature == _RAW_ARCHIVE_DIAGNOSTIC_LAST:
        return False
    now = time.monotonic()
    if (
        not force
        and _RAW_ARCHIVE_DIAGNOSTIC_LAST is not None
        and now - _RAW_ARCHIVE_DIAGNOSTIC_LAST_EMITTED_AT
        < RAW_ARCHIVE_DIAGNOSTIC_LOG_INTERVAL_SECONDS
    ):
        return False
    ts_now = datetime.now(UTC).strftime("%H:%M:%S")
    print(
        f"  [{ts_now}] [raw archive io] "
        f"matched_hit={signature[0]} matched_miss={signature[1]} "
        f"verified_rehash_hit={signature[2]} verified_rehash_miss={signature[3]} "
        f"verified_rehash_source_bytes={signature[4]} divergence_hit={signature[5]} "
        f"full_scans={signature[6]} full_source_bytes={signature[7]} "
        f"full_archive_bytes={signature[8]} full_total_bytes={signature[9]}"
    )
    _RAW_ARCHIVE_DIAGNOSTIC_LAST = signature
    _RAW_ARCHIVE_DIAGNOSTIC_LAST_EMITTED_AT = now
    return True


def _process_read_transfer_bytes():
    if os.name == "nt":
        try:
            import ctypes

            class IoCounters(ctypes.Structure):
                _fields_ = [
                    ("read_operation_count", ctypes.c_ulonglong),
                    ("write_operation_count", ctypes.c_ulonglong),
                    ("other_operation_count", ctypes.c_ulonglong),
                    ("read_transfer_count", ctypes.c_ulonglong),
                    ("write_transfer_count", ctypes.c_ulonglong),
                    ("other_transfer_count", ctypes.c_ulonglong),
                ]

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            get_current_process = kernel32.GetCurrentProcess
            get_current_process.argtypes = []
            get_current_process.restype = ctypes.c_void_p
            get_process_io_counters = kernel32.GetProcessIoCounters
            get_process_io_counters.argtypes = [ctypes.c_void_p, ctypes.POINTER(IoCounters)]
            get_process_io_counters.restype = ctypes.c_int
            counters = IoCounters()
            if not get_process_io_counters(get_current_process(), ctypes.byref(counters)):
                return None
            return int(counters.read_transfer_count)
        except Exception:
            return None

    try:
        with open("/proc/self/io", "r", encoding="ascii") as handle:
            for line in handle:
                key, separator, value = line.partition(":")
                if separator and key.strip() == "read_bytes":
                    return int(value.strip())
    except (OSError, TypeError, ValueError):
        pass
    return None


def _measure_watcher_phase_io(phase, callback, *args, **kwargs):
    before = _process_read_transfer_bytes()
    try:
        return callback(*args, **kwargs)
    finally:
        after = _process_read_transfer_bytes()
        counters = _WATCHER_PHASE_IO.get(phase)
        if counters is not None:
            counters["call_count"] += 1
            if isinstance(before, int) and isinstance(after, int) and after >= before:
                counters["measured_call_count"] += 1
                counters["read_bytes"] += after - before


def _watcher_phase_io_snapshot():
    return {
        "contract": "time_library_watcher_phase_io_diagnostics.v1",
        "unit": "calls/measured_calls/read_transfer_bytes",
        "phases": {
            phase: {
                "call_count": int(_WATCHER_PHASE_IO[phase]["call_count"]),
                "measured_call_count": int(_WATCHER_PHASE_IO[phase]["measured_call_count"]),
                "read_bytes": int(_WATCHER_PHASE_IO[phase]["read_bytes"]),
            }
            for phase in WATCHER_PHASE_IO_KEYS
        },
    }


def _emit_watcher_phase_io_diagnostics(force=False):
    global _WATCHER_PHASE_IO_LAST, _WATCHER_PHASE_IO_LAST_EMITTED_AT
    snapshot = _watcher_phase_io_snapshot()
    phases = snapshot["phases"]
    signature = tuple(
        value
        for phase in WATCHER_PHASE_IO_KEYS
        for value in (
            phases[phase]["call_count"],
            phases[phase]["measured_call_count"],
            phases[phase]["read_bytes"],
        )
    )
    if (
        not any(phases[phase]["measured_call_count"] for phase in WATCHER_PHASE_IO_KEYS)
        or signature == _WATCHER_PHASE_IO_LAST
    ):
        return False
    now = time.monotonic()
    if (
        not force
        and _WATCHER_PHASE_IO_LAST is not None
        and now - _WATCHER_PHASE_IO_LAST_EMITTED_AT
        < WATCHER_PHASE_IO_LOG_INTERVAL_SECONDS
    ):
        return False
    ts_now = datetime.now(UTC).strftime("%H:%M:%S")
    values = " ".join(
        f"{phase}={phases[phase]['call_count']}/"
        f"{phases[phase]['measured_call_count']}/"
        f"{phases[phase]['read_bytes']}"
        for phase in WATCHER_PHASE_IO_KEYS
    )
    print(f"  [{ts_now}] [watcher phase io] unit=calls/measured/read_bytes {values}")
    _WATCHER_PHASE_IO_LAST = signature
    _WATCHER_PHASE_IO_LAST_EMITTED_AT = now
    return True


def _claude_desktop_artifact_triggers_raw_ingest(artifact):
    artifact_type = str((artifact or {}).get("artifact_type") or "").strip()
    return artifact_type not in CLAUDE_DESKTOP_NON_RAW_TRIGGER_ARTIFACT_TYPES


def file_event_backend_status():
    try:
        from watchdog.observers import Observer
    except Exception as exc:
        return {
            "available": False,
            "backend": "unavailable",
            "error": f"{type(exc).__name__}:{str(exc)[:120]}",
        }
    backend = getattr(Observer, "__module__", "watchdog.observers")
    return {
        "available": True,
        "backend": backend,
    }


def _iter_openclaw_session_files():
    if not os.path.isdir(OPENCLAW_ROOT):
        return []
    files = []
    for agent_dir in sorted(os.listdir(OPENCLAW_ROOT)):
        sessions_dir = os.path.join(OPENCLAW_ROOT, agent_dir, "sessions")
        if not os.path.isdir(sessions_dir):
            continue
        for sf in sorted(glob.glob(os.path.join(sessions_dir, "*.jsonl"))):
            session_id = os.path.basename(sf).replace(".jsonl", "")
            if ".checkpoint." not in session_id:
                files.append((agent_dir, session_id, sf))
    return files


def _codex_session_signatures():
    try:
        from codex_local_connector import codex_sessions_root
    except Exception:
        return None
    root = codex_sessions_root()
    if not root.exists():
        return ()
    items = []
    try:
        files = root.rglob("*.jsonl")
        for path in files:
            if not path.is_file():
                continue
            sig = _file_signature(path)
            if sig is not None:
                items.append((str(path), sig))
    except OSError:
        return None
    return tuple(sorted(items))


def _normalized_signature_map(signature):
    normalized = {}
    for item in signature or ():
        if not isinstance(item, tuple) or len(item) != 2:
            continue
        path, value = item
        normalized[os.path.normcase(os.path.abspath(str(path)))] = value
    return normalized


def _codex_archive_covers_source_signature(dest, source_signature):
    if not source_signature:
        return False
    try:
        source_size = int(source_signature[1])
    except (IndexError, TypeError, ValueError):
        return False

    meta_path = Path(str(dest) + ".meta.json")
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8-sig"))
        if isinstance(meta, dict) and "file_offset" in meta:
            return int(meta.get("file_offset", -1)) == source_size
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        pass

    try:
        return Path(dest).stat().st_size == source_size
    except OSError:
        return False


def _advance_codex_signature_cache_after_event(signature_cache, event_result):
    """Advance reconciliation only when every observed change was processed.

    A native event may race another file change or omit a path. In either case
    the old signature is retained so the next fallback pass remains fail-safe.
    """
    if not isinstance(signature_cache, dict) or "codex" not in signature_cache:
        return False
    processed = {
        os.path.normcase(os.path.abspath(str(path))): value
        for path, value in (event_result.get("processed_signatures") or {}).items()
    }
    if not processed:
        return False
    current_signature = _codex_session_signatures()
    if current_signature is None:
        return False
    previous = _normalized_signature_map(signature_cache.get("codex"))
    current = _normalized_signature_map(current_signature)
    changed_paths = {
        path
        for path in previous.keys() | current.keys()
        if previous.get(path) != current.get(path)
    }
    if not changed_paths or any(
        path not in processed or processed[path] != current.get(path)
        for path in changed_paths
    ):
        return False
    signature_cache["codex"] = current_signature
    return True


def _claude_code_session_signatures():
    try:
        from claude_code_local_connector import claude_code_projects_root, claude_desktop_code_sessions_root
    except Exception:
        return None
    items = []
    try:
        for root, suffix in (
            (claude_code_projects_root(), ".jsonl"),
            (claude_desktop_code_sessions_root(), ".json"),
        ):
            if not root.exists():
                continue
            for path in root.rglob(f"*{suffix}"):
                if not path.is_file() or ".checkpoint." in path.name:
                    continue
                sig = _file_signature(path)
                if sig is not None:
                    items.append((str(path), sig))
    except OSError:
        return None
    return tuple(sorted(items))


def _kiro_session_signatures():
    try:
        from kiro_local_connector import _candidate_session_files, _kiro_workspace_session_roots
    except Exception:
        return None
    items = []
    try:
        for root in _kiro_workspace_session_roots():
            for path in _candidate_session_files(root):
                sig = _file_signature(path)
                if sig is not None:
                    items.append((str(path), sig))
    except OSError:
        return None
    return tuple(sorted(items))


def _claude_desktop_signature_artifacts(force_refresh=False):
    global _CLAUDE_DESKTOP_SIGNATURE_ARTIFACTS, _CLAUDE_DESKTOP_SIGNATURE_DISCOVERED_AT
    try:
        from claude_desktop_connector import discover_artifacts
    except Exception:
        return None
    now = time.monotonic()
    if (
        not force_refresh
        and _CLAUDE_DESKTOP_SIGNATURE_ARTIFACTS is not None
        and now - _CLAUDE_DESKTOP_SIGNATURE_DISCOVERED_AT
        < CLAUDE_DESKTOP_SIGNATURE_DISCOVERY_INTERVAL_SECONDS
    ):
        return _CLAUDE_DESKTOP_SIGNATURE_ARTIFACTS
    try:
        artifacts = []
        for artifact in discover_artifacts(limit=80):
            if not _claude_desktop_artifact_triggers_raw_ingest(artifact):
                continue
            artifact_type = str(artifact.get("artifact_type") or "")
            path_text = artifact.get("path") or artifact.get("source_path") or artifact.get("store_path") or ""
            if path_text:
                artifacts.append((artifact_type, str(Path(path_text).expanduser())))
    except Exception:
        return None
    _CLAUDE_DESKTOP_SIGNATURE_ARTIFACTS = tuple(artifacts)
    _CLAUDE_DESKTOP_SIGNATURE_DISCOVERED_AT = now
    return _CLAUDE_DESKTOP_SIGNATURE_ARTIFACTS


def _claude_desktop_store_signatures(force_refresh=False):
    artifacts = _claude_desktop_signature_artifacts(force_refresh=force_refresh)
    if artifacts is None:
        return None
    items = []
    try:
        for artifact_type, path_text in artifacts:
            path = Path(path_text)
            if path.is_file():
                sig = _file_signature(path)
                if sig is not None:
                    items.append((str(path), sig))
            elif path.is_dir():
                dir_sig = _file_signature(path)
                if dir_sig is not None:
                    items.append((str(path), dir_sig))
                if artifact_type not in {
                    "claude_desktop_indexeddb_leveldb_dir",
                    "claude_desktop_indexeddb_blob_dir",
                    "claude_desktop_local_storage_leveldb_dir",
                    "claude_desktop_session_storage_dir",
                    "claude_desktop_logs_dir",
                }:
                    continue
                try:
                    sampled = 0
                    for child in path.iterdir():
                        if not child.is_file() or child.suffix.lower() not in CLAUDE_SIGNATURE_FILE_SUFFIXES:
                            continue
                        sig = _file_signature(child)
                        if sig is not None:
                            items.append((str(child), sig))
                            sampled += 1
                        if sampled >= MAX_SIGNATURE_FILES_PER_DIR:
                            break
                except OSError:
                    continue
    except Exception:
        return None
    return tuple(sorted(items))


def _hermes_state_db_signatures():
    try:
        from hermes_paths import hermes_state_db_path
    except Exception:
        return None
    db_path = Path(hermes_state_db_path()).expanduser()
    # SQLite readers update SHM coordination metadata without changing the
    # logical database. Main DB and WAL signatures cover durable changes.
    candidates = [db_path, Path(str(db_path) + "-wal")]
    items = []
    for path in candidates:
        if not path.exists():
            continue
        sig = _file_signature(path)
        if sig is not None:
            items.append((str(path), sig))
    return tuple(sorted(items))


def _watch_root_candidates(args):
    roots = {}
    if _source_enabled(args, "openclaw"):
        os.makedirs(OPENCLAW_ROOT, exist_ok=True)
        roots[str(Path(OPENCLAW_ROOT).expanduser())] = "openclaw"
    if _source_enabled(args, "codex"):
        try:
            from codex_local_connector import codex_sessions_root
            root = codex_sessions_root()
            if root.exists():
                roots[str(root)] = "codex"
        except Exception:
            pass
    if _source_enabled(args, "claude_code_cli"):
        try:
            from claude_code_local_connector import claude_code_projects_root, claude_desktop_code_sessions_root
            for root in (claude_code_projects_root(), claude_desktop_code_sessions_root()):
                if root.exists():
                    roots[str(root)] = "claude_code_cli"
        except Exception:
            pass
    if _source_enabled(args, "kiro"):
        try:
            from kiro_local_connector import _kiro_workspace_session_roots
            for root in _kiro_workspace_session_roots():
                if root.exists():
                    roots[str(root)] = "kiro"
        except Exception:
            pass
    if _source_enabled(args, "claude_desktop") and claude_desktop_raw_ingest_enabled():
        try:
            from claude_desktop_connector import discover_artifacts
            for artifact in discover_artifacts(limit=80):
                if not _claude_desktop_artifact_triggers_raw_ingest(artifact):
                    continue
                path_text = artifact.get("path") or artifact.get("source_path") or artifact.get("store_path") or ""
                if not path_text:
                    continue
                path = Path(path_text).expanduser()
                if path.is_file() and path.parent.exists():
                    roots[str(path.parent)] = "claude_desktop"
                elif path.is_dir():
                    roots[str(path)] = "claude_desktop"
        except Exception:
            pass
    if _source_enabled(args, "hermes") and hermes_raw_backfill_enabled():
        try:
            from hermes_paths import hermes_state_db_path
            db_path = Path(hermes_state_db_path()).expanduser()
            if db_path.exists() and db_path.parent.exists():
                roots[str(db_path.parent)] = "hermes"
        except Exception:
            pass
    return [(source, Path(path)) for path, source in sorted(roots.items())]


def _watch_event_relevant(event):
    if getattr(event, "is_directory", False):
        return True
    for attr in ("src_path", "dest_path"):
        path = Path(str(getattr(event, attr, "") or ""))
        if not path.name or ".checkpoint." in path.name:
            continue
        if path.suffix.lower() in WATCH_EVENT_FILE_SUFFIXES:
            return True
    return False


def _watch_event_paths(entry):
    if not isinstance(entry, tuple):
        return []
    paths = []
    for value in entry[2:]:
        text = str(value or "").strip()
        if text:
            paths.append(text)
    return paths


def _run_openclaw_sync_once(args, signature_cache=None, force=False, retry_pending=False):
    if not _source_enabled(args, "openclaw"):
        return False
    os.makedirs(OPENCLAW_ROOT, exist_ok=True)
    did_work = False
    checkpoint_snapshot = load_checkpoint() if retry_pending else {}
    for agent_dir, session_id, sf in _iter_openclaw_session_files():
        sig = _file_signature(sf)
        changed = force or signature_cache is None or _signature_changed(signature_cache, f"openclaw:{sf}", sig)
        if not changed and not retry_pending:
            continue
        checkpoint_entry = checkpoint_snapshot.get(sf, {}) if isinstance(checkpoint_snapshot, dict) else {}
        pending_events = checkpoint_entry.get(OPENCLAW_EVENT_PENDING_KEY, [])
        has_pending = isinstance(pending_events, list) and bool(pending_events)
        if not changed and retry_pending and not has_pending:
            continue
        if changed:
            if retry_pending:
                prior_offset = checkpoint_entry.get("offset", 0)
            else:
                prior_offset = load_checkpoint().get(sf, {}).get("offset", 0)
            dest, status = archive_session(sf)
            ts_now = datetime.now(UTC).strftime("%H:%M:%S")
            if status == "archived":
                print(f"  [{ts_now}] [openclaw archived] {agent_dir}/{session_id[:8]}")
            elif status.startswith("appended") or status.startswith("rotation"):
                print(f"  [{ts_now}] [openclaw {status.split('(')[0]}] {agent_dir}/{session_id[:8]}")
            did_work = did_work or status not in ("up_to_date", "empty_append")
        else:
            prior_offset = load_checkpoint().get(sf, {}).get("offset", 0)
            dest, status = None, "pending_retry"
            ts_now = datetime.now(UTC).strftime("%H:%M:%S")

        delivery = deliver_openclaw_native_events(sf, prior_offset, status)
        if delivery["attempted"] or delivery["errors"]:
            statuses = ",".join(r.get("status", "") for r in delivery.get("responses", [])[:3]) or "-"
            print(f"  [{ts_now}] [entry] delivered={delivery['delivered']} statuses={statuses} errors={len(delivery['errors'])}")
            did_work = True

        if changed and dest and status not in ("up_to_date", "empty_append"):
            try:
                pn, cn, en = incremental_extract_session(dest)
                if pn or cn or en:
                    print(f"  [{ts_now}] [p2] pref={pn} case={cn} error={en}")
            except Exception as e:
                print(f"  [{ts_now}] [p2 error] {e}")
    return did_work


def _run_codex_sync_once(args, signature_cache=None, force=False):
    if not _source_enabled(args, "codex"):
        return False
    initial_signature_pass = signature_cache is not None and "codex" not in signature_cache
    if not force and signature_cache is not None:
        codex_sig = _codex_session_signatures()
        if codex_sig is not None and not _signature_changed(signature_cache, "codex", codex_sig):
            return False
    did_work = False
    try:
        from codex_local_connector import (
            catch_up_latest_sessions,
            status_scan_limit,
            watch_scan_limit,
        )
        scan_limit = watch_scan_limit()
        if initial_signature_pass:
            scan_limit = max(scan_limit, status_scan_limit())
        catchup = catch_up_latest_sessions(limit=scan_limit)
        ts_now = datetime.now(UTC).strftime("%H:%M:%S")
        for item in catchup.get("items", []):
            status = item.get("status", "")
            if not status.startswith(("archived", "appended", "generation_started", "rotation")):
                continue
            did_work = True
            print(f"  [{ts_now}] [codex {status.split('(')[0]}] {item.get('canonical_window_id','')}/{item.get('session_id','')[:8]}")
            try:
                pn, cn, en = incremental_extract_session(item["dest"])
                if pn or cn or en:
                    print(f"  [{ts_now}] [p2 codex] pref={pn} case={cn} error={en}")
            except Exception as e:
                print(f"  [{ts_now}] [p2 codex error] {e}")
        raw_sync = catchup.get("raw_sync", {}) if isinstance(catchup.get("raw_sync"), dict) else {}
        if catchup.get("changed") or raw_sync.get("missing_or_stale_count"):
            did_work = did_work or bool(catchup.get("changed"))
            lag_bytes = raw_sync.get("raw_archive_total_lag_bytes", 0)
            lag_ms = raw_sync.get("raw_archive_max_lag_milliseconds", 0)
            status = raw_sync.get("status", "")
            print(
                f"  [{ts_now}] [codex catchup] status={status} passes={catchup.get('passes')} "
                f"changed={catchup.get('changed')} lag_bytes={lag_bytes} lag_ms={lag_ms}"
            )
    except Exception as e:
        ts_now = datetime.now(UTC).strftime("%H:%M:%S")
        print(f"  [{ts_now}] [codex scan error] {e}")
    return did_work


def _run_codex_event_sync_once(args, event_paths):
    if not _source_enabled(args, "codex"):
        return {
            "handled_sources": set(),
            "work_sources": set(),
            "handled_paths": 0,
            "changed_paths": 0,
        }
    try:
        from codex_local_connector import (
            _register_current_window_for_artifact,
            archive_session_incremental,
            artifact_from_path,
            codex_sessions_root,
        )
    except Exception:
        return {
            "handled_sources": set(),
            "work_sources": set(),
            "handled_paths": 0,
            "changed_paths": 0,
        }

    root = codex_sessions_root()
    if not root.exists():
        return {
            "handled_sources": set(),
            "work_sources": set(),
            "handled_paths": 0,
            "changed_paths": 0,
        }

    try:
        root_resolved = root.resolve()
    except OSError:
        root_resolved = root

    seen_paths = set()
    handled_paths = 0
    changed_paths = 0
    index_artifacts = []
    processed_signatures = {}
    current_window_registered = False
    ts_now = datetime.now(UTC).strftime("%H:%M:%S")

    for raw_path in event_paths or []:
        candidate = Path(str(raw_path or "")).expanduser()
        if candidate.suffix.lower() != ".jsonl" or ".checkpoint." in candidate.name:
            continue
        try:
            resolved = candidate.resolve()
        except OSError:
            resolved = candidate
        try:
            resolved.relative_to(root_resolved)
        except ValueError:
            continue
        path_key = str(resolved)
        if path_key in seen_paths:
            continue
        seen_paths.add(path_key)
        handled_paths += 1
        if not resolved.exists() or not resolved.is_file():
            continue

        try:
            artifact = artifact_from_path(resolved)
            dest, status = archive_session_incremental(str(resolved), dry_run=False, artifact=artifact)
        except Exception as exc:
            print(f"  [{ts_now}] [codex event error] {type(exc).__name__}:{str(exc)[:160]}")
            continue

        processed_signature = _file_signature(resolved)
        fail_closed = status.startswith("source_divergence_generation_fail_closed")
        if (
            not fail_closed
            and _codex_archive_covers_source_signature(dest, processed_signature)
        ):
            processed_signatures[str(resolved)] = processed_signature

        changed_status = status.startswith((
            "archived",
            "appended",
            "generation_started",
            "rotation",
            "rebuilt",
        ))
        metadata_only = status.startswith("metadata_updated")
        terminal_attention = status.startswith((
            "source_regression_raw_retained",
            "source_divergence_raw_retained",
            "source_divergence_generation_fail_closed",
        ))
        if changed_status or metadata_only or terminal_attention:
            print(
                f"  [{ts_now}] [codex event {status.split('(')[0]}] "
                f"{artifact.get('canonical_window_id', '')}/{artifact.get('session_id', '')[:8]}"
            )
        if changed_status or metadata_only:
            index_artifacts.append(artifact)
        if (changed_status or metadata_only) and not current_window_registered:
            try:
                binding = _register_current_window_for_artifact(artifact, dest)
                current_window_registered = bool(binding.get("ok")) if isinstance(binding, dict) else False
            except Exception:
                current_window_registered = False
        if not changed_status:
            continue

        changed_paths += 1
        try:
            pn, cn, en = incremental_extract_session(dest)
            if pn or cn or en:
                print(f"  [{ts_now}] [p2 codex] pref={pn} case={cn} error={en}")
        except Exception as exc:
            print(f"  [{ts_now}] [p2 codex error] {exc}")

    handled_sources = {"codex"} if handled_paths else set()
    work_sources = {"codex"} if changed_paths else set()
    return {
        "handled_sources": handled_sources,
        "work_sources": work_sources,
        "handled_paths": handled_paths,
        "changed_paths": changed_paths,
        "index_artifacts": index_artifacts,
        "processed_signatures": processed_signatures,
    }


def _run_event_driven_sync_once(args, event_paths):
    handled_sources = set()
    work_sources = set()
    index_artifacts = {}
    codex_result = _measure_watcher_phase_io(
        "codex_event_archive",
        _run_codex_event_sync_once,
        args,
        event_paths,
    )
    handled_sources.update(codex_result.get("handled_sources") or ())
    work_sources.update(codex_result.get("work_sources") or ())
    if codex_result.get("index_artifacts"):
        index_artifacts["codex"] = codex_result["index_artifacts"]
    _emit_raw_archive_diagnostics()
    _emit_watcher_phase_io_diagnostics()
    return {
        "handled_sources": handled_sources,
        "work_sources": work_sources,
        "index_artifacts": index_artifacts,
        "codex": codex_result,
    }


def _run_claude_code_sync_once(args, signature_cache=None, force=False):
    if not _source_enabled(args, "claude_code_cli"):
        return False
    if not force and signature_cache is not None:
        claude_code_sig = _claude_code_session_signatures()
        if claude_code_sig is not None and not _signature_changed(signature_cache, "claude_code_cli", claude_code_sig):
            return False
    did_work = False
    try:
        from claude_code_local_connector import scan_sessions as scan_claude_code_sessions
        result = scan_claude_code_sessions(dry_run=False)
        ts_now = datetime.now(UTC).strftime("%H:%M:%S")
        for item in result.get("items", []):
            status = item.get("status", "")
            if not status.startswith(("archived", "appended", "generation_started", "rotation", "metadata_updated")):
                continue
            did_work = True
            print(f"  [{ts_now}] [claude_code_cli {status.split('(')[0]}] {item.get('canonical_window_id','')}/{item.get('session_id','')[:8]}")
            if status.startswith("metadata_updated"):
                continue
            try:
                pn, cn, en = incremental_extract_session(item["dest"])
                if pn or cn or en:
                    print(f"  [{ts_now}] [p2 claude_code_cli] pref={pn} case={cn} error={en}")
            except Exception as e:
                print(f"  [{ts_now}] [p2 claude_code_cli error] {e}")
    except Exception as e:
        ts_now = datetime.now(UTC).strftime("%H:%M:%S")
        print(f"  [{ts_now}] [claude_code_cli scan error] {e}")
    return did_work


def _run_claude_desktop_sync_once(args, signature_cache=None, force=False):
    if not _source_enabled(args, "claude_desktop") or not claude_desktop_raw_ingest_enabled():
        return False
    refresh_signature_paths_after_scan = False
    if not force and signature_cache is not None:
        initial_signature_pass = "claude_desktop" not in signature_cache
        claude_sig = _claude_desktop_store_signatures()
        if claude_sig is not None and not _signature_changed(signature_cache, "claude_desktop", claude_sig):
            return False
        refresh_signature_paths_after_scan = not initial_signature_pass
    ts_now = datetime.now(UTC).strftime("%H:%M:%S")
    result = scan_claude_desktop_raw(
        dry_run=False,
        limit=getattr(args, "claude_desktop_limit", None),
    )
    if result.get("ok"):
        if refresh_signature_paths_after_scan:
            refreshed_signature = _claude_desktop_store_signatures(force_refresh=True)
            if refreshed_signature is not None:
                signature_cache["claude_desktop"] = refreshed_signature
        raw_write = result.get("raw_write", {}) if isinstance(result.get("raw_write"), dict) else {}
        records = int(raw_write.get("records_written", 0) or 0)
        candidates = int(result.get("candidate_count", 0) or 0)
        if records or candidates:
            print(f"  [{ts_now}] [claude_desktop raw] candidates={candidates} records={records}")
        return bool(records)
    print(f"  [{ts_now}] [claude_desktop raw error] {result.get('error') or result}")
    return False


def _run_kiro_sync_once(args, signature_cache=None, force=False):
    if not _source_enabled(args, "kiro"):
        return False
    if not force and signature_cache is not None:
        kiro_sig = _kiro_session_signatures()
        if kiro_sig is not None and not _signature_changed(signature_cache, "kiro", kiro_sig):
            return False
    did_work = False
    try:
        from kiro_local_connector import scan_sessions as scan_kiro_sessions
        result = scan_kiro_sessions(dry_run=False)
        ts_now = datetime.now(UTC).strftime("%H:%M:%S")
        for item in result.get("items", []):
            status = item.get("status", "")
            if not status.startswith(("archived", "appended")):
                continue
            did_work = True
            print(f"  [{ts_now}] [kiro {status.split('(')[0]}] {item.get('canonical_window_id','')}/{item.get('session_id','')[:8]}")
            try:
                pn, cn, en = incremental_extract_session(item["dest"])
                if pn or cn or en:
                    print(f"  [{ts_now}] [p2 kiro] pref={pn} case={cn} error={en}")
            except Exception as e:
                print(f"  [{ts_now}] [p2 kiro error] {e}")
    except Exception as e:
        ts_now = datetime.now(UTC).strftime("%H:%M:%S")
        print(f"  [{ts_now}] [kiro scan error] {e}")
    return did_work


def _hermes_backfill_recommended(limit):
    try:
        from raw_record_guardian import hermes_backfill_recommendation
        result = hermes_backfill_recommendation(limit=limit)
    except Exception:
        return False
    try:
        return int(result.get("recommended_count", 0) or 0) > 0
    except Exception:
        return False


def _run_hermes_sync_once(args, signature_cache=None, force=False, retry_pending=False):
    if not _source_enabled(args, "hermes") or not hermes_raw_backfill_enabled():
        return False
    limit = hermes_raw_backfill_limit()
    if not force and signature_cache is not None:
        hermes_sig = _hermes_state_db_signatures()
        if hermes_sig is not None and not _signature_changed(signature_cache, "hermes_state_db", hermes_sig):
            if not retry_pending or not _hermes_backfill_recommended(limit):
                return False
    ts_now = datetime.now(UTC).strftime("%H:%M:%S")
    try:
        from raw_record_guardian import run_raw_backfill
        result = run_raw_backfill(
            limit=limit,
            source_systems=["hermes"],
        )
    except Exception as exc:
        print(f"  [{ts_now}] [hermes raw error] {type(exc).__name__}:{str(exc)[:160]}")
        return False
    hermes_result = next(
        (
            item for item in result.get("results", [])
            if item.get("source_system") == "hermes"
        ),
        {},
    )
    changed = int(hermes_result.get("changed", 0) or 0)
    if result.get("ok") and changed:
        raw_sync = hermes_result.get("raw_sync", {}) if isinstance(hermes_result.get("raw_sync"), dict) else {}
        print(
            f"  [{ts_now}] [hermes raw] changed={changed} "
            f"items={raw_sync.get('items_checked', 0)} status={raw_sync.get('status', '')}"
        )
        return True
    if not result.get("ok"):
        print(f"  [{ts_now}] [hermes raw error] {hermes_result.get('error') or result}")
    return False


def _run_sync_once(args, signature_cache=None, state=None, force=False, retry_pending=False, skip_sources=None):
    state = state if isinstance(state, dict) else {}
    skipped = {
        str(source or "").strip().lower()
        for source in (skip_sources or ())
        if str(source or "").strip()
    }
    did_work = False
    if "openclaw" not in skipped:
        did_work = _measure_watcher_phase_io(
            "openclaw_sync",
            _run_openclaw_sync_once,
            args,
            signature_cache=signature_cache,
            force=force,
            retry_pending=retry_pending,
        ) or did_work
    if "codex" not in skipped:
        did_work = _measure_watcher_phase_io(
            "codex_fallback_sync",
            _run_codex_sync_once,
            args,
            signature_cache=signature_cache,
            force=force,
        ) or did_work
    if "claude_code_cli" not in skipped:
        did_work = _measure_watcher_phase_io(
            "claude_code_sync",
            _run_claude_code_sync_once,
            args,
            signature_cache=signature_cache,
            force=force,
        ) or did_work
    now = time.time()
    last_claude = float(state.get("last_claude_desktop_scan", 0.0) or 0.0)
    if "claude_desktop" not in skipped and (force or now - last_claude >= claude_desktop_raw_ingest_interval_seconds()):
        state["last_claude_desktop_scan"] = now
        did_work = _measure_watcher_phase_io(
            "claude_desktop_sync",
            _run_claude_desktop_sync_once,
            args,
            signature_cache=signature_cache,
            force=force,
        ) or did_work
    if "kiro" not in skipped:
        did_work = _measure_watcher_phase_io(
            "kiro_sync",
            _run_kiro_sync_once,
            args,
            signature_cache=signature_cache,
            force=force,
        ) or did_work
    hermes_retry_pending = False
    if retry_pending:
        last_hermes_recheck = float(state.get("last_hermes_backfill_recheck", 0.0) or 0.0)
        if (
            not last_hermes_recheck
            or now - last_hermes_recheck >= hermes_raw_backfill_recheck_interval_seconds()
        ):
            state["last_hermes_backfill_recheck"] = now
            hermes_retry_pending = True
    if "hermes" not in skipped:
        did_work = _measure_watcher_phase_io(
            "hermes_sync",
            _run_hermes_sync_once,
            args,
            signature_cache=signature_cache,
            force=force,
            retry_pending=hermes_retry_pending,
        ) or did_work
    now = time.time()
    last_index = float(state.get("last_canonical_record_index", 0.0) or 0.0)
    should_refresh_index = (
        canonical_index_enabled()
        and (
            force
            or did_work
            or now - last_index >= canonical_index_interval_seconds()
        )
    )
    if should_refresh_index:
        state["last_canonical_record_index"] = now
        refresh_kwargs = {
            "limit": canonical_index_limit(),
            "scan_mode": "fast",
        }
        source_systems = _canonical_index_source_systems(args)
        if source_systems is not None:
            refresh_kwargs["source_systems"] = source_systems
        _measure_watcher_phase_io(
            "periodic_canonical_index",
            _refresh_canonical_record_index,
            **refresh_kwargs,
        )
    _emit_raw_archive_diagnostics()
    _emit_watcher_phase_io_diagnostics()
    return did_work


def scan_claude_desktop_raw(dry_run=False, limit=None):
    """Run the authorized Claude Desktop local-store parser into Time Library raw.

    This writes only Time Library raw JSONL records. It never writes Claude
    Desktop config, native stores, cookies, tokens, MCP config, or skills.
    """
    if not claude_desktop_raw_ingest_enabled():
        return {
            "ok": True,
            "source_system": "claude_desktop",
            "status": "disabled",
            "reason": "claude_desktop_raw_ingest_explicitly_disabled",
            "write_performed": False,
            "platform_write_performed": False,
            "memory_write_performed": False,
        }
    try:
        from claude_desktop_connector import raw_ingest_dry_run, ingest_authorized_raw
    except Exception as exc:
        return {
            "ok": False,
            "source_system": "claude_desktop",
            "status": "error",
            "error": f"import_failed:{type(exc).__name__}:{str(exc)[:160]}",
            "write_performed": False,
            "platform_write_performed": False,
            "memory_write_performed": False,
        }

    body = {
        "limit": int(limit or claude_desktop_raw_ingest_limit()),
        "confirm_authorized_parser": True,
        "confirm_user_owns_claude_desktop_data": True,
    }
    try:
        if dry_run:
            result = raw_ingest_dry_run(body, public=True)
        else:
            body.update({
                "apply": True,
                "confirm_write_time_library_raw": True,
                "confirm_no_claude_platform_write": True,
            })
            result = ingest_authorized_raw(body, public=True)
    except Exception as exc:
        return {
            "ok": False,
            "source_system": "claude_desktop",
            "status": "error",
            "error": f"raw_ingest_failed:{type(exc).__name__}:{str(exc)[:160]}",
            "write_performed": False,
            "platform_write_performed": False,
            "memory_write_performed": False,
        }

    result["status"] = "dry_run" if dry_run else "ingested"
    result["authorized_by"] = claude_desktop_raw_ingest_authorized_by()
    result["platform_write_performed"] = False
    return result

# ─── alias_map ───────────────────────────────────────────────

def load_alias_map():
    if not os.path.exists(ALIAS_MAP_FILE):
        return {}
    with open(ALIAS_MAP_FILE, encoding="utf-8-sig") as f:
        data = json.load(f)
    m = {}
    for canon, info in data.get("canonical_windows", {}).items():
        for obs in info.get("observed_names", []):
            m[obs] = canon
    return m

def get_canonical(observed):
    static_map = load_alias_map()
    if observed in static_map:
        return static_map[observed]
    if observed.startswith("group-"):
        parts = observed.split("--")
        if len(parts) >= 2:
            return parts[-1]
    return observed

def _agent_session_from_path(src_path):
    src = Path(src_path)
    try:
        rel = src.resolve().relative_to(Path(OPENCLAW_ROOT).resolve())
        parts = rel.parts
        if len(parts) >= 3 and parts[1] == "sessions":
            agent_dir = parts[0]
        else:
            raise ValueError("unexpected OpenClaw session path")
    except Exception:
        normalized = str(src_path).replace("\\", "/")
        agent_dir = normalized.split("/agents/")[1].split("/sessions")[0]
    session_id = os.path.basename(src_path).replace(".jsonl", "")
    return agent_dir, session_id

def _raw_dest_for_openclaw(canonical_window, session_id):
    return str(preferred_raw_archive_path(
        MEMCORE_ROOT,
        computer_name=HOSTNAME,
        source_system=SOURCE_SYSTEM,
        native_format=NATIVE_ARTIFACT_FORMAT,
        native_scope=canonical_window,
        session_id=session_id,
    ))

def _openclaw_event_message_text(event):
    message = event.get("message", {}) if isinstance(event, dict) else {}
    if not isinstance(message, dict):
        return ""
    content = message.get("content", [])
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts = []
    for item in content:
        if isinstance(item, dict) and item.get("type") in ("text", "input_text"):
            parts.append(str(item.get("text", "")))
    return "\n".join(parts)

def _is_openclaw_gateway_client_event(event):
    text = _openclaw_event_message_text(event).lstrip()
    if not text.startswith("Sender (untrusted metadata):"):
        return False
    head = text[:600]
    compact = head.replace(" ", "")
    return '"id":"gateway-client"' in compact or '"label":"gateway-client"' in compact

# ─── checkpoint ─────────────────────────────────────────────

def load_checkpoint():
    if not os.path.exists(CHECKPOINT_FILE):
        return {}
    try:
        with open(CHECKPOINT_FILE, encoding="utf-8-sig") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError, ValueError):
        _backup_corrupt_checkpoint(CHECKPOINT_FILE)
        return {}

def save_checkpoint(data):
    checkpoint_dir = os.path.dirname(CHECKPOINT_FILE)
    if checkpoint_dir:
        os.makedirs(checkpoint_dir, exist_ok=True)
    tmp = f"{CHECKPOINT_FILE}.{os.getpid()}.{time.monotonic_ns()}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        for attempt in range(20):
            try:
                os.replace(tmp, CHECKPOINT_FILE)
                return
            except PermissionError:
                if attempt == 19:
                    raise
                time.sleep(0.25)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass

def _backup_corrupt_checkpoint(path):
    if not os.path.exists(path):
        return ""
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    base = f"{path}.corrupt-backup-{stamp}-{os.getpid()}"
    backup = base
    suffix = 1
    while os.path.exists(backup):
        suffix += 1
        backup = f"{base}-{suffix}"
    try:
        shutil.move(path, backup)
    except OSError:
        return ""
    return backup

def _checkpoint_delivered_ids(src_path):
    entry = load_checkpoint().get(src_path, {})
    ids = entry.get(OPENCLAW_EVENT_DELIVERED_KEY, [])
    return set(ids if isinstance(ids, list) else [])

def _checkpoint_pending_events(src_path):
    entry = load_checkpoint().get(src_path, {})
    pending = entry.get(OPENCLAW_EVENT_PENDING_KEY, [])
    return pending if isinstance(pending, list) else []

def _mark_checkpoint_delivered(src_path, event_key):
    checkpoint = load_checkpoint()
    entry = checkpoint.get(src_path, {})
    ids = entry.get(OPENCLAW_EVENT_DELIVERED_KEY, [])
    if not isinstance(ids, list):
        ids = []
    if event_key not in ids:
        ids.append(event_key)
    entry[OPENCLAW_EVENT_DELIVERED_KEY] = ids[-500:]
    checkpoint[src_path] = entry
    save_checkpoint(checkpoint)

def _mark_checkpoint_pending(src_path, item, response=None, error=""):
    checkpoint = load_checkpoint()
    entry = checkpoint.get(src_path, {})
    pending = entry.get(OPENCLAW_EVENT_PENDING_KEY, [])
    if not isinstance(pending, list):
        pending = []
    response = response if isinstance(response, dict) else {}
    event_key = item.get("event_key", "")
    existing = next((p for p in pending if p.get("event_key") == event_key), {})
    record = {
        "event_key": event_key,
        "event_id": item.get("event_id", ""),
        "source_session_id": item.get("source_session_id", ""),
        "agent_id": item.get("agent_id", ""),
        "attempts": int(existing.get("attempts", 0) or 0) + 1,
        "last_status": response.get("status", ""),
        "last_chain": response.get("chain", ""),
        "last_reason": response.get("reason", ""),
        "last_error": error,
        "last_update": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    pending = [p for p in pending if p.get("event_key") != event_key]
    pending.append(record)
    entry[OPENCLAW_EVENT_PENDING_KEY] = pending[-500:]
    checkpoint[src_path] = entry
    save_checkpoint(checkpoint)

def _clear_checkpoint_pending(src_path, event_key):
    checkpoint = load_checkpoint()
    entry = checkpoint.get(src_path, {})
    pending = entry.get(OPENCLAW_EVENT_PENDING_KEY, [])
    if not isinstance(pending, list):
        return
    filtered = [p for p in pending if p.get("event_key") != event_key]
    if filtered:
        entry[OPENCLAW_EVENT_PENDING_KEY] = filtered[-500:]
    else:
        entry.pop(OPENCLAW_EVENT_PENDING_KEY, None)
    checkpoint[src_path] = entry
    save_checkpoint(checkpoint)

def _openclaw_event_delivery_terminal(response):
    response = response if isinstance(response, dict) else {}
    status = str(response.get("status", ""))
    if status in ("blocked", "error"):
        return False
    openclaw = response.get("openclaw", {})
    if response.get("chain") == "F3_zhiyi_direct" and isinstance(openclaw, dict):
        if openclaw and not openclaw.get("ok", False):
            return False
    platform_delivery = response.get("platform_delivery", {})
    if isinstance(platform_delivery, dict):
        if platform_delivery.get("executed") and not platform_delivery.get("openclaw_ok", False):
            return False
    return bool(status)

def _iter_pending_openclaw_user_events(src_path):
    pending = _checkpoint_pending_events(src_path)
    if not pending:
        return []
    wanted = {p.get("event_id"): p for p in pending if p.get("event_id")}
    if not wanted:
        return []
    found = {}
    try:
        with open(src_path, "rb") as f:
            for raw_line in f:
                if not raw_line.strip():
                    continue
                try:
                    event = json.loads(raw_line.decode("utf-8"))
                except Exception:
                    continue
                event_id = str(event.get("id") or "")
                if event_id not in wanted:
                    continue
                message = event.get("message", {})
                if not isinstance(message, dict) or message.get("role") != "user":
                    continue
                if _is_openclaw_gateway_client_event(event):
                    continue
                pending_item = wanted[event_id]
                found[event_id] = {
                    "event_key": pending_item.get("event_key", ""),
                    "event_id": event_id,
                    "event": event,
                    "agent_id": pending_item.get("agent_id", ""),
                    "source_session_id": pending_item.get("source_session_id", ""),
                    "retry_pending": True,
                }
    except OSError:
        return []
    return [found[p.get("event_id")] for p in pending if p.get("event_id") in found]

def _iter_openclaw_user_events(src_path, prior_offset=0, status="", now=None):
    if status in ("up_to_date", "empty_append") or not status:
        return []
    if ".trajectory." in os.path.basename(src_path):
        return []

    try:
        src_stat = os.stat(src_path)
    except OSError:
        return []

    start_offset = max(0, int(prior_offset or 0))
    if start_offset == 0 and status == "archived":
        current_ts = time.time() if now is None else now
        if current_ts - src_stat.st_mtime > OPENCLAW_EVENT_FRESH_ARCHIVE_SECONDS:
            return []

    agent_dir, session_id = _agent_session_from_path(src_path)
    only_latest_user = start_offset == 0 and (status == "archived" or status.startswith("rotation"))
    events = []
    with open(src_path, "rb") as f:
        if start_offset and start_offset <= src_stat.st_size:
            f.seek(start_offset)
        else:
            start_offset = 0
        cursor = start_offset
        for raw_line in f:
            line_offset = cursor
            cursor += len(raw_line)
            if not raw_line.strip():
                continue
            try:
                event = json.loads(raw_line.decode("utf-8"))
            except Exception:
                continue
            if event.get("type") != "message":
                continue
            message = event.get("message", {})
            if not isinstance(message, dict) or message.get("role") != "user":
                continue
            if _is_openclaw_gateway_client_event(event):
                continue
            event_id = str(event.get("id") or f"{session_id}:{line_offset}")
            events.append({
                "event_key": f"{session_id}:{event_id}",
                "event_id": event_id,
                "event": event,
                "agent_id": agent_dir,
                "source_session_id": session_id,
            })
    if only_latest_user and events:
        return events[-1:]
    return events

def deliver_openclaw_native_events(
    src_path,
    prior_offset=0,
    status="",
    url=None,
    timeout=OPENCLAW_EVENT_DELIVERY_TIMEOUT,
    now=None,
):
    """Send newly appended OpenClaw user message events to the 9860 native entry."""
    url = url or DIALOG_ENTRY_OPENCLAW_EVENT_URL
    delivered_ids = _checkpoint_delivered_ids(src_path)
    result = {
        "attempted": 0,
        "delivered": 0,
        "pending": 0,
        "retried_pending": 0,
        "skipped_duplicate": 0,
        "responses": [],
        "errors": [],
    }
    items = []
    seen = set()
    for item in _iter_pending_openclaw_user_events(src_path):
        if item["event_key"] not in seen:
            items.append(item)
            seen.add(item["event_key"])
    for item in _iter_openclaw_user_events(src_path, prior_offset, status, now=now):
        if item["event_key"] not in seen:
            items.append(item)
            seen.add(item["event_key"])
    for item in items:
        event_key = item["event_key"]
        if event_key in delivered_ids:
            _clear_checkpoint_pending(src_path, event_key)
            result["skipped_duplicate"] += 1
            continue
        payload = {
            "event": item["event"],
            "event_id": item["event_id"],
            "source_session_id": item["source_session_id"],
            "agent_id": item["agent_id"],
            "platform_delivery": {
                "enabled": True,
                "authorized": True,
                "platform": "openclaw",
                "delivery_runtime_kind": "ws_rpc_forward",
                "session_binding": "native_event",
                "mode": "same_chat",
                "idempotency_key": f"memcore-openclaw-event-{item['event_id']}",
            },
        }
        result["attempted"] += 1
        if item.get("retry_pending"):
            result["retried_pending"] += 1
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read()
                http_status = getattr(resp, "status", None) or getattr(resp, "code", None)
            try:
                response = json.loads(body.decode("utf-8"))
            except Exception:
                response = {}
            terminal = _openclaw_event_delivery_terminal(response)
            result["responses"].append({
                "event_id": item["event_id"],
                "http_status": http_status,
                "status": response.get("status", ""),
                "chain": response.get("chain", ""),
                "reason": response.get("reason", ""),
                "openclaw_ok": response.get("openclaw", {}).get("ok") if isinstance(response.get("openclaw"), dict) else None,
                "terminal": terminal,
                "pending_retry": not terminal,
            })
            if terminal:
                _mark_checkpoint_delivered(src_path, event_key)
                _clear_checkpoint_pending(src_path, event_key)
                delivered_ids.add(event_key)
                result["delivered"] += 1
            else:
                _mark_checkpoint_pending(src_path, item, response=response)
                result["pending"] += 1
        except Exception as e:
            err = str(e)
            result["errors"].append(err)
            _mark_checkpoint_pending(src_path, item, error=err)
            result["pending"] += 1
    return result

# ─── sidecar metadata ─────────────────────────────────────

def _write_meta(dest, src_path, src_stat, offset, raw_order):
    """写 raw 文件的 sidecar metadata"""
    dest_meta = dest + ".meta.json"
    with open(src_path, "rb") as f:
        data = f.read()
    checksum = hex(sum(data) % (2**64))
    meta = {
        "source_path": src_path,
        "source_inode": src_stat.st_ino,
        "source_mtime": src_stat.st_mtime,
        "source_checksum": checksum,
        "file_offset": offset,
        "raw_order": raw_order,
        "archived_to": dest,
        "source_system": SOURCE_SYSTEM,
        "native_artifact_format": NATIVE_ARTIFACT_FORMAT,
        "raw_archive_layout": "computer_first",
        "last_update": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    with open(dest_meta, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    return dest_meta

# ─── archive one session ──────────────────────────────────

def archive_session_incremental(src_path, dry_run=False):
    """增量归档：只追加新行，不重复复制整个文件。

    checkpoint 记录每个 source 文件已处理的字节偏移、source inode/mtime，
    用于 rotation 检测；每次追加后写 .meta.json sidecar。
    """
    agent_dir, session_id = _agent_session_from_path(src_path)
    canonical_window = get_canonical(agent_dir)
    dest = _raw_dest_for_openclaw(canonical_window, session_id)

    checkpoint = load_checkpoint()
    prior = checkpoint.get(src_path, {})
    last_offset = prior.get("offset", 0)

    if dry_run:
        src_size = os.path.getsize(src_path)
        return dest, f"dry_run(offset={last_offset}/{src_size})"

    try:
        src_stat = os.stat(src_path)
        src_size = src_stat.st_size
        src_inode = src_stat.st_ino
        src_mtime = src_stat.st_mtime
    except OSError:
        return dest, "error: cannot stat source"

    # 判断是否有新内容，或文件被轮换（inode 变化）
    is_rotation = prior and prior.get("source_inode") != src_inode

    if src_size <= last_offset and not is_rotation:
        # 没有新内容，且文件未被替换
        return dest, f"up_to_date(offset={last_offset})"

    if is_rotation:
        # 文件轮换（truncate/rotation），从头开始
        last_offset = 0
        raw_order = prior.get("raw_order", 0) + 1
        msg = f"rotation_detected(inode changed, {raw_order}th archive)"
    else:
        # 读取新增内容
        with open(src_path, "rb") as f:
            f.seek(last_offset)
            new_bytes = f.read()
            new_offset = f.tell()

        if not new_bytes.strip():
            return dest, f"empty_append(offset={new_offset})"

        # 追加写入目标
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "ab") as f:
            f.write(new_bytes)

        # 部分 checksum（仅新增部分）
        checksum = hex(sum(new_bytes) % (2**64))
        new_lines = new_bytes.count(b"\n")
        msg = f"appended({new_lines} lines, {len(new_bytes)} bytes, {last_offset}→{new_offset})"
        last_offset = new_offset
        raw_order = prior.get("raw_order", 0)

    delivered_ids = prior.get(OPENCLAW_EVENT_DELIVERED_KEY, [])
    pending_events = prior.get(OPENCLAW_EVENT_PENDING_KEY, [])
    # 更新 checkpoint（含 source inode/mtime 用于 rotation 检测）
    entry = {
        "offset": last_offset,
        "archived_to": dest,
        "source_inode": src_inode,
        "source_size": src_stat.st_size,
        "source_mtime": src_mtime,
        "source_checksum": checksum if not is_rotation else None,
        "raw_order": raw_order,
        "last_update": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if isinstance(delivered_ids, list):
        entry[OPENCLAW_EVENT_DELIVERED_KEY] = delivered_ids[-500:]
    if isinstance(pending_events, list):
        entry[OPENCLAW_EVENT_PENDING_KEY] = pending_events[-500:]
    checkpoint[src_path] = entry
    save_checkpoint(checkpoint)

    # 写 sidecar metadata
    _write_meta(dest, src_path, src_stat, last_offset, raw_order)

    return dest, msg


def archive_session(src_path, dry_run=False):
    """兼容旧接口：首次全量归档（copy），后续增量追加。"""
    agent_dir, session_id = _agent_session_from_path(src_path)
    canonical_window = get_canonical(agent_dir)
    dest = _raw_dest_for_openclaw(canonical_window, session_id)

    if os.path.exists(dest):
        # 已有完整副本，走增量追加
        return archive_session_incremental(src_path, dry_run=dry_run)

    # 首次全量 copy（不用 hardlink）
    if dry_run:
        return dest, "dry_run"
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    shutil.copy2(src_path, dest)

    # 初始化 checkpoint（含 source inode/mtime）
    src_stat = os.stat(src_path)
    checkpoint = load_checkpoint()
    prior = checkpoint.get(src_path, {})
    delivered_ids = prior.get(OPENCLAW_EVENT_DELIVERED_KEY, [])
    pending_events = prior.get(OPENCLAW_EVENT_PENDING_KEY, [])
    raw_order = 1
    entry = {
        "offset": src_stat.st_size,
        "archived_to": dest,
        "source_inode": src_stat.st_ino,
        "source_mtime": src_stat.st_mtime,
        "source_checksum": None,
        "raw_order": raw_order,
        "last_update": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if isinstance(delivered_ids, list):
        entry[OPENCLAW_EVENT_DELIVERED_KEY] = delivered_ids[-500:]
    if isinstance(pending_events, list):
        entry[OPENCLAW_EVENT_PENDING_KEY] = pending_events[-500:]
    checkpoint[src_path] = entry
    save_checkpoint(checkpoint)

    # 写 sidecar metadata
    _write_meta(dest, src_path, src_stat, src_stat.st_size, raw_order)

    return dest, "archived"

# ─── batch scan ────────────────────────────────────────────

def _source_enabled(args, source_system):
    wanted = getattr(args, "source", "all") or "all"
    return wanted in ("all", source_system)


def canonical_index_enabled() -> bool:
    value = os.environ.get("MEMCORE_CANONICAL_RECORD_INDEX_ENABLED", "1").strip().lower()
    return value not in {"0", "false", "no", "off"}


def canonical_index_interval_seconds() -> float:
    raw_ms = os.environ.get("MEMCORE_CANONICAL_RECORD_INDEX_INTERVAL_MS")
    if raw_ms is not None:
        try:
            return max(0.25, min(float(raw_ms) / 1000.0, 3600.0))
        except Exception:
            return DEFAULT_CANONICAL_INDEX_INTERVAL_SECONDS
    raw_seconds = os.environ.get("MEMCORE_CANONICAL_RECORD_INDEX_INTERVAL_SECONDS")
    try:
        return max(
            0.25,
            min(
                float(
                    raw_seconds
                    if raw_seconds is not None
                    else DEFAULT_CANONICAL_INDEX_INTERVAL_SECONDS
                ),
                3600.0,
            ),
        )
    except Exception:
        return DEFAULT_CANONICAL_INDEX_INTERVAL_SECONDS


def canonical_index_limit() -> int:
    raw = os.environ.get("MEMCORE_CANONICAL_RECORD_INDEX_LIMIT")
    try:
        return max(1, min(int(raw if raw is not None else 20), 500))
    except Exception:
        return 20


def _canonical_index_source_systems(args):
    source = str(getattr(args, "source", "") or "").strip().lower()
    if not source or source == "all":
        return None
    allowed = {"openclaw", "codex", "claude_code_cli", "claude_desktop", "kiro", "hermes"}
    if source not in allowed:
        return None
    return [source]


def _canonical_index_refresh_due(
    *,
    db_path=None,
    source_systems=None,
    include_internal_targets=False,
):
    try:
        from raw_record_canonical_index import canonical_index_refresh_due
    except ImportError:  # pragma: no cover
        from src.raw_record_canonical_index import canonical_index_refresh_due
    return canonical_index_refresh_due(
        db_path=db_path,
        source_systems=source_systems,
        include_internal_targets=include_internal_targets,
    )


def _refresh_canonical_record_index(
    *,
    limit=None,
    scan_mode="fast",
    quiet=False,
    source_systems=None,
    connector_artifacts=None,
):
    if not canonical_index_enabled():
        return {"ok": True, "disabled": True, "write_performed": False}
    try:
        targeted_refresh = connector_artifacts is not None
        targeted_count = sum(
            len(items) for items in (connector_artifacts or {}).values()
            if isinstance(items, (list, tuple))
        )
        refresh_due = (
            {
                "refresh_needed": targeted_count > 0,
                "reason": "targeted_source_event",
                "tracked_records": targeted_count,
                "changed_records": targeted_count,
            }
            if targeted_refresh
            else _canonical_index_refresh_due(
                source_systems=source_systems,
                include_internal_targets=True,
            )
        )
        public_refresh_due = {
            key: value for key, value in refresh_due.items()
            if not str(key).startswith("_internal_")
        }
        if not refresh_due.get("refresh_needed"):
            index_update = {
                "records_upserted": 0,
                "records_skipped_unchanged": int(refresh_due.get("tracked_records", 0) or 0),
                "canonical_messages_upserted": 0,
                "canonical_chunks_upserted": 0,
                "reason": refresh_due.get("reason", "tracked_sources_unchanged"),
            }
            if not quiet:
                ts_now = datetime.now(UTC).strftime("%H:%M:%S")
                print(
                    f"  [{ts_now}] [canonical index] records=0 messages=0 chunks=0 "
                    f"skipped={index_update.get('records_skipped_unchanged', 0)} "
                    f"reason={index_update.get('reason', '')}"
                )
            return {
                "ok": True,
                "contract": refresh_due.get("contract"),
                "refresh_skipped": True,
                "refresh_due": public_refresh_due,
                "index_update": index_update,
                "write_performed": False,
            }
        changed_record_ids = refresh_due.get("_internal_changed_record_ids")
        if (
            not targeted_refresh
            and refresh_due.get("reason") == "tracked_source_stat_changed"
            and isinstance(changed_record_ids, list)
            and changed_record_ids
        ):
            try:
                from canonical_index_delta_refresh import refresh_changed_records_index
            except ImportError:  # pragma: no cover
                from src.canonical_index_delta_refresh import refresh_changed_records_index
            index_update = refresh_changed_records_index(changed_record_ids)
            if not quiet:
                ts_now = datetime.now(UTC).strftime("%H:%M:%S")
                print(
                    f"  [{ts_now}] [canonical index] records={index_update.get('records_upserted', 0)} "
                    f"messages={index_update.get('canonical_messages_upserted', 0)} "
                    f"chunks={index_update.get('canonical_chunks_upserted', 0)} "
                    f"skipped={index_update.get('records_skipped_unchanged', 0)} "
                    "mode=tracked_delta"
                )
            return {
                "ok": bool(index_update.get("ok", True)),
                "contract": refresh_due.get("contract"),
                "refresh_due": public_refresh_due,
                "index_update": index_update,
                "write_performed": bool(index_update.get("write_performed")),
            }
        from raw_record_guardian import build_guardian_status
        refresh_limit = int(limit or canonical_index_limit())
        if source_systems and not targeted_refresh:
            refresh_limit = max(
                refresh_limit,
                int(refresh_due.get("tracked_records", 0) or 0),
            )
        guardian_kwargs = {
            "limit": refresh_limit,
            "include_gaps": False,
            "scan_mode": scan_mode,
            "write_index": True,
            "compact": False,
            "public": True,
            "source_systems": source_systems,
        }
        if targeted_refresh:
            guardian_kwargs["connector_artifacts"] = connector_artifacts
        report = build_guardian_status(
            **guardian_kwargs,
        )
        index_update = report.get("index_update", {}) if isinstance(report.get("index_update"), dict) else {}
        if not quiet:
            ts_now = datetime.now(UTC).strftime("%H:%M:%S")
            print(
                f"  [{ts_now}] [canonical index] records={index_update.get('records_upserted', 0)} "
                f"messages={index_update.get('canonical_messages_upserted', 0)} "
                f"chunks={index_update.get('canonical_chunks_upserted', 0)} "
                f"skipped={index_update.get('records_skipped_unchanged', 0)}"
            )
        return report
    except Exception as exc:
        if not quiet:
            ts_now = datetime.now(UTC).strftime("%H:%M:%S")
            print(f"  [{ts_now}] [canonical index error] {type(exc).__name__}:{str(exc)[:160]}")
        return {
            "ok": False,
            "error": f"{type(exc).__name__}:{str(exc)[:160]}",
            "write_performed": False,
        }

def cmd_scan(args):
    total_archived = 0
    if _source_enabled(args, "openclaw"):
        os.makedirs(OPENCLAW_ROOT, exist_ok=True)
        for agent_dir in sorted(os.listdir(OPENCLAW_ROOT)):
            sessions_dir = os.path.join(OPENCLAW_ROOT, agent_dir, "sessions")
            if not os.path.isdir(sessions_dir):
                continue
            for sf in sorted(glob.glob(os.path.join(sessions_dir, "*.jsonl"))):
                session_id = os.path.basename(sf).replace(".jsonl", "")
                if ".checkpoint." in session_id:
                    continue
                dest, status = archive_session(sf, dry_run=args.dry_run)
                if status == "archived":
                    total_archived += 1
                    print(f"  [openclaw archived] {agent_dir} → {get_canonical(agent_dir)}/{session_id[:8]}")
                elif status == "exists":
                    pass
                if not args.dry_run and dest and status not in ("up_to_date", "empty_append"):
                    try:
                        pn, cn, en = incremental_extract_session(dest)
                        if pn or cn or en:
                            print(f"  [p2] pref={pn} case={cn} error={en}")
                    except Exception as e:
                        print(f"  [p2 error] {e}")

    if _source_enabled(args, "codex"):
        try:
            from codex_local_connector import scan_sessions as scan_codex_sessions
            result = scan_codex_sessions(dry_run=args.dry_run)
            if args.dry_run:
                total_archived += int(result.get("would_change", 0) or 0)
            for item in result.get("items", []):
                status = item.get("status", "")
                if status.startswith(("archived", "appended", "generation_started", "rotation")):
                    total_archived += 1
                    print(f"  [codex {status.split('(')[0]}] {item.get('canonical_window_id','')}/{item.get('session_id','')[:8]}")
                    if not args.dry_run:
                        try:
                            pn, cn, en = incremental_extract_session(item["dest"])
                            if pn or cn or en:
                                print(f"  [p2 codex] pref={pn} case={cn} error={en}")
                        except Exception as e:
                            print(f"  [p2 codex error] {e}")
        except Exception as e:
            print(f"  [codex scan error] {e}")

    if _source_enabled(args, "claude_code_cli"):
        try:
            from claude_code_local_connector import scan_sessions as scan_claude_code_sessions
            result = scan_claude_code_sessions(dry_run=args.dry_run)
            if args.dry_run:
                total_archived += int(result.get("would_change", 0) or 0)
            for item in result.get("items", []):
                status = item.get("status", "")
                if status.startswith(("archived", "appended", "generation_started", "rotation", "metadata_updated")):
                    total_archived += 1
                    print(f"  [claude_code_cli {status.split('(')[0]}] {item.get('canonical_window_id','')}/{item.get('session_id','')[:8]}")
                    if not args.dry_run and not status.startswith("metadata_updated"):
                        try:
                            pn, cn, en = incremental_extract_session(item["dest"])
                            if pn or cn or en:
                                print(f"  [p2 claude_code_cli] pref={pn} case={cn} error={en}")
                        except Exception as e:
                            print(f"  [p2 claude_code_cli error] {e}")
        except Exception as e:
            print(f"  [claude_code_cli scan error] {e}")

    if _source_enabled(args, "claude_desktop"):
        result = scan_claude_desktop_raw(
            dry_run=args.dry_run,
            limit=getattr(args, "claude_desktop_limit", None),
        )
        if result.get("status") == "disabled":
            print(f"  [claude_desktop] disabled ({result.get('reason', '')})")
        elif result.get("ok"):
            raw_write = result.get("raw_write", {}) if isinstance(result.get("raw_write"), dict) else {}
            records = int(raw_write.get("records_written", 0) or 0)
            candidates = int(result.get("candidate_count", 0) or 0)
            total_archived += records if not args.dry_run else candidates
            verb = "would ingest" if args.dry_run else "ingested"
            print(f"  [claude_desktop {verb}] candidates={candidates} records={records}")
        else:
            print(f"  [claude_desktop scan error] {result.get('error') or result}")

    if _source_enabled(args, "kiro"):
        try:
            from kiro_local_connector import scan_sessions as scan_kiro_sessions
            result = scan_kiro_sessions(dry_run=args.dry_run)
            if args.dry_run:
                total_archived += int(result.get("would_change", 0) or 0)
            for item in result.get("items", []):
                status = item.get("status", "")
                if status.startswith(("archived", "appended")):
                    total_archived += 1
                    print(f"  [kiro {status.split('(')[0]}] {item.get('canonical_window_id','')}/{item.get('session_id','')[:8]}")
                    if not args.dry_run:
                        try:
                            pn, cn, en = incremental_extract_session(item["dest"])
                            if pn or cn or en:
                                print(f"  [p2 kiro] pref={pn} case={cn} error={en}")
                        except Exception as e:
                            print(f"  [p2 kiro error] {e}")
        except Exception as e:
            print(f"  [kiro scan error] {e}")

    if _source_enabled(args, "hermes"):
        if args.dry_run:
            try:
                from raw_record_guardian import build_guardian_status
                report = build_guardian_status(
                    limit=hermes_raw_backfill_limit(),
                    include_gaps=False,
                    scan_mode="fast",
                    public=True,
                )
                recommended = len([
                    item for item in report.get("records", [])
                    if item.get("source_system") == "hermes" and item.get("backfill_recommended")
                ])
                total_archived += recommended
                print(f"  [hermes dry-run] would backfill {recommended} sessions")
            except Exception as e:
                print(f"  [hermes scan error] {e}")
        else:
            did_work = _run_hermes_sync_once(args, signature_cache=None, force=True)
            if did_work:
                total_archived += 1

    if args.dry_run:
        print(f"[scan dry-run] source={getattr(args, 'source', 'all')} would archive/update {total_archived} sessions")
    else:
        print(f"[scan] source={getattr(args, 'source', 'all')} archived/updated {total_archived} sessions")
        refresh_kwargs = {
            "limit": canonical_index_limit(),
            "scan_mode": "fast",
        }
        source_systems = _canonical_index_source_systems(args)
        if source_systems is not None:
            refresh_kwargs["source_systems"] = source_systems
        _refresh_canonical_record_index(**refresh_kwargs)

# ─── continuous watcher ───────────────────────────────────

def watch_file_events(args):
    """Prefer OS file events, with periodic low-latency fallback ticks."""
    try:
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer
    except Exception as exc:
        print(f"[memcore-cloud] file events unavailable: {type(exc).__name__}:{str(exc)[:120]}")
        return None

    roots = _watch_root_candidates(args)
    if not roots:
        print("[memcore-cloud] no watchable source roots found for event backend")
        return None

    event_queue = queue.Queue()

    class MemcoreEventHandler(FileSystemEventHandler):
        def on_any_event(self, event):
            if _watch_event_relevant(event):
                try:
                    event_queue.put_nowait(
                        (
                            time.time(),
                            getattr(event, "event_type", ""),
                            getattr(event, "src_path", ""),
                            getattr(event, "dest_path", ""),
                        )
                    )
                except Exception:
                    pass

    observer = Observer()
    scheduled = []
    handler = MemcoreEventHandler()
    for source, root in roots:
        try:
            observer.schedule(handler, str(root), recursive=True)
            scheduled.append((source, root))
        except Exception as exc:
            print(f"[memcore-cloud] watch skipped: source={source} root={root} error={type(exc).__name__}:{str(exc)[:100]}")

    if not scheduled:
        return None

    backend = getattr(Observer, "__module__", "watchdog.observers")
    poll_interval = watcher_poll_interval_seconds()
    poll_interval_ms = watcher_poll_interval_milliseconds()
    signature_cache = {}
    state = {}
    last_pending_retry = 0.0
    print(
        f"[memcore-cloud] file-event watch mode: backend={backend} roots={len(scheduled)} "
        f"fallback_tick={poll_interval_ms}ms"
    )
    for source, root in scheduled[:12]:
        print(f"  [watch source] {source}: {root}")
    if len(scheduled) > 12:
        print(f"  [watch source] ... +{len(scheduled) - 12} more")

    # Initial pass catches records written before the observer starts.
    _run_sync_once(args, signature_cache=signature_cache, state=state, force=False, retry_pending=True)
    last_pending_retry = time.time()
    last_fallback_sync = time.monotonic()
    observer.start()
    try:
        while True:
            event_paths = []
            try:
                first_event = event_queue.get(timeout=poll_interval)
                event_paths.extend(_watch_event_paths(first_event))
                while True:
                    try:
                        event_paths.extend(_watch_event_paths(event_queue.get_nowait()))
                    except queue.Empty:
                        break
            except queue.Empty:
                pass

            now = time.time()
            retry_pending = now - last_pending_retry >= 5.0
            if retry_pending:
                last_pending_retry = now

            event_result = {"handled_sources": set(), "work_sources": set(), "index_artifacts": {}}
            if event_paths:
                event_result = _run_event_driven_sync_once(args, event_paths)
                _advance_codex_signature_cache_after_event(
                    signature_cache,
                    event_result.get("codex") or {},
                )
                if event_result.get("index_artifacts"):
                    state["last_canonical_record_index"] = now
                    _measure_watcher_phase_io(
                        "targeted_canonical_index",
                        _refresh_canonical_record_index,
                        limit=canonical_index_limit(),
                        scan_mode="fast",
                        source_systems=sorted(event_result.get("index_artifacts") or ()),
                        connector_artifacts=event_result.get("index_artifacts"),
                    )
            # Native events accelerate known paths. Reconciliation keeps its
            # own clock so a busy source cannot amplify one event stream into
            # full signature passes over every other platform.
            fallback_now = time.monotonic()
            if fallback_now - last_fallback_sync >= poll_interval:
                last_fallback_sync = fallback_now
                _run_sync_once(
                    args,
                    signature_cache=signature_cache,
                    state=state,
                    force=False,
                    retry_pending=retry_pending,
                    skip_sources=event_result.get("handled_sources") or (),
                )
    finally:
        observer.stop()
        observer.join()


def cmd_watch(args):
    _write_watcher_pid_file()
    try:
        result = watch_file_events(args)
        if result is not None:
            return result
        print(
            "[memcore-cloud] falling back to low-latency loop "
            f"({watcher_poll_interval_milliseconds()}ms interval)"
        )
        return watch_poll(args)
    finally:
        _clear_watcher_pid_file()

def watch_poll(args):
    """Low-latency fallback loop for sources without a native file event hook."""
    poll_interval = watcher_poll_interval_seconds()
    poll_interval_ms = watcher_poll_interval_milliseconds()
    print(
        f"[memcore-cloud] low-latency poll mode: source={getattr(args, 'source', 'all')} "
        f"target={poll_interval_ms}ms"
    )
    if _source_enabled(args, "openclaw"):
        os.makedirs(OPENCLAW_ROOT, exist_ok=True)
    signature_cache = {}
    state = {}
    last_openclaw_pending_retry = 0.0
    while True:
        now = time.time()
        retry_openclaw_pending = now - last_openclaw_pending_retry >= 5.0
        if retry_openclaw_pending:
            last_openclaw_pending_retry = now
        _run_sync_once(
            args,
            signature_cache=signature_cache,
            state=state,
            force=False,
            retry_pending=retry_openclaw_pending,
        )
        time.sleep(poll_interval)

# ─── main ──────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="memcore-cloud P0")
    p.add_argument("--scan", action="store_true", help="批量扫描已有 session")
    p.add_argument("--watch", action="store_true", help="实时监听新 session（inotify）")
    p.add_argument("--dry-run", action="store_true", help="干跑不写入")
    p.add_argument(
        "--source",
        choices=["all", "openclaw", "codex", "claude_code_cli", "claude_desktop", "kiro", "hermes"],
        default=None,
        help="source system to scan/watch; defaults to services.p0_watcher_source_default or all for watch",
    )
    p.add_argument("--claude-desktop-limit", type=int, default=0, help="max Claude Desktop raw ingest candidates per scan")
    args = p.parse_args()
    if args.source is None:
        args.source = "all" if args.scan else watcher_source_default()

    if args.watch:
        cmd_watch(args)
    elif args.scan:
        cmd_scan(args)
    else:
        p.print_help()

if __name__ == "__main__":
    main()
