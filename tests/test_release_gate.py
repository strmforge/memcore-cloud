import ast
import importlib.util
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RELEASE_GATE = ROOT / "tools" / "release_gate.py"


def _load_release_gate():
    spec = importlib.util.spec_from_file_location("release_gate_under_test", RELEASE_GATE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_release_gate_uses_clean_head_archive_by_default():
    gate = _load_release_gate()
    text = RELEASE_GATE.read_text(encoding="utf-8")

    assert 'default="head"' in text
    assert '"git", "archive"' in text
    assert "HEAD" in text
    assert "working-tree" in text
    assert "copy_working_tree" in text
    assert "--exclude-standard" in text
    assert "shutil.copy2" in text
    assert "PRIVATE_RELEASE_PREFIXES" in text
    assert "PRIVATE_RELEASE_PATHS" in text
    assert "FORBIDDEN_RUNTIME_DATA_PREFIXES" in text
    assert "LOCAL_PRIVATE_DENYLIST_PATHS" in text
    assert "TIME_LIBRARY_PRIVATE_RELEASE_DENYLIST" in text
    assert "FAKE_PRESET_TERMS" in text
    assert "assert_no_public_surface_terms" in text
    assert "assert_no_private_release_paths" in text
    assert "assert_no_runtime_data_paths" in text
    assert "assert_no_private_denylist_terms_in_repository" in text
    assert "PRIVATE_TOP_LEVEL_FILES" in text
    assert "assert_no_private_top_level_files" in text
    assert "PRIVATE_RELEASE_PREFIXES" in text
    assert "assert_no_private_release_prefixes" in text
    assert "FORBIDDEN_PUBLIC_EVAL_PATHS" in text
    assert "assert_no_public_eval_payload" in text
    assert "assert_product_src_does_not_import_eval" in text
    assert "assert_runtime_version_uses_version_file" in text
    assert "PERSONAL_IDENTITY_TERMS" in text
    assert "assert_no_personal_identity_terms" in text
    assert "LOB_CREDENTIAL_SHAPE" in text
    assert "assert_no_lob_credential_shapes" in text
    assert tuple(gate.PRIVATE_TOP_LEVEL_FILES) == (
        "AGENTS.md",
        "CODEX_CONTINUITY_LEDGER.md",
        "design-qa.md",
        "known-issues.md",
    )
    assert tuple(gate.PRIVATE_RELEASE_PREFIXES) == (
        "docs/construction/",
        "docs/decisions/",
        "docs/fixtures/",
        "docs/internal/",
        "docs/releases/",
        "system/skills/" + "yifan" + "chen" + "-zhiyi" + "/",
    )
    assert "config/private_release_denylist.local.txt" in tuple(gate.PRIVATE_RELEASE_PATHS)
    assert "src/tiandao/source_canon.py" not in tuple(gate.PRIVATE_RELEASE_PATHS)
    assert "config/window_binding_registry.json" in tuple(gate.PRIVATE_RELEASE_PATHS)
    assert "input/" in tuple(gate.FORBIDDEN_RUNTIME_DATA_PREFIXES)
    assert "zhiyi/" in tuple(gate.FORBIDDEN_RUNTIME_DATA_PREFIXES)
    assert "复" + "盘：多横态" in tuple(gate.FAKE_PRESET_TERMS)
    assert "yang" + "haibin" in tuple(gate.PERSONAL_IDENTITY_TERMS)
    assert "src/official_memory_benchmarks.py" in tuple(gate.FORBIDDEN_PUBLIC_EVAL_PATHS)
    assert "tools/model_memory_judge.py" in tuple(gate.FORBIDDEN_PUBLIC_EVAL_PATHS)
    assert "benchmarks/README.md" in tuple(gate.FORBIDDEN_PUBLIC_EVAL_PATHS)
    assert "official_memory_benchmarks" in tuple(gate.FORBIDDEN_PRODUCT_IMPORT_MODULES)
    assert "benchmarks" in tuple(gate.FORBIDDEN_PRODUCT_IMPORT_MODULES)
    assert "web/console_product.html" in tuple(gate.RUNTIME_VERSION_SURFACE_PATHS)
    assert "src/raw_consumption_gateway.py" in tuple(gate.RUNTIME_VERSION_SURFACE_PATHS)
    assert tuple(gate.PUBLIC_DOCS) == (
        "README.md",
        "README.en.md",
        "README.zh-CN.md",
        "docs/wiki/Getting-Started.md",
    )
    surface_paths = tuple(gate.PUBLIC_SURFACE_PATHS)
    assert "tools/macos_menu_bar.swift" in surface_paths
    assert "tools/windows_native_smoke.ps1" in surface_paths
    assert "tools/windows_full_install.ps1" in surface_paths
    assert "docs" in surface_paths
    assert "Time Library Installer.command" in surface_paths
    assert "Time Library Installer.cmd" in surface_paths
    assert "uninstall.sh" in surface_paths
    assert "uninstall.ps1" in surface_paths


def test_release_gate_guards_public_install_and_authorization_terms():
    gate = _load_release_gate()
    terms = tuple(gate.PUBLIC_FORBIDDEN_TERMS)
    repo_terms = tuple(gate.REPOSITORY_FORBIDDEN_TERMS)

    assert gate._term("CC", " Switch") in terms
    assert gate._term("cc", "switch") in terms
    assert gate._term("cc", "-switch") in terms
    assert gate._term("or", "phan") in repo_terms
    assert gate._term("or", "phan raw") in repo_terms
    assert "raw.githubusercontent.com/strmforge/time-library/main/install" in terms
    assert "archive/refs/heads/main.zip" in terms
    assert "time-library-main.zip" in terms
    assert "| bash" in terms
    assert "| iex" in terms
    assert "can_auto_connect_without_authorization" in terms
    assert "can_write_platform_config_without_authorization" in terms
    assert "can_parse_chat_bodies_without_authorization" in terms
    assert gate._term("capability", " matrix") in terms
    assert gate._term("能力", "矩阵") in terms
    assert gate._term("hooks", " / MCP / REST") in terms
    assert gate._term("AGENTS", ".md") in terms
    assert gate._term("旧的", "游离记录") in terms


def test_release_gate_scans_uninstall_public_surface():
    gate = _load_release_gate()
    repo_paths = tuple(gate.REPOSITORY_WORDING_PATHS)

    assert "uninstall.sh" in repo_paths
    assert "uninstall.ps1" in repo_paths


def test_release_gate_runs_core_release_checks():
    text = RELEASE_GATE.read_text(encoding="utf-8")

    assert "requirements-core.txt" in text
    assert "requirements-dev.txt" in text
    assert "py_compile" in text
    assert "run_internal_direction_audit" in text
    assert "tools\" / \"internal_direction_audit.py" in text
    assert "run_core_record_reliability_contract" in text
    assert "tools\" / \"core_record_reliability_audit.py" in text
    assert "--contract-only" in text
    assert '"--format", "json"' in text
    assert "DEFAULT_RELEASE_PYTEST_ARGS" in text
    assert "tests/test_release_artifact.py" in text
    assert "tests/test_security_boundaries.py" in text
    assert "test_mcp_default_recall_surfaces_recent_delta_freshness_telemetry" in text
    assert "test_raw_gateway_recent_delta_normalizes_session_window_without_platform_declaration" in text
    assert '["bash", "-n", "install.sh"]' in text
    assert '["bash", "-n", "Time Library Installer.command"]' in text
    assert '["bash", "-n", "tools/macos_full_install.sh"]' in text
    assert '["bash", "-n", "tools/linux_full_install.sh"]' in text
    assert "git diff" in text


def test_release_gate_default_pytest_suite_covers_release_risks():
    gate = _load_release_gate()
    args = tuple(gate.DEFAULT_RELEASE_PYTEST_ARGS)

    assert "tests/test_release_artifact.py" in args
    assert "tests/test_release_gate.py" in args
    assert "tests/test_public_experience_wording.py" in args
    assert "tests/test_console_product_boundary.py" in args
    assert "tests/test_zhiyi_skill_package.py" in args
    assert "tests/test_security_boundaries.py" in args
    assert "tests/test_release_truthfulness.py" in args
    assert "tests/test_hermes_autonomous_loop.py" in args
    assert any("test_raw_gateway_default_recall_uses_saved_bge_preference" in item for item in args)
    assert any("test_mcp_default_recall_surfaces_recent_delta_freshness_telemetry" in item for item in args)
    assert any("test_raw_gateway_recent_delta_normalizes_session_window_without_platform_declaration" in item for item in args)
    assert args[-1] == "-q"


def test_release_gate_default_pytest_node_ids_exist():
    gate = _load_release_gate()

    for arg in gate.DEFAULT_RELEASE_PYTEST_ARGS:
        if "::" not in arg:
            continue
        relative, node_id = arg.split("::", 1)
        path = ROOT / relative
        assert path.is_file(), relative
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        functions = {
            node.name
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        assert node_id in functions, arg


def test_local_connectors_explicitly_enable_divergence_generations_on_ingest_paths():
    def call_name(call):
        func = call.func
        if isinstance(func, ast.Name):
            return func.id
        if isinstance(func, ast.Attribute):
            return func.attr
        return ""

    def catches_oserror(handler):
        names = set()
        for node in ast.walk(handler.type) if handler.type is not None else ():
            if isinstance(node, ast.Name):
                names.add(node.id)
            elif isinstance(node, ast.Attribute):
                names.add(node.attr)
        return "OSError" in names

    connector_paths = sorted((ROOT / "src").glob("*_local_connector.py"))
    assert connector_paths
    guarded_calls = 0
    for path in connector_paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        oserror_calls = {
            id(call)
            for handler in ast.walk(tree)
            if isinstance(handler, ast.ExceptHandler) and catches_oserror(handler)
            for statement in handler.body
            for call in ast.walk(statement)
            if isinstance(call, ast.Call) and call_name(call) == "append_source_file"
        }
        for call in ast.walk(tree):
            if not isinstance(call, ast.Call) or call_name(call) != "append_source_file":
                continue
            policy = next(
                (keyword.value for keyword in call.keywords if keyword.arg == "continue_on_divergence"),
                None,
            )
            location = f"{path.relative_to(ROOT)}:{call.lineno}"
            if id(call) in oserror_calls:
                assert not (
                    isinstance(policy, ast.Constant) and policy.value is True
                ), f"{location} must stay fail-closed when source stat raises OSError"
                continue
            guarded_calls += 1
            assert isinstance(policy, ast.Constant) and policy.value is True, (
                f"{location} must explicitly pass continue_on_divergence=True"
            )
    assert guarded_calls >= 3


def test_release_gate_rejects_private_top_level_agent_rules(tmp_path):
    gate = _load_release_gate()
    (tmp_path / "AGENTS.md").write_text("private local agent rules", encoding="utf-8")

    try:
        gate.assert_no_private_top_level_files(tmp_path)
    except SystemExit as exc:
        assert "AGENTS.md" in str(exc)
    else:
        raise AssertionError("release gate allowed private AGENTS.md in public source")


def test_release_gate_rejects_private_construction_docs(tmp_path):
    gate = _load_release_gate()
    path = tmp_path / "docs" / "decisions"
    path.mkdir(parents=True)
    (path / "local-plan.md").write_text("private local decision", encoding="utf-8")

    try:
        gate.assert_no_private_release_prefixes(tmp_path)
    except SystemExit as exc:
        assert "docs/decisions/" in str(exc)
    else:
        raise AssertionError("release gate allowed private construction docs in public source")


def test_release_gate_rejects_private_release_paths(tmp_path):
    gate = _load_release_gate()
    path = tmp_path / "config" / "window_binding_registry.json"
    path.parent.mkdir(parents=True)
    path.write_text("{}", encoding="utf-8")

    try:
        gate.assert_no_private_release_paths(tmp_path)
    except SystemExit as exc:
        assert "window_binding_registry.json" in str(exc)
    else:
        raise AssertionError("release gate allowed a private runtime binding path")


def test_release_gate_rejects_tracked_runtime_or_memory_data(tmp_path):
    gate = _load_release_gate()
    path = tmp_path / "zhiyi" / "case_memory" / "case_memory.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text("{}\n", encoding="utf-8")

    try:
        gate.assert_no_runtime_data_paths(tmp_path)
    except SystemExit as exc:
        assert "zhiyi/" in str(exc)
    else:
        raise AssertionError("release gate allowed tracked memory data")


def test_release_gate_rejects_blocked_public_surface_terms(tmp_path):
    gate = _load_release_gate()
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "public.md").write_text("preset task: " + ("AI" + " Act") + " notes", encoding="utf-8")

    try:
        gate.assert_no_public_surface_terms(tmp_path)
    except SystemExit as exc:
        assert "blocked public-surface term" in str(exc)
    else:
        raise AssertionError("release gate allowed private project or LAN terms")


def test_release_gate_rejects_local_private_denylist_terms(tmp_path, monkeypatch):
    gate = _load_release_gate()
    docs = tmp_path / "docs"
    docs.mkdir()
    local_private_term = "private-project-codename-alpha"
    (docs / "public.md").write_text(f"project={local_private_term}", encoding="utf-8")
    monkeypatch.setenv("TIME_LIBRARY_PRIVATE_RELEASE_DENYLIST", local_private_term)

    try:
        gate.assert_no_public_surface_terms(tmp_path)
    except SystemExit as exc:
        assert "blocked public-surface term" in str(exc)
    else:
        raise AssertionError("release gate allowed a locally denied private term")


def test_release_gate_rejects_repository_private_denylist_terms(tmp_path, monkeypatch):
    gate = _load_release_gate()
    src = tmp_path / "src"
    src.mkdir()
    local_private_term = "private-repository-codename-alpha"
    (src / "public_module.py").write_text(f"NAME = {local_private_term!r}", encoding="utf-8")
    monkeypatch.setenv("TIME_LIBRARY_PRIVATE_RELEASE_DENYLIST", local_private_term)

    try:
        gate.assert_no_private_denylist_terms_in_repository(tmp_path)
    except SystemExit as exc:
        assert "private denylist term" in str(exc)
    else:
        raise AssertionError("release gate allowed a private term in tracked repository source")


def test_release_gate_does_not_embed_real_private_terms_in_source():
    text = RELEASE_GATE.read_text(encoding="utf-8")
    forbidden = (
        "南" + "天" + "门",
        "洪" + "荒",
        "京" + "造",
        "windows" + "123",
        "windows" + "191",
        "192." + "168." + "50.",
    )
    assert not any(term in text for term in forbidden)


def test_release_gate_rejects_personal_identity_terms(tmp_path):
    gate = _load_release_gate()
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "public.md").write_text("path=/" + "Users" + "/" + "yang" + "haibin" + "/Downloads", encoding="utf-8")

    try:
        gate.assert_no_personal_identity_terms(tmp_path)
    except SystemExit as exc:
        assert "personal identity" in str(exc)
    else:
        raise AssertionError("release gate allowed a personal identity term in public source")


def test_release_gate_rejects_lob_credential_shapes_without_echoing_value(tmp_path):
    gate = _load_release_gate()
    src = tmp_path / "src"
    src.mkdir()
    candidate = ("li" + "ve_") + ("a" * 35)
    (src / "public_module.py").write_text(f"VALUE = {candidate!r}\n", encoding="utf-8")

    try:
        gate.assert_no_lob_credential_shapes(tmp_path)
    except SystemExit as exc:
        message = str(exc)
        assert "src/public_module.py:1" in message
        assert "Lob credential-shaped value" in message
        assert candidate not in message
    else:
        raise AssertionError("release gate allowed a Lob credential-shaped value")


def test_release_gate_requires_neutral_license_identity(tmp_path):
    gate = _load_release_gate()
    license_path = tmp_path / "LICENSE"
    license_path.write_text(
        "MIT License\n\nCopyright (c) 2026 " + "Named" + " Person\n",
        encoding="utf-8",
    )

    try:
        gate.assert_neutral_license_identity(tmp_path)
    except SystemExit as exc:
        assert "neutral" in str(exc)
    else:
        raise AssertionError("release gate allowed a named LICENSE identity")

    license_path.write_text(
        "MIT License\n\nCopyright (c) 2026 Time Library contributors\n",
        encoding="utf-8",
    )
    gate.assert_neutral_license_identity(tmp_path)


def test_release_gate_rejects_public_eval_payload(tmp_path):
    gate = _load_release_gate()
    path = tmp_path / "src" / "official_memory_benchmarks.py"
    path.parent.mkdir()
    path.write_text("# internal eval", encoding="utf-8")

    try:
        gate.assert_no_public_eval_payload(tmp_path)
    except SystemExit as exc:
        assert "official_memory_benchmarks" in str(exc)
    else:
        raise AssertionError("release gate allowed eval source in public payload")


def test_release_gate_rejects_product_src_importing_eval(tmp_path):
    gate = _load_release_gate()
    path = tmp_path / "src" / "preflight_doctor.py"
    path.parent.mkdir()
    path.write_text("from src.official_memory_benchmarks import official_sources\n", encoding="utf-8")

    try:
        gate.assert_product_src_does_not_import_eval(tmp_path)
    except SystemExit as exc:
        assert "official_memory_benchmarks" in str(exc)
    else:
        raise AssertionError("release gate allowed product src to import eval modules")


def test_release_gate_rejects_runtime_version_hardcoding(tmp_path):
    gate = _load_release_gate()
    root = tmp_path
    (root / "VERSION").write_text("2099.7.8\n", encoding="utf-8")
    src_dir = root / "src"
    src_dir.mkdir()
    (src_dir / "__init__.py").write_text("", encoding="utf-8")
    (src_dir / "memcore_version.py").write_text(
        "\n".join([
            "from pathlib import Path",
            "def read_memcore_version(root=None, default='unknown'):",
            "    return (Path(root) / 'VERSION').read_text(encoding='utf-8').strip()",
            "SERVICE_VERSION = read_memcore_version(Path(__file__).resolve().parents[1])",
            "",
        ]),
        encoding="utf-8",
    )
    (root / "web").mkdir()
    (root / "web" / "console_product.html").write_text(
        '<span id="sidebar-version">2026.6.20</span>',
        encoding="utf-8",
    )

    try:
        gate.assert_runtime_version_uses_version_file(root, Path(sys.executable))
    except SystemExit as exc:
        assert "web/console_product.html" in str(exc)
    else:
        raise AssertionError("release gate allowed runtime version hardcoding")


def test_release_gate_includes_dialog_entry_install_safety_checks():
    text = RELEASE_GATE.read_text(encoding="utf-8")

    assert "tools/macos_full_install.sh" in text
    assert "tools/linux_full_install.sh" in text
