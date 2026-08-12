#!/usr/bin/env python3
"""MCP runtime orchestration for raw_consumption_gateway.

This module keeps MCP initialize/tool dispatch, reading-area registry actions,
platform self-report receipts, and direct library_id borrowing outside the raw
HTTP recall gateway hot path. It is intentionally an orchestration layer; raw
recall, preflight, response budgeting, and Tiandao payload construction stay in
raw_consumption_gateway.
"""

from __future__ import annotations

import importlib
import json
import os
import re
import secrets
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Mapping, Optional, Tuple

try:
    from src.p4_provider import DEFAULT_CATALOG_TARGET_TOKENS as P4_DEFAULT_CATALOG_TARGET_TOKENS
except Exception:
    try:
        from p4_provider import DEFAULT_CATALOG_TARGET_TOKENS as P4_DEFAULT_CATALOG_TARGET_TOKENS
    except Exception:
        P4_DEFAULT_CATALOG_TARGET_TOKENS = 1500
try:
    from src.raw_gateway_mcp import (
        MCP_PROTOCOL_VERSION,
        _mcp_request_id,
        mcp_error,
        mcp_success,
    )
except Exception:
    from raw_gateway_mcp import (
        MCP_PROTOCOL_VERSION,
        _mcp_request_id,
        mcp_error,
        mcp_success,
    )
try:
    from src.source_system_runtime_declarations import source_system_from_consumer_name
except Exception:
    from source_system_runtime_declarations import source_system_from_consumer_name

UTC = timezone.utc
MCP_SERVER_NAME = "time-library"
MCP_LEGACY_SERVER_NAMES = ("time-library",)
STARTUP_CATALOG_TARGET_TOKENS = P4_DEFAULT_CATALOG_TARGET_TOKENS
STARTUP_CATALOG_DELIVERY_RECEIPT_CONTRACT = "time_library_startup_catalog_delivery_receipt.v1"
STARTUP_CATALOG_MODE_FULL = "full"
STARTUP_CATALOG_MODE_DEFERRED = "deferred"
PLATFORM_HANDSHAKE_RECEIPT_CONTRACT = "time_library_platform_handshake_receipt.v1"
PLATFORM_SELF_REPORT_QUESTIONS_CONTRACT = "time_library_platform_self_report_questions.v1"
PLATFORM_SELF_REPORT_RECEIPT_CONTRACT = "time_library_platform_self_report_receipt.v1"
MCP_SESSION_HEADER = "Mcp-Session-Id"
MCP_RESUME_REJECTION_CONTRACT = "time_library.mcp_resume_rejection.v1"
MCP_SESSION_TTL_SECONDS = 24 * 60 * 60
MCP_SESSION_MAX_RECALL_PROOFS = 20
_MCP_SESSIONS: Dict[str, Dict[str, Any]] = {}
_MCP_SESSION_LOCK = threading.Lock()
_MCP_SESSION_REQUEST_LOCKS: Dict[str, Any] = {}
READING_AREA_TOOL_ALLOWED_KEYS = {
    "action",
    "source_system",
    "platform_name",
    "consumer",
    "client_name",
    "client_version",
    "client_surface",
    "canonical_window_id",
    "session_id",
    "native_window_id",
    "title",
    "borrowing_card_id",
    "card_id",
    "reading_area",
    "declared_project_ids",
    "declared_series_ids",
    "declared_roles",
    "aliases",
    "record_type",
    "task_id",
    "task_name",
    "summary",
    "status",
    "role",
    "next_owner",
    "supersedes",
    "library_ids",
    "source_refs",
    "history_type",
    "nomination_id",
    "nominated_project",
    "nominated_series",
    "source_path",
    "reason",
    "confidence",
    "projects",
    "series",
    "limit",
    "statuses",
    "skill_surface_status",
    "config_write_authority",
    "proof_library_id",
    "request_id",
}


@contextmanager
def mcp_transport_session_request_guard(token: str) -> Iterator[None]:
    session_id = str(token or "").strip()
    if not session_id:
        yield
        return
    with _MCP_SESSION_LOCK:
        request_lock = _MCP_SESSION_REQUEST_LOCKS.get(session_id)
        if request_lock is None:
            request_lock = threading.RLock()
            if session_id in _MCP_SESSIONS:
                _MCP_SESSION_REQUEST_LOCKS[session_id] = request_lock
    with request_lock:
        yield


def _new_mcp_transport_session(
    params: Dict[str, Any],
    *,
    resume_token: str = "",
) -> Tuple[str, Dict[str, Any]]:
    client_info = params.get("clientInfo") if isinstance(params.get("clientInfo"), dict) else {}
    client_name = re.sub(r"\s+", " ", str(client_info.get("name") or "")).strip()[:200]
    client_version = re.sub(r"\s+", " ", str(client_info.get("version") or "")).strip()[:120]
    token = secrets.token_urlsafe(32)
    resumed_connection: Dict[str, Any] = {}
    resume_rejected_reason = ""
    candidate_token = str(resume_token or "").strip()
    if candidate_token:
        verification = _delivery_runtime().rotate_verified_host_connection_resume(
            {"transport_session_id": candidate_token},
            {"transport_session_id": token},
            initialized_client_name=client_name,
            initialized_client_version=client_version,
            inferred_platform_hint=(
                source_system_from_consumer_name(client_name.lower()) if client_name else ""
            ),
        )
        if verification.get("ok") is True:
            resumed_connection = verification
        else:
            resume_rejected_reason = str(verification.get("error") or "")
    now = time.time()
    context = {
        "transport_session_id": token,
        "initialized": True,
        "client_info_present": bool(client_name),
        "client_name": client_name,
        "client_version": client_version,
        "inferred_platform_hint": source_system_from_consumer_name(client_name.lower()) if client_name else "",
        "created_at_epoch": now,
        "last_seen_epoch": now,
        "self_report_verified": bool(resumed_connection),
        "verified_platform": str(resumed_connection.get("platform") or ""),
        "connection_receipt_id": str(resumed_connection.get("receipt_id") or ""),
        "resumed_verified_connection": bool(resumed_connection),
        "resume_requested": bool(candidate_token),
        "resume_rejected_reason": resume_rejected_reason,
    }
    with _MCP_SESSION_LOCK:
        cutoff = now - MCP_SESSION_TTL_SECONDS
        stale = [
            session_id
            for session_id, item in _MCP_SESSIONS.items()
            if float(item.get("last_seen_epoch") or 0.0) < cutoff
        ]
        for session_id in stale:
            _MCP_SESSIONS.pop(session_id, None)
            _MCP_SESSION_REQUEST_LOCKS.pop(session_id, None)
        if resumed_connection:
            _MCP_SESSIONS.pop(candidate_token, None)
            _MCP_SESSION_REQUEST_LOCKS.pop(candidate_token, None)
        if not candidate_token or resumed_connection:
            _MCP_SESSIONS[token] = context
    return token, dict(context)


def new_mcp_transport_session(
    params: Dict[str, Any],
    *,
    resume_token: str = "",
) -> Tuple[str, Dict[str, Any]]:
    with mcp_transport_session_request_guard(resume_token):
        return _new_mcp_transport_session(
            params,
            resume_token=resume_token,
        )


def mcp_transport_session(token: str) -> Dict[str, Any]:
    session_id = str(token or "").strip()
    if not session_id:
        return {}
    now = time.time()
    with _MCP_SESSION_LOCK:
        context = _MCP_SESSIONS.get(session_id)
        if not isinstance(context, dict):
            return {}
        if now - float(context.get("last_seen_epoch") or 0.0) > MCP_SESSION_TTL_SECONDS:
            _MCP_SESSIONS.pop(session_id, None)
            _MCP_SESSION_REQUEST_LOCKS.pop(session_id, None)
            return {}
        context["last_seen_epoch"] = now
        return dict(context)


def mcp_resume_rejection(
    request_id: Any,
    connection_context: Optional[Mapping[str, Any]],
) -> Dict[str, Any] | None:
    context = connection_context if isinstance(connection_context, Mapping) else {}
    if not context.get("resume_requested") or context.get("resumed_verified_connection") is True:
        return None
    rejection = mcp_error(
        request_id,
        -32002,
        "MCP verified session resume rejected; original request was not sent",
    )
    rejection["error"]["data"] = {
        "contract": MCP_RESUME_REJECTION_CONTRACT,
        "reason": str(
            context.get("resume_rejected_reason") or "verified_host_connection_required"
        ),
        "request_dispatched": False,
        "session_issued": False,
        "safe_to_retry_without_user_reverification": False,
    }
    return rejection


def mark_mcp_transport_session_verified(token: str, response: Dict[str, Any]) -> None:
    result = response.get("result") if isinstance(response.get("result"), dict) else {}
    structured = result.get("structuredContent") if isinstance(result.get("structuredContent"), dict) else {}
    if structured.get("self_report_verified") is not True:
        return
    client_info = structured.get("client_info") if isinstance(structured.get("client_info"), dict) else {}
    platform = str(client_info.get("self_reported_platform") or "").strip()
    connection_receipt = structured.get("connection_receipt") if isinstance(structured.get("connection_receipt"), dict) else {}
    if not platform or connection_receipt.get("ok") is not True:
        return
    with _MCP_SESSION_LOCK:
        context = _MCP_SESSIONS.get(token)
        if not isinstance(context, dict):
            return
        context["self_report_verified"] = True
        context["verified_platform"] = platform
        context["connection_receipt_id"] = str(connection_receipt.get("receipt_id") or "")


def mark_mcp_transport_session_capability_check(
    token: str,
    request: Dict[str, Any],
    response: Dict[str, Any],
) -> None:
    if str(request.get("method") or "") != "tools/call":
        return
    params = request.get("params") if isinstance(request.get("params"), dict) else {}
    if str(params.get("name") or "") not in {"time_library_recall", "zhiyi_recall"}:
        return
    arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
    if not _is_capability_check_request(arguments):
        return
    result = response.get("result") if isinstance(response.get("result"), dict) else {}
    structured = result.get("structuredContent") if isinstance(result.get("structuredContent"), dict) else {}
    if not (
        structured.get("ok") is True
        and structured.get("mode") == "capability_check"
        and structured.get("recall_performed") is False
        and structured.get("raw_excerpt_returned") is False
        and structured.get("write_performed") is False
    ):
        return
    with _MCP_SESSION_LOCK:
        context = _MCP_SESSIONS.get(token)
        if not isinstance(context, dict):
            return
        context["capability_check_observed_at_epoch"] = time.time()
        context["capability_check_request_id"] = str(request.get("id") or "")[:160]
        context.pop("real_recall_proofs", None)


def mcp_real_recall_proofs(
    request: Dict[str, Any],
    response: Dict[str, Any],
) -> List[Dict[str, Any]]:
    if str(request.get("method") or "") != "tools/call":
        return []
    params = request.get("params") if isinstance(request.get("params"), dict) else {}
    if str(params.get("name") or "") not in {"time_library_recall", "zhiyi_recall"}:
        return []
    arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
    mode = str(arguments.get("mode") or arguments.get("recall_mode") or "").strip().lower()
    if (
        _is_capability_check_request(arguments)
        or _is_preflight_request(arguments)
        or _is_work_preflight_request(arguments)
        or mode == "startup_preflight"
    ):
        return []
    result = response.get("result") if isinstance(response.get("result"), dict) else {}
    structured = result.get("structuredContent") if isinstance(result.get("structuredContent"), dict) else {}
    items = structured.get("items") if isinstance(structured.get("items"), list) else []
    if int(structured.get("matched_count") or 0) < 1 or not items:
        return []
    consumer_receipt = (
        structured.get("consumer_receipt")
        if isinstance(structured.get("consumer_receipt"), dict)
        else {}
    )
    used_source_refs = consumer_receipt.get("used_source_refs")
    source_refs_count = len(used_source_refs) if isinstance(used_source_refs, list) else 0
    if source_refs_count < 1:
        return []
    common = {
        "matched_count": int(structured.get("matched_count") or 0),
        "source_refs_count": source_refs_count,
        "raw_excerpt_returned": bool(structured.get("raw_excerpt_returned")),
        "recall_source_system_filter": str(arguments.get("source_system") or "").strip()[:120],
        "canonical_window_id": str(arguments.get("canonical_window_id") or "").strip()[:220],
        "session_id": str(arguments.get("session_id") or "").strip()[:220],
        "observed_at_epoch": time.time(),
    }
    proofs: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        library_id = str(item.get("library_id") or "").strip()[:160]
        if not library_id or library_id in seen:
            continue
        seen.add(library_id)
        proofs.append({"library_id": library_id, **common})
    return proofs


def mark_mcp_transport_session_recall_proof(
    token: str,
    request: Dict[str, Any],
    response: Dict[str, Any],
) -> None:
    proofs = mcp_real_recall_proofs(request, response)
    if not proofs:
        return
    with _MCP_SESSION_LOCK:
        context = _MCP_SESSIONS.get(token)
        if not isinstance(context, dict):
            return
        capability_observed_at = float(context.get("capability_check_observed_at_epoch") or 0.0)
        if capability_observed_at <= 0.0:
            return
        existing = context.get("real_recall_proofs")
        proof_map = dict(existing) if isinstance(existing, dict) else {}
        for proof in proofs:
            if float(proof.get("observed_at_epoch") or 0.0) < capability_observed_at:
                continue
            proof_map[proof["library_id"]] = proof
        if len(proof_map) > MCP_SESSION_MAX_RECALL_PROOFS:
            ordered = sorted(
                proof_map.items(),
                key=lambda item: float((item[1] or {}).get("observed_at_epoch") or 0.0),
                reverse=True,
            )[:MCP_SESSION_MAX_RECALL_PROOFS]
            proof_map = dict(ordered)
        context["real_recall_proofs"] = proof_map


def _gateway():
    try:
        return importlib.import_module("src.raw_consumption_gateway")
    except Exception:
        return importlib.import_module("raw_consumption_gateway")


def _delivery_runtime():
    try:
        return importlib.import_module("src.time_library_delivery_runtime")
    except Exception:
        return importlib.import_module("time_library_delivery_runtime")


def _service_version() -> str:
    return str(getattr(_gateway(), "SERVICE_VERSION", ""))


def ts() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _first_text(*values: Any) -> str:
    for value in values:
        text = _clean_text(value)
        if text:
            return text
    return ""


def _truthy(value: Any) -> bool:
    return _gateway()._truthy(value)


def _records_db_path_for_gateway():
    return _gateway()._records_db_path_for_gateway()


def _consumer_receipt(*args, **kwargs):
    return _gateway()._consumer_receipt(*args, **kwargs)


def _is_raw_evidence_status(status: str) -> bool:
    return _gateway()._is_raw_evidence_status(status)


def _is_capability_check_request(args: Dict[str, Any]) -> bool:
    return _gateway()._is_capability_check_request(args)


def _is_preflight_request(args: Dict[str, Any]) -> bool:
    return _gateway()._is_preflight_request(args)


def _is_work_preflight_request(args: Dict[str, Any]) -> bool:
    return _gateway()._is_work_preflight_request(args)


def _preflight_kwargs_from_args(
    args: Dict[str, Any],
    *,
    consumer_default: str,
    limit_default: int,
    excerpt_default: int,
    binding_identity: Optional[str] = None,
) -> Dict[str, Any]:
    return _gateway()._preflight_kwargs_from_args(
        args,
        consumer_default=consumer_default,
        limit_default=limit_default,
        excerpt_default=excerpt_default,
        binding_identity=binding_identity,
    )


def _work_preflight_from_kwargs(kwargs: Dict[str, Any]) -> Dict[str, Any]:
    return _gateway()._work_preflight_from_kwargs(kwargs)


def capability_check_payload(*args, **kwargs):
    return _gateway().capability_check_payload(*args, **kwargs)


def preflight_payload(*args, **kwargs):
    return _gateway().preflight_payload(*args, **kwargs)


def query_raw_source_refs(*args, **kwargs):
    return _gateway().query_raw_source_refs(*args, **kwargs)


def compact_recall_payload(*args, **kwargs):
    return _gateway().compact_recall_payload(*args, **kwargs)


def _response_budget_mode(args: Dict[str, Any]) -> str:
    return _gateway()._response_budget_mode(args)


def _include_raw_excerpt(args: Dict[str, Any]) -> bool:
    return _gateway()._include_raw_excerpt(args)


def _mcp_binding_identity(
    connection_context: Optional[Mapping[str, Any]],
) -> Optional[str]:
    if connection_context is None:
        return None
    verification = _delivery_runtime().verified_host_connection(connection_context)
    if verification.get("ok") is not True:
        return ""
    return _clean_text(verification.get("platform"))


def mcp_tools_payload() -> Dict[str, Any]:
    return _gateway().mcp_tools_payload()

def _library_id_from_args(args: Dict[str, Any]) -> str:
    pattern = r"(?:ZX|WB|PH)-[A-Z0-9]+(?:-[A-Z0-9]+)*"
    value = _clean_text(args.get("library_id"))
    if re.fullmatch(pattern, value.upper()):
        return value.upper()
    query = _clean_text(args.get("query") or args.get("q"))
    if re.fullmatch(pattern, query.upper()):
        return query.upper()
    return ""


def _catalog_card_item_from_result(result: Dict[str, Any]) -> Dict[str, Any]:
    card = result.get("card") if isinstance(result.get("card"), dict) else {}
    refs = result.get("source_refs") if isinstance(result.get("source_refs"), dict) else {}
    excerpt_ref = result.get("raw_source_excerpt_ref") if isinstance(result.get("raw_source_excerpt_ref"), dict) else {}
    source_path = _first_text(
        refs.get("resolved_source_path"),
        refs.get("source_path"),
        excerpt_ref.get("source_path"),
    )
    byte_offsets = refs.get("byte_offsets") if isinstance(refs.get("byte_offsets"), dict) else {}
    if not byte_offsets and isinstance(excerpt_ref.get("byte_offsets"), dict):
        byte_offsets = excerpt_ref.get("byte_offsets")
    raw_excerpt = _first_text(result.get("raw_source_excerpt"), result.get("verbatim_excerpt"))
    return {
        "library_id": result.get("library_id", ""),
        "library_shelf": result.get("shelf") or card.get("shelf", ""),
        "type": card.get("type", ""),
        "memory_type": card.get("type", ""),
        "summary": card.get("summary") or card.get("title") or "",
        "source_system": refs.get("source_system", ""),
        "computer_name": refs.get("computer_name") or refs.get("computer_id", ""),
        "canonical_window_id": refs.get("canonical_window_id", ""),
        "session_id": refs.get("session_id", ""),
        "project_id": refs.get("project_id", ""),
        "project_root": refs.get("project_root") or refs.get("workspace_root") or refs.get("cwd") or "",
        "source_path": source_path,
        "msg_ids": refs.get("msg_ids", []) or ([refs.get("message_id")] if refs.get("message_id") else []),
        "byte_offsets": byte_offsets,
        "artifact_type": refs.get("artifact_type") or card.get("artifact_type", ""),
        "raw_excerpt": raw_excerpt,
        "raw_evidence_status": "raw" if raw_excerpt else "not_raw",
        "zhiyi_experience_used_as_raw": False,
        "matched_by": ["library_id_exact"],
        "rank_reason": "library_id_exact_borrow",
    }


def _catalog_card_borrow_payload(
    library_id: str,
    *,
    consumer: str,
    request_id: str,
    borrowing_card_id: str = "",
    project_id: str = "",
    series_id: str = "",
    reading_area_id: str = "",
) -> Dict[str, Any]:
    try:
        from src.p4_provider import fetch_catalog_card_by_library_id
    except Exception:
        from p4_provider import fetch_catalog_card_by_library_id

    result = fetch_catalog_card_by_library_id(
        library_id,
        records_db_path=str(_records_db_path_for_gateway()),
        reading_area_registry_path=os.environ.get("MEMCORE_READING_AREA_REGISTRY", ""),
        include_raw_index=True,
        project_ids=[project_id] if project_id else None,
        series_ids=[series_id] if series_id else None,
        borrowing_card_id=borrowing_card_id,
        consumer=consumer,
        request_id=request_id,
        reading_area_id=reading_area_id,
        project_id=project_id,
        series_id=series_id,
    )
    item = _catalog_card_item_from_result(result) if result.get("ok") else {}
    items = [item] if item else []
    source_refs_count = 1 if item.get("source_path") else 0
    raw_items_count = 1 if _is_raw_evidence_status(item.get("raw_evidence_status", "")) else 0
    receipt = _consumer_receipt(
        consumer,
        request_id,
        len(items),
        source_refs_count,
        raw_items_count,
        items,
    )
    receipt["query_path"] = "/catalog-card"
    receipt["receipt_scope"] = "library_id_direct_borrow"
    return {
        "ok": bool(result.get("ok")),
        "mode": "library_card_borrow",
        "query": library_id,
        "library_id": library_id,
        "read_only": True,
        "write_performed": False,
        "platform_write_performed": False,
        "recall_performed": False,
        "matched_count": len(items),
        "source_refs_count": source_refs_count,
        "raw_items_count": raw_items_count,
        "raw_excerpt_returned": bool(item.get("raw_excerpt")),
        "catalog_card": result,
        "items": items,
        "consumer_receipt": receipt,
        "response_budget": {
            "mode": "library_card_borrow",
            "items_returned": len(items),
            "items_available": len(items),
            "raw_excerpt_returned": bool(item.get("raw_excerpt")),
            "omitted_large_fields": [],
        },
        "error": result.get("error", ""),
    }

def _startup_catalog_inject_payload(target_tokens: int = STARTUP_CATALOG_TARGET_TOKENS) -> Dict[str, Any]:
    """Build passive startup catalog delivery for MCP initialize.

    This is the clean split startup path: it reuses the catalog/p4 candidate
    loader and stays silent when no clean catalog exists.
    """
    try:
        from src.p4_provider import build_catalog_inject_from_candidates
    except Exception:
        try:
            from p4_provider import build_catalog_inject_from_candidates
        except Exception as exc:
            return {
                "ok": False,
                "should_inject": False,
                "error": f"catalog_builder_unavailable:{type(exc).__name__}",
            }
    try:
        payload = build_catalog_inject_from_candidates(target_tokens=target_tokens)
    except Exception as exc:
        return {
            "ok": False,
            "should_inject": False,
            "error": f"catalog_build_failed:{type(exc).__name__}:{exc}",
        }
    if not isinstance(payload, dict) or not payload.get("ok") or not payload.get("should_inject"):
        return {
            "ok": False,
            "should_inject": False,
            "error": payload.get("error", "startup_catalog_empty") if isinstance(payload, dict) else "startup_catalog_empty",
            "catalog_entry_count": int(payload.get("catalog_entry_count") or 0) if isinstance(payload, dict) else 0,
        }
    receipt = {
        "ok": True,
        "contract": STARTUP_CATALOG_DELIVERY_RECEIPT_CONTRACT,
        "delivery_layer": "mcp_initialize_instructions",
        "server": MCP_SERVER_NAME,
        "passive_delivery": True,
        "consumer_invoked_tool": False,
        "consumer_called_catalog_endpoint": False,
        "new_window_startup_auto_injection": True,
        "received_by": "naked_mcp_consumer_initialize",
        "delivered_at": ts(),
        "catalog_entry_count": int(payload.get("catalog_entry_count") or 0),
        "catalog_token_count": int(payload.get("catalog_token_count") or 0),
        "inject_token_count": int(payload.get("inject_token_count") or 0),
        "system_prompt_token_count": int(payload.get("system_prompt_token_count") or payload.get("inject_token_count") or 0),
        "startup_instruction_mode": payload.get("startup_instruction_mode", ""),
        "flat_catalog_prompt_omitted": bool(payload.get("flat_catalog_prompt_omitted", False)),
        "instructions_char_count": int(payload.get("instructions_char_count") or 0),
        "instructions_byte_count": int(payload.get("instructions_byte_count") or 0),
        "startup_instructions_char_budget": int(payload.get("startup_instructions_char_budget") or 0),
        "reading_area_project_page_count": int(payload.get("reading_area_project_page_count") or 0),
        "reading_area_toc_token_count": int(payload.get("reading_area_toc_token_count") or 0),
        "reading_area_block_token_count": int(payload.get("reading_area_block_token_count") or 0),
        "reading_area_raw_index": payload.get("reading_area_raw_index", {}),
        "target_tokens": int(payload.get("target_tokens") or target_tokens),
        "contains_body_markers": bool(payload.get("contains_body_markers", False)),
        "reading_area_contains_body_markers": bool(payload.get("reading_area_contains_body_markers", False)),
        "no_window_binding_required": bool(payload.get("no_window_binding_required", True)),
        "library_id_pull_endpoint": "/catalog-card",
        "library_id_pull_available": True,
        "read_only": True,
        "write_performed": False,
        "platform_write_performed": False,
        "body_pushed": False,
    }
    return {
        **payload,
        "startup_catalog_delivery_receipt": receipt,
    }


def _platform_from_client_name(name: str) -> str:
    lowered = str(name or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not lowered:
        return "unknown_mcp_client"
    platform = source_system_from_consumer_name(lowered)
    if platform:
        return platform
    return lowered[:80] or "unknown_mcp_client"


def _sanitize_client_info_field(value: Any, *, max_chars: int = 120) -> str:
    text = str(value or "")
    text = re.sub(r"[\x00-\x1f\x7f]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_chars:
        return text[: max_chars - 1].rstrip() + "…"
    return text


def _platform_self_report_questions(inferred_platform: str) -> List[Dict[str, Any]]:
    return [
        {
            "id": "platform_identity",
            "question": "Which host platform and client surface are you connecting from?",
            "expected_answer": "platform_name_and_client_surface",
            "required_before_registration": True,
        },
        {
            "id": "mcp_capability",
            "question": "Can this client call the Time Library MCP tools after initialize?",
            "expected_answer": "capability_check_result_only_no_memory_recall",
            "required_before_registration": True,
        },
        {
            "id": "skill_surface",
            "question": "Does this client expose a skill/custom-instruction surface for Time Library guidance?",
            "expected_answer": "skill_or_instruction_surface_status",
            "required_before_registration": True,
        },
        {
            "id": "config_write_authority",
            "question": "Did the host agent have authority to configure its own MCP or instruction surface?",
            "expected_answer": "host_owned_configuration_authority_status",
            "required_before_registration": True,
        },
        {
            "id": "declared_project_series",
            "question": "Which reading-area project and series does this window declare?",
            "expected_answer": "declared_project_ids_and_series_ids",
            "required_before_registration": True,
        },
        {
            "id": "post_connect_proof",
            "question": "After capability_check and one user-authorized real recall, can the client submit that recall's library_id in this same MCP session and replay the recall after verification?",
            "expected_answer": "same_session_recall_proof_then_verified_replay",
            "required_before_registration": True,
        },
    ]


def _platform_self_report_policy(client_info_present: bool, inferred_platform: str) -> Dict[str, Any]:
    questions = _platform_self_report_questions(inferred_platform) if client_info_present else []
    return {
        "contract": PLATFORM_SELF_REPORT_QUESTIONS_CONTRACT,
        "read_only": True,
        "write_performed": False,
        "platform_write_performed": False,
        "memory_write_performed": False,
        "question_source": "static_read_only_handshake_contract",
        "inferred_platform_hint": inferred_platform,
        "identity_authority": "host_self_report",
        "inference_is_non_authoritative": True,
        "answers_expected_from": "connecting_platform_or_client_after_initialize",
        "answers_observed": False,
        "answers_verified": False,
        "question_count": len(questions),
        "no_user_prompt_performed": True,
        "registration_effect": "questions_do_not_register_without_capability_check_and_real_recall",
        "questions": questions,
        "blockers": ["self_report_answers_not_observed", "self_report_not_verified"] if questions else [],
    }


def _platform_handshake_receipt(params: Dict[str, Any] | None = None) -> Dict[str, Any]:
    params = params if isinstance(params, dict) else {}
    client_info = params.get("clientInfo") if isinstance(params.get("clientInfo"), dict) else {}
    client_name = _sanitize_client_info_field(client_info.get("name"))
    client_version = _sanitize_client_info_field(client_info.get("version"))
    client_info_present = bool(client_name or client_version)
    inferred_platform = _platform_from_client_name(client_name)
    self_report_policy = _platform_self_report_policy(client_info_present, inferred_platform)
    blockers = []
    if not client_info_present:
        blockers.append("clientInfo_missing_from_mcp_initialize")
    blockers.extend([
        "handshake_not_verified_beyond_client_info",
        "capability_check_not_performed",
        "real_recall_not_proven",
    ])
    blockers.extend(self_report_policy.get("blockers", []))
    return {
        "contract": PLATFORM_HANDSHAKE_RECEIPT_CONTRACT,
        "evidence_source": "mcp_initialize.params.clientInfo",
        "client_info_present": client_info_present,
        "client_name": client_name,
        "client_version": client_version,
        "inferred_platform": inferred_platform,
        "inferred_platform_hint": inferred_platform,
        "identity_authority": "host_self_report_not_yet_observed",
        "current_stage": "client_info_observed" if client_info_present else "client_info_missing",
        "lifecycle_order": [
            "discovered",
            "client_info_observed",
            "handshake_verified",
            "capability_check_proven",
            "real_recall_proven",
            "registered",
        ],
        "handshake_observed": client_info_present,
        "handshake_verified": False,
        "verification_level": "client_info_observed_only" if client_info_present else "none",
        "capability_check_performed": False,
        "real_recall_performed": False,
        "recall_proven": False,
        "registered": False,
        "registration_blockers": blockers,
        "next_actions": [
            "run_capability_check_after_connect",
            "run_real_recall_before_marking_registered",
        ],
        "read_only": True,
        "platform_write_performed": False,
        "memory_write_performed": False,
        "chat_body_included": False,
        "raw_excerpt_included": False,
        "client_info_redaction_policy": "name_version_only",
        "client_info_sanitized": True,
        "self_report_policy": {
            key: value for key, value in self_report_policy.items() if key != "questions"
        },
        "platform_self_report_questions": self_report_policy["questions"],
        "self_report_answers_observed": False,
        "self_report_verified": False,
        "self_report_blockers": self_report_policy["blockers"],
    }


def _normalize_startup_catalog_mode(value: Any) -> str:
    mode = str(value or "").strip().lower()
    return STARTUP_CATALOG_MODE_DEFERRED if mode == STARTUP_CATALOG_MODE_DEFERRED else STARTUP_CATALOG_MODE_FULL


def build_mcp_initialize_result(
    params: Dict[str, Any] | None = None,
    *,
    startup_catalog_mode: str = STARTUP_CATALOG_MODE_FULL,
) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "protocolVersion": MCP_PROTOCOL_VERSION,
        "capabilities": {"tools": {}},
        "serverInfo": {
            "name": MCP_SERVER_NAME,
            "version": _service_version(),
            "legacyNames": MCP_LEGACY_SERVER_NAMES,
        },
        "platformHandshakeReceipt": _platform_handshake_receipt(params),
    }
    resolved_catalog_mode = _normalize_startup_catalog_mode(startup_catalog_mode)
    if resolved_catalog_mode == STARTUP_CATALOG_MODE_DEFERRED:
        result["instructions"] = (
            "Time Library is available on demand through time_library_recall. "
            "Startup catalog content is deferred for this native-preflight client."
        )
        result["startupCatalog"] = {
            "ok": True,
            "delivery": "deferred_native_preflight_client",
            "catalog_entry_count": 0,
            "catalog": [],
            "contains_body_markers": False,
            "private_catalog_text_delivered": False,
        }
        result["startupCatalogDeliveryReceipt"] = {
            "ok": True,
            "contract": STARTUP_CATALOG_DELIVERY_RECEIPT_CONTRACT,
            "delivery_layer": "mcp_initialize_deferred",
            "server": MCP_SERVER_NAME,
            "passive_delivery": False,
            "consumer_invoked_tool": False,
            "consumer_called_catalog_endpoint": False,
            "new_window_startup_auto_injection": False,
            "catalog_entry_count": 0,
            "contains_body_markers": False,
            "private_catalog_text_delivered": False,
            "read_only": True,
            "write_performed": False,
            "platform_write_performed": False,
            "body_pushed": False,
        }
        return result
    catalog = _startup_catalog_inject_payload()
    if catalog.get("ok") and catalog.get("should_inject") and catalog.get("system_prompt"):
        result["instructions"] = str(catalog.get("system_prompt") or "")
        result["startupCatalog"] = {
            "ok": True,
            "delivery": "passive_mcp_initialize_instructions",
            "catalog_entry_count": catalog.get("catalog_entry_count", 0),
            "catalog_token_count": catalog.get("catalog_token_count", 0),
            "inject_token_count": catalog.get("inject_token_count", 0),
            "system_prompt_token_count": catalog.get("system_prompt_token_count", catalog.get("inject_token_count", 0)),
            "startup_instruction_mode": catalog.get("startup_instruction_mode", ""),
            "flat_catalog_prompt_omitted": catalog.get("flat_catalog_prompt_omitted", False),
            "instructions_char_count": catalog.get("instructions_char_count", 0),
            "instructions_byte_count": catalog.get("instructions_byte_count", 0),
            "startup_instructions_char_budget": catalog.get("startup_instructions_char_budget", 0),
            "reading_area_project_page_count": catalog.get("reading_area_project_page_count", 0),
            "reading_area_toc_token_count": catalog.get("reading_area_toc_token_count", 0),
            "reading_area_block_token_count": catalog.get("reading_area_block_token_count", 0),
            "reading_area_raw_index": catalog.get("reading_area_raw_index", {}),
            "reading_area_contains_body_markers": catalog.get("reading_area_contains_body_markers", False),
            "target_tokens": catalog.get("target_tokens", STARTUP_CATALOG_TARGET_TOKENS),
            "contains_body_markers": catalog.get("contains_body_markers", False),
            "no_window_binding_required": catalog.get("no_window_binding_required", True),
            "catalog": catalog.get("catalog", []),
        }
        result["startupCatalogDeliveryReceipt"] = catalog.get("startup_catalog_delivery_receipt", {})
    return result


def _bounded_self_report_text(value: Any, *, limit: int = 200) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit]


def _self_report_list(value: Any) -> List[str]:
    raw = value if isinstance(value, list) else ([] if value in (None, "") else [value])
    seen: set[str] = set()
    result: List[str] = []
    for item in raw:
        original = re.sub(r"\s+", " ", str(item or "")).strip()
        if original and original not in seen:
            seen.add(original)
            result.append(original[:160])
    return result


def _import_reading_area_registry():
    try:
        from src import reading_area_registry as registry
    except Exception:
        import reading_area_registry as registry
    return registry


def _issue_reading_area_borrowing_card(
    args: Dict[str, Any],
    *,
    verified_card_id: str = "",
) -> Dict[str, Any]:
    client_name = _sanitize_client_info_field(args.get("client_name"))
    source_system = _bounded_self_report_text(
        args.get("source_system"),
        limit=120,
    ).lower().replace("-", "_")
    if not source_system:
        return {
            "ok": False,
            "mode": "reading_area_borrowing_card",
            "contract": "time_library_reading_area_borrowing_card_mcp.v1",
            "error": "source_system_self_report_required",
            "registry_write_performed": False,
            "write_performed": False,
            "platform_write_performed": False,
            "memory_write_performed": False,
            "raw_write_performed": False,
            "reading_area_content_write_performed": False,
        }
    registry = _import_reading_area_registry()
    if verified_card_id:
        resolved = registry.resolve_borrowing_card(
            card_id=verified_card_id,
            source_system=source_system,
            path=os.environ.get("MEMCORE_READING_AREA_REGISTRY", "") or None,
        )
        if not resolved.get("ok"):
            return {
                **resolved,
                "mode": "reading_area_borrowing_card",
                "contract": "time_library_reading_area_borrowing_card_mcp.v1",
                "registry_write_performed": False,
                "write_performed": False,
                "platform_write_performed": False,
                "memory_write_performed": False,
                "raw_write_performed": False,
                "reading_area_content_write_performed": False,
            }
        return {
            "ok": True,
            "mode": "reading_area_borrowing_card",
            "contract": "time_library_reading_area_borrowing_card_mcp.v1",
            "registry_path": str(registry.registry_path(os.environ.get("MEMCORE_READING_AREA_REGISTRY", "") or None)),
            "card": resolved["card"],
            "card_id": verified_card_id,
            "idempotent": True,
            "identity_authority": "verified_host_connection_receipt",
            "registry_write_performed": False,
            "write_performed": False,
            "platform_write_performed": False,
            "memory_write_performed": False,
            "raw_write_performed": False,
            "reading_area_content_write_performed": False,
        }
    consumer = _bounded_self_report_text(args.get("consumer") or source_system, limit=120)
    result = registry.ensure_borrowing_card(
        source_system=source_system,
        consumer=consumer,
        canonical_window_id=_bounded_self_report_text(args.get("canonical_window_id"), limit=200),
        session_id=_bounded_self_report_text(args.get("session_id"), limit=200),
        native_window_id=_bounded_self_report_text(args.get("native_window_id"), limit=200),
        title=_bounded_self_report_text(args.get("title") or client_name, limit=200),
        declared_by="mcp_platform_self_report",
        path=os.environ.get("MEMCORE_READING_AREA_REGISTRY", "") or None,
    )
    return {
        **result,
        "mode": "reading_area_borrowing_card",
        "contract": "time_library_reading_area_borrowing_card_mcp.v1",
        "registry_write_performed": bool(result.get("ok")),
        "write_performed": bool(result.get("ok")),
        "platform_write_performed": False,
        "memory_write_performed": False,
        "raw_write_performed": False,
        "reading_area_content_write_performed": False,
    }


def _declare_reading_area_membership(args: Dict[str, Any], *, card_id: str = "") -> Dict[str, Any]:
    registry = _import_reading_area_registry()
    selected_card_id = _bounded_self_report_text(card_id or args.get("borrowing_card_id") or args.get("card_id"), limit=220)
    result = registry.declare_membership(
        card_id=selected_card_id,
        reading_area=_bounded_self_report_text(args.get("reading_area"), limit=200),
        projects=_self_report_list(args.get("declared_project_ids") or args.get("projects")),
        series=_self_report_list(args.get("declared_series_ids") or args.get("series")),
        roles=_self_report_list(args.get("declared_roles") or args.get("roles")),
        aliases=_self_report_list(args.get("aliases")),
        path=os.environ.get("MEMCORE_READING_AREA_REGISTRY", "") or None,
    )
    return {
        **result,
        "mode": "reading_area_membership",
        "contract": "time_library_reading_area_membership_mcp.v1",
        "registry_write_performed": bool(result.get("ok")),
        "write_performed": bool(result.get("ok")),
        "platform_write_performed": False,
        "memory_write_performed": False,
        "raw_write_performed": False,
        "reading_area_content_write_performed": False,
        "technical_project_id_used_as_declared_identity": False,
    }


def _whiteboard_write_payload(args: Dict[str, Any]) -> Dict[str, Any]:
    registry = _import_reading_area_registry()
    result = registry.write_whiteboard_record(
        borrowing_card_id=_bounded_self_report_text(args.get("borrowing_card_id") or args.get("card_id"), limit=220),
        source_system=_bounded_self_report_text(args.get("source_system"), limit=120),
        canonical_window_id=_bounded_self_report_text(args.get("canonical_window_id"), limit=200),
        session_id=_bounded_self_report_text(args.get("session_id"), limit=200),
        consumer=_bounded_self_report_text(args.get("consumer"), limit=120),
        record_type=_bounded_self_report_text(args.get("record_type"), limit=60),
        task_id=_bounded_self_report_text(args.get("task_id"), limit=120),
        task_name=_bounded_self_report_text(args.get("task_name"), limit=120),
        summary=_bounded_self_report_text(args.get("summary"), limit=240),
        status=_bounded_self_report_text(args.get("status"), limit=60),
        role=_bounded_self_report_text(args.get("role"), limit=80),
        next_owner=_bounded_self_report_text(args.get("next_owner"), limit=120),
        supersedes=_self_report_list(args.get("supersedes")),
        library_ids=_self_report_list(args.get("library_ids")),
        source_refs=args.get("source_refs"),
        request_id=_bounded_self_report_text(args.get("request_id"), limit=160),
        path=os.environ.get("MEMCORE_READING_AREA_REGISTRY", "") or None,
    )
    return {
        **result,
        "mode": "whiteboard_write",
        "contract": "time_library_whiteboard_write_receipt.v1",
        "platform_write_performed": False,
        "memory_write_performed": False,
        "raw_write_performed": False,
        "reading_area_content_write_performed": False,
    }


def _whiteboard_list_payload(args: Dict[str, Any]) -> Dict[str, Any]:
    registry = _import_reading_area_registry()
    result = registry.list_whiteboard_records(
        borrowing_card_id=_bounded_self_report_text(args.get("borrowing_card_id") or args.get("card_id"), limit=220),
        source_system=_bounded_self_report_text(args.get("source_system"), limit=120),
        canonical_window_id=_bounded_self_report_text(args.get("canonical_window_id"), limit=200),
        session_id=_bounded_self_report_text(args.get("session_id"), limit=200),
        consumer=_bounded_self_report_text(args.get("consumer"), limit=120),
        reading_area_ids=_self_report_list(args.get("reading_area") or args.get("declared_reading_area_ids")),
        project_ids=_self_report_list(args.get("declared_project_ids") or args.get("projects")),
        series_ids=_self_report_list(args.get("declared_series_ids") or args.get("series")),
        statuses=_self_report_list(args.get("statuses")),
        limit=int(args.get("limit") or 20),
        path=os.environ.get("MEMCORE_READING_AREA_REGISTRY", "") or None,
    )
    return {
        **result,
        "mode": "whiteboard_list",
        "platform_write_performed": False,
        "memory_write_performed": False,
        "raw_write_performed": False,
        "reading_area_content_write_performed": False,
    }


def _project_history_write_payload(args: Dict[str, Any]) -> Dict[str, Any]:
    registry = _import_reading_area_registry()
    result = registry.write_project_history_record(
        borrowing_card_id=_bounded_self_report_text(args.get("borrowing_card_id") or args.get("card_id"), limit=220),
        source_system=_bounded_self_report_text(args.get("source_system"), limit=120),
        canonical_window_id=_bounded_self_report_text(args.get("canonical_window_id"), limit=200),
        session_id=_bounded_self_report_text(args.get("session_id"), limit=200),
        consumer=_bounded_self_report_text(args.get("consumer"), limit=120),
        history_type=_bounded_self_report_text(args.get("history_type"), limit=60),
        project_id=_bounded_self_report_text(args.get("project_id"), limit=160),
        title=_bounded_self_report_text(args.get("title"), limit=160),
        summary=_bounded_self_report_text(args.get("summary"), limit=500),
        source_refs=args.get("source_refs"),
        request_id=_bounded_self_report_text(args.get("request_id"), limit=160),
        path=os.environ.get("MEMCORE_READING_AREA_REGISTRY", "") or None,
    )
    return {
        **result,
        "mode": "project_history_write",
        "contract": "time_library_project_history_write_receipt.v1",
        "platform_write_performed": False,
        "memory_write_performed": False,
        "raw_write_performed": False,
        "reading_area_content_write_performed": False,
        "not_a_sixth_shelf": True,
    }


def _project_history_list_payload(args: Dict[str, Any]) -> Dict[str, Any]:
    registry = _import_reading_area_registry()
    result = registry.list_project_history_records(
        borrowing_card_id=_bounded_self_report_text(args.get("borrowing_card_id") or args.get("card_id"), limit=220),
        source_system=_bounded_self_report_text(args.get("source_system"), limit=120),
        canonical_window_id=_bounded_self_report_text(args.get("canonical_window_id"), limit=200),
        session_id=_bounded_self_report_text(args.get("session_id"), limit=200),
        consumer=_bounded_self_report_text(args.get("consumer"), limit=120),
        project_ids=_self_report_list(args.get("declared_project_ids") or args.get("projects") or args.get("project_id")),
        series_ids=_self_report_list(args.get("declared_series_ids") or args.get("series")),
        reading_area_ids=_self_report_list(args.get("reading_area") or args.get("declared_reading_area_ids")),
        statuses=_self_report_list(args.get("statuses")),
        limit=int(args.get("limit") or 20),
        path=os.environ.get("MEMCORE_READING_AREA_REGISTRY", "") or None,
    )
    return {
        **result,
        "mode": "project_history_list",
        "platform_write_performed": False,
        "memory_write_performed": False,
        "raw_write_performed": False,
        "reading_area_content_write_performed": False,
        "not_a_sixth_shelf": True,
    }


def _nomination_create_payload(args: Dict[str, Any]) -> Dict[str, Any]:
    registry = _import_reading_area_registry()
    result = registry.create_project_nomination(
        source_system=_bounded_self_report_text(args.get("source_system"), limit=120),
        canonical_window_id=_bounded_self_report_text(args.get("canonical_window_id"), limit=200),
        session_id=_bounded_self_report_text(args.get("session_id"), limit=200),
        source_path=_bounded_self_report_text(args.get("source_path"), limit=1000),
        nominated_project=_bounded_self_report_text(args.get("nominated_project") or args.get("project_id"), limit=200),
        nominated_series=_bounded_self_report_text(args.get("nominated_series"), limit=200),
        reason=_bounded_self_report_text(args.get("reason"), limit=500),
        confidence=float(args.get("confidence") or 0.0),
        request_id=_bounded_self_report_text(args.get("request_id"), limit=160),
        path=os.environ.get("MEMCORE_READING_AREA_REGISTRY", "") or None,
    )
    return {
        **result,
        "mode": "nomination_create",
        "contract": "time_library_project_nomination_create_receipt.v1",
        "declared_membership_written": False,
        "platform_write_performed": False,
        "memory_write_performed": False,
        "raw_write_performed": False,
    }


def _nomination_list_payload(args: Dict[str, Any]) -> Dict[str, Any]:
    registry = _import_reading_area_registry()
    result = registry.list_project_nominations(
        statuses=_self_report_list(args.get("statuses")),
        project=_bounded_self_report_text(args.get("nominated_project") or args.get("project_id"), limit=200),
        limit=int(args.get("limit") or 50),
        path=os.environ.get("MEMCORE_READING_AREA_REGISTRY", "") or None,
    )
    return {**result, "mode": "nomination_list"}


def _claim_nomination_payload(args: Dict[str, Any]) -> Dict[str, Any]:
    registry = _import_reading_area_registry()
    result = registry.claim_project_nomination(
        nomination_id=_bounded_self_report_text(args.get("nomination_id"), limit=120),
        borrowing_card_id=_bounded_self_report_text(args.get("borrowing_card_id") or args.get("card_id"), limit=220),
        reading_area=_bounded_self_report_text(args.get("reading_area"), limit=200),
        projects=_self_report_list(args.get("declared_project_ids") or args.get("projects")),
        series=_self_report_list(args.get("declared_series_ids") or args.get("series")),
        roles=_self_report_list(args.get("declared_roles") or args.get("roles")),
        path=os.environ.get("MEMCORE_READING_AREA_REGISTRY", "") or None,
    )
    return {
        **result,
        "mode": "claim_nomination",
        "contract": "time_library_project_nomination_claim_receipt.v1",
        "platform_write_performed": False,
        "memory_write_performed": False,
        "raw_write_performed": False,
        "technical_project_id_used_as_declared_identity": False,
    }


def _reject_nomination_payload(args: Dict[str, Any]) -> Dict[str, Any]:
    registry = _import_reading_area_registry()
    result = registry.reject_project_nomination(
        nomination_id=_bounded_self_report_text(args.get("nomination_id"), limit=120),
        borrowing_card_id=_bounded_self_report_text(args.get("borrowing_card_id") or args.get("card_id"), limit=220),
        reason=_bounded_self_report_text(args.get("reason"), limit=500),
        path=os.environ.get("MEMCORE_READING_AREA_REGISTRY", "") or None,
    )
    return {
        **result,
        "mode": "reject_nomination",
        "contract": "time_library_project_nomination_reject_receipt.v1",
        "declared_membership_written": False,
        "platform_write_performed": False,
        "memory_write_performed": False,
        "raw_write_performed": False,
    }


def _platform_self_report_connect_payload(
    args: Dict[str, Any],
    *,
    connection_context: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    context = connection_context if isinstance(connection_context, Mapping) else {}
    if not context.get("initialized") or not context.get("client_info_present") or not context.get("transport_session_id"):
        return {
            "ok": False,
            "mode": "platform_self_report_connect",
            "contract": PLATFORM_SELF_REPORT_RECEIPT_CONTRACT,
            "error": "mcp_initialize_session_required",
            "self_report_verified": False,
            "reading_area_registered": False,
            "write_performed": False,
            "registry_write_performed": False,
            "platform_write_performed": False,
            "memory_write_performed": False,
            "raw_write_performed": False,
        }
    capability_observed_at = float(context.get("capability_check_observed_at_epoch") or 0.0)
    if capability_observed_at <= 0.0:
        return {
            "ok": False,
            "mode": "platform_self_report_connect",
            "contract": PLATFORM_SELF_REPORT_RECEIPT_CONTRACT,
            "error": "capability_check_not_observed_in_transport_session",
            "self_report_verified": False,
            "reading_area_registered": False,
            "write_performed": False,
            "registry_write_performed": False,
            "platform_write_performed": False,
            "memory_write_performed": False,
            "raw_write_performed": False,
            "reading_area_content_write_performed": False,
            "registration_blockers": ["capability_check_not_observed_in_transport_session"],
            "next_actions": ["run_capability_check_then_real_recall_in_this_transport_session"],
        }
    request_id = _bounded_self_report_text(args.get("request_id"), limit=160)
    consumer = _bounded_self_report_text(args.get("consumer") or args.get("source_system") or "mcp", limit=120)
    client_name = _sanitize_client_info_field(context.get("client_name"))
    client_version = _sanitize_client_info_field(context.get("client_version"))
    self_reported_platform = _bounded_self_report_text(
        args.get("source_system") or args.get("platform_name"),
        limit=120,
    ).lower().replace("-", "_").replace(" ", "_")
    inferred_platform_hint = _bounded_self_report_text(
        context.get("inferred_platform_hint") or _platform_from_client_name(client_name),
        limit=120,
    )
    source_system = self_reported_platform
    identity_mismatch = bool(
        self_reported_platform
        and inferred_platform_hint
        and inferred_platform_hint != "unknown_mcp_client"
        and self_reported_platform != inferred_platform_hint
    )
    existing_connection = _delivery_runtime().verified_host_connection(context)
    if existing_connection.get("ok") is True:
        existing_platform = _bounded_self_report_text(
            existing_connection.get("platform"),
            limit=120,
        )
        if not self_reported_platform or self_reported_platform != existing_platform:
            return {
                "ok": False,
                "mode": "platform_self_report_connect",
                "contract": PLATFORM_SELF_REPORT_RECEIPT_CONTRACT,
                "error": "transport_session_identity_already_bound",
                "existing_platform": existing_platform,
                "attempted_platform": self_reported_platform,
                "self_report_verified": False,
                "reading_area_registered": False,
                "write_performed": False,
                "registry_write_performed": False,
                "platform_write_performed": False,
                "memory_write_performed": False,
                "raw_write_performed": False,
                "reading_area_content_write_performed": False,
                "connection_receipt": existing_connection,
            }
        existing_card_id = _bounded_self_report_text(
            existing_connection.get("borrowing_card_id"),
            limit=220,
        )
        if not existing_card_id:
            return {
                "ok": False,
                "mode": "platform_self_report_connect",
                "contract": PLATFORM_SELF_REPORT_RECEIPT_CONTRACT,
                "error": "verified_host_borrowing_card_required",
                "self_report_verified": False,
                "reading_area_registered": False,
                "write_performed": False,
                "registry_write_performed": False,
                "platform_write_performed": False,
                "memory_write_performed": False,
                "raw_write_performed": False,
                "reading_area_content_write_performed": False,
                "connection_receipt": existing_connection,
            }
        stored_proof = (
            existing_connection.get("real_recall_proof")
            if isinstance(existing_connection.get("real_recall_proof"), Mapping)
            else {}
        )
        replayed_proof = {
            "ok": True,
            "library_id": _bounded_self_report_text(existing_connection.get("proof_library_id"), limit=160),
            "mode": "existing_verified_connection",
            "source_refs_count": int(existing_connection.get("proof_source_refs_count") or 0),
        }
        for key in (
            "matched_count",
            "raw_excerpt_returned",
            "recall_source_system_filter",
            "observed_at_epoch",
        ):
            if key in stored_proof:
                replayed_proof[key] = stored_proof[key]
        return {
            "ok": True,
            "mode": "platform_self_report_connect",
            "contract": PLATFORM_SELF_REPORT_RECEIPT_CONTRACT,
            "idempotent": True,
            "read_only": False,
            "write_performed": False,
            "registry_write_performed": False,
            "platform_write_performed": False,
            "memory_write_performed": False,
            "raw_write_performed": False,
            "reading_area_content_write_performed": False,
            "chat_body_included": False,
            "raw_excerpt_included_in_self_report": False,
            "registry_metadata_written_fields": [],
            "client_info": {
                "client_name": client_name,
                "client_version": client_version,
                "client_surface": _bounded_self_report_text(args.get("client_surface"), limit=160),
                "self_reported_platform": self_reported_platform,
                "inferred_platform": inferred_platform_hint,
                "inferred_platform_hint": inferred_platform_hint,
                "identity_mismatch": identity_mismatch,
                "sanitized": True,
                "identity_authority": "host_self_report",
                "inference_is_non_authoritative": True,
                "host_neutral_no_platform_allowlist": True,
            },
            "answers_observed": True,
            "self_report_verified": True,
            "reading_area_registered": True,
            "platform_config_registered": False,
            "registration_scope": "existing_verified_connection_scope_preserved",
            "registration_blockers": [],
            "connection_proof_method": "existing_initialize_bound_self_report_plus_real_recall",
            "consumer_connection_requires_native_parser": False,
            "capability_check_advert": {
                "ok": True,
                "recall_performed": False,
                "raw_excerpt_returned": False,
                "observed_in_same_transport_session": True,
                "observed_at_epoch": capability_observed_at,
            },
            "real_recall_proof": replayed_proof,
            "borrowing_card_receipt": {
                "ok": True,
                "card_id": existing_card_id,
                "idempotent": True,
                "write_performed": False,
                "registry_write_performed": False,
            },
            "membership_receipt": {
                "ok": True,
                "status": "existing_connection_scope_preserved",
                "write_performed": False,
                "registry_write_performed": False,
            },
            "connection_receipt": existing_connection,
            "next_actions": [],
        }
    capability = capability_check_payload(
        consumer=consumer or source_system,
        request_id=request_id,
        source="mcp_self_report_connect",
    )
    proof_library_id = _library_id_from_args({"library_id": args.get("proof_library_id")})
    session_proofs = context.get("real_recall_proofs") if isinstance(context.get("real_recall_proofs"), Mapping) else {}
    prior_recall = session_proofs.get(proof_library_id) if proof_library_id else None
    prior_recall = prior_recall if isinstance(prior_recall, Mapping) else {}
    answer_blockers: List[str] = []
    if not _bounded_self_report_text(args.get("source_system"), limit=120):
        answer_blockers.append("source_system_not_self_reported")
    if not (args.get("canonical_window_id") or args.get("session_id")):
        answer_blockers.append("window_identity_not_self_reported")
    if "config_write_authority" not in args:
        answer_blockers.append("config_write_authority_answer_missing")
    if not _bounded_self_report_text(args.get("skill_surface_status"), limit=160):
        answer_blockers.append("skill_surface_answer_missing")
    if not (
        _bounded_self_report_text(args.get("reading_area"), limit=200)
        or _self_report_list(args.get("declared_project_ids") or args.get("projects"))
        or _self_report_list(args.get("declared_series_ids") or args.get("series"))
    ):
        answer_blockers.append("declared_project_series_missing")
    recall_observed_at = float(prior_recall.get("observed_at_epoch") or 0.0)
    capability_preceded_recall = bool(
        prior_recall
        and capability_observed_at > 0.0
        and recall_observed_at >= capability_observed_at
    )
    if prior_recall and capability_preceded_recall:
        proof = {
            "ok": True,
            "mode": "same_transport_session_prior_real_recall",
            "library_id": proof_library_id,
            "matched_count": int(prior_recall.get("matched_count") or 0),
            "raw_excerpt_returned": bool(prior_recall.get("raw_excerpt_returned")),
            "source_refs_count": int(prior_recall.get("source_refs_count") or 0),
            "same_initialized_transport_session": True,
            "observed_at_epoch": recall_observed_at,
            "recall_source_system_filter": _bounded_self_report_text(
                prior_recall.get("recall_source_system_filter"),
                limit=120,
            ),
        }
    else:
        proof_error = (
            "capability_check_must_precede_real_recall"
            if prior_recall and not capability_preceded_recall
            else (
                "prior_real_recall_proof_not_found_in_transport_session"
                if proof_library_id
                else "proof_library_id_required"
            )
        )
        proof = {
            "ok": False,
            "mode": "same_transport_session_prior_real_recall",
            "error": proof_error,
            "matched_count": 0,
            "source_refs_count": 0,
            "raw_excerpt_returned": False,
            "same_initialized_transport_session": False,
        }
    blockers: List[str] = list(answer_blockers)
    if (
        not proof.get("ok")
        or int(proof.get("matched_count") or 0) < 1
        or int(proof.get("source_refs_count") or 0) < 1
    ):
        blockers.append("real_recall_not_proven")
    if not capability.get("ok"):
        blockers.append("capability_check_failed")
    card: Dict[str, Any] = {
        "ok": False,
        "status": "not_attempted_until_self_report_and_recall_proof_pass",
        "registry_write_performed": False,
        "write_performed": False,
    }
    membership: Dict[str, Any] = {
        "ok": False,
        "status": "not_attempted_until_borrowing_card_issued",
        "registry_write_performed": False,
        "write_performed": False,
    }
    if not blockers:
        card = _issue_reading_area_borrowing_card({
            **args,
            "source_system": source_system,
            "consumer": consumer or source_system,
            "client_name": client_name,
        })
        if not card.get("ok"):
            blockers.append(str(card.get("error") or "borrowing_card_not_issued"))
        else:
            membership = _declare_reading_area_membership(args, card_id=str(card.get("card_id") or ""))
            if not membership.get("ok"):
                blockers.append(str(membership.get("error") or "membership_not_declared"))
    registry_ready = not blockers
    registry_write_performed = bool(card.get("ok") or membership.get("ok"))
    payload = {
        "ok": registry_ready,
        "mode": "platform_self_report_connect",
        "contract": PLATFORM_SELF_REPORT_RECEIPT_CONTRACT,
        "read_only": False,
        "write_performed": registry_write_performed,
        "registry_write_performed": registry_write_performed,
        "platform_write_performed": False,
        "memory_write_performed": False,
        "raw_write_performed": False,
        "reading_area_content_write_performed": False,
        "chat_body_included": False,
        "raw_excerpt_included_in_self_report": False,
        "registry_metadata_written_fields": ["borrowing_card", "declared_reading_area_ids", "declared_project_ids", "declared_series_ids"] if registry_write_performed else [],
        "client_info": {
            "client_name": client_name,
            "client_version": client_version,
            "client_surface": _bounded_self_report_text(args.get("client_surface"), limit=160),
            "self_reported_platform": self_reported_platform,
            "inferred_platform": inferred_platform_hint,
            "inferred_platform_hint": inferred_platform_hint,
            "identity_mismatch": identity_mismatch,
            "sanitized": True,
            "identity_authority": "host_self_report",
            "inference_is_non_authoritative": True,
            "host_neutral_no_platform_allowlist": True,
        },
        "answers_observed": not bool(answer_blockers),
        "self_report_verified": registry_ready,
        "reading_area_registered": registry_ready,
        "platform_config_registered": False,
        "registration_scope": "reading_area_registry_only_no_platform_config_write",
        "registration_blockers": blockers,
        "connection_proof_method": (
            "capability_check_then_same_transport_session_real_recall"
            if prior_recall
            else "pending_same_transport_session_real_recall"
        ),
        "consumer_connection_requires_native_parser": False,
        "capability_check_advert": {
            "ok": bool(capability.get("ok")),
            "recall_performed": bool(capability.get("recall_performed")),
            "raw_excerpt_returned": bool(capability.get("raw_excerpt_returned")),
            "observed_in_same_transport_session": True,
            "observed_at_epoch": capability_observed_at,
        },
        "real_recall_proof": {
            "ok": bool(proof.get("ok")),
            "library_id": proof_library_id,
            "mode": proof.get("mode", ""),
            "matched_count": int(proof.get("matched_count") or 0),
            "raw_excerpt_returned": bool(proof.get("raw_excerpt_returned")),
            "source_refs_count": int(proof.get("source_refs_count") or 0),
            "same_initialized_transport_session": bool(
                proof.get("same_initialized_transport_session")
            ),
            "observed_at_epoch": float(proof.get("observed_at_epoch") or 0.0),
            "recall_source_system_filter": _bounded_self_report_text(
                proof.get("recall_source_system_filter"),
                limit=120,
            ),
            "error": _bounded_self_report_text(proof.get("error"), limit=200),
        },
        "borrowing_card_receipt": card,
        "membership_receipt": membership,
        "next_actions": (
            []
            if registry_ready
            else ["perform_user_authorized_real_recall_then_retry_in_same_transport_session"]
        ),
    }
    if registry_ready:
        connection_receipt = _delivery_runtime().record_verified_host_connection(
            context,
            payload,
        )
        payload["connection_receipt"] = connection_receipt
        if connection_receipt.get("ok") is not True:
            payload["ok"] = False
            payload["self_report_verified"] = False
            payload["reading_area_registered"] = False
            payload["registration_blockers"] = [
                *list(payload.get("registration_blockers") or []),
                str(connection_receipt.get("error") or "host_connection_receipt_failed"),
            ]
    return payload


def _reading_area_tool_payload(
    args: Dict[str, Any],
    *,
    connection_context: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    extra_keys = sorted(set(args.keys()) - READING_AREA_TOOL_ALLOWED_KEYS)
    if extra_keys:
        return {
            "ok": False,
            "mode": "reading_area",
            "error": "unknown_reading_area_arguments",
            "unknown_arguments": extra_keys,
            "write_performed": False,
            "registry_write_performed": False,
            "platform_write_performed": False,
            "memory_write_performed": False,
            "raw_write_performed": False,
        }
    action = str(args.get("action") or "").strip().lower()
    if action == "self_report_connect":
        return _platform_self_report_connect_payload(
            args,
            connection_context=connection_context,
        )
    handlers = {
        "declare_membership": _declare_reading_area_membership,
        "whiteboard_write": _whiteboard_write_payload,
        "whiteboard_list": _whiteboard_list_payload,
        "project_history_write": _project_history_write_payload,
        "project_history_list": _project_history_list_payload,
        "nomination_create": _nomination_create_payload,
        "nomination_list": _nomination_list_payload,
        "claim_nomination": _claim_nomination_payload,
        "reject_nomination": _reject_nomination_payload,
    }
    if action == "issue_borrowing_card" or action in handlers:
        bound_args = dict(args)
        verified_card_id = ""
        if connection_context is not None:
            verification = _delivery_runtime().verified_host_connection(connection_context)
            if verification.get("ok") is not True:
                return {
                    "ok": False,
                    "mode": "reading_area",
                    "error": str(verification.get("error") or "verified_host_connection_required"),
                    "identity_authority": "verified_host_connection_receipt",
                    "write_performed": False,
                    "registry_write_performed": False,
                    "platform_write_performed": False,
                    "memory_write_performed": False,
                    "raw_write_performed": False,
                }
            platform = _bounded_self_report_text(verification.get("platform"), limit=120)
            verified_card_id = _bounded_self_report_text(verification.get("borrowing_card_id"), limit=220)
            if not platform or not verified_card_id:
                return {
                    "ok": False,
                    "mode": "reading_area",
                    "error": "verified_host_borrowing_card_required",
                    "identity_authority": "verified_host_connection_receipt",
                    "write_performed": False,
                    "registry_write_performed": False,
                    "platform_write_performed": False,
                    "memory_write_performed": False,
                    "raw_write_performed": False,
                }
            requested_card_id = _bounded_self_report_text(
                bound_args.get("borrowing_card_id") or bound_args.get("card_id"),
                limit=220,
            )
            if requested_card_id and requested_card_id != verified_card_id:
                return {
                    "ok": False,
                    "mode": "reading_area",
                    "error": "borrowing_card_identity_mismatch",
                    "identity_authority": "verified_host_connection_receipt",
                    "write_performed": False,
                    "registry_write_performed": False,
                    "platform_write_performed": False,
                    "memory_write_performed": False,
                    "raw_write_performed": False,
                }
            bound_args["source_system"] = platform
            if verified_card_id:
                bound_args["borrowing_card_id"] = verified_card_id
                bound_args["card_id"] = verified_card_id
        if action == "issue_borrowing_card":
            return _issue_reading_area_borrowing_card(
                bound_args,
                verified_card_id=verified_card_id,
            )
        return handlers[action](bound_args)
    return {
        "ok": False,
        "mode": "reading_area",
        "error": "unknown_reading_area_action",
        "allowed_actions": [
            "issue_borrowing_card",
            "declare_membership",
            "self_report_connect",
            "whiteboard_write",
            "whiteboard_list",
            "project_history_write",
            "project_history_list",
            "nomination_create",
            "nomination_list",
            "claim_nomination",
            "reject_nomination",
        ],
        "write_performed": False,
        "platform_write_performed": False,
        "memory_write_performed": False,
        "raw_write_performed": False,
    }


def mcp_call_tool(
    name: str,
    arguments: Dict[str, Any],
    *,
    connection_context: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    if name == "time_library_reading_area":
        result = _reading_area_tool_payload(
            arguments if isinstance(arguments, dict) else {},
            connection_context=connection_context,
        )
        return {
            "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
            "structuredContent": result,
            "isError": not bool(result.get("ok")),
        }
    if name == "time_library_delivery_ack":
        result = _delivery_runtime().acknowledge_delivery(
            arguments if isinstance(arguments, dict) else {},
            connection_context=connection_context,
        )
        return {
            "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
            "structuredContent": result,
            "isError": not bool(result.get("ok")),
        }
    if name not in ("time_library_recall", "zhiyi_recall"):
        return {
            "isError": True,
            "content": [{"type": "text", "text": f"Unknown tool: {name}"}],
        }
    args = arguments if isinstance(arguments, dict) else {}
    binding_identity = _mcp_binding_identity(connection_context)
    delivery_eligible = False
    if _is_capability_check_request(args):
        result = capability_check_payload(
            consumer=str(args.get("consumer") or "mcp"),
            request_id=str(args.get("request_id") or ""),
            source="mcp",
        )
    elif _is_work_preflight_request(args):
        result = _work_preflight_from_kwargs(_preflight_kwargs_from_args(
            args,
            consumer_default="mcp",
            limit_default=3,
            excerpt_default=180,
            binding_identity=binding_identity,
        ))
    elif _is_preflight_request(args):
        result = preflight_payload(**_preflight_kwargs_from_args(
            args,
            consumer_default="mcp",
            limit_default=3,
            excerpt_default=180,
            binding_identity=binding_identity,
        ))
    else:
        direct_library_id = _library_id_from_args(args)
        if direct_library_id:
            verification = (
                _delivery_runtime().verified_host_connection(connection_context)
                if connection_context is not None
                else {"ok": True, "borrowing_card_id": ""}
            )
            if verification.get("ok") is not True:
                result = {
                    "ok": False,
                    "mode": "library_card_borrow",
                    "query": direct_library_id,
                    "library_id": direct_library_id,
                    "error": str(verification.get("error") or "verified_host_connection_required"),
                    "identity_authority": "verified_host_connection_receipt",
                    "read_only": True,
                    "write_performed": False,
                    "matched_count": 0,
                    "items": [],
                }
            else:
                result = _catalog_card_borrow_payload(
                    direct_library_id,
                    consumer=str(args.get("consumer") or "mcp"),
                    request_id=str(args.get("request_id") or ""),
                    borrowing_card_id=_bounded_self_report_text(
                        verification.get("borrowing_card_id"),
                        limit=220,
                    ),
                    project_id=str(args.get("project_id") or ""),
                    series_id=str(args.get("series_id") or args.get("declared_series_id") or ""),
                    reading_area_id=str(args.get("reading_area_id") or ""),
                )
            delivery_eligible = True
        else:
            result = query_raw_source_refs(
                query=str(args.get("query") or ""),
                source_system=str(args.get("source_system") or ""),
                computer_name=str(args.get("computer_name") or ""),
                session_id=str(args.get("session_id") or ""),
                limit=args.get("limit", 5),
                excerpt_chars=args.get("excerpt_chars", 300),
                consumer=str(args.get("consumer") or "mcp"),
                request_id=str(args.get("request_id") or ""),
                memory_scope=str(args.get("memory_scope") or ""),
                canonical_window_id=str(args.get("canonical_window_id") or ""),
                allow_cross_window_recall=_truthy(args.get("allow_cross_window_recall")),
                cross_window_reason=str(args.get("cross_window_reason") or args.get("workflow_reason") or ""),
                project_id=str(args.get("project_id") or ""),
                project_root=str(args.get("project_root") or args.get("workspace_root") or args.get("cwd") or ""),
                workstream_id=str(args.get("workstream_id") or args.get("workstream") or ""),
                task_id=str(args.get("task_id") or args.get("task") or ""),
                recall_mode=str(args.get("recall_mode") or ""),
                fts5_recall=_truthy(args.get("fts5_recall")) or _truthy(args.get("enable_fts5_recall")),
                binding_identity=binding_identity,
                expand_catalog_raw=_include_raw_excerpt(args),
            )
            result = compact_recall_payload(
                result,
                response_budget_mode=_response_budget_mode(args),
                include_raw_excerpt=_include_raw_excerpt(args),
            )
            delivery_eligible = True
    if delivery_eligible:
        try:
            result = _delivery_runtime().instrument_recall_result(
                result,
                args,
                connection_context=connection_context,
            )
        except Exception as exc:
            result = dict(result)
            result["delivery_runtime"] = {
                "ok": False,
                "contract": "time_library.delivery_runtime.v2026.7.13",
                "error": "%s: %s" % (type(exc).__name__, str(exc)[:240]),
                "proof_layer": "runtime_instrumentation_failed",
                "write_performed": False,
                "source_memory_read_only": True,
                "raw_write_performed": False,
                "memory_write_performed": False,
                "platform_write_performed": False,
                "delivery_performed": False,
            }
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(result, ensure_ascii=False),
            }
        ],
        "structuredContent": result,
        "isError": False,
    }


def handle_mcp_request(
    data: Dict[str, Any],
    *,
    startup_catalog_mode: str = STARTUP_CATALOG_MODE_FULL,
    connection_context: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any] | None:
    request_id = _mcp_request_id(data)
    method = str(data.get("method") or "")
    params = data.get("params", {}) if isinstance(data.get("params"), dict) else {}

    if method == "initialize":
        return mcp_success(
            request_id,
            build_mcp_initialize_result(params, startup_catalog_mode=startup_catalog_mode),
        )
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return mcp_success(request_id, mcp_tools_payload())
    if method == "tools/call":
        try:
            result = mcp_call_tool(
                str(params.get("name") or ""),
                params.get("arguments", {}) if isinstance(params.get("arguments"), dict) else {},
                connection_context=connection_context,
            )
        except Exception as exc:
            return mcp_error(
                request_id,
                -32603,
                f"Internal error while calling tool: {type(exc).__name__}: {exc}",
            )
        return mcp_success(request_id, result)
    if method == "ping":
        return mcp_success(request_id, {})
    return mcp_error(request_id, -32601, f"Method not found: {method}")
