#!/usr/bin/env python3
"""Runtime-profile sanitization and loader for the product console."""

import datetime
import importlib.util
import os
import time
from pathlib import Path


def write_owned_pid_file(path, pid=None):
    target = Path(path)
    owner = int(pid or os.getpid())
    temporary = target.with_name(f"{target.name}.{owner}.{time.monotonic_ns()}.tmp")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(f"{owner}\n", encoding="ascii")
        os.replace(temporary, target)
        return True
    except OSError:
        return False
    finally:
        try:
            temporary.unlink()
        except OSError:
            pass


def clear_owned_pid_file(path, pid=None):
    target = Path(path)
    owner = int(pid or os.getpid())
    try:
        current = int(target.read_text(encoding="ascii").strip())
    except (OSError, TypeError, ValueError):
        return False
    if current != owner:
        return False
    try:
        target.unlink()
        return True
    except OSError:
        return False


def _safe_runtime_profile_part(name, builder):
    try:
        value = builder()
        if isinstance(value, dict):
            return value
        return {"system": name, "status": "unknown", "value": value}
    except Exception as exc:
        return {
            "system": name,
            "status": "unknown",
            "ok": False,
            "error": "runtime_profile_part_failed",
            "detail": f"{type(exc).__name__}: {str(exc)[:180]}",
        }


def _public_runtime_profile_instances(summary):
    if not isinstance(summary, dict):
        return {
            "profile_status": "unknown",
            "memcore_cloud": [],
            "openclaw": [],
            "hermes": [],
            "claude_desktop": [],
            "detected_count": 0,
            "openclaw_detected": False,
            "hermes_detected": False,
            "claude_desktop_detected": False,
            "stale_instances": [],
            "version_mismatches": [],
        }

    def clean_item(item):
        if not isinstance(item, dict):
            return {"type": str(item or "unknown")}
        return {
            key: item[key]
            for key in ("type", "status", "version", "has_console", "size")
            if key in item
        }

    public = {}
    for key in ("memcore_cloud", "openclaw", "hermes", "claude_desktop"):
        items = summary.get(key) if isinstance(summary.get(key), list) else []
        public[key] = [clean_item(item) for item in items]
    for key in (
        "profile_status",
        "error",
        "detail",
        "detected_count",
        "openclaw_detected",
        "hermes_detected",
        "claude_desktop_detected",
        "stale_instances",
        "version_mismatches",
    ):
        if key in summary:
            public[key] = summary[key]
    return public

def load_runtime_profile_module(memcore_root):
    module_path = os.path.join(str(memcore_root), "tools", "runtime_profile.py")
    if os.path.exists(module_path):
        spec = importlib.util.spec_from_file_location("time_library_runtime_profile", module_path)
        if not spec or not spec.loader:
            raise ModuleNotFoundError(f"runtime_profile.py not loadable at {module_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    detail = (
        f"required runtime profile asset is missing: {module_path}; "
        "release package must include tools/runtime_profile.py"
    )

    class MissingRuntimeProfile:
        @staticmethod
        def ts():
            return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

        @staticmethod
        def _profile(system):
            return {
                "system": system,
                "status": "unknown",
                "ok": False,
                "error": "runtime_profile_asset_missing",
                "detail": detail,
                "instances": [],
                "running_instance": None,
                "selected_runtime": None,
                "health": {"reachable": False, "health_url": None, "status_code": None},
                "stale_instances": [],
                "version_mismatches": [],
            }

        @classmethod
        def build_memcore_profile(cls):
            return cls._profile("memcore-cloud")

        @classmethod
        def build_openclaw_profile(cls):
            return cls._profile("openclaw")

        @classmethod
        def build_hermes_profile(cls):
            return cls._profile("hermes")

        @classmethod
        def build_claude_desktop_profile(cls):
            return cls._profile("claude_desktop")

        @staticmethod
        def build_instances_summary():
            return {
                "profile_status": "unavailable",
                "error": "runtime_profile_asset_missing",
                "detail": detail,
                "memcore_cloud": [],
                "openclaw": [],
                "hermes": [],
                "claude_desktop": [],
                "detected_count": 0,
                "openclaw_detected": False,
                "hermes_detected": False,
                "claude_desktop_detected": False,
                "stale_instances": [],
                "version_mismatches": [],
            }

    return MissingRuntimeProfile
