#!/usr/bin/env python3
"""Bounded, read-only metadata probe for a Time Library host fleet."""

from __future__ import annotations

import argparse
import base64
import concurrent.futures
import hashlib
import json
import os
import shlex
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


CONTRACT = "time_library_fleet_probe.v2026.7.31"
DEFAULT_TOTAL_DEADLINE_SECONDS = 720.0
MAX_TOTAL_DEADLINE_SECONDS = 840.0
DEFAULT_HOST_TIMEOUT_SECONDS = 30.0
MAX_SSH_CONNECT_TIMEOUT_SECONDS = 5

REMOTE_PROBE_SOURCE = r'''
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

EXPECTED_VERSION = __EXPECTED_VERSION__
EXPECTED_SHA256 = __EXPECTED_SHA256__
SERVICE_SCRIPTS = {
    "watcher": ("src/memcore-cloud.py", "--watch"),
    "p3": ("src/p3_recall.py", ""),
    "p4": ("src/p4_provider.py", ""),
    "p6": ("src/p6_console.py", ""),
    "raw": ("src/raw_consumption_gateway.py", ""),
    "dialog": ("src/dialog_entry_proxy.py", ""),
    "front_door": ("src/single_port_runtime.py", ""),
}
SAFE_RECORD_KEYS = (
    "record_count",
    "physical_record_count",
    "logical_record_count",
    "layout_variant_count",
    "record_guarded_count",
    "raw_lagging_or_missing_count",
    "raw_catching_up_count",
    "raw_attention_count",
    "raw_source_divergence_count",
    "raw_divergence_generation_active_count",
    "raw_metadata_only_divergence_count",
    "raw_source_regression_count",
    "raw_monotonic_probe_incomplete_count",
    "lost_source_count",
    "lost_source_recoverable_count",
    "lost_source_unrecoverable_count",
    "lost_source_not_measured_count",
    "lost_source_one_sided_count",
    "lost_source_non_conversation_count",
    "lost_raw_count",
    "corrupt_record_count",
    "backfill_recommended_count",
)
SAFE_RECOVERABILITY_PROBE_KEYS = (
    "candidate_count",
    "candidate_limit",
    "per_file_byte_limit",
    "round_byte_limit",
    "targeted_scan_count",
    "cache_hit_count",
    "canonical_cache_hit_count",
    "measured_count",
    "not_measured_count",
    "bytes_read",
    "budget_exhausted_count",
    "one_sided_count",
    "non_conversation_count",
)
SAFE_RECOVERABILITY_CACHE_STATUSES = {
    "available",
    "not_applicable",
    "not_needed",
}
GUARDIAN_STATUS_MAX_AGE_SECONDS = 20 * 60
GUARDIAN_STATUS_FUTURE_SKEW_SECONDS = 5 * 60


def _safe_recoverability_probe(probe):
    if not isinstance(probe, dict):
        return None
    result = {"schema": "recoverability_probe.v1"}
    for key in SAFE_RECOVERABILITY_PROBE_KEYS:
        value = probe.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return None
        result[key] = value
    cache_status = probe.get("canonical_cache_status")
    if not isinstance(cache_status, str) or not cache_status:
        return None
    result["canonical_cache_status"] = (
        cache_status
        if cache_status in SAFE_RECOVERABILITY_CACHE_STATUSES
        else "unavailable"
    )
    return result


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _command(command, timeout=4):
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
        return result.returncode, result.stdout
    except Exception:
        return -1, ""


def _powershell_json(script):
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    code, output = _command(
        ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
        timeout=6,
    )
    if code != 0 or not output.strip():
        return []
    try:
        value = json.loads(output)
    except Exception:
        return []
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _process_rows(root):
    if os.name == "nt":
        quoted = "'" + str(root).replace("'", "''") + "'"
        script = (
            "$ErrorActionPreference='SilentlyContinue';$r=" + quoted + ";"
            "$p=@(Get-CimInstance Win32_Process|Where-Object{[string]$_.CommandLine -like ('*'+$r+'*')}|"
            "Select-Object ProcessId,ParentProcessId,CommandLine);"
            "ConvertTo-Json -InputObject $p -Compress -Depth 3"
        )
        rows = []
        for item in _powershell_json(script):
            rows.append({
                "pid": int(item.get("ProcessId") or 0),
                "ppid": int(item.get("ParentProcessId") or 0),
                "command": str(item.get("CommandLine") or ""),
            })
        return rows
    code, output = _command(["ps", "-axo", "pid=,ppid=,command="], timeout=4)
    rows = []
    if code != 0:
        return rows
    for line in output.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) != 3:
            continue
        try:
            pid, ppid = int(parts[0]), int(parts[1])
        except ValueError:
            continue
        rows.append({"pid": pid, "ppid": ppid, "command": parts[2]})
    return rows


def _logical_processes(rows, root):
    normalized_root = str(root).replace("\\", "/").lower().rstrip("/")
    services = {}
    for name, (relative, required) in SERVICE_SCRIPTS.items():
        needle = normalized_root + "/" + relative.lower()
        matches = [
            row for row in rows
            if needle in str(row["command"]).replace("\\", "/").lower()
            and (not required or required in str(row["command"]))
        ]
        ids = {row["pid"] for row in matches}
        roots = sorted(row["pid"] for row in matches if row["ppid"] not in ids)
        services[name] = {
            "logical_count": len(roots),
            "root_pids": roots,
            "process_count": len(matches),
        }
    worker_needle = normalized_root + "/tools/build_fts5_recall_index.py"
    worker_matches = [
        row for row in rows
        if worker_needle in str(row["command"]).replace("\\", "/").lower()
    ]
    worker_ids = {row["pid"] for row in worker_matches}
    worker_roots = sorted(
        row["pid"] for row in worker_matches if row["ppid"] not in worker_ids
    )
    guard_needle = normalized_root + "/tools/codex_mcp_config_guard.py"
    guard_matches = [
        row for row in rows
        if guard_needle in str(row["command"]).replace("\\", "/").lower()
        and "--watch" in str(row["command"])
    ]
    guard_ids = {row["pid"] for row in guard_matches}
    guard_roots = sorted(
        row["pid"] for row in guard_matches if row["ppid"] not in guard_ids
    )
    return services, {
        "fts_worker_logical_count": len(worker_roots),
        "fts_worker_root_pids": worker_roots,
        "codex_guard_logical_count": len(guard_roots),
        "codex_guard_root_pids": guard_roots,
    }


def _listener_rows(ports):
    wanted = {int(port) for port in ports if int(port) > 0}
    if os.name == "nt":
        joined = ",".join(str(port) for port in sorted(wanted))
        script = (
            "$ErrorActionPreference='SilentlyContinue';$w=@(" + joined + ");"
            "$p=@(Get-NetTCPConnection -State Listen|Where-Object{$w -contains [int]$_.LocalPort}|"
            "Select-Object LocalAddress,LocalPort,OwningProcess);"
            "ConvertTo-Json -InputObject $p -Compress -Depth 3"
        )
        return [
            {
                "address": str(item.get("LocalAddress") or ""),
                "port": int(item.get("LocalPort") or 0),
                "pid": int(item.get("OwningProcess") or 0),
            }
            for item in _powershell_json(script)
        ]

    code, output = _command(["lsof", "-nP", "-iTCP", "-sTCP:LISTEN", "-Fpn"], timeout=4)
    rows = []
    if code == 0:
        current_pid = 0
        for line in output.splitlines():
            if line.startswith("p"):
                try:
                    current_pid = int(line[1:])
                except ValueError:
                    current_pid = 0
            elif line.startswith("n"):
                endpoint = line[1:].removeprefix("TCP ")
                match = re.search(r"(.+):(\d+)(?:\s|$)", endpoint)
                if not match or int(match.group(2)) not in wanted:
                    continue
                address = match.group(1).strip("[]")
                rows.append({"address": address, "port": int(match.group(2)), "pid": current_pid})
        return rows

    code, output = _command(["ss", "-ltnpH"], timeout=4)
    if code != 0:
        return []
    for line in output.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        endpoint = parts[3]
        match = re.search(r"(.+):(\d+)$", endpoint)
        if not match or int(match.group(2)) not in wanted:
            continue
        pid_match = re.search(r"pid=(\d+)", line)
        rows.append({
            "address": match.group(1).strip("[]"),
            "port": int(match.group(2)),
            "pid": int(pid_match.group(1)) if pid_match else 0,
        })
    return rows


def _http_json(url, timeout=3):
    try:
        request = urllib.request.Request(
            url,
            headers={"Accept": "application/json"},
            method="GET",
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read(1024 * 1024).decode("utf-8"))
            return {
                "reachable": True,
                "status": int(response.status),
                "payload": payload if isinstance(payload, dict) else {},
                "method_error": "",
            }
    except Exception as exc:
        return {
            "reachable": False,
            "status": 0,
            "payload": {},
            "method_error": type(exc).__name__,
        }


def _guardian_status(root):
    path = root / "runtime" / "guardian-status.json"
    result = {"exists": path.is_file()}
    if not path.is_file():
        return result
    try:
        status_mtime = path.stat().st_mtime
        status_age_seconds = time.time() - status_mtime
        status_fresh = (
            -GUARDIAN_STATUS_FUTURE_SKEW_SECONDS
            <= status_age_seconds
            <= GUARDIAN_STATUS_MAX_AGE_SECONDS
        )
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        checks = [
            item for item in (data.get("checks") or [])
            if isinstance(item, dict)
        ]
        failed_check_names = sorted(
            str(item.get("name") or "")
            for item in checks
            if item.get("ok") is False
        )
        not_measured_check_names = sorted(
            str(item.get("name") or "")
            for item in checks
            if item.get("measurement_status") == "not_measured" or item.get("ok") is None
        )
        scope_fields = {"measurement_status", "full_health_check", "not_measured_layers"}
        scope_present = any(field in data for field in scope_fields)
        reported_ok = data.get("ok") is True
        if scope_present:
            measurement_status = data.get("measurement_status")
            full_health_check = data.get("full_health_check")
            raw_not_measured_layers = data.get("not_measured_layers")
            layers_valid = isinstance(raw_not_measured_layers, list) and all(
                isinstance(item, str) and bool(item.strip())
                for item in raw_not_measured_layers
            )
            not_measured_layers = sorted(set(raw_not_measured_layers)) if layers_valid else []
            scope_schema_valid = (
                measurement_status in {"complete", "partial"}
                and isinstance(full_health_check, bool)
                and layers_valid
            )
            coverage_complete = (
                scope_schema_valid
                and measurement_status == "complete"
                and full_health_check is True
                and not not_measured_layers
                and not not_measured_check_names
            )
            if measurement_status == "partial":
                scope_schema_valid = (
                    scope_schema_valid
                    and full_health_check is False
                    and bool(not_measured_layers or not_measured_check_names)
                )
            elif measurement_status == "complete":
                scope_schema_valid = scope_schema_valid and coverage_complete
            effective_ok = reported_ok and scope_schema_valid and coverage_complete
            coverage_schema = "v1" if scope_schema_valid else "invalid"
        else:
            full_health_check = None
            not_measured_layers = []
            if not_measured_check_names:
                measurement_status = "legacy_partial"
                scope_schema_valid = False
                coverage_complete = False
                effective_ok = False
                coverage_schema = "legacy_incomplete"
            else:
                measurement_status = "legacy_unknown"
                scope_schema_valid = None
                coverage_complete = None
                effective_ok = reported_ok
                coverage_schema = "legacy"
        result.update({
            "ok": effective_ok and status_fresh,
            "reported_ok": reported_ok,
            "status_fresh": status_fresh,
            "status_age_seconds": round(status_age_seconds, 3),
            "status_max_age_seconds": GUARDIAN_STATUS_MAX_AGE_SECONDS,
            "measurement_status": measurement_status,
            "full_health_check": full_health_check,
            "not_measured_layers": not_measured_layers,
            "not_measured_check_names": not_measured_check_names,
            "coverage_schema": coverage_schema,
            "coverage_schema_valid": scope_schema_valid,
            "coverage_complete": coverage_complete,
            "generated_at": str(data.get("generated_at") or ""),
            "mtime_epoch": round(status_mtime, 3),
            "failed_check_names": failed_check_names,
        })
        evidence = data.get("record_guardian")
        if isinstance(evidence, dict):
            summary = evidence.get("summary")
            summary_scope = evidence.get("summary_scope")
            recoverability_probe = _safe_recoverability_probe(
                evidence.get("recoverability_probe")
            )
            try:
                refresh_attempt_age = int(evidence.get("refresh_attempt_age_seconds"))
            except (TypeError, ValueError, OverflowError):
                refresh_attempt_age = -1
            result["record_guardian"] = {
                "available": bool(evidence.get("available")),
                "fresh": bool(evidence.get("fresh")),
                "evidence_source": str(evidence.get("evidence_source") or ""),
                "observed_at": str(evidence.get("observed_at") or ""),
                "cache_age_seconds": int(evidence.get("cache_age_seconds") or 0),
                "last_refresh_attempt_at": str(evidence.get("last_refresh_attempt_at") or ""),
                "refresh_attempt_age_seconds": refresh_attempt_age,
                "refresh_throttled": bool(evidence.get("refresh_throttled")),
                "summary": {
                    key: int((summary or {}).get(key) or 0)
                    for key in SAFE_RECORD_KEYS
                } if isinstance(summary, dict) else None,
                "summary_scope": {
                    "population_complete": bool(summary_scope.get("population_complete")),
                    "summary_is_sample": bool(summary_scope.get("summary_is_sample")),
                    "detail_limit": int(summary_scope.get("detail_limit") or 0),
                    "population_limit_per_source": int(summary_scope.get("population_limit_per_source") or 0),
                    "trend_comparison_key": str(summary_scope.get("trend_comparison_key") or ""),
                } if isinstance(summary_scope, dict) else None,
                "recoverability_probe": recoverability_probe,
            }
    except Exception as exc:
        result["method_error"] = type(exc).__name__
    return result


def _fts_status(root):
    candidates = (
        root / "runtime" / "fts5_recall" / "p3_memories.sqlite3",
        root / "runtime" / "fts5" / "p3.sqlite3",
    )
    path = next((candidate for candidate in candidates if candidate.is_file()), candidates[0])
    result = {"exists": path.is_file(), "worker_checked": True}
    if not path.is_file():
        return result
    try:
        con = sqlite3.connect("file:" + urllib.parse.quote(str(path)) + "?mode=ro", uri=True, timeout=1)
        try:
            meta = {
                str(key): str(value)
                for key, value in con.execute("SELECT key, value FROM meta").fetchall()
            }
        finally:
            con.close()
        result.update({
            "doc_count": int(meta.get("doc_count") or 0),
            "built_at": meta.get("built_at", ""),
            "contract": meta.get("contract", ""),
            "source_signature_present": bool(meta.get("source_signature")),
            "mtime_epoch": round(path.stat().st_mtime, 3),
        })
    except Exception as exc:
        result["method_error"] = type(exc).__name__
    return result


def _codex_registration(root, config_path, applicable):
    if not applicable:
        return {"applicable": False, "status": "not_applicable"}
    path = Path(config_path).expanduser() if config_path else Path.home() / ".codex" / "config.toml"
    result = {"applicable": True, "config_exists": path.is_file()}
    if not path.is_file():
        result["status"] = "missing"
        return result
    try:
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib
        data = tomllib.loads(path.read_text(encoding="utf-8-sig"))
        server = (data.get("mcp_servers") or {}).get("time-library")
        if not isinstance(server, dict):
            result["status"] = "server_missing"
            result["parse_ok"] = True
            return result
        args = [str(value) for value in (server.get("args") or [])]
        root_positions = [index for index, value in enumerate(args) if value == "--root"]
        configured_roots = [
            args[index + 1]
            for index in root_positions
            if index + 1 < len(args)
        ]
        expected_bridge = root / "tools" / "codex_mcp_bridge.py"
        expected_python = (
            root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        )
        normalize = lambda value: os.path.normcase(os.path.abspath(os.path.expanduser(str(value))))
        result.update({
            "parse_ok": True,
            "server_present": True,
            "enabled": server.get("enabled") is not False,
            "command_matches_installed_python": normalize(server.get("command") or "") == normalize(expected_python),
            "installed_bridge_present_in_args": any(normalize(value) == normalize(expected_bridge) for value in args),
            "explicit_root_count": len(root_positions),
            "explicit_root_matches": len(configured_roots) == 1 and normalize(configured_roots[0]) == normalize(root),
        })
        result["registration_ok"] = all((
            result["enabled"],
            result["command_matches_installed_python"],
            result["installed_bridge_present_in_args"],
            result["explicit_root_count"] == 1,
            result["explicit_root_matches"],
        ))
        result["status"] = "ok" if result["registration_ok"] else "miswired"
    except (ImportError, ModuleNotFoundError):
        codex = shutil.which("codex")
        if not codex:
            result.update({
                "parse_ok": False,
                "status": "method_error",
                "method_error": "toml_parser_and_codex_cli_unavailable",
            })
            return result
        code, output = _command([codex, "mcp", "get", "time-library"], timeout=5)
        fields = {}
        if code == 0:
            for line in output.splitlines():
                key, separator, value = line.strip().partition(":")
                if separator and key in {"enabled", "transport", "command", "args"}:
                    fields[key] = value.strip()
        expected_bridge = str(root / "tools" / "codex_mcp_bridge.py")
        expected_python = str(
            root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        )
        args_text = fields.get("args", "")
        result.update({
            "parse_ok": code == 0,
            "server_present": code == 0,
            "enabled": fields.get("enabled", "").lower() == "true",
            "command_matches_installed_python": os.path.normcase(fields.get("command", "")) == os.path.normcase(expected_python),
            "installed_bridge_present_in_args": expected_bridge in args_text,
            "explicit_root_count": args_text.split().count("--root"),
            "explicit_root_matches": ("--root " + str(root)) in args_text,
            "evidence_source": "codex_mcp_get",
        })
        result["registration_ok"] = all((
            result["parse_ok"],
            result["enabled"],
            fields.get("transport") == "stdio",
            result["command_matches_installed_python"],
            result["installed_bridge_present_in_args"],
            result["explicit_root_count"] == 1,
            result["explicit_root_matches"],
        ))
        result["status"] = "ok" if result["registration_ok"] else "miswired"
    except Exception as exc:
        result.update({"parse_ok": False, "status": "method_error", "method_error": type(exc).__name__})
    return result


def main():
    root = Path(sys.argv[1]).expanduser()
    config_path = sys.argv[2] if len(sys.argv) > 2 else ""
    applicable = (sys.argv[3].lower() == "true") if len(sys.argv) > 3 else True
    started = time.monotonic()
    report = {
        "read_only": True,
        "recall_performed": False,
        "raw_excerpt_returned": False,
        "write_performed": False,
        "root_exists": root.is_dir(),
    }
    version_path = root / "VERSION"
    try:
        version = version_path.read_text(encoding="utf-8").strip()
    except Exception:
        version = ""
    report["version"] = version
    report["version_match"] = bool(EXPECTED_VERSION and version == EXPECTED_VERSION)
    sha_checks = {}
    for relative, expected in EXPECTED_SHA256.items():
        path = root / relative
        try:
            actual = _sha256(path)
            sha_checks[relative] = {
                "exists": True,
                "match": actual == expected,
                "actual_sha256": actual,
            }
        except Exception:
            sha_checks[relative] = {"exists": False, "match": False, "actual_sha256": ""}
    report["sha_checks"] = sha_checks

    port_path = root / "runtime" / "front_door_port"
    try:
        port = int(port_path.read_text(encoding="ascii").strip())
        discovery_ok = 1 <= port <= 65535
    except Exception:
        port, discovery_ok = 0, False
    report["port_discovery"] = {"ok": discovery_ok, "port": port}

    rows = _process_rows(root)
    services, helpers = _logical_processes(rows, root)
    report["services"] = services
    report["helpers"] = helpers
    ports = [port, 19300, 19400, 19500, 19510, 19600]
    listeners = _listener_rows(ports)
    loopback = {"127.0.0.1", "::1", "localhost"}
    report["listeners"] = {
        "rows": listeners,
        "all_expected_present": all(any(item["port"] == expected for item in listeners) for expected in ports if expected),
        "only_loopback": bool(listeners) and all(item["address"].split("%", 1)[0] in loopback for item in listeners),
    }

    if discovery_ok:
        base = "http://127.0.0.1:" + str(port)
        health = _http_json(base + "/health", timeout=3)
        payload = health.pop("payload")
        health.update({
            "ok": payload.get("ok") is True,
            "service": str(payload.get("service") or ""),
            "user_visible_address_count": int(payload.get("user_visible_address_count") or 0),
        })
        report["health"] = health
        query = urllib.parse.urlencode({
            "mode": "capability_check",
            "no_recall": "1",
            "consumer": "fleet-monitor",
            "request_id": "fleet-monitor-capability",
        })
        capability = _http_json(base + "/api/v1/raw/query?" + query, timeout=4)
        payload = capability.pop("payload")
        capability.update({
            "ok": payload.get("ok") is True,
            "mode": str(payload.get("mode") or ""),
            "recall_performed": bool(payload.get("recall_performed")),
            "raw_excerpt_returned": bool(payload.get("raw_excerpt_returned")),
            "write_performed": bool(payload.get("write_performed")),
        })
        report["capability"] = capability
    else:
        report["health"] = {"reachable": False, "ok": False, "method_error": "port_discovery_unavailable"}
        report["capability"] = {
            "reachable": False,
            "ok": False,
            "recall_performed": False,
            "raw_excerpt_returned": False,
            "write_performed": False,
            "method_error": "port_discovery_unavailable",
        }

    report["guardian"] = _guardian_status(root)
    report["fts5"] = _fts_status(root)
    report["codex_registration"] = _codex_registration(root, config_path, applicable)
    report["elapsed_seconds"] = round(time.monotonic() - started, 3)
    print(json.dumps(report, ensure_ascii=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
'''


@dataclass(frozen=True)
class HostSpec:
    alias: str
    platform: str
    root: str
    target: str
    codex_applicable: bool = True
    codex_config: str = ""
    local: bool = False


def _host_spec(raw: str) -> HostSpec:
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("host spec must be a JSON object")
    alias = str(data.get("alias") or "").strip()
    platform = str(data.get("platform") or "").strip().lower()
    root = str(data.get("root") or "").strip()
    target = str(data.get("target") or alias).strip()
    if not alias or platform not in {"unix", "windows"} or not root or not target:
        raise ValueError("host spec requires alias, platform=unix|windows, root, and target")
    return HostSpec(
        alias=alias,
        platform=platform,
        root=root,
        target=target,
        codex_applicable=bool(data.get("codex_applicable", True)),
        codex_config=str(data.get("codex_config") or ""),
    )


def _render_remote_source(expected_version: str, expected_sha256: dict[str, str]) -> str:
    return (
        REMOTE_PROBE_SOURCE
        .replace("__EXPECTED_VERSION__", repr(str(expected_version or "")), 1)
        .replace("__EXPECTED_SHA256__", repr(dict(sorted(expected_sha256.items()))), 1)
    )


def _powershell_encoded(command: str) -> str:
    return base64.b64encode(command.encode("utf-16le")).decode("ascii")


def _windows_remote_command(spec: HostSpec) -> str:
    quote = lambda value: "'" + str(value).replace("'", "''") + "'"
    script = (
        "$ProgressPreference='SilentlyContinue';"
        "$ErrorActionPreference='Stop';"
        "[Console]::InputEncoding=New-Object System.Text.UTF8Encoding($false);"
        "[Console]::OutputEncoding=New-Object System.Text.UTF8Encoding($false);"
        f"$r={quote(spec.root)};$c={quote(spec.codex_config)};"
        f"$a={quote(str(spec.codex_applicable).lower())};"
        "$p=Join-Path $r '.venv\\Scripts\\python.exe';"
        "if(-not(Test-Path -LiteralPath $p)){"
        "[Console]::Error.WriteLine('installed_python_missing');exit 2};"
        "$ErrorActionPreference='Continue';"
        "& $p - $r $c $a;exit $LASTEXITCODE"
    )
    return (
        "powershell.exe -NoLogo -NoProfile -NonInteractive "
        "-InputFormat Text -OutputFormat Text "
        "-EncodedCommand " + _powershell_encoded(script)
    )


def _unix_remote_command(spec: HostSpec) -> str:
    python = str(Path(spec.root) / ".venv" / "bin" / "python")
    return shlex.join([
        python,
        "-",
        spec.root,
        spec.codex_config,
        str(spec.codex_applicable).lower(),
    ])


def _terminate(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=0.5)
    except Exception:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except Exception:
            process.kill()


def _run(
    command: list[str],
    *,
    stdin: str,
    timeout: float,
) -> tuple[int, str, str, bool]:
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(stdin, timeout=max(0.05, timeout))
        return process.returncode, stdout, stderr, False
    except subprocess.TimeoutExpired:
        _terminate(process)
        stdout, stderr = process.communicate()
        return process.returncode or 124, stdout, stderr, True


def _ssh_error(stderr: str, timed_out: bool) -> str:
    text = str(stderr or "").lower()
    if timed_out or "connection timed out" in text or "operation timed out" in text:
        return "ssh_timeout"
    if "no route to host" in text or "host is down" in text:
        return "network_unreachable"
    if "permission denied" in text:
        return "ssh_permission_denied"
    if "could not resolve hostname" in text:
        return "ssh_name_resolution_failed"
    if "connection refused" in text:
        return "ssh_connection_refused"
    return "remote_probe_failed"


def _decode_report(stdout: str) -> dict[str, Any] | None:
    for line in reversed(stdout.splitlines()):
        try:
            value = json.loads(line)
        except Exception:
            continue
        if isinstance(value, dict) and value.get("read_only") is True:
            return value
    return None


def _strict_read_only_report(payload: dict[str, Any] | None) -> bool:
    required_sections = (
        "root_exists",
        "version",
        "sha_checks",
        "services",
        "listeners",
        "health",
        "capability",
        "guardian",
        "fts5",
        "codex_registration",
    )
    return bool(
        payload
        and payload.get("read_only") is True
        and payload.get("recall_performed") is False
        and payload.get("raw_excerpt_returned") is False
        and payload.get("write_performed") is False
        and all(section in payload for section in required_sections)
    )


def _transport_diagnostics(
    code: int,
    stdout: str,
    stderr: str,
    timed_out: bool,
    *,
    report_detected: bool,
) -> dict[str, Any]:
    stdout_text = str(stdout or "")
    stderr_text = str(stderr or "")
    return {
        "returncode": int(code),
        "timed_out": bool(timed_out),
        "stdout_bytes": len(stdout_text.encode("utf-8", errors="replace")),
        "stderr_bytes": len(stderr_text.encode("utf-8", errors="replace")),
        "stdout_report_detected": bool(report_detected),
        "stderr_clixml_detected": "#< CLIXML" in stderr_text,
    }


def _probe_one(
    spec: HostSpec,
    *,
    ssh_config: Path,
    source: str,
    connect_timeout: int,
    host_timeout: float,
    deadline: float,
) -> dict[str, Any]:
    started = time.monotonic()
    result = {
        "alias": spec.alias,
        "platform": spec.platform,
        "reachable": False,
        "method_status": "not_started",
        "attempts": 0,
    }
    attempts = 1 if spec.local else 2
    for attempt in range(1, attempts + 1):
        remaining = min(host_timeout, deadline - time.monotonic())
        if remaining <= 0:
            result.update({"method_status": "deadline_exhausted", "error": "fleet_deadline"})
            break
        result["attempts"] = attempt
        if spec.local:
            python = Path(spec.root).expanduser() / ".venv" / "bin" / "python"
            command = [str(python if python.is_file() else sys.executable), "-", spec.root, spec.codex_config, str(spec.codex_applicable).lower()]
        else:
            remote = _windows_remote_command(spec) if spec.platform == "windows" else _unix_remote_command(spec)
            command = [
                "ssh",
                "-T",
                "-F",
                str(ssh_config),
                "-o",
                "BatchMode=yes",
                "-o",
                f"ConnectTimeout={connect_timeout}",
                "-o",
                "ConnectionAttempts=1",
                "-o",
                "ServerAliveInterval=3",
                "-o",
                "ServerAliveCountMax=1",
                spec.target,
                remote,
            ]
        code, stdout, stderr, timed_out = _run(command, stdin=source, timeout=remaining)
        payload = _decode_report(stdout)
        valid_nonzero_report = code != 0 and not timed_out and _strict_read_only_report(payload)
        if (code == 0 and payload is not None) or valid_nonzero_report:
            result.update({
                "reachable": True,
                "method_status": "ok",
                "evidence": payload,
            })
            if valid_nonzero_report:
                result["method_warnings"] = ["remote_exit_nonzero_with_valid_read_only_report"]
                result["transport_diagnostics"] = _transport_diagnostics(
                    code,
                    stdout,
                    stderr,
                    timed_out,
                    report_detected=True,
                )
            break
        error = _ssh_error(stderr, timed_out) if not spec.local else (
            "probe_timeout" if timed_out else "local_probe_failed"
        )
        result.update({
            "method_status": "failed",
            "error": error,
            "transport_diagnostics": _transport_diagnostics(
                code,
                stdout,
                stderr,
                timed_out,
                report_detected=payload is not None,
            ),
        })
        if spec.local or error not in {
            "ssh_timeout",
            "network_unreachable",
            "ssh_connection_refused",
            "ssh_name_resolution_failed",
        }:
            break
    result["elapsed_seconds"] = round(time.monotonic() - started, 3)
    return result


def run_fleet_probe(
    specs: list[HostSpec],
    *,
    ssh_config: Path,
    expected_version: str,
    expected_sha256: dict[str, str],
    total_deadline_seconds: float,
    host_timeout_seconds: float,
    connect_timeout_seconds: int,
    probe: Callable[..., dict[str, Any]] = _probe_one,
) -> dict[str, Any]:
    started = time.monotonic()
    deadline = started + total_deadline_seconds
    source = _render_remote_source(expected_version, expected_sha256)
    hosts: list[dict[str, Any]] = []
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(len(specs), 8)))
    futures = {
        pool.submit(
            probe,
            spec,
            ssh_config=ssh_config,
            source=source,
            connect_timeout=connect_timeout_seconds,
            host_timeout=host_timeout_seconds,
            deadline=deadline,
        ): spec
        for spec in specs
    }
    try:
        done, pending = concurrent.futures.wait(
            futures,
            timeout=max(0.0, deadline - time.monotonic()),
        )
        for future in done:
            try:
                hosts.append(future.result())
            except Exception as exc:
                spec = futures[future]
                hosts.append({
                    "alias": spec.alias,
                    "platform": spec.platform,
                    "reachable": False,
                    "method_status": "failed",
                    "error": f"probe_exception:{type(exc).__name__}",
                })
        for future in pending:
            spec = futures[future]
            future.cancel()
            hosts.append({
                "alias": spec.alias,
                "platform": spec.platform,
                "reachable": False,
                "method_status": "deadline_exhausted",
                "error": "fleet_deadline",
            })
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    hosts.sort(key=lambda item: item["alias"])
    elapsed = time.monotonic() - started
    return {
        "contract": CONTRACT,
        "read_only": True,
        "recall_performed": False,
        "raw_excerpt_returned": False,
        "write_performed": False,
        "total_deadline_seconds": total_deadline_seconds,
        "deadline_exhausted": bool(
            elapsed >= total_deadline_seconds
            or any(item.get("method_status") == "deadline_exhausted" for item in hosts)
        ),
        "elapsed_seconds": round(elapsed, 3),
        "hosts": hosts,
        "summary": {
            "host_count": len(hosts),
            "reachable_count": sum(bool(item.get("reachable")) for item in hosts),
            "method_failure_count": sum(item.get("method_status") != "ok" for item in hosts),
        },
    }


def _sha_arg(value: str) -> tuple[str, str]:
    relative, separator, digest = value.partition("=")
    if not separator or not relative or len(digest) != 64:
        raise argparse.ArgumentTypeError("--expected-sha requires relative/path=64_hex_sha256")
    try:
        int(digest, 16)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("invalid SHA-256") from exc
    return relative, digest.lower()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ssh-config", type=Path, required=True)
    parser.add_argument("--host-json", action="append", default=[])
    parser.add_argument("--local-root", default="")
    parser.add_argument("--local-alias", default="local")
    parser.add_argument("--local-codex-config", default="")
    parser.add_argument("--expected-version", default="")
    parser.add_argument("--expected-sha", action="append", type=_sha_arg, default=[])
    parser.add_argument("--total-deadline", type=float, default=DEFAULT_TOTAL_DEADLINE_SECONDS)
    parser.add_argument("--host-timeout", type=float, default=DEFAULT_HOST_TIMEOUT_SECONDS)
    parser.add_argument("--connect-timeout", type=int, default=MAX_SSH_CONNECT_TIMEOUT_SECONDS)
    args = parser.parse_args(argv)

    if not args.ssh_config.is_file():
        parser.error("--ssh-config must name an existing file")
    if not 0.1 <= args.total_deadline <= MAX_TOTAL_DEADLINE_SECONDS:
        parser.error(f"--total-deadline must be between 0.1 and {MAX_TOTAL_DEADLINE_SECONDS:g}")
    if not 0.1 <= args.host_timeout <= args.total_deadline:
        parser.error("--host-timeout must be positive and no larger than --total-deadline")
    if not 1 <= args.connect_timeout <= MAX_SSH_CONNECT_TIMEOUT_SECONDS:
        parser.error(f"--connect-timeout must be between 1 and {MAX_SSH_CONNECT_TIMEOUT_SECONDS}")

    try:
        specs = [_host_spec(raw) for raw in args.host_json]
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    if args.local_root:
        specs.append(HostSpec(
            alias=args.local_alias,
            platform="unix",
            root=args.local_root,
            target=args.local_alias,
            codex_applicable=True,
            codex_config=args.local_codex_config,
            local=True,
        ))
    if not specs:
        parser.error("at least one --host-json or --local-root is required")

    report = run_fleet_probe(
        specs,
        ssh_config=args.ssh_config,
        expected_version=args.expected_version,
        expected_sha256=dict(args.expected_sha),
        total_deadline_seconds=args.total_deadline,
        host_timeout_seconds=args.host_timeout,
        connect_timeout_seconds=args.connect_timeout,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
