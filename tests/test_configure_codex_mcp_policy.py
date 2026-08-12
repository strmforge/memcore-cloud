from pathlib import Path

from tools.configure_codex_mcp_policy import configure_codex_mcp_policy


def _fixture(tmp_path: Path) -> tuple[Path, Path]:
    install = tmp_path / "time-library"
    (install / "tools").mkdir(parents=True)
    (install / "config").mkdir()
    bridge = install / "tools" / "codex_mcp_bridge.py"
    bridge.write_text("# fixture bridge\n", encoding="utf-8")
    (install / "config" / "window_binding_registry.json").write_text("{}\n", encoding="utf-8")
    config = tmp_path / "codex" / "config.toml"
    config.parent.mkdir()
    config.write_text(
        f'''[mcp_servers.time-library]\ncommand = "/opt/python"\nargs = ["{bridge}"]\n\n''',
        encoding="utf-8",
    )
    return install, config


def test_legacy_policy_entry_point_delegates_to_guard(tmp_path: Path):
    install, config = _fixture(tmp_path)

    result = configure_codex_mcp_policy(config)
    updated = config.read_text(encoding="utf-8")

    assert result["ok"] is True
    assert result["implementation"] == "codex_mcp_config_guard"
    assert result["deprecated"] is True
    assert "[mcp_servers.time-library.tools.time_library_recall]" in updated
    assert "[mcp_servers.time-library.tools.time_library_delivery_ack]" in updated
    assert updated.count('approval_mode = "approve"') == 2
    assert "time_library_reading_area" not in updated
    assert (tmp_path / "codex/config.toml.time-library-mcp-guard.backup").exists()


def test_legacy_policy_entry_point_is_idempotent(tmp_path: Path):
    _, config = _fixture(tmp_path)

    first = configure_codex_mcp_policy(config)
    after_first = config.read_bytes()
    second = configure_codex_mcp_policy(config)

    assert first["changed"] is True
    assert second["ok"] is True
    assert second["changed"] is False
    assert config.read_bytes() == after_first


def test_legacy_policy_entry_point_preserves_existing_tool_fields(tmp_path: Path):
    _, config = _fixture(tmp_path)
    config.write_text(
        config.read_text(encoding="utf-8")
        + '''[mcp_servers."time-library".tools.time_library_recall]\nenabled = true\napproval_mode = "prompt"\n''',
        encoding="utf-8",
    )

    result = configure_codex_mcp_policy(config)
    updated = config.read_text(encoding="utf-8")

    assert result["ok"] is True
    assert "enabled = true" in updated
    assert 'approval_mode = "prompt"' not in updated
    assert updated.count('approval_mode = "approve"') == 2


def test_legacy_policy_entry_point_refuses_missing_or_unowned_server(tmp_path: Path):
    config = tmp_path / "config.toml"
    config.write_text('[mcp_servers.other]\ncommand = "other"\n', encoding="utf-8")

    result = configure_codex_mcp_policy(config)

    assert result["ok"] is False
    assert result["error"] == "codex_mcp_server_section_missing"
    assert result["write_performed"] is False
    assert config.read_text(encoding="utf-8") == '[mcp_servers.other]\ncommand = "other"\n'


def test_legacy_policy_entry_point_refuses_relative_or_foreign_bridge(tmp_path: Path):
    config = tmp_path / "config.toml"
    original = (
        '[mcp_servers.time-library]\n'
        'command = "/bin/echo"\n'
        'args = ["codex_mcp_bridge.py"]\n'
    )
    config.write_text(original, encoding="utf-8")

    result = configure_codex_mcp_policy(config)

    assert result["ok"] is False
    assert result["error"] == "codex_mcp_guard_required"
    assert result["write_performed"] is False
    assert config.read_text(encoding="utf-8") == original
