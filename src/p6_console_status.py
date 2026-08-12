#!/usr/bin/env python3
"""Read-only console status diagnostics under Time River.

Tiandao contract: this module owns local console status and legacy task result
diagnostics. It reads local runtime/raw/Zhiyi/output state for owner-facing
status panels, but it is not the console entrypoint, not raw origin, and not an
authorized action or platform-write path.
"""

from __future__ import annotations

import glob
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

try:
    from src.config_loader import base_path
except Exception:
    from config_loader import base_path
try:
    from src.service_manager import get_service_manager
    from src.raw_record_recoverability import lost_source_triage
except Exception:
    from service_manager import get_service_manager
    from raw_record_recoverability import lost_source_triage
TIANDAO_CONSOLE_STATUS_CONTRACT = "tiandao_console_status_diagnostics.v1"
MEMCORE_ROOT = base_path()


def configure_console_status(memcore_root=None) -> None:
    global MEMCORE_ROOT
    if memcore_root is not None:
        MEMCORE_ROOT = memcore_root


def get_console_status_contract() -> Dict[str, Any]:
    return {
        "ok": True,
        "contract": TIANDAO_CONSOLE_STATUS_CONTRACT,
        "parent_tiandao_contract": "tiandao_time_river.v1",
        "console_layer": "status_diagnostics",
        "not_raw_origin": True,
        "read_only_by_default": True,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "raw_origin_policy": "raw/time origin remains the source of truth; console status reads derived runtime counters only",
    }


# ─── Data fetchers ──────────────────────────────────────────

def _command_line_looks_like_p0_watcher(command_line):
    text = str(command_line or "").replace("\\", "/").lower()
    return (
        "runtime/p0-watcher.cmd" in text
        or ("memcore-cloud.py" in text and "--watch" in text)
    )


def _windows_p0_watcher_process(pid=None):
    try:
        if pid:
            script = (
                "$p=Get-CimInstance Win32_Process -Filter 'ProcessId=%d' -ErrorAction SilentlyContinue;"
                "if($p){[Console]::OutputEncoding=[System.Text.Encoding]::UTF8;"
                "Write-Output (($p.ProcessId.ToString())+'|'+[string]$p.CommandLine)}"
            ) % int(pid)
        else:
            script = (
                "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8;"
                "Get-CimInstance Win32_Process | "
                "Where-Object { $_.CommandLine -match 'p0-watcher\\.cmd' -or "
                "($_.CommandLine -match 'memcore-cloud\\.py' -and $_.CommandLine -match '--watch') } | "
                "Select-Object -First 1 | ForEach-Object { Write-Output (($_.ProcessId.ToString())+'|'+[string]$_.CommandLine) }"
            )
        ps = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            timeout=6,
        )
    except Exception:
        return None
    for line in ps.stdout.splitlines():
        if "|" not in line:
            continue
        pid_text, command_line = line.split("|", 1)
        if _command_line_looks_like_p0_watcher(command_line):
            return {"pid": pid_text.strip(), "command_line": command_line.strip()}
    return None


def _pid_file_value(path):
    try:
        with open(path, encoding="ascii", errors="ignore") as f:
            text = f.read().strip()
        return int(text) if text.isdigit() else None
    except Exception:
        return None


def _windows_guardian_watcher_status():
    status_path = Path(str(MEMCORE_ROOT)) / "runtime" / "guardian-status.json"
    try:
        if not status_path.exists():
            return None
        stat = status_path.stat()
        age_seconds = (datetime.now(timezone.utc) - datetime.fromtimestamp(stat.st_mtime, timezone.utc)).total_seconds()
        if age_seconds > 900:
            return None
        payload = json.loads(status_path.read_text(encoding="utf-8-sig"))
    except Exception:
        return None
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        return None
    checks = payload.get("checks")
    if not isinstance(checks, list):
        return None
    for check in checks:
        if not isinstance(check, dict) or check.get("ok") is not True:
            continue
        name = str(check.get("name") or "")
        if name not in {"p0_watcher_process", "p0_watcher_start"}:
            continue
        detail = str(check.get("detail") or "")
        pid_match = re.search(r"\bPID\s+(\d+)\b", detail)
        return {
            "active": True,
            "method": "windows_guardian_status",
            "pid": pid_match.group(1) if pid_match else "",
            "detail": f"{name}: {detail}",
        }
    return None


def _posix_process_command(pid):
    try:
        ps = subprocess.run(
            ["ps", "-p", str(int(pid)), "-o", "command="],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return ""
    if ps.returncode != 0:
        return ""
    return ps.stdout.strip()


def _posix_watcher_from_pid(pid):
    command_line = _posix_process_command(pid)
    if command_line and _command_line_looks_like_p0_watcher(command_line):
        return {"pid": str(pid), "command_line": command_line}
    return None


def _macos_launchd_p0_watcher_process():
    try:
        ps = subprocess.run(
            ["launchctl", "list", "com.memcorecloud.p0-watcher"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return None
    if ps.returncode != 0:
        return None
    text = ps.stdout or ""
    pid_match = re.search(r'"PID"\s*=\s*(\d+);', text)
    stdout_match = re.search(r'"StandardOutPath"\s*=\s*"([^"]+)";', text)
    stderr_match = re.search(r'"StandardErrorPath"\s*=\s*"([^"]+)";', text)
    status_match = re.search(r'"LastExitStatus"\s*=\s*(-?\d+);', text)
    pid = pid_match.group(1) if pid_match else ""
    found = _posix_watcher_from_pid(pid) if pid else None
    return {
        "active": bool(found),
        "pid": found.get("pid", pid) if found else pid,
        "command_line": found.get("command_line", "") if found else "",
        "stdout_path": stdout_match.group(1) if stdout_match else "",
        "stderr_path": stderr_match.group(1) if stderr_match else "",
        "last_exit_status": status_match.group(1) if status_match else "",
    }


def _macos_process_scan_p0_watcher():
    try:
        ps = subprocess.run(
            ["ps", "axo", "pid=,command="],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return None
    for line in ps.stdout.splitlines():
        text = line.strip()
        if not text:
            continue
        parts = text.split(None, 1)
        if len(parts) != 2:
            continue
        pid, command_line = parts
        if _command_line_looks_like_p0_watcher(command_line):
            return {"pid": pid.strip(), "command_line": command_line.strip()}
    return None


def get_watcher_status_detail():
    sm = get_service_manager()
    if sm.is_active("memcore-cloud"):
        return {
            "active": True,
            "method": "service_manager",
            "detail": "memcore-cloud service active",
        }
    pid_path = os.path.join(str(MEMCORE_ROOT), "runtime", "p0-watcher.pid")
    pid = _pid_file_value(pid_path)
    if sys.platform == "win32":
        if pid:
            found = _windows_p0_watcher_process(pid)
            if found:
                return {
                    "active": True,
                    "method": "windows_pid_file_commandline",
                    "pid": found.get("pid") or str(pid),
                    "detail": "runtime/p0-watcher.pid command line verified",
                }
        found = _windows_p0_watcher_process()
        if found:
            return {
                "active": True,
                "method": "windows_process_scan",
                "pid": found.get("pid", ""),
                "detail": "p0 watcher process found without trusted pid file",
            }
        guardian = _windows_guardian_watcher_status()
        if guardian:
            return guardian
        return {
            "active": False,
            "method": "windows_process_scan",
            "pid": str(pid or ""),
            "detail": "p0 watcher process not found",
        }
    if sys.platform == "darwin":
        launchd = _macos_launchd_p0_watcher_process()
        if launchd and launchd.get("active"):
            payload = {
                "active": True,
                "method": "macos_launchd",
                "pid": str(launchd.get("pid") or ""),
                "detail": "com.memcorecloud.p0-watcher launchd command line verified",
            }
            if launchd.get("stdout_path"):
                payload["stdout_path"] = launchd["stdout_path"]
            if launchd.get("stderr_path"):
                payload["stderr_path"] = launchd["stderr_path"]
            return payload
        found = _macos_process_scan_p0_watcher()
        if found:
            return {
                "active": True,
                "method": "macos_process_scan",
                "pid": found.get("pid", ""),
                "detail": "p0 watcher process found without launchd PID",
            }
        if pid:
            return {
                "active": False,
                "method": "macos_launchd",
                "pid": str(pid),
                "detail": "p0 watcher process not found; ignored stale runtime/p0-watcher.pid",
            }
        return {
            "active": False,
            "method": "macos_launchd",
            "pid": "",
            "detail": "p0 watcher process not found",
        }
    if pid:
        found = _posix_watcher_from_pid(pid)
        if found:
            return {
                "active": True,
                "method": "pid_file_commandline",
                "pid": found.get("pid", str(pid)),
                "detail": "runtime/p0-watcher.pid command line verified",
            }
    if sys.platform.startswith("linux"):
        for cmd in (
            ["systemctl", "--user", "is-active", "--quiet", "memcore-cloud-p0-watcher.service"],
            ["systemctl", "is-active", "--quiet", "memcore-cloud-p0-watcher.service"],
        ):
            try:
                ps = subprocess.run(cmd, capture_output=True, timeout=5)
                if ps.returncode == 0:
                    return {
                        "active": True,
                        "method": "systemctl",
                        "detail": "memcore-cloud-p0-watcher.service",
                    }
            except Exception:
                pass
    return {
        "active": False,
        "method": "not_found",
        "pid": str(pid or ""),
        "detail": "p0 watcher process not found",
    }


def get_watcher_status():
    return bool(get_watcher_status_detail().get("active"))

def _raw_session_files():
    patterns = [
        f"{MEMCORE_ROOT}/memory/*/*/*/*.jsonl",
        f"{MEMCORE_ROOT}/memory/*/*/*/*/*.jsonl",
    ]
    sessions = []
    for pattern in patterns:
        sessions.extend(glob.glob(pattern))
    return sorted(set(sessions))

def get_raw_stats():
    sessions = _raw_session_files()
    windows = set()
    by_source = {}
    total_msgs = 0
    for s in sessions:
        windows.add(os.path.dirname(s).split("/")[-1])
        parts = os.path.relpath(s, f"{MEMCORE_ROOT}/memory").split(os.sep)
        if len(parts) >= 5:
            source_system = parts[1]
        elif parts:
            source_system = parts[0]
        else:
            source_system = "unknown"
        by_source[source_system] = by_source.get(source_system, 0) + 1
    # Fast: just count files, skip expensive line counting for API
    return {"sessions": len(sessions), "windows": len(windows), "messages": -1, "by_source_system": by_source}

def get_zhiyi_stats():
    stats = {}
    for ftype in ["case_memory", "error_memory", "preference_memory"]:
        path = f"{MEMCORE_ROOT}/zhiyi/{ftype}/{ftype}.jsonl"
        try:
            with open(path, encoding="utf-8", errors="ignore") as f:
                stats[ftype] = sum(1 for _ in f if _.strip())
        except:
            stats[ftype] = 0
    return stats

def get_alias_map():
    path = f"{MEMCORE_ROOT}/config/alias_map.json"
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            return json.load(f)
    except:
        return {}

def load_zhiyi_objects(ftype=None, limit=None):
    objects = []
    types = [ftype] if ftype else ["case_memory", "error_memory", "preference_memory"]
    for t in types:
        path = f"{MEMCORE_ROOT}/zhiyi/{t}/{t}.jsonl"
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8", errors="ignore") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                    obj["_type"] = t
                    try:
                        obj["_source_refs"] = json.loads(obj.get("source_refs", "{}"))
                    except:
                        obj["_source_refs"] = {}
                    objects.append(obj)
                    if limit is not None and len(objects) >= limit:
                        return objects
                except:
                    pass
    return objects

def run_health_check():
    import sys
    results = {}
    sessions = [
        path for path in _raw_session_files()
        if "/memory/openclaw/" in path.replace("\\", "/")
        or "/openclaw/openclaw_session_jsonl/" in path.replace("\\", "/")
    ]
    # Fast: only count sessions, skip per-line reading for performance
    results["p0raw"] = {"status": "passed", "detail": f"{len(sessions)} sessions"}
    watcher_detail_payload = get_watcher_status_detail()
    watcher_active = bool(watcher_detail_payload.get("active"))
    if sys.platform == "win32":
        watcher_detail = "runtime/p0-watcher.pid"
    elif sys.platform.startswith("linux"):
        watcher_detail = "memcore-cloud-p0-watcher.service"
    else:
        watcher_detail = "com.memcorecloud.p0-watcher"
    results["p0watcher"] = {
        "status": "passed" if watcher_active else "failed",
        "detail": f"{watcher_detail}: {watcher_detail_payload.get('detail', '')}",
        "watcher": watcher_detail_payload,
    }
    stats = get_zhiyi_stats()
    results["p2zhiyi"] = {"status": "passed",
                            "detail": f"case={stats.get('case_memory',0)} error={stats.get('error_memory',0)} pref={stats.get('preference_memory',0)}"}
    objs = load_zhiyi_objects(limit=2000)
    failures = sum(1 for o in objs if o.get("_source_refs", {}).get("source_path", "") and
                   not os.path.exists(o.get("_source_refs", {}).get("source_path", "")))
    results["p2sourceRef"] = {"status": "passed" if failures == 0 else "failed",
                                "detail": f"{len(objs)} sampled objects, {failures} path failures"}
    # p3_recall + p4_provider health: socket 端口检测（避免加载 bge-m3 模型）
    import socket
    internal_ports = {
        "p3recall": int(os.environ.get("TIME_LIBRARY_INTERNAL_P3_PORT", "19300")),
        "p4provider": int(os.environ.get("TIME_LIBRARY_INTERNAL_P4_PORT", "19400")),
    }
    for svc_name, port in internal_ports.items():
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            result = sock.connect_ex(('127.0.0.1', port))
            sock.close()
            if result == 0:
                results[svc_name] = {"status": "passed", "detail": f"port {port} reachable"}
            else:
                results[svc_name] = {"status": "failed", "detail": f"port {port} unreachable"}
        except Exception as e:
            results[svc_name] = {"status": "failed", "detail": str(e)[:80]}
    return results

# ─── M3 Status API Helpers (只读) ──────────────────────────────
# Runtime/Zhiyi/Audit status helpers for the legacy local console.
# 原则：全部只读，不写任何文件，不触发 apply，不外推状态

def m3_get_overview(
    get_watcher_status_fn=None,
    get_raw_stats_fn=None,
    get_zhiyi_stats_fn=None,
    get_service_ports_fn=None,
):
    """M3-1: 系统总览状态"""
    import socket
    get_watcher_status_fn = get_watcher_status_fn or get_watcher_status
    get_raw_stats_fn = get_raw_stats_fn or get_raw_stats
    get_zhiyi_stats_fn = get_zhiyi_stats_fn or get_zhiyi_stats
    watcher = get_watcher_status_fn()
    raw = get_raw_stats_fn()
    zhiyi = get_zhiyi_stats_fn()
    # Port checks
    if get_service_ports_fn is not None:
        ports = dict(get_service_ports_fn())
    else:
        ports = {}
        for svc, port in [
            ("p3recall", int(os.environ.get("TIME_LIBRARY_INTERNAL_P3_PORT", "19300"))),
            ("p4inject", int(os.environ.get("TIME_LIBRARY_INTERNAL_P4_PORT", "19400"))),
        ]:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(2)
                r = s.connect_ex(("127.0.0.1", port))
                s.close()
                ports[svc] = "up" if r == 0 else "down"
            except Exception:
                ports[svc] = "unknown"
    services_ready = bool(watcher) and bool(ports) and all(value == "up" for value in ports.values())
    return {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "status": "ok" if services_ready else "attention",
        "watcher_active": watcher,
        "raw_memory": raw,
        "zhiyi_objects": zhiyi,
        "service_ports": ports,
        "phase": "local-service-ready" if services_ready else "local-service-attention",
    }


def m3_get_openclaw_runtime():
    """M3-2: OpenClaw Runtime 状态"""
    import socket
    result = {"gateway_reachable": False, "gateway_port": 18789}
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2)
        r = s.connect_ex(("127.0.0.1", 18789))
        s.close()
        result["gateway_reachable"] = (r == 0)
    except:
        pass
    # Check paired.json existence
    import os as _os
    paired_path = _os.path.expanduser("~/.openclaw/gateway/paired.json")
    result["device_paired"] = _os.path.exists(paired_path)
    return result


def m3_get_memory_runtime():
    """M3-3: Memory/Zhiyi Runtime 状态"""
    zhiyi = get_zhiyi_stats()
    raw = get_raw_stats()
    # Count lifecycle overlay entries
    lifecycle_stats = {}
    for ftype in ["case_memory", "error_memory"]:
        lc_path = f"{MEMCORE_ROOT}/zhiyi/{ftype}/{ftype}.lifecycle.jsonl"
        try:
            with open(lc_path) as f:
                lifecycle_stats[ftype] = sum(1 for _ in f if _.strip())
        except:
            lifecycle_stats[ftype] = 0
    return {
        "raw_memory": raw,
        "zhiyi_objects": zhiyi,
        "lifecycle_overlay": lifecycle_stats,
        "lifecycle_overlay_total": sum(lifecycle_stats.values()),
    }


def m3_get_j2_j7_runtime():
    """M3-4: J2-J7 Lifecycle Runtime 状态"""
    # Check if lifecycle overlay is loaded and working
    try:
        import sys as _sys
        _sys.path.insert(0, str(MEMCORE_ROOT) + "/src")
        from p3_recall import _get_lifecycle_overlay, load_memories, _apply_lifecycle_overlay
        overlay = _get_lifecycle_overlay()
        memories = load_memories()
        enhanced = _apply_lifecycle_overlay(memories)
        from collections import Counter
        status_ctr = Counter(m.get("_lifecycle", {}).get("status", "") for m in enhanced)
        conflict_ctr = Counter(m.get("_lifecycle", {}).get("conflict_decision", "") for m in enhanced)
        j3_superseded_filtered = len(memories) - len(enhanced)
        return {
            "evidence_status": "loaded_runtime_state_not_end_to_end_measured",
            "j2_dedup_applied": None,
            "j2_unique_exp_ids": len({
                str(item.get("exp_id") or "")
                for item in memories
                if isinstance(item, dict) and item.get("exp_id")
            }),
            "j3_supersession_filter_applied": None,
            "j3_superseded_filtered_count": j3_superseded_filtered,
            "j4_freshness_applied": None,
            "j5_ranking_applied": None,
            "lifecycle_overlay_entries": len(overlay),
            "status_distribution": dict(status_ctr),
            "conflict_decision_distribution": dict(conflict_ctr),
            "_note": "Loaded state does not prove dedup, freshness, ranking, or end-to-end recall behavior.",
        }
    except Exception as e:
        return {"error": str(e), "j2_j7_runtime_ready": False}


def m3_get_recent_recall():
    """M3-5: 最近召回结果（触发一次真实 recall）"""
    try:
        import sys as _sys
        _sys.path.insert(0, str(MEMCORE_ROOT) + "/src")
        from p3_recall import handle_recall
        # Use window/sg as default scope (most common), threshold=0.1 to show injectable
        result = handle_recall({
            "query": "",
            "scope_filter": "window/sg",
            "top_k": 5,
            "threshold": 0.1,
            "recall_mode": "substring",
        })
        return {
            "recall_working": True,
            "total_matched": result.get("total_matched", 0),
            "returned": result.get("returned", 0),
            "_scope_enforced": result.get("_scope_enforced", False),
            "matched_memories_count": len(result.get("matched_memories", [])),
        }
    except Exception as e:
        return {"error": str(e), "recall_working": False}


def m3_get_audit_risks():
    """M3-6: current record-health risks from the real guardian path."""
    try:
        try:
            from src.raw_record_guardian import build_guardian_status
        except ImportError:  # pragma: no cover - direct script import fallback
            from raw_record_guardian import build_guardian_status

        report = build_guardian_status(
            limit=80,
            include_gaps=True,
            scan_mode="fast",
            compact=True,
            public=True,
        )
        summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
        summary_scope = report.get("summary_scope") if isinstance(report.get("summary_scope"), dict) else {}
        risks = []
        _, _, lost_source_unrecoverable, lost_source_not_measured = lost_source_triage(summary)
        checks = (
            ("lost_raw", "lost_raw_count", "HIGH"),
            ("corrupt_record", "corrupt_record_count", "HIGH"),
            ("raw_attention", "raw_attention_count", "MEDIUM"),
        )
        for risk_type, field, severity in checks:
            count = int(summary.get(field) or 0)
            if count:
                risks.append({
                    "type": risk_type,
                    "count": count,
                    "status": "attention",
                    "severity": severity,
                })
        if lost_source_unrecoverable:
            risks.append({"type": "lost_source", "recoverability": "measured_unrecoverable", "count": lost_source_unrecoverable, "status": "attention", "severity": "MEDIUM"})
        measured = bool(summary)
        evidence_gaps = ([{"type": "lost_source_recoverability_not_measured", "count": lost_source_not_measured, "status": "observe"}] if lost_source_not_measured else [])
        if summary_scope.get("summary_is_sample"):
            evidence_gaps.append({"type": "guardian_summary_population_incomplete", "count": 1, "status": "observe"})
        return {
            "risks": risks,
            "total_risks": len(risks),
            "audit1_pass": measured and not any(
                item.get("severity") in {"CRITICAL", "HIGH"} for item in risks
            ),
            "evidence_status": "partial" if evidence_gaps else ("measured" if measured else "not_measured"),
            "evidence_gaps": evidence_gaps,
            "guardian_summary": summary,
            "guardian_summary_scope": summary_scope,
        }
    except Exception as e:
        return {
            "risks": [],
            "total_risks": 0,
            "audit1_pass": None,
            "evidence_status": "not_measured",
            "error": str(e),
        }


def m3_get_update_status():
    """M3-7: Update 状态"""
    import os, hashlib, json as _json
    version_path = f"{MEMCORE_ROOT}/VERSION"
    current = "unknown"
    if os.path.exists(version_path):
        with open(version_path) as f:
            current = f.read().strip()
    update_plan_path = f"{MEMCORE_ROOT}/release/update_plan.json"
    update_plan = {}
    if os.path.exists(update_plan_path):
        with open(update_plan_path) as f:
            update_plan = _json.load(f)
    return {
        "current_version": current,
        "update_plan_exists": os.path.exists(update_plan_path),
        "update_plan": update_plan,
        "apply_enabled": False,  # Linux gated, never auto-apply
    }


def m3_get_source_systems():
    """M3-8: Source Systems 状态"""
    import sys as _sys
    _sys.path.insert(0, str(MEMCORE_ROOT) + "/src")
    try:
        from source_system_registry import list_source_systems, get_active_sources
        all_sources = list_source_systems()
        active_sources = get_active_sources()
        return {
            "all_sources": all_sources,
            "active_sources": active_sources,
            "total": len(all_sources),
            "active_count": len(active_sources),
            "_note": "status is read-only, not extrapolated",
        }
    except Exception as e:
        return {"error": str(e)}


# ─── M4 Task Results API Helpers (只读) ──────────────────────────────
# Legacy task result panel helpers.
# 原则：全部只读，读取 output/ 目录下的验收 JSON，不写任何文件

def _m4_scan_task_results():
    """扫描 output/ 目录，构建历史任务结果列表。"""
    import os, json as _json
    output_root = f"{MEMCORE_ROOT}/output"
    tasks = []
    if not os.path.isdir(output_root):
        return tasks
    for name in os.listdir(output_root):
        legacy_task_prefix = "P9" + "-System-"
        if not name.startswith(legacy_task_prefix):
            continue
        checks_dir = os.path.join(output_root, name, "checks")
        if not os.path.isdir(checks_dir):
            tasks.append({
                "task_id": name,
                "status": "unknown",
                "result": None,
                "all_ok": None,
            })
            continue
        # Find the acceptance check file
        acceptance_file = None
        for f in os.listdir(checks_dir):
            if f.endswith("_acceptance_check.json"):
                acceptance_file = os.path.join(checks_dir, f)
                break
        if acceptance_file:
            try:
                with open(acceptance_file) as f:
                    d = _json.load(f)
                tasks.append({
                    "task_id": name,
                    "status": d.get("result", "unknown").lower(),
                    "result": d.get("result"),
                    "all_ok": d.get("all_ok"),
                    "timestamp": d.get("timestamp", ""),
                    "scope_check": d.get("scope_check", {}),
                })
            except Exception:
                tasks.append({"task_id": name, "status": "error", "result": None, "all_ok": None})
        else:
            tasks.append({"task_id": name, "status": "unknown", "result": None, "all_ok": None})
    return tasks


def m4_get_task_results():
    """M4-1: 任务结果列表"""
    tasks = _m4_scan_task_results()
    # Sort: PASS first, thenLIMITED, then FAIL, then unknown
    order = {"pass": 0, "limited": 1, "fail": 2, "error": 3, "unknown": 4}
    tasks.sort(key=lambda t: (order.get(t["status"], 9), t["task_id"]))
    return {
        "total": len(tasks),
        "passed": sum(1 for t in tasks if t["status"] == "pass"),
        "failed": sum(1 for t in tasks if t["status"] == "fail"),
        "limited": sum(1 for t in tasks if t["status"] == "limited"),
        "tasks": tasks,
    }


def m4_get_task_detail(task_id):
    """M4-2: 任务详情"""
    import os, json as _json
    # Sanitize task_id to prevent path traversal
    safe_id = task_id.replace("..", "_").replace("/", "_")
    checks_dir = f"{MEMCORE_ROOT}/output/{safe_id}/checks"
    if not os.path.isdir(checks_dir):
        return {"error": f"Task {task_id} not found", "task_id": task_id}
    acceptance_file = None
    for f in os.listdir(checks_dir):
        if f.endswith("_acceptance_check.json"):
            acceptance_file = os.path.join(checks_dir, f)
            break
    if not acceptance_file:
        return {"error": f"No acceptance check for {task_id}", "task_id": task_id}
    try:
        with open(acceptance_file) as f:
            d = _json.load(f)
        # Add code and test file lists
        code_files = []
        test_files = []
        code_path = f"{MEMCORE_ROOT}/output/{safe_id}/code_changed_files.txt"
        test_path = f"{MEMCORE_ROOT}/output/{safe_id}/test_changed_files.txt"
        if os.path.exists(code_path):
            with open(code_path) as f:
                code_files = [l.strip() for l in f if l.strip()]
        if os.path.exists(test_path):
            with open(test_path) as f:
                test_files = [l.strip() for l in f if l.strip()]
        d["code_files"] = code_files
        d["test_files"] = test_files
        d["_note"] = "read-only: task result from acceptance check"
        return d
    except Exception as e:
        return {"error": str(e), "task_id": task_id}


def m4_get_task_summary(task_id):
    """M4-3: 可复制摘要文本"""
    detail = m4_get_task_detail(task_id)
    if "error" in detail:
        return {"error": detail["error"]}
    lines = []
    lines.append(f"## {detail.get('system', task_id)}")
    lines.append(f"**结果**: {detail.get('result', 'N/A')}")
    if detail.get('timestamp'):
        lines.append(f"**时间**: {detail['timestamp']}")
    if detail.get('scope_check'):
        sc = detail['scope_check']
        lines.append(f"**红线检查**:")
        for k, v in sc.items():
            icon = "✅" if v else "❌"
            lines.append(f"  {icon} {k}: {v}")
    if detail.get('test_suite'):
        ts = detail['test_suite']
        if 'm3_new_tests' in ts:
            m3 = ts['m3_new_tests']
            lines.append(f"**测试**: {m3.get('all_pass', 'N/A')} ({m3.get('total', 0)} cases)")
    if detail.get('code_files'):
        lines.append(f"**修改文件数**: {len(detail['code_files'])}")
        for f in detail['code_files'][:3]:
            lines.append(f"  - {f}")
        if len(detail['code_files']) > 3:
            lines.append(f"  ... and {len(detail['code_files'])-3} more")
    lines.append(f"[复制时间: {detail.get('timestamp','')}]")
    return {
        "task_id": task_id,
        "summary_text": "\n".join(lines),
        "result": detail.get("result"),
        "all_ok": detail.get("all_ok"),
    }


def m4_get_risk_backlog():
    """M4-4: compatibility view over current guardian-backed risks."""
    audit = m3_get_audit_risks()
    risks = [
        {
            "id": str(item.get("type") or "runtime-risk").upper().replace("_", "-"),
            "task": "record-health",
            "severity": item.get("severity", "MEDIUM"),
            "type": item.get("type", "record_health"),
            "description": f"{item.get('type', 'record health')} count: {item.get('count', 0)}",
            "status": item.get("status", "attention"),
            "property": "live guardian result",
        }
        for item in audit.get("risks", [])
        if isinstance(item, dict)
    ]
    return {
        "total": len(risks),
        "risks": risks,
        "audit1_pass": audit.get("audit1_pass"),
        "evidence_status": audit.get("evidence_status", "not_measured"),
        "_note": "Derived from the current raw record guardian; no preset backlog is shipped.",
    }


def m4_get_next_decision_summary():
    """M4-5: compatibility endpoint without preset project decisions."""
    return {
        "status": "not_configured",
        "current_phase": "unknown",
        "pending_decisions": [],
        "completed_systems": [],
        "_note": "No project decisions are preset in the product package.",
    }




__all__ = [
    "TIANDAO_CONSOLE_STATUS_CONTRACT",
    "configure_console_status",
    "get_console_status_contract",
    "_command_line_looks_like_p0_watcher",
    "_windows_p0_watcher_process",
    "_pid_file_value",
    "get_watcher_status_detail",
    "get_watcher_status",
    "_raw_session_files",
    "get_raw_stats",
    "get_zhiyi_stats",
    "get_alias_map",
    "load_zhiyi_objects",
    "run_health_check",
    "m3_get_overview",
    "m3_get_openclaw_runtime",
    "m3_get_memory_runtime",
    "m3_get_j2_j7_runtime",
    "m3_get_recent_recall",
    "m3_get_audit_risks",
    "m3_get_update_status",
    "m3_get_source_systems",
    "_m4_scan_task_results",
    "m4_get_task_results",
    "m4_get_task_detail",
    "m4_get_task_summary",
    "m4_get_risk_backlog",
    "m4_get_next_decision_summary",
]
