#!/usr/bin/env python3
"""Internal core-record reliability audit.

This maintainer-only audit reduces the raw guardian payload to one long-run
question: are the core conversation records guarded, merely catching up, or in
need of explicit recovery/backfill?
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from raw_record_recoverability import lost_source_triage as _lost_source_triage

CONTRACT = "memcore_core_record_reliability_audit.v1"
AUDIENCE = "maintainer_only_not_product_ui"
DEFAULT_FOCUS_SOURCES = (
    "codex",
    "claude_code_cli",
    "claude_desktop",
    "openclaw",
    "hermes",
)

ATTENTION_STATUSES = {
    "raw_missing",
    "raw_lagging",
    "source_corrupt",
    "raw_corrupt",
    "source_metadata_incomplete",
    "raw_metadata_incomplete",
    "stat_incomplete",
    "connector_unavailable",
    "connector_scan_error",
    "connector_missing_discover_sessions",
    "authorized_raw_source_unverified",
    "source_regression_raw_retained",
    "source_divergence_raw_retained",
    "source_divergence_generation_active",
    "raw_monotonic_probe_incomplete",
    "source_missing_unrecoverable_from_raw",
    "authorized_raw_unrecoverable_source_missing",
}

PARTIAL_STATUSES = {
    "source_partial_conversation",
    "raw_partial_conversation",
}

PASS_STATUSES = {
    "record_guarded",
    "record_stat_guarded",
    "source_divergence_metadata_only_raw_retained",
    "authorized_raw_recoverable_source_missing",
    "authorized_raw_one_sided_source_missing",
    "authorized_raw_non_conversation_source_missing",
    "source_missing_recoverable_from_raw",
}

OBSERVE_STATUSES = {
    "source_missing_recoverability_unmeasured",
    "authorized_raw_source_recoverability_unmeasured",
}

raw_record_guardian = None


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _guardian_module():
    global raw_record_guardian
    if raw_record_guardian is None:
        import raw_record_guardian as guardian  # type: ignore

        raw_record_guardian = guardian
    return raw_record_guardian


def default_install_root() -> Path:
    home = Path.home()
    system = platform.system().lower()
    if system == "windows":
        base = Path(os.environ.get("LOCALAPPDATA") or home / "AppData" / "Local")
        return base / "memcore-cloud"
    if system == "darwin":
        return home / "Library" / "Application Support" / "memcore-cloud"
    return home / ".local" / "share" / "memcore-cloud"


def _has_config(root: Path) -> bool:
    return (root / "config" / "memcore.json").is_file()


def prepare_runtime_environment(runtime_root: str = "auto") -> dict[str, Any]:
    """Choose the root used for live record scans.

    The repository root can contain fixture or development memory. Live long-run
    audits should prefer the installed runtime root unless the caller explicitly
    sets MEMCORE_ROOT or passes a root.
    """
    existing = os.environ.get("MEMCORE_ROOT", "").strip()
    if existing:
        root = Path(existing).expanduser()
        if _has_config(root):
            if "MEMCORE_CONFIG" not in os.environ:
                os.environ["MEMCORE_CONFIG"] = str(root / "config" / "memcore.json")
            return {
                "runtime_root": str(root),
                "runtime_root_source": "env_MEMCORE_ROOT",
                "runtime_root_exists": root.exists(),
                "runtime_config_exists": True,
                "ignored_invalid_env_root": "",
            }
        install_root = default_install_root()
        if _has_config(install_root):
            os.environ["MEMCORE_ROOT"] = str(install_root)
            if "MEMCORE_CONFIG" not in os.environ:
                os.environ["MEMCORE_CONFIG"] = str(install_root / "config" / "memcore.json")
            return {
                "runtime_root": str(install_root),
                "runtime_root_source": "auto_install_root_ignored_invalid_env_MEMCORE_ROOT",
                "runtime_root_exists": install_root.exists(),
                "runtime_config_exists": True,
                "ignored_invalid_env_root": str(root),
            }
        if "MEMCORE_CONFIG" not in os.environ and _has_config(root):
            os.environ["MEMCORE_CONFIG"] = str(root / "config" / "memcore.json")
        return {
            "runtime_root": str(root),
            "runtime_root_source": "env_MEMCORE_ROOT",
            "runtime_root_exists": root.exists(),
            "runtime_config_exists": False,
            "ignored_invalid_env_root": "",
        }

    requested = str(runtime_root or "auto").strip()
    if requested and requested not in {"auto", "repo", "repository", "dev"}:
        root = Path(requested).expanduser()
        os.environ["MEMCORE_ROOT"] = str(root)
        if "MEMCORE_CONFIG" not in os.environ and _has_config(root):
            os.environ["MEMCORE_CONFIG"] = str(root / "config" / "memcore.json")
        return {
            "runtime_root": str(root),
            "runtime_root_source": "argument",
            "runtime_root_exists": root.exists(),
            "runtime_config_exists": _has_config(root),
        }

    install_root = default_install_root()
    if requested == "auto" and _has_config(install_root):
        os.environ["MEMCORE_ROOT"] = str(install_root)
        if "MEMCORE_CONFIG" not in os.environ:
            os.environ["MEMCORE_CONFIG"] = str(install_root / "config" / "memcore.json")
        return {
            "runtime_root": str(install_root),
            "runtime_root_source": "auto_install_root",
            "runtime_root_exists": install_root.exists(),
            "runtime_config_exists": True,
        }

    root = ROOT
    return {
        "runtime_root": str(root),
        "runtime_root_source": "repository_fallback",
        "runtime_root_exists": root.exists(),
        "runtime_config_exists": _has_config(root),
    }


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _summary(report: dict[str, Any]) -> dict[str, Any]:
    value = report.get("summary")
    return value if isinstance(value, dict) else {}


def _source_systems(item: dict[str, Any]) -> list[str]:
    source = str(item.get("source_system") or "").strip()
    co_sources = [
        str(value).strip()
        for value in _list(item.get("co_source_systems"))
        if str(value).strip()
    ]
    values = [source, *co_sources]
    return sorted({value for value in values if value})


def _record_is_attention(item: dict[str, Any]) -> bool:
    status = str(item.get("guard_status") or "")
    return bool(item.get("backfill_recommended")) or status in ATTENTION_STATUSES


def _record_is_catching_up(item: dict[str, Any]) -> bool:
    return str(item.get("guard_status") or "") == "raw_catching_up"


def _record_is_partial(item: dict[str, Any]) -> bool:
    return str(item.get("guard_status") or "") in PARTIAL_STATUSES


def _record_is_observe(item: dict[str, Any]) -> bool:
    return str(item.get("guard_status") or "") in OBSERVE_STATUSES


def _record_is_pass(item: dict[str, Any]) -> bool:
    status = str(item.get("guard_status") or "")
    return status in PASS_STATUSES and not item.get("backfill_recommended")


def _status_for_source(
    source: str,
    records: list[dict[str, Any]],
    *,
    inactive_sources: set[str],
    gap_sources: set[str],
) -> dict[str, Any]:
    source_records = [
        item for item in records
        if source in _source_systems(item)
    ]
    status_counts: dict[str, int] = {}
    for item in source_records:
        status = str(item.get("guard_status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1

    attention = [item for item in source_records if _record_is_attention(item)]
    catching_up = [
        item for item in source_records
        if _record_is_catching_up(item) and not item.get("backfill_recommended")
    ]
    partial = [
        item for item in source_records
        if _record_is_partial(item) and not item.get("backfill_recommended")
    ]
    evidence_incomplete = [item for item in source_records if _record_is_observe(item)]
    guarded = [item for item in source_records if _record_is_pass(item)]

    if attention:
        state = "needs_backfill" if any(item.get("backfill_recommended") for item in attention) else "attention"
    elif source in gap_sources:
        state = "guardian_gap"
    elif catching_up:
        state = "observing_raw_catching_up"
    elif partial and guarded:
        state = "guarded_with_source_partial_samples"
    elif partial:
        state = "source_partial_samples"
    elif evidence_incomplete:
        state = "source_recoverability_not_measured"
    elif guarded:
        state = "guarded"
    elif source in inactive_sources:
        state = "inactive_no_live_source_sample"
    else:
        state = "needs_sample"

    return {
        "source_system": source,
        "state": state,
        "record_count": len(source_records),
        "guarded_record_count": len(guarded),
        "catching_up_count": len(catching_up),
        "partial_sample_count": len(partial),
        "recoverability_not_measured_count": len(evidence_incomplete),
        "attention_record_count": len(attention),
        "guard_status_counts": status_counts,
    }


def _issue_samples(records: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for item in records:
        if not _record_is_attention(item):
            continue
        source_scan = item.get("source_scan") if isinstance(item.get("source_scan"), dict) else {}
        raw_scan = item.get("raw_scan") if isinstance(item.get("raw_scan"), dict) else {}
        samples.append({
            "source_system": item.get("source_system", ""),
            "artifact_type": item.get("artifact_type", ""),
            "session_id": item.get("session_id", ""),
            "canonical_window_id": item.get("canonical_window_id", ""),
            "thread_name": item.get("thread_name", ""),
            "guard_status": item.get("guard_status", ""),
            "backfill_recommended": bool(item.get("backfill_recommended")),
            "recoverable_from_raw": item.get("recoverable_from_raw"),
            "recoverability_status": item.get("recoverability_status", "not_measured"),
            "source_exists": bool(source_scan.get("exists")),
            "raw_exists": bool(raw_scan.get("exists")),
            "source_health_status": source_scan.get("health_status", ""),
            "raw_health_status": raw_scan.get("health_status", ""),
        })
        if len(samples) >= max(0, int(limit)):
            break
    return samples


def _action_items(
    *,
    status: str,
    summary: dict[str, Any],
    issue_sources: list[str],
    focus_statuses: list[dict[str, Any]],
) -> list[str]:
    items: list[str] = []
    if _int(summary.get("backfill_recommended_count")):
        items.append("Run explicit raw backfill for sources marked backfill_recommended.")
    if _int(summary.get("lost_raw_count")):
        items.append("Inspect 遗失 raw entries first; they mean a source exists without witnessed raw.")
    _lost_source, _recoverable_source, unrecoverable_source, unmeasured_source = _lost_source_triage(summary)
    if unrecoverable_source:
        items.append("Inspect measured-unrecoverable 遗失源 entries before source repair.")
    if unmeasured_source:
        items.append("Complete the bounded 遗失源 structural check; not_measured is not data loss.")
    if issue_sources:
        items.append("Review attention sources: " + ", ".join(sorted(set(issue_sources))))
    if status == "needs_samples":
        missing = [
            item["source_system"]
            for item in focus_statuses
            if item["state"] in {"inactive_no_live_source_sample", "needs_sample"}
        ]
        if missing:
            items.append("Collect live samples for: " + ", ".join(missing))
    if status == "observe":
        items.append("Re-sample after the active append window; short raw_catching_up is not a failure.")
    if not items:
        items.append("Keep long-running samples under the same audit command.")
    return items


def classify_report(
    guardian_report: dict[str, Any],
    *,
    focus_sources: Iterable[str] = DEFAULT_FOCUS_SOURCES,
    issue_sample_limit: int = 20,
) -> dict[str, Any]:
    summary = _summary(guardian_report)
    records = [
        item for item in _list(guardian_report.get("records"))
        if isinstance(item, dict)
    ]
    focus = tuple(dict.fromkeys(str(item).strip() for item in focus_sources if str(item).strip()))
    inactive_sources = {str(item) for item in _list(guardian_report.get("inactive_sources"))}
    gap_sources = {str(item) for item in _list(guardian_report.get("gap_sources"))}
    focus_statuses = [
        _status_for_source(source, records, inactive_sources=inactive_sources, gap_sources=gap_sources)
        for source in focus
    ]
    issue_sources = [
        item["source_system"]
        for item in focus_statuses
        if item["state"] in {"attention", "needs_backfill", "guardian_gap"}
    ]

    record_count = _int(summary.get("record_count"))
    raw_attention_count = _int(summary.get("raw_attention_count"))
    backfill_count = _int(summary.get("backfill_recommended_count"))
    lost_source_count, recoverable_source_count, unrecoverable_source_count, unmeasured_source_count = _lost_source_triage(summary)
    lost_raw_count = _int(summary.get("lost_raw_count"))
    corrupt_count = _int(summary.get("corrupt_record_count"))
    gap_count = _int(summary.get("gap_source_count"))
    catching_up_count = _int(summary.get("raw_catching_up_count"))
    raw_not_current_count = _int(summary.get("raw_not_current_count"))
    partial_count = _int(summary.get("partial_record_count"))
    summary_scope = guardian_report.get("summary_scope") if isinstance(guardian_report.get("summary_scope"), dict) else {}
    summary_is_sample = bool(summary_scope.get("summary_is_sample"))

    if backfill_count:
        audit_status = "needs_backfill"
    elif raw_attention_count or unrecoverable_source_count or lost_raw_count or corrupt_count or gap_count or issue_sources:
        audit_status = "attention"
    elif record_count == 0 or all(
        item["state"] in {"inactive_no_live_source_sample", "needs_sample"}
        for item in focus_statuses
    ):
        audit_status = "needs_samples"
    elif catching_up_count or raw_not_current_count or partial_count or unmeasured_source_count or summary_is_sample:
        audit_status = "observe"
    else:
        audit_status = "pass"

    attention_required = audit_status in {"attention", "needs_backfill"}
    return {
        "ok": not attention_required,
        "contract": CONTRACT,
        "audience": AUDIENCE,
        "generated_at": _utc_now(),
        "read_only": True,
        "write_performed": False,
        "service_call_performed": False,
        "product_ui_write_performed": False,
        "public_docs_write_performed": False,
        "source_guardian_contract": guardian_report.get("contract", ""),
        "index_contract": guardian_report.get("index_contract", ""),
        "time_origin_contract": guardian_report.get("time_origin_contract", ""),
        "summary_scope": summary_scope,
        "audit_status": audit_status,
        "attention_required": attention_required,
        "record_chain_proven": audit_status in {"pass", "observe"},
        "focus_sources": list(focus),
        "source_statuses": focus_statuses,
        "summary": {
            "record_count": record_count,
            "physical_record_count": _int(summary.get("physical_record_count")),
            "logical_record_count": _int(summary.get("logical_record_count")),
            "layout_variant_count": _int(summary.get("layout_variant_count")),
            "record_guarded_count": _int(summary.get("record_guarded_count")),
            "raw_not_current_count": raw_not_current_count,
            "raw_catching_up_count": catching_up_count,
            "raw_attention_count": raw_attention_count,
            "raw_divergence_generation_active_count": _int(
                summary.get("raw_divergence_generation_active_count")
            ),
            "raw_metadata_only_divergence_count": _int(summary.get("raw_metadata_only_divergence_count")),
            "backfill_recommended_count": backfill_count,
            "lost_source_count": lost_source_count,
            "lost_source_recoverable_count": recoverable_source_count,
            "lost_source_unrecoverable_count": unrecoverable_source_count,
            "lost_source_not_measured_count": unmeasured_source_count,
            "lost_source_one_sided_count": _int(summary.get("lost_source_one_sided_count")),
            "lost_source_non_conversation_count": _int(summary.get("lost_source_non_conversation_count")),
            "lost_raw_count": lost_raw_count,
            "inactive_source_count": _int(summary.get("inactive_source_count")),
            "gap_source_count": gap_count,
            "corrupt_record_count": corrupt_count,
            "partial_record_count": _int(summary.get("partial_record_count")),
            "max_raw_lag_bytes": _int(summary.get("max_raw_lag_bytes")),
            "max_raw_lag_milliseconds": _int(summary.get("max_raw_lag_milliseconds")),
        },
        "issue_sources": sorted(set(issue_sources)),
        "issue_samples": _issue_samples(records, limit=issue_sample_limit),
        "action_items": _action_items(
            status=audit_status,
            summary=summary,
            issue_sources=issue_sources,
            focus_statuses=focus_statuses,
        ),
        "notes": [
            "This is a maintainer-only audit and must not be surfaced as an ordinary user completion panel.",
            "no_live_source_sample is inactive evidence, not a record failure.",
            "Short raw_catching_up is observed, not failed, unless backfill_recommended is true.",
            "Only measured-unrecoverable 遗失源 and 遗失 raw are incidents; recoverable is retained platform history and not_measured is an evidence gap.",
        ],
    }


def build_audit(
    *,
    limit: int = 80,
    scan_mode: str = "fast",
    focus_sources: Iterable[str] = DEFAULT_FOCUS_SOURCES,
    include_gaps: bool = True,
    private_paths: bool = False,
    issue_sample_limit: int = 20,
    contract_only: bool = False,
    runtime_root: str = "auto",
) -> dict[str, Any]:
    if contract_only:
        return {
            "ok": True,
            "contract": CONTRACT,
            "audience": AUDIENCE,
            "generated_at": _utc_now(),
            "read_only": True,
            "write_performed": False,
            "service_call_performed": False,
            "product_ui_write_performed": False,
            "public_docs_write_performed": False,
            "audit_status": "contract_only",
            "focus_sources": list(focus_sources),
            "summary": {
                "record_count": 0,
                "record_guarded_count": 0,
                "raw_attention_count": 0,
                "backfill_recommended_count": 0,
                "lost_source_count": 0,
                "lost_source_recoverable_count": 0,
                "lost_source_unrecoverable_count": 0,
                "lost_source_not_measured_count": 0,
                "lost_raw_count": 0,
            },
            "notes": [
                "Contract-only mode does not scan machine records and is intended for release-gate wiring.",
            ],
        }

    runtime = prepare_runtime_environment(runtime_root)
    guardian = _guardian_module()
    report = guardian.build_guardian_status(
        limit=max(1, int(limit or 80)),
        include_gaps=include_gaps,
        scan_mode=scan_mode,
        compact=False,
        public=not private_paths,
    )
    return classify_report(
        report,
        focus_sources=focus_sources,
        issue_sample_limit=issue_sample_limit,
    ) | {"runtime": runtime}


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# 核心记录可靠性长跑审计",
        "",
        f"- 合同: `{report['contract']}`",
        f"- 受众: `{report['audience']}`",
        f"- 生成时间: `{report['generated_at']}`",
        f"- 状态: `{report['audit_status']}`",
        f"- 只读: `{report['read_only']}`",
        f"- 需要处理: `{report.get('attention_required', False)}`",
        "",
        "## 摘要",
        "",
    ]
    for key, value in report.get("summary", {}).items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## 平台状态", ""])
    for item in report.get("source_statuses", []):
        lines.append(
            f"- `{item['source_system']}`: `{item['state']}` "
            f"(records={item['record_count']}, guarded={item['guarded_record_count']}, "
            f"attention={item['attention_record_count']})"
        )
    lines.extend(["", "## 下一步", ""])
    for item in report.get("action_items", []):
        lines.append(f"- {item}")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run internal core-record reliability audit.")
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    parser.add_argument("--limit", type=int, default=80)
    parser.add_argument("--mode", choices=("fast", "full"), default="fast")
    parser.add_argument("--focus", nargs="*", default=list(DEFAULT_FOCUS_SOURCES))
    parser.add_argument("--no-gaps", action="store_true")
    parser.add_argument("--private-paths", action="store_true")
    parser.add_argument("--issue-sample-limit", type=int, default=20)
    parser.add_argument("--contract-only", action="store_true")
    parser.add_argument(
        "--runtime-root",
        default="auto",
        help="live scan root: auto prefers the installed runtime root; use repo to force repository fixtures",
    )
    args = parser.parse_args()

    report = build_audit(
        limit=args.limit,
        scan_mode=args.mode,
        focus_sources=args.focus,
        include_gaps=not args.no_gaps,
        private_paths=args.private_paths,
        issue_sample_limit=args.issue_sample_limit,
        contract_only=args.contract_only,
        runtime_root=args.runtime_root,
    )
    if args.format == "markdown":
        print(render_markdown(report), end="")
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
