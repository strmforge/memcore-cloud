#!/usr/bin/env python3
"""Record-chain doctor and timeline.

Tiandao contract: this module is a read-only presentation layer above the
raw record guardian and canonical record index. It helps users answer the
plain question "are my records guarded?" without becoming a raw origin,
canonical index owner, memory writer, or platform-config owner.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

try:
    from raw_record_guardian import build_guardian_status
except ImportError:  # pragma: no cover
    from src.raw_record_guardian import build_guardian_status
try:
    from raw_record_canonical_index import query_records_index
except ImportError:  # pragma: no cover
    from src.raw_record_canonical_index import query_records_index
try:
    from raw_record_recoverability import lost_source_triage as _lost_source_triage
except ImportError:  # pragma: no cover
    from src.raw_record_recoverability import lost_source_triage as _lost_source_triage


RECORD_CHAIN_DOCTOR_CONTRACT = "record_chain_doctor.v1"
RECORD_CHAIN_TIMELINE_CONTRACT = "record_chain_timeline.v1"
RECORD_CHAIN_REPLAY_CONTRACT = "record_chain_replay.v1"
RECORD_CHAIN_PARENT_TIANDAO_CONTRACT = "tiandao_time_river.v1"
GUARDED_STATUSES = {
    "record_guarded",
    "record_stat_guarded",
    "authorized_raw_recoverable_source_missing",
    "source_missing_recoverable_from_raw",
}
ATTENTION_STATUSES = {"raw_missing", "source_corrupt", "raw_corrupt"}


def ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _clamp_limit(limit: int | str | None, *, default: int = 20, maximum: int = 200) -> int:
    try:
        value = int(limit or default)
    except Exception:
        value = default
    return max(1, min(value, maximum))


def _guardian_report(
    *,
    guardian_report: dict[str, Any] | None,
    limit: int,
    scan_mode: str,
    public: bool,
) -> dict[str, Any]:
    if guardian_report is not None:
        return guardian_report
    return build_guardian_status(
        limit=limit,
        include_gaps=True,
        write_index=False,
        scan_mode="full" if str(scan_mode).lower() in {"full", "deep"} else "fast",
        compact=True,
        public=public,
    )


def _canonical_report(
    *,
    canonical_index: dict[str, Any] | None,
    source_system: str = "",
    session_id: str = "",
    query: str = "",
    limit: int,
    public: bool,
) -> dict[str, Any]:
    if canonical_index is not None:
        return canonical_index
    try:
        return query_records_index(
            source_system=source_system,
            session_id=session_id,
            query=query,
            limit=limit,
            public=public,
        )
    except Exception as exc:
        return {
            "ok": False,
            "contract": "canonical_record_index.v2",
            "error": f"canonical_index_query_failed:{type(exc).__name__}",
            "error_detail": str(exc)[:200],
            "read_only": True,
            "write_performed": False,
            "sessions": [],
            "messages": [],
            "origin_events": [],
            "totals": {},
        }


def _doctor_status(summary: dict[str, Any], canonical: dict[str, Any]) -> tuple[str, str, str]:
    record_count = _int(summary.get("record_count"))
    guarded = _int(summary.get("record_guarded_count"))
    attention = _int(summary.get("raw_attention_count"))
    backfill = _int(summary.get("backfill_recommended_count"))
    lost_source, _recoverable_source, unrecoverable_source, unmeasured_source = _lost_source_triage(summary)
    lost_raw = _int(summary.get("lost_raw_count"))
    corrupt = _int(summary.get("corrupt_record_count"))
    catching_up = _int(summary.get("raw_catching_up_count"))
    canonical_ok = bool(canonical.get("ok"))

    if record_count <= 0:
        return (
            "no_records_seen",
            "No local source records were seen yet.",
            "还没有看到本机来源记录。",
        )
    if unrecoverable_source or lost_raw or attention or corrupt:
        return (
            "attention",
            "Some records need attention before the chain is fully guarded.",
            "有记录需要处理，链路还没有完全守住。",
        )
    if backfill:
        return (
            "needs_backfill",
            "Records were found, and explicit backfill is recommended.",
            "已发现记录，但建议显式回填。",
        )
    if unmeasured_source:
        return (
            "recoverability_evidence_incomplete",
            "Raw is retained, but bounded recovery evidence is still incomplete.",
            "Raw 仍在，但有界可恢复性证据尚未补齐。",
        )
    if catching_up and guarded < record_count:
        return (
            "catching_up",
            "Records are being tailed and should be sampled again shortly.",
            "记录正在追尾，稍后再采样即可。",
        )
    if not canonical_ok:
        return (
            "records_guarded_index_not_ready",
            "Raw records are guarded; the searchable index is not ready yet.",
            "原始记录已守住；可搜索索引尚未就绪。",
        )
    return (
        "records_guarded",
        "Records are guarded: source, raw, and the canonical index line up.",
        "记录已守住：源、raw 和索引链路已经对齐。",
    )


def build_record_doctor(
    *,
    guardian_report: dict[str, Any] | None = None,
    canonical_index: dict[str, Any] | None = None,
    limit: int = 20,
    scan_mode: str = "fast",
    public: bool = True,
) -> dict[str, Any]:
    """Build a one-click, read-only record doctor payload."""
    limit = _clamp_limit(limit, default=20, maximum=200)
    guardian = _guardian_report(
        guardian_report=guardian_report,
        limit=limit,
        scan_mode=scan_mode,
        public=public,
    )
    canonical = _canonical_report(
        canonical_index=canonical_index,
        limit=limit,
        public=public,
    )
    summary = _dict(guardian.get("summary"))
    summary_scope = _dict(guardian.get("summary_scope"))
    totals = _dict(canonical.get("totals"))
    status, headline, zh_headline = _doctor_status(summary, canonical)
    attention = _int(summary.get("raw_attention_count"))
    active_generations = _int(summary.get("raw_divergence_generation_active_count"))
    backfill = _int(summary.get("backfill_recommended_count"))
    lost_source, recoverable_source, unrecoverable_source, unmeasured_source = _lost_source_triage(summary)
    lost_raw = _int(summary.get("lost_raw_count"))
    corrupt = _int(summary.get("corrupt_record_count"))
    raw_not_current = _int(summary.get("raw_not_current_count"))
    record_guarded = status in {"records_guarded", "records_guarded_index_not_ready"}

    checks = [
        {
            "id": "source_seen",
            "label": "Source records",
            "zh_label": "来源记录",
            "ok": _int(summary.get("record_count")) > 0,
            "value": _int(summary.get("record_count")),
        },
        {
            "id": "raw_guarded",
            "label": "Raw guarded",
            "zh_label": "Raw 已守住",
            "ok": record_guarded and raw_not_current == 0,
            "value": _int(summary.get("record_guarded_count")),
        },
        {
            "id": "time_origin",
            "label": "Time origin witnessed",
            "zh_label": "时间起源已见证",
            "ok": _int(summary.get("origin_event_count")) >= 0,
            "value": _int(summary.get("origin_event_count") or summary.get("origin_witnessed_count")),
        },
        {
            "id": "lost_records",
            "label": "Lost source / lost raw",
            "zh_label": "遗失源 / 遗失 raw",
            "ok": unrecoverable_source == 0 and lost_raw == 0,
            "value": {
                "lost_source": lost_source,
                "lost_source_recoverable": recoverable_source,
                "lost_source_unrecoverable": unrecoverable_source,
                "lost_source_not_measured": unmeasured_source,
                "lost_raw": lost_raw,
            },
        },
        {
            "id": "canonical_index",
            "label": "Canonical index",
            "zh_label": "所有会话底座",
            "ok": bool(canonical.get("ok")),
            "value": {
                "sessions": _int(totals.get("canonical_sessions")),
                "messages": _int(totals.get("canonical_messages")),
            },
        },
        {
            "id": "attention",
            "label": "Attention",
            "zh_label": "需处理",
            "ok": attention == 0 and backfill == 0 and corrupt == 0,
            "value": {"attention": attention, "backfill": backfill, "corrupt": corrupt},
        },
    ]

    next_actions: list[str] = []
    if lost_raw or backfill:
        next_actions.append("Run explicit record backfill for the affected source.")
    if unrecoverable_source:
        next_actions.append("Inspect measured-unrecoverable raw as recovery evidence before any source repair.")
    if unmeasured_source:
        next_actions.append("Complete the bounded lost-source structural check; do not treat unmeasured as lost.")
    if active_generations:
        next_actions.append("Review active divergence generations; continuation is guarded and backfill is not implied.")
    if not canonical.get("ok"):
        next_actions.append("Refresh the canonical index from guarded records when you want searchable replay.")
    if not next_actions and status == "records_guarded":
        next_actions.append("No action needed; the record chain is ready for recall and experience.")

    return {
        "ok": status in {
            "records_guarded",
            "records_guarded_index_not_ready",
            "catching_up",
            "recoverability_evidence_incomplete",
        },
        "contract": RECORD_CHAIN_DOCTOR_CONTRACT,
        "parent_tiandao_contract": RECORD_CHAIN_PARENT_TIANDAO_CONTRACT,
        "audience": "product_read_only_self_check",
        "generated_at": ts(),
        "read_only": True,
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "doctor_status": status,
        "headline": headline,
        "zh_headline": zh_headline,
        "record_chain_mode": "source_to_raw_to_canonical_to_memory_experience",
        "summary_scope": summary_scope,
        "not_memory_wall": True,
        "summary": {
            "record_count": _int(summary.get("record_count")),
            "physical_record_count": _int(summary.get("physical_record_count")),
            "logical_record_count": _int(summary.get("logical_record_count")),
            "layout_variant_count": _int(summary.get("layout_variant_count")),
            "record_guarded_count": _int(summary.get("record_guarded_count")),
            "record_stat_guarded_count": _int(summary.get("record_stat_guarded_count")),
            "raw_not_current_count": raw_not_current,
            "raw_attention_count": attention,
            "raw_divergence_generation_active_count": active_generations,
            "raw_metadata_only_divergence_count": _int(summary.get("raw_metadata_only_divergence_count")),
            "backfill_recommended_count": backfill,
            "lost_source_count": lost_source,
            "lost_source_recoverable_count": recoverable_source,
            "lost_source_unrecoverable_count": unrecoverable_source,
            "lost_source_not_measured_count": unmeasured_source,
            "lost_source_one_sided_count": _int(summary.get("lost_source_one_sided_count")),
            "lost_source_non_conversation_count": _int(summary.get("lost_source_non_conversation_count")),
            "lost_raw_count": lost_raw,
            "origin_event_count": _int(summary.get("origin_event_count") or summary.get("origin_witnessed_count")),
            "canonical_sessions": _int(totals.get("canonical_sessions")),
            "canonical_messages": _int(totals.get("canonical_messages")),
            "canonical_chunks": _int(totals.get("canonical_chunks")),
        },
        "checks": checks,
        "next_actions": next_actions,
        "source_contracts": {
            "guardian": guardian.get("contract"),
            "canonical_index": canonical.get("contract"),
            "time_origin": guardian.get("time_origin_contract"),
        },
        "notes": [
            "This doctor is read-only and does not trigger backfill or index writes.",
            "A guarded record chain means source/raw evidence is preserved before memory or experience is trusted.",
        ],
    }


def _record_label(item: dict[str, Any]) -> str:
    return (
        _safe_str(item.get("thread_name"))
        or _safe_str(item.get("session_id"))
        or _safe_str(item.get("canonical_window_id"))
        or _safe_str(item.get("record_id"))
        or "-"
    )


def _stage(stage_id: str, label: str, status: str, **extra: Any) -> dict[str, Any]:
    payload = {"id": stage_id, "label": label, "status": status}
    payload.update({key: value for key, value in extra.items() if value not in (None, "")})
    return payload


def _chain_from_session(
    session: dict[str, Any],
    guardian_by_record: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    record_id = _safe_str(session.get("record_id"))
    guardian = guardian_by_record.get(record_id, {})
    source_label = _safe_str(session.get("source_path_label") or guardian.get("source_path_label"))
    raw_label = _safe_str(session.get("raw_path_label") or guardian.get("raw_path_label"))
    indexed_messages = _int(session.get("indexed_message_count"))
    raw_offset_coverage = _int(session.get("raw_offset_coverage_count"))
    guard_status = _safe_str(guardian.get("guard_status")) or _safe_str(session.get("index_status"))
    raw_current = bool(guardian.get("raw_current")) or raw_offset_coverage > 0
    stages = [
        _stage(
            "source_record",
            "Source record",
            "seen" if source_label else "not_labeled",
            path_label=source_label,
        ),
        _stage(
            "raw_mirror",
            "Raw mirror",
            "guarded" if raw_current or raw_label else "not_current",
            path_label=raw_label,
            guard_status=guard_status,
        ),
        _stage(
            "canonical_index",
            "Canonical index",
            "indexed" if indexed_messages else "not_indexed",
            indexed_message_count=indexed_messages,
            raw_offset_coverage_count=raw_offset_coverage,
        ),
        _stage(
            "memory_experience",
            "Memory and experience",
            "source_refs_ready" if indexed_messages or raw_current else "waiting_for_records",
            note="Derived memory and experience must point back to the guarded record chain.",
        ),
    ]
    return {
        "record_id": record_id,
        "source_system": _safe_str(session.get("source_system") or guardian.get("source_system")),
        "session_id": _safe_str(session.get("session_id") or guardian.get("session_id")),
        "canonical_window_id": _safe_str(session.get("canonical_window_id") or guardian.get("canonical_window_id")),
        "project_id": _safe_str(session.get("project_id") or guardian.get("project_id")),
        "title": _record_label({**guardian, **session}),
        "updated_at": _safe_str(session.get("updated_at") or guardian.get("raw_mtime") or guardian.get("source_mtime")),
        "chain_status": "guarded" if raw_current and indexed_messages else ("guarded_not_indexed" if raw_current else "needs_attention"),
        "stages": stages,
    }


def _chain_from_guardian_record(item: dict[str, Any]) -> dict[str, Any]:
    guard_status = _safe_str(item.get("guard_status"))
    source_exists = bool(item.get("source_exists"))
    raw_exists = bool(item.get("raw_exists"))
    raw_current = bool(item.get("raw_current")) or guard_status in GUARDED_STATUSES
    return {
        "record_id": _safe_str(item.get("record_id")),
        "source_system": _safe_str(item.get("source_system")),
        "session_id": _safe_str(item.get("session_id")),
        "canonical_window_id": _safe_str(item.get("canonical_window_id")),
        "project_id": _safe_str(item.get("project_id")),
        "title": _record_label(item),
        "updated_at": _safe_str(item.get("raw_mtime") or item.get("source_mtime")),
        "chain_status": "guarded_not_indexed" if raw_current else "needs_attention",
        "stages": [
            _stage(
                "source_record",
                "Source record",
                "seen" if source_exists or item.get("source_path_label") else "missing",
                path_label=item.get("source_path_label"),
                health=item.get("source_health_status"),
            ),
            _stage(
                "raw_mirror",
                "Raw mirror",
                "guarded" if raw_current else ("seen" if raw_exists else "missing"),
                path_label=item.get("raw_path_label"),
                health=item.get("raw_health_status"),
                guard_status=guard_status,
            ),
            _stage(
                "canonical_index",
                "Canonical index",
                "not_loaded",
                note="Run an explicit index refresh when searchable replay is needed.",
            ),
            _stage(
                "memory_experience",
                "Memory and experience",
                "waiting_for_index" if raw_current else "waiting_for_records",
            ),
        ],
    }


def build_record_chain_timeline(
    *,
    guardian_report: dict[str, Any] | None = None,
    canonical_index: dict[str, Any] | None = None,
    source_system: str = "",
    session_id: str = "",
    query: str = "",
    limit: int = 20,
    scan_mode: str = "fast",
    public: bool = True,
) -> dict[str, Any]:
    """Build a record-chain timeline from source/raw/index facts."""
    limit = _clamp_limit(limit, default=20, maximum=200)
    guardian = _guardian_report(
        guardian_report=guardian_report,
        limit=limit,
        scan_mode=scan_mode,
        public=public,
    )
    canonical = _canonical_report(
        canonical_index=canonical_index,
        source_system=source_system,
        session_id=session_id,
        query=query,
        limit=limit,
        public=public,
    )
    records = [item for item in _list(guardian.get("records")) if isinstance(item, dict)]
    guardian_by_record = {
        _safe_str(item.get("record_id")): item
        for item in records
        if _safe_str(item.get("record_id"))
    }
    sessions = [item for item in _list(canonical.get("sessions")) if isinstance(item, dict)]
    if sessions:
        chains = [_chain_from_session(item, guardian_by_record) for item in sessions[:limit]]
    else:
        chains = [_chain_from_guardian_record(item) for item in records[:limit]]
    messages = [
        {
            "message_id": _safe_str(item.get("message_id")),
            "record_id": _safe_str(item.get("record_id")),
            "source_system": _safe_str(item.get("source_system")),
            "session_id": _safe_str(item.get("session_id")),
            "role": _safe_str(item.get("role")),
            "timestamp": _safe_str(item.get("timestamp")),
            "content_preview": _safe_str(item.get("content_preview")),
            "raw_available": bool(_int(item.get("raw_available"))),
        }
        for item in _list(canonical.get("messages"))
        if isinstance(item, dict)
    ][:limit]
    return {
        "ok": bool(chains) or bool(canonical.get("ok")),
        "contract": RECORD_CHAIN_TIMELINE_CONTRACT,
        "parent_tiandao_contract": RECORD_CHAIN_PARENT_TIANDAO_CONTRACT,
        "generated_at": ts(),
        "read_only": True,
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "timeline_kind": "record_chain",
        "not_memory_wall": True,
        "source_system": source_system,
        "session_id": session_id,
        "query": query,
        "chain_count": len(chains),
        "record_chains": chains,
        "recent_messages": messages,
        "origin_events": _list(canonical.get("origin_events"))[:limit],
        "canonical_index_ready": bool(canonical.get("ok")),
        "notes": [
            "Record chain order is source -> raw -> canonical index -> memory/experience.",
            "Recent messages are index previews, not a replacement for raw records.",
        ],
    }


def build_record_chain_replay(
    *,
    guardian_report: dict[str, Any] | None = None,
    canonical_index: dict[str, Any] | None = None,
    source_system: str = "",
    session_id: str = "",
    limit: int = 50,
    scan_mode: str = "fast",
    public: bool = True,
) -> dict[str, Any]:
    """Return a single session replay as a record chain, not a memory wall."""
    limit = _clamp_limit(limit, default=50, maximum=200)
    canonical = _canonical_report(
        canonical_index=canonical_index,
        source_system=source_system,
        session_id=session_id,
        limit=limit,
        public=public,
    )
    messages = [item for item in _list(canonical.get("messages")) if isinstance(item, dict)]
    replay_session_id = session_id or (_safe_str(messages[0].get("session_id")) if messages else "")
    if replay_session_id and not session_id and canonical_index is None:
        canonical = _canonical_report(
            canonical_index=None,
            source_system=source_system,
            session_id=replay_session_id,
            limit=limit,
            public=public,
        )
        messages = [item for item in _list(canonical.get("messages")) if isinstance(item, dict)]
    timeline = build_record_chain_timeline(
        guardian_report=guardian_report,
        canonical_index=canonical,
        source_system=source_system,
        session_id=replay_session_id,
        limit=limit,
        scan_mode=scan_mode,
        public=public,
    )
    replay_messages = [
        {
            "role": _safe_str(item.get("role")),
            "timestamp": _safe_str(item.get("timestamp")),
            "line_no": _int(item.get("line_no")),
            "raw_line_no": _int(item.get("raw_line_no")),
            "raw_available": bool(_int(item.get("raw_available"))),
            "content_preview": _safe_str(item.get("content_preview")),
        }
        for item in messages
        if not replay_session_id or _safe_str(item.get("session_id")) == replay_session_id
    ][:limit]
    return {
        "ok": bool(replay_messages) or bool(timeline.get("record_chains")),
        "contract": RECORD_CHAIN_REPLAY_CONTRACT,
        "parent_tiandao_contract": RECORD_CHAIN_PARENT_TIANDAO_CONTRACT,
        "generated_at": ts(),
        "read_only": True,
        "write_performed": False,
        "raw_write_performed": False,
        "memory_write_performed": False,
        "platform_write_performed": False,
        "replay_kind": "record_chain",
        "not_memory_wall": True,
        "source_system": source_system,
        "session_id": replay_session_id,
        "record_chains": timeline.get("record_chains", []),
        "messages": replay_messages,
        "message_count": len(replay_messages),
        "notes": [
            "Replay shows indexed previews and raw availability, not full raw replacement.",
        ],
    }


def render_doctor_markdown(payload: dict[str, Any]) -> str:
    summary = _dict(payload.get("summary"))
    lines = [
        f"# Record Doctor: {payload.get('doctor_status', 'unknown')}",
        "",
        _safe_str(payload.get("headline")) or "-",
        "",
        f"- Records: {summary.get('record_guarded_count', 0)}/{summary.get('record_count', 0)} guarded",
        f"- Canonical messages: {summary.get('canonical_messages', 0)}",
        f"- Lost source (recoverable / unrecoverable / not measured): "
        f"{summary.get('lost_source_recoverable_count', 0)} / "
        f"{summary.get('lost_source_unrecoverable_count', 0)} / "
        f"{summary.get('lost_source_not_measured_count', 0)}",
        f"- Lost raw: {summary.get('lost_raw_count', 0)}",
        f"- Attention / backfill: {summary.get('raw_attention_count', 0)} / {summary.get('backfill_recommended_count', 0)}",
        "",
        "## Checks",
    ]
    for item in _list(payload.get("checks")):
        if not isinstance(item, dict):
            continue
        mark = "PASS" if item.get("ok") else "CHECK"
        lines.append(f"- {mark}: {item.get('label')} = {json.dumps(item.get('value'), ensure_ascii=False)}")
    actions = [_safe_str(item) for item in _list(payload.get("next_actions")) if _safe_str(item)]
    if actions:
        lines.extend(["", "## Next Actions"])
        lines.extend(f"- {item}" for item in actions)
    return "\n".join(lines) + "\n"
