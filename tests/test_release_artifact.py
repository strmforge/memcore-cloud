import importlib.util
import shutil
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "build_release_artifact.py"


def _load_builder():
    spec = importlib.util.spec_from_file_location("build_release_artifact_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_release_artifact_builder_defaults_to_head_and_writes_zip_checksum():
    text = SCRIPT.read_text(encoding="utf-8")

    assert 'default="head"' in text
    assert "git\", \"archive\"" in text
    assert "working-tree" in text
    assert "git\", \"ls-files\"" in text
    assert ".sha256" in text
    assert "time-library-{version}" in text
    assert "time-library-release-artifact-" in text
    assert "memcore-release-artifact-" not in text
    assert "EXCLUDED_PATH_PARTS" in text
    assert "EXCLUDED_TOP_LEVEL_FILES" in text
    assert "EXCLUDED_RELATIVE_PATHS" in text
    assert "EXCLUDED_RELATIVE_PREFIXES" in text
    assert '"AGENTS.md"' in text
    assert '"CODEX_CONTINUITY_LEDGER.md"' in text
    assert '"known-issues.md"' in text
    assert '"docs/github-positioning-2026.6.16.md"' in text
    assert '"src/official_memory_benchmarks.py"' in text
    assert '"tools/model_memory_judge.py"' in text
    assert '"benchmarks/README.md"' in text
    assert '"benchmarks/eval-runs/"' in text
    assert '"docs/construction/"' in text
    assert '"docs/decisions/"' in text


def test_windows_pip_requirements_file_is_ascii():
    """Windows pip may decode requirements files with the active code page."""
    (ROOT / "requirements-core.txt").read_bytes().decode("ascii")


def test_release_artifact_working_tree_package_excludes_ignored_runtime_data(tmp_path):
    builder = _load_builder()
    if not (ROOT / ".git").exists():
        return

    result = builder.build_artifact(source="working-tree", output_dir=tmp_path)

    zip_path = Path(result["zip"])
    sha_path = Path(result["sha256"])
    assert zip_path.exists()
    assert sha_path.exists()
    assert result["checksum"] in sha_path.read_text(encoding="ascii")
    with zipfile.ZipFile(zip_path) as archive:
        names = archive.namelist()
        license_text = archive.read(next(name for name in names if name.endswith("/LICENSE"))).decode("utf-8")
    assert any(name.endswith("/VERSION") for name in names)
    assert "Copyright (c) 2026 Time Library contributors" in license_text
    assert not any(name.endswith("/tools/build_release_artifact.py") for name in names)
    assert any(name.endswith("/tools/build_fts5_recall_index.py") for name in names)
    assert any(name.endswith("/tools/runtime_profile.py") for name in names)
    assert any(name.endswith("/config/memcore.json") for name in names)
    assert any(name.endswith("/config/default_model_config.json") for name in names)
    assert any(name.endswith("/THIRD_PARTY_NOTICES.md") for name in names)
    assert any(name.endswith("/licenses/Apache-2.0.txt") for name in names)
    assert any(name.endswith("/src/granite_vector_assets.py") for name in names)
    assert any(name.endswith("/tools/prepare_granite_vector_assets.py") for name in names)
    assert any(name.endswith("/tools/install_config_merge.py") for name in names)
    assert any(name.endswith("/tools/install_runtime_identity.py") for name in names)
    assert any(name.endswith("/tools/install_runtime_quiescence.py") for name in names)
    assert any(name.endswith("/tools/install_transaction_snapshot.py") for name in names)
    assert any(name.endswith("/tools/codex_mcp_config_guard.py") for name in names)
    assert any(name.endswith("/tools/configure_codex_mcp_policy.py") for name in names)
    assert any(name.endswith("/tools/distill_transparency.py") for name in names)
    assert any(name.endswith("/tools/install_state_migrate.py") for name in names)
    assert any(name.endswith("/tools/macos_menu_bar.swift") for name in names)
    assert any(name.endswith("/tools/refresh_claude_desktop_mcp_bridges.py") for name in names)
    assert any(name.endswith("/tools/windows_native_smoke.ps1") for name in names)
    assert not any(name.endswith("/model.safetensors") for name in names)
    assert any(name.endswith("/config/default_feature_flags.json") for name in names)
    assert any(name.endswith("/config/intent_router_rules.json") for name in names)
    assert not any("/.git/" in name or name.endswith("/.checkpoint") for name in names)
    assert not any("/.release-gate-venv/" in name for name in names)
    assert not any("/memory/" in name or "/logs/" in name or "/output/" in name for name in names)
    assert not any("/input/" in name for name in names)
    assert not any("/runtime/" in name for name in names)
    assert not any("/tests/" in name for name in names)
    assert not any(name.endswith("/raw") for name in names)
    assert not any("/release/" in name for name in names)
    assert not any(name.endswith("/AGENTS.md") for name in names)
    assert not any(name.endswith("/CODEX_CONTINUITY_LEDGER.md") for name in names)
    assert not any(name.endswith("/known-issues.md") for name in names)
    assert not any("/docs/construction/" in name for name in names)
    assert not any("/docs/decisions/" in name for name in names)
    assert not any("/docs/fixtures/" in name for name in names)
    assert not any("/docs/internal/" in name for name in names)
    assert not any("/docs/releases/" in name for name in names)
    legacy_skill_dir = "/system/skills/" + "yifan" + "chen" + "-zhiyi" + "/"
    assert not any(legacy_skill_dir in name for name in names)
    legacy_logo_a = "yifan" + "chen" + "-logo"
    legacy_logo_b = "yifan" + "chen" + "_logo"
    assert not any(legacy_logo_a in name or legacy_logo_b in name for name in names)
    assert not any(name.endswith("/docs/github-positioning-2026.6.16.md") for name in names)
    assert any(name.endswith("/src/tiandao/source_canon.py") for name in names)
    assert any(name.endswith("/src/tiandao/time_twin_star_behavior_proof.json") for name in names)
    assert not any(name.endswith("/tools/core_record_multi_host_audit.py") for name in names)
    assert not any(name.endswith("/tools/code_change_tiandao_audit.py") for name in names)
    assert not any(name.endswith("/tools/time_twin_star_turn_loop_probe.py") for name in names)
    assert not any(name.endswith("/tools/time_twin_star_turn_loop_trace_gate.py") for name in names)
    assert not any(name.endswith("/tools/time_library_fleet_probe.py") for name in names)
    assert not any("/benchmarks/cache/" in name for name in names)
    assert not any("/benchmarks/eval-runs/" in name for name in names)
    assert not any("/benchmarks/results/" in name for name in names)
    assert not any(name.endswith("/benchmarks/README.md") for name in names)
    assert not any(name.endswith("/src/official_memory_benchmarks.py") for name in names)
    assert not any(name.endswith("/src/model_memory_judge.py") for name in names)
    assert not any(name.endswith("/tools/official_memory_benchmark.py") for name in names)
    assert not any(name.endswith("/tools/model_memory_judge.py") for name in names)
    assert not any(name.endswith("/config/window_binding_registry.json") for name in names)
    assert any(name.endswith("/assets/brand/time-library-logo-en.png") for name in names)
    assert any(name.endswith("/assets/brand/time-library-logo-zh.png") for name in names)
    assert any(name.endswith("/assets/brand/time-library-emblem.ico") for name in names)
    assert any(name.endswith("/assets/brand/time-library-emblem.icns") for name in names)
    assert any(name.endswith("/web/assets/time_library_logo_en.png") for name in names)
    assert any(name.endswith("/web/assets/time_library_logo_zh.png") for name in names)
    assert any(name.endswith("/web/assets/time_library_logo_en_sidebar.png") for name in names)
    assert any(name.endswith("/web/assets/time_library_logo_zh_sidebar.png") for name in names)
    assert any(name.endswith("/web/assets/time_library_emblem.ico") for name in names)
    assert any(name.endswith("/web/assets/time_library_emblem.icns") for name in names)

    forbidden_identity_terms = (
        "yang" + "haibin",
        "/" + "Users" + "/" + "yang" + "haibin",
        "yang" + "haibinde",
    )
    with zipfile.ZipFile(zip_path) as archive:
        for name in names:
            if not name.endswith((".css", ".html", ".json", ".js", ".md", ".ps1", ".py", ".sh", ".swift", ".txt", ".yml", ".yaml")):
                continue
            text = archive.read(name).decode("utf-8", errors="replace")
            assert not any(term in text for term in forbidden_identity_terms), name
            forbidden_preset_terms = (
                "AI" + " Act",
                "OpenAI" + " o3",
                "本地" + "数据库快照",
                "命中率" + "示例",
                "已用" + "示例容量",
                "128" + " GB",
                "example" + "-embed-model",
                "/" + "Volumes" + "/",
                "/" + "Users" + "/",
                "C:" + "/" + "Users" + "/",
                "C:" + "\\" + "Users" + "\\",
                "192." + "168.",
                "ssh-" + "192",
                "windows" + "123",
                "windows" + "191",
                "562" + "14",
                "南" + "天" + "门",
                "忆" + "凡" + "尘",
                "洪" + "荒",
                "京" + "造",
                "Project " + "Alpha",
                "shared " + "framework",
                "共享" + "规则",
                "yifan" + "chen",
                "memcore-" + "zhiyi-native",
                "memcore_" + "yifan" + "chen",
            )
            assert not any(term in text for term in forbidden_preset_terms), name


def test_release_artifact_can_package_gitless_snapshot(tmp_path, monkeypatch):
    builder = _load_builder()
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    shutil.copy2(ROOT / "VERSION", snapshot / "VERSION")
    (snapshot / "README.md").write_text("# Time Library\n", encoding="utf-8")
    private_dir = snapshot / "docs" / "construction"
    private_dir.mkdir(parents=True)
    (private_dir / "private.md").write_text("private", encoding="utf-8")

    monkeypatch.setattr(builder, "ROOT", snapshot)
    result = builder.build_artifact(source="working-tree", output_dir=tmp_path / "out")

    with zipfile.ZipFile(Path(result["zip"])) as archive:
        names = archive.namelist()

    assert any(name.endswith("/VERSION") for name in names)
    assert any(name.endswith("/README.md") for name in names)
    assert not any("/.git/" in name for name in names)
    assert not any("/docs/construction/" in name for name in names)


def test_release_artifact_contains_dialog_entry_lan_safety_contract(tmp_path):
    builder = _load_builder()
    if not (ROOT / ".git").exists():
        return

    result = builder.build_artifact(source="working-tree", output_dir=tmp_path)
    with zipfile.ZipFile(Path(result["zip"])) as archive:
        payload = {
            name.split("/", 1)[1]: archive.read(name).decode("utf-8")
            for name in archive.namelist()
            if name.endswith((
                "install.ps1",
                "Time Library Installer.command",
                "Time Library Installer.cmd",
                "tools/windows_full_install.ps1",
                "tools/windows_double_click_install.ps1",
                "tools/windows_guardian.ps1",
                "tools/macos_full_install.sh",
                "tools/linux_full_install.sh",
                "system/openclaw/plugins/time-library-native/index.js",
            ))
        }

    assert "DialogEntryHost" in payload["install.ps1"]
    assert "DialogEntryEndpointUrl" in payload["install.ps1"]
    assert "DialogEntryToken" in payload["install.ps1"]
    assert "bash ./install.sh" in payload["Time Library Installer.command"]
    assert "windows_double_click_install.ps1" in payload["Time Library Installer.cmd"]
    assert "FolderBrowserDialog" in payload["tools/windows_double_click_install.ps1"]
    assert "-Dir $installRoot" in payload["tools/windows_double_click_install.ps1"]
    assert "Ensure-DialogEntryToken" in payload["tools/windows_full_install.ps1"]
    assert "Backup-InstallFiles" in payload["tools/windows_full_install.ps1"]
    assert "Copy-Item -Path $InstallRoot -Destination $backup -Recurse -Force" not in payload["tools/windows_full_install.ps1"]
    assert '"memory", "raw", "zhiyi"' in payload["tools/windows_full_install.ps1"]
    assert "Get-DialogEntryHost" in payload["tools/windows_guardian.ps1"]
    assert "--host 127.0.0.1 --port $InternalDialogPort" in payload["tools/windows_guardian.ps1"]
    assert "ensure_dialog_entry_token" in payload["tools/macos_full_install.sh"]
    assert "ensure_dialog_entry_token" in payload["tools/linux_full_install.sh"]
    assert "dialogEntryToken" in payload["system/openclaw/plugins/time-library-native/index.js"]
    assert "headers.Authorization" in payload["system/openclaw/plugins/time-library-native/index.js"]
