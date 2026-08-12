import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _assert_tiandao_console_contract(contract, *, contract_id, layer):
    assert contract["ok"] is True
    assert contract["contract"] == contract_id
    assert contract["parent_tiandao_contract"] == "tiandao_time_river.v1"
    assert contract["console_layer"] == layer
    assert contract["not_raw_origin"] is True
    assert contract["raw_write_performed"] is False
    assert contract["memory_write_performed"] is False
    assert contract["platform_write_performed"] is False
    assert "raw_origin_policy" in contract


def test_console_surface_modules_are_under_tiandao_contracts():
    import p6_console_openclaw
    import p6_console_security
    import p6_console_status
    import p6_console_ui
    import p6_experience_hermes_feedback
    import p6_experience_governance
    import p6_zhiyi_model_runtime
    import p6_zhiyi_usage_log
    import hermes_skill_artifact_status
    import platform_guard_catalog
    import platform_guard_package_inventory
    import platform_guard_model_identity
    import platform_guard_surface_scan
    import platform_thin_adapter_core

    _assert_tiandao_console_contract(
        p6_console_ui.get_console_ui_contract(),
        contract_id="tiandao_console_surface.v1",
        layer="human_entry_surface",
    )
    _assert_tiandao_console_contract(
        p6_console_security.get_console_security_contract(),
        contract_id="tiandao_console_action_gate.v1",
        layer="action_security_gate",
    )
    _assert_tiandao_console_contract(
        p6_console_openclaw.get_openclaw_console_contract(),
        contract_id="tiandao_openclaw_console_inlet.v1",
        layer="platform_guard_inlet",
    )
    _assert_tiandao_console_contract(
        p6_console_status.get_console_status_contract(),
        contract_id="tiandao_console_status_diagnostics.v1",
        layer="status_diagnostics",
    )
    _assert_tiandao_console_contract(
        p6_zhiyi_model_runtime.get_zhiyi_model_runtime_contract(),
        contract_id="tiandao_zhiyi_model_runtime_console.v1",
        layer="zhiyi_runtime_control",
    )
    _assert_tiandao_console_contract(
        p6_zhiyi_usage_log.get_zhiyi_usage_log_contract(),
        contract_id="tiandao_zhiyi_usage_log_observation.v1",
        layer="zhiyi_usage_log_observation",
    )
    usage_log_contract = p6_zhiyi_usage_log.get_zhiyi_usage_log_contract()
    assert usage_log_contract["usage_log_write_performed"] is False
    assert usage_log_contract["authorization_required_for_write"] is True
    _assert_tiandao_console_contract(
        p6_experience_governance.get_experience_governance_contract(),
        contract_id="tiandao_experience_governance_console.v1",
        layer="experience_governance",
    )
    experience_contract = p6_experience_governance.get_experience_governance_contract()
    assert experience_contract["workbench_id"] == "experience_governance"
    assert experience_contract["write_capable"] is True
    assert experience_contract["authorization_required_for_write"] is True
    assert "candidate_action_receipt" in experience_contract["authorized_write_scopes"]
    assert "zhiyi_case_memory_lifecycle_overlay" in experience_contract["authorized_write_scopes"]
    assert experience_contract["default_query_boundary"]["write_performed"] is False
    hermes_feedback_contract = p6_experience_hermes_feedback.get_experience_hermes_feedback_contract()
    assert hermes_feedback_contract["ok"] is True
    assert hermes_feedback_contract["contract"] == "tiandao_experience_hermes_feedback_governance.v1"
    assert hermes_feedback_contract["parent_tiandao_contract"] == "tiandao_time_river.v1"
    assert hermes_feedback_contract["workbench_id"] == "experience_governance"
    assert hermes_feedback_contract["governance_layer"] == "hermes_feedback_governance"
    assert hermes_feedback_contract["not_raw_origin"] is True
    assert hermes_feedback_contract["raw_write_performed"] is False
    assert hermes_feedback_contract["memory_write_performed"] is False
    assert hermes_feedback_contract["platform_write_performed"] is False
    assert "hermes_feedback_action_receipt" in hermes_feedback_contract["authorized_write_scopes"]
    assert "hermes_native_skill_file" in hermes_feedback_contract["forbidden_write_scopes"]
    hermes_skill_status_contract = hermes_skill_artifact_status.get_hermes_skill_artifact_status_contract()
    assert hermes_skill_status_contract["ok"] is True
    assert hermes_skill_status_contract["contract"] == "tiandao_hermes_skill_artifact_status_observation.v1"
    assert hermes_skill_status_contract["parent_tiandao_contract"] == "tiandao_time_river.v1"
    assert hermes_skill_status_contract["workbench_id"] == "experience_governance"
    assert hermes_skill_status_contract["governance_layer"] == "hermes_skill_artifact_status"
    assert hermes_skill_status_contract["not_raw_origin"] is True
    assert hermes_skill_status_contract["raw_write_performed"] is False
    assert hermes_skill_status_contract["memory_write_performed"] is False
    assert hermes_skill_status_contract["platform_write_performed"] is False
    assert hermes_skill_status_contract["hermes_skill_write_performed_by_time_library"] is False
    assert hermes_skill_status_contract["production_experience_write_performed"] is False
    assert "hermes_native_skill_file" in hermes_skill_status_contract["forbidden_write_scopes"]
    platform_contract = platform_thin_adapter_core.get_platform_guard_core_contract()
    assert platform_contract["ok"] is True
    assert platform_contract["contract"] == "tiandao_platform_guard_core.v1"
    assert platform_contract["parent_tiandao_contract"] == "tiandao_time_river.v1"
    assert platform_contract["workbench_id"] == "platform_guard"
    assert platform_contract["not_raw_origin"] is True
    assert platform_contract["raw_write_performed"] is False
    assert platform_contract["memory_write_performed"] is False
    assert platform_contract["platform_write_performed"] is False
    assert platform_contract["subcontracts"] == [
        "tiandao_platform_guard_catalog.v1",
        "tiandao_platform_guard_model_identity.v1",
        "tiandao_platform_guard_surface_scan.v1",
    ]

    for contract, contract_id, layer in (
        (
            platform_guard_catalog.get_platform_guard_catalog_contract(),
            "tiandao_platform_guard_catalog.v1",
            "platform_guard_catalog",
        ),
        (
            platform_guard_package_inventory.get_platform_guard_package_inventory_contract(),
            "tiandao_platform_guard_package_inventory.v1",
            "platform_guard_package_inventory",
        ),
        (
            platform_guard_model_identity.get_platform_guard_model_identity_contract(),
            "tiandao_platform_guard_model_identity.v1",
            "platform_guard_model_identity",
        ),
        (
            platform_guard_surface_scan.get_platform_guard_surface_scan_contract(),
            "tiandao_platform_guard_surface_scan.v1",
            "platform_guard_surface_scan",
        ),
    ):
        assert contract["ok"] is True
        assert contract["contract"] == contract_id
        assert contract["parent_tiandao_contract"] == "tiandao_time_river.v1"
        assert contract["workbench_id"] == "platform_guard"
        assert contract["console_layer"] == layer
        assert contract["not_raw_origin"] is True
        assert contract["raw_write_performed"] is False
        assert contract["memory_write_performed"] is False
        assert contract["platform_write_performed"] is False


def test_p6_console_remains_compatibility_entry_not_contract_owner():
    import p6_console as p6

    assert p6.get_console_ui_contract()["contract"] == "tiandao_console_surface.v1"
    assert p6.get_console_security_contract()["contract"] == "tiandao_console_action_gate.v1"
    assert p6.get_openclaw_console_contract()["contract"] == "tiandao_openclaw_console_inlet.v1"
    assert p6.get_console_status_contract()["contract"] == "tiandao_console_status_diagnostics.v1"
    assert p6.get_zhiyi_model_runtime_contract()["contract"] == "tiandao_zhiyi_model_runtime_console.v1"
    assert p6.get_zhiyi_usage_log_contract()["contract"] == "tiandao_zhiyi_usage_log_observation.v1"
    assert p6.get_experience_governance_contract()["contract"] == "tiandao_experience_governance_console.v1"
    assert p6.query_zhixing_library({"page_size": 1})["write_performed"] is False
    assert p6.I18N["zh-CN"]["dashboard.sealed"] == "本机服务就绪"
    assert "Time Library Console" in p6.HTML_TEMPLATE
    assert "memcore-cloud Console" not in p6.HTML_TEMPLATE
    assert p6._action_post_requires_console_token("/api/v1/update/apply") is True


def test_p6_console_is_reduced_but_still_entrypoint():
    p6_path = SRC / "p6_console.py"
    lines = p6_path.read_text(encoding="utf-8").splitlines()
    text = "\n".join(lines)

    status_path = SRC / "p6_console_status.py"
    status_lines = status_path.read_text(encoding="utf-8").splitlines()
    status_text = "\n".join(status_lines)

    assert len(lines) < 3000
    assert len(status_lines) < 900
    assert "class Handler(BaseHTTPRequestHandler):" in text
    assert "class Handler(BaseHTTPRequestHandler):" not in status_text
    assert "from src.p6_console_ui import I18N, HTML_TEMPLATE" in text
    assert "from src import p6_console_status as _console_status" in text
    assert "from src.p6_experience_governance import *" in text
    assert "from src.hermes_native_liveness import" not in text
    assert "def m3_get_overview(" in status_text
    assert "def m4_get_task_results(" in status_text
    assert "def m3_get_overview(" in text
    assert "def m4_get_task_results(" in text


def test_experience_governance_module_is_bounded_workbench():
    import hermes_native_liveness
    import hermes_skill_artifact_status
    import p6_experience_hermes_feedback
    import p6_experience_governance

    module_path = SRC / "p6_experience_governance.py"
    hermes_path = SRC / "p6_experience_hermes_feedback.py"
    native_path = SRC / "hermes_native_liveness.py"
    skill_status_path = SRC / "hermes_skill_artifact_status.py"
    lines = module_path.read_text(encoding="utf-8").splitlines()
    hermes_lines = hermes_path.read_text(encoding="utf-8").splitlines()
    native_lines = native_path.read_text(encoding="utf-8").splitlines()
    skill_status_lines = skill_status_path.read_text(encoding="utf-8").splitlines()

    assert len(lines) < 2400
    assert len(hermes_lines) < 1200
    assert len(native_lines) < 1800
    assert len(skill_status_lines) < 700
    text = "\n".join(lines)
    hermes_text = "\n".join(hermes_lines)
    native_text = "\n".join(native_lines)
    skill_status_text = "\n".join(skill_status_lines)
    assert "EXPERIENCE_GOVERNANCE_CONTRACT" in text
    assert "def configure_experience_governance(" in text
    assert "def apply_experience_service_xingce_adoption(" in text
    assert "def apply_experience_service_case_memory_rollback(" in text
    assert "def apply_experience_service_hermes_upgrade_input(" in text
    assert "def get_zhiyi_experience_summary(" in text
    assert "def query_hermes_feedback_candidates(" not in text
    assert "def apply_hermes_feedback_candidate_action(" not in text
    assert "def query_hermes_feedback_candidates(" in hermes_text
    assert "def apply_hermes_feedback_candidate_action(" in hermes_text
    assert "def build_hermes_native_learning_liveness(" in native_text
    assert "def build_hermes_skill_artifact_status_dry_run(" not in native_text
    assert "def build_hermes_skill_artifact_status_dry_run(" in skill_status_text
    assert p6_experience_governance.query_hermes_feedback_candidates is p6_experience_hermes_feedback.query_hermes_feedback_candidates
    assert p6_experience_governance.apply_hermes_feedback_candidate_action is p6_experience_hermes_feedback.apply_hermes_feedback_candidate_action
    assert hermes_native_liveness.build_hermes_skill_artifact_status_dry_run is hermes_skill_artifact_status.build_hermes_skill_artifact_status_dry_run
    assert hermes_native_liveness.record_hermes_skill_artifact_status is hermes_skill_artifact_status.record_hermes_skill_artifact_status


def test_zhiyi_model_runtime_delegates_usage_log_observation_under_tiandao():
    import importlib
    import p6_zhiyi_model_runtime

    usage_log_module = importlib.import_module(
        p6_zhiyi_model_runtime.build_zhiyi_usage_log_dry_run.__module__
    )

    runtime_path = SRC / "p6_zhiyi_model_runtime.py"
    usage_log_path = SRC / "p6_zhiyi_usage_log.py"
    runtime_text = runtime_path.read_text(encoding="utf-8")
    usage_log_text = usage_log_path.read_text(encoding="utf-8")
    runtime_lines = runtime_text.splitlines()
    usage_log_lines = usage_log_text.splitlines()

    assert len(runtime_lines) < 1800
    assert len(usage_log_lines) < 800
    assert "def build_zhiyi_model_binding_plan(" in runtime_text
    assert "def build_zhiyi_usage_log_dry_run(" not in runtime_text
    assert "def build_zhiyi_usage_log_dry_run(" in usage_log_text
    assert "def get_zhiyi_usage_light_prompt_policy(" in usage_log_text
    assert usage_log_module.get_zhiyi_usage_log_contract()["contract"] == "tiandao_zhiyi_usage_log_observation.v1"
    assert (
        p6_zhiyi_model_runtime.build_zhiyi_usage_log_dry_run
        is usage_log_module.build_zhiyi_usage_log_dry_run
    )
    assert (
        p6_zhiyi_model_runtime.query_zhiyi_usage_log_dry_run
        is usage_log_module.query_zhiyi_usage_log_dry_run
    )
    assert p6_zhiyi_model_runtime._usage_log_positive_int is usage_log_module._usage_log_positive_int


def test_claude_desktop_connector_is_tiandao_source_inlet_not_raw_origin():
    import claude_desktop_connector
    import claude_desktop_raw_ingest

    connector_contract = claude_desktop_connector.get_claude_desktop_connector_contract()
    assert connector_contract["ok"] is True
    assert connector_contract["contract"] == "tiandao_claude_desktop_source_connector.v1"
    assert connector_contract["parent_tiandao_contract"] == "tiandao_time_river.v1"
    assert connector_contract["connector_layer"] == "platform_source_inlet"
    assert connector_contract["source_system"] == "claude_desktop"
    assert connector_contract["not_raw_origin"] is True
    assert connector_contract["raw_write_performed"] is False
    assert connector_contract["memory_write_performed"] is False
    assert connector_contract["platform_write_performed"] is False
    assert connector_contract["subcontracts"] == [
        "tiandao_claude_desktop_raw_ingest_connector.v1",
    ]

    ingest_contract = claude_desktop_raw_ingest.get_claude_desktop_raw_ingest_contract()
    assert ingest_contract["ok"] is True
    assert ingest_contract["contract"] == "tiandao_claude_desktop_raw_ingest_connector.v1"
    assert ingest_contract["parent_tiandao_contract"] == "tiandao_time_river.v1"
    assert ingest_contract["connector_layer"] == "platform_raw_ingest_inlet"
    assert ingest_contract["not_raw_origin"] is True
    assert ingest_contract["read_only_by_default"] is True
    assert ingest_contract["authorization_required_for_write"] is True
    assert ingest_contract["raw_write_performed"] is False
    assert ingest_contract["memory_write_performed"] is False
    assert ingest_contract["platform_write_performed"] is False
    assert "time_library_raw_jsonl_mirror" in ingest_contract["authorized_write_scopes"]

    connector_lines = (SRC / "claude_desktop_connector.py").read_text(encoding="utf-8").splitlines()
    raw_ingest_lines = (SRC / "claude_desktop_raw_ingest.py").read_text(encoding="utf-8").splitlines()
    assert len(connector_lines) < 2600
    assert len(raw_ingest_lines) < 2200
    assert "def raw_ingest_dry_run(" not in "\n".join(connector_lines)
    assert "def raw_ingest_dry_run(" in "\n".join(raw_ingest_lines)


def test_platform_registry_is_orchestration_entry_not_guard_core_owner():
    import platform_thin_adapter_registry as registry

    registry_path = SRC / "platform_thin_adapter_registry.py"
    core_path = SRC / "platform_thin_adapter_core.py"
    catalog_path = SRC / "platform_guard_catalog.py"
    package_inventory_path = SRC / "platform_guard_package_inventory.py"
    model_identity_path = SRC / "platform_guard_model_identity.py"
    surface_scan_path = SRC / "platform_guard_surface_scan.py"
    registry_lines = registry_path.read_text(encoding="utf-8").splitlines()
    core_lines = core_path.read_text(encoding="utf-8").splitlines()
    catalog_lines = catalog_path.read_text(encoding="utf-8").splitlines()
    package_inventory_lines = package_inventory_path.read_text(encoding="utf-8").splitlines()
    model_identity_lines = model_identity_path.read_text(encoding="utf-8").splitlines()
    surface_scan_lines = surface_scan_path.read_text(encoding="utf-8").splitlines()

    assert len(registry_lines) < 1500
    assert len(core_lines) < 200
    assert len(catalog_lines) < 2000
    assert len(package_inventory_lines) < 600
    assert len(model_identity_lines) < 1500
    assert len(surface_scan_lines) < 1800
    assert registry.get_platform_guard_core_contract()["contract"] == "tiandao_platform_guard_core.v1"
    assert registry.get_platform_guard_catalog_contract()["contract"] == "tiandao_platform_guard_catalog.v1"
    assert registry.get_platform_guard_package_inventory_contract()["contract"] == "tiandao_platform_guard_package_inventory.v1"
    assert registry.get_platform_guard_model_identity_contract()["contract"] == "tiandao_platform_guard_model_identity.v1"
    assert registry.get_platform_guard_surface_scan_contract()["contract"] == "tiandao_platform_guard_surface_scan.v1"
    assert registry.build_thin_adapter_registry(include_generic=False)["contract"] == "thin_adapter_registry.v1"
    assert registry.build_package_manager_agent_inventory.__module__.endswith("platform_guard_package_inventory")


def test_raw_record_guardian_delegates_canonical_index_under_tiandao():
    import raw_record_backfill
    import raw_record_canonical_index
    import raw_record_guardian

    contract = raw_record_canonical_index.get_raw_record_canonical_index_contract()
    assert contract["ok"] is True
    assert contract["contract"] == "tiandao_raw_record_canonical_index.v1"
    assert contract["index_contract"] == "canonical_record_index.v2"
    assert contract["parent_tiandao_contract"] == "tiandao_time_river.v1"
    assert contract["index_layer"] == "canonical_record_index"
    assert contract["source_authority"] == "raw_record_guardian"
    assert contract["not_raw_origin"] is True
    assert contract["raw_write_performed"] is False
    assert contract["memory_write_performed"] is False
    assert contract["platform_write_performed"] is False

    backfill_contract = raw_record_backfill.get_raw_record_backfill_contract()
    assert backfill_contract["ok"] is True
    assert backfill_contract["contract"] == "tiandao_raw_record_backfill_repair.v1"
    assert backfill_contract["backfill_contract"] == "raw_record_backfill.v1"
    assert backfill_contract["parent_tiandao_contract"] == "tiandao_time_river.v1"
    assert backfill_contract["repair_layer"] == "raw_record_backfill"
    assert backfill_contract["source_authority"] == "raw_record_guardian"
    assert backfill_contract["not_raw_origin"] is True
    assert backfill_contract["read_only_by_default"] is True
    assert backfill_contract["write_capable"] is True
    assert backfill_contract["write_performed"] is False
    assert backfill_contract["raw_write_performed"] is False
    assert backfill_contract["memory_write_performed"] is False
    assert backfill_contract["platform_write_performed"] is False
    assert backfill_contract["authorization_required_for_write"] is True
    assert backfill_contract["divergence_generation_policy"] == (
        "connector_owned_ingest_only; direct_openclaw_backfill_retains_divergent_raw"
    )

    guardian_path = SRC / "raw_record_guardian.py"
    canonical_index_path = SRC / "raw_record_canonical_index.py"
    backfill_path = SRC / "raw_record_backfill.py"
    guardian_text = guardian_path.read_text(encoding="utf-8")
    canonical_text = canonical_index_path.read_text(encoding="utf-8")
    backfill_text = backfill_path.read_text(encoding="utf-8")
    guardian_lines = guardian_text.splitlines()
    canonical_lines = canonical_text.splitlines()
    backfill_lines = backfill_text.splitlines()

    assert len(guardian_lines) < 2200
    assert len(canonical_lines) < 1800
    assert len(backfill_lines) < 700
    assert "def build_guardian_status(" in guardian_text
    assert "def update_records_index(" not in guardian_text
    assert "def query_records_index(" not in guardian_text
    assert "def run_raw_backfill(" not in guardian_text
    assert "def _hermes_backfill(" not in guardian_text
    assert "def update_records_index(" in canonical_text
    assert "def query_records_index(" in canonical_text
    assert "def run_raw_backfill(" in backfill_text
    assert "def _hermes_backfill(" in backfill_text
    assert raw_record_guardian.update_records_index is raw_record_canonical_index.update_records_index
    assert raw_record_guardian.query_records_index is raw_record_canonical_index.query_records_index
    assert raw_record_guardian.run_raw_backfill is raw_record_backfill.run_raw_backfill
    assert raw_record_guardian._write_jsonl_atomic is raw_record_backfill._write_jsonl_atomic


def test_raw_consumption_gateway_delegates_raw_evidence_excerpt_under_tiandao():
    import importlib
    import raw_consumption_gateway

    raw_evidence_excerpt = importlib.import_module(raw_consumption_gateway._extract_bounded_raw_excerpt.__module__)

    contract = raw_evidence_excerpt.get_raw_evidence_excerpt_contract()
    assert contract["ok"] is True
    assert contract["contract"] == "tiandao_raw_evidence_excerpt_reader.v1"
    assert contract["parent_tiandao_contract"] == "tiandao_time_river.v1"
    assert contract["reader_layer"] == "raw_evidence_excerpt"
    assert contract["source_authority"] == "raw_record_guardian"
    assert contract["not_raw_origin"] is True
    assert contract["read_only_by_default"] is True
    assert contract["raw_write_performed"] is False
    assert contract["memory_write_performed"] is False
    assert contract["platform_write_performed"] is False
    assert "bounded_reader_cursor_cache" in contract["writes_limited_to"]

    gateway_path = SRC / "raw_consumption_gateway.py"
    excerpt_path = SRC / "raw_evidence_excerpt.py"
    response_budget_path = SRC / "raw_recall_response_budget.py"
    gateway_text = gateway_path.read_text(encoding="utf-8")
    excerpt_text = excerpt_path.read_text(encoding="utf-8")
    response_budget_text = response_budget_path.read_text(encoding="utf-8")
    gateway_lines = gateway_text.splitlines()
    excerpt_lines = excerpt_text.splitlines()

    assert len(gateway_lines) < 2700
    assert len(excerpt_lines) < 900
    assert "def query_raw_source_refs(" in gateway_text
    assert "def _extract_bounded_raw_excerpt(" not in gateway_text
    assert "def _extract_bounded_raw_excerpt(" in excerpt_text
    assert "def compact_recall_payload(" not in gateway_text
    assert "def compact_recall_payload(" in response_budget_text
    assert "class Handler(BaseHTTPRequestHandler):" in gateway_text
    assert "class Handler(BaseHTTPRequestHandler):" not in excerpt_text
    assert raw_consumption_gateway._extract_bounded_raw_excerpt is raw_evidence_excerpt._extract_bounded_raw_excerpt
    assert raw_consumption_gateway._raw_segment_state_dir is raw_evidence_excerpt._raw_segment_state_dir
    assert raw_consumption_gateway.get_raw_evidence_excerpt_contract is raw_evidence_excerpt.get_raw_evidence_excerpt_contract
