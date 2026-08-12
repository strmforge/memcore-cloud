#!/usr/bin/env python3
"""Build the P3 SQLite FTS5 recall index from the current zhiyi memories."""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from src.fts5_recall_index import (  # noqa: E402
    build_index_atomically,
    default_index_path,
    source_signature_digest,
)


def _lower_process_priority() -> str:
    try:
        if os.name == "nt":
            below_normal_priority_class = 0x00004000
            handle = ctypes.windll.kernel32.GetCurrentProcess()
            if not ctypes.windll.kernel32.SetPriorityClass(handle, below_normal_priority_class):
                raise OSError("SetPriorityClass failed")
            return "below_normal"
        os.nice(10)
        if sys.platform == "darwin":
            try:
                subprocess.run(
                    ["/usr/sbin/taskpolicy", "-b", "-p", str(os.getpid())],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return "darwin_background_nice_10"
            except Exception as exc:
                return f"nice_10:darwin_background_failed:{type(exc).__name__}"
        return "nice_10"
    except Exception as exc:
        return f"unchanged:{type(exc).__name__}"


def _write_result(path: str, payload: dict) -> None:
    if not path:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=str(target.parent))
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, target)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def _release_lock(path: str, token: str) -> None:
    if not path or not token:
        return
    lock_path = Path(path)
    try:
        state = json.loads(lock_path.read_text(encoding="utf-8"))
    except Exception:
        return
    if state.get("token") != token:
        return
    try:
        lock_path.unlink()
    except FileNotFoundError:
        pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Build P3 FTS5 recall index.")
    parser.add_argument("--index-path", default="", help="Output sqlite index path.")
    parser.add_argument("--expected-signature", default="", help="Expected source corpus signature.")
    parser.add_argument("--expected-source-signature", default="", help="Expected source snapshot signature.")
    parser.add_argument("--result-path", default="", help="Write a machine-readable completion receipt.")
    parser.add_argument("--lock-path", default="", help="Refresh ownership lock to release on exit.")
    parser.add_argument("--lock-token", default="", help="Ownership token for the refresh lock.")
    parser.add_argument("--json", action="store_true", help="Print JSON report.")
    args = parser.parse_args()
    priority = _lower_process_priority()
    try:
        import src.p3_recall as p3_recall  # noqa: WPS433

        memcore_root = os.environ.get("MEMCORE_ROOT") or os.environ.get("MEMCORE_INSTALL_ROOT") or str(ROOT)
        index_path = args.index_path or os.environ.get("MEMCORE_FTS5_RECALL_INDEX_PATH") or default_index_path(memcore_root)
        memories = p3_recall.get_memories()
        source_signature = p3_recall._fts5_expected_source_signature(memories)
        report = build_index_atomically(
            memories,
            index_path=index_path,
            expected_signature=args.expected_signature,
            source_signature=source_signature,
            expected_source_signature=args.expected_source_signature,
            source_signature_probe=lambda: source_signature_digest(
                p3_recall._memories_source_signature()
            ),
        )
        report["memory_count"] = len(memories)
        report["worker_pid"] = os.getpid()
        report["worker_priority"] = priority
    except Exception as exc:
        report = {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "write_performed": False,
            "atomic_publish": False,
            "worker_pid": os.getpid(),
            "worker_priority": priority,
        }
    finally:
        try:
            _write_result(args.result_path, report)
        finally:
            _release_lock(args.lock_path, args.lock_token)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    elif not args.result_path:
        print(f"ok={report.get('ok')} index_path={report.get('index_path')} doc_count={report.get('doc_count')} error={report.get('error')}")
    return 0 if report.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
