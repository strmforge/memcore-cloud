#!/usr/bin/env python3
"""stdio bridge for Codex -> Time Library MCP.

Codex can register HTTP MCP servers directly, but direct HTTP does not carry
the current Codex thread/session identity. This bridge keeps recall anchored by
injecting `consumer=codex`, a scoped memory mode, and the current session or
window id when Codex exposes one through the environment. Ordinary recall stays
active-layered; preflight defaults to window scope when a current binding is
available.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

TOOLS_DIR = Path(__file__).resolve().parent
INSTALL_ROOT = TOOLS_DIR.parent
for _path in (str(INSTALL_ROOT), str(INSTALL_ROOT / "src")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

try:
    from src.port_discovery import resolve_client_url
except Exception:
    from port_discovery import resolve_client_url

if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from claude_desktop_mcp_bridge import (
    DEFAULT_RECALL_EXCERPT_CHARS,
    DEFAULT_RECALL_LIMIT,
    DEFAULT_TIMEOUT_SECONDS,
    _compact_consumer_receipt,
    _compact_item,
    _compact_preflight_payload,
    _compact_work_preflight_payload,
    _compact_tiandao_context_package,
    _McpHttpSession,
    _is_jsonrpc_response,
    _is_session_rejection,
    _is_zhiyi_recall_call,
    _mcp_error,
    _mcp_reverification_required,
    _normalize_jsonrpc_response,
    _read_message,
    _reinitialize_session,
    _send_once,
    _truncate,
    _write_message,
)


MAX_COMPACT_ITEMS = 5
DEFAULT_BINDING_KEYS = ("codex", "codex_cli")


def _log(message: str) -> None:
    print(f"[time_library-codex-mcp] {message}", file=sys.stderr, flush=True)


def _window_binding_registry_path(explicit: str = "") -> Path:
    value = str(explicit or os.environ.get("MEMCORE_WINDOW_BINDING_REGISTRY") or "").strip()
    if value:
        return Path(value).expanduser()
    root = str(os.environ.get("MEMCORE_ROOT") or "").strip()
    if root:
        return Path(root).expanduser() / "config" / "window_binding_registry.json"
    try:
        return Path(__file__).resolve().parents[1] / "config" / "window_binding_registry.json"
    except Exception:
        return Path("config") / "window_binding_registry.json"


def _current_window_binding_from_registry(
    *,
    registry_path: str = "",
    binding_key: str = "",
) -> dict[str, str]:
    path = _window_binding_registry_path(registry_path)
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {"canonical_window_id": "", "session_id": ""}
    current_windows = data.get("current_windows") if isinstance(data, dict) else {}
    if not isinstance(current_windows, dict):
        return {"canonical_window_id": "", "session_id": ""}
    keys: list[str] = []
    for key in (
        binding_key,
        os.environ.get("MEMCORE_CODEX_BINDING_KEY"),
        *DEFAULT_BINDING_KEYS,
    ):
        text = str(key or "").strip().lower().replace("-", "_")
        if text and text not in keys:
            keys.append(text)
    for key in keys:
        entry = current_windows.get(key)
        if not isinstance(entry, dict):
            continue
        session_id = str(entry.get("session_id") or "").strip()
        canonical_window_id = str(entry.get("canonical_window_id") or "").strip()
        if canonical_window_id or session_id:
            return {
                "canonical_window_id": canonical_window_id,
                "session_id": session_id,
            }
    return {"canonical_window_id": "", "session_id": ""}


def _current_window_binding(
    *,
    canonical_window_id: str = "",
    session_id: str = "",
    registry_path: str = "",
    binding_key: str = "",
) -> dict[str, str]:
    explicit_canonical = str(
        canonical_window_id
        or os.environ.get("MEMCORE_CODEX_CANONICAL_WINDOW_ID")
        or ""
    ).strip()
    explicit_session = str(
        session_id
        or os.environ.get("MEMCORE_CODEX_SESSION_ID")
        or os.environ.get("MEMCORE_CODEX_THREAD_ID")
        or os.environ.get("CODEX_THREAD_ID")
        or ""
    ).strip()
    if explicit_canonical or explicit_session:
        return {
            "canonical_window_id": explicit_canonical,
            "session_id": explicit_session,
        }
    registry_binding = _current_window_binding_from_registry(
        registry_path=registry_path,
        binding_key=binding_key,
    )
    if registry_binding["canonical_window_id"] or registry_binding["session_id"]:
        return registry_binding
    return {"canonical_window_id": "", "session_id": ""}


def _budget_zhiyi_request(
    data: dict[str, Any],
    *,
    canonical_window_id: str = "",
    session_id: str = "",
    registry_path: str = "",
    binding_key: str = "",
) -> dict[str, Any]:
    if not _is_zhiyi_recall_call(data):
        return data
    params = dict(data.get("params") if isinstance(data.get("params"), dict) else {})
    args = dict(params.get("arguments") if isinstance(params.get("arguments"), dict) else {})
    mode = str(args.get("mode") or "").strip().lower()
    if mode == "capability_check" or args.get("capability_check") or args.get("no_recall"):
        return data
    args.setdefault("consumer", "codex")
    binding = _current_window_binding(
        canonical_window_id=canonical_window_id,
        session_id=session_id,
        registry_path=registry_path,
        binding_key=binding_key,
    )
    has_window_binding = bool(binding["canonical_window_id"] or binding["session_id"])
    if not str(args.get("memory_scope") or "").strip():
        args["memory_scope"] = "window" if mode in {"preflight", "work_preflight", "agent_work_preflight"} and has_window_binding else "active"
    if binding["canonical_window_id"]:
        args.setdefault("canonical_window_id", binding["canonical_window_id"])
    if binding["session_id"]:
        args.setdefault("session_id", binding["session_id"])
    args.setdefault("limit", DEFAULT_RECALL_LIMIT)
    args.setdefault("excerpt_chars", DEFAULT_RECALL_EXCERPT_CHARS)
    args.setdefault("response_budget", "compact")
    params["arguments"] = args
    budgeted = dict(data)
    budgeted["params"] = params
    return budgeted


def _compact_delivery_runtime(value: Any) -> dict[str, Any]:
    runtime = value if isinstance(value, dict) else {}
    challenge = runtime.get("challenge") if isinstance(runtime.get("challenge"), dict) else {}
    write_boundary = runtime.get("write_boundary") if isinstance(runtime.get("write_boundary"), dict) else {}
    compact = {
        "ok": runtime.get("ok"),
        "contract": runtime.get("contract"),
        "proof_layer": runtime.get("proof_layer"),
        "platform": runtime.get("platform"),
        "retrieval_id": runtime.get("retrieval_id"),
        "decision": runtime.get("decision"),
        "requested_delivery_form": runtime.get("requested_delivery_form"),
        "delivery_form": runtime.get("delivery_form"),
        "silent_reasons": runtime.get("silent_reasons"),
        "latest_proven_stage": runtime.get("latest_proven_stage"),
        "unknown_for_stage": runtime.get("unknown_for_stage"),
        "source_refs": runtime.get("source_refs"),
        "delivery_performed": runtime.get("delivery_performed"),
        "used_observed": runtime.get("used_observed"),
        "helped_observed": runtime.get("helped_observed"),
        "helped_state": runtime.get("helped_state"),
        "request_body_byte_capture": runtime.get("request_body_byte_capture"),
        "response_body_byte_capture": runtime.get("response_body_byte_capture"),
        "challenge": {
            key: challenge.get(key)
            for key in (
                "ack_required",
                "ack_tool",
                "challenge_id",
                "challenge",
                "retrieval_id",
                "platform",
                "selected_source_refs",
                "expires_at",
                "instruction",
            )
            if key in challenge
        },
        "write_boundary": {
            key: write_boundary.get(key)
            for key in (
                "write_performed",
                "derived_delivery_audit_write_performed",
                "source_memory_read_only",
                "raw_write_performed",
                "memory_write_performed",
                "platform_write_performed",
                "recall_ranking_changed",
                "append_only",
            )
            if key in write_boundary
        },
    }
    return {key: item for key, item in compact.items() if item not in (None, "", [], {})}


def _compact_recall_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("mode") == "capability_check":
        keys = (
            "ok",
            "mode",
            "service",
            "server",
            "version",
            "source",
            "read_only",
            "read_only_scope",
            "source_memory_read_only",
            "write_performed",
            "derived_delivery_audit_write_performed",
            "delivery_audit_available",
            "platform_write_performed",
            "recall_performed",
            "raw_excerpt_returned",
            "raw_query_path",
            "mcp_path",
            "mcp_tools",
            "matched_count",
            "source_refs_count",
            "raw_items_count",
        )
        compact = {key: payload.get(key) for key in keys if key in payload}
        compact["consumer_receipt"] = _compact_consumer_receipt(payload.get("consumer_receipt"))
        return compact
    if payload.get("mode") == "preflight":
        return _compact_preflight_payload(payload, response_budget_mode="codex_preflight_compact")
    if payload.get("mode") == "work_preflight":
        return _compact_work_preflight_payload(payload, response_budget_mode="codex_work_preflight_compact")

    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    compact = {
        "ok": payload.get("ok"),
        "consumer": payload.get("consumer"),
        "query": payload.get("query"),
        "source_system_filter": payload.get("source_system_filter"),
        "memory_scope": payload.get("memory_scope"),
        "memory_base_scope": payload.get("memory_base_scope"),
        "scope_missing": payload.get("scope_missing"),
        "recall_status": payload.get("recall_status"),
        "window_binding_hint": payload.get("window_binding_hint"),
        "missing_scope_fields": payload.get("missing_scope_fields"),
        "cross_window_read": payload.get("cross_window_read"),
        "cross_window_read_allowed": payload.get("cross_window_read_allowed"),
        "canonical_window_id_filter": payload.get("canonical_window_id_filter"),
        "project_id_filter": payload.get("project_id_filter"),
        "project_root_filter": payload.get("project_root_filter"),
        "workstream_id_filter": payload.get("workstream_id_filter"),
        "task_id_filter": payload.get("task_id_filter"),
        "current_window_binding_applied": payload.get("current_window_binding_applied"),
        "current_window_binding_key": payload.get("current_window_binding_key"),
        "current_window_binding_fields": payload.get("current_window_binding_fields"),
        "active_layers_used": payload.get("active_layers_used"),
        "agent_boundary": payload.get("agent_boundary"),
        "injection_boundary": payload.get("injection_boundary"),
        "tiandao_context_package_valid": payload.get("tiandao_context_package_valid"),
        "tiandao_context_package": _compact_tiandao_context_package(payload.get("tiandao_context_package")),
        "recall_performed": payload.get("recall_performed"),
        "read_only": payload.get("read_only"),
        "source_memory_read_only": payload.get("source_memory_read_only"),
        "write_performed": payload.get("write_performed"),
        "derived_delivery_audit_write_performed": payload.get("derived_delivery_audit_write_performed"),
        "raw_write_performed": payload.get("raw_write_performed"),
        "memory_write_performed": payload.get("memory_write_performed"),
        "platform_write_performed": payload.get("platform_write_performed"),
        "raw_excerpt_returned": payload.get("raw_excerpt_returned"),
        "matched_count": payload.get("matched_count"),
        "source_refs_count": payload.get("source_refs_count"),
        "raw_items_count": payload.get("raw_items_count"),
        "catalog_index_used": payload.get("catalog_index_used"),
        "catalog_index_status": payload.get("catalog_index_status"),
        "catalog_index_items_count": payload.get("catalog_index_items_count"),
        "raw_fallback_used": payload.get("raw_fallback_used"),
        "raw_fallback_status": payload.get("raw_fallback_status"),
        "raw_fallback_scanned_files": payload.get("raw_fallback_scanned_files"),
        "raw_fallback_scanned_bytes": payload.get("raw_fallback_scanned_bytes"),
        "raw_fallback_scanned_lines": payload.get("raw_fallback_scanned_lines"),
        "raw_fallback_truncated": payload.get("raw_fallback_truncated"),
        "raw_fallback_timed_out": payload.get("raw_fallback_timed_out"),
        "raw_evidence_status": payload.get("raw_evidence_status"),
        "zhiyi_experience_used_as_raw": payload.get("zhiyi_experience_used_as_raw"),
        "items": [_compact_item(item) for item in items[:MAX_COMPACT_ITEMS]],
        "response_budget": {
            "mode": "codex_compact",
            "items_returned": min(len(items), MAX_COMPACT_ITEMS),
            "items_available": len(items),
            "omitted_large_fields": ["zhixing_library", "hybrid_recall", "library_card", "typed_graph", "items.raw_excerpt", "tiandao_context_package.matched_memories", "tiandao_context_package.raw_projection"],
        },
        "consumer_receipt": _compact_consumer_receipt(payload.get("consumer_receipt")),
        "delivery_runtime": _compact_delivery_runtime(payload.get("delivery_runtime")),
    }
    return {key: value for key, value in compact.items() if value not in (None, "", [], {})}


def _compact_zhiyi_response(response: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    if not _is_zhiyi_recall_call(request):
        return response
    result = response.get("result") if isinstance(response.get("result"), dict) else {}
    if result.get("isError"):
        return response
    structured = result.get("structuredContent")
    if not isinstance(structured, dict):
        return response

    compact_payload = _compact_recall_payload(structured)
    compact_result = dict(result)
    compact_result["structuredContent"] = compact_payload
    compact_result["content"] = [
        {
            "type": "text",
            "text": json.dumps(compact_payload, ensure_ascii=False, separators=(",", ":")),
        }
    ]
    compact_response = dict(response)
    compact_response["result"] = compact_result
    return compact_response


def _forward(
    endpoint: str,
    data: dict[str, Any],
    timeout: float,
    compact_recall: bool,
    *,
    http_session: _McpHttpSession | None = None,
    canonical_window_id: str = "",
    session_id: str = "",
    registry_path: str = "",
    binding_key: str = "",
) -> dict[str, Any] | None:
    forwarded = (
        _budget_zhiyi_request(
            data,
            canonical_window_id=canonical_window_id,
            session_id=session_id,
            registry_path=registry_path,
            binding_key=binding_key,
        )
        if compact_recall
        else data
    )
    method = str(forwarded.get("method") or "")
    recovery_performed = False
    if http_session is not None:
        http_session.set_endpoint(endpoint)
        http_session.remember_request(forwarded)
        if (
            method != "initialize"
            and not http_session.session_id
            and http_session.initialize_request is not None
        ):
            recovery_performed, reverification_reason = _reinitialize_session(
                endpoint,
                timeout,
                http_session,
                replay_initialized_notification=method != "notifications/initialized",
                log=_log,
            )
            if not recovery_performed:
                if reverification_reason:
                    return _mcp_reverification_required(
                        forwarded.get("id"),
                        reverification_reason,
                    )
                return _mcp_error(
                    forwarded.get("id"),
                    -32000,
                    "Time Library MCP session recovery failed; original request was not sent",
                )
    response, status, raw = _send_once(
        endpoint,
        forwarded,
        timeout,
        http_session=http_session,
    )
    if (
        http_session is not None
        and method != "initialize"
        and not recovery_performed
        and _is_session_rejection(status, response, raw)
    ):
        recovery_performed, reverification_reason = _reinitialize_session(
            endpoint,
            timeout,
            http_session,
            replay_initialized_notification=method != "notifications/initialized",
            log=_log,
        )
        if not recovery_performed and reverification_reason:
            return _mcp_reverification_required(
                forwarded.get("id"),
                reverification_reason,
            )
        if recovery_performed:
            response, status, raw = _send_once(
                endpoint,
                forwarded,
                timeout,
                http_session=http_session,
            )
    if http_session is not None and recovery_performed:
        if _is_session_rejection(status, response, raw):
            preserve_verified_bearer = bool(
                http_session.verified_connection and http_session.session_id
            )
            http_session.mark_recovery_failure(
                endpoint,
                preserve_resume=preserve_verified_bearer,
            )
            _log(
                "MCP session recovery failed stage=original_request "
                f"failures={http_session.recovery_failures} "
                f"verified_bearer_preserved={str(preserve_verified_bearer).lower()}"
            )
        else:
            http_session.mark_recovery_success()
            _log("MCP session recovery completed")
    if http_session is not None:
        http_session.observe_response(forwarded, response)
    if response is None:
        return None
    return _compact_zhiyi_response(response, data) if compact_recall else response


def _forward_discovered(
    configured_endpoint: str,
    data: dict[str, Any],
    timeout: float,
    compact_recall: bool,
    root: str = "",
    **kwargs: Any,
) -> dict[str, Any] | None:
    try:
        endpoint = resolve_client_url(
            "/mcp",
            endpoint=configured_endpoint,
            root=str(root or os.environ.get("MEMCORE_ROOT") or "").strip() or None,
            wait_timeout=min(max(0.0, timeout), 3.0),
        )
    except RuntimeError as exc:
        return _mcp_error(data.get("id"), -32000, str(exc))
    return _forward(endpoint, data, timeout, compact_recall, **kwargs)


def main() -> int:
    parser = argparse.ArgumentParser(description="Codex stdio bridge for Time Library MCP")
    parser.add_argument(
        "--endpoint",
        default="",
        help="Optional explicit endpoint; omitted or legacy loopback endpoints use the front-door discovery file.",
    )
    parser.add_argument(
        "--root",
        default="",
        help="Explicit Time Library install/runtime root for front-door discovery.",
    )
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument(
        "--canonical-window-id",
        default="",
        help="Explicit Codex project/window id for window-scoped recall.",
    )
    parser.add_argument(
        "--session-id",
        default="",
        help="Explicit Codex thread/session id for window-scoped recall.",
    )
    parser.add_argument(
        "--window-binding-registry",
        default="",
        help="Path to the Time Library window_binding_registry.json.",
    )
    parser.add_argument(
        "--binding-key",
        default="",
        help="Current-window registry key for this Codex bridge.",
    )
    parser.add_argument(
        "--full-recall-response",
        dest="compact_recall",
        action="store_false",
        help="Forward the full raw gateway recall payload instead of the compact payload.",
    )
    parser.set_defaults(compact_recall=True)
    args = parser.parse_args()

    _log(f"bridge started -> per-request front-door discovery timeout={args.timeout}s compact_recall={args.compact_recall}")
    http_session = _McpHttpSession()
    while True:
        data = _read_message()
        if data is None:
            return 0
        method = str(data.get("method") or "")
        if method == "__parse_error__":
            _write_message(_mcp_error(data.get("id"), -32700, "Parse error"))
            continue
        if method == "__invalid_request__":
            _write_message(_mcp_error(data.get("id"), -32600, "Invalid Request"))
            continue
        response = _forward_discovered(
            args.endpoint,
            data,
            args.timeout,
            args.compact_recall,
            root=args.root,
            http_session=http_session,
            canonical_window_id=args.canonical_window_id,
            session_id=args.session_id,
            registry_path=args.window_binding_registry,
            binding_key=args.binding_key,
        )
        if response is not None:
            _write_message(response)


if __name__ == "__main__":
    raise SystemExit(main())
