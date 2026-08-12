#!/usr/bin/env python3
"""
Source-memory read-only raw/source_refs HTTP and MCP-compatible gateway.

This module does NOT write Hermes skill/memory, does NOT modify platform config,
and does NOT treat zhiyi experience layer as raw evidence. A recognized MCP host
may append explicitly scoped Delivery Spine audit metadata under runtime/; that
derived audit never mutates source memory.
"""

from __future__ import annotations

import json
import hashlib
import ipaddress
import os
import re
import sqlite3
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple
from urllib.parse import parse_qs, urlparse

try:
    from src import raw_recall_query as _raw_recall_query
except Exception:
    import raw_recall_query as _raw_recall_query
try:
    from src import raw_recall_preflight as _raw_recall_preflight
except Exception:
    import raw_recall_preflight as _raw_recall_preflight

try:
    from src.source_system_runtime_declarations import (
        canonical_source_system_name as _canonical_source_system_name,
        normalize_source_system_window_identity as _normalize_source_system_window_identity,
        recall_source_system_filters as _declared_recall_source_system_filters,
        source_system_filter_matches as _source_system_filter_matches,
        source_system_from_consumer_name as _source_system_from_consumer_name,
        source_system_filter_query_tokens as _source_system_filter_query_tokens,
    )
except Exception:
    from source_system_runtime_declarations import (
        canonical_source_system_name as _canonical_source_system_name,
        normalize_source_system_window_identity as _normalize_source_system_window_identity,
        recall_source_system_filters as _declared_recall_source_system_filters,
        source_system_filter_matches as _source_system_filter_matches,
        source_system_from_consumer_name as _source_system_from_consumer_name,
        source_system_filter_query_tokens as _source_system_filter_query_tokens,
    )
try:
    from src.memcore_version import SERVICE_VERSION
except Exception:
    from memcore_version import SERVICE_VERSION
try:
    from src.config_loader import base_path as _memcore_base_path
except Exception:
    try:
        from config_loader import base_path as _memcore_base_path
    except Exception:
        def _memcore_base_path():
            return os.environ.get("MEMCORE_ROOT") or str(Path(__file__).resolve().parents[1])
try:
    from src.raw_gateway_mcp import (
        MCP_PROTOCOL_VERSION,
        _mcp_request_id,
        mcp_error,
        mcp_success,
        mcp_tools_payload as _raw_gateway_mcp_tools_payload,
    )
except Exception:
    from raw_gateway_mcp import (
        MCP_PROTOCOL_VERSION,
        _mcp_request_id,
        mcp_error,
        mcp_success,
        mcp_tools_payload as _raw_gateway_mcp_tools_payload,
    )
try:
    from src.p4_provider import DEFAULT_CATALOG_TARGET_TOKENS as P4_DEFAULT_CATALOG_TARGET_TOKENS
except Exception:
    try:
        from p4_provider import DEFAULT_CATALOG_TARGET_TOKENS as P4_DEFAULT_CATALOG_TARGET_TOKENS
    except Exception:
        P4_DEFAULT_CATALOG_TARGET_TOKENS = 1500
try:
    from src.raw_text_decode import (
        decode_text_bytes as _decode_text_bytes,
        iter_decoded_jsonl_lines as _iter_decoded_jsonl_lines,
        jsonl_line_separator_for_sample as _jsonl_line_separator_for_sample,
    )
except Exception:
    from raw_text_decode import (
        decode_text_bytes as _decode_text_bytes,
        iter_decoded_jsonl_lines as _iter_decoded_jsonl_lines,
        jsonl_line_separator_for_sample as _jsonl_line_separator_for_sample,
    )
try:
    from src.raw_evidence_excerpt import (
        DEFAULT_RAW_SEGMENT_BYTES,
        DEFAULT_RAW_SEGMENT_MAX_SEGMENTS,
        FORBIDDEN_STATE_DIR_PARTS,
        MAX_RAW_OFFSET_READ_BYTES,
        MAX_RAW_SEGMENT_BYTES,
        MAX_RAW_SEGMENT_MAX_SEGMENTS,
        MAX_RAW_STREAM_SCAN_BYTES,
        RAW_SEGMENT_OVERLAP_BYTES,
        TIANDAO_RAW_EVIDENCE_EXCERPT_CONTRACT,
        _append_jsonl_obj_excerpt,
        _extract_bounded_raw_excerpt,
        _extract_bounded_raw_excerpt_by_cursor_segments,
        _extract_bounded_raw_excerpt_by_offsets,
        _extract_content_text,
        _is_safe_raw_gateway_state_dir,
        _load_raw_offset_index,
        _load_raw_segment_state,
        _raw_segment_state_dir,
        _resolve_source_path,
        get_raw_evidence_excerpt_contract,
    )
except Exception:
    from raw_evidence_excerpt import (
        DEFAULT_RAW_SEGMENT_BYTES,
        DEFAULT_RAW_SEGMENT_MAX_SEGMENTS,
        FORBIDDEN_STATE_DIR_PARTS,
        MAX_RAW_OFFSET_READ_BYTES,
        MAX_RAW_SEGMENT_BYTES,
        MAX_RAW_SEGMENT_MAX_SEGMENTS,
        MAX_RAW_STREAM_SCAN_BYTES,
        RAW_SEGMENT_OVERLAP_BYTES,
        TIANDAO_RAW_EVIDENCE_EXCERPT_CONTRACT,
        _append_jsonl_obj_excerpt,
        _extract_bounded_raw_excerpt,
        _extract_bounded_raw_excerpt_by_cursor_segments,
        _extract_bounded_raw_excerpt_by_offsets,
        _extract_content_text,
        _is_safe_raw_gateway_state_dir,
        _load_raw_offset_index,
        _load_raw_segment_state,
        _raw_segment_state_dir,
        _resolve_source_path,
        get_raw_evidence_excerpt_contract,
    )
try:
    from src.zhixing_library import attach_library_card, hybrid_recall_manifest, library_manifest
except Exception:
    from zhixing_library import attach_library_card, hybrid_recall_manifest, library_manifest
try:
    from src.zhixing_preflight import build_zhixing_preflight, classify_prompt
except Exception:
    from zhixing_preflight import build_zhixing_preflight, classify_prompt
try:
    from src.agent_work_preflight import build_gateway_agent_work_preflight
except Exception:
    from agent_work_preflight import build_gateway_agent_work_preflight
try:
    from src.raw_recall_response_budget import (
        compact_recall_payload,
        include_raw_excerpt as _include_raw_excerpt,
        response_budget_mode as _response_budget_mode,
    )
except Exception:
    from raw_recall_response_budget import (
        compact_recall_payload,
        include_raw_excerpt as _include_raw_excerpt,
        response_budget_mode as _response_budget_mode,
    )
try:
    from src.raw_recall_catalog_index import (
        query_canonical_window_index,
        records_db_path_for_gateway as _records_db_path_for_gateway,
    )
except Exception:
    from raw_recall_catalog_index import (
        query_canonical_window_index,
        records_db_path_for_gateway as _records_db_path_for_gateway,
    )
try:
    from src.raw_recall_explainability import (
        LIBRARY_INDEX_PROJECTION_POLICY,
        RAW_RECALL_TRAJECTORY_CONTRACT,
        RAW_RECALL_TRAJECTORY_POLICY,
        build_query_payload_from_items,
        consumer_receipt as _explainability_consumer_receipt,
        library_index_projection_refs as _library_index_projection_refs,
        mark_library_index_projection_item as _mark_library_index_projection_item,
    )
except Exception:
    from raw_recall_explainability import (
        LIBRARY_INDEX_PROJECTION_POLICY,
        RAW_RECALL_TRAJECTORY_CONTRACT,
        RAW_RECALL_TRAJECTORY_POLICY,
        build_query_payload_from_items,
        consumer_receipt as _explainability_consumer_receipt,
        library_index_projection_refs as _library_index_projection_refs,
        mark_library_index_projection_item as _mark_library_index_projection_item,
    )
try:
    from src.trusted_memory_authority_anchor import (
        TRUSTED_MEMORY_AUTHORITY_ANCHOR_CONTRACT,
        TRUSTED_MEMORY_AUTHORITY_ANCHORS,
        TRUSTED_MEMORY_AUTHORITY_TRIGGER_TERMS,
        has_trusted_memory_authority_anchor as _has_trusted_memory_authority_anchor,
        trusted_memory_authority_anchor_items as _trusted_memory_authority_anchor_items,
        trusted_memory_authority_anchor_query as _trusted_memory_authority_anchor_query,
    )
except Exception:
    from trusted_memory_authority_anchor import (
        TRUSTED_MEMORY_AUTHORITY_ANCHOR_CONTRACT,
        TRUSTED_MEMORY_AUTHORITY_ANCHORS,
        TRUSTED_MEMORY_AUTHORITY_TRIGGER_TERMS,
        has_trusted_memory_authority_anchor as _has_trusted_memory_authority_anchor,
        trusted_memory_authority_anchor_items as _trusted_memory_authority_anchor_items,
        trusted_memory_authority_anchor_query as _trusted_memory_authority_anchor_query,
    )
try:
    from src.active_memory_routing import (
        DEFAULT_MEMORY_SCOPE,
        active_memory_routing_status as _active_memory_routing_status,
        resolve_recall_scope as _routing_resolve_recall_scope,
        scope_missing_status as _routing_scope_missing_status,
        truthy as _routing_truthy,
    )
except Exception:
    from active_memory_routing import (
        DEFAULT_MEMORY_SCOPE,
        active_memory_routing_status as _active_memory_routing_status,
        resolve_recall_scope as _routing_resolve_recall_scope,
        scope_missing_status as _routing_scope_missing_status,
        truthy as _routing_truthy,
    )
try:
    from src.window_binding_registry import get_current_window_binding
except Exception:
    try:
        from window_binding_registry import get_current_window_binding
    except Exception:
        get_current_window_binding = None
try:
    from src.tiandao import ContextPackage, IntentMode, MemoryContextMode
    from src.tiandao.memory_routing import (
        TIANDAO_ACTIVE_MEMORY_ROUTING_CONTRACT,
        active_memory_routing_contract_descriptor,
        memory_context_mode_for_routing,
    )
    from src.tiandao.validators import validate_context_package as _validate_tiandao_context_package
except Exception:
    try:
        from tiandao import ContextPackage, IntentMode, MemoryContextMode
        from tiandao.memory_routing import (
            TIANDAO_ACTIVE_MEMORY_ROUTING_CONTRACT,
            active_memory_routing_contract_descriptor,
            memory_context_mode_for_routing,
        )
        from tiandao.validators import validate_context_package as _validate_tiandao_context_package
    except Exception:
        ContextPackage = None
        IntentMode = None
        MemoryContextMode = None
        TIANDAO_ACTIVE_MEMORY_ROUTING_CONTRACT = "tiandao_active_memory_routing.v1"
        active_memory_routing_contract_descriptor = None
        memory_context_mode_for_routing = None
        _validate_tiandao_context_package = None


P3_RECALL_URL = os.environ.get(
    "MEMCORE_P3_RECALL_URL",
    f"http://127.0.0.1:{os.environ.get('TIME_LIBRARY_INTERNAL_P3_PORT', '19300')}/recall",
).strip()
P3_RECALL_TRANSPORT = os.environ.get("MEMCORE_P3_RECALL_TRANSPORT", "http").strip().lower()


def _inline_handle_recall():
    try:
        from src.p3_recall import handle_recall
    except Exception:
        from p3_recall import handle_recall
    return handle_recall


def _p3_service_handle_recall(body):
    request = urllib.request.Request(
        P3_RECALL_URL,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=90) as response:
        payload = json.load(response)
    if not isinstance(payload, dict):
        raise ValueError("P3 recall service returned a non-object payload")
    payload["recall_transport"] = "p3_http_service"
    return payload


def _load_handle_recall():
    if P3_RECALL_TRANSPORT == "inline":
        return _inline_handle_recall()

    def handle(body):
        try:
            return _p3_service_handle_recall(body)
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
            fallback_body = dict(body)
            vector_fallback = str(fallback_body.get("recall_mode") or "").strip() == "vector"
            if vector_fallback:
                fallback_body["recall_mode"] = "substring"
                fallback_body["fts5_recall"] = True
            result = _inline_handle_recall()(fallback_body)
            if isinstance(result, dict):
                result["recall_transport"] = "inline_fallback_p3_service_unavailable"
                if vector_fallback:
                    result["vector_fallback_applied"] = True
                    result["vector_fallback_backend"] = "FTS5+BM25"
                    result["vector_degraded"] = True
            return result
    return handle


UTC = timezone.utc
PORT = int(os.environ.get("TIME_LIBRARY_INTERNAL_RAW_PORT", "19510"))
MAX_LIMIT = 20
MAX_EXCERPT = 800
ACTIVE_RECALL_CANDIDATE_MAX = 80
PROJECT_FALLBACK_MAX_TECHNICAL_ANCHORS = 6
PROJECT_STATUS_EXCERPT_CHARS = 800
RAW_FALLBACK_DEFAULT_MAX_FILES = 8
RAW_FALLBACK_DEFAULT_MAX_BYTES = 8 * 1024 * 1024
RAW_FALLBACK_DEFAULT_MAX_LINES = 5000
RAW_FALLBACK_DEFAULT_DEADLINE_SECONDS = 8.0
GATEWAY_RECENT_DELTA_MAX_BYTES = int(os.environ.get("MEMCORE_GATEWAY_RECENT_DELTA_MAX_BYTES") or str(512 * 1024))
GATEWAY_RECENT_DELTA_MAX_DOCS = int(os.environ.get("MEMCORE_GATEWAY_RECENT_DELTA_MAX_DOCS") or "64")
SERVICE_NAME = "raw_consumption_gateway"
HEALTH_IDENTITY_CONTRACT = "raw_gateway_health_identity.v1"
ACTIVE_MEMORY_ROUTING_CONTRACT = "active_memory_routing.v2026.7.15"
MCP_SERVER_NAME = "time-library"
MCP_LEGACY_SERVER_NAMES = ("time-library",)
STARTUP_CATALOG_TARGET_TOKENS = P4_DEFAULT_CATALOG_TARGET_TOKENS
STARTUP_CATALOG_DELIVERY_RECEIPT_CONTRACT = "time_library_startup_catalog_delivery_receipt.v1"
PLATFORM_HANDSHAKE_RECEIPT_CONTRACT = "time_library_platform_handshake_receipt.v1"
PLATFORM_SELF_REPORT_QUESTIONS_CONTRACT = "time_library_platform_self_report_questions.v1"
PLATFORM_SELF_REPORT_RECEIPT_CONTRACT = "time_library_platform_self_report_receipt.v1"
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
HTTPServer = ThreadingHTTPServer

def _service_source_path() -> Path:
    return Path(__file__).resolve()


def _service_source_sha256(path: Path | None = None) -> str:
    source_path = path or _service_source_path()
    h = hashlib.sha256()
    try:
        with source_path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
    except Exception:
        return ""
    return h.hexdigest()


def ts() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe_int(value: str, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        return default
    return max(minimum, min(maximum, parsed))


def _json_loads_maybe(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value:
        try:
            return json.loads(value)
        except Exception:
            return {}
    return {}


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _first_text(*values: Any) -> str:
    for value in values:
        text = _clean_text(value)
        if text:
            return text
    return ""


def _normalize_path_text(value: Any) -> str:
    text = _clean_text(value)
    if not text:
        return ""
    return text.replace("\\", "/").rstrip("/").lower()


def _item_project_id(item: Dict[str, Any]) -> str:
    return _first_text(item.get("project_id"), item.get("project"))


def _item_project_root(item: Dict[str, Any]) -> str:
    return _first_text(item.get("project_root"), item.get("workspace_root"), item.get("cwd"))


def _item_workstream_id(item: Dict[str, Any]) -> str:
    return _first_text(item.get("workstream_id"), item.get("workstream"), item.get("task_stream"))


def _item_task_id(item: Dict[str, Any]) -> str:
    return _first_text(item.get("task_id"), item.get("task"), item.get("ticket_id"))


def _item_legacy_window_id(item: Dict[str, Any]) -> str:
    return _first_text(item.get("source_refs_canonical_window_id"), item.get("legacy_canonical_window_id"))


def _recall_source_system_filters(
    *,
    effective_source_system: str,
    session_id: str,
    canonical_window_id: str,
    declared_source_system_filters: List[str] | None = None,
) -> List[str]:
    filters, _ = _declared_recall_source_system_filters(
        effective_source_system=effective_source_system,
        session_id=session_id,
        canonical_window_id=canonical_window_id,
    )
    if session_id or canonical_window_id:
        for item in declared_source_system_filters or []:
            source = _canonical_source_system_name(item)
            if source and source not in filters:
                filters.append(source)
    return filters


def _source_alias_extra(
    source_filters: List[str],
    *,
    effective_source_system: str,
    session_id: str,
    canonical_window_id: str,
) -> Dict[str, Any]:
    aliases = [
        source
        for source in source_filters
        if source and source != _clean_text(effective_source_system)
    ]
    if not aliases:
        return {}
    return {
        "source_system_filter_aliases": [source for source in source_filters if source],
        "source_collection_filter": "binding_declared_source_systems",
        "source_collection_alias_applied": True,
        "source_collection_alias_boundary": "verified_binding_same_window_or_session_anchor_only",
    }


def _dedupe_recall_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    deduped: List[Dict[str, Any]] = []
    seen = set()
    for item in items:
        key = (
            str(item.get("library_id", "")),
            str(item.get("exp_id", "")),
            str(item.get("source_path", "")),
            tuple(item.get("msg_ids") or []),
            str(item.get("raw_excerpt", "")),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _specific_source_system_filters(filters: List[str]) -> List[str]:
    return [
        _clean_text(source_filter)
        for source_filter in (filters or [])
        if _clean_text(source_filter)
    ]


def _declared_source_system(value: str, fallback: str = "") -> str:
    text = _clean_text(value)
    if text:
        return _canonical_source_system_name(text)
    return _clean_text(fallback)


def _has_active_project_or_workstream_anchor(
    *,
    project_id: str,
    project_root: str,
    workstream_id: str,
    task_id: str,
) -> bool:
    return bool(project_id or project_root or workstream_id or task_id)


def _is_active_empty_window_project_fallback_candidate(
    *,
    active_scope: bool,
    scope: Dict[str, Any],
    effective_session_id: str,
    effective_window_id: str,
    project_id: str,
    project_root: str,
    workstream_id: str,
    task_id: str,
    source_system_filters: List[str],
    active_layers_used: List[str],
    needs_more_candidates: bool,
) -> bool:
    return bool(
        active_scope
        and scope.get("memory_scope") == "active"
        and not scope.get("cross_window_read")
        and (effective_session_id or effective_window_id)
        and _has_active_project_or_workstream_anchor(
            project_id=project_id,
            project_root=project_root,
            workstream_id=workstream_id,
            task_id=task_id,
        )
        and _specific_source_system_filters(source_system_filters)
        and not active_layers_used
        and needs_more_candidates
    )


def _item_has_source_backing(item: Dict[str, Any]) -> bool:
    return bool(
        _clean_text(item.get("source_path"))
        and _clean_text(item.get("raw_excerpt"))
        and _is_raw_evidence_status(item.get("raw_evidence_status", ""))
    )


def _query_active_empty_window_project_fallback(
    *,
    query: str,
    computer_name: str,
    limit: int,
    excerpt_chars: int,
    effective_session_id: str,
    effective_window_id: str,
    project_id: str,
    project_root: str,
    workstream_id: str,
    task_id: str,
    existing_items: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    stats: Dict[str, Any] = {
        "active_empty_window_project_fallback_used": False,
        "active_empty_window_project_fallback_status": "not_attempted",
        "active_empty_window_project_fallback_policy": (
            "same_project_workstream_only_source_backed_no_raw_pool"
        ),
        "active_empty_window_project_fallback_source_system_filters": ["all"],
        "active_empty_window_project_fallback_candidate_count": 0,
        "active_empty_window_project_fallback_routed_count": 0,
        "active_empty_window_project_fallback_layers_used": [],
        "active_empty_window_project_fallback_scope": "same_project_or_workstream",
        "active_empty_window_project_fallback_index_status": "not_attempted",
    }
    if not _has_active_project_or_workstream_anchor(
        project_id=project_id,
        project_root=project_root,
        workstream_id=workstream_id,
        task_id=task_id,
    ):
        stats["active_empty_window_project_fallback_status"] = "skipped_no_project_or_workstream_anchor"
        return [], stats

    fallback_limit = min(ACTIVE_RECALL_CANDIDATE_MAX, max(limit * 8, limit))
    candidate_items, index_status = _query_active_project_canonical_index(
        query=query,
        limit=fallback_limit,
        excerpt_chars=excerpt_chars,
        effective_session_id=effective_session_id,
        effective_window_id=effective_window_id,
        project_id=project_id,
        project_root=project_root,
        workstream_id=workstream_id,
        task_id=task_id,
    )
    stats["active_empty_window_project_fallback_index_status"] = index_status
    if index_status == "hit_declared_project_anchor":
        for item in candidate_items:
            item["declared_project_anchor_fallback"] = True
            item["_active_memory_layer_override"] = "same_project_workspace"

    candidate_items = _dedupe_recall_items(existing_items + candidate_items)
    routed_items, routed_layers = _apply_active_layered_routing(
        candidate_items,
        limit=limit,
        session_id=effective_session_id,
        canonical_window_id=effective_window_id,
        project_id=project_id,
        project_root=project_root,
        workstream_id=workstream_id,
        task_id=task_id,
    )
    fallback_items = [
        item for item in routed_items
        if item.get("active_empty_window_project_fallback")
        and item.get("active_memory_layer") in {"same_project_workspace", "same_workstream_task", "stable_user_preferences_tool_facts"}
        and _item_has_source_backing(item)
    ]
    fallback_layers = []
    for item in fallback_items:
        layer = str(item.get("active_memory_layer") or "")
        if layer and layer not in fallback_layers:
            fallback_layers.append(layer)
    stats["active_empty_window_project_fallback_used"] = bool(fallback_items)
    stats["active_empty_window_project_fallback_candidate_count"] = len(candidate_items)
    stats["active_empty_window_project_fallback_routed_count"] = len(fallback_items)
    stats["active_empty_window_project_fallback_layers_used"] = fallback_layers
    stats["active_empty_window_project_fallback_status"] = (
        "hit"
        if fallback_items
        else "miss_no_same_project_or_workstream_source_backed_evidence"
    )
    return fallback_items, stats


def _reading_area_registry_path_for_gateway() -> Path:
    explicit = _clean_text(os.environ.get("MEMCORE_READING_AREA_REGISTRY"))
    if explicit:
        return Path(explicit).expanduser()
    try:
        from src.config_loader import config_dir
    except Exception:
        try:
            from config_loader import config_dir
        except Exception:
            config_dir = None
    if config_dir is not None:
        try:
            return Path(config_dir()).expanduser() / "reading_area_registry.json"
        except Exception:
            pass
    return Path("config") / "reading_area_registry.json"


def _declared_project_scope_ids_for_anchor(project_id: str, project_root: str) -> List[str]:
    values = [
        _clean_text(project_id),
        _clean_text(project_root),
    ]
    root_tail = ""
    try:
        root_tail = Path(project_root).expanduser().name
    except Exception:
        root_tail = _clean_text(project_root).rstrip("/").rsplit("/", 1)[-1]
    if root_tail:
        values.append(root_tail)
    values = [value for value in values if value]
    if not values:
        return []
    try:
        data = json.loads(_reading_area_registry_path_for_gateway().read_text(encoding="utf-8-sig"))
    except Exception:
        return []
    if not isinstance(data, dict):
        return []
    projects = data.get("projects") if isinstance(data.get("projects"), dict) else {}
    aliases = data.get("aliases") if isinstance(data.get("aliases"), dict) else {}
    project_aliases = aliases.get("project") if isinstance(aliases.get("project"), dict) else {}
    result: List[str] = []
    for value in values:
        candidates = [value, value.lower()]
        if value in projects:
            candidates.append(value)
        for candidate in candidates:
            resolved = _clean_text(project_aliases.get(candidate) or "")
            if resolved and resolved not in result:
                result.append(resolved)
    lowered_values = {value.lower() for value in values}
    for scope_id, scope in projects.items():
        if not isinstance(scope, dict):
            continue
        scope_values = [
            _clean_text(scope_id),
            _clean_text(scope.get("name")),
            *[_clean_text(alias) for alias in (scope.get("aliases") or [])],
        ]
        if any(value.lower() in lowered_values for value in scope_values if value):
            resolved = _clean_text(scope_id)
            if resolved and resolved not in result:
                result.append(resolved)
    return result


def _declared_project_session_anchors(scope_ids: List[str]) -> List[Dict[str, str]]:
    if not scope_ids:
        return []
    try:
        data = json.loads(_reading_area_registry_path_for_gateway().read_text(encoding="utf-8-sig"))
    except Exception:
        return []
    if not isinstance(data, dict):
        return []
    cards = data.get("borrowing_cards") if isinstance(data.get("borrowing_cards"), dict) else {}
    anchors: List[Dict[str, str]] = []
    for card in cards.values():
        if not isinstance(card, dict):
            continue
        declared = [str(item) for item in (card.get("declared_project_ids") or [])]
        if not set(scope_ids) & set(declared):
            continue
        source_system = _declared_source_system(_clean_text(card.get("source_system")))
        consumer = _clean_text(card.get("consumer"))
        session_id = _clean_text(card.get("session_id"))
        window_id = _clean_text(card.get("canonical_window_id"))
        technical = card.get("technical_anchors") if isinstance(card.get("technical_anchors"), dict) else {}
        anchors.append({
            "source_system": source_system,
            "consumer": consumer,
            "session_id": session_id,
            "canonical_window_id": window_id,
            "technical_project_id": _clean_text(technical.get("project_id")),
            "technical_project_root": _clean_text(technical.get("project_root")),
            "technical_source_path": _clean_text(technical.get("source_path")),
        })
    return anchors


def _technical_project_anchors_from_declared_project(
    conn: sqlite3.Connection,
    *,
    project_id: str,
    project_root: str,
    limit: int,
) -> Tuple[List[Dict[str, str]], str]:
    scope_ids = _declared_project_scope_ids_for_anchor(project_id, project_root)
    if not scope_ids:
        return [], "not_declared_project"
    session_anchors = _declared_project_session_anchors(scope_ids)
    technical: List[Dict[str, str]] = []
    source_identity_missing = False

    def add(project: str, root: str, reason: str) -> None:
        project = _clean_text(project)
        root = _clean_text(root)
        if not project and not root:
            return
        item = {
            "project_id": project,
            "project_root": root,
            "reason": reason,
        }
        key = (item["project_id"], item["project_root"])
        if key not in {(existing["project_id"], existing["project_root"]) for existing in technical}:
            technical.append(item)

    for anchor in session_anchors:
        add(anchor.get("technical_project_id", ""), anchor.get("technical_project_root", ""), "declared_card_technical_anchor")
        declared_source_system = _clean_text(anchor.get("source_system", ""))
        if not declared_source_system:
            source_identity_missing = True
            continue
        source_tokens = _source_system_filter_query_tokens([declared_source_system])
        source_tokens = source_tokens or tuple(_specific_source_system_filters([declared_source_system]))
        identity_pairs = [
            ("session_id", anchor.get("session_id", "")),
            ("canonical_window_id", anchor.get("canonical_window_id", "")),
        ]
        for column, identity in identity_pairs:
            identity = _clean_text(identity)
            if not identity:
                continue
            source_where = ""
            params: List[Any] = []
            if source_tokens:
                source_where = f"source_system in ({','.join('?' for _ in source_tokens)}) and "
                params.extend(source_tokens)
            params.extend([identity, max(1, min(limit, 20))])
            try:
                rows = conn.execute(
                    f"""
                    select project_id, project_root
                    from canonical_messages
                    where {source_where}{column} = ?
                      and coalesce(project_id, project_root, '') != ''
                    order by timestamp desc, line_no desc
                    limit ?
                    """,
                    tuple(params),
                ).fetchall()
            except Exception:
                rows = []
            for row in rows:
                add(row["project_id"], row["project_root"], f"declared_card_{column}_canonical_index")
    if technical:
        return technical, "hit"
    if source_identity_missing:
        return [], "declared_project_source_system_required"
    return [], "declared_project_without_technical_anchor"


def _project_id_prefix_bounds(project_id: str) -> Tuple[str, str]:
    prefix = f"{project_id}-"
    return prefix, f"{project_id}."


def _append_unique_rows(rows: List[sqlite3.Row], seen: set[str], new_rows: List[sqlite3.Row]) -> None:
    for row in new_rows:
        key = _clean_text(row["message_id"])
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        rows.append(row)


def _project_row_query_plans(
    *,
    project_id: str,
    project_root: str,
    row_limit: int,
) -> List[Tuple[str, Tuple[Any, ...]]]:
    select_sql = """
        select message_id, record_id, source_system, session_id,
               canonical_window_id, project_id, project_root, source_path,
               raw_path, role, native_type, native_id, timestamp, line_no,
               raw_line_no, source_offset_start, source_offset_end,
               raw_offset_start, raw_offset_end, content_preview,
               updated_at
        from canonical_messages indexed by {index_name}
        where {where_sql}
          and coalesce(source_path, raw_path, '') != ''
        order by timestamp desc, line_no desc
        limit ?
    """
    plans: List[Tuple[str, Tuple[Any, ...]]] = []
    per_query_limit = max(row_limit, 1)
    if project_id:
        plans.append((
            select_sql.format(
                index_name="idx_canonical_messages_project_time",
                where_sql="project_id = ?",
            ),
            (project_id, per_query_limit),
        ))
        prefix_start, prefix_end = _project_id_prefix_bounds(project_id)
        plans.append((
            select_sql.format(
                index_name="idx_canonical_messages_project_time",
                where_sql="project_id >= ? and project_id < ?",
            ),
            (prefix_start, prefix_end, per_query_limit),
        ))
    if project_root:
        plans.append((
            select_sql.format(
                index_name="idx_canonical_messages_project_root_time",
                where_sql="project_root = ?",
            ),
            (project_root, per_query_limit),
        ))
    return plans


def _query_project_rows_with_indexes(
    conn: sqlite3.Connection,
    *,
    project_id: str,
    project_root: str,
    row_limit: int,
) -> List[sqlite3.Row]:
    rows: List[sqlite3.Row] = []
    seen: set[str] = set()
    for sql, params in _project_row_query_plans(
        project_id=project_id,
        project_root=project_root,
        row_limit=row_limit,
    ):
        by_root = conn.execute(sql, params).fetchall()
        _append_unique_rows(rows, seen, by_root)
    rows.sort(
        key=lambda row: (
            _clean_text(row["timestamp"]),
            int(row["line_no"] or 0),
        ),
        reverse=True,
    )
    return rows[:row_limit]


def _query_project_rows_for_technical_anchors(
    conn: sqlite3.Connection,
    *,
    anchors: List[Dict[str, str]],
    row_limit: int,
) -> List[sqlite3.Row]:
    rows: List[sqlite3.Row] = []
    seen: set[str] = set()
    for anchor in anchors[:PROJECT_FALLBACK_MAX_TECHNICAL_ANCHORS]:
        anchor_rows = _query_project_rows_with_indexes(
            conn,
            project_id=anchor.get("project_id", ""),
            project_root=anchor.get("project_root", ""),
            row_limit=row_limit,
        )
        _append_unique_rows(rows, seen, anchor_rows)
    rows.sort(
        key=lambda row: (
            _clean_text(row["timestamp"]),
            int(row["line_no"] or 0),
        ),
        reverse=True,
    )
    return rows


def _query_active_project_canonical_index(
    *,
    query: str,
    limit: int,
    excerpt_chars: int,
    effective_session_id: str,
    effective_window_id: str,
    project_id: str,
    project_root: str,
    workstream_id: str,
    task_id: str,
) -> Tuple[List[Dict[str, Any]], str]:
    db_path = _records_db_path_for_gateway()
    if not db_path.exists():
        return [], "records_db_missing"

    cleaned_project_id = _clean_text(project_id)
    cleaned_project_root = _clean_text(project_root)
    if not (cleaned_project_id or cleaned_project_root):
        return [], "project_anchor_required"

    query_terms = _raw_fallback_query_terms(query or "")
    row_limit = min(max(limit * 80, 200), 1200)
    declared_project_anchor_status = "not_attempted"
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=0.2)
        conn.row_factory = sqlite3.Row
        try:
            rows = _query_project_rows_with_indexes(
                conn,
                project_id=cleaned_project_id,
                project_root=cleaned_project_root,
                row_limit=row_limit,
            )
            if not rows:
                technical_anchors, declared_project_anchor_status = _technical_project_anchors_from_declared_project(
                    conn,
                    project_id=cleaned_project_id,
                    project_root=cleaned_project_root,
                    limit=row_limit,
                )
                rows = _query_project_rows_for_technical_anchors(
                    conn,
                    anchors=technical_anchors,
                    row_limit=row_limit,
                )
        finally:
            conn.close()
    except sqlite3.OperationalError as exc:
        message = str(exc).lower()
        if "no such table" in message:
            return [], "canonical_messages_missing"
        if "locked" in message or "busy" in message:
            return [], "records_db_busy"
        return [], "records_db_error"
    except Exception:
        return [], "records_db_error"

    scored_rows: List[Tuple[int, str, int, sqlite3.Row]] = []
    skipped_current_window = 0
    for row in rows:
        if not _canonical_dialogue_row_visible(row):
            continue
        row_session = _clean_text(row["session_id"])
        row_window = _clean_text(row["canonical_window_id"])
        if effective_session_id and row_session == effective_session_id:
            skipped_current_window += 1
            continue
        if effective_window_id and row_window == effective_window_id:
            skipped_current_window += 1
            continue
        preview = _clean_text(row["content_preview"])
        if not preview:
            continue
        meta_text = "\n".join(
            _clean_text(value)
            for value in (
                row["source_system"],
                row["session_id"],
                row["canonical_window_id"],
                row["project_id"],
                row["project_root"],
                row["source_path"],
                row["raw_path"],
                row["native_type"],
            )
            if _clean_text(value)
        )
        if query_terms and not _raw_fallback_matches(query_terms, preview, meta_text):
            continue
        scored_rows.append((
            sum(1 for term in query_terms if term in (preview + "\n" + meta_text).lower()),
            _clean_text(row["timestamp"]),
            int(row["line_no"] or 0),
            row,
        ))

    if query_terms:
        scored_rows.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    else:
        scored_rows.sort(key=lambda item: (item[1], item[2]), reverse=True)

    items: List[Dict[str, Any]] = []
    for _score, _timestamp, _line_no, row in scored_rows:
        item = _active_project_index_item(
            row,
            excerpt_chars=excerpt_chars,
            workstream_id=workstream_id,
            task_id=task_id,
        )
        if item is None:
            continue
        items.append(_annotate_gateway_item(item, query or ""))
        if len(items) >= limit:
            break
    if items:
        if declared_project_anchor_status == "hit":
            return items, "hit_declared_project_anchor"
        return items, "hit"
    if rows and skipped_current_window:
        return [], "miss_only_current_window_rows"
    if rows:
        return [], "miss_content_filter"
    if declared_project_anchor_status not in {"not_attempted", "not_declared_project"}:
        return [], declared_project_anchor_status
    return [], "miss_project"


def _active_project_index_item(
    row: sqlite3.Row,
    *,
    excerpt_chars: int,
    workstream_id: str,
    task_id: str,
) -> Dict[str, Any] | None:
    preview = _clean_text(row["content_preview"])
    source_path = _first_text(row["raw_path"], row["source_path"])
    if not preview or not source_path:
        return None
    offset_start = (
        row["raw_offset_start"]
        if row["raw_offset_start"] is not None
        else row["source_offset_start"]
    )
    offset_end = (
        row["raw_offset_end"]
        if row["raw_offset_end"] is not None
        else row["source_offset_end"]
    )
    bounded = preview[:excerpt_chars]
    row_source_system = _clean_text(row["source_system"])
    row_session_id = _clean_text(row["session_id"])
    row_window_id = _clean_text(row["canonical_window_id"])
    project_id = _clean_text(row["project_id"])
    normalized_identity = _normalize_source_system_window_identity(
        source_system=row_source_system,
        session_id=row_session_id,
        canonical_window_id=row_window_id,
        project_id=project_id,
    )
    row_session_id = normalized_identity["session_id"] or row_session_id
    row_window_id = normalized_identity["canonical_window_id"] or row_window_id
    project_id = normalized_identity["project_id"]
    legacy_window_id = normalized_identity["source_refs_canonical_window_id"]
    msg_id = _first_text(row["native_id"], row["timestamp"], row["message_id"])
    item: Dict[str, Any] = {
        "memory_type": "case_memory",
        "source_kind": "raw_jsonl",
        "exp_id": f"raw-project-index-{hashlib.sha256(str(row['message_id']).encode('utf-8')).hexdigest()[:16]}",
        "summary": bounded[:200],
        "should_inject": False,
        "confidence": None,
        "source_system": row_source_system,
        "computer_name": "",
        "canonical_window_id": row_window_id,
        "session_id": row_session_id,
        "project_id": project_id,
        "project_root": row["project_root"] or "",
        "workstream_id": workstream_id,
        "task_id": task_id,
        "native_session_key": row_session_id,
        "native_artifact_format": row["native_type"] or "",
        "raw_archive_layout": "canonical_record_index",
        "source_path": source_path,
        "source_path_indexed": row["source_path"] or "",
        "raw_path_indexed": row["raw_path"] or "",
        "msg_ids": [msg_id] if msg_id else [],
        "byte_offsets": {"start": offset_start, "end": offset_end},
        "artifact_type": row["native_type"] or f"{row_source_system}_canonical_message",
        "raw_excerpt": bounded,
        "evidence_hash": hashlib.sha256(bounded.encode("utf-8")).hexdigest() if bounded else None,
        "created_at": row["timestamp"] or row["updated_at"] or ts(),
        "raw_evidence_status": "raw_index",
        "raw_mapping_mode": "canonical_project_index",
        "zhiyi_experience_used_as_raw": False,
        "matched_by": ["canonical_project_index"],
        "rank_reason": "canonical_project_index_same_project_source_backed",
        "active_empty_window_project_fallback": True,
    }
    if legacy_window_id:
        item["source_refs_canonical_window_id"] = legacy_window_id
    return item


def _active_layer_for_item(
    item: Dict[str, Any],
    *,
    session_id: str,
    canonical_window_id: str,
    project_id: str,
    project_root: str,
    workstream_id: str,
    task_id: str,
) -> str:
    if session_id and _clean_text(item.get("session_id")) == session_id:
        return "current_window"
    if canonical_window_id and _clean_text(item.get("canonical_window_id")) == canonical_window_id:
        return "current_window"
    if canonical_window_id and _item_legacy_window_id(item) == canonical_window_id:
        return "current_window"
    if project_id and _item_project_id(item) == project_id:
        return "same_project_workspace"
    if project_root and _normalize_path_text(_item_project_root(item)) == _normalize_path_text(project_root):
        return "same_project_workspace"
    layer_override = _clean_text(item.get("_active_memory_layer_override"))
    if (
        layer_override == "same_project_workspace"
        and item.get("declared_project_anchor_fallback")
        and item.get("active_empty_window_project_fallback")
    ):
        return "same_project_workspace"
    if workstream_id and _item_workstream_id(item) == workstream_id:
        return "same_workstream_task"
    if task_id and _item_task_id(item) == task_id:
        return "same_workstream_task"
    memory_type = _clean_text(item.get("memory_type") or item.get("type")).lower()
    stable_types = {
        "preference_memory",
        "tool_fact",
        "tool_facts",
        "toolbook",
        "toolbook_candidate",
        "model_fact",
        "source_system_fact",
        "source_system_profile",
    }
    if (
        memory_type in stable_types
        or memory_type.startswith("tool")
        or memory_type.endswith("_fact")
    ):
        return "stable_user_preferences_tool_facts"
    return ""


def _apply_active_layered_routing(
    items: List[Dict[str, Any]],
    *,
    limit: int,
    session_id: str,
    canonical_window_id: str,
    project_id: str,
    project_root: str,
    workstream_id: str,
    task_id: str,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    order = [
        "current_window",
        "current_session",
        "same_project_workspace",
        "same_workstream_task",
        "stable_user_preferences_tool_facts",
    ]
    layered: Dict[str, List[Dict[str, Any]]] = {layer: [] for layer in order}
    seen_keys = set()
    for item in items:
        layer = _active_layer_for_item(
            item,
            session_id=session_id,
            canonical_window_id=canonical_window_id,
            project_id=project_id,
            project_root=project_root,
            workstream_id=workstream_id,
            task_id=task_id,
        )
        if not layer:
            continue
        key = (
            str(item.get("source_path", "")),
            tuple(item.get("msg_ids") or []),
            str(item.get("exp_id", "")),
            str(item.get("raw_excerpt", "")),
        )
        if key in seen_keys:
            continue
        seen_keys.add(key)
        routed = dict(item)
        routed["active_memory_layer"] = layer
        layered[layer].append(routed)

    selected: List[Dict[str, Any]] = []
    used_layers: List[str] = []
    for layer in order:
        for item in layered[layer]:
            selected.append(item)
            if layer not in used_layers:
                used_layers.append(layer)
            if len(selected) >= limit:
                return selected, used_layers
    return selected, used_layers


def _query_raw_jsonl_fallback(
    query: str,
    source_system: str,
    computer_name: str,
    session_id: str,
    canonical_window_id: str,
    limit: int,
    excerpt_chars: int,
    *,
    max_files: int = RAW_FALLBACK_DEFAULT_MAX_FILES,
    max_bytes: int = RAW_FALLBACK_DEFAULT_MAX_BYTES,
    max_lines: int = RAW_FALLBACK_DEFAULT_MAX_LINES,
    deadline_seconds: float = RAW_FALLBACK_DEFAULT_DEADLINE_SECONDS,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    stats: Dict[str, Any] = {
        "raw_fallback_used": True,
        "raw_fallback_status": "not_started",
        "raw_fallback_scanned_files": 0,
        "raw_fallback_scanned_bytes": 0,
        "raw_fallback_scanned_lines": 0,
        "raw_fallback_truncated": False,
        "raw_fallback_timed_out": False,
    }
    query_text = str(query or "").strip()
    query_terms = _raw_fallback_query_terms(query_text)
    canonical_window_id = str(canonical_window_id or "").strip()
    if not query_text and not session_id and not canonical_window_id:
        stats["raw_fallback_status"] = "identity_required"
        return [], stats

    try:
        from src.config_loader import memory_root
    except ImportError:
        try:
            from config_loader import memory_root
        except ImportError:
            memory_root = None
    if memory_root is None:
        stats["raw_fallback_status"] = "memory_root_missing"
        return [], stats

    root = Path(memory_root()).expanduser()
    if not root.exists():
        stats["raw_fallback_status"] = "memory_root_missing"
        return [], stats

    candidates: List[Path] = []
    current_patterns: List[str]
    if source_system and computer_name:
        current_patterns = [f"{computer_name}/{source_system}/*/*/*.jsonl"]
    elif source_system:
        current_patterns = [f"*/{source_system}/*/*/*.jsonl"]
    else:
        current_patterns = ["*/*/*/*/*.jsonl"]

    legacy_patterns: List[str]
    if source_system:
        legacy_patterns = [f"{source_system}/*/*/*.jsonl"]
    else:
        legacy_patterns = ["*/*/*.jsonl"]

    for pattern in current_patterns + legacy_patterns:
        for path in root.glob(pattern):
            parts = path.relative_to(root).parts
            if len(parts) >= 5:
                comp = parts[0]
                src = parts[1]
            elif len(parts) >= 4:
                src = parts[0]
                comp = parts[1]
            else:
                continue
            if source_system and src != source_system:
                continue
            if computer_name and comp != computer_name:
                continue
            if session_id and path.stem != session_id:
                continue
            if canonical_window_id:
                if len(parts) >= 5:
                    window = parts[3]
                elif len(parts) >= 4:
                    window = parts[2]
                else:
                    window = ""
                session_matches = bool(
                    session_id
                    and path.stem == session_id
                )
                if not session_matches and window != canonical_window_id:
                    continue
            candidates.append(path)
    candidates = list(dict.fromkeys(candidates))

    candidates.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
    if len(candidates) > max_files:
        candidates = candidates[:max_files]
        stats["raw_fallback_truncated"] = True
    items: List[Dict[str, Any]] = []
    started = time.monotonic()
    for path in candidates:
        if time.monotonic() - started > deadline_seconds:
            stats["raw_fallback_timed_out"] = True
            stats["raw_fallback_truncated"] = True
            break
        try:
            file_size = path.stat().st_size
        except Exception:
            file_size = 0
        if stats["raw_fallback_scanned_bytes"] + file_size > max_bytes:
            stats["raw_fallback_truncated"] = True
            break
        try:
            rel = path.relative_to(root).parts
        except Exception:
            rel = ()
        if len(rel) >= 5:
            comp = rel[0]
            src = rel[1]
            native_format = rel[2]
            window = rel[3]
            layout = "computer_first"
        elif len(rel) >= 4:
            src = rel[0]
            comp = rel[1]
            native_format = ""
            window = rel[2]
            layout = "legacy_source_first"
        else:
            continue
        sid = path.stem
        meta_text = _raw_fallback_meta_text(path, root)
        stats["raw_fallback_scanned_files"] += 1
        stats["raw_fallback_scanned_bytes"] += file_size
        try:
            for start, end, text in _iter_decoded_jsonl_lines(path):
                if time.monotonic() - started > deadline_seconds:
                    stats["raw_fallback_timed_out"] = True
                    stats["raw_fallback_truncated"] = True
                    break
                if stats["raw_fallback_scanned_lines"] >= max_lines:
                    stats["raw_fallback_truncated"] = True
                    break
                stats["raw_fallback_scanned_lines"] += 1
                if len(items) >= limit:
                    break
                text = text.strip()
                if not text:
                    continue
                if query_terms and not _raw_fallback_matches(query_terms, text, meta_text):
                    continue
                try:
                    obj = json.loads(text)
                except Exception:
                    obj = {}
                excerpt_parts: List[str] = []
                if isinstance(obj, dict):
                    _append_jsonl_obj_excerpt(obj, [], excerpt_parts)
                raw_excerpt = " | ".join(excerpt_parts).strip() or text
                bounded = raw_excerpt[:excerpt_chars]
                evidence_hash = hashlib.sha256(bounded.encode("utf-8")).hexdigest() if bounded else None
                msg_id = ""
                project_id = ""
                project_root = ""
                workstream_id = ""
                task_id = ""
                if isinstance(obj, dict):
                    payload = obj.get("payload", {}) if isinstance(obj.get("payload"), dict) else {}
                    source_refs = obj.get("source_refs", {}) if isinstance(obj.get("source_refs"), dict) else {}
                    msg_id = str(
                        obj.get("id")
                        or payload.get("turn_id")
                        or obj.get("timestamp")
                        or f"offset:{start}"
                    )
                    project_id = _first_text(
                        obj.get("project_id"),
                        payload.get("project_id"),
                        source_refs.get("project_id"),
                    )
                    project_root = _first_text(
                        obj.get("project_root"),
                        obj.get("workspace_root"),
                        obj.get("cwd"),
                        payload.get("project_root"),
                        payload.get("workspace_root"),
                        payload.get("cwd"),
                        source_refs.get("project_root"),
                        source_refs.get("workspace_root"),
                        source_refs.get("cwd"),
                    )
                    workstream_id = _first_text(
                        obj.get("workstream_id"),
                        obj.get("workstream"),
                        payload.get("workstream_id"),
                        payload.get("workstream"),
                        source_refs.get("workstream_id"),
                        source_refs.get("workstream"),
                    )
                    task_id = _first_text(
                        obj.get("task_id"),
                        obj.get("task"),
                        payload.get("task_id"),
                        payload.get("task"),
                        source_refs.get("task_id"),
                        source_refs.get("task"),
                    )
                normalized_identity = _normalize_source_system_window_identity(
                    source_system=src,
                    session_id=sid,
                    canonical_window_id=window,
                    project_id=project_id,
                )
                item_window_id = normalized_identity["canonical_window_id"] or window
                legacy_window_id = normalized_identity["source_refs_canonical_window_id"]
                project_id = normalized_identity["project_id"]
                item = {
                    "memory_type": "raw_jsonl",
                    "exp_id": "raw-{}".format(hashlib.sha256(f"{path}:{start}:{end}".encode()).hexdigest()[:16]),
                    "summary": bounded[:200],
                    "should_inject": False,
                    "confidence": None,
                    "source_system": src,
                    "computer_name": comp,
                    "canonical_window_id": item_window_id,
                    "session_id": sid,
                    "project_id": project_id,
                    "project_root": project_root,
                    "workstream_id": workstream_id,
                    "task_id": task_id,
                    "native_session_key": sid,
                    "native_artifact_format": native_format,
                    "raw_archive_layout": layout,
                    "source_path": str(path),
                    "msg_ids": [msg_id] if msg_id else [],
                    "byte_offsets": {"start": start, "end": end},
                    "artifact_type": native_format or f"{src}_session_jsonl",
                    "raw_excerpt": bounded,
                    "evidence_hash": evidence_hash,
                    "created_at": ts(),
                    "raw_evidence_status": "raw_direct",
                    "raw_mapping_mode": "raw_jsonl_fallback",
                    "zhiyi_experience_used_as_raw": False,
                }
                if legacy_window_id:
                    item["source_refs_canonical_window_id"] = legacy_window_id
                items.append(item)
                if len(items) >= limit:
                    break
        except Exception:
            continue
        if len(items) >= limit:
            break
        if stats["raw_fallback_timed_out"] or stats["raw_fallback_truncated"]:
            break
    if items:
        stats["raw_fallback_status"] = "hit_truncated" if stats["raw_fallback_truncated"] else "hit"
    else:
        stats["raw_fallback_status"] = "miss_truncated" if stats["raw_fallback_truncated"] else "miss"
    return items, stats


def _gateway_zhiyi_root() -> Path:
    override = os.environ.get("MEMCORE_ZHIYI_ROOT_OVERRIDE")
    if override:
        return Path(override).expanduser()
    try:
        from src.config_loader import zhiyi_root
    except ImportError:
        try:
            from config_loader import zhiyi_root
        except ImportError:
            zhiyi_root = None
    if zhiyi_root is None:
        return Path()
    return Path(zhiyi_root()).expanduser()


def _gateway_recent_delta_file_specs() -> List[Tuple[str, Path]]:
    root = _gateway_zhiyi_root()
    if not root:
        return []
    return [
        (ftype, root / ftype / f"{ftype}.jsonl")
        for ftype in ("preference_memory", "case_memory", "error_memory")
    ]


def _read_gateway_recent_delta_records() -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    stats: Dict[str, Any] = {
        "applied": False,
        "reason": "not_checked",
        "doc_count": 0,
        "truncated": False,
        "source_files": [],
        "bytes_read": 0,
        "max_docs": GATEWAY_RECENT_DELTA_MAX_DOCS,
        "max_bytes": GATEWAY_RECENT_DELTA_MAX_BYTES,
        "full_refresh_waited": False,
    }
    records: List[Dict[str, Any]] = []
    remaining = max(0, GATEWAY_RECENT_DELTA_MAX_BYTES)
    if remaining <= 0:
        stats["reason"] = "disabled"
        return records, stats

    for ftype, path in _gateway_recent_delta_file_specs():
        if remaining <= 0:
            stats["truncated"] = True
            break
        try:
            size = path.stat().st_size
        except FileNotFoundError:
            continue
        except Exception:
            continue
        if size <= 0:
            continue
        to_read = min(size, remaining)
        start = max(0, size - to_read)
        try:
            with path.open("rb") as f:
                f.seek(start)
                if start > 0:
                    f.readline()
                data = f.read(to_read)
        except Exception:
            continue
        if start > 0:
            stats["truncated"] = True
        remaining -= len(data)
        stats["bytes_read"] += len(data)
        stats["source_files"].append(str(path))
        file_records: List[Dict[str, Any]] = []
        for raw_line in data.decode("utf-8", errors="ignore").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except Exception:
                continue
            if not isinstance(record, dict):
                continue
            item = dict(record)
            item["_gateway_recent_delta_type"] = str(item.get("type") or ftype)
            file_records.append(item)
        if len(file_records) > GATEWAY_RECENT_DELTA_MAX_DOCS:
            file_records = file_records[-GATEWAY_RECENT_DELTA_MAX_DOCS:]
            stats["truncated"] = True
        records.extend(file_records)
    stats["doc_count"] = len(records)
    stats["reason"] = "bounded_tail_read" if records else "no_recent_delta_records"
    return records, stats


def _gateway_recent_delta_record_matches(record: Dict[str, Any], query: str) -> bool:
    q = str(query or "").strip().lower()
    if not q:
        return False
    parts = [
        record.get("exp_id", ""),
        record.get("summary", ""),
        record.get("detail", ""),
        record.get("verbatim_excerpt", ""),
        record.get("source_refs", ""),
    ]
    text = "\n".join(str(part or "") for part in parts).lower()
    return q in text


def _gateway_recent_delta_item(record: Dict[str, Any], query: str, excerpt_chars: int) -> Dict[str, Any]:
    sr = _json_loads_maybe(record.get("source_refs", {}))
    sr_source_system = _first_text(sr.get("source_system"), record.get("source_system"))
    sr_computer_name = _first_text(sr.get("computer_name"), sr.get("computer_id"), record.get("computer_id"))
    sr_session_id = _first_text(sr.get("session_id"), record.get("session_id"))
    sr_window_id = _first_text(sr.get("canonical_window_id"), record.get("canonical_window_id"))
    sr_legacy_window_id = _first_text(sr.get("source_refs_canonical_window_id"), record.get("source_refs_canonical_window_id"))
    sr_project_id = _first_text(sr.get("project_id"), record.get("project_id"))
    normalized_identity = _normalize_source_system_window_identity(
        source_system=sr_source_system,
        session_id=sr_session_id,
        canonical_window_id=sr_window_id,
        project_id=sr_project_id,
        legacy_window_id=sr_legacy_window_id,
    )
    sr_session_id = normalized_identity["session_id"]
    sr_window_id = normalized_identity["canonical_window_id"]
    sr_project_id = normalized_identity["project_id"]
    sr_legacy_window_id = normalized_identity["source_refs_canonical_window_id"]
    source_path = str(sr.get("source_path") or "")
    msg_ids = sr.get("msg_ids", []) or []
    raw_excerpt, raw_status, evidence_hash = _extract_bounded_raw_excerpt(
        source_path,
        msg_ids,
        excerpt_chars,
        sr,
    )
    if not raw_excerpt:
        raw_excerpt = str(record.get("summary") or record.get("detail") or "")[:excerpt_chars]
        evidence_hash = hashlib.sha256(raw_excerpt.encode("utf-8")).hexdigest() if raw_excerpt else None
        raw_status = "zhiyi_recent_delta_without_raw_excerpt"
    memory_type = str(record.get("_gateway_recent_delta_type") or record.get("type") or "")
    return {
        "type": memory_type,
        "memory_type": memory_type,
        "exp_id": str(record.get("exp_id") or ""),
        "summary": str(record.get("summary") or "")[:800],
        "detail": str(record.get("detail") or "")[:1200],
        "should_inject": True,
        "confidence": record.get("score", record.get("confidence", 0.7)),
        "source_system": sr_source_system,
        "computer_name": sr_computer_name,
        "canonical_window_id": sr_window_id,
        "session_id": sr_session_id,
        "project_id": sr_project_id,
        "project_root": _first_text(sr.get("project_root"), sr.get("workspace_root"), sr.get("cwd"), record.get("project_root"), record.get("workspace_root"), record.get("cwd")),
        "workstream_id": _first_text(sr.get("workstream_id"), sr.get("workstream"), record.get("workstream_id"), record.get("workstream")),
        "task_id": _first_text(sr.get("task_id"), sr.get("task"), record.get("task_id"), record.get("task")),
        "native_session_key": sr_session_id or str(record.get("exp_id") or ""),
        "source_path": source_path,
        "msg_ids": msg_ids,
        "raw_excerpt": raw_excerpt,
        "evidence_hash": evidence_hash,
        "created_at": ts(),
        "raw_evidence_status": raw_status if source_path else "not_raw",
        "zhiyi_experience_used_as_raw": False,
        "matched_by": "recent_delta",
        "rank_reason": "bounded_gateway_recent_delta_default_recall",
        "source_refs_canonical_window_id": sr_legacy_window_id,
    }


def _query_gateway_recent_delta_items(query: str, excerpt_chars: int) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    records, stats = _read_gateway_recent_delta_records()
    matched = [
        _gateway_recent_delta_item(record, query, excerpt_chars)
        for record in records
        if _gateway_recent_delta_record_matches(record, query)
    ]
    stats["applied"] = bool(matched)
    stats["matched_count"] = len(matched)
    stats["reason"] = (
        "bounded_gateway_recent_delta_default_recall_hit"
        if matched
        else "bounded_gateway_recent_delta_no_query_hit"
        if records
        else stats.get("reason", "no_recent_delta_records")
    )
    return matched, stats


def _preflight_recent_context_allowed(query: str) -> bool:
    text = _clean_text(query)
    if not text:
        return False
    prompt = classify_prompt(text)
    if not bool(prompt.get("should_recall")):
        return False
    prompt_class = str(prompt.get("prompt_class") or "")
    if prompt_class not in {"continuation", "status", "task", "preference", "correction"}:
        return False
    compact_text = re.sub(r"\s+", "", text)
    query_terms = _raw_fallback_query_terms(text)
    if len(compact_text) <= 32:
        return True
    return (
        len(compact_text) <= 48
        and 0 < len(query_terms) <= 2
        and all(len(term) <= 16 for term in query_terms)
    )


def _focused_cjk_query_terms(text: str) -> List[str]:
    value = _clean_text(text).lower().strip("？?。.!！,，；;：:")
    if not value or not re.search(r"[\u4e00-\u9fff]", value):
        return []
    candidates: List[str] = []
    for marker in (
        "还记不记得",
        "是否还记得",
        "有没有记得",
        "你还记得",
        "还记得",
        "记得",
        "回忆一下",
        "回忆",
        "想起来",
        "什么是",
        "关于",
    ):
        if marker in value:
            candidates.append(value.split(marker, 1)[1])
    result: List[str] = []
    for candidate in candidates:
        cleaned = candidate.strip().strip("？?。.!！,，；;：:的了呢吗么吧啊呀").strip()
        if len(cleaned) >= 2 and cleaned not in result:
            result.append(cleaned)
        for token in re.findall(r"[\w\-.:\u4e00-\u9fff]+", cleaned):
            token = token.strip("._:-？?。.!！,，；;：:的了呢吗么吧啊呀")
            if len(token) >= 2 and token not in result:
                result.append(token)
    return result


def _strip_cjk_query_suffix(text: str) -> str:
    value = _clean_text(text).strip()
    for suffix in (
        "怎么验证",
        "怎么测试",
        "怎么验",
        "怎么做",
        "怎么办",
        "是什么",
    ):
        if value.endswith(suffix):
            return value[: -len(suffix)].strip("？?。.!！,，；;：:的了呢吗么吧啊呀 ")
    return value


MEMORY_PROMPT_QUERY_STOP_TERMS = {
    "你还记得",
    "还记得",
    "记得",
    "回忆一下",
    "回忆",
    "怎么验",
    "怎么验证",
    "怎么测试",
    "怎么做",
    "是什么",
    "怎么办",
    "remember",
    "recall",
}


def _canonical_dialogue_row_visible(row: sqlite3.Row) -> bool:
    role = _clean_text(row["role"]).lower()
    native_type = _clean_text(row["native_type"]).lower()
    runtime_roles = {"tool", "tool_result", "tool_use", "function", "function_call", "function_call_output"}
    if role in runtime_roles or native_type in runtime_roles:
        return False
    return role in {"", "user", "assistant", "message"}


def _raw_fallback_query_terms(query: str) -> List[str]:
    terms: List[str] = []
    focused_terms = _focused_cjk_query_terms(str(query or ""))
    for focused in focused_terms:
        if focused not in terms:
            terms.append(focused)
    for term in re.findall(r"[\w\-.:\u4e00-\u9fff]+", str(query or "").lower()):
        cleaned = term.strip("._:-？?。.!！,，；;：:")
        if re.search(r"[\u4e00-\u9fff]", cleaned):
            cleaned = cleaned.strip("的了呢吗么吧啊呀")
            cleaned = _strip_cjk_query_suffix(cleaned)
        if cleaned in MEMORY_PROMPT_QUERY_STOP_TERMS:
            continue
        if focused_terms and cleaned not in focused_terms and _focused_cjk_query_terms(cleaned):
            continue
        if len(cleaned) >= 2 and cleaned not in terms:
            terms.append(cleaned)
        for focused in _focused_cjk_query_terms(cleaned):
            if focused not in terms:
                terms.append(focused)
    return terms


def _raw_fallback_meta_text(path: Path, root: Path) -> str:
    parts: List[str] = []
    try:
        parts.extend(str(part) for part in path.relative_to(root).parts)
    except Exception:
        parts.append(str(path))
    meta_path = Path(str(path) + ".meta.json")
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8-sig"))
        except Exception:
            meta = {}
        if isinstance(meta, dict):
            for key in (
                "thread_name",
                "project_id",
                "project_root",
                "session_id",
                "conversation_origin",
                "runtime_consumer",
                "storage_owner",
                "body_storage_owner",
                "desktop_session_id",
            ):
                value = meta.get(key)
                if value:
                    parts.append(str(value))
    return "\n".join(parts).lower()


def _raw_fallback_matches(query_terms: List[str], line_text: str, meta_text: str) -> bool:
    haystack = (str(line_text or "") + "\n" + str(meta_text or "")).lower()
    if not query_terms:
        return True
    matched = sum(1 for term in query_terms if term in haystack)
    if matched == len(query_terms):
        return True
    if matched >= max(2, min(len(query_terms), 3)):
        return True
    return False


def _consumer_receipt(
    consumer: str,
    request_id: str,
    items_count: int,
    source_refs_count: int,
    raw_items_count: int,
    items: List[Dict[str, Any]] | None = None,
    raw_recall_trajectory: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    return _explainability_consumer_receipt(
        consumer=consumer,
        request_id=request_id,
        items_count=items_count,
        source_refs_count=source_refs_count,
        raw_items_count=raw_items_count,
        items=items,
        raw_trajectory=raw_recall_trajectory,
    )


def _truthy(value: Any) -> bool:
    return _routing_truthy(value)


def _load_default_recall_preference() -> Dict[str, Any]:
    path = Path(str(_memcore_base_path())) / "config" / "zhiyi_model_binding.user.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        payload = {}
    raw = payload.get("vector_recall_preference") if isinstance(payload, dict) else {}
    if not isinstance(raw, dict):
        raw = {}
    enabled = _truthy(raw.get("enabled", False))
    vector_assets = {}
    if enabled:
        try:
            from src.granite_vector_assets import granite_asset_status
        except Exception:
            try:
                from granite_vector_assets import granite_asset_status
            except Exception:
                granite_asset_status = None
        if granite_asset_status is not None:
            vector_assets = granite_asset_status(_memcore_base_path())
            if not vector_assets.get("ready"):
                enabled = False
    return {
        "configured": bool(raw),
        "enabled": enabled,
        "default_recall_mode": "vector" if enabled else "substring",
        "fts5_recall": not enabled,
        "source": str(path),
        "hot_switch_status": str(raw.get("hot_switch_status") or "effective_for_new_gateway_requests"),
        "requires_restart": _truthy(raw.get("requires_restart", False)),
        "forced_fallback": bool(raw) and not enabled and bool(vector_assets),
        "fallback_reason": "vector_assets_not_ready" if vector_assets and not vector_assets.get("ready") else "",
        "vector_asset_status": vector_assets,
    }


def _resolve_recall_scope(
    *,
    source_system: str,
    consumer: str,
    memory_scope: str,
    canonical_window_id: str,
    session_id: str,
    allow_cross_window_recall: bool = False,
    cross_window_reason: str = "",
) -> Dict[str, Any]:
    return _routing_resolve_recall_scope(
        source_system=source_system,
        consumer=consumer,
        memory_scope=memory_scope,
        canonical_window_id=canonical_window_id,
        session_id=session_id,
        allow_cross_window_recall=allow_cross_window_recall,
        cross_window_reason=cross_window_reason,
    )


def _scope_missing_status(scope: Dict[str, Any]) -> Dict[str, str]:
    return _routing_scope_missing_status(scope)


def _is_capability_check_request(args: Dict[str, Any]) -> bool:
    mode = str(args.get("mode") or "").strip().lower()
    return (
        mode == "capability_check"
        or _truthy(args.get("capability_check"))
        or _truthy(args.get("no_recall"))
    )


def _is_preflight_request(args: Dict[str, Any]) -> bool:
    return str(args.get("mode") or "").strip().lower() == "preflight"


def _is_work_preflight_request(args: Dict[str, Any]) -> bool:
    return str(args.get("mode") or "").strip().lower() in {"work_preflight", "agent_work_preflight"}


def _mcp_runtime():
    try:
        from src import raw_gateway_mcp_runtime as runtime
    except Exception:
        import raw_gateway_mcp_runtime as runtime
    return runtime


def _platform_handshake_receipt(params: Dict[str, Any] | None = None) -> Dict[str, Any]:
    return _mcp_runtime()._platform_handshake_receipt(params)


def _platform_self_report_connect_payload(
    args: Dict[str, Any],
    *,
    connection_context: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    return _mcp_runtime()._platform_self_report_connect_payload(
        args,
        connection_context=connection_context,
    )


def build_mcp_initialize_result(
    params: Dict[str, Any] | None = None,
    *,
    startup_catalog_mode: str = "full",
) -> Dict[str, Any]:
    return _mcp_runtime().build_mcp_initialize_result(
        params,
        startup_catalog_mode=startup_catalog_mode,
    )


def mcp_call_tool(
    name: str,
    arguments: Dict[str, Any],
    *,
    connection_context: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    return _mcp_runtime().mcp_call_tool(
        name,
        arguments,
        connection_context=connection_context,
    )


def handle_mcp_request(
    data: Dict[str, Any],
    *,
    startup_catalog_mode: str = "full",
    connection_context: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any] | None:
    return _mcp_runtime().handle_mcp_request(
        data,
        startup_catalog_mode=startup_catalog_mode,
        connection_context=connection_context,
    )


def _preflight_kwargs_from_args(
    args: Dict[str, Any],
    *,
    consumer_default: str,
    limit_default: int,
    excerpt_default: int,
    binding_identity: Optional[str] = None,
) -> Dict[str, Any]:
    kwargs = {
        "query": str(args.get("query") or args.get("q") or ""),
        "source_system": str(args.get("source_system") or ""),
        "computer_name": str(args.get("computer_name") or ""),
        "session_id": str(args.get("session_id") or ""),
        "limit": args.get("limit", limit_default),
        "excerpt_chars": args.get("excerpt_chars", excerpt_default),
        "consumer": str(args.get("consumer") or consumer_default),
        "request_id": str(args.get("request_id") or ""),
        "memory_scope": str(args.get("memory_scope") or ""),
        "canonical_window_id": str(args.get("canonical_window_id") or ""),
        "allow_cross_window_recall": _truthy(args.get("allow_cross_window_recall")),
        "cross_window_reason": str(args.get("cross_window_reason") or args.get("workflow_reason") or ""),
        "project_id": str(args.get("project_id") or ""),
        "project_root": str(args.get("project_root") or args.get("workspace_root") or args.get("cwd") or ""),
        "workstream_id": str(args.get("workstream_id") or args.get("workstream") or ""),
        "task_id": str(args.get("task_id") or args.get("task") or ""),
        "force_task_preflight": bool(args.get("force_task_preflight")),
        "fast_preflight_miss_policy": str(args.get("fast_preflight_miss_policy") or ""),
        "binding_identity": binding_identity,
    }
    if _is_work_preflight_request(args):
        kwargs.update({
            "deep_work_preflight": _truthy(args.get("deep_work_preflight")),
            "full_work_preflight": _truthy(args.get("full_work_preflight")),
            "allow_full_work_preflight": _truthy(args.get("allow_full_work_preflight")),
            "allow_cold_work_preflight": _truthy(args.get("allow_cold_work_preflight")),
        })
    return kwargs


def _work_preflight_from_kwargs(kwargs: Dict[str, Any]) -> Dict[str, Any]:
    return build_gateway_agent_work_preflight(
        query=str(kwargs.get("query") or ""),
        preflight_builder=preflight_payload,
        preflight_kwargs=kwargs,
        consumer=str(kwargs.get("consumer") or ""),
        request_id=str(kwargs.get("request_id") or ""),
    )


def _preflight_has_active_anchor(
    *,
    session_id: str,
    canonical_window_id: str,
    project_id: str,
    project_root: str,
    workstream_id: str,
    task_id: str,
) -> bool:
    return any(
        _clean_text(value)
        for value in (
            session_id,
            canonical_window_id,
            project_id,
            project_root,
            workstream_id,
            task_id,
        )
    )


def _current_window_binding_anchor(binding_identity: str) -> Dict[str, Any]:
    if get_current_window_binding is None:
        return {}
    try:
        binding = get_current_window_binding(binding_identity)
    except Exception:
        return {}
    return binding if isinstance(binding, dict) else {}


_binding_metadata = _raw_recall_preflight._binding_metadata
_tiandao_source_refs = _raw_recall_preflight._tiandao_source_refs
_tiandao_matched_memories = _raw_recall_preflight._tiandao_matched_memories


def _tiandao_memory_mode(*args, **kwargs):
    return _raw_recall_preflight._tiandao_memory_mode_impl(globals(), *args, **kwargs)


def _build_tiandao_context_package(*args, **kwargs):
    return _raw_recall_preflight._build_tiandao_context_package_impl(globals(), *args, **kwargs)


def capability_check_payload(*args, **kwargs):
    return _raw_recall_preflight.capability_check_payload_impl(globals(), *args, **kwargs)


def preflight_payload(*args, **kwargs):
    return _raw_recall_preflight.preflight_payload_impl(globals(), *args, **kwargs)


def _is_raw_evidence_status(status: str) -> bool:
    status = str(status or "")
    return status == "raw" or status.startswith("raw_")


def _annotate_gateway_item(item: Dict[str, Any], query: str = "") -> Dict[str, Any]:
    raw_status = str(item.get("raw_evidence_status") or "")
    raw_excerpt = str(item.get("raw_excerpt") or "")
    annotated = attach_library_card(item, query=query, raw_status=raw_status, raw_excerpt=raw_excerpt)
    card = annotated.get("library_card", {})
    annotated["library_id"] = card.get("library_id", annotated.get("library_id", ""))
    annotated["library_shelf"] = card.get("shelf", annotated.get("library_shelf", ""))
    annotated["matched_by"] = card.get("matched_by", annotated.get("matched_by", []))
    annotated["rank_reason"] = card.get("rank_reason", annotated.get("rank_reason", ""))
    annotated["typed_graph"] = card.get("typed_graph", annotated.get("typed_graph", {}))
    return annotated


def _query_payload_from_items(
    *,
    query: str,
    consumer: str,
    request_id: str,
    effective_source_system: str,
    scope: Dict[str, Any],
    effective_window_id: str,
    effective_session_id: str,
    project_id: str,
    project_root: str,
    workstream_id: str,
    task_id: str,
    binding: Dict[str, Any],
    binding_applied_fields: List[str],
    active_layers_used: List[str],
    items: List[Dict[str, Any]],
    injection_boundary: str,
    extra: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    return build_query_payload_from_items(
        query=query,
        consumer=consumer,
        request_id=request_id,
        effective_source_system=effective_source_system,
        scope=scope,
        effective_window_id=effective_window_id,
        effective_session_id=effective_session_id,
        project_id=project_id,
        project_root=project_root,
        workstream_id=workstream_id,
        task_id=task_id,
        binding=binding,
        binding_applied_fields=binding_applied_fields,
        active_layers_used=active_layers_used,
        items=items,
        injection_boundary=injection_boundary,
        tiandao_context_builder=_build_tiandao_context_package,
        library_manifest_payload=library_manifest(),
        hybrid_recall_manifest_payload=hybrid_recall_manifest(),
        raw_status_fn=_is_raw_evidence_status,
        extra=extra,
    )


def query_raw_source_refs(
    query: str,
    source_system: str = '',
    computer_name: str = '',
    session_id: str = '',
    limit: int = 5,
    excerpt_chars: int = 300,
    consumer: str = '',
    request_id: str = '',
    memory_scope: str = '',
    canonical_window_id: str = '',
    allow_cross_window_recall: bool = False,
    cross_window_reason: str = '',
    project_id: str = '',
    project_root: str = '',
    workstream_id: str = '',
    task_id: str = '',
    fast_window_preflight: bool = False,
    fast_preflight_miss_policy: str = 'continue_recall',
    recall_mode: str = '',
    fts5_recall: bool = False,
    binding_identity: Optional[str] = None,
    expand_catalog_raw: bool = False,
) -> Dict[str, Any]:
    return _raw_recall_query.query_raw_source_refs_impl(
        globals(),
        query=query,
        source_system=source_system,
        computer_name=computer_name,
        session_id=session_id,
        limit=limit,
        excerpt_chars=excerpt_chars,
        consumer=consumer,
        request_id=request_id,
        memory_scope=memory_scope,
        canonical_window_id=canonical_window_id,
        allow_cross_window_recall=allow_cross_window_recall,
        cross_window_reason=cross_window_reason,
        project_id=project_id,
        project_root=project_root,
        workstream_id=workstream_id,
        task_id=task_id,
        fast_window_preflight=fast_window_preflight,
        fast_preflight_miss_policy=fast_preflight_miss_policy,
        recall_mode=recall_mode,
        fts5_recall=fts5_recall,
        binding_identity=binding_identity,
        expand_catalog_raw=expand_catalog_raw,
    )


def health_payload() -> Dict[str, Any]:
    source_path = _service_source_path()
    return {
        "ok": True,
        "service": SERVICE_NAME,
        "version": SERVICE_VERSION,
        "port": PORT,
        "loopback_only": True,
        "read_only": True,
        "read_only_scope": "raw_and_source_memory",
        "source_memory_read_only": True,
        "write_performed": False,
        "production_write_performed": False,
        "derived_delivery_audit": {
            "available": True,
            "append_only": True,
            "default_for_verified_self_reported_mcp_hosts": True,
            "opt_out_field": "delivery_tracking=false",
            "store_scope": "runtime/delivery-events.sqlite3",
            "raw_write_performed": False,
            "memory_write_performed": False,
            "platform_write_performed": False,
        },
        "state_dir_guard": True,
        "raw_query_path": "/api/v1/raw/query",
        "raw_query_methods": ["GET", "POST"],
        "mcp_path": "/mcp",
        "mcp_tools": [
            "time_library_recall",
            "time_library_delivery_ack",
            "time_library_reading_area",
            "zhiyi_recall",
        ],
        "capability_check": True,
        "capability_check_modes": ["mode=capability_check", "capability_check=true"],
        "preflight": True,
        "preflight_modes": ["mode=preflight", "mode=work_preflight", "mode=agent_work_preflight"],
        "consumer_receipt": True,
        "identity_contract": HEALTH_IDENTITY_CONTRACT,
        "source_path": str(source_path),
        "source_sha256": _service_source_sha256(source_path),
        "zhixing_library": library_manifest(),
    }


def active_memory_routing_status() -> Dict[str, Any]:
    return _active_memory_routing_status()


def mcp_tools_payload() -> Dict[str, Any]:
    return _raw_gateway_mcp_tools_payload(
        max_limit=MAX_LIMIT,
        max_excerpt=MAX_EXCERPT,
    )




def _is_loopback_host(host: str) -> bool:
    raw = str(host or "").strip()
    if not raw:
        return False
    if raw.startswith("[") and raw.endswith("]"):
        raw = raw[1:-1]
    if raw.lower() == "localhost":
        return True
    try:
        parsed = ipaddress.ip_address(raw)
    except ValueError:
        return False
    mapped = getattr(parsed, "ipv4_mapped", None)
    if mapped:
        return bool(mapped.is_loopback)
    return bool(parsed.is_loopback)


def _is_loopback_client(client_address: Any) -> bool:
    if isinstance(client_address, (list, tuple)) and client_address:
        return _is_loopback_host(str(client_address[0]))
    return _is_loopback_host(str(client_address or ""))


MCP_SESSION_HEADER = "Mcp-Session-Id"
MCP_SESSION_MAX_RECALL_PROOFS = 20
MCP_SESSION_REJECTION_CONTRACT = "time_library.mcp_session_rejection.v1"


def _new_mcp_transport_session(
    params: Dict[str, Any],
    *,
    resume_token: str = "",
) -> Tuple[str, Dict[str, Any]]:
    return _mcp_runtime().new_mcp_transport_session(
        params,
        resume_token=resume_token,
    )


def _mcp_transport_session(token: str) -> Dict[str, Any]:
    return _mcp_runtime().mcp_transport_session(token)


def _mark_mcp_transport_session_verified(token: str, response: Dict[str, Any]) -> None:
    _mcp_runtime().mark_mcp_transport_session_verified(token, response)


def _mark_mcp_transport_session_capability_check(
    token: str,
    request: Dict[str, Any],
    response: Dict[str, Any],
) -> None:
    _mcp_runtime().mark_mcp_transport_session_capability_check(token, request, response)


def _mcp_real_recall_proofs(
    request: Dict[str, Any],
    response: Dict[str, Any],
) -> List[Dict[str, Any]]:
    return _mcp_runtime().mcp_real_recall_proofs(request, response)


def _mark_mcp_transport_session_recall_proof(
    token: str,
    request: Dict[str, Any],
    response: Dict[str, Any],
) -> None:
    _mcp_runtime().mark_mcp_transport_session_recall_proof(token, request, response)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send_json(
        self,
        data: Dict[str, Any],
        code: int = 200,
        *,
        headers: Optional[Mapping[str, str]] = None,
    ):
        payload = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(payload)))
        for name, value in (headers or {}).items():
            self.send_header(str(name), str(value))
        self.end_headers()
        self.wfile.write(payload)

    def reject_non_loopback(self) -> bool:
        if _is_loopback_client(getattr(self, "client_address", None)):
            return False
        self.send_json({"ok": False, "error": "loopback clients only"}, 403)
        return True

    def do_GET(self):
        if self.reject_non_loopback():
            return
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self.send_json(health_payload())
            return
        if parsed.path == "/api/v1/memory-routing/status":
            self.send_json(active_memory_routing_status())
            return
        if parsed.path == "/mcp":
            self.send_json({
                "ok": True,
                "service": "time-library-mcp",
                "protocol": "jsonrpc",
                "transport": "streamable_http",
                "tools": mcp_tools_payload()["tools"],
            })
            return
        if parsed.path != '/api/v1/raw/query':
            self.send_json({'ok': False, 'error': 'not found'}, 404)
            return
        qs = parse_qs(parsed.query)
        query = (qs.get('query') or qs.get('q') or [''])[0]
        source_system = (qs.get('source_system') or [''])[0]
        memory_scope = (qs.get('memory_scope') or [''])[0]
        canonical_window_id = (qs.get('canonical_window_id') or [''])[0]
        computer_name = (qs.get('computer_name') or [''])[0]
        session_id = (qs.get('session_id') or [''])[0]
        limit = (qs.get('limit') or ['5'])[0]
        excerpt_chars = (qs.get('excerpt_chars') or ['300'])[0]
        consumer = (qs.get('consumer') or [''])[0]
        request_id = (qs.get('request_id') or [''])[0]
        mode = (qs.get('mode') or [''])[0]
        recall_mode = (qs.get('recall_mode') or [''])[0]
        fts5_recall = (qs.get('fts5_recall') or qs.get('enable_fts5_recall') or [''])[0]
        capability_check = (qs.get('capability_check') or [''])[0]
        no_recall = (qs.get('no_recall') or [''])[0]
        response_budget = (qs.get('response_budget') or qs.get('budget') or [''])[0]
        include_raw_excerpt = (qs.get('include_raw_excerpt') or qs.get('include_raw') or [''])[0]
        allow_cross_window_recall = (qs.get('allow_cross_window_recall') or [''])[0]
        cross_window_reason = (qs.get('cross_window_reason') or qs.get('workflow_reason') or [''])[0]
        project_id = (qs.get('project_id') or [''])[0]
        project_root = (qs.get('project_root') or qs.get('workspace_root') or qs.get('cwd') or [''])[0]
        workstream_id = (qs.get('workstream_id') or qs.get('workstream') or [''])[0]
        task_id = (qs.get('task_id') or qs.get('task') or [''])[0]
        fast_preflight_miss_policy = (qs.get('fast_preflight_miss_policy') or [''])[0]
        if _is_capability_check_request({
            "mode": mode,
            "capability_check": capability_check,
            "no_recall": no_recall,
        }):
            self.send_json(capability_check_payload(consumer, request_id, "http_get"))
            return
        preflight_args = {
            "query": query,
            "source_system": source_system,
            "computer_name": computer_name,
            "session_id": session_id,
            "limit": limit,
            "excerpt_chars": excerpt_chars,
            "consumer": consumer,
            "request_id": request_id,
            "memory_scope": memory_scope,
            "canonical_window_id": canonical_window_id,
            "allow_cross_window_recall": allow_cross_window_recall,
            "cross_window_reason": cross_window_reason,
            "project_id": project_id,
            "project_root": project_root,
            "workstream_id": workstream_id,
            "task_id": task_id,
            "fast_preflight_miss_policy": fast_preflight_miss_policy,
        }
        if _is_work_preflight_request({"mode": mode}):
            self.send_json(_work_preflight_from_kwargs(_preflight_kwargs_from_args(preflight_args, consumer_default="", limit_default=3, excerpt_default=180)))
            return
        if _is_preflight_request({"mode": mode}):
            self.send_json(preflight_payload(**_preflight_kwargs_from_args(preflight_args, consumer_default="", limit_default=3, excerpt_default=180)))
            return
        recall_args = {
            "mode": mode,
            "response_budget": response_budget,
            "include_raw_excerpt": include_raw_excerpt,
        }
        result = query_raw_source_refs(
            query,
            source_system,
            computer_name,
            session_id,
            limit,
            excerpt_chars,
            consumer,
            request_id,
            memory_scope,
            canonical_window_id,
            _truthy(allow_cross_window_recall),
            cross_window_reason,
            project_id,
            project_root,
            workstream_id,
            task_id,
            recall_mode=recall_mode,
            fts5_recall=_truthy(fts5_recall),
            expand_catalog_raw=_include_raw_excerpt(recall_args),
        )
        self.send_json(compact_recall_payload(
            result,
            response_budget_mode=_response_budget_mode(recall_args),
            include_raw_excerpt=_include_raw_excerpt(recall_args),
        ))

    def do_POST(self):
        if self.reject_non_loopback():
            return
        parsed = urlparse(self.path)
        if parsed.path == "/mcp":
            length = _safe_int(self.headers.get('Content-Length', '0'), 0, 0, 1024 * 1024)
            try:
                body = self.rfile.read(length).decode('utf-8') if length else '{}'
                data = json.loads(body) if body.strip() else {}
            except Exception:
                self.send_json(mcp_error(None, -32700, "Parse error"), 400)
                return
            if not isinstance(data, dict):
                self.send_json(mcp_error(None, -32600, "Invalid Request"), 400)
                return
            startup_catalog_mode = str(
                (parse_qs(parsed.query).get("startup_catalog") or ["deferred"])[0]
            )
            method = str(data.get("method") or "")
            if method == "initialize":
                params = data.get("params") if isinstance(data.get("params"), dict) else {}
                resume_token = str(self.headers.get(MCP_SESSION_HEADER) or "").strip()
                session_token, connection_context = _new_mcp_transport_session(
                    params,
                    resume_token=resume_token,
                )
                rejection = _mcp_runtime().mcp_resume_rejection(
                    data.get("id"), connection_context
                )
                if rejection is not None:
                    self.send_json(rejection, 409)
                    return
                response = handle_mcp_request(
                    data,
                    startup_catalog_mode=startup_catalog_mode,
                    connection_context=connection_context,
                )
                if response is None:
                    self.send_response(202)
                    self.end_headers()
                    return
                _mark_mcp_transport_session_capability_check(session_token, data, response)
                _mark_mcp_transport_session_recall_proof(session_token, data, response)
                _mark_mcp_transport_session_verified(session_token, response)
                self.send_json(response, headers={MCP_SESSION_HEADER: session_token})
                return

            session_token = str(self.headers.get(MCP_SESSION_HEADER) or "").strip()
            with _mcp_runtime().mcp_transport_session_request_guard(session_token):
                connection_context = _mcp_transport_session(session_token)
                if session_token and not connection_context:
                    rejection = mcp_error(
                        data.get("id"),
                        -32001,
                        "MCP session not found; reinitialize before retrying the request",
                    )
                    rejection["error"]["data"] = {
                        "contract": MCP_SESSION_REJECTION_CONTRACT,
                        "reason": "session_not_found",
                        "request_dispatched": False,
                        "safe_to_retry_after_initialize": True,
                    }
                    self.send_json(rejection, 404)
                    return
                response = handle_mcp_request(
                    data,
                    startup_catalog_mode=startup_catalog_mode,
                    connection_context=connection_context,
                )
                if response is None:
                    self.send_response(202)
                    self.end_headers()
                    return
                if session_token:
                    _mark_mcp_transport_session_capability_check(session_token, data, response)
                    _mark_mcp_transport_session_recall_proof(session_token, data, response)
                    _mark_mcp_transport_session_verified(session_token, response)
                self.send_json(response)
                return
        if parsed.path != '/api/v1/raw/query':
            self.send_json({'ok': False, 'error': 'not found'}, 404)
            return
        length = _safe_int(self.headers.get('Content-Length', '0'), 0, 0, 1024 * 1024)
        try:
            body = self.rfile.read(length).decode('utf-8') if length else '{}'
            data = json.loads(body) if body.strip() else {}
        except Exception:
            self.send_json({'ok': False, 'error': 'invalid json'}, 400)
            return
        if not isinstance(data, dict):
            self.send_json({'ok': False, 'error': 'json body must be object'}, 400)
            return
        query = str(data.get('query') or data.get('q') or '')
        source_system = str(data.get('source_system') or '')
        memory_scope = str(data.get('memory_scope') or '')
        canonical_window_id = str(data.get('canonical_window_id') or '')
        computer_name = str(data.get('computer_name') or '')
        session_id = str(data.get('session_id') or '')
        project_id = str(data.get('project_id') or '')
        project_root = str(data.get('project_root') or data.get('workspace_root') or data.get('cwd') or '')
        workstream_id = str(data.get('workstream_id') or data.get('workstream') or '')
        task_id = str(data.get('task_id') or data.get('task') or '')
        limit = data.get('limit', 5)
        excerpt_chars = data.get('excerpt_chars', 300)
        consumer = str(data.get('consumer') or '')
        request_id = str(data.get('request_id') or '')
        recall_mode = str(data.get('recall_mode') or '')
        fts5_recall = _truthy(data.get("fts5_recall")) or _truthy(data.get("enable_fts5_recall"))
        if _is_capability_check_request(data):
            self.send_json(capability_check_payload(consumer, request_id, "http_post"))
            return
        if _is_work_preflight_request(data):
            self.send_json(_work_preflight_from_kwargs(_preflight_kwargs_from_args(data, consumer_default="", limit_default=3, excerpt_default=180)))
            return
        if _is_preflight_request(data):
            self.send_json(preflight_payload(**_preflight_kwargs_from_args(data, consumer_default="", limit_default=3, excerpt_default=180)))
            return
        result = query_raw_source_refs(
            query,
            source_system,
            computer_name,
            session_id,
            limit,
            excerpt_chars,
            consumer,
            request_id,
            memory_scope,
            canonical_window_id,
            _truthy(data.get("allow_cross_window_recall")),
            str(data.get("cross_window_reason") or data.get("workflow_reason") or ""),
            project_id,
            project_root,
            workstream_id,
            task_id,
            recall_mode=recall_mode,
            fts5_recall=fts5_recall,
            expand_catalog_raw=_include_raw_excerpt(data),
        )
        self.send_json(compact_recall_payload(
            result,
            response_budget_mode=_response_budget_mode(data),
            include_raw_excerpt=_include_raw_excerpt(data),
        ))


def run(port: int = PORT):
    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    print(f'[raw_consumption_gateway] running on http://127.0.0.1:{port}')
    server.serve_forever()


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description="Time Library raw/source gateway")
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args()
    run(args.port)
