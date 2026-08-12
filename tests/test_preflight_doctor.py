import importlib
import json
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def test_preflight_doctor_scores_existing_read_only_loops(tmp_path):
    doctor = importlib.import_module("src.preflight_doctor")

    payload = doctor.build_preflight_doctor(
        {"skip_platform_scan": True},
        memcore_root=tmp_path,
        home=tmp_path,
    )

    assert payload["ok"] is True
    assert payload["contract"] == "preflight_doctor.v2026.6.17"
    assert payload["doctor_score_contract"] == "preflight_doctor_score_contract.v2026.6.17"
    assert payload["read_only"] is True
    assert payload["write_performed"] is False
    assert payload["raw_write_performed"] is False
    assert payload["memory_write_performed"] is False
    assert payload["platform_write_performed"] is False
    assert payload["not_a_new_memory_layer"] is True
    assert payload["under_tiandao_five_shelves"] is True
    assert payload["overall_score"] < 55
    for field in [
        "connection_health_score",
        "binding_health_score",
        "fast_path_health_score",
        "latency_score",
        "recall_score",
        "source_backed_score",
        "raw_traceability_score",
        "projection_explainability_score",
        "answer_debug_score",
        "experience_intervention_score",
        "behavior_change_score",
        "acceptance_check_score",
        "benchmark_readiness_score",
    ]:
        assert isinstance(payload[field], int)
        assert 0 <= payload[field] <= 100
        assert field in payload["score_breakdown"] or field == "benchmark_readiness_score"
    assert payload["binding_health_score"] >= 80
    assert payload["recall_score"] == 0
    assert "recall_score" in payload["critical_attention"]
    assert payload["productized_loops"]["evidence_status"] == "no_records_not_measured"
    assert payload["experience_intervention_score"] >= 80
    assert payload["score_breakdown"]["latency_score"]["status"] == "not_measured"
    assert payload["answer_debug_score"] >= 80
    assert payload["score_breakdown"]["answer_debug_score"]["status"] == "ok"
    assert payload["answer_debug_capability"]["contract"] == "preflight_answer_debug_capability.v2026.6.18"
    assert payload["answer_debug_capability"]["dialog_entry_answer_debug_contract"] == "dialog_entry_answer_debug.v2026.6.18"
    assert payload["answer_debug_capability"]["evidence_bound_model_gating_contract"] == "evidence_bound_model_gating.v2026.6.18"
    assert payload["answer_debug_capability"]["read_only"] is True
    assert payload["answer_debug_capability"]["model_call_performed"] is False
    assert payload["answer_debug_capability"]["request_sent"] is False
    assert payload["memory_absorption_contracts"]["read_only"] is True
    assert payload["memory_absorption_contracts"]["model_call_performed"] is False
    assert payload["memory_absorption_contracts"]["evidence_atom_vocabulary"]["not_a_memory_layer"] is True
    assert payload["memory_absorption_contracts"]["search_think_boundary"]["think_owner"] == "evidence_bound_model"
    assert payload["memory_absorption_contracts"]["search_think_dry_run"]["model_call_performed"] is False
    assert payload["memory_absorption_contracts"]["search_think_dry_run"]["local_answer_synthesis_allowed"] is False
    assert payload["memory_absorption_contracts"]["delivery_receipt_contract"] == "memory_delivery_receipt.v2026.6.21"
    assert payload["boundary"]["preflight_doctor_sent_model_request"] is False
    assert payload["boundary"]["answer_debug_requires_explicit_request"] is True
    assert payload["boundary"]["think_answer_must_be_model_owned"] is True
    assert payload["boundary"]["public_metric_claim_requires_source_gate"] is True
    assert payload["route_summary"]["final_evidence_authority"] == "raw_source_refs"
    assert payload["route_summary"]["answer_debug_authority"] == "diagnostic_only_not_evidence"
    assert payload["route_summary"]["search_think_authority"] == "local_search_only_model_owned_think"
    assert payload["route_summary"]["public_metric_claim_authority"] == "source_gate_required_before_public_homepage"
    assert "productized_loops_doctor" in payload["route_summary"]["uses"]
    assert "dialog_entry_answer_debug" in payload["route_summary"]["uses"]
    assert "memory_absorption_contracts" in payload["route_summary"]["uses"]


def test_preflight_doctor_scores_answer_debug_capability_from_payload(tmp_path):
    doctor = importlib.import_module("src.preflight_doctor")

    payload = doctor.build_preflight_doctor(
        {
            "skip_platform_scan": True,
            "preflight_payload": {
                "contract": "zhixing_preflight.v2026.6.20",
                "decision": "surface",
                "should_surface": True,
                "memory_scope": "window",
                "active_layers_used": ["current_window"],
                "must_surface": [
                    {
                        "library_id": "ZX-XINGCE-DEBUG",
                        "library_shelf": "xingce",
                        "summary": "Answer debug should be visible before work.",
                        "source_path": "raw/probe_logs/debug.jsonl",
                        "raw_evidence_status": "raw_index",
                    }
                ],
                "source_refs_count": 1,
                "raw_items_count": 1,
                "answer_debug_available": True,
                "answer_debug_capability_contract": "preflight_answer_debug_capability.v2026.6.18",
                "dialog_entry_answer_debug_contract": "dialog_entry_answer_debug.v2026.6.18",
                "evidence_bound_model_contract": "evidence_bound_model.v2026.6.18",
                "evidence_bound_model_gating_contract": "evidence_bound_model_gating.v2026.6.18",
                "answer_model_call_policy": "auto",
                "answer_debug_capability": {
                    "contract": "preflight_answer_debug_capability.v2026.6.18",
                    "available": True,
                    "read_only": True,
                    "raw_write_performed": False,
                    "memory_write_performed": False,
                    "platform_write_performed": False,
                    "model_call_performed": False,
                    "request_sent": False,
                    "requires_explicit_answer_debug": True,
                    "requires_confirm_live_model_call": True,
                    "dialog_entry_answer_debug_contract": "dialog_entry_answer_debug.v2026.6.18",
                    "evidence_bound_model_contract": "evidence_bound_model.v2026.6.18",
                    "evidence_bound_model_gating_contract": "evidence_bound_model_gating.v2026.6.18",
                    "default_model_call_policy": "auto",
                    "supported_model_call_policies": ["auto", "always", "never"],
                    "provider": "minimax",
                    "model_name": "MiniMax-M2",
                    "base_url_present": True,
                    "api_key_env": "MINIMAX_API_KEY",
                    "api_key_present": False,
                    "runtime_binding_ready": False,
                    "final_evidence_authority": "raw_source_refs",
                },
            },
        },
        memcore_root=tmp_path,
        home=tmp_path,
    )

    assert payload["answer_debug_score"] == 100
    score = payload["score_breakdown"]["answer_debug_score"]
    assert "answer_debug_available" in score["signals"]
    assert "debug_capability_read_only_no_model_call" in score["signals"]
    assert "raw_source_refs_remain_final_authority" in score["signals"]
    assert "live_model_runtime_binding_not_ready_or_not_checked" in score["attention"]
    assert payload["answer_debug_capability"]["provider"] == "minimax"
    assert payload["answer_debug_capability"]["api_key_env"] == "MINIMAX_API_KEY"
    assert payload["answer_debug_capability"]["api_key_present"] is False


def test_preflight_doctor_surfaces_memory_absorption_contracts_and_metric_gate(tmp_path):
    doctor = importlib.import_module("src.preflight_doctor")

    payload = doctor.build_preflight_doctor(
        {
            "skip_platform_scan": True,
            "public_metric_claim": {
                "benchmark": "LongMemEval-S",
                "split": "s",
                "metric": "recall_any@5",
                "score": 95.2,
                "measured_by": "internal",
                "reproducible_command": "python eval.py",
                "dataset_source": "longmemeval-cleaned",
                "evaluation_scope": "qa accuracy",
                "public_wording": "Time Library reaches 95.2% answer accuracy and SOTA.",
            },
        },
        memcore_root=tmp_path,
        home=tmp_path,
    )

    contracts = payload["memory_absorption_contracts"]
    metric_gate = contracts["public_metric_claim_gate"]
    assert contracts["contract"] == "memory_absorption_contracts.v2026.6.21"
    assert contracts["read_only"] is True
    assert contracts["model_call_performed"] is False
    assert contracts["search_think_boundary"]["search_owner"] == "local_memcore"
    assert contracts["search_think_boundary"]["think_owner"] == "evidence_bound_model"
    assert "synthesize_answer" in contracts["search_think_boundary"]["local_forbidden_after_think"]
    assert contracts["search_think_dry_run"]["contract"] == "search_think_delivery_receipt_dry_run.v2026.6.21"
    assert contracts["search_think_dry_run"]["receipt_is_projection_only"] is True
    assert metric_gate["is_publication_ready"] is False
    assert "retrieval_recall_must_not_be_labeled_qa_accuracy" in metric_gate["errors"]
    assert "retrieval_recall_public_wording_must_not_claim_qa_or_answer_accuracy" in metric_gate["errors"]
    assert "public_metric_wording_must_not_claim_sota_or_leaderboard_first" in metric_gate["errors"]
    assert "missing_provenance_field_one_of:claim_source_url|source_refs" in metric_gate["errors"]
    assert payload["boundary"]["public_metric_claim_requires_source_gate"] is True


def test_preflight_doctor_accepts_measured_fast_path_overlay(tmp_path):
    doctor = importlib.import_module("src.preflight_doctor")

    payload = doctor.build_preflight_doctor(
        {
            "skip_platform_scan": True,
            "latency_ms": 49.6,
            "fast_window_preflight": True,
            "fast_recall_path": "canonical_window_index",
            "fast_window_index_status": "hit",
            "zhiyi_layer_skipped_for_fast_preflight": True,
        },
        memcore_root=tmp_path,
        home=tmp_path,
    )

    assert payload["fast_path_health_score"] == 100
    assert payload["latency_score"] == 100
    fast_path = payload["score_breakdown"]["fast_path_health_score"]
    assert "canonical_window_index" in fast_path["signals"]
    assert "fast_window_index_hit" in fast_path["signals"]


def test_preflight_doctor_projection_explainability_overlay_is_triggerable(tmp_path):
    doctor = importlib.import_module("src.preflight_doctor")

    payload = doctor.build_preflight_doctor(
        {
            "skip_platform_scan": True,
            "library_index_projection_used": True,
            "library_index_projection_refs_count": 2,
            "library_index_projection_policy": "navigation_hint_only_raw_evidence_required",
            "library_index_projection_soft_weight_policy": "library_index_projection_is_soft_navigation_signal_only",
            "library_index_projection_soft_weight": 6,
        },
        memcore_root=tmp_path,
        home=tmp_path,
    )

    assert payload["projection_explainability_score"] == 100
    projection = payload["score_breakdown"]["projection_explainability_score"]
    assert projection["status"] == "ok"
    assert "library_index_projection_used" in projection["signals"]
    assert "projection_refs_present" in projection["signals"]
    assert "projection_policy_exposed" in projection["signals"]
    assert payload["route_summary"]["projection_authority"] == "navigation_hint_only"
    assert payload["route_summary"]["final_evidence_authority"] == "raw_source_refs"


def test_preflight_doctor_live_work_preflight_smoke_overlays_latency_and_projection(tmp_path):
    doctor = importlib.import_module("src.preflight_doctor")
    captured = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            return

        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0") or 0)
            captured["request"] = json.loads(self.rfile.read(length).decode("utf-8"))
            payload = {
                "ok": True,
                "mode": "work_preflight",
                "contract": "agent_work_preflight.v2026.6.20",
                "classification": "already_built_but_forgotten",
                "decision": "surface",
                "fast_window_preflight": True,
                "fast_recall_path": "canonical_window_index",
                "fast_window_index_status": "hit_recent_context",
                "zhiyi_layer_skipped_for_fast_preflight": True,
                "library_index_projection_used": True,
                "library_index_projection_refs_count": 2,
                "library_index_projection_policy": "navigation_hint_only_raw_evidence_required",
                "library_index_projection_soft_weight_policy": "library_index_projection_is_soft_navigation_signal_only",
                "library_index_projection_soft_weight": 6,
                "source_refs_count": 1,
                "raw_items_count": 1,
            }
            body = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        payload = doctor.build_preflight_doctor(
            {
                "skip_platform_scan": True,
                "live_work_preflight_smoke": True,
                "live_work_preflight_endpoint": f"http://127.0.0.1:{server.server_address[1]}/api/v1/raw/query",
                "live_work_preflight_query": "继续，开工前先查已有机制",
                "project_root": str(tmp_path),
            },
            memcore_root=tmp_path,
            home=tmp_path,
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert captured["request"]["mode"] == "work_preflight"
    assert captured["request"]["query"] == "继续，开工前先查已有机制"
    assert captured["request"]["source_system"] == ""
    assert payload["live_work_preflight_smoke"]["ok"] is True
    assert payload["live_work_preflight_smoke"]["read_only"] is True
    assert payload["live_work_preflight_smoke"]["model_call_performed"] is False
    assert payload["live_work_preflight_smoke"]["response"]["decision"] == "surface"
    assert payload["fast_path_health_score"] == 100
    assert payload["latency_score"] >= 80
    assert payload["projection_explainability_score"] == 100
    assert "hit_recent_context" in payload["score_breakdown"]["fast_path_health_score"]["signals"]
    assert payload["route_summary"]["live_work_preflight_smoke"] == "measured_overlay"
    assert payload["boundary"]["live_work_preflight_smoke_read_only"] is True


def test_preflight_doctor_live_work_preflight_smoke_samples_score_median_and_report_outlier(tmp_path):
    doctor = importlib.import_module("src.preflight_doctor")
    captured = []
    delays = [0.01, 1.15, 0.02]

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            return

        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0") or 0)
            captured.append(json.loads(self.rfile.read(length).decode("utf-8")))
            time.sleep(delays[len(captured) - 1])
            payload = {
                "ok": True,
                "mode": "work_preflight",
                "contract": "agent_work_preflight.v2026.6.20",
                "classification": "already_built_but_forgotten",
                "decision": "surface",
                "fast_window_preflight": True,
                "fast_recall_path": "canonical_window_index",
                "fast_window_index_status": "hit_recent_context",
                "zhiyi_layer_skipped_for_fast_preflight": True,
                "source_refs_count": 1,
                "raw_items_count": 1,
            }
            body = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        payload = doctor.build_preflight_doctor(
            {
                "skip_platform_scan": True,
                "live_work_preflight_smoke": True,
                "live_work_preflight_smoke_samples": 3,
                "live_work_preflight_endpoint": f"http://127.0.0.1:{server.server_address[1]}/api/v1/raw/query",
                "project_root": str(tmp_path),
            },
            memcore_root=tmp_path,
            home=tmp_path,
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert len(captured) == 3
    smoke = payload["live_work_preflight_smoke"]
    latency_summary = smoke["latency_summary"]
    latency_score = payload["score_breakdown"]["latency_score"]
    assert smoke["ok"] is True
    assert smoke["sample_count"] == 3
    assert len(smoke["samples"]) == 3
    assert latency_summary["sample_count"] == 3
    assert latency_summary["slow_sample_count"] == 1
    assert latency_summary["median_ms"] < 500
    assert latency_summary["max_ms"] > 1000
    assert payload["latency_score"] >= 90
    assert "latency_samples=3" in latency_score["signals"]
    assert "slow_latency_sample_count=1" in latency_score["attention"]


def test_preflight_doctor_daily_smoke_defaults_to_current_window_anchor(tmp_path):
    doctor = importlib.import_module("src.preflight_doctor")
    captured = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            return

        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0") or 0)
            captured["request"] = json.loads(self.rfile.read(length).decode("utf-8"))
            assert "canonical_window_id" not in captured["request"]
            payload = {
                "ok": True,
                "mode": "work_preflight",
                "contract": "agent_work_preflight.v2026.6.20",
                "classification": "already_built_but_forgotten",
                "decision": "surface",
                "fast_window_preflight": True,
                "fast_recall_path": "canonical_window_index",
                "fast_window_index_status": "hit_recent_context",
                "zhiyi_layer_skipped_for_fast_preflight": True,
                "source_refs_count": 1,
                "raw_items_count": 1,
            }
            body = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        payload = doctor.build_preflight_doctor(
            {
                "diagnostic_profile": "smoke",
                "live_work_preflight_endpoint": f"http://127.0.0.1:{server.server_address[1]}/api/v1/raw/query",
            },
            memcore_root=tmp_path,
            home=tmp_path,
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert captured["request"]["mode"] == "work_preflight"
    assert captured["request"]["source_system"] == ""
    assert payload["live_work_preflight_smoke"]["request"]["has_canonical_window_id"] is False
    assert payload["live_work_preflight_smoke"]["request"]["canonical_window_id"] == ""
    assert payload["live_work_preflight_smoke"]["request"]["default_work_anchor_applied"] is False
    assert payload["live_work_preflight_smoke"]["default_work_anchor"]["applied"] is False
    assert payload["live_work_preflight_smoke"]["default_work_anchor"]["reason"] == "explicit_anchor_missing"
    assert payload["summary"]["default_work_anchor_applied"] is False
    assert payload["route_summary"]["default_work_anchor"]["canonical_window_id"] == ""
    assert payload["boundary"]["default_work_anchor_applied"] is False
    assert payload["overall_score"] >= 80


def test_preflight_doctor_default_work_anchor_can_be_disabled_for_scope_diagnostics(tmp_path):
    doctor = importlib.import_module("src.preflight_doctor")
    captured = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            return

        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0") or 0)
            captured["request"] = json.loads(self.rfile.read(length).decode("utf-8"))
            payload = {
                "ok": False,
                "mode": "work_preflight",
                "contract": "agent_work_preflight.v2026.6.20",
                "classification": "scope_required",
                "decision": "scope_required",
                "scope_missing": True,
                "source_refs_count": 0,
                "raw_items_count": 0,
            }
            body = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        payload = doctor.build_preflight_doctor(
            {
                "diagnostic_profile": "smoke",
                "disable_default_work_anchor": True,
                "live_work_preflight_endpoint": f"http://127.0.0.1:{server.server_address[1]}/api/v1/raw/query",
            },
            memcore_root=tmp_path,
            home=tmp_path,
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert "canonical_window_id" not in captured["request"]
    assert payload["live_work_preflight_smoke"]["request"]["has_canonical_window_id"] is False
    assert payload["live_work_preflight_smoke"]["request"]["default_work_anchor_applied"] is False
    assert payload["live_work_preflight_smoke"]["default_work_anchor"]["disabled"] is True
    assert payload["live_work_preflight_smoke"]["default_work_anchor"]["reason"] == "explicit_anchor_check_disabled_by_request"
    assert payload["live_work_preflight_smoke"]["response"]["decision"] == "scope_required"
    assert payload["summary"]["default_work_anchor_applied"] is False
    assert payload["boundary"]["default_work_anchor_applied"] is False


def test_preflight_doctor_smoke_profile_skips_heavy_productized_loops(tmp_path):
    doctor = importlib.import_module("src.preflight_doctor")
    captured = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            return

        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0") or 0)
            captured.append(json.loads(self.rfile.read(length).decode("utf-8")))
            payload = {
                "ok": True,
                "mode": "work_preflight",
                "contract": "agent_work_preflight.v2026.6.20",
                "classification": "already_built_but_forgotten",
                "decision": "surface",
                "fast_window_preflight": True,
                "fast_recall_path": "canonical_window_index",
                "fast_window_index_status": "hit_recent_context",
                "zhiyi_layer_skipped_for_fast_preflight": True,
                "library_index_projection_used": True,
                "library_index_projection_refs_count": 2,
                "library_index_projection_policy": "navigation_hint_only_raw_evidence_required",
                "source_refs_count": 2,
                "raw_items_count": 2,
            }
            body = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        payload = doctor.build_preflight_doctor(
            {
                "diagnostic_profile": "smoke",
                "live_work_preflight_smoke_samples": 2,
                "live_work_preflight_endpoint": f"http://127.0.0.1:{server.server_address[1]}/api/v1/raw/query",
                "project_root": str(tmp_path),
            },
            memcore_root=tmp_path,
            home=tmp_path,
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert len(captured) == 2
    assert payload["ok"] is True
    assert payload["diagnostic_profile"] == "smoke"
    assert payload["profile_contract"] == "preflight_doctor_smoke_profile.v2026.6.18"
    assert payload["heavy_diagnostics_skipped"] is True
    assert payload["productized_loops"]["status"] == "skipped_in_smoke_profile"
    assert "productized_loops_doctor" in payload["route_summary"]["skips"]
    assert payload["connection_health_score"] == 100
    assert payload["fast_path_health_score"] == 100
    assert payload["latency_score"] >= 90
    assert payload["source_backed_score"] == 100
    assert payload["raw_traceability_score"] == 100
    assert payload["projection_explainability_score"] == 100
    assert payload["benchmark_readiness"]["readiness_level"] == "skipped_in_smoke_profile"
    assert payload["benchmark_readiness"]["status"] == "non_blocking_skipped"
    assert payload["benchmark_readiness_score"] == 0
    assert payload["critical_attention"] == []
    assert payload["boundary"]["heavy_diagnostics_skipped"] is True


def test_preflight_doctor_live_work_preflight_makes_record_attention_non_blocking(tmp_path):
    doctor = importlib.import_module("src.preflight_doctor")

    productized_payload = {
        "ok": True,
        "loops": {
            "connect_doctor": {
                "auto_connect": {
                    "ok": True,
                    "scan_mode": "fast_known_adapters_only",
                },
                "record_doctor": {
                    "doctor_status": "attention",
                },
                "statuses": {
                    "detected_connectable": 1,
                },
            },
            "hot_path_preflight": {
                "ok": True,
                "decision": "surface",
                "memory_scope": "window",
                "active_layers_used": ["current_window"],
                "source_refs_count": 1,
                "raw_items_count": 1,
                "fast_window_preflight": True,
                "fast_recall_path": "canonical_window_index",
                "fast_window_index_status": "hit_recent_context",
            },
            "borrowing_receipts": {
                "receipt_count": 1,
                "source_refs_count": 1,
                "raw_items_count": 1,
            },
            "recall_experience_benchmark": {
                "summary": {"best_mode": "fused", "top1_accuracy": 1.0},
            },
            "experience_evolution_demo": {
                "summary": {"candidate_count": 1},
            },
        },
        "loop_statuses": {
            "connect_doctor": {"ok": True, "read_only": True, "write_performed": False},
            "hot_path_preflight": {"ok": True, "read_only": True, "write_performed": False},
            "recall_experience_benchmark": {"ok": True, "read_only": True, "write_performed": False},
            "borrowing_receipts": {"ok": True, "read_only": True, "write_performed": False},
            "experience_evolution_demo": {"ok": True, "read_only": True, "write_performed": False},
        },
        "summary": {},
        "read_only": True,
        "model_call_performed": False,
    }

    payload = doctor.build_preflight_doctor(
        {
            "productized_payload": productized_payload,
            "live_work_preflight_smoke": {
                "ok": True,
                "contract": "preflight_doctor_live_work_preflight_smoke.v2026.6.18",
                "elapsed_ms": 30,
                "response": {
                    "ok": True,
                    "decision": "surface",
                    "fast_window_preflight": True,
                    "fast_recall_path": "canonical_window_index",
                    "fast_window_index_status": "hit_recent_context",
                    "source_refs_count": 1,
                    "raw_items_count": 1,
                },
            },
        },
        memcore_root=tmp_path,
        home=tmp_path,
    )

    connection = payload["score_breakdown"]["connection_health_score"]
    assert payload["connection_health_score"] == 100
    assert "work_preflight_live_connection_validated" in connection["signals"]
    assert "record_chain_attention_is_non_blocking_for_live_connection_score" in connection["attention"]
    assert "record_doctor_status=attention" in connection["attention"]


def test_preflight_doctor_separates_internal_diagnostic_from_official_scores(tmp_path):
    doctor = importlib.import_module("src.preflight_doctor")

    payload = doctor.build_preflight_doctor(
        {"skip_platform_scan": True},
        memcore_root=tmp_path,
        home=tmp_path,
    )
    readiness = payload["benchmark_readiness"]

    assert readiness["official_leaderboard_score"] is False
    assert readiness["tiny_diagnostic_is_not_official_score"] is True
    assert readiness["internal_retrieval_diagnostic_available"] is True
    assert readiness["full_qa_status"]["implemented"] is False
    assert readiness["full_qa_status"]["official_evaluator_preflight_available"] is False
    assert "official_evaluator_preflight_runner_available" not in readiness["signals"]
    assert "separate pinned evaluator workspace" in readiness["full_qa_status"]["reason"]
    assert set(readiness["supported_targets"]) >= {"locomo", "longmemeval"}
    assert payload["boundary"]["official_leaderboard_score"] is False
    assert payload["boundary"]["tiny_fixture_is_internal_diagnostic_only"] is True
    assert payload["summary"]["official_leaderboard_score"] is False


def test_preflight_doctor_cli_outputs_json_and_text(tmp_path):
    script = ROOT / "tools" / "preflight_doctor.py"
    json_run = subprocess.run(
        [
            sys.executable,
            str(script),
            "--skip-platform-scan",
            "--memcore-root",
            str(tmp_path),
            "--home",
            str(tmp_path),
            "--diagnostic-profile",
            "full",
            "--live-work-preflight-smoke",
            "--live-work-preflight-smoke-samples",
            "1",
            "--live-work-preflight-endpoint",
            "http://127.0.0.1:1/api/v1/raw/query",
            "--live-work-preflight-timeout-seconds",
            "0.01",
            "--latency-ms",
            "42",
            "--fast-window-preflight",
            "--fast-recall-path",
            "canonical_window_index",
            "--fast-window-index-status",
            "hit",
            "--zhiyi-layer-skipped-for-fast-preflight",
            "--library-index-projection-used",
            "--library-index-projection-refs-count",
            "2",
            "--library-index-projection-policy",
            "navigation_hint_only_raw_evidence_required",
            "--library-index-projection-soft-weight-policy",
            "library_index_projection_is_soft_navigation_signal_only",
            "--library-index-projection-soft-weight",
            "6",
            "--json",
        ],
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    payload = json.loads(json_run.stdout)
    assert payload["contract"] == "preflight_doctor.v2026.6.17"
    assert payload.get("diagnostic_profile") != "smoke"
    assert payload["fast_path_health_score"] == 100
    assert payload["latency_score"] == 100
    assert payload["projection_explainability_score"] == 100
    assert payload["live_work_preflight_smoke"]["ok"] is False
    assert payload["benchmark_readiness"]["official_leaderboard_score"] is False

    text_run = subprocess.run(
        [
            sys.executable,
            str(script),
            "--skip-platform-scan",
            "--memcore-root",
            str(tmp_path),
            "--home",
            str(tmp_path),
            "--diagnostic-profile",
            "full",
            "--latency-ms",
            "42",
            "--fast-window-preflight",
            "--fast-recall-path",
            "canonical_window_index",
            "--fast-window-index-status",
            "hit",
            "--zhiyi-layer-skipped-for-fast-preflight",
        ],
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    assert "Time Library Preflight Doctor" in text_run.stdout
    assert "- fast path: 100/100" in text_run.stdout
    assert "- latency: 100/100" in text_run.stdout
    assert "official leaderboard score: False" in text_run.stdout

    class RawHandler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            return

        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0") or 0)
            self.rfile.read(length)
            payload = {
                "ok": True,
                "mode": "work_preflight",
                "contract": "agent_work_preflight.v2026.6.20",
                "classification": "already_built_but_forgotten",
                "decision": "surface",
                "fast_window_preflight": True,
                "fast_recall_path": "canonical_window_index",
                "fast_window_index_status": "hit_recent_context",
                "zhiyi_layer_skipped_for_fast_preflight": True,
                "source_refs_count": 1,
                "raw_items_count": 1,
            }
            body = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    raw_server = ThreadingHTTPServer(("127.0.0.1", 0), RawHandler)
    raw_thread = threading.Thread(target=raw_server.serve_forever, daemon=True)
    raw_thread.start()
    try:
        default_smoke_run = subprocess.run(
            [
                sys.executable,
                str(script),
                "--memcore-root",
                str(tmp_path),
                "--home",
                str(tmp_path),
                "--live-work-preflight-endpoint",
                f"http://127.0.0.1:{raw_server.server_address[1]}/api/v1/raw/query",
                "--live-work-preflight-timeout-seconds",
                "1",
                "--json",
            ],
            cwd=ROOT,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
        )
    finally:
        raw_server.shutdown()
        raw_thread.join(timeout=5)
    default_payload = json.loads(default_smoke_run.stdout)
    assert default_payload["diagnostic_profile"] == "smoke"
    assert default_payload["heavy_diagnostics_skipped"] is True
    assert default_payload["productized_loops"]["status"] == "skipped_in_smoke_profile"


def test_preflight_doctor_console_routes_are_read_only(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMCORE_ROOT", str(tmp_path / "memcore"))
    monkeypatch.setenv("MEMCORE_CONFIG", str(ROOT / "config" / "memcore.json"))
    for name in [
        "config_loader",
        "src.config_loader",
        "p6_console",
        "src.p6_console",
        "p6_experience_governance",
        "src.p6_experience_governance",
        "productized_loops",
        "src.productized_loops",
        "preflight_doctor",
        "src.preflight_doctor",
    ]:
        sys.modules.pop(name, None)
    p6 = importlib.import_module("p6_console")
    class RawHandler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            return

        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0") or 0)
            self.rfile.read(length)
            payload = {
                "ok": True,
                "mode": "work_preflight",
                "contract": "agent_work_preflight.v2026.6.20",
                "classification": "already_built_but_forgotten",
                "decision": "surface",
                "fast_window_preflight": True,
                "fast_recall_path": "canonical_window_index",
                "fast_window_index_status": "hit_recent_context",
                "zhiyi_layer_skipped_for_fast_preflight": True,
                "source_refs_count": 1,
                "raw_items_count": 1,
            }
            body = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    raw_server = ThreadingHTTPServer(("127.0.0.1", 0), RawHandler)
    raw_thread = threading.Thread(target=raw_server.serve_forever, daemon=True)
    raw_thread.start()
    raw_endpoint = f"http://127.0.0.1:{raw_server.server_address[1]}/api/v1/raw/query"
    server = p6.ThreadingHTTPServer(("127.0.0.1", 0), p6.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/v1/preflight-doctor?skip_platform_scan=1&live_work_preflight_endpoint={raw_endpoint}",
            timeout=10,
        ) as response:
            get_payload = json.loads(response.read().decode("utf-8"))
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/v1/preflight-doctor",
            data=json.dumps({"skip_platform_scan": True, "live_work_preflight_endpoint": raw_endpoint}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            post_payload = json.loads(response.read().decode("utf-8"))
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/v1/preflight-doctor?skip_platform_scan=1&diagnostic_profile=full",
            timeout=10,
        ) as response:
            full_payload = json.loads(response.read().decode("utf-8"))
    finally:
        server.shutdown()
        thread.join(timeout=5)
        raw_server.shutdown()
        raw_thread.join(timeout=5)

    for payload in (get_payload, post_payload):
        assert payload["contract"] == "preflight_doctor.v2026.6.17"
        assert payload["diagnostic_profile"] == "smoke"
        assert payload["heavy_diagnostics_skipped"] is True
        assert payload["read_only"] is True
        assert payload["write_performed"] is False
        assert payload["raw_write_performed"] is False
        assert payload["platform_write_performed"] is False
        assert payload["doctor_score_contract"] == "preflight_doctor_score_contract.v2026.6.17"
        assert payload["benchmark_readiness"]["official_leaderboard_score"] is False
        assert payload["productized_loops"]["status"] == "skipped_in_smoke_profile"

    assert full_payload["contract"] == "preflight_doctor.v2026.6.17"
    assert full_payload.get("diagnostic_profile") != "smoke"
    assert full_payload["benchmark_readiness"]["official_leaderboard_score"] is False
    assert full_payload["recall_score"] == 0
    assert full_payload["productized_loops"]["evidence_status"] == "no_records_not_measured"
