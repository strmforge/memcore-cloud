#!/usr/bin/env python3
"""
memcore-cloud local UI server.

The default page is the product-facing Time Library personal memory center.
Older read-only API routes remain available for diagnostics and phased review.
"""
import os, sys, json, glob, subprocess, datetime, mimetypes, secrets
import importlib.util
import ipaddress
import urllib.parse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from threading import Thread
try:
    from src.hermes_paths import hermes_config_paths, resolve_hermes_home
except Exception:
    from hermes_paths import hermes_config_paths, resolve_hermes_home
try:
    from src.zhiyi_archive import attach_archive_card, archive_card
except Exception:
    from zhiyi_archive import attach_archive_card, archive_card
try:
    from src.zhixing_library import (
        attach_library_card,
        build_toolbook_candidate,
        benchmark_plan,
        hybrid_recall_manifest,
        library_manifest,
        replay_plan,
        run_benchmark_dry_run,
        run_replay_dry_run,
        validate_toolbook_candidate,
        zhixing_loop_manifest,
    )
except Exception:
    from zhixing_library import (
        attach_library_card,
        build_toolbook_candidate,
        benchmark_plan,
        hybrid_recall_manifest,
        library_manifest,
        replay_plan,
        run_benchmark_dry_run,
        run_replay_dry_run,
        validate_toolbook_candidate,
        zhixing_loop_manifest,
    )
try:
    from src import p6_zhixing_routes
except Exception:
    import p6_zhixing_routes
try:
    from src.library_search import search_library
except Exception:
    from library_search import search_library
try:
    from src.time_library_delivery_runtime import query_delivery_status
except Exception:
    from time_library_delivery_runtime import query_delivery_status
try:
    from src.dialog_intent_router import classify_fine_intent
except Exception:
    from dialog_intent_router import classify_fine_intent
try:
    from src.zhiyi_errata import build_zhiyi_errata_candidate
except Exception:
    from zhiyi_errata import build_zhiyi_errata_candidate
try:
    from src.zhixing_method_signal import build_method_signal_candidate, get_method_signal_contract
except Exception:
    from zhixing_method_signal import build_method_signal_candidate, get_method_signal_contract
try:
    from src.zhixing_state_ledger import build_state_ledger_snapshot, get_state_ledger_plan
except Exception:
    from zhixing_state_ledger import build_state_ledger_snapshot, get_state_ledger_plan
try:
    from src.zhixing_context_unit import build_context_budget_unit_candidate, get_context_budget_unit_contract
except Exception:
    from zhixing_context_unit import build_context_budget_unit_candidate, get_context_budget_unit_contract
try:
    from src.external_docs_evidence import (
        build_external_docs_evidence_dry_run,
        get_external_docs_evidence_contract,
    )
except Exception:
    from external_docs_evidence import (
        build_external_docs_evidence_dry_run,
        get_external_docs_evidence_contract,
    )
try:
    from src.context_delivery_compaction import (
        build_context_delivery_compaction_dry_run,
        get_context_delivery_compaction_contract,
    )
except Exception:
    from context_delivery_compaction import (
        build_context_delivery_compaction_dry_run,
        get_context_delivery_compaction_contract,
    )
try:
    from src.tiandao.memory_routing import time_origin_contract_descriptor
except Exception:
    from tiandao.memory_routing import time_origin_contract_descriptor
try:
    from src.tiandao import time_twin_star_runtime_status
except Exception:
    from tiandao import time_twin_star_runtime_status
try:
    from src.time_river_sediment import (
        build_time_river_sediment_dry_run,
        get_time_river_sediment_contract,
    )
except Exception:
    from time_river_sediment import (
        build_time_river_sediment_dry_run,
        get_time_river_sediment_contract,
    )
try:
    from src.material_processing_pipeline import (
        build_material_processing_pipeline_dry_run,
        get_material_processing_pipeline_contract,
    )
except Exception:
    from material_processing_pipeline import (
        build_material_processing_pipeline_dry_run,
        get_material_processing_pipeline_contract,
    )
try:
    from src.second_brain import build_second_brain_dry_run, get_second_brain_contract
except Exception:
    from second_brain import build_second_brain_dry_run, get_second_brain_contract
try:
    from src.tiandao_workbenches import (
        build_tiandao_workbenches_dashboard,
        get_tiandao_workbenches_contract,
    )
except Exception:
    from tiandao_workbenches import (
        build_tiandao_workbenches_dashboard,
        get_tiandao_workbenches_contract,
    )
try:
    from src.record_chain_doctor import (
        build_record_chain_replay,
        build_record_chain_timeline,
        build_record_doctor,
    )
except Exception:
    from record_chain_doctor import (
        build_record_chain_replay,
        build_record_chain_timeline,
        build_record_doctor,
    )
try:
    from src.hermes_skill_experience_diff import (
        build_hermes_skill_experience_diff_dry_run,
        get_hermes_skill_experience_diff_plan,
    )
except Exception:
    from hermes_skill_experience_diff import (
        build_hermes_skill_experience_diff_dry_run,
        get_hermes_skill_experience_diff_plan,
    )
try:
    from src.hermes_self_review_report import (
        build_hermes_self_review_report_dry_run,
        get_hermes_self_review_report_plan,
        record_hermes_self_review_report_candidate,
    )
except Exception:
    from hermes_self_review_report import (
        build_hermes_self_review_report_dry_run,
        get_hermes_self_review_report_plan,
        record_hermes_self_review_report_candidate,
    )
try:
    from src.model_facts import (
        build_model_facts_report,
        build_model_runnable_doctor_smoke,
        get_model_facts_plan,
        get_model_runnable_doctor_plan,
    )
except Exception:
    from model_facts import (
        build_model_facts_report,
        build_model_runnable_doctor_smoke,
        get_model_facts_plan,
        get_model_runnable_doctor_plan,
    )
try:
    from src.distill_transparency import default_ledger_path as get_distill_transparency_ledger_path
    from src.distill_transparency import get_entry as get_distill_transparency_entry
    from src.distill_transparency import ledger_status as get_distill_transparency_status
    from src.distill_transparency import read_entries as read_distill_transparency_entries
except Exception:
    from distill_transparency import default_ledger_path as get_distill_transparency_ledger_path
    from distill_transparency import get_entry as get_distill_transparency_entry
    from distill_transparency import ledger_status as get_distill_transparency_status
    from distill_transparency import read_entries as read_distill_transparency_entries

try:
    from src.p6_console_ui import I18N, HTML_TEMPLATE, get_console_ui_contract
except Exception:
    from p6_console_ui import I18N, HTML_TEMPLATE, get_console_ui_contract
try:
    from src import p6_console_reading_area as _console_reading_area
    from src import p6_console_runtime_profile as _console_runtime_profile
except Exception:
    import p6_console_reading_area as _console_reading_area
    import p6_console_runtime_profile as _console_runtime_profile
try:
    from src.p6_console_state import (
        add_console_note,
        add_console_project,
        add_console_task,
        configure_console_state,
        delete_console_note,
        delete_console_project,
        delete_console_task,
        get_console_state,
    )
except Exception:
    from p6_console_state import (
        add_console_note,
        add_console_project,
        add_console_task,
        configure_console_state,
        delete_console_note,
        delete_console_project,
        delete_console_task,
        get_console_state,
    )
try:
    from src.memcore_version import read_memcore_version
except Exception:
    from memcore_version import read_memcore_version
try:
    from src.p6_console_security import (
        SENSITIVE_ACTION_POST_PATHS,
        SENSITIVE_ACTION_POST_PREFIX_SUFFIXES,
        _action_post_requires_console_token as _console_security_action_post_requires_console_token,
        _browser_post_allowed as _console_security_browser_post_allowed,
        _is_loopback_client as _console_security_is_loopback_client,
        _is_loopback_host as _console_security_is_loopback_host,
        _request_host_name as _console_security_request_host_name,
        _same_origin_or_local as _console_security_same_origin_or_local,
        _strict_action_post_allowed as _console_security_strict_action_post_allowed,
        get_console_security_contract,
    )
except Exception:
    from p6_console_security import (
        SENSITIVE_ACTION_POST_PATHS,
        SENSITIVE_ACTION_POST_PREFIX_SUFFIXES,
        _action_post_requires_console_token as _console_security_action_post_requires_console_token,
        _browser_post_allowed as _console_security_browser_post_allowed,
        _is_loopback_client as _console_security_is_loopback_client,
        _is_loopback_host as _console_security_is_loopback_host,
        _request_host_name as _console_security_request_host_name,
        _same_origin_or_local as _console_security_same_origin_or_local,
        _strict_action_post_allowed as _console_security_strict_action_post_allowed,
        get_console_security_contract,
    )
try:
    from src import p6_console_status as _console_status
except Exception:
    import p6_console_status as _console_status
try:
    from src import p6_console_memory as _console_memory
except Exception:
    import p6_console_memory as _console_memory
try:
    from src.p6_console_openclaw import (
        _openclaw_chat_send_bool,
        _openclaw_chat_send_parse_key,
        _openclaw_chat_send_present,
        _openclaw_chat_send_session_iso,
        _openclaw_chat_send_session_ms,
        _openclaw_chat_send_session_summary,
        apply_openclaw_chat_send_authorized,
        get_openclaw_console_contract,
        query_openclaw_chat_send_targets,
    )
except Exception:
    from p6_console_openclaw import (
        _openclaw_chat_send_bool,
        _openclaw_chat_send_parse_key,
        _openclaw_chat_send_present,
        _openclaw_chat_send_session_iso,
        _openclaw_chat_send_session_ms,
        _openclaw_chat_send_session_summary,
        apply_openclaw_chat_send_authorized,
        get_openclaw_console_contract,
        query_openclaw_chat_send_targets,
    )
try:
    from src.p4_provider import build_catalog_inject_from_candidates
except Exception:
    from p4_provider import build_catalog_inject_from_candidates
try:
    from src.reading_area_registry import load_registry as load_reading_area_registry
except Exception:
    from reading_area_registry import load_registry as load_reading_area_registry
try:
    from src.productized_loops import (
        build_borrowing_receipts_view_dry_run,
        build_productized_loops_doctor,
    )
except Exception:
    from productized_loops import (
        build_borrowing_receipts_view_dry_run,
        build_productized_loops_doctor,
    )
try:
    from src.preflight_doctor import build_preflight_doctor
except Exception:
    from preflight_doctor import build_preflight_doctor
try:
    from src.p6_zhiyi_model_runtime import *
except Exception:
    from p6_zhiyi_model_runtime import *
try:
    from src.granite_vector_assets import resume_legacy_vector_upgrade
except Exception:
    from granite_vector_assets import resume_legacy_vector_upgrade
try:
    from src import p6_experience_governance as _experience_governance
    from src.p6_experience_governance import *
except Exception:
    import p6_experience_governance as _experience_governance
    from p6_experience_governance import *
from config_loader import base_path
from service_manager import get_service_manager
MEMCORE_ROOT = base_path()
SERVICE_VERSION = read_memcore_version(MEMCORE_ROOT)
try:
    _console_status.configure_console_status(MEMCORE_ROOT)
except Exception:
    pass
try:
    configure_console_state(MEMCORE_ROOT)
except Exception:
    pass
try:
    configure_zhiyi_model_runtime(MEMCORE_ROOT)
except Exception:
    pass
try:
    configure_experience_governance(MEMCORE_ROOT)
    M6_PROPOSALS_DIR = _experience_governance.M6_PROPOSALS_DIR
except Exception:
    pass
PORT = int(os.environ.get("TIME_LIBRARY_INTERNAL_P6_PORT", "19500"))
INTERNAL_P3_PORT = int(os.environ.get("TIME_LIBRARY_INTERNAL_P3_PORT", "19300"))
INTERNAL_P4_PORT = int(os.environ.get("TIME_LIBRARY_INTERNAL_P4_PORT", "19400"))
PRODUCT_UI_TEMPLATE_PATH = os.path.join(str(MEMCORE_ROOT), "web", "console_product.html")
PRODUCT_ASSET_ROOT = os.path.join(str(MEMCORE_ROOT), "web", "assets")
CONSOLE_CSRF_TOKEN = os.environ.get("MEMCORE_CONSOLE_TOKEN", "").strip() or secrets.token_urlsafe(32)
CONSOLE_CSRF_JS = json.dumps(CONSOLE_CSRF_TOKEN)
CONSOLE_TOKEN_PATH = os.path.join(str(MEMCORE_ROOT), "runtime", "console_token")
P6_PID_PATH = os.path.join(str(MEMCORE_ROOT), "runtime", "p6-console.pid")


def _write_p6_pid_file() -> bool:
    return _console_runtime_profile.write_owned_pid_file(P6_PID_PATH)


def _clear_p6_pid_file() -> None:
    _console_runtime_profile.clear_owned_pid_file(P6_PID_PATH)


def _write_console_token_file() -> None:
    try:
        os.makedirs(os.path.dirname(CONSOLE_TOKEN_PATH), exist_ok=True)
        existing = ""
        if os.path.exists(CONSOLE_TOKEN_PATH):
            with open(CONSOLE_TOKEN_PATH, encoding="utf-8") as f:
                existing = f.read().strip()
        if existing != CONSOLE_CSRF_TOKEN:
            with open(CONSOLE_TOKEN_PATH, "w", encoding="utf-8") as f:
                f.write(CONSOLE_CSRF_TOKEN + "\n")
        try:
            os.chmod(CONSOLE_TOKEN_PATH, 0o600)
        except Exception:
            pass
    except Exception:
        pass


_write_console_token_file()

# V4: dry_run_token store for apply endpoint binding validation
# token → {version, pkg_path, install_root, created_at}
# Cleaned up on token expiry (10min TTL)
_DRY_RUN_TOKENS = {}


_safe_runtime_profile_part = _console_runtime_profile._safe_runtime_profile_part
_public_runtime_profile_instances = _console_runtime_profile._public_runtime_profile_instances


def _load_runtime_profile_module():
    return _console_runtime_profile.load_runtime_profile_module(MEMCORE_ROOT)


def build_reading_area_summary():
    return _console_reading_area.build_reading_area_summary(
        MEMCORE_ROOT,
        load_registry=load_reading_area_registry,
        build_catalog=build_catalog_inject_from_candidates,
    )



# ─── Console status diagnostics delegates ──────────────────────────

def get_console_status_contract():
    return _console_status.get_console_status_contract()


def _command_line_looks_like_p0_watcher(command_line):
    return _console_status._command_line_looks_like_p0_watcher(command_line)


def _windows_p0_watcher_process(pid=None):
    return _console_status._windows_p0_watcher_process(pid)


def _pid_file_value(path):
    return _console_status._pid_file_value(path)


def get_watcher_status_detail():
    return _console_status.get_watcher_status_detail()


def get_watcher_status():
    return _console_status.get_watcher_status()


def _raw_session_files():
    return _console_status._raw_session_files()


def get_raw_stats():
    return _console_status.get_raw_stats()


def get_zhiyi_stats():
    return _console_status.get_zhiyi_stats()


def get_alias_map():
    return _console_status.get_alias_map()


def load_zhiyi_objects(ftype=None, limit=None):
    return _console_status.load_zhiyi_objects(ftype=ftype, limit=limit)


def run_health_check():
    return _console_status.run_health_check()


def m3_get_overview():
    return _console_status.m3_get_overview(
        get_watcher_status_fn=get_watcher_status,
        get_raw_stats_fn=get_raw_stats,
        get_zhiyi_stats_fn=get_zhiyi_stats,
    )


def m3_get_openclaw_runtime():
    return _console_status.m3_get_openclaw_runtime()


def m3_get_memory_runtime():
    return _console_status.m3_get_memory_runtime()


def m3_get_j2_j7_runtime():
    return _console_status.m3_get_j2_j7_runtime()


def m3_get_recent_recall():
    return _console_status.m3_get_recent_recall()


def m3_get_audit_risks():
    return _console_status.m3_get_audit_risks()


def m3_get_update_status():
    return _console_status.m3_get_update_status()


def m3_get_source_systems():
    return _console_status.m3_get_source_systems()


def _m4_scan_task_results():
    return _console_status._m4_scan_task_results()


def m4_get_task_results():
    return _console_status.m4_get_task_results()


def m4_get_task_detail(task_id):
    return _console_status.m4_get_task_detail(task_id)


def m4_get_task_summary(task_id):
    return _console_status.m4_get_task_summary(task_id)


def m4_get_risk_backlog():
    return _console_status.m4_get_risk_backlog()


def m4_get_next_decision_summary():
    return _console_status.m4_get_next_decision_summary()


_m5_raw_evidence_for_refs = _console_memory._m5_raw_evidence_for_refs
_m5_safe_memories = _console_memory._m5_safe_memories
_m5_get_memories = _console_memory._m5_get_memories
_m5_get_memory_detail = _console_memory._m5_get_memory_detail
_m5_get_memory_refs = _console_memory._m5_get_memory_refs
_m5_get_lifecycle_overlay_stats = _console_memory._m5_get_lifecycle_overlay_stats
_m5_recall_preview = _console_memory._m5_recall_preview
_m5_injection_explain = _console_memory._m5_injection_explain

try:
    _console_memory.configure_console_memory(
        MEMCORE_ROOT,
        load_zhiyi_objects_fn=load_zhiyi_objects,
    )
    configure_experience_governance(
        MEMCORE_ROOT,
        load_zhiyi_objects=lambda ftype=None, limit=None: load_zhiyi_objects(ftype=ftype, limit=limit),
        get_zhiyi_stats=lambda: get_zhiyi_stats(),
        raw_evidence_for_refs=lambda refs, excerpt_chars=600: _m5_raw_evidence_for_refs(
            refs,
            excerpt_chars=excerpt_chars,
        ),
    )
    M6_PROPOSALS_DIR = _experience_governance.M6_PROPOSALS_DIR
except Exception:
    pass


# Experience governance console helpers live under p6_experience_governance.py.


# ─── API Handler ──────────────────────────────────────────


# ─── Console action gate delegates ──────────────────────────

def _is_loopback_host(host: str) -> bool:
    return _console_security_is_loopback_host(host)


def _is_loopback_client(client_address) -> bool:
    return _console_security_is_loopback_client(client_address)


def _request_host_name(value: str) -> str:
    return _console_security_request_host_name(value)


def _same_origin_or_local(origin: str, host_header: str) -> bool:
    return _console_security_same_origin_or_local(origin, host_header)


def _action_post_requires_console_token(path: str) -> bool:
    return _console_security_action_post_requires_console_token(path)


def _strict_action_post_allowed(headers, client_address) -> bool:
    return _console_security_strict_action_post_allowed(headers, client_address, CONSOLE_CSRF_TOKEN)


def _browser_post_allowed(headers, client_address) -> bool:
    return _console_security_browser_post_allowed(headers, client_address, CONSOLE_CSRF_TOKEN)

class Handler(BaseHTTPRequestHandler):
    """本地管理控制台 - 仅监听 localhost，不对外暴露。

    静态文件服务限制在白名单路径内，禁止目录遍历。
    """

    def send_json(self, data, code=200):
        try:
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode())
        except (BrokenPipeError, ConnectionResetError):
            pass

    def read_json_body(self):
        cl = int(self.headers.get("Content-Length", 0))
        if cl <= 0:
            return {}, None
        raw = self.rfile.read(cl).decode("utf-8", errors="replace")
        try:
            body = json.loads(raw)
        except Exception as exc:
            return {}, {
                "ok": False,
                "error": "invalid_json_body",
                "detail": f"{type(exc).__name__}: {str(exc)[:160]}",
            }
        if not isinstance(body, dict):
            return {}, {"ok": False, "error": "json_object_required"}
        return body, None

    def reject_unsafe_post(self) -> bool:
        if _browser_post_allowed(self.headers, getattr(self, "client_address", None)):
            return False
        self.send_json({"ok": False, "error": "local console token required"}, 403)
        return True

    def reject_unsafe_action_post(self, path: str) -> bool:
        if not _action_post_requires_console_token(path):
            return False
        if _strict_action_post_allowed(self.headers, getattr(self, "client_address", None)):
            return False
        self.send_json({"ok": False, "error": "local console action token required"}, 403)
        return True

    def send_html(self):
        i18n_json = json.dumps(I18N, ensure_ascii=False)
        memcore_root_json = json.dumps(str(MEMCORE_ROOT), ensure_ascii=False)
        memcore_version = read_memcore_version(MEMCORE_ROOT)
        template = HTML_TEMPLATE
        if os.path.exists(PRODUCT_UI_TEMPLATE_PATH):
            with open(PRODUCT_UI_TEMPLATE_PATH, encoding="utf-8") as f:
                template = f.read()
        html = (
            template
            .replace("$I18N_JSON", i18n_json)
            .replace("$PORT", str(PORT))
            .replace("$MEMCORE_ROOT_JSON", memcore_root_json)
            .replace("$MEMCORE_VERSION", memcore_version)
            .replace("$CONSOLE_CSRF_TOKEN", CONSOLE_CSRF_JS)
        )
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    def log_message(self, *args):
        pass

    def do_HEAD(self):
        import urllib.parse
        norm_path = urllib.parse.unquote(self.path)
        if ".." in norm_path or norm_path.startswith("//"):
            self.send_error(403)
            return
        if norm_path == "/" or norm_path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            return
        if norm_path.startswith("/assets/"):
            relative_path = norm_path[len("/assets/"):]
            real_path = os.path.realpath(os.path.join(PRODUCT_ASSET_ROOT, relative_path))
            allowed_root = os.path.realpath(PRODUCT_ASSET_ROOT)
            if real_path != allowed_root and real_path.startswith(allowed_root + os.sep) and os.path.isfile(real_path):
                self.send_response(200)
                self.send_header("Content-Type", mimetypes.guess_type(real_path)[0] or "application/octet-stream")
                self.send_header("Content-Length", str(os.path.getsize(real_path)))
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                return
        self.send_error(404)

    def do_GET(self):
        # 禁止目录遍历
        import urllib.parse
        parsed_path = urllib.parse.urlparse(self.path)
        norm_path = urllib.parse.unquote(parsed_path.path)
        if ".." in norm_path or norm_path.startswith("//"):
            self.send_error(403)
            return

        if norm_path == "/" or norm_path == "/index.html":
            self.send_html()
        elif norm_path.startswith("/assets/"):
            self.serve_product_asset(norm_path)
        elif norm_path.startswith("/api/v1/"):
            self.do_GET_api_v1(norm_path)
        elif norm_path.startswith("/api/"):
            self.do_GET_api(norm_path)
        else:
            # 静态文件白名单
            self.serve_static(norm_path)

    def serve_product_asset(self, path):
        relative_path = path[len("/assets/"):]
        if not relative_path or ".." in relative_path or relative_path.startswith(("/", "\\")):
            self.send_error(403)
            return
        real_path = os.path.realpath(os.path.join(PRODUCT_ASSET_ROOT, relative_path))
        allowed_root = os.path.realpath(PRODUCT_ASSET_ROOT)
        if real_path != allowed_root and not real_path.startswith(allowed_root + os.sep):
            self.send_error(403)
            return
        if not os.path.isfile(real_path):
            self.send_error(404)
            return
        content_type = mimetypes.guess_type(real_path)[0] or "application/octet-stream"
        with open(real_path, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "public, max-age=3600")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def serve_static(self, path):
        # 只允许访问 memory/ 下的新旧 raw session 文件
        if path.count("/") < 4:
            # legacy: memory/<source_system>/<node>/window/session.jsonl
            # current: memory/<node>/<source_system>/<native_format>/scope/session.jsonl
            self.send_error(403)
            return
        # 禁止访问 zhiyi/ 等敏感子目录
        normalized = os.path.normpath(path)
        if "/zhiyi/" in normalized or normalized.startswith("/zhiyi"):
            self.send_error(403)
            return
        safe_path = MEMCORE_ROOT + path
        real_path = os.path.realpath(safe_path)
        allowed_root = os.path.realpath(MEMCORE_ROOT)
        allowed_memory = os.path.join(allowed_root, "memory") + os.sep
        if not real_path.startswith(allowed_memory):
            self.send_error(403)
            return
        if not os.path.isfile(real_path) or not real_path.endswith(".jsonl"):
            self.send_error(403)
            return
        try:
            with open(real_path, "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", len(data))
            self.end_headers()
            self.wfile.write(data)
        except:
            self.send_error(404)

    def do_GET_api(self, path):
        if path == "/api/watcher":
            self.send_json({"active": get_watcher_status()})
        elif path == "/api/raw_stats":
            self.send_json(get_raw_stats())
        elif path == "/api/zhiyi_stats":
            self.send_json(get_zhiyi_stats())
        elif path == "/api/raw_sessions":
            from pathlib import Path
            root = Path(str(MEMCORE_ROOT)) / "memory"
            sessions = sorted(root.glob("*/*/*/*.jsonl")) if root.exists() else []
            result = []
            for s in sessions:
                try:
                    rel_parts = s.relative_to(root).parts
                except Exception:
                    rel_parts = ()
                source_system = rel_parts[0] if len(rel_parts) >= 1 else ""
                computer_name = rel_parts[1] if len(rel_parts) >= 2 else ""
                window = s.parent.name
                session_id = s.stem
                try:
                    size_bytes = s.stat().st_size
                except OSError:
                    size_bytes = 0
                if size_bytes <= 5 * 1024 * 1024:
                    try:
                        with s.open("r", encoding="utf-8", errors="ignore") as f:
                            msg_count = sum(1 for line in f if line.strip())
                    except Exception:
                        msg_count = -1
                else:
                    msg_count = -1
                channel = "webchat"
                ch_path = s.parent / ".channel_index.json"
                if ch_path.exists():
                    try:
                        with ch_path.open("r", encoding="utf-8", errors="ignore") as f:
                            idx = json.load(f)
                        channel = idx.get("sessions", {}).get(session_id, {}).get("channel", "webchat")
                    except:
                        pass
                result.append({"source_system": source_system,
                                "computer_name": computer_name,
                                "window": window,
                                # P1-3 Fix: show short session_id on LAN-exposed API
                                "session_id": session_id[:8] + "...",
                                "session_id_full": session_id,
                                "msg_count": msg_count,
                                "msg_count_note": "skipped_large_file" if msg_count == -1 and size_bytes > 5 * 1024 * 1024 else "",
                                "size_bytes": size_bytes,
                                "channel": channel})
            result.sort(key=lambda x: (x.get("source_system", ""), x["window"]))
            known_messages = sum(s["msg_count"] for s in result if s["msg_count"] >= 0)
            skipped_large_files = sum(1 for s in result if s["msg_count"] == -1)
            self.send_json({"sessions": len(sessions),
                            "windows": len(set(s["window"] for s in result)),
                            "source_systems": sorted(set(s.get("source_system", "") for s in result if s.get("source_system"))),
                            "messages": -1 if skipped_large_files else known_messages,
                            "messages_known": known_messages,
                            "skipped_large_files": skipped_large_files,
                            "sessions_list": result})
        elif path == "/api/alias_map":
            self.send_json(get_alias_map())
        elif path == "/api/zhiyi_objects":
            self.send_json(load_zhiyi_objects(limit=500))
        elif path == "/api/health":
            self.send_json(run_health_check())
        # ── M3 Status APIs (只读) ──
        elif path == "/api/m3/status/overview":
            self.send_json(m3_get_overview())
        elif path == "/api/m3/status/openclaw-runtime":
            self.send_json(m3_get_openclaw_runtime())
        elif path == "/api/m3/status/memory-runtime":
            self.send_json(m3_get_memory_runtime())
        elif path == "/api/m3/status/j2-j7":
            self.send_json(m3_get_j2_j7_runtime())
        elif path == "/api/m3/status/recent-recall":
            self.send_json(m3_get_recent_recall())
        elif path == "/api/m3/status/audit-risks":
            self.send_json(m3_get_audit_risks())
        elif path == "/api/m3/status/update":
            self.send_json(m3_get_update_status())
        elif path == "/api/m3/status/source-systems":
            self.send_json(m3_get_source_systems())
        # ── M4 Task Results APIs (只读) ──
        elif path == "/api/v1/tasks/results":
            self.send_json(m4_get_task_results())
        elif path.startswith("/api/v1/tasks/results/"):
            task_id = path[len("/api/v1/tasks/results/"):]
            if task_id.endswith("/summary"):
                task_id = task_id[:-8]
                self.send_json(m4_get_task_summary(task_id))
            else:
                self.send_json(m4_get_task_detail(task_id))
        elif path == "/api/v1/tasks/risk-backlog":
            self.send_json(m4_get_risk_backlog())
        elif path == "/api/v1/tasks/next-decision-summary":
            self.send_json(m4_get_next_decision_summary())
        else:
            self.send_error(404)

    def do_GET_api_v1(self, path):
        # M1: 单机轻量控制台与知意管理 API v1
        import sys as _sys_api
        import urllib.parse

        # GET /api/v1/distill/transparency - local distillation request ledger
        if path == "/api/v1/distill/transparency":
            full_parsed = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(full_parsed.query)
            try:
                limit = min(max(int((q.get("limit") or ["50"])[0]), 1), 200)
            except Exception:
                limit = 50
            ledger_path = get_distill_transparency_ledger_path(MEMCORE_ROOT)
            items = read_distill_transparency_entries(ledger_path, limit=limit)
            summaries = []
            for item in items:
                summary = dict(item)
                summary.pop("payload_text", None)
                summaries.append(summary)
            self.send_json({**get_distill_transparency_status(ledger_path), "items": summaries})

        # GET /api/v1/distill/transparency/{call_id} - exact local payload drill-down
        elif path.startswith("/api/v1/distill/transparency/"):
            call_id = urllib.parse.unquote(path[len("/api/v1/distill/transparency/"):])
            item = get_distill_transparency_entry(call_id, get_distill_transparency_ledger_path(MEMCORE_ROOT))
            if item is None:
                self.send_json({"ok": False, "error": "transparency_entry_not_found", "call_id": call_id}, 404)
            else:
                self.send_json(item)

        # GET /api/v1/status - 系统总览
        elif path == "/api/v1/status":
            watcher = get_watcher_status()
            raw = get_raw_stats()
            zhiyi = get_zhiyi_stats()
            import socket
            ports_ok = {}
            for svc_name, port in [("p3recall", INTERNAL_P3_PORT), ("p4provider", INTERNAL_P4_PORT)]:
                sock = socket.socket()
                ports_ok[svc_name] = sock.connect_ex(("127.0.0.1", port)) == 0
                sock.close()
            services_ready = bool(watcher) and bool(ports_ok) and all(ports_ok.values())
            self.send_json({
                "status": "ok" if services_ready else "attention",
                "watcher": watcher,
                "raw_memory": raw,
                "zhiyi_stats": zhiyi,
                "service_ports": ports_ok,
                "phase": "local-service-ready" if services_ready else "local-service-attention",
                "memcore_root": str(MEMCORE_ROOT),
            })

        # GET /api/v1/console/state - local product-console state, not memory.
        elif path == "/api/v1/console/state":
            self.send_json(get_console_state())

        # GET /api/v1/delivery/status - append-only delivery audit projection.
        elif path == "/api/v1/delivery/status":
            full_parsed = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(full_parsed.query)
            platform = str((q.get("platform") or [""])[0]).strip()
            try:
                limit = int((q.get("limit") or ["12"])[0])
            except Exception:
                limit = 12
            self.send_json(query_delivery_status(
                memcore_root=str(MEMCORE_ROOT),
                platform=platform,
                limit=limit,
            ))

        # GET /api/v1/reading-area/summary - true Reading Room projection, read-only.
        elif path == "/api/v1/reading-area/summary":
            self.send_json(build_reading_area_summary())

        # GET /api/v1/tasks/* - M4 task pages (read-only)
        elif path == "/api/v1/tasks/results":
            self.send_json(m4_get_task_results())
        elif path.startswith("/api/v1/tasks/results/"):
            task_id = path[len("/api/v1/tasks/results/"):]
            if task_id.endswith("/summary"):
                task_id = task_id[:-8]
                self.send_json(m4_get_task_summary(task_id))
            else:
                self.send_json(m4_get_task_detail(task_id))
        elif path == "/api/v1/tasks/risk-backlog":
            self.send_json(m4_get_risk_backlog())
        elif path == "/api/v1/tasks/next-decision-summary":
            self.send_json(m4_get_next_decision_summary())

        # GET /api/v1/path/layout - X2: full path layout with override priority
        elif path == "/api/v1/path/layout":
            from platform_adapters.paths import verify_path_layout
            self.send_json(verify_path_layout())

        # GET /api/v1/raw/stats - raw统计
        elif path == "/api/v1/raw/stats":
            self.send_json(get_raw_stats())

        # GET /api/v1/memory-routing/status - current-window-first recall scope contract
        elif path == "/api/v1/memory-routing/status":
            try:
                from active_memory_routing import active_memory_routing_status
            except Exception:
                from src.active_memory_routing import active_memory_routing_status
            self.send_json(active_memory_routing_status())

        # GET /api/v1/zhiyi/stats - 知意统计
        elif path == "/api/v1/zhiyi/stats":
            self.send_json(get_zhiyi_stats())

        # GET /api/v1/zhiyi/model-options - 知意可用模型选择（只读）
        elif path == "/api/v1/zhiyi/model-options":
            self.send_json(get_zhiyi_model_options())

        elif path == "/api/v1/zhiyi/vector-assets/status":
            verify = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("verify", [""])[0]
            self.send_json(granite_asset_status(MEMCORE_ROOT, verify=str(verify).lower() in {"1", "true", "yes"}))

        # GET /api/v1/model-facts - 平台模型事实只读回读
        elif path == "/api/v1/model-facts":
            self.send_json(build_model_facts_report())

        # GET /api/v1/model-facts/plan - 平台模型事实读取契约
        elif path == "/api/v1/model-facts/plan":
            self.send_json(get_model_facts_plan())

        # GET /api/v1/model-facts/runnable-doctor/plan - 模型运行态医生计划
        elif path == "/api/v1/model-facts/runnable-doctor/plan":
            self.send_json(get_model_runnable_doctor_plan())

        # GET /api/v1/zhiyi/model-binding/apply-gate/dry-run - 模型绑定授权门禁
        elif path == "/api/v1/zhiyi/model-binding/apply-gate/dry-run":
            self.send_json(get_zhiyi_model_binding_apply_gate_policy())

        # GET /api/v1/zhiyi/runtime-adapter/dry-run - runtime adapter 调用链路预检
        elif path == "/api/v1/zhiyi/runtime-adapter/dry-run":
            self.send_json(get_zhiyi_runtime_adapter_dry_run_policy())

        # GET /api/v1/zhiyi/runtime-adapter/apply-gate/dry-run - runtime adapter apply 门禁
        elif path == "/api/v1/zhiyi/runtime-adapter/apply-gate/dry-run":
            self.send_json(get_zhiyi_runtime_adapter_apply_gate_policy())

        # GET /api/v1/zhiyi/model-request/envelope/dry-run - 模型请求 envelope 草案
        elif path == "/api/v1/zhiyi/model-request/envelope/dry-run":
            self.send_json(get_zhiyi_model_request_envelope_dry_run_policy())

        # GET /api/v1/zhiyi/usage-log/light-prompts/dry-run - 失败轻提示分类表
        elif path == "/api/v1/zhiyi/usage-log/light-prompts/dry-run":
            self.send_json(get_zhiyi_usage_light_prompt_policy())

        # GET /api/v1/zhiyi/usage-log/apply-gate/dry-run - 使用日志写入授权门禁
        elif path == "/api/v1/zhiyi/usage-log/apply-gate/dry-run":
            self.send_json(get_zhiyi_usage_log_apply_gate_policy())

        # GET /api/v1/zhiyi/usage-log/query/dry-run - 使用日志查询草案（只读）
        elif path == "/api/v1/zhiyi/usage-log/query/dry-run":
            full_parsed = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(full_parsed.query)
            params = {k: v[0] if len(v) == 1 else v for k, v in q.items()}
            self.send_json(query_zhiyi_usage_log_dry_run(params))

        # GET /api/v1/productized-loops/doctor - five visible read-only proof loops
        elif path == "/api/v1/productized-loops/doctor":
            full_parsed = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(full_parsed.query)
            params = {k: v[0] if len(v) == 1 else v for k, v in q.items()}
            self.send_json(build_productized_loops_doctor(params, memcore_root=str(MEMCORE_ROOT)))

        # GET /api/v1/productized-loops/borrowing-receipts - local borrowing receipt viewer
        elif path == "/api/v1/productized-loops/borrowing-receipts":
            full_parsed = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(full_parsed.query)
            params = {k: v[0] if len(v) == 1 else v for k, v in q.items()}
            self.send_json(build_borrowing_receipts_view_dry_run(params, memcore_root=str(MEMCORE_ROOT)))

        # GET /api/v1/preflight-doctor - scored read-only pre-work doctor
        elif path == "/api/v1/preflight-doctor":
            full_parsed = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(full_parsed.query)
            params = {k: v[0] if len(v) == 1 else v for k, v in q.items()}
            params.setdefault("diagnostic_profile", "smoke")
            self.send_json(build_preflight_doctor(params, memcore_root=str(MEMCORE_ROOT)))

        # GET /api/v1/zhiyi/experience-summary - 知意经验概览（只读摘要）
        elif path == "/api/v1/zhiyi/experience-summary":
            self.send_json(get_zhiyi_experience_summary())

        elif path == "/api/v1/library/search":
            full_parsed = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(full_parsed.query)
            query = str((q.get("q") or q.get("query") or [""])[0]).strip()
            try:
                limit = int((q.get("limit") or ["40"])[0])
            except Exception:
                limit = 40
            result = search_library(query, memcore_root=str(MEMCORE_ROOT), limit=limit)
            self.send_json(result, 200 if result.get("ok") else 503)

        # GET /api/v1/zhiyi/experience-recycle-bin - 垃圾桶经验
        elif path == "/api/v1/zhiyi/experience-recycle-bin":
            full_parsed = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(full_parsed.query)
            limit = q.get("limit", ["20"])[0]
            self.send_json(get_zhiyi_experience_recycle_bin(limit))

        # GET /api/v1/openclaw/chat-send/targets - OpenClaw chat.send target sessions（只读）
        elif path == "/api/v1/openclaw/chat-send/targets":
            full_parsed = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(full_parsed.query)
            params = {k: v[0] if len(v) == 1 else v for k, v in q.items()}
            result = query_openclaw_chat_send_targets(params)
            self.send_json(result, 200 if result.get("ok") else 502)

        # GET /api/v1/hermes/feedback-candidates - Hermes 观察经验候选（只读）
        elif path == "/api/v1/hermes/feedback-candidates":
            full_parsed = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(full_parsed.query)
            params = {k: v[0] if len(v) == 1 else v for k, v in q.items()}
            self.send_json(query_hermes_feedback_candidates(params))

        # GET /api/v1/xingce/work-experience-candidates - 行策工作经验候选（只读）
        elif path == "/api/v1/xingce/work-experience-candidates":
            full_parsed = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(full_parsed.query)
            params = {k: v[0] if len(v) == 1 else v for k, v in q.items()}
            self.send_json(query_xingce_work_experience_candidates(params))

        # GET /api/v1/zhixing/library - 知行图书馆只读索引
        elif path == "/api/v1/zhixing/library":
            full_parsed = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(full_parsed.query)
            params = {k: v[0] if len(v) == 1 else v for k, v in q.items()}
            self.send_json(query_zhixing_library(params))

        # GET /api/v1/zhixing/library-trust-dashboard - 真实馆藏可信自检（只读）
        elif path == "/api/v1/zhixing/library-trust-dashboard":
            full_parsed = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(full_parsed.query)
            params = {k: v[0] if len(v) == 1 else v for k, v in q.items()}
            self.send_json(query_zhixing_library_trust_dashboard(params))

        # GET /api/v1/zhixing/replay/plan - 知意/行策效果回放计划
        elif path == "/api/v1/zhixing/replay/plan":
            self.send_json(get_zhixing_replay_plan())

        # GET /api/v1/zhixing/benchmark/plan - 知意/行策真实任务集验证计划
        elif path == "/api/v1/zhixing/benchmark/plan":
            self.send_json(get_zhixing_benchmark_plan())

        # GET /api/v1/zhixing/.../contract - 知行图书馆只读合同
        elif p6_zhixing_routes.send_contract_if_matched(self, path):
            pass

        # GET /api/v1/zhixing/method-signals/contract - 外部方法信号候选合同
        elif path == "/api/v1/zhixing/method-signals/contract":
            self.send_json(get_method_signal_contract())

        # GET /api/v1/zhixing/state-ledger/plan - 状态账本 / 时间索引计划
        elif path == "/api/v1/zhixing/state-ledger/plan":
            self.send_json(get_state_ledger_plan())

        # GET /api/v1/zhixing/context-units/contract - 上下文最小单元候选合同
        elif path == "/api/v1/zhixing/context-units/contract":
            self.send_json(get_context_budget_unit_contract())

        # GET /api/v1/zhixing/external-docs-evidence/contract - 外部文档证据层合同
        elif path == "/api/v1/zhixing/external-docs-evidence/contract":
            self.send_json(get_external_docs_evidence_contract())

        # GET /api/v1/zhixing/context-delivery-compaction/contract - 上下文投递压缩合同
        elif path == "/api/v1/zhixing/context-delivery-compaction/contract":
            self.send_json(get_context_delivery_compaction_contract())

        # GET /api/v1/tiandao/time-origin/contract - 时间起源公共规则合同
        elif path == "/api/v1/tiandao/time-origin/contract":
            payload = time_origin_contract_descriptor()
            payload.update({
                "ok": True,
                "read_only": True,
                "write_performed": False,
                "platform_write_performed": False,
                "memory_write_performed": False,
            })
            self.send_json(payload)

        # GET /api/v1/tiandao/time-twin-star/status - 时间双子星一等状态面
        elif path == "/api/v1/tiandao/time-twin-star/status":
            self.send_json(time_twin_star_runtime_status())

        # GET /api/v1/tiandao/time-river-sediment/contract - 时间长河沉积链合同
        elif path == "/api/v1/tiandao/time-river-sediment/contract":
            self.send_json(get_time_river_sediment_plan())

        # GET /api/v1/zhixing/material-processing-pipeline/contract - 资料处理流水线候选合同
        elif path == "/api/v1/zhixing/material-processing-pipeline/contract":
            self.send_json(get_material_processing_pipeline_plan())

        # GET /api/v1/tiandao/second-brain/contract - 第二大脑合同
        elif path == "/api/v1/tiandao/second-brain/contract":
            self.send_json(get_second_brain_plan())

        # GET /api/v1/tiandao/workbenches/contract - 五大工作台只读合同
        elif path == "/api/v1/tiandao/workbenches/contract":
            self.send_json(get_tiandao_workbenches_contract())

        # GET /api/v1/tiandao/workbenches/dashboard - 五大工作台状态聚合
        elif path == "/api/v1/tiandao/workbenches/dashboard":
            self.send_json(build_tiandao_workbenches_dashboard(
                watcher_active=get_watcher_status(),
                governance_stats=m6_get_stats(),
                hermes_liveness=query_hermes_native_learning_liveness({}),
                hermes_triggers=query_hermes_self_review_triggers_http({"limit": 5}),
                hermes_probes=query_hermes_skill_generation_probes_http({"limit": 5}),
                hermes_statuses=query_hermes_skill_artifact_statuses_http({"limit": 5}),
                hermes_diff_plan=get_hermes_skill_experience_diff_plan(),
                hermes_report_plan=get_hermes_self_review_report_plan(),
            ))

        # GET /api/v1/dialog/intent-routes - 细粒度意图路由说明
        elif path == "/api/v1/dialog/intent-routes":
            self.send_json({
                "ok": True,
                "read_only": True,
                "write_performed": False,
                "version": SERVICE_VERSION,
                "routes": [
                    "correction_errata",
                    "source_lookup",
                    "zhiyi_lookup",
                    "xingce_lookup",
                    "toolbook_lookup",
                    "benchmark_replay",
                    "method_signal",
                    "state_ledger",
                    "context_unit",
                    "memory_recall",
                    "no_memory",
                    "complex_task",
                    "pass_through",
                    "chitchat",
                ],
            })

        # GET /api/v1/xingce/work-experience-actions - 行策候选处理记录（只读）
        elif path == "/api/v1/xingce/work-experience-actions":
            full_parsed = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(full_parsed.query)
            params = {k: v[0] if len(v) == 1 else v for k, v in q.items()}
            self.send_json(query_xingce_work_experience_actions(params))

        # GET /api/v1/hermes/feedback-actions - Hermes 候选处理记录（只读）
        elif path == "/api/v1/hermes/feedback-actions":
            full_parsed = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(full_parsed.query)
            params = {k: v[0] if len(v) == 1 else v for k, v in q.items()}
            self.send_json(query_hermes_feedback_actions(params))

        # GET /api/v1/hermes/native-learning/liveness - Hermes native learning 心跳（只读）
        elif path == "/api/v1/hermes/native-learning/liveness":
            full_parsed = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(full_parsed.query)
            params = {k: v[0] if len(v) == 1 else v for k, v in q.items()}
            self.send_json(query_hermes_native_learning_liveness(params))

        # GET /api/v1/hermes/native-learning/self-review/wake/dry-run - Hermes 自审信号计划（只读）
        elif path == "/api/v1/hermes/native-learning/self-review/wake/dry-run":
            full_parsed = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(full_parsed.query)
            params = {k: v[0] if len(v) == 1 else v for k, v in q.items()}
            self.send_json(build_hermes_self_review_wake_http_dry_run(params))

        # GET /api/v1/hermes/native-learning/self-review/trigger/dry-run - Hermes 自审真实触发计划
        elif path == "/api/v1/hermes/native-learning/self-review/trigger/dry-run":
            full_parsed = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(full_parsed.query)
            params = {k: v[0] if len(v) == 1 else v for k, v in q.items()}
            self.send_json(build_hermes_self_review_trigger_http_dry_run(params))

        # GET /api/v1/hermes/native-learning/self-review/triggers - Hermes 自审触发回执
        elif path == "/api/v1/hermes/native-learning/self-review/triggers":
            full_parsed = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(full_parsed.query)
            params = {k: v[0] if len(v) == 1 else v for k, v in q.items()}
            self.send_json(query_hermes_self_review_triggers_http(params))

        # GET /api/v1/hermes/native-learning/skill-generation/probe/dry-run - Hermes native skill 生成探针计划
        elif path == "/api/v1/hermes/native-learning/skill-generation/probe/dry-run":
            full_parsed = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(full_parsed.query)
            params = {k: v[0] if len(v) == 1 else v for k, v in q.items()}
            self.send_json(build_hermes_skill_generation_probe_http_dry_run(params))

        # GET /api/v1/hermes/native-learning/skill-generation/probes - Hermes native skill 生成探针回执
        elif path == "/api/v1/hermes/native-learning/skill-generation/probes":
            full_parsed = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(full_parsed.query)
            params = {k: v[0] if len(v) == 1 else v for k, v in q.items()}
            self.send_json(query_hermes_skill_generation_probes_http(params))

        # GET /api/v1/hermes/native-learning/skill-artifact-status/plan - Hermes skill artifact 状态化计划
        elif path == "/api/v1/hermes/native-learning/skill-artifact-status/plan":
            full_parsed = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(full_parsed.query)
            params = {k: v[0] if len(v) == 1 else v for k, v in q.items()}
            self.send_json(build_hermes_skill_artifact_status_http_dry_run(params))

        # GET /api/v1/hermes/native-learning/skill-artifact-status/dry-run - Hermes skill artifact 状态化草案
        elif path == "/api/v1/hermes/native-learning/skill-artifact-status/dry-run":
            full_parsed = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(full_parsed.query)
            params = {k: v[0] if len(v) == 1 else v for k, v in q.items()}
            self.send_json(build_hermes_skill_artifact_status_http_dry_run(params))

        # GET /api/v1/hermes/native-learning/skill-artifact-statuses - Hermes skill artifact 状态回执
        elif path == "/api/v1/hermes/native-learning/skill-artifact-statuses":
            full_parsed = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(full_parsed.query)
            params = {k: v[0] if len(v) == 1 else v for k, v in q.items()}
            self.send_json(query_hermes_skill_artifact_statuses_http(params))

        # GET /api/v1/hermes/native-learning/autonomous-loop/state - Hermes 自主环门控状态
        elif path == "/api/v1/hermes/native-learning/autonomous-loop/state":
            full_parsed = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(full_parsed.query)
            params = {k: v[0] if len(v) == 1 else v for k, v in q.items()}
            self.send_json(query_hermes_autonomous_loop_state_http(params))

        # GET /api/v1/hermes/native-learning/autonomous-loop/run/dry-run - Hermes 自主环门控计划
        elif path == "/api/v1/hermes/native-learning/autonomous-loop/run/dry-run":
            full_parsed = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(full_parsed.query)
            params = {k: v[0] if len(v) == 1 else v for k, v in q.items()}
            self.send_json(build_hermes_autonomous_loop_http_dry_run(params))

        # GET /api/v1/hermes/native-learning/autonomous-loop/runs - Hermes 自主环运行回执
        elif path == "/api/v1/hermes/native-learning/autonomous-loop/runs":
            full_parsed = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(full_parsed.query)
            params = {k: v[0] if len(v) == 1 else v for k, v in q.items()}
            self.send_json(query_hermes_autonomous_loop_runs_http(params))

        # GET /api/v1/hermes/native-learning/self-review/report/plan - 自审报告升级材料计划
        elif path == "/api/v1/hermes/native-learning/self-review/report/plan":
            self.send_json(get_hermes_self_review_report_plan())

        # GET /api/v1/hermes/native-learning/self-review/report/dry-run - 自审报告转候选草案
        elif path == "/api/v1/hermes/native-learning/self-review/report/dry-run":
            full_parsed = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(full_parsed.query)
            params = {k: v[0] if len(v) == 1 else v for k, v in q.items()}
            self.send_json(build_hermes_self_review_report_dry_run(params, memcore_root=str(MEMCORE_ROOT)))

        # GET /api/v1/hermes/skill-experience-diff/plan - Hermes 技能与经验对比升级计划
        elif path == "/api/v1/hermes/skill-experience-diff/plan":
            self.send_json(get_hermes_skill_experience_diff_plan())

        # GET /api/v1/hermes/consumption-receipts - Hermes 每轮消费回执（只读）
        elif path == "/api/v1/hermes/consumption-receipts":
            full_parsed = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(full_parsed.query)
            params = {k: v[0] if len(v) == 1 else v for k, v in q.items()}
            self.send_json(query_hermes_consumption_receipts(params))

        # GET /api/v1/hermes/feedback-upgrade-inputs - Hermes 升级输入（只读）
        elif path == "/api/v1/hermes/feedback-upgrade-inputs":
            full_parsed = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(full_parsed.query)
            params = {k: v[0] if len(v) == 1 else v for k, v in q.items()}
            self.send_json(query_hermes_feedback_upgrade_inputs(params))

        # GET /api/v1/hermes/feedback-upgrade-inputs/{upgrade_input_id} - 升级输入详情（只读）
        elif path.startswith("/api/v1/hermes/feedback-upgrade-inputs/"):
            upgrade_input_id = path.split("/api/v1/hermes/feedback-upgrade-inputs/")[1]
            result = get_hermes_feedback_upgrade_input(urllib.parse.unquote(upgrade_input_id))
            self.send_json(result, 200 if result.get("ok") else 404)

        # GET /api/v1/xingce/work-experience-candidates/{candidate_id} - 行策候选详情（只读）
        elif path.startswith("/api/v1/xingce/work-experience-candidates/"):
            candidate_id = path.split("/api/v1/xingce/work-experience-candidates/")[1]
            result = get_xingce_work_experience_candidate(urllib.parse.unquote(candidate_id))
            self.send_json(result, 200 if result.get("ok") else 404)

        # GET /api/v1/hermes/feedback-candidates/{candidate_id} - 候选详情（只读）
        elif path.startswith("/api/v1/hermes/feedback-candidates/"):
            candidate_id = path.split("/api/v1/hermes/feedback-candidates/")[1]
            result = get_hermes_feedback_candidate(urllib.parse.unquote(candidate_id))
            self.send_json(result, 200 if result.get("ok") else 404)

        # GET /api/v1/zhiyi/memories/{memory_id}/refs - 回指
        elif path.startswith("/api/v1/zhiyi/memories/") and path.endswith("/refs"):
            id_part = path.split("/api/v1/zhiyi/memories/")[1]
            id_part = urllib.parse.unquote(id_part.replace("/refs", ""))
            result = _m5_get_memory_refs(id_part)
            if "error" in result:
                self.send_error(404)
            else:
                self.send_json(result)

        # GET /api/v1/zhiyi/memories/{id} - global_idx or exp_id detail
        elif path.startswith("/api/v1/zhiyi/memories/") and "?" not in path:
            id_part = path.split("/api/v1/zhiyi/memories/")[1]
            id_part = urllib.parse.unquote(id_part)
            try:
                idx = int(id_part)
                all_objects = load_zhiyi_objects()
                if 0 <= idx < len(all_objects):
                    self.send_json(all_objects[idx])
                else:
                    self.send_error(404)
            except ValueError:
                result = _m5_get_memory_detail(id_part)
                if "error" in result:
                    self.send_error(404)
                else:
                    self.send_json(result)

        # GET /api/v1/zhiyi/memories - 知意列表（分页）
        elif path.startswith("/api/v1/zhiyi/memories"):
            parsed = urllib.parse.urlparse(path)
            q = urllib.parse.parse_qs(parsed.query)
            page = int(q.get("page", [1])[0])
            page_size = min(int(q.get("page_size", [20])[0]), 100)
            ftype = q.get("type", [None])[0]

            all_objects = load_zhiyi_objects(ftype)
            total = len(all_objects)
            start = (page - 1) * page_size
            end = start + page_size
            page_items = all_objects[start:end]

            self.send_json({
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": (total + page_size - 1) // page_size,
                "items": page_items,
            })

        # GET /api/v1/zhiyi/lifecycle-overlay - Lifecycle Overlay 统计
        elif path == "/api/v1/zhiyi/lifecycle-overlay":
            self.send_json(_m5_get_lifecycle_overlay_stats())

        # GET /api/v1/zhiyi/recall/preview - Recall dry-view
        elif path == "/api/v1/zhiyi/recall/preview":
            parsed = urllib.parse.urlparse(path)
            q = urllib.parse.parse_qs(self.path.split("?", 1)[1] if "?" in self.path else "")
            # Use parsed query from original self.path
            full_parsed = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(full_parsed.query)
            params = {k: v[0] if len(v) == 1 else v for k, v in q.items()}
            self.send_json(_m5_recall_preview(params))

        # GET /api/v1/zhiyi/injection/explain - 注入决策解释
        elif path == "/api/v1/zhiyi/injection/explain":
            full_parsed = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(full_parsed.query)
            params = {k: v[0] if len(v) == 1 else v for k, v in q.items()}
            self.send_json(_m5_injection_explain(params))

        # ── M6 Governance Proposal GET Routes (dry-run only) ──
        # GET /api/v1/zhiyi/governance/proposals - proposal 列表
        elif path == "/api/v1/zhiyi/governance/proposals":
            self.send_json(m6_list_proposals())

        # GET /api/v1/zhiyi/governance/proposals/{id} - proposal 详情
        elif path.startswith("/api/v1/zhiyi/governance/proposals/") and "/summary" not in path:
            pid = path.split("/api/v1/zhiyi/governance/proposals/")[1]
            pid = urllib.parse.unquote(pid)
            result = m6_get_proposal(pid)
            if "error" in result:
                self.send_error(404)
            else:
                self.send_json(result)

        # GET /api/v1/zhiyi/governance/proposals/{id}/summary - 复制摘要
        elif path.startswith("/api/v1/zhiyi/governance/proposals/") and "/summary" in path:
            pid = path.replace("/api/v1/zhiyi/governance/proposals/", "").replace("/summary", "")
            pid = urllib.parse.unquote(pid)
            result = m6_get_proposal_summary(pid)
            if "error" in result:
                self.send_error(404)
            else:
                self.send_json(result)

        # GET /api/v1/zhiyi/governance/stats - governance 统计
        elif path == "/api/v1/zhiyi/governance/stats":
            self.send_json(m6_get_stats())

        # GET /api/v1/source-systems - source_system状态
        elif path == "/api/v1/source-systems":
            _sys_api.path.insert(0, str(MEMCORE_ROOT) + "/src")
            try:
                from source_system_registry import list_source_systems, get_active_sources
                self.send_json({
                    "all": list_source_systems(),
                    "active": get_active_sources(),
                })
            except Exception as e:
                self.send_json({"error": str(e), "all": [], "active": []})

        # GET /api/v1/source-systems/local_files/status
        elif path == "/api/v1/source-systems/local_files/status":
            _sys_api.path.insert(0, str(MEMCORE_ROOT) + "/src")
            from connectors.local_files_connector import status as lf_status
            self.send_json(lf_status())

        # GET /api/v1/source-systems/local_files/scan
        elif path == "/api/v1/source-systems/local_files/scan":
            _sys_api.path.insert(0, str(MEMCORE_ROOT) + "/src")
            from connectors.local_files_connector import scan as lf_scan
            self.send_json({"files": lf_scan()})

        # GET /api/v1/source-systems/local_files/checkpoint
        elif path == "/api/v1/source-systems/local_files/checkpoint":
            _sys_api.path.insert(0, str(MEMCORE_ROOT) + "/src")
            from connectors.local_files_connector import checkpoint as lf_checkpoint
            self.send_json(lf_checkpoint())

        # GET /api/v1/source-systems/codex/status
        elif path == "/api/v1/source-systems/codex/status":
            _sys_api.path.insert(0, str(MEMCORE_ROOT) + "/src")
            from codex_local_connector import status as codex_status
            self.send_json(codex_status())

        # GET /api/v1/source-systems/codex/scan
        elif path == "/api/v1/source-systems/codex/scan":
            _sys_api.path.insert(0, str(MEMCORE_ROOT) + "/src")
            from codex_local_connector import scan_sessions as codex_scan
            self.send_json(codex_scan(dry_run=True, limit=20, public=True))

        # GET /api/v1/source-systems/claude_code_cli/status
        elif path == "/api/v1/source-systems/claude_code_cli/status":
            _sys_api.path.insert(0, str(MEMCORE_ROOT) + "/src")
            from claude_code_local_connector import status as claude_code_status
            self.send_json(claude_code_status())

        # GET /api/v1/source-systems/claude_code_cli/scan
        elif path == "/api/v1/source-systems/claude_code_cli/scan":
            _sys_api.path.insert(0, str(MEMCORE_ROOT) + "/src")
            from claude_code_local_connector import scan_sessions as claude_code_scan
            self.send_json(claude_code_scan(dry_run=True, limit=20, public=True))

        # GET /api/v1/source-systems/claude_desktop/status
        elif path == "/api/v1/source-systems/claude_desktop/status":
            _sys_api.path.insert(0, str(MEMCORE_ROOT) + "/src")
            from claude_desktop_connector import status as claude_desktop_status
            self.send_json(claude_desktop_status())

        # GET /api/v1/source-systems/claude_desktop/scan
        elif path == "/api/v1/source-systems/claude_desktop/scan":
            _sys_api.path.insert(0, str(MEMCORE_ROOT) + "/src")
            from claude_desktop_connector import scan as claude_desktop_scan
            self.send_json(claude_desktop_scan(dry_run=True, limit=20, public=True))

        # GET /api/v1/source-systems/claude_desktop/sync-manifest
        elif path == "/api/v1/source-systems/claude_desktop/sync-manifest":
            _sys_api.path.insert(0, str(MEMCORE_ROOT) + "/src")
            from claude_desktop_connector import build_sync_manifest
            self.send_json(build_sync_manifest(public=True, limit=80))

        # GET /api/v1/source-systems/claude_desktop/sync-state
        elif path == "/api/v1/source-systems/claude_desktop/sync-state":
            _sys_api.path.insert(0, str(MEMCORE_ROOT) + "/src")
            from claude_desktop_connector import build_sync_state
            self.send_json(build_sync_state(public=True, apply=False, limit=80))

        # GET /api/v1/source-systems/claude_desktop/consumer-status
        elif path == "/api/v1/source-systems/claude_desktop/consumer-status":
            _sys_api.path.insert(0, str(MEMCORE_ROOT) + "/src")
            from claude_desktop_connector import consumer_status as claude_desktop_consumer_status
            self.send_json(claude_desktop_consumer_status())

        # GET /api/v1/source-systems/claude_desktop/parser-gate
        elif path == "/api/v1/source-systems/claude_desktop/parser-gate":
            _sys_api.path.insert(0, str(MEMCORE_ROOT) + "/src")
            from claude_desktop_connector import parser_gate_policy as claude_desktop_parser_gate_policy
            self.send_json(claude_desktop_parser_gate_policy())

        # GET /api/v1/source-systems/claude_desktop/conversation-body-probe
        elif path == "/api/v1/source-systems/claude_desktop/conversation-body-probe":
            _sys_api.path.insert(0, str(MEMCORE_ROOT) + "/src")
            from claude_desktop_connector import conversation_body_probe as claude_desktop_conversation_body_probe
            self.send_json(claude_desktop_conversation_body_probe())

        # GET /api/v1/source-systems/continuous-sync/status
        elif path == "/api/v1/source-systems/continuous-sync/status":
            _sys_api.path.insert(0, str(MEMCORE_ROOT) + "/src")
            full_parsed = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(full_parsed.query)
            include_generic = str((q.get("scan") or q.get("mode") or [""])[0]).lower() in {"full", "deep"}
            from continuous_sync_status import build_continuous_sync_status
            self.send_json(build_continuous_sync_status(
                watcher_active=get_watcher_status(),
                include_generic=include_generic,
            ))

        # GET /api/v1/records/guardian/status
        elif path == "/api/v1/records/guardian/status":
            _sys_api.path.insert(0, str(MEMCORE_ROOT) + "/src")
            full_parsed = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(full_parsed.query)
            try:
                limit = int((q.get("limit") or ["20"])[0])
            except Exception:
                limit = 20
            include_gaps = str((q.get("gaps") or ["1"])[0]).lower() not in {"0", "false", "no"}
            requested_mode = str((q.get("mode") or q.get("scan") or ["fast"])[0]).lower()
            scan_mode = "full" if requested_mode in {"full", "deep"} else "fast"
            compact = str((q.get("compact") or ["0"])[0]).lower() in {"1", "true", "yes"}
            from raw_record_guardian import build_guardian_status
            self.send_json(build_guardian_status(
                limit=limit,
                include_gaps=include_gaps,
                write_index=False,
                scan_mode=scan_mode,
                compact=compact,
                public=True,
            ))

        # GET /api/v1/records/guardian/index
        elif path == "/api/v1/records/guardian/index":
            _sys_api.path.insert(0, str(MEMCORE_ROOT) + "/src")
            full_parsed = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(full_parsed.query)
            try:
                limit = int((q.get("limit") or ["20"])[0])
            except Exception:
                limit = 20
            include_gaps = str((q.get("gaps") or ["1"])[0]).lower() not in {"0", "false", "no"}
            requested_mode = str((q.get("mode") or q.get("scan") or ["full"])[0]).lower()
            scan_mode = "fast" if requested_mode in {"fast", "stat", "quick"} else "full"
            from raw_record_guardian import build_guardian_status
            self.send_json(build_guardian_status(
                limit=limit,
                include_gaps=include_gaps,
                write_index=True,
                scan_mode=scan_mode,
                public=True,
            ))

        # GET /api/v1/records/canonical-index
        elif path == "/api/v1/records/canonical-index":
            _sys_api.path.insert(0, str(MEMCORE_ROOT) + "/src")
            full_parsed = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(full_parsed.query)
            try:
                limit = int((q.get("limit") or ["20"])[0])
            except Exception:
                limit = 20
            source_system = str((q.get("source_system") or [""])[0]).strip()
            session_id = str((q.get("session_id") or [""])[0]).strip()
            query = str((q.get("q") or q.get("query") or [""])[0]).strip()
            from raw_record_guardian import query_records_index
            self.send_json(query_records_index(
                source_system=source_system,
                session_id=session_id,
                query=query,
                limit=limit,
                public=True,
            ))

        # GET /api/v1/records/doctor - one-click record-chain self-check
        elif path == "/api/v1/records/doctor":
            full_parsed = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(full_parsed.query)
            try:
                limit = int((q.get("limit") or ["20"])[0])
            except Exception:
                limit = 20
            requested_mode = str((q.get("mode") or q.get("scan") or ["fast"])[0]).lower()
            scan_mode = "full" if requested_mode in {"full", "deep"} else "fast"
            self.send_json(build_record_doctor(
                limit=limit,
                scan_mode=scan_mode,
                public=True,
            ))

        # GET /api/v1/records/timeline - source/raw/index record chain
        elif path == "/api/v1/records/timeline":
            full_parsed = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(full_parsed.query)
            try:
                limit = int((q.get("limit") or ["20"])[0])
            except Exception:
                limit = 20
            requested_mode = str((q.get("mode") or q.get("scan") or ["fast"])[0]).lower()
            scan_mode = "full" if requested_mode in {"full", "deep"} else "fast"
            self.send_json(build_record_chain_timeline(
                source_system=str((q.get("source_system") or [""])[0]).strip(),
                session_id=str((q.get("session_id") or [""])[0]).strip(),
                query=str((q.get("q") or q.get("query") or [""])[0]).strip(),
                limit=limit,
                scan_mode=scan_mode,
                public=True,
            ))

        # GET /api/v1/records/replay - session replay as a record chain
        elif path == "/api/v1/records/replay":
            full_parsed = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(full_parsed.query)
            try:
                limit = int((q.get("limit") or ["50"])[0])
            except Exception:
                limit = 50
            requested_mode = str((q.get("mode") or q.get("scan") or ["fast"])[0]).lower()
            scan_mode = "full" if requested_mode in {"full", "deep"} else "fast"
            self.send_json(build_record_chain_replay(
                source_system=str((q.get("source_system") or [""])[0]).strip(),
                session_id=str((q.get("session_id") or [""])[0]).strip(),
                limit=limit,
                scan_mode=scan_mode,
                public=True,
            ))

        # GET /api/v1/source-systems/kiro/status
        elif path == "/api/v1/source-systems/kiro/status":
            _sys_api.path.insert(0, str(MEMCORE_ROOT) + "/src")
            from kiro_local_connector import status as kiro_status
            self.send_json(kiro_status())

        # GET /api/v1/release/status - 版本状态
        elif path == "/api/v1/release/status":
            version_path = f"{MEMCORE_ROOT}/VERSION"
            latest_path = f"{MEMCORE_ROOT}/release/latest.json"
            version = "unknown"
            if os.path.exists(version_path):
                with open(version_path) as f:
                    version = f.read().strip()
            latest_info = {}
            if os.path.exists(latest_path):
                with open(latest_path) as f:
                    latest_info = json.load(f)
            self.send_json({
                "current_version": version,
                "latest": latest_info.get("latest_version", version),
                "release_catalog": latest_info,
            })

        # GET /api/v1/diagnostics - 诊断索引（轻量版，不加载全部zhiyi对象）
        elif path == "/api/v1/diagnostics":
            import socket
            diag = {
                "watcher": get_watcher_status(),
                "watcher_detail": get_watcher_status_detail(),
                "raw_memory": get_raw_stats(),
                "zhiyi_stats": get_zhiyi_stats(),
                "health": {
                    "p0raw": {"status": "passed", "detail": str(get_raw_stats().get("sessions", 0)) + " sessions"},
                    "p0watcher": {"status": "passed" if get_watcher_status() else "failed", "detail": "memcore-cloud.service"},
                },
            }
            # Quick port checks
            ports = {}
            for svc_name, port in [("p3recall", INTERNAL_P3_PORT), ("p4provider", INTERNAL_P4_PORT)]:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(2)
                r = sock.connect_ex(("127.0.0.1", port))
                sock.close()
                ports[svc_name] = "passed" if r == 0 else "failed"
            diag["health"]["p3recall"] = {"status": ports.get("p3recall", "failed")}
            diag["health"]["p4provider"] = {"status": ports.get("p4provider", "failed")}
            try:
                from source_system_registry import list_source_systems
                diag["source_systems"] = list_source_systems()
            except:
                diag["source_systems"] = []
            self.send_json(diag)

        # GET /api/v1/update/status - 更新状态（C2: GitHub source 检测）
        elif path == "/api/v1/update/status":
            import update_source as _upd_src
            version_path = f"{MEMCORE_ROOT}/VERSION"
            current = "unknown"
            if os.path.exists(version_path):
                with open(version_path) as f:
                    current = f.read().strip()
            # C2: Check remote version from GitHub/source
            remote_info = _upd_src.check_remote_version()
            latest_version = ""
            metadata_source = ""
            update_available = None
            remote_error = None
            check_ok = bool(remote_info.get("ok"))
            if remote_info.get("ok"):
                latest_version = remote_info["latest_version"]
                metadata_source = remote_info["metadata_source"]
                update_available = _upd_src.compare_versions(current, latest_version) < 0
            elif remote_info.get("error"):
                remote_error = remote_info["error"]
                metadata_source = remote_info.get("metadata_source", "error")
            self.send_json({
                "current_version": current,
                "latest_version": latest_version,
                "update_available": update_available,
                "check_ok": check_ok,
                "metadata_source": metadata_source,
                "remote_error": remote_error,
                "download_enabled": bool(check_ok and remote_info.get("archive_available", True)),
                "install_enabled": bool(check_ok and remote_info.get("archive_available", True)),
                "auto_apply": True,
                "one_click_supported": True,
                "apply_mode": "flat_install_apply",
                "preserves_user_data": True,
                "user_upload_required": False,
                "archive_url": remote_info.get("archive_url", "") if check_ok else "",
                "version_url": _upd_src._get_version_url(),
            })

        # GET /api/v1/update/source - 获取更新源配置
        elif path == "/api/v1/update/source":
            source_path = f"{MEMCORE_ROOT}/config/update_source.json"
            if os.path.exists(source_path):
                with open(source_path) as f:
                    self.send_json(json.load(f))
            else:
                self.send_json({"source_url": None, "type": "local"})


        # GET /api/v1/update/history - 更新历史
        elif path == "/api/v1/update/history":
            hist_path = f"{MEMCORE_ROOT}/update_history.jsonl"
            entries = []
            if os.path.exists(hist_path):
                with open(hist_path) as f:
                    for line in f:
                        if line.strip():
                            try:
                                entries.append(json.loads(line))
                            except:
                                pass
            self.send_json({"entries": entries[-10:], "total": len(entries)})

        # GET /api/v1/runtime/profile - 完整 profile
        elif path == "/api/v1/runtime/profile":
            _sys_api.path.insert(0, f"{MEMCORE_ROOT}")
            runtime_profile = _load_runtime_profile_module()
            mc = _safe_runtime_profile_part("memcore_cloud", runtime_profile.build_memcore_profile)
            oc = _safe_runtime_profile_part("openclaw", runtime_profile.build_openclaw_profile)
            hm = _safe_runtime_profile_part("hermes", runtime_profile.build_hermes_profile)
            cd = _safe_runtime_profile_part("claude_desktop", runtime_profile.build_claude_desktop_profile)
            summary = _safe_runtime_profile_part("instances_summary", runtime_profile.build_instances_summary)
            oc_detected = oc.get("health", {}).get("reachable", False) or bool(oc.get("running_instance"))
            hm_detected = hm.get("health", {}).get("reachable", False) or bool(hm.get("running_instance"))
            cd_detected = cd.get("status") in ("active", "detected")
            self.send_json({
                "generated_at": runtime_profile.ts(),
                "memcore_cloud": mc,
                "openclaw": oc,
                "hermes": hm,
                "claude_desktop": cd,
                "instances_summary": {
                    **summary,
                    "openclaw_detected": oc_detected,
                    "hermes_detected": hm_detected,
                    "claude_desktop_detected": cd_detected,
                    "detected_count": (1 if oc_detected else 0) + (1 if hm_detected else 0) + (1 if cd_detected else 0),
                },
            })

        # GET /api/v1/runtime/profile/memcore-cloud
        elif path == "/api/v1/runtime/profile/memcore-cloud":
            _sys_api.path.insert(0, f"{MEMCORE_ROOT}")
            runtime_profile = _load_runtime_profile_module()
            self.send_json({"generated_at": runtime_profile.ts(), **runtime_profile.build_memcore_profile()})

        # GET /api/v1/runtime/profile/openclaw
        elif path == "/api/v1/runtime/profile/openclaw":
            _sys_api.path.insert(0, f"{MEMCORE_ROOT}")
            runtime_profile = _load_runtime_profile_module()
            self.send_json({"generated_at": runtime_profile.ts(), **runtime_profile.build_openclaw_profile()})

        # GET /api/v1/runtime/profile/instances
        elif path == "/api/v1/runtime/profile/instances":
            _sys_api.path.insert(0, f"{MEMCORE_ROOT}")
            runtime_profile = _load_runtime_profile_module()
            summary = runtime_profile.build_instances_summary()
            self.send_json({"generated_at": runtime_profile.ts(), **_public_runtime_profile_instances(summary)})

        # GET /api/v1/runtime/profile/version-compatibility
        elif path == "/api/v1/runtime/profile/version-compatibility":
            _sys_api.path.insert(0, f"{MEMCORE_ROOT}")
            runtime_profile = _load_runtime_profile_module()
            mc = runtime_profile.build_memcore_profile()
            oc = runtime_profile.build_openclaw_profile()
            self.send_json({
                "generated_at": runtime_profile.ts(),
                "memcore_cloud": {
                    "selected_runtime": mc.get("selected_runtime"),
                    "version_mismatches": mc.get("version_mismatches", []),
                    "stale_instances": mc.get("stale_instances", []),
                },
                "openclaw": {
                    "selected_runtime": oc.get("selected_runtime"),
                    "version_mismatches": oc.get("version_mismatches", []),
                    "stale_instances": oc.get("stale_instances", []),
                },
            })

        # GET /api/v1/runtime/profile/hermes - Hermes 只读探测（experimental）
        elif path == "/api/v1/runtime/profile/hermes":
            _sys_api.path.insert(0, f"{MEMCORE_ROOT}")
            runtime_profile = _load_runtime_profile_module()
            self.send_json({"generated_at": runtime_profile.ts(), **runtime_profile.build_hermes_profile()})

        # GET /api/v1/platforms/autodiscovery - read-only Tiandao thin-adapter discovery
        elif path == "/api/v1/platforms/autodiscovery":
            _sys_api.path.insert(0, str(MEMCORE_ROOT) + "/src")
            full_parsed = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(full_parsed.query)
            include_generic = str((q.get("scan") or q.get("mode") or [""])[0]).lower() in {"full", "deep"}
            from platform_autodiscovery import build_autodiscovery
            self.send_json(build_autodiscovery(include_generic=include_generic))

        # GET /api/v1/platforms/thin-adapter-registry - read-only platform target registry
        elif path == "/api/v1/platforms/thin-adapter-registry":
            _sys_api.path.insert(0, str(MEMCORE_ROOT) + "/src")
            full_parsed = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(full_parsed.query)
            include_generic = str((q.get("scan") or q.get("mode") or [""])[0]).lower() in {"full", "deep"}
            from platform_thin_adapter_registry import build_thin_adapter_registry
            self.send_json(build_thin_adapter_registry(include_generic=include_generic))

        # GET /api/v1/platforms/discovery-dashboard - dashboard-friendly safe next steps
        elif path == "/api/v1/platforms/discovery-dashboard":
            _sys_api.path.insert(0, str(MEMCORE_ROOT) + "/src")
            full_parsed = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(full_parsed.query)
            include_generic = str((q.get("scan") or q.get("mode") or [""])[0]).lower() in {"full", "deep"}
            internal_view = str((q.get("view") or [""])[0]).lower() in {"internal", "debug", "full"}
            from platform_thin_adapter_registry import build_platform_discovery_dashboard
            self.send_json(build_platform_discovery_dashboard(
                include_generic=include_generic,
                public=not internal_view,
            ))

        # GET /api/v1/platforms/catalog - local AI tool discovery catalog
        elif path == "/api/v1/platforms/catalog":
            _sys_api.path.insert(0, str(MEMCORE_ROOT) + "/src")
            from platform_thin_adapter_registry import load_platform_catalog
            self.send_json(load_platform_catalog())

        # GET /api/v1/platforms/package-manager-inventory - read-only npm/pipx/brew/docker agent radar
        elif path == "/api/v1/platforms/package-manager-inventory":
            _sys_api.path.insert(0, str(MEMCORE_ROOT) + "/src")
            full_parsed = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(full_parsed.query)
            scan_mode = "full" if str((q.get("scan") or q.get("mode") or [""])[0]).lower() in {"full", "deep"} else "fast"
            from platform_thin_adapter_registry import build_package_manager_agent_inventory
            self.send_json(build_package_manager_agent_inventory(scan_mode=scan_mode))

        # GET /api/v1/raw/archive-layout - preferred computer/source/native raw folder contract
        elif path == "/api/v1/raw/archive-layout":
            _sys_api.path.insert(0, str(MEMCORE_ROOT) + "/src")
            from raw_archive_layout import layout_descriptor
            self.send_json(layout_descriptor())

        # GET /api/v1/raw/archive-layout/audit - read-only current-vs-legacy raw layout audit
        elif path == "/api/v1/raw/archive-layout/audit":
            _sys_api.path.insert(0, str(MEMCORE_ROOT) + "/src")
            from raw_archive_layout import audit_raw_archive_layout
            self.send_json(audit_raw_archive_layout(os.path.join(str(MEMCORE_ROOT), "memory")))

        # GET /api/v1/platforms/generic-local-ai-surfaces - read-only generic MCP/config scan
        elif path == "/api/v1/platforms/generic-local-ai-surfaces":
            _sys_api.path.insert(0, str(MEMCORE_ROOT) + "/src")
            full_parsed = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(full_parsed.query)
            scan_mode = str((q.get("scan") or q.get("mode") or [""])[0]).lower()
            from platform_thin_adapter_registry import build_generic_local_ai_surfaces, build_generic_local_ai_surfaces_snapshot, public_tool_discovery_payload
            heavy_scan_requested = scan_mode in {"full", "deep", "smart"}
            self.send_json(public_tool_discovery_payload(
                build_generic_local_ai_surfaces(scan_mode=scan_mode)
                if heavy_scan_requested
                else build_generic_local_ai_surfaces_snapshot()
            ))

        # GET /api/v1/platforms/model-identification - model-assisted local tool recognition
        elif path == "/api/v1/platforms/model-identification":
            _sys_api.path.insert(0, str(MEMCORE_ROOT) + "/src")
            full_parsed = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(full_parsed.query)
            scan_mode = str((q.get("scan") or q.get("mode") or [""])[0]).lower()
            include_generic = scan_mode in {"full", "deep", "smart"}
            execute = str((q.get("execute") or q.get("run") or [""])[0]).lower() in {"1", "true", "yes"}
            model_limit_raw = str((q.get("model_limit") or q.get("limit") or [""])[0]).strip()
            model_limit = int(model_limit_raw) if model_limit_raw.isdigit() else None
            from platform_thin_adapter_registry import build_model_identification_report, public_tool_discovery_payload
            self.send_json(public_tool_discovery_payload(build_model_identification_report(
                include_generic=include_generic,
                execute=execute,
                scan_mode=scan_mode or "fast_snapshot",
                model_execute_limit=model_limit,
            )))

        # GET /api/v1/platforms/provisional-adapter-candidates - recognized local tools as adapter candidates
        elif path == "/api/v1/platforms/provisional-adapter-candidates":
            _sys_api.path.insert(0, str(MEMCORE_ROOT) + "/src")
            full_parsed = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(full_parsed.query)
            scan_mode = str((q.get("scan") or q.get("mode") or [""])[0]).lower()
            include_generic = scan_mode in {"full", "deep", "smart"}
            execute = str((q.get("execute") or q.get("run") or [""])[0]).lower() in {"1", "true", "yes"}
            model_limit_raw = str((q.get("model_limit") or q.get("limit") or [""])[0]).strip()
            model_limit = int(model_limit_raw) if model_limit_raw.isdigit() else None
            from platform_thin_adapter_registry import build_provisional_adapter_candidates_report, public_tool_discovery_payload
            self.send_json(public_tool_discovery_payload(build_provisional_adapter_candidates_report(
                include_generic=include_generic,
                execute=execute,
                scan_mode=scan_mode or "fast_snapshot",
                model_execute_limit=model_limit,
            )))

        # GET /api/v1/platforms/authorized-auto-connect/dry-run - detailed preflight, no writes
        elif path == "/api/v1/platforms/authorized-auto-connect/dry-run":
            _sys_api.path.insert(0, str(MEMCORE_ROOT) + "/src")
            full_parsed = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(full_parsed.query)
            include_generic = str((q.get("scan") or q.get("mode") or [""])[0]).lower() in {"full", "deep"}
            from platform_thin_adapter_registry import build_authorized_auto_connect_dry_run
            self.send_json(build_authorized_auto_connect_dry_run(include_generic=include_generic))

        # GET /api/v1/platforms/{system}/authorized-connect-plan - single platform preflight
        elif path.startswith("/api/v1/platforms/") and path.endswith("/authorized-connect-plan"):
            system_id = path.split("/api/v1/platforms/")[1].replace("/authorized-connect-plan", "")
            _sys_api.path.insert(0, str(MEMCORE_ROOT) + "/src")
            full_parsed = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(full_parsed.query)
            include_generic = str((q.get("scan") or q.get("mode") or [""])[0]).lower() in {"full", "deep"}
            from platform_thin_adapter_registry import build_authorized_auto_connect_dry_run
            result = build_authorized_auto_connect_dry_run(
                system=urllib.parse.unquote(system_id),
                include_generic=include_generic,
            )
            self.send_json(result, 200 if result.get("ok") else 404)

        # GET /api/v1/platforms/authorized-auto-connect/plan - plan only, no platform writes
        elif path == "/api/v1/platforms/authorized-auto-connect/plan":
            _sys_api.path.insert(0, str(MEMCORE_ROOT) + "/src")
            from platform_autodiscovery import build_authorized_autoconnect_plan
            self.send_json(build_authorized_autoconnect_plan())

        # GET /api/v1/platforms/agent-entrypoints/preview - read-only native instruction previews
        elif path == "/api/v1/platforms/agent-entrypoints/preview":
            _sys_api.path.insert(0, str(MEMCORE_ROOT) + "/src")
            full_parsed = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(full_parsed.query)
            project_root = str((q.get("project_root") or q.get("root") or [""])[0]).strip() or None
            include_content = str((q.get("include_content") or ["true"])[0]).lower() not in {"0", "false", "no"}
            from platform_native_entrypoints import build_agent_native_entrypoints_preview
            self.send_json(build_agent_native_entrypoints_preview(
                project_root=project_root,
                include_content=include_content,
            ))

        # GET /api/v1/platforms/agent-event-triggers/preview - read-only automatic reminder moments
        elif path == "/api/v1/platforms/agent-event-triggers/preview":
            _sys_api.path.insert(0, str(MEMCORE_ROOT) + "/src")
            full_parsed = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(full_parsed.query)
            project_root = str((q.get("project_root") or q.get("root") or [""])[0]).strip() or None
            from platform_event_triggers import build_agent_event_triggers_preview
            self.send_json(build_agent_event_triggers_preview(project_root=project_root))

        else:
            self.send_error(404)

    def do_POST(self):
        if self.reject_unsafe_post():
            return
        parsed_post_path = urllib.parse.urlparse(self.path).path
        if self.reject_unsafe_action_post(parsed_post_path):
            return
        import sys as _sys
        import urllib.parse as _urlparse_post
        _sys.path.insert(0, f"{MEMCORE_ROOT}")
        _sys.path.insert(0, f"{MEMCORE_ROOT}/src")
        import importlib

        if self.path == "/api/recall":
            import p3_recall
            importlib.reload(p3_recall)
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            result = p3_recall.handle_recall(body)
            self.send_json(result)

        elif self.path == "/api/v1/zhiyi/test-query":
            import p3_recall
            importlib.reload(p3_recall)
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            result = p3_recall.handle_recall(body)
            self.send_json(result)

        elif parsed_post_path == "/api/v1/console/tasks":
            body, body_error = self.read_json_body()
            if body_error:
                self.send_json(body_error, 400)
                return
            result = add_console_task(body)
            self.send_json(result, 200 if result.get("ok") else 400)

        elif parsed_post_path == "/api/v1/console/tasks/delete":
            body, body_error = self.read_json_body()
            if body_error:
                self.send_json(body_error, 400)
                return
            result = delete_console_task(body)
            self.send_json(result, 200 if result.get("ok") else 400)

        elif parsed_post_path == "/api/v1/console/notes":
            body, body_error = self.read_json_body()
            if body_error:
                self.send_json(body_error, 400)
                return
            result = add_console_note(body)
            self.send_json(result, 200 if result.get("ok") else 400)

        elif parsed_post_path == "/api/v1/console/notes/delete":
            body, body_error = self.read_json_body()
            if body_error:
                self.send_json(body_error, 400)
                return
            result = delete_console_note(body)
            self.send_json(result, 200 if result.get("ok") else 400)

        elif parsed_post_path == "/api/v1/console/projects":
            body, body_error = self.read_json_body()
            if body_error:
                self.send_json(body_error, 400)
                return
            result = add_console_project(body)
            self.send_json(result, 200 if result.get("ok") else 400)

        elif parsed_post_path == "/api/v1/console/projects/delete":
            body, body_error = self.read_json_body()
            if body_error:
                self.send_json(body_error, 400)
                return
            result = delete_console_project(body)
            self.send_json(result, 200 if result.get("ok") else 400)

        elif parsed_post_path == "/api/v1/productized-loops/doctor":
            body, body_error = self.read_json_body()
            if body_error:
                self.send_json(body_error, 400)
                return
            result = build_productized_loops_doctor(body, memcore_root=str(MEMCORE_ROOT))
            self.send_json(result, 200 if result.get("ok") else 400)

        elif parsed_post_path == "/api/v1/preflight-doctor":
            body, body_error = self.read_json_body()
            if body_error:
                self.send_json(body_error, 400)
                return
            body.setdefault("diagnostic_profile", "smoke")
            result = build_preflight_doctor(body, memcore_root=str(MEMCORE_ROOT))
            self.send_json(result, 200 if result.get("ok") else 400)

        elif self.path == "/api/v1/source-systems/claude_desktop/raw-ingest/dry-run":
            from claude_desktop_connector import raw_ingest_dry_run
            body, body_error = self.read_json_body()
            if body_error:
                self.send_json(body_error, 400)
                return
            result = raw_ingest_dry_run(body, public=True)
            self.send_json(result, 200 if result.get("ok") else 400)

        elif self.path == "/api/v1/source-systems/claude_desktop/raw-ingest":
            from claude_desktop_connector import ingest_authorized_raw
            body, body_error = self.read_json_body()
            if body_error:
                self.send_json(body_error, 400)
                return
            result = ingest_authorized_raw(body, public=True)
            self.send_json(result, 200 if result.get("ok") else 400)

        elif self.path == "/api/v1/records/guardian/backfill":
            from raw_record_guardian import run_raw_backfill
            body, body_error = self.read_json_body()
            if body_error:
                self.send_json(body_error, 400)
                return
            try:
                limit = int(body.get("limit") or 20)
            except Exception:
                limit = 20
            raw_sources = body.get("source_systems")
            source_systems = [
                str(item).strip()
                for item in raw_sources
                if str(item).strip()
            ] if isinstance(raw_sources, list) else None
            raw_targets = body.get("target_raw_paths")
            target_raw_paths = [
                str(item).strip()
                for item in raw_targets
                if str(item).strip()
            ] if isinstance(raw_targets, list) else None
            result = run_raw_backfill(
                limit=max(1, min(limit, 200)),
                source_systems=source_systems,
                target_raw_paths=target_raw_paths,
            )
            self.send_json(result, 200 if result.get("ok") else 400)

        elif self.path == "/api/v1/platforms/authorized-auto-connect/apply-gate/dry-run":
            from platform_thin_adapter_registry import build_authorized_auto_connect_apply_gate_dry_run
            body, body_error = self.read_json_body()
            if body_error:
                self.send_json(body_error, 400)
                return
            result = build_authorized_auto_connect_apply_gate_dry_run(body)
            self.send_json(result, 200 if result.get("ok") else 400)

        elif self.path == "/api/v1/platforms/authorized-auto-connect/apply":
            from pathlib import Path as _PathPost
            from platform_thin_adapter_registry import apply_authorized_auto_connect
            body, body_error = self.read_json_body()
            if body_error:
                self.send_json(body_error, 400)
                return
            result = apply_authorized_auto_connect(body, memcore_root=_PathPost(str(MEMCORE_ROOT)))
            self.send_json(result, 200 if result.get("ok") else 400)

        elif _urlparse_post.urlparse(self.path).path.startswith("/api/v1/zhiyi/experiences/") and _urlparse_post.urlparse(self.path).path.endswith("/recycle"):
            path = _urlparse_post.urlparse(self.path).path
            exp_id = path[len("/api/v1/zhiyi/experiences/"):-len("/recycle")]
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            result = recycle_zhiyi_experience(_urlparse_post.unquote(exp_id), body)
            if result.get("ok"):
                self.send_json(result)
            else:
                self.send_json(result, 400 if result.get("error") == "invalid_exp_id" else 404)

        elif _urlparse_post.urlparse(self.path).path.startswith("/api/v1/zhiyi/experiences/") and _urlparse_post.urlparse(self.path).path.endswith("/restore"):
            path = _urlparse_post.urlparse(self.path).path
            exp_id = path[len("/api/v1/zhiyi/experiences/"):-len("/restore")]
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            result = restore_zhiyi_experience(_urlparse_post.unquote(exp_id), body)
            if result.get("ok"):
                self.send_json(result)
            else:
                self.send_json(result, 400 if result.get("error") == "invalid_exp_id" else 404)

        # ── P1-5 Zhiyi model binding dry-run (no config/profile write) ──
        elif self.path == "/api/v1/zhiyi/model-binding/dry-run":
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            self.send_json(build_zhiyi_model_binding_plan(body))

        elif self.path == "/api/v1/zhiyi/model-binding/apply":
            body, body_error = self.read_json_body()
            if body_error:
                self.send_json(body_error, 400)
                return
            result = apply_zhiyi_model_binding_user_default(body)
            self.send_json(result, 200 if result.get("ok") else 400)

        elif self.path == "/api/v1/zhiyi/model-connection/smoke":
            body, body_error = self.read_json_body()
            if body_error:
                self.send_json(body_error, 400)
                return
            result = run_model_connection_smoke(body)
            self.send_json(result, 200 if result.get("ok") else 400)

        # ── P1-9 Zhiyi model binding apply authorization gate (no config write) ──
        elif self.path == "/api/v1/zhiyi/model-binding/apply-gate/dry-run":
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            self.send_json(build_zhiyi_model_binding_apply_gate_dry_run(body))

        # ── P1-10 Zhiyi runtime adapter preflight contract (no model call/config write) ──
        elif self.path == "/api/v1/zhiyi/runtime-adapter/dry-run":
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            self.send_json(build_zhiyi_runtime_adapter_dry_run(body))

        # ── P1-11 Zhiyi runtime adapter apply gate + read-only client resolver ──
        elif self.path == "/api/v1/zhiyi/runtime-adapter/apply-gate/dry-run":
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            self.send_json(build_zhiyi_runtime_adapter_apply_gate_dry_run(body))

        # ── Zhixing toolbook candidate dry-run: no raw/toolbook write ──
        elif self.path == "/api/v1/zhixing/toolbook-candidates/dry-run":
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            result = build_toolbook_candidate(body)
            self.send_json(result, 200 if result.get("ok") else 400)

        # ── Zhixing toolbook candidate validator: validates supplied candidate only ──
        elif self.path == "/api/v1/zhixing/toolbook-candidates/validate":
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            candidate = body.get("candidate") if isinstance(body.get("candidate"), dict) else body
            result = validate_toolbook_candidate(candidate)
            self.send_json(result, 200 if result.get("ok") else 400)

        # ── Zhixing library dry-run routes: all read-only previews ──
        elif p6_zhixing_routes.send_dry_run_if_matched(self, self.path):
            pass

        # ── Dialog fine-grained intent route: read-only, no recall/write ──
        elif self.path == "/api/v1/dialog/intent-route/dry-run":
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            message = body.get("message") or body.get("text") or body.get("query") or ""
            self.send_json(classify_fine_intent(message))

        # ── Zhiyi natural-language correction candidate: dry-run only ──
        elif self.path == "/api/v1/zhiyi/errata-candidates/dry-run":
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            result = build_zhiyi_errata_candidate(body)
            self.send_json(result, 200 if result.get("ok") else 400)

        # ── Zhixing external/prior method signal candidate: dry-run only ──
        elif self.path == "/api/v1/zhixing/method-signals/dry-run":
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            result = build_method_signal_candidate(body)
            self.send_json(result, 200 if result.get("ok") else 400)

        # ── Zhixing State Ledger / Temporal Index dry-run: no memory writes ──
        elif self.path == "/api/v1/zhixing/state-ledger/dry-run":
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            result = build_state_ledger_snapshot(body)
            self.send_json(result, 200 if result.get("ok") else 400)

        # ── Zhixing Context Budget Unit candidate: dry-run only ──
        elif self.path == "/api/v1/zhixing/context-units/dry-run":
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            result = build_context_budget_unit_candidate(body)
            self.send_json(result, 200 if result.get("ok") else 400)

        # ── External documentation evidence dry-run: no network/raw/platform write ──
        elif self.path == "/api/v1/zhixing/external-docs-evidence/dry-run":
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            result = build_external_docs_evidence_dry_run(body)
            self.send_json(result, 200 if result.get("ok") else 400)

        # ── Context delivery compaction dry-run: no raw/cache/platform write ──
        elif self.path == "/api/v1/zhixing/context-delivery-compaction/dry-run":
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            result = build_context_delivery_compaction_dry_run(body)
            self.send_json(result, 200 if result.get("ok") else 400)

        # ── Time river sediment dry-run: link derived memory to raw origin only ──
        elif self.path == "/api/v1/tiandao/time-river-sediment/dry-run":
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            result = build_time_river_sediment_dry_run(body)
            self.send_json(result, 200 if result.get("ok") else 400)

        # ── Material processing pipeline dry-run: no raw or memory writes ──
        elif self.path == "/api/v1/zhixing/material-processing-pipeline/dry-run":
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            result = build_material_processing_pipeline_dry_run(body)
            self.send_json(result, 200 if result.get("ok") else 400)

        # ── Second Brain dry-run: orchestrates candidates, no durable writes ──
        elif self.path == "/api/v1/tiandao/second-brain/dry-run":
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            result = build_second_brain_dry_run(body)
            self.send_json(result, 200 if result.get("ok") else 400)

        # ── Hermes self-review wake signal dry-run: signal only, no Hermes write ──
        elif self.path == "/api/v1/hermes/native-learning/self-review/wake/dry-run":
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            result = build_hermes_self_review_wake_http_dry_run(body)
            self.send_json(result, 200 if result.get("ok") else 400)

        # ── Hermes self-review signal receipt: records Time Library receipt only ──
        elif self.path == "/api/v1/hermes/native-learning/self-review/receipts":
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            result = apply_hermes_self_review_signal_receipt_http(body)
            self.send_json(result, 200 if result.get("ok") else 400)

        # ── Hermes self-review live trigger: explicit authorization required ──
        elif self.path == "/api/v1/hermes/native-learning/self-review/trigger":
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            result = apply_hermes_self_review_trigger_http(body)
            self.send_json(result, 200 if result.get("ok") else 400)

        # ── Hermes native skill generation probe: explicit authorization required ──
        elif self.path == "/api/v1/hermes/native-learning/skill-generation/probe":
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            result = apply_hermes_skill_generation_probe_http(body)
            self.send_json(result, 200 if result.get("ok") else 400)

        # ── Hermes native skill generation probe dry-run: no Hermes call ──
        elif self.path == "/api/v1/hermes/native-learning/skill-generation/probe/dry-run":
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            result = build_hermes_skill_generation_probe_http_dry_run(body)
            self.send_json(result, 200 if result.get("ok") else 400)

        # ── Hermes skill artifact status: record review-only status artifact ──
        elif self.path == "/api/v1/hermes/native-learning/skill-artifact-status/record":
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            result = record_hermes_skill_artifact_status_http(body)
            self.send_json(result, 200 if result.get("ok") else 400)

        # ── Hermes skill artifact status dry-run: no writes ──
        elif self.path == "/api/v1/hermes/native-learning/skill-artifact-status/dry-run":
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            result = build_hermes_skill_artifact_status_http_dry_run(body)
            self.send_json(result, 200 if result.get("ok") else 400)

        # ── Hermes autonomous loop run-once: value-gated, explicit authorization required ──
        elif self.path == "/api/v1/hermes/native-learning/autonomous-loop/run":
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            result = apply_hermes_autonomous_loop_http(body)
            self.send_json(result, 200 if result.get("ok") else 400)

        # ── Hermes autonomous loop dry-run: no Hermes call ──
        elif self.path == "/api/v1/hermes/native-learning/autonomous-loop/run/dry-run":
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            result = build_hermes_autonomous_loop_http_dry_run(body)
            self.send_json(result, 200 if result.get("ok") else 400)

        # ── Hermes self-review report: record review-only candidate + upgrade input ──
        elif self.path == "/api/v1/hermes/native-learning/self-review/report/record":
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            result = record_hermes_self_review_report_candidate(body, memcore_root=str(MEMCORE_ROOT))
            self.send_json(result, 200 if result.get("ok") else 400)

        # ── Hermes self-review report: dry-run candidate extraction, no writes ──
        elif self.path == "/api/v1/hermes/native-learning/self-review/report/dry-run":
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            result = build_hermes_self_review_report_dry_run(body, memcore_root=str(MEMCORE_ROOT))
            self.send_json(result, 200 if result.get("ok") else 400)

        # ── Runtime runnable doctor: explicit smoke, no platform config write ──
        elif self.path == "/api/v1/model-facts/runnable-doctor/smoke":
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            result = build_model_runnable_doctor_smoke(body)
            self.send_json(result, 200 if result.get("ok") else 400)

        # ── Hermes skill vs experience diff: read-only candidate generation ──
        elif self.path == "/api/v1/hermes/skill-experience-diff/dry-run":
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            result = build_hermes_skill_experience_diff_dry_run(
                body,
                memcore_root=str(MEMCORE_ROOT),
            )
            self.send_json(result, 200 if result.get("ok") else 400)

        # ── Hermes consumption receipt from MemoryProvider.sync_turn ──
        elif self.path == "/api/v1/hermes/consumption-receipts":
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            result = persist_hermes_consumption_receipt(body)
            self.send_json(result, 200 if result.get("ok") else 400)

        # ── Zhixing replay dry-run: deterministic evaluation, no model/platform write ──
        elif self.path == "/api/v1/zhixing/replay/dry-run":
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            self.send_json(run_replay_dry_run(body))

        # ── Zhixing benchmark dry-run: multi-case deterministic evaluation, no writes ──
        elif self.path == "/api/v1/zhixing/benchmark/dry-run":
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            self.send_json(run_benchmark_dry_run(body))

        # ── Zhixing replay feedback application: receipt only, no production write ──
        elif self.path == "/api/v1/zhixing/replay/feedback-candidates/apply":
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            result = apply_zhixing_replay_feedback_candidate(body)
            self.send_json(result, 200 if result.get("ok") else 400)

        # ── P1-12 Zhiyi model request envelope + no-call adapter response ──
        elif self.path == "/api/v1/zhiyi/model-request/envelope/dry-run":
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            self.send_json(build_zhiyi_model_request_envelope_dry_run(body))

        # ── P1-6 Zhiyi usage log dry-run (no log append) ──
        elif self.path == "/api/v1/zhiyi/usage-log/dry-run":
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            self.send_json(build_zhiyi_usage_log_dry_run(body))

        # ── P1-6b Zhiyi usage light prompt classifier (no log append) ──
        elif self.path == "/api/v1/zhiyi/usage-log/light-prompts/classify/dry-run":
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            self.send_json(build_zhiyi_usage_light_prompt(body))

        # ── P1-7 Zhiyi usage log persistence artifact (no log append) ──
        elif self.path == "/api/v1/zhiyi/usage-log/persist/dry-run":
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            self.send_json(build_zhiyi_usage_log_persist_dry_run(body))

        # ── P1-8 Zhiyi usage log apply authorization gate (no log append) ──
        elif self.path == "/api/v1/zhiyi/usage-log/apply-gate/dry-run":
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            self.send_json(build_zhiyi_usage_log_apply_gate_dry_run(body))

        # ── P1-1 Experience Frontstage Actions (backend proposal, no localStorage) ──
        elif self.path == "/api/v1/zhiyi/experience-actions/dry-run":
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            result = m5_create_experience_action(body)
            if "error" in result:
                self.send_error(400)
            else:
                self.send_json(result)

        # ── B74 OpenClaw chat.send live authorization gate ──
        elif self.path == "/api/v1/openclaw/chat-send/authorized":
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            result = apply_openclaw_chat_send_authorized(body)
            self.send_json(result, 200 if result.get("ok") else 400)

        # ── B71 Hermes feedback candidate live lifecycle action receipt ──
        elif self.path.startswith("/api/v1/hermes/feedback-candidates/") and self.path.endswith("/actions"):
            import urllib.parse as _urlparse_post
            candidate_id = self.path.split("/api/v1/hermes/feedback-candidates/")[1].rsplit("/actions", 1)[0]
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            result = apply_hermes_feedback_candidate_action(_urlparse_post.unquote(candidate_id), body)
            if result.get("ok"):
                self.send_json(result)
            else:
                self.send_json(result, 400)

        # ── B101 Xingce work-experience candidate live lifecycle action receipt ──
        elif self.path.startswith("/api/v1/xingce/work-experience-candidates/") and self.path.endswith("/actions"):
            import urllib.parse as _urlparse_post
            candidate_id = self.path.split("/api/v1/xingce/work-experience-candidates/")[1].rsplit("/actions", 1)[0]
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            result = apply_xingce_work_experience_candidate_action(_urlparse_post.unquote(candidate_id), body)
            if result.get("ok"):
                self.send_json(result)
            else:
                self.send_json(result, 400)

        # ── B110 Experience service live adoption from Xingce candidate ──
        elif self.path.startswith("/api/v1/experience-service/xingce-candidates/") and self.path.endswith("/adopt"):
            import urllib.parse as _urlparse_post
            candidate_id = self.path.split("/api/v1/experience-service/xingce-candidates/")[1].rsplit("/adopt", 1)[0]
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            result = apply_experience_service_xingce_adoption(_urlparse_post.unquote(candidate_id), body)
            if result.get("ok"):
                self.send_json(result)
            else:
                self.send_json(result, 400)

        # ── B110 Experience service live rollback by lifecycle overlay ──
        elif self.path.startswith("/api/v1/experience-service/case-memories/") and self.path.endswith("/rollback"):
            import urllib.parse as _urlparse_post
            exp_id = self.path.split("/api/v1/experience-service/case-memories/")[1].rsplit("/rollback", 1)[0]
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            result = apply_experience_service_case_memory_rollback(_urlparse_post.unquote(exp_id), body)
            if result.get("ok"):
                self.send_json(result)
            else:
                self.send_json(result, 400)

        # ── B111 Experience service semantic upgrade from Hermes upgrade input ──
        elif self.path.startswith("/api/v1/experience-service/hermes-upgrade-inputs/") and self.path.endswith("/apply"):
            import urllib.parse as _urlparse_post
            upgrade_input_id = self.path.split("/api/v1/experience-service/hermes-upgrade-inputs/")[1].rsplit("/apply", 1)[0]
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            result = apply_experience_service_hermes_upgrade_input(_urlparse_post.unquote(upgrade_input_id), body)
            if result.get("ok"):
                self.send_json(result)
            else:
                self.send_json(result, 400)

        # ── M6 Governance Proposal (dry-run only) ──
        elif self.path == "/api/v1/zhiyi/governance/proposals/dry-run":
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            result = m6_create_proposal(body)
            if "error" in result:
                self.send_error(400)
            else:
                self.send_json(result)

        elif self.path == "/api/v1/update/download":
            import update_source as _upd_src
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            result = _upd_src.download_update_archive(str(MEMCORE_ROOT))
            self.send_json(result)

        elif self.path == "/api/v1/update/one-click":
            import update_source as _upd_src
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            version_path = f"{MEMCORE_ROOT}/VERSION"
            current = "unknown"
            if os.path.exists(version_path):
                with open(version_path) as f:
                    current = f.read().strip()
            result = _upd_src.one_click_update(
                str(MEMCORE_ROOT),
                current,
                apply=body.get("apply", True),
                restart=body.get("restart", True),
            )
            self.send_json(result)

        elif self.path == "/api/v1/update/source":
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            source_url = body.get("source_url", "")
            source_type = body.get("type", "local")
            source_path = f"{MEMCORE_ROOT}/config/update_source.json"
            os.makedirs(os.path.dirname(source_path), exist_ok=True)
            with open(source_path, "w") as f:
                json.dump({"source_url": source_url, "type": source_type}, f, indent=2)
            self.send_json({"ok": True, "source_url": source_url, "type": source_type})


        elif self.path == "/api/v1/source-systems/local_files/ingest":
            from connectors.local_files_connector import ingest as lf_ingest
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            dry_run = body.get("dry_run", False)
            result = lf_ingest(dry_run=dry_run)
            self.send_json(result)

        elif self.path == "/api/v1/update/verify":
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            pkg_path = body.get("package_path") or f"{MEMCORE_ROOT}/release/time-library-{body.get('version', SERVICE_VERSION)}.zip"
            import hashlib
            result = {"path": pkg_path, "exists": os.path.exists(pkg_path)}
            if os.path.exists(pkg_path):
                with open(pkg_path, "rb") as f:
                    result["checksum"] = hashlib.sha256(f.read()).hexdigest()
                result["size"] = os.path.getsize(pkg_path)
                # Verify the release archive without extracting it.
                try:
                    if pkg_path.endswith(".zip"):
                        import zipfile
                        with zipfile.ZipFile(pkg_path) as archive:
                            names = archive.namelist()
                    else:
                        import tarfile
                        with tarfile.open(pkg_path) as archive:
                            names = archive.getnames()
                    result["valid_archive"] = True
                    result["entries"] = len(names)
                    result["sample_entries"] = names[:5]
                except Exception as e:
                    result["valid_archive"] = False
                    result["archive_error"] = str(e)[:100]
            self.send_json(result)

        elif self.path == "/api/v1/update/plan":
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            target_version = body.get("version") or SERVICE_VERSION
            pkg_path = body.get("package_path") or f"{MEMCORE_ROOT}/release/time-library-{target_version}.zip"
            install_root = body.get("install_root", "/opt/time-library")
            version_path = f"{MEMCORE_ROOT}/VERSION"
            current = "unknown"
            if os.path.exists(version_path):
                with open(version_path) as f:
                    current = f.read().strip()
            plan = {
                "from_version": current,
                "to_version": target_version,
                "package": pkg_path,
                "install_root": install_root,
                "steps": [
                    {"step": 1, "action": "backup", "target": f"{install_root}/src", "description": "备份当前安装"},
                    {"step": 2, "action": "verify", "target": pkg_path, "description": "校验包完整性"},
                    {"step": 3, "action": "extract", "target": install_root, "description": "解压到安装目录"},
                    {"step": 4, "action": "reload", "target": "memcore-cloud.service", "description": "重启服务"},
                ],
                "rollback_plan": [
                    {"step": 1, "action": "restore", "target": f"{install_root}/src.bak", "description": "恢复备份"},
                    {"step": 2, "action": "reload", "target": "memcore-cloud.service", "description": "重启服务"},
                ],
            }
            plan_path = f"{MEMCORE_ROOT}/release/update_plan.json"
            with open(plan_path, "w") as f:
                json.dump(plan, f, indent=2)
            self.send_json(plan)

        elif self.path == "/api/v1/update/apply-dry-run":
            # C1: Enhanced dry-run with full package validation
            from pathlib import Path
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            target_version = body.get("version", SERVICE_VERSION)
            pkg_path = body.get("package_path") or ""
            sandbox_root = body.get("sandbox_root", "").strip()
            install_root = body.get("install_root", sandbox_root) or sandbox_root
            if not pkg_path:
                self.send_json({"ok": False, "dry_run": True, "error": "package_path required", "steps": []})
                return
            if not install_root:
                self.send_json({"ok": False, "dry_run": True, "error": "install_root or sandbox_root required", "steps": []})
                return
            steps_log = []
            validation = {}
            try:
                # Step 1: Package existence
                if not os.path.exists(pkg_path):
                    steps_log.append({"step": 1, "status": "fail", "action": "check_exists", "reason": "package not found"})
                    self.send_json({"ok": False, "dry_run": True, "error": "package not found", "steps": steps_log})
                    return
                steps_log.append({"step": 1, "status": "pass", "action": "check_exists", "target": pkg_path})
                # Step 2: SHA256
                import hashlib
                with open(pkg_path, "rb") as f:
                    sha256 = hashlib.sha256(f.read()).hexdigest()
                steps_log.append({"step": 2, "status": "pass", "action": "sha256", "sha256": sha256[:16] + "..."})
                # Step 3: Package type and content validation
                is_tar = pkg_path.endswith(".tar.gz") or pkg_path.endswith(".tgz")
                is_zip = pkg_path.endswith(".zip")
                if not (is_tar or is_zip):
                    self.send_json({"ok": False, "dry_run": True, "error": "unsupported package type (only .zip or .tar.gz)", "steps": steps_log})
                    return
                forbidden_found = []
                top_dirs = set()
                file_count = 0
                if is_tar:
                    import tarfile
                    with tarfile.open(pkg_path, "r:gz") as tf:
                        names = tf.getnames()
                        file_count = len(names)
                        for n in names:
                            parts = n.replace("\\", "/").split("/")
                            if parts:
                                top_dirs.add(parts[0])
                            # Forbidden paths in package
                            for forbid in ("memory/", "zhiyi/", "raw/", "output/", "dist/", "backups/",
                                           "experience_lancedb/", "config/memcore.json",
                                           "config/source_system_registry.json",
                                           "config/window_binding_registry.json",
                                           "config/model_config.json"):
                                if n.startswith(forbid):
                                    forbidden_found.append(n)
                else:
                    import zipfile
                    with zipfile.ZipFile(pkg_path) as zf:
                        names = zf.namelist()
                        file_count = len(names)
                        for n in names:
                            parts = n.replace("\\", "/").split("/")
                            if parts:
                                top_dirs.add(parts[0])
                            for forbid in ("memory/", "zhiyi/", "raw/", "output/", "dist/", "backups/",
                                           "experience_lancedb/", "config/memcore.json",
                                           "config/source_system_registry.json",
                                           "config/window_binding_registry.json",
                                           "config/model_config.json"):
                                if n.startswith(forbid):
                                    forbidden_found.append(n)
                # Check required files
                has_required = any(d in top_dirs for d in ("src", "VERSION", "config"))
                steps_log.append({
                    "step": 3, "status": "pass" if not forbidden_found else "warn",
                    "action": "content_scan", "files": file_count,
                    "top_dirs": sorted(top_dirs),
                    "forbidden_found": forbidden_found,
                    "has_required_content": has_required,
                })
                # Check sandbox marker if sandbox mode
                sandbox_ok = True
                if sandbox_root:
                    marker = Path(sandbox_root) / ".memcore-sandbox-root"
                    sandbox_ok = marker.exists()
                    steps_log.append({
                        "step": 4, "status": "pass" if sandbox_ok else "fail",
                        "action": "sandbox_marker_check",
                        "marker": str(marker),
                        "found": sandbox_ok,
                    })
                    if not sandbox_ok:
                        self.send_json({
                            "ok": False, "dry_run": True,
                            "error": f".memcore-sandbox-root marker not found at {marker}; create marker directory to enable sandbox apply",
                            "steps": steps_log
                        })
                        return
                # Generate dry_run_token (inline, same algorithm as apply endpoint)
                import secrets, time as _time
                _raw = f"{target_version}:{pkg_path}:{install_root}:{_time.time()}:{secrets.token_hex(16)}"
                token = hashlib.sha256(_raw.encode()).hexdigest()[:32]
                _TOKEN_TTL = 600
                validation = {
                    "ok": True, "dry_run": True,
                    "dry_run_token": token,
                    "token_ttl_seconds": _TOKEN_TTL,
                    "token_bound_to": {"version": target_version, "package_path": pkg_path, "install_root": install_root},
                    "package_sha256": sha256,
                    "target_version": target_version,
                    "forbidden_paths_found": len(forbidden_found) > 0,
                    "would_preserve_user_data": True,
                    "sandbox_apply": bool(sandbox_root),
                    "steps": steps_log,
                }
                self.send_json(validation)
            except Exception as e:
                self.send_json({"ok": False, "dry_run": True, "error": str(e)[:200], "steps": steps_log})

        elif self.path == "/api/v1/update/apply":
            # Hardened apply endpoint.
            # Requires sandbox_root + allow_sandbox_apply OR production_apply + confirm_apply
            # install_root is REQUIRED for production apply — no default production path
            # dry_run_token must be bound to version+pkg_path+install_root with 10min expiry
            cl = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(cl).decode()) if cl > 0 else {}
            target_version = body.get("version", SERVICE_VERSION)
            pkg_path = body.get("package_path") or f"{MEMCORE_ROOT}/release/time-library-{target_version}.zip"
            sandbox_root = body.get("sandbox_root")
            allow_sandbox = body.get("allow_sandbox_apply", False)
            production_apply = body.get("production_apply", False)
            confirm_apply = body.get("confirm_apply", False)
            dry_run_token = body.get("dry_run_token", "")
            audit_note = body.get("audit_note", "")

            from pathlib import Path
            from datetime import datetime, timezone, timedelta
            import hashlib, time as _time

            # P0-2 Fix: expanded protected paths
            PROTECTED_PATHS_API = [
                Path.home() / ".openclaw",
                Path.home() / ".npm-global",
                Path("/usr/local"),
                Path("/usr/bin"),
                Path("/usr/lib"),
                Path("/opt"),
                Path("/etc"),
                Path("/root"),
                Path(MEMCORE_ROOT),
            ]

            # Token store: token -> {version, pkg_path, install_root, created_at}
            # Module-level so it persists across requests within the same process
            if not hasattr(Handler, "_dry_run_tokens"):
                Handler._dry_run_tokens = {}

            TOKEN_TTL_SECONDS = 600  # 10 minutes

            def make_dry_run_token(version, pkg, install_root):
                """Generate a dry-run token bound to version+pkg+install_root."""
                import secrets
                raw = f"{version}:{pkg}:{install_root}:{_time.time()}:{secrets.token_hex(16)}"
                token = hashlib.sha256(raw.encode()).hexdigest()[:32]
                Handler._dry_run_tokens[token] = {
                    "version": version,
                    "pkg_path": pkg,
                    "install_root": install_root,
                    "created_at": _time.time(),
                }
                return token

            def validate_dry_run_token(token, version, pkg, install_root):
                """Validate token is bound to the same version+pkg+install_root and not expired."""
                store = Handler._dry_run_tokens
                if token not in store:
                    return False, "token not found or already used/consumed"
                entry = store[token]
                if _time.time() - entry["created_at"] > TOKEN_TTL_SECONDS:
                    del store[token]
                    return False, "token expired (10min TTL)"
                if entry["version"] != version:
                    return False, f"token version mismatch: {entry['version']} != {version}"
                if entry["pkg_path"] != pkg:
                    return False, f"token package_path mismatch"
                if entry["install_root"] != install_root:
                    return False, f"token install_root mismatch: {entry['install_root']} != {install_root}"
                # Consume token (one-time use)
                del store[token]
                return True, ""

            # Audit log helper
            def log_apply(action, ok, error_msg=""):
                log_file = Path(MEMCORE_ROOT) / "logs" / "update_audit.log"
                log_file.parent.mkdir(parents=True, exist_ok=True)
                entry = {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "action": action,
                    "ok": ok,
                    "error": error_msg,
                    "version": target_version,
                    "package": pkg_path,
                    "audit_note": audit_note,
                }
                try:
                    with open(log_file, "a") as f:
                        f.write(json.dumps(entry) + "\n")
                except Exception:
                    pass  # Non-blocking

            # Step 1: Check sandbox OR production flag
            if sandbox_root and allow_sandbox:
                # SANDBOX flow: requires .memcore-sandbox-root marker at sandbox_root
                sandbox_path = Path(sandbox_root).resolve()
                marker = sandbox_path / ".memcore-sandbox-root"
                if not marker.exists():
                    log_apply("apply_sandbox", False, "sandbox marker missing")
                    self.send_json({"ok": False, "error": f".memcore-sandbox-root marker not found at {marker}", "steps": []})
                    return
                install_root = sandbox_root
            elif production_apply and confirm_apply:
                # PRODUCTION flow: install_root is REQUIRED — no default
                install_root = body.get("install_root", "").strip()
                if not install_root:
                    log_apply("apply_production", False, "install_root required for production apply")
                    self.send_json({"ok": False, "error": "install_root is required for production apply; no default production path is used", "steps": []})
                    return
                # V4 Fix: validate dry_run_token is bound to the same version+pkg+install_root
                if not dry_run_token:
                    log_apply("apply_production", False, "dry_run_token required")
                    self.send_json({"ok": False, "error": "dry_run_token required (must match a prior dry-run with the same version+package_path+install_root)", "steps": []})
                    return
                tok_ok, tok_err = validate_dry_run_token(dry_run_token, target_version, pkg_path, install_root)
                if not tok_ok:
                    log_apply("apply_production", False, f"dry_run_token validation failed: {tok_err}")
                    self.send_json({"ok": False, "error": f"dry_run_token validation failed: {tok_err}", "steps": []})
                    return
            else:
                log_apply("apply_blocked", False, "missing allow_sandbox_apply or production_apply+confirm_apply")
                self.send_json({
                    "ok": False,
                    "error": "apply blocked: must specify sandbox_root + allow_sandbox_apply=true OR production_apply=true + confirm_apply=true",
                    "steps": [],
                    "hint": "For sandbox apply: {sandbox_root: '/path', allow_sandbox_apply: true}. For production: {production_apply: true, confirm_apply: true, install_root: '/full/path/to/install', dry_run_token: '...'}"
                })
                return

            # Step 2: Boundary check
            ir = Path(install_root).resolve()
            for prot in PROTECTED_PATHS_API:
                try:
                    ir.relative_to(prot.resolve())
                    log_apply("apply_blocked", False, f"protected path: {prot}")
                    self.send_json({"ok": False, "error": f"install_root {install_root} overlaps with protected path {prot}; refused", "steps": []})
                    return
                except ValueError:
                    pass

            # Step 3: Execute apply
            try:
                import subprocess as _subp
                mc_root = str(MEMCORE_ROOT)
                dry_flag = "--dry-run" if not (sandbox_root or production_apply) else ""
                _result = _subp.run(
                    ["python3", f"{mc_root}/tools/apply_linux_update.py",
                     "--install-root", install_root,
                     "--pkg", pkg_path,
                     "--apply"],
                    capture_output=True, text=True, timeout=60,
                    cwd=mc_root, env={**os.environ, "PYTHONPATH": f"{mc_root}:{os.environ.get('PYTHONPATH','')}"}
                )
                try:
                    result = json.loads(_result.stdout)
                except:
                    result = {"ok": False, "error": "apply script output unparseable", "stderr": _result.stderr[:200]}
                result["note"] = "applied via console API; sandbox=" + str(bool(sandbox_root))
                result["sandbox_apply"] = bool(sandbox_root)
                result["production_apply"] = bool(production_apply)
                log_apply("apply_complete", result.get("ok", False))
                self.send_json(result)
            except _subp.TimeoutExpired:
                log_apply("apply_timeout", False)
                self.send_json({"ok": False, "error": "apply timed out after 60s", "steps": []})
            except Exception as e:
                log_apply("apply_error", False, str(e)[:100])
                self.send_json({"ok": False, "error": str(e)[:200], "steps": []})

        else:
            self.send_error(404)

def run(port=PORT, host="127.0.0.1"):
    migration = resume_legacy_vector_upgrade(MEMCORE_ROOT)
    if migration.get("write_performed") or migration.get("asset_prepare_started"):
        print(f"[memcore-m1] vector upgrade migration: {migration.get('state')}")
    server = ThreadingHTTPServer((host, port), Handler)
    _write_p6_pid_file()
    try:
        print(f"[memcore-m1] console running on http://{host}:{port}")
        server.serve_forever()
    finally:
        server.server_close()
        _clear_p6_pid_file()

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="memcore-m1 console")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args()
    run(port=args.port, host=args.host)
