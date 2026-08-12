#!/usr/bin/env python3
"""Main read-only recall orchestration used by the raw consumption gateway."""

from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional


def query_raw_source_refs_impl(
    namespace: Dict[str, Any],
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
    ACTIVE_RECALL_CANDIDATE_MAX = namespace["ACTIVE_RECALL_CANDIDATE_MAX"]
    MAX_EXCERPT = namespace["MAX_EXCERPT"]
    MAX_LIMIT = namespace["MAX_LIMIT"]
    PROJECT_STATUS_EXCERPT_CHARS = namespace["PROJECT_STATUS_EXCERPT_CHARS"]
    TRUSTED_MEMORY_AUTHORITY_ANCHORS = namespace["TRUSTED_MEMORY_AUTHORITY_ANCHORS"]
    TRUSTED_MEMORY_AUTHORITY_ANCHOR_CONTRACT = namespace["TRUSTED_MEMORY_AUTHORITY_ANCHOR_CONTRACT"]
    TRUSTED_MEMORY_AUTHORITY_TRIGGER_TERMS = namespace["TRUSTED_MEMORY_AUTHORITY_TRIGGER_TERMS"]
    _annotate_gateway_item = namespace["_annotate_gateway_item"]
    _apply_active_layered_routing = namespace["_apply_active_layered_routing"]
    _binding_metadata = namespace["_binding_metadata"]
    _build_tiandao_context_package = namespace["_build_tiandao_context_package"]
    _clean_text = namespace["_clean_text"]
    _consumer_receipt = namespace["_consumer_receipt"]
    _current_window_binding_anchor = namespace["_current_window_binding_anchor"]
    _dedupe_recall_items = namespace["_dedupe_recall_items"]
    _extract_bounded_raw_excerpt = namespace["_extract_bounded_raw_excerpt"]
    _first_text = namespace["_first_text"]
    _has_active_project_or_workstream_anchor = namespace["_has_active_project_or_workstream_anchor"]
    _has_trusted_memory_authority_anchor = namespace["_has_trusted_memory_authority_anchor"]
    _is_active_empty_window_project_fallback_candidate = namespace["_is_active_empty_window_project_fallback_candidate"]
    _is_raw_evidence_status = namespace["_is_raw_evidence_status"]
    _item_legacy_window_id = namespace["_item_legacy_window_id"]
    _item_project_id = namespace["_item_project_id"]
    _json_loads_maybe = namespace["_json_loads_maybe"]
    _load_default_recall_preference = namespace["_load_default_recall_preference"]
    _load_handle_recall = namespace["_load_handle_recall"]
    _mark_library_index_projection_item = namespace["_mark_library_index_projection_item"]
    _normalize_source_system_window_identity = namespace["_normalize_source_system_window_identity"]
    _preflight_recent_context_allowed = namespace["_preflight_recent_context_allowed"]
    _query_active_empty_window_project_fallback = namespace["_query_active_empty_window_project_fallback"]
    _query_gateway_recent_delta_items = namespace["_query_gateway_recent_delta_items"]
    _query_payload_from_items = namespace["_query_payload_from_items"]
    _query_raw_jsonl_fallback = namespace["_query_raw_jsonl_fallback"]
    _recall_source_system_filters = namespace["_recall_source_system_filters"]
    _resolve_recall_scope = namespace["_resolve_recall_scope"]
    _safe_int = namespace["_safe_int"]
    _scope_missing_status = namespace["_scope_missing_status"]
    _source_alias_extra = namespace["_source_alias_extra"]
    _source_system_filter_matches = namespace["_source_system_filter_matches"]
    _specific_source_system_filters = namespace["_specific_source_system_filters"]
    _trusted_memory_authority_anchor_items = namespace["_trusted_memory_authority_anchor_items"]
    _trusted_memory_authority_anchor_query = namespace["_trusted_memory_authority_anchor_query"]
    _truthy = namespace["_truthy"]
    hybrid_recall_manifest = namespace["hybrid_recall_manifest"]
    library_manifest = namespace["library_manifest"]
    query_canonical_window_index = namespace["query_canonical_window_index"]
    ts = namespace["ts"]

    limit = _safe_int(str(limit), 5, 1, MAX_LIMIT)
    excerpt_chars = _safe_int(str(excerpt_chars), 300, 1, MAX_EXCERPT)
    consumer = _clean_text(consumer)
    source_system = _clean_text(source_system)
    computer_name = _clean_text(computer_name)
    canonical_window_id = _clean_text(canonical_window_id)
    session_id = _clean_text(session_id)
    project_id = _clean_text(project_id)
    project_root = _clean_text(project_root)
    workstream_id = _clean_text(workstream_id)
    task_id = _clean_text(task_id)
    fast_preflight_miss_policy = _clean_text(fast_preflight_miss_policy).lower() or "continue_recall"
    if fast_preflight_miss_policy not in {
        "continue_recall",
        "return_without_cold_recall",
    }:
        raise ValueError("invalid_fast_preflight_miss_policy")
    recall_mode = _clean_text(recall_mode)
    fts5_recall = _truthy(fts5_recall)
    expand_catalog_raw = _truthy(expand_catalog_raw)
    recall_mode_explicit = bool(recall_mode)
    fts5_recall_explicit = bool(fts5_recall)
    default_recall_preference = _load_default_recall_preference()
    default_recall_preference_applied = False
    if (
        query
        and not recall_mode_explicit
        and not fts5_recall_explicit
    ):
        recall_mode = str(default_recall_preference.get("default_recall_mode") or "").strip()
        fts5_recall = _truthy(default_recall_preference.get("fts5_recall"))
        default_recall_preference_applied = True
    configured_default_recall_route = bool(
        default_recall_preference_applied
        and default_recall_preference.get("configured")
    )
    binding_lookup_identity = (
        _clean_text(binding_identity)
        if binding_identity is not None
        else source_system
    )
    binding = _current_window_binding_anchor(binding_lookup_identity)
    binding_meta = _binding_metadata(binding)
    binding_applied_fields: List[str] = []
    binding_source_system_filters: List[str] = []
    if binding:
        if not source_system and _clean_text(binding.get("source_system")):
            source_system = _clean_text(binding.get("source_system"))
            binding_applied_fields.append("source_system")
        if not canonical_window_id and _clean_text(binding.get("canonical_window_id")):
            canonical_window_id = _clean_text(binding.get("canonical_window_id"))
            binding_applied_fields.append("canonical_window_id")
        if not session_id and _clean_text(binding.get("session_id")):
            session_id = _clean_text(binding.get("session_id"))
            binding_applied_fields.append("session_id")
        if not project_id:
            value = _first_text(binding.get("project_id"), binding_meta.get("project_id"))
            if value:
                project_id = value
                binding_applied_fields.append("project_id")
        if not project_root:
            value = _first_text(
                binding.get("project_root"),
                binding.get("workspace_root"),
                binding.get("cwd"),
                binding_meta.get("project_root"),
                binding_meta.get("workspace_root"),
                binding_meta.get("cwd"),
            )
            if value:
                project_root = value
                binding_applied_fields.append("project_root")
        if not workstream_id:
            value = _first_text(binding.get("workstream_id"), binding.get("workstream"), binding_meta.get("workstream_id"), binding_meta.get("workstream"))
            if value:
                workstream_id = value
                binding_applied_fields.append("workstream_id")
        if not task_id:
            value = _first_text(binding.get("task_id"), binding.get("task"), binding_meta.get("task_id"), binding_meta.get("task"))
            if value:
                task_id = value
                binding_applied_fields.append("task_id")
    scope = _resolve_recall_scope(
        source_system=source_system,
        consumer=consumer,
        memory_scope=memory_scope,
        canonical_window_id=canonical_window_id,
        session_id=session_id,
        allow_cross_window_recall=allow_cross_window_recall,
        cross_window_reason=cross_window_reason,
    )
    effective_source_system = scope["effective_source_system"]
    effective_session_id = scope["session_id"]
    effective_window_id = scope["canonical_window_id"]
    active_scope = scope["memory_scope"] == "active"
    binding_session_id = _clean_text(binding.get("session_id")) if binding else ""
    binding_window_id = _clean_text(binding.get("canonical_window_id")) if binding else ""
    binding_anchor_matches = bool(
        binding
        and (
            (binding_session_id and binding_session_id == effective_session_id)
            or (binding_window_id and binding_window_id == effective_window_id)
        )
    )
    if binding_anchor_matches:
        declared_filters = (
            binding.get("source_system_filters")
            or binding_meta.get("source_system_filters")
            or []
        )
        if isinstance(declared_filters, (list, tuple, set)):
            binding_source_system_filters = [
                _clean_text(item) for item in declared_filters if _clean_text(item)
            ]
            if binding_source_system_filters:
                binding_applied_fields.append("source_system_filters")
    source_system_filters = _recall_source_system_filters(
        effective_source_system=effective_source_system,
        session_id=effective_session_id,
        canonical_window_id=effective_window_id,
        declared_source_system_filters=binding_source_system_filters,
    )
    alias_extra = _source_alias_extra(
        source_filters=source_system_filters,
        effective_source_system=effective_source_system,
        session_id=effective_session_id,
        canonical_window_id=effective_window_id,
    )
    active_anchor_filter = bool(
        active_scope
        and alias_extra
        and (effective_session_id or effective_window_id)
    )
    recall_session_filter = (
        effective_session_id
        if active_anchor_filter
        else "" if active_scope else effective_session_id
    )
    recall_window_filter = (
        effective_window_id
        if active_anchor_filter
        else "" if active_scope else effective_window_id
    )
    recall_limit = (
        min(ACTIVE_RECALL_CANDIDATE_MAX, max(limit * 8, limit))
        if active_scope
        else limit
    )
    fast_preflight_telemetry: Dict[str, Any] = {}

    def expand_catalog_item(item: Dict[str, Any]) -> Dict[str, Any]:
        if not expand_catalog_raw or str(item.get("raw_evidence_status") or "") != "raw_index":
            return item
        expanded = dict(item)
        msg_ids = [str(msg_id) for msg_id in (expanded.get("msg_ids") or []) if str(msg_id)]
        source_refs = dict(expanded)
        offsets = expanded.get("byte_offsets") if isinstance(expanded.get("byte_offsets"), dict) else {}
        if "start" in offsets and "end" in offsets and msg_ids:
            source_refs["byte_offsets"] = {msg_ids[0]: offsets}
        excerpt, status, evidence_hash = _extract_bounded_raw_excerpt(
            str(expanded.get("source_path") or ""),
            msg_ids,
            excerpt_chars,
            source_refs,
        )
        expanded["raw_excerpt"] = excerpt
        expanded["raw_evidence_status"] = status if excerpt else "raw_index"
        expanded["raw_expand_status"] = status
        expanded["raw_expand_from_catalog_index"] = bool(excerpt)
        if evidence_hash:
            expanded["evidence_hash"] = evidence_hash
        return expanded

    if scope["scope_missing"]:
        scope_status = _scope_missing_status(scope)
        injection_boundary = 'window_scope_required_for_default_recall'
        tiandao_context_package = _build_tiandao_context_package(
            query=query,
            source_system=effective_source_system,
            consumer=consumer,
            canonical_window_id=effective_window_id,
            session_id=effective_session_id,
            items=[],
            memory_scope=scope["memory_scope"],
            memory_base_scope=scope["memory_base_scope"],
            scope_missing=True,
            active_layers_used=[],
            binding=binding,
            binding_applied_fields=binding_applied_fields,
            cross_window_read=scope["cross_window_read"],
            cross_window_read_allowed=scope["cross_window_read_allowed"],
            injection_boundary=injection_boundary,
            block_reason=scope_status["recall_status"],
        )
        return {
            'ok': True,
            'consumer': consumer or 'unknown',
            'query': query,
            'source_system_filter': effective_source_system or 'unresolved',
            'requested_source_system': scope["requested_source_system"],
            'inferred_source_system': scope["inferred_source_system"],
            'source_filter_authority': scope.get("source_filter_authority", ""),
            'consumer_name_inference_used_for_routing': bool(
                scope.get("consumer_name_inference_used_for_routing", False)
            ),
            'memory_scope': scope["memory_scope"],
            'memory_base_scope': scope["memory_base_scope"],
            'scope_missing': True,
            'recall_status': scope_status["recall_status"],
            'window_binding_hint': scope_status["window_binding_hint"],
            'missing_scope_fields': scope["missing_scope_fields"],
            'cross_window_read': scope["cross_window_read"],
            'cross_window_read_allowed': scope["cross_window_read_allowed"],
            'cross_window_permission_explicit': scope.get("cross_window_permission_explicit", False),
            'cross_window_reason_is_authorization': False,
            'cross_window_reason': scope.get("cross_window_reason", ""),
            'canonical_window_id_filter': effective_window_id,
            'project_id_filter': project_id,
            'project_root_filter': project_root,
            'workstream_id_filter': workstream_id,
            'task_id_filter': task_id,
            'current_window_binding_applied': bool(binding_applied_fields),
            'current_window_binding_key': binding.get("binding_key", "") if binding else "",
            'current_window_binding_fields': binding_applied_fields,
            'active_layers_used': [],
            'agent_boundary': 'active_window_first_explicit_broad_scope',
            'injection_boundary': injection_boundary,
            'tiandao_context_package': tiandao_context_package,
            'tiandao_context_package_valid': tiandao_context_package.get("validation", {}).get("valid", True),
            'zhixing_library': library_manifest(),
            'hybrid_recall': hybrid_recall_manifest(),
            'matched_count': 0,
            'source_refs_count': 0,
            'raw_items_count': 0,
            'items': [],
            'recall_performed': False,
            'raw_excerpt_returned': False,
            'raw_evidence_status': 'not_raw',
            'zhiyi_experience_used_as_raw': False,
            'consumer_receipt': _consumer_receipt(
                consumer,
                request_id,
                0,
                0,
                0,
                [],
            ),
        }

    if (
        fast_window_preflight
        and scope["memory_scope"] in {"active", "window"}
        and (effective_window_id or effective_session_id)
        and not scope["cross_window_read"]
    ):
        indexed_items: List[Dict[str, Any]] = []
        index_statuses: List[str] = []
        for source_filter in source_system_filters:
            source_items, index_status = query_canonical_window_index(
                query=query or '',
                source_system=source_filter or '',
                session_id=effective_session_id or '',
                canonical_window_id=effective_window_id or '',
                limit=limit,
                excerpt_chars=excerpt_chars,
                allow_recent_context=_preflight_recent_context_allowed(query or ''),
            )
            source_items = [expand_catalog_item(item) for item in source_items]
            index_statuses.append(f"{source_filter or 'all'}:{index_status}")
            indexed_items.extend(source_items)
            if len(indexed_items) >= limit:
                break
        indexed_items = _dedupe_recall_items(indexed_items)[:limit]
        fast_index_status = (
            ";".join(index_statuses)
            if alias_extra
            else (index_statuses[0].split(":", 1)[-1] if index_statuses else "identity_required")
        )
        active_empty_window_project_fallback_stats: Dict[str, Any] = {
            "active_empty_window_project_fallback_used": False,
            "active_empty_window_project_fallback_status": "not_attempted",
            "active_empty_window_project_fallback_policy": (
                "same_project_workstream_only_source_backed_no_raw_pool"
            ),
            "active_empty_window_project_fallback_source_system_filters": [],
            "active_empty_window_project_fallback_candidate_count": 0,
            "active_empty_window_project_fallback_routed_count": 0,
            "active_empty_window_project_fallback_layers_used": [],
            "active_empty_window_project_fallback_scope": "same_project_or_workstream",
            "active_empty_window_project_fallback_index_status": "not_attempted",
        }
        if (
            not indexed_items
            and scope["memory_scope"] == "active"
            and _has_active_project_or_workstream_anchor(
                project_id=project_id,
                project_root=project_root,
                workstream_id=workstream_id,
                task_id=task_id,
            )
            and _specific_source_system_filters(source_system_filters)
        ):
            fallback_items, active_empty_window_project_fallback_stats = _query_active_empty_window_project_fallback(
                query=query or "",
                computer_name=computer_name,
                limit=limit,
                excerpt_chars=excerpt_chars,
                effective_session_id=effective_session_id,
                effective_window_id=effective_window_id,
                project_id=project_id,
                project_root=project_root,
                workstream_id=workstream_id,
                task_id=task_id,
                existing_items=[],
            )
            if fallback_items:
                indexed_items = _dedupe_recall_items(fallback_items)[:limit]
        items = [
            _mark_library_index_projection_item(
                _annotate_gateway_item(item, query or ''),
                status=fast_index_status,
            )
            for item in indexed_items
        ]
        active_layers_used = ["current_window"] if items and not active_empty_window_project_fallback_stats.get("active_empty_window_project_fallback_used") else []
        if active_empty_window_project_fallback_stats.get("active_empty_window_project_fallback_used"):
            active_layers_used = list(active_empty_window_project_fallback_stats.get("active_empty_window_project_fallback_layers_used") or [])
        authority_anchor_items: List[Dict[str, Any]] = []
        if _trusted_memory_authority_anchor_query(
            query,
            TRUSTED_MEMORY_AUTHORITY_TRIGGER_TERMS,
        ) and not _has_trusted_memory_authority_anchor(items):
            authority_anchor_items = _trusted_memory_authority_anchor_items(
                query=query,
                source_system=effective_source_system,
                computer_name=computer_name,
                canonical_window_id=effective_window_id,
                session_id=effective_session_id,
                project_id=project_id,
                project_root=project_root,
                workstream_id=workstream_id,
                task_id=task_id,
                excerpt_chars=excerpt_chars,
                limit=limit,
                anchors=TRUSTED_MEMORY_AUTHORITY_ANCHORS,
                trigger_terms=TRUSTED_MEMORY_AUTHORITY_TRIGGER_TERMS,
                created_at=ts(),
                annotate_item=lambda item: _annotate_gateway_item(item, query or ""),
            )
            items = _dedupe_recall_items(authority_anchor_items + items)[:limit]
        fast_recall_path = (
            "canonical_window_index+trusted_memory_authority_anchor"
            if authority_anchor_items
            else "canonical_window_index+canonical_project_index"
            if active_empty_window_project_fallback_stats.get("active_empty_window_project_fallback_used")
            else "canonical_window_index"
        )
        fast_index_observed_status = (
            "authority_anchor_fallback_hit"
            if authority_anchor_items
            else "project_fallback_hit"
            if active_empty_window_project_fallback_stats.get("active_empty_window_project_fallback_used")
            else fast_index_status
        )
        window_scope_fast_miss = bool(
            not items and scope["memory_scope"] == "window"
        )
        policy_fast_miss = bool(
            not items and fast_preflight_miss_policy == "return_without_cold_recall"
        )
        fast_preflight_telemetry = {
            "fast_window_preflight": True,
            "fast_preflight_miss_policy": fast_preflight_miss_policy,
            "fast_preflight_miss_continued_to_cold_recall": bool(
                not items
                and not window_scope_fast_miss
                and fast_preflight_miss_policy == "continue_recall"
            ),
            "fast_preflight_miss_return_reason": (
                "explicit_window_scope"
                if window_scope_fast_miss
                else "declared_return_without_cold_recall"
                if policy_fast_miss
                else ""
            ),
            "fast_recall_path": fast_recall_path,
            "fast_window_index_status": fast_index_observed_status,
        }
        should_return_fast = bool(
            items
            or window_scope_fast_miss
            or policy_fast_miss
        )
        if should_return_fast:
            return _query_payload_from_items(
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
                injection_boundary='explicit_window_scope' if scope["memory_scope"] == "window" else 'active_layered_source_refs_only',
                extra={
                    'recall_performed': bool(items),
                    'raw_excerpt_returned': bool(items),
                    **fast_preflight_telemetry,
                    'fast_preflight_miss_returned_without_cold_recall': bool(
                        window_scope_fast_miss or policy_fast_miss
                    ),
                    'zhiyi_layer_skipped_for_fast_preflight': True,
                    'authority_anchor_fallback_used': bool(authority_anchor_items),
                    'authority_anchor_contract': TRUSTED_MEMORY_AUTHORITY_ANCHOR_CONTRACT if authority_anchor_items else "",
                    'authority_anchor_scope': "project_boundary_files_only" if authority_anchor_items else "",
                    'authority_anchor_triggered_by': "trusted_memory_authority_boundary_query" if authority_anchor_items else "",
                    'catalog_index_used': bool(items),
                    'catalog_index_status': fast_index_observed_status,
                    'catalog_index_items_count': len(items),
                    'catalog_index_eligible': True,
                    'raw_fallback_used': False,
                    'raw_fallback_status': (
                        "skipped_authority_anchor_fallback_hit"
                        if authority_anchor_items
                        else "skipped_active_project_index_hit"
                        if active_empty_window_project_fallback_stats.get("active_empty_window_project_fallback_used")
                        else "skipped_fast_window_index_hit"
                        if items
                        else "skipped_fast_window_index_miss"
                    ),
                    'raw_fallback_scanned_files': 0,
                    'raw_fallback_scanned_bytes': 0,
                    'raw_fallback_scanned_lines': 0,
                    'raw_fallback_truncated': False,
                    'raw_fallback_timed_out': False,
                    'raw_fallback_eligible': False,
                    'raw_recall_source_system_filters': source_system_filters,
                    'raw_recall_primary_items_count': 0,
                    'raw_recall_needs_more_candidates': not bool(items),
                    **active_empty_window_project_fallback_stats,
                    **alias_extra,
                },
            )

    if (
        query
        and not recall_mode_explicit
        and not fts5_recall_explicit
        and not configured_default_recall_route
    ):
        recent_items, gateway_recent_delta_status = _query_gateway_recent_delta_items(
            query=query,
            excerpt_chars=excerpt_chars,
        )
        if recent_items:
            filtered_recent_items: List[Dict[str, Any]] = []
            for item in recent_items:
                item_source_system = _clean_text(item.get("source_system"))
                item_computer_name = _clean_text(item.get("computer_name"))
                item_session_id = _clean_text(item.get("session_id"))
                item_window_id = _clean_text(item.get("canonical_window_id"))
                item_legacy_window_id = _item_legacy_window_id(item)
                item_project_id = _item_project_id(item)
                if source_system_filters != [""] and item_source_system not in source_system_filters:
                    continue
                if computer_name and item_computer_name != computer_name:
                    continue
                if recall_session_filter and item_session_id != recall_session_filter:
                    continue
                session_matched = bool(recall_session_filter and item_session_id == recall_session_filter)
                window_matched = bool(
                    recall_window_filter
                    and (
                        item_window_id == recall_window_filter
                        or item_legacy_window_id == recall_window_filter
                        or item_project_id == recall_window_filter
                    )
                )
                if recall_window_filter and not session_matched and not window_matched:
                    continue
                filtered_recent_items.append(item)
            recent_items = filtered_recent_items

        if recent_items:
            annotated_items = [
                _annotate_gateway_item(item, query or "")
                for item in recent_items
            ]
            annotated_items = _dedupe_recall_items(annotated_items)
            active_layers_used: List[str] = []
            if active_scope:
                annotated_items, active_layers_used = _apply_active_layered_routing(
                    annotated_items,
                    limit=limit,
                    session_id=effective_session_id,
                    canonical_window_id=effective_window_id,
                    project_id=project_id,
                    project_root=project_root,
                    workstream_id=workstream_id,
                    task_id=task_id,
                )
            elif len(annotated_items) > limit:
                annotated_items = annotated_items[:limit]
            if annotated_items:
                return _query_payload_from_items(
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
                    items=annotated_items,
                    injection_boundary=(
                        "active_layered_source_refs_only"
                        if active_scope
                        else "source_refs_only_no_cross_agent_window_write"
                    ),
                    extra={
                        "recall_performed": True,
                        "raw_excerpt_returned": any(
                            _is_raw_evidence_status(item.get("raw_evidence_status", ""))
                            for item in annotated_items
                        ),
                        "memory_cache_status": "recent_delta_fast_path",
                        "refresh_status": "not_waited",
                        "refresh_pending": False,
                        "freshness_boundary": "bounded_recent_delta",
                        "recent_delta_applied": True,
                        "recent_delta_status": gateway_recent_delta_status,
                        "recent_delta_doc_count": int(gateway_recent_delta_status.get("doc_count") or 0),
                        "recent_delta_bounded": True,
                        "recent_delta_full_refresh_waited": False,
                        "freshness_fast_path": "bounded_recent_delta",
                        "default_recall_freshness_covered": True,
                        "default_vector_freshness_covered": False,
                        "vector_search_deferred_for_recent_delta": True,
                        "recall_methods_used": ["recent_delta", "keyword"],
                        "primary_recall_backend": "gateway_recent_delta",
                        "primary_recall_modes": ["recent_delta"],
                        "ranking_owner": "gateway_recent_delta_before_vector",
                        "catalog_index_used": False,
                        "catalog_index_status": "skipped_recent_delta_fast_path",
                        "catalog_index_items_count": 0,
                        "catalog_index_eligible": False,
                        "raw_fallback_used": False,
                        "raw_fallback_status": (
                            "skipped_active_without_window_identity"
                            if active_scope and not (effective_session_id or effective_window_id)
                            else "skipped_recent_delta_fast_path"
                        ),
                        "raw_fallback_scanned_files": 0,
                        "raw_fallback_scanned_bytes": 0,
                        "raw_fallback_scanned_lines": 0,
                        "raw_fallback_truncated": False,
                        "raw_fallback_timed_out": False,
                        "raw_recall_source_system_filters": source_system_filters,
                        "raw_recall_primary_items_count": 0,
                        "raw_recall_needs_more_candidates": False,
                        **fast_preflight_telemetry,
                        **alias_extra,
                    },
                )

    handle_recall = _load_handle_recall()
    matched = []
    recall_telemetry: Dict[str, Any] = {}
    for source_filter in source_system_filters:
        recall_body = {
            'query': query or '',
            'scope_filter': '',
            'type_filter': [],
            'top_k': recall_limit,
            'source_system_filter': source_filter,
            'computer_name_filter': computer_name,
            'session_id_filter': recall_session_filter,
            'canonical_window_id_filter': recall_window_filter,
        }
        if recall_mode:
            recall_body['recall_mode'] = recall_mode
        if fts5_recall:
            recall_body['fts5_recall'] = True
        result = handle_recall(recall_body)
        if not recall_telemetry:
            recall_telemetry = {
                "memory_cache_status": result.get("memory_cache_status", ""),
                "refresh_status": result.get("refresh_status", ""),
                "refresh_pending": bool(result.get("refresh_pending", False)),
                "freshness_boundary": result.get("freshness_boundary", ""),
                "last_refresh_started_at": result.get("last_refresh_started_at"),
                "last_refresh_completed_at": result.get("last_refresh_completed_at"),
                "last_refresh_duration_seconds": result.get("last_refresh_duration_seconds"),
                "refresh_trigger_count": result.get("refresh_trigger_count", 0),
                "recent_delta_applied": bool(result.get("recent_delta_applied", False)),
                "recent_delta_status": result.get("recent_delta_status", {}),
                "recent_delta_doc_count": int(result.get("recent_delta_doc_count") or 0),
                "recent_delta_bounded": bool(result.get("recent_delta_bounded", False)),
                "recent_delta_full_refresh_waited": bool(result.get("recent_delta_full_refresh_waited", False)),
                "freshness_fast_path": result.get("freshness_fast_path", ""),
                "default_recall_freshness_covered": bool(result.get("default_recall_freshness_covered", False)),
                "default_vector_freshness_covered": bool(result.get("default_vector_freshness_covered", False)),
                "recall_methods_used": result.get("recall_methods_used", []),
                "primary_recall_backend": result.get("primary_recall_backend", ""),
                "primary_recall_modes": result.get("primary_recall_modes", []),
                "ranking_owner": result.get("ranking_owner", ""),
                "recall_transport": result.get("recall_transport", ""),
                "vector_degraded": bool(result.get("vector_degraded", False)),
                "vector_fallback_applied": bool(result.get("vector_fallback_applied", False)),
                "vector_fallback_backend": result.get("vector_fallback_backend", ""),
            }
        if fts5_recall and recall_telemetry:
            recall_telemetry.update({
                "fts5_recall_requested": True,
                "fts5_applied": bool(result.get("fts5_applied", False)),
                "fts5_status": result.get("fts5_status", {}),
                "fts5_rank_reason": result.get("fts5_rank_reason", ""),
                "primary_recall_backend": result.get("primary_recall_backend", recall_telemetry.get("primary_recall_backend", "")),
                "primary_recall_modes": result.get("primary_recall_modes", recall_telemetry.get("primary_recall_modes", [])),
                "ranking_owner": result.get("ranking_owner", recall_telemetry.get("ranking_owner", "")),
                "recall_methods_used": result.get("recall_methods_used", recall_telemetry.get("recall_methods_used", [])),
                "freshness_boundary": result.get("freshness_boundary", recall_telemetry.get("freshness_boundary", "")),
                "default_vector_freshness_covered": bool(result.get("default_vector_freshness_covered", False)),
            })
        if default_recall_preference_applied and recall_telemetry:
            recall_telemetry.update({
                "default_recall_preference_applied": True,
                "default_recall_preference": default_recall_preference,
            })
        matched.extend(result.get('matched_memories', []) or [])

    items = []
    for m in matched:
        sr = _json_loads_maybe(m.get('source_refs', {}))
        sr_source_system = sr.get('source_system', '')
        sr_computer_name = sr.get('computer_name', '') or sr.get('computer_id', '')
        sr_session_id = sr.get('session_id', '')
        sr_window_id = sr.get('canonical_window_id', '') or m.get('canonical_window_id', '')
        sr_legacy_window_id = sr.get('source_refs_canonical_window_id', '') or m.get('source_refs_canonical_window_id', '')
        sr_project_id = _first_text(sr.get('project_id'), m.get('project_id'))
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
        sr_project_root = _first_text(
            sr.get('project_root'),
            sr.get('workspace_root'),
            sr.get('cwd'),
            m.get('project_root'),
            m.get('workspace_root'),
            m.get('cwd'),
        )
        sr_workstream_id = _first_text(
            sr.get('workstream_id'),
            sr.get('workstream'),
            m.get('workstream_id'),
            m.get('workstream'),
        )
        sr_task_id = _first_text(
            sr.get('task_id'),
            sr.get('task'),
            m.get('task_id'),
            m.get('task'),
        )

        xingce_meta = m.get('_xingce', {}) if isinstance(m.get('_xingce'), dict) else {}
        if not _source_system_filter_matches(sr_source_system, source_system_filters) and not xingce_meta:
            continue
        if computer_name and sr_computer_name != computer_name:
            continue
        if recall_session_filter and sr_session_id != recall_session_filter:
            continue
        session_matched = bool(recall_session_filter and sr_session_id == recall_session_filter)
        window_matched = bool(
            recall_window_filter
            and (
                sr_window_id == recall_window_filter
                or sr_legacy_window_id == recall_window_filter
                or sr_project_id == recall_window_filter
            )
        )
        if recall_window_filter and not session_matched and not window_matched:
            continue

        source_path = sr.get('source_path', '')
        msg_ids = sr.get('msg_ids', []) or []
        raw_excerpt, raw_status, evidence_hash = _extract_bounded_raw_excerpt(source_path, msg_ids, excerpt_chars, sr)
        project_status_meta = m.get('_project_status', {}) if isinstance(m.get('_project_status'), dict) else {}
        if project_status_meta and not raw_excerpt:
            status_excerpt_chars = max(excerpt_chars, PROJECT_STATUS_EXCERPT_CHARS)
            raw_excerpt = str(m.get('injectable_context') or m.get('summary') or '')[:status_excerpt_chars]
            raw_status = 'artifact'
            evidence_hash = hashlib.sha256(raw_excerpt.encode('utf-8')).hexdigest() if raw_excerpt else None
        item = {
            'type': m.get('type', '') or m.get('_type', ''),
            'memory_type': m.get('type', '') or m.get('_type', ''),
            'exp_id': m.get('exp_id', ''),
            'summary': str(m.get('summary') or '')[:800],
            'should_inject': bool(m.get('should_inject', False)),
            'confidence': m.get('confidence'),
            'source_system': sr_source_system,
            'computer_name': sr_computer_name,
            'canonical_window_id': sr_window_id,
            'session_id': sr_session_id,
            'project_id': sr_project_id,
            'project_root': sr_project_root,
            'workstream_id': sr_workstream_id,
            'task_id': sr_task_id,
            'native_session_key': sr_session_id or m.get('exp_id', ''),
            'source_path': source_path,
            'msg_ids': msg_ids,
            'raw_excerpt': raw_excerpt,
            'evidence_hash': evidence_hash,
            'created_at': ts(),
            'raw_evidence_status': raw_status if source_path else 'not_raw',
            'zhiyi_experience_used_as_raw': False,
            'matched_by': m.get('matched_by', ''),
            'rank_reason': m.get('rank_reason', ''),
        }
        if isinstance(m.get("_fts5"), dict):
            item["_fts5"] = m["_fts5"]
        if sr_legacy_window_id:
            item['source_refs_canonical_window_id'] = sr_legacy_window_id
        if xingce_meta:
            item['xingce_candidate'] = {
                'candidate_id': xingce_meta.get('candidate_id', ''),
                'candidate_type': xingce_meta.get('candidate_type', ''),
                'action_status': xingce_meta.get('action_status', ''),
                'lifecycle_status': xingce_meta.get('lifecycle_status', ''),
                'matched_by': m.get('matched_by', ''),
                'rank_reason': m.get('rank_reason', ''),
                'production_experience_write_performed': bool(xingce_meta.get('production_experience_write_performed', False)),
                'raw_write_performed': bool(xingce_meta.get('raw_write_performed', False)),
                'zhiyi_write_performed': bool(xingce_meta.get('zhiyi_write_performed', False)),
                'xingce_write_performed': bool(xingce_meta.get('xingce_write_performed', False)),
                'hermes_write_performed': bool(xingce_meta.get('hermes_write_performed', False)),
                'openclaw_write_performed': bool(xingce_meta.get('openclaw_write_performed', False)),
                'work_experience': m.get('work_experience', {}),
            }
        if project_status_meta:
            item['project_status'] = {
                'status_id': project_status_meta.get('status_id', ''),
                'artifact_type': project_status_meta.get('artifact_type', ''),
                'status': project_status_meta.get('status', ''),
                'project': project_status_meta.get('project', ''),
                'skill_artifact_status': project_status_meta.get('skill_artifact_status', ''),
                'probe_id': project_status_meta.get('probe_id', ''),
                'probe_receipt_path': project_status_meta.get('probe_receipt_path', ''),
                'skill_relative_path': project_status_meta.get('skill_relative_path', ''),
                'skill_path': project_status_meta.get('skill_path', ''),
                'skill_sha256': project_status_meta.get('skill_sha256', ''),
                'status_receipt_write_performed': bool(project_status_meta.get('status_receipt_write_performed', False)),
                'production_experience_write_performed': bool(project_status_meta.get('production_experience_write_performed', False)),
                'raw_write_performed': bool(project_status_meta.get('raw_write_performed', False)),
                'zhiyi_write_performed': bool(project_status_meta.get('zhiyi_write_performed', False)),
                'xingce_write_performed': bool(project_status_meta.get('xingce_write_performed', False)),
                'hermes_write_performed': bool(project_status_meta.get('hermes_write_performed', False)),
                'hermes_skill_write_performed_by_time_library': bool(project_status_meta.get('hermes_skill_write_performed_by_time_library', False)),
                'openclaw_write_performed': bool(project_status_meta.get('openclaw_write_performed', False)),
            }
        items.append(_annotate_gateway_item(item, query or ''))
        if len(items) >= limit:
            if active_scope:
                continue
            break
    items = _dedupe_recall_items(items)

    candidate_target = recall_limit if active_scope else limit
    active_preview_count = 0
    if active_scope:
        active_preview, _ = _apply_active_layered_routing(
            items,
            limit=limit,
            session_id=effective_session_id,
            canonical_window_id=effective_window_id,
            project_id=project_id,
            project_root=project_root,
            workstream_id=workstream_id,
            task_id=task_id,
        )
        active_preview_count = len(active_preview)
    needs_more_candidates = (
        active_preview_count < limit
        if active_scope
        else len(items) < limit
    )
    catalog_index_used = False
    catalog_index_status = "not_attempted"
    catalog_index_items_count = 0
    primary_recall_items_count = len(items)
    catalog_index_eligible = False
    raw_fallback_eligible = False
    raw_fallback_stats: Dict[str, Any] = {
        "raw_fallback_used": False,
        "raw_fallback_status": "not_needed",
        "raw_fallback_scanned_files": 0,
        "raw_fallback_scanned_bytes": 0,
        "raw_fallback_scanned_lines": 0,
        "raw_fallback_truncated": False,
        "raw_fallback_timed_out": False,
    }
    active_empty_window_project_fallback_stats: Dict[str, Any] = {
        "active_empty_window_project_fallback_used": False,
        "active_empty_window_project_fallback_status": "not_attempted",
        "active_empty_window_project_fallback_policy": (
            "same_project_workstream_only_source_backed_no_raw_pool"
        ),
        "active_empty_window_project_fallback_source_system_filters": [],
        "active_empty_window_project_fallback_candidate_count": 0,
        "active_empty_window_project_fallback_routed_count": 0,
        "active_empty_window_project_fallback_layers_used": [],
        "active_empty_window_project_fallback_scope": "same_project_or_workstream",
    }
    active_has_window_anchor = bool(active_scope and (effective_session_id or effective_window_id))
    raw_fallback_session_filter = effective_session_id if active_has_window_anchor else recall_session_filter
    raw_fallback_window_filter = effective_window_id if active_has_window_anchor else recall_window_filter
    raw_fallback_eligible = not (active_scope and not active_has_window_anchor)

    if needs_more_candidates or not any(_is_raw_evidence_status(item.get('raw_evidence_status', '')) for item in items):
        existing_raw_keys = {
            (str(item.get("source_path", "")), tuple(item.get("msg_ids") or []), str(item.get("raw_excerpt", "")))
            for item in items
        }
        remaining = max(limit, candidate_target - len(items))
        catalog_index_eligible = (
            scope["memory_scope"] in {"active", "window"}
            and (effective_window_id or effective_session_id)
            and not scope["cross_window_read"]
        )
        if catalog_index_eligible:
            catalog_statuses: List[str] = []
            catalog_items_added: List[Dict[str, Any]] = []
            for source_filter in source_system_filters:
                indexed_items, index_status = query_canonical_window_index(
                    query=query or '',
                    source_system=source_filter or '',
                    session_id=effective_session_id or '',
                    canonical_window_id=effective_window_id or '',
                    limit=remaining,
                    excerpt_chars=excerpt_chars,
                    allow_recent_context=False,
                )
                indexed_items = [expand_catalog_item(item) for item in indexed_items]
                catalog_statuses.append(f"{source_filter or 'all'}:{index_status}")
                for indexed_item in indexed_items:
                    key = (
                        str(indexed_item.get("source_path", "")),
                        tuple(indexed_item.get("msg_ids") or []),
                        str(indexed_item.get("raw_excerpt", "")),
                    )
                    if key in existing_raw_keys:
                        continue
                    annotated = _mark_library_index_projection_item(
                        _annotate_gateway_item(indexed_item, query or ''),
                        status=index_status,
                    )
                    catalog_items_added.append(annotated)
                    existing_raw_keys.add(key)
                    if len(catalog_items_added) >= remaining:
                        break
                if len(catalog_items_added) >= remaining:
                    break
            if catalog_statuses:
                catalog_index_status = (
                    ";".join(catalog_statuses)
                    if alias_extra or len(catalog_statuses) > 1
                    else catalog_statuses[0].split(":", 1)[-1]
                )
            if catalog_items_added:
                items.extend(catalog_items_added)
                items = _dedupe_recall_items(items)
                catalog_index_items_count = len(catalog_items_added)
                catalog_index_used = True
                needs_more_candidates = False
                raw_fallback_stats["raw_fallback_status"] = "skipped_catalog_index_hit"

    if (
        (needs_more_candidates or not any(_is_raw_evidence_status(item.get('raw_evidence_status', '')) for item in items))
        and not catalog_index_used
    ):
        if not raw_fallback_eligible:
            raw_fallback_stats["raw_fallback_status"] = "skipped_active_without_window_identity"
        else:
            existing_raw_keys = {
                (str(item.get("source_path", "")), tuple(item.get("msg_ids") or []), str(item.get("raw_excerpt", "")))
                for item in items
            }
            remaining = max(limit, candidate_target - len(items))
            fallback_statuses: List[str] = []
            for source_filter in source_system_filters:
                fallback_items, fallback_stats = _query_raw_jsonl_fallback(
                    query=query or '',
                    source_system=source_filter or '',
                    computer_name=computer_name or '',
                    session_id=raw_fallback_session_filter or '',
                    canonical_window_id=raw_fallback_window_filter or '',
                    limit=remaining,
                    excerpt_chars=excerpt_chars,
                )
                raw_fallback_stats["raw_fallback_used"] = (
                    bool(raw_fallback_stats["raw_fallback_used"])
                    or bool(fallback_stats.get("raw_fallback_used"))
                )
                raw_fallback_stats["raw_fallback_scanned_files"] += int(fallback_stats.get("raw_fallback_scanned_files") or 0)
                raw_fallback_stats["raw_fallback_scanned_bytes"] += int(fallback_stats.get("raw_fallback_scanned_bytes") or 0)
                raw_fallback_stats["raw_fallback_scanned_lines"] += int(fallback_stats.get("raw_fallback_scanned_lines") or 0)
                raw_fallback_stats["raw_fallback_truncated"] = (
                    bool(raw_fallback_stats["raw_fallback_truncated"])
                    or bool(fallback_stats.get("raw_fallback_truncated"))
                )
                raw_fallback_stats["raw_fallback_timed_out"] = (
                    bool(raw_fallback_stats["raw_fallback_timed_out"])
                    or bool(fallback_stats.get("raw_fallback_timed_out"))
                )
                fallback_statuses.append(f"{source_filter or 'all'}:{fallback_stats.get('raw_fallback_status') or 'unknown'}")
                for fallback_item in fallback_items:
                    key = (
                        str(fallback_item.get("source_path", "")),
                        tuple(fallback_item.get("msg_ids") or []),
                        str(fallback_item.get("raw_excerpt", "")),
                    )
                    if key in existing_raw_keys:
                        continue
                    items.append(_annotate_gateway_item(fallback_item, query or ''))
                    existing_raw_keys.add(key)
                    if len(items) >= candidate_target:
                        break
                if len(items) >= candidate_target:
                    break
            if fallback_statuses:
                raw_fallback_stats["raw_fallback_status"] = (
                    ";".join(fallback_statuses)
                    if alias_extra or len(fallback_statuses) > 1
                    else fallback_statuses[0].split(":", 1)[-1]
                )

    if active_scope:
        active_preview, preview_layers = _apply_active_layered_routing(
            items,
            limit=limit,
            session_id=effective_session_id,
            canonical_window_id=effective_window_id,
            project_id=project_id,
            project_root=project_root,
            workstream_id=workstream_id,
            task_id=task_id,
        )
        if _is_active_empty_window_project_fallback_candidate(
            active_scope=active_scope,
            scope=scope,
            effective_session_id=effective_session_id,
            effective_window_id=effective_window_id,
            project_id=project_id,
            project_root=project_root,
            workstream_id=workstream_id,
            task_id=task_id,
            source_system_filters=source_system_filters,
            active_layers_used=preview_layers,
            needs_more_candidates=not bool(active_preview),
        ):
            fallback_items, active_empty_window_project_fallback_stats = _query_active_empty_window_project_fallback(
                query=query or "",
                computer_name=computer_name,
                limit=limit,
                excerpt_chars=excerpt_chars,
                effective_session_id=effective_session_id,
                effective_window_id=effective_window_id,
                project_id=project_id,
                project_root=project_root,
                workstream_id=workstream_id,
                task_id=task_id,
                existing_items=items,
            )
            if fallback_items:
                items = _dedupe_recall_items(items + fallback_items)

    active_layers_used: List[str] = []
    if active_scope:
        items, active_layers_used = _apply_active_layered_routing(
            items,
            limit=limit,
            session_id=effective_session_id,
            canonical_window_id=effective_window_id,
            project_id=project_id,
            project_root=project_root,
            workstream_id=workstream_id,
            task_id=task_id,
        )
    elif len(items) > limit:
        items = items[:limit]

    injection_boundary = (
        'explicit_window_scope'
        if scope["memory_scope"] == 'window'
        else 'active_layered_source_refs_only'
        if scope["memory_scope"] == 'active'
        else 'source_refs_only_no_cross_agent_window_write'
    )
    payload = _query_payload_from_items(
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
        extra={
            **raw_fallback_stats,
            **active_empty_window_project_fallback_stats,
            **alias_extra,
            'catalog_index_used': catalog_index_used,
            'catalog_index_status': catalog_index_status,
            'catalog_index_items_count': catalog_index_items_count,
            'catalog_index_eligible': catalog_index_eligible,
            'raw_fallback_stats': raw_fallback_stats,
            'raw_fallback_eligible': raw_fallback_eligible,
            'raw_recall_source_system_filters': source_system_filters,
            'raw_recall_primary_items_count': primary_recall_items_count,
            'raw_recall_needs_more_candidates': needs_more_candidates,
            **recall_telemetry,
            **fast_preflight_telemetry,
        },
    )
    payload.update(alias_extra)
    return payload
