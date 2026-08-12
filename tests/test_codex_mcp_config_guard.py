from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import time
from pathlib import Path

import tools.codex_mcp_config_guard as guard_module
from tools.codex_mcp_config_guard import reconcile_codex_mcp


ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / "tools" / "codex_mcp_config_guard.py"


def _fixture(tmp_path: Path) -> tuple[Path, Path]:
    install = tmp_path / "time-library"
    (install / "tools").mkdir(parents=True)
    (install / "config").mkdir()
    (install / "tools" / "codex_mcp_bridge.py").write_text("# fixture bridge\n", encoding="utf-8")
    (install / "config" / "window_binding_registry.json").write_text("{}\n", encoding="utf-8")
    config = tmp_path / "codex" / "config.toml"
    config.parent.mkdir()
    return install, config


def _managed_config(install: Path, python: str = "/opt/python") -> str:
    return f'''[mcp_servers.time-library]
command = "{python}"
args = ["{install / 'tools' / 'codex_mcp_bridge.py'}"]
'''


def _foreign_projection(config: Path) -> bytes:
    text = config.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    sections = guard_module._sections(
        lines,
        server="time-library",
        approved_tools=guard_module.DEFAULT_APPROVED_TOOLS,
    )
    managed = {
        "server",
        "legacy_env",
        "tool:time_library_recall",
        "tool:time_library_delivery_ack",
    }
    ranges = sorted((section.start, section.end) for section in sections if section.kind in managed)
    output: list[str] = []
    cursor = 0
    for start, end in ranges:
        output.extend(lines[cursor:start])
        cursor = end
    output.extend(lines[cursor:])
    return "".join(output).encode("utf-8")


def test_guard_preserves_relay_provider_and_other_mcp_on_first_registration(tmp_path: Path):
    install, config = _fixture(tmp_path)
    original_prefix = (
        '[model_providers.custom]\n'
        'name = "relay-provider"\n'
        'base_url = "http://127.0.0.1:15721/v1"\n'
        'wire_api = "responses"\n\n'
        '[mcp_servers.other]\n'
        'command = "other-server"\n'
    )
    config.write_text(original_prefix, encoding="utf-8")
    os.chmod(config, 0o600)

    result = reconcile_codex_mcp(config, install, python_executable="/opt/python", create_if_missing=True)
    updated = config.read_text(encoding="utf-8")

    assert result["ok"] is True
    assert result["changed"] is True
    assert updated.startswith(original_prefix)
    assert '[mcp_servers.time-library]' in updated
    assert 'codex_mcp_bridge.py' in updated
    assert '[mcp_servers.other]' in updated
    assert 'base_url = "http://127.0.0.1:15721/v1"' in updated
    assert stat.S_IMODE(config.stat().st_mode) == 0o600
    assert stat.S_IMODE((config.parent / "config.toml.time-library-mcp-guard.backup").stat().st_mode) == 0o600


def test_guard_recovers_after_repeated_external_full_file_replacement(tmp_path: Path):
    install, config = _fixture(tmp_path)
    provider = (
        '[model_providers.custom]\n'
        'name = "relay-provider"\n'
        'base_url = "http://127.0.0.1:15721/v1"\n'
        'model = "relay-model"\n'
    )
    config.write_text(provider, encoding="utf-8")

    for _ in range(20):
        result = reconcile_codex_mcp(config, install, python_executable="/opt/python")
        assert result["ok"] is True
        assert "[mcp_servers.time-library]" in config.read_text(encoding="utf-8")
        # This models a relay writing a fresh config that retains its own
        # provider settings but drops unknown MCP tables. Real relays commonly
        # publish a complete replacement through a temporary file.
        replacement_path = config.with_name(".relay-config.tmp")
        replacement_path.write_text(provider, encoding="utf-8")
        os.replace(replacement_path, config)

    final_result = reconcile_codex_mcp(config, install, python_executable="/opt/python")
    final = config.read_text(encoding="utf-8")
    assert final_result["ok"] is True
    assert final.startswith(provider)
    assert final.count("[mcp_servers.time-library]") == 1
    assert final.count("time_library_recall]") == 1
    assert final.count("time_library_delivery_ack]") == 1


def test_guard_full_file_replacement_preserves_foreign_projection_bytes(tmp_path: Path):
    install, config = _fixture(tmp_path)
    foreign = (
        '[model_providers.custom]\n'
        'name = "relay-provider"\n'
        'base_url = "http://127.0.0.1:15721/v1"\n\n'
        '[mcp_servers.other]\n'
        'command = "other-server"\n'
    )
    config.write_text(foreign, encoding="utf-8")
    assert reconcile_codex_mcp(config, install, python_executable="/opt/python")["ok"] is True

    replacement = config.with_name(".relay-config.tmp")
    replacement.write_text(foreign, encoding="utf-8")
    os.replace(replacement, config)
    foreign_before = _foreign_projection(config)

    result = reconcile_codex_mcp(config, install, python_executable="/opt/python")

    assert result["ok"] is True
    assert _foreign_projection(config) == foreign_before
    assert guard_module._parse_toml(config.read_text(encoding="utf-8"))[1] is None
    assert config.read_text(encoding="utf-8").count("[mcp_servers.time-library]") == 1


def test_guard_preserves_array_tables_after_owned_registration(tmp_path: Path):
    install, config = _fixture(tmp_path)
    bridge = install / "tools" / "codex_mcp_bridge.py"
    config.write_text(
        f'[mcp_servers.time-library]\n'
        f'command = "/opt/python"\n'
        f'args = ["{bridge}"]\n\n'
        '[[relay.routes]]\n'
        'name = "keep-me"\n'
        '[[relay.routes]]\n'
        'name = "keep-me-too"\n',
        encoding="utf-8",
    )

    result = reconcile_codex_mcp(config, install, python_executable="/opt/python")
    updated = config.read_text(encoding="utf-8")

    assert result["ok"] is True
    assert "[[relay.routes]]" in updated
    assert 'name = "keep-me"' in updated
    assert 'name = "keep-me-too"' in updated
    assert guard_module._parse_toml(updated)[1] is None


def test_guard_does_not_treat_multiline_string_content_as_table_headers(tmp_path: Path):
    install, config = _fixture(tmp_path)
    bridge = install / "tools" / "codex_mcp_bridge.py"
    config.write_text(
        f'[mcp_servers.time-library]\n'
        f'command = "/opt/python"\n'
        f'args = ["{bridge}"]\n\n'
        '[relay]\n'
        'instructions = """\n'
        '[mcp_servers.time-library.tools.time_library_recall]\n'
        'approval_mode = "foreign-text"\n'
        '"""\n',
        encoding="utf-8",
    )

    result = reconcile_codex_mcp(config, install, python_executable="/opt/python")
    updated = config.read_text(encoding="utf-8")

    assert result["ok"] is True
    assert 'approval_mode = "foreign-text"' in updated
    assert updated.count("[mcp_servers.time-library]") == 1
    assert guard_module._parse_toml(updated)[1] is None


def test_guard_is_idempotent_and_does_not_duplicate_owned_tables(tmp_path: Path):
    install, config = _fixture(tmp_path)
    config.write_text(_managed_config(install), encoding="utf-8")

    first = reconcile_codex_mcp(config, install, python_executable="/opt/python")
    after_first = config.read_bytes()
    second = reconcile_codex_mcp(config, install, python_executable="/opt/python")

    assert first["ok"] is True
    assert second == {
        "ok": True,
        "changed": False,
        "write_performed": False,
        "backup_created": False,
        "server": "time-library",
        "reason": "already_current",
    }
    assert config.read_bytes() == after_first
    assert after_first.count(b"[mcp_servers.time-library]") == 1


def test_guard_migrates_owned_legacy_env_subtable_and_preserves_other_servers(tmp_path: Path):
    install, config = _fixture(tmp_path)
    bridge = install / "tools" / "codex_mcp_bridge.py"
    config.write_text(
        f'[mcp_servers.time-library]\n'
        f'command = "/opt/python"\n'
        f'args = ["{bridge}"]\n\n'
        '[mcp_servers.time-library.env]\n'
        'PYTHONUTF8 = "1"\n'
        'MEMCORE_ROOT = "/old/root"\n\n'
        '[mcp_servers.time-library.tools.time_library_recall]\n'
        'approval_mode = "approve"\n\n'
        '[mcp_servers.other]\n'
        'command = "other-server"\n',
        encoding="utf-8",
    )

    result = reconcile_codex_mcp(config, install, python_executable="/opt/python")
    updated = config.read_text(encoding="utf-8")

    assert result["ok"] is True
    assert result["reason"] == "reconciled"
    assert "[mcp_servers.time-library.env]" not in updated
    assert "env = {" in updated
    assert updated.count("[mcp_servers.time-library]") == 1
    assert '[mcp_servers.other]\ncommand = "other-server"' in updated
    assert guard_module._parse_toml(updated)[1] is None


def test_guard_fails_closed_for_malformed_duplicate_or_foreign_config(tmp_path: Path):
    install, config = _fixture(tmp_path)
    cases = (
        ("[model_providers.custom\n", "invalid_toml"),
        (
            _managed_config(install) + "\n[mcp_servers.time-library]\ncommand = \"other\"\n",
            "invalid_toml",
        ),
        (
            '[mcp_servers.time-library]\ncommand = "/bin/echo"\nargs = ["other"]\n',
            "codex_mcp_server_name_conflict",
        ),
        (
            '[mcp_servers.time-library.extra]\nPYTHONUTF8 = "1"\n',
            "unexpected_codex_mcp_subsection",
        ),
        (
            '[mcp_servers.time-library]\n'
            'command = "/bin/echo"\n'
            'args = ["other"]\n'
            'description = "/opt/time-library/tools/codex_mcp_bridge.py"\n',
            "codex_mcp_server_name_conflict",
        ),
    )
    for original, reason in cases:
        config.write_text(original, encoding="utf-8")
        before = config.read_bytes()
        result = reconcile_codex_mcp(config, install, python_executable="/opt/python")
        assert result["ok"] is False
        assert result["reason"] == reason
        assert config.read_bytes() == before


def test_guard_does_not_create_a_missing_config_during_watch_mode(tmp_path: Path):
    install, config = _fixture(tmp_path)

    result = reconcile_codex_mcp(config, install, python_executable="/opt/python")

    assert result["ok"] is False
    assert result["reason"] == "codex_config_not_found"
    assert not config.exists()


def test_guard_disable_file_is_explicit_and_non_destructive(tmp_path: Path):
    install, config = _fixture(tmp_path)
    provider = '[model_providers.custom]\nbase_url = "http://127.0.0.1:15721/v1"\n'
    config.write_text(provider, encoding="utf-8")
    disabled = config.parent / "time-library-mcp-guard.disabled"
    disabled.write_text("owner disabled\n", encoding="utf-8")

    result = reconcile_codex_mcp(config, install, python_executable="/opt/python")

    assert result["ok"] is True
    assert result["reason"] == "disabled"
    assert config.read_text(encoding="utf-8") == provider


def test_guard_cli_never_echoes_provider_secret(tmp_path: Path):
    install, config = _fixture(tmp_path)
    secret = "relay-secret-do-not-print"
    config.write_text(
        f'[model_providers.custom]\napi_key = "{secret}"\n',
        encoding="utf-8",
    )
    completed = subprocess.run(
        [
            sys.executable,
            str(GUARD),
            "--config",
            str(config),
            "--install-root",
            str(install),
            "--python-executable",
            "/opt/python",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert secret not in completed.stdout
    assert secret not in completed.stderr


def test_guard_watch_recovers_without_a_second_manual_registration(tmp_path: Path):
    install, config = _fixture(tmp_path)
    provider = '[model_providers.custom]\nbase_url = "http://127.0.0.1:15721/v1"\n'
    config.write_text(provider, encoding="utf-8")
    process = subprocess.Popen(
        [
            sys.executable,
            str(GUARD),
            "--watch",
            "--interval",
            "0.2",
            "--config",
            str(config),
            "--install-root",
            str(install),
            "--python-executable",
            "/opt/python",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        time.sleep(0.45)
        replacement_path = config.with_name(".relay-config.tmp")
        replacement_path.write_text(
            provider + '\n[mcp_servers.other]\ncommand = "other-server"\n',
            encoding="utf-8",
        )
        os.replace(replacement_path, config)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if "[mcp_servers.time-library]" in config.read_text(encoding="utf-8"):
                break
            time.sleep(0.1)
        assert "[mcp_servers.time-library]" in config.read_text(encoding="utf-8")
    finally:
        process.terminate()
        process.wait(timeout=5)

    assert process.returncode == 0
    output = process.stdout.read() if process.stdout else ""
    assert json.loads(output.splitlines()[0])["ok"] is True
    final = config.read_text(encoding="utf-8")
    assert "[mcp_servers.other]" in final
    assert final.count("[mcp_servers.time-library]") == 1


def test_guard_cli_once_is_explicit_and_fail_closed(tmp_path: Path):
    install, config = _fixture(tmp_path)
    config.write_text('[model_providers.custom]\nbase_url = "http://127.0.0.1:15721/v1"\n', encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            str(GUARD),
            "--once",
            "--config",
            str(config),
            "--install-root",
            str(install),
            "--python-executable",
            "/opt/python",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    result = json.loads(completed.stdout)
    assert result["ok"] is True
    assert result["write_performed"] is True

    malformed = config.with_name("malformed.toml")
    malformed.write_text("[model_providers.custom\n", encoding="utf-8")
    rejected = subprocess.run(
        [
            sys.executable,
            str(GUARD),
            "--once",
            "--config",
            str(malformed),
            "--install-root",
            str(install),
            "--python-executable",
            "/opt/python",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert rejected.returncode == 2
    assert json.loads(rejected.stdout)["reason"] == "invalid_toml"
    assert malformed.read_text(encoding="utf-8") == "[model_providers.custom\n"


def test_guard_abandons_stale_reconciliation_when_config_changes_during_read(tmp_path: Path, monkeypatch):
    install, config = _fixture(tmp_path)
    provider = '[model_providers.custom]\nbase_url = "http://127.0.0.1:15721/v1"\n'
    config.write_text(provider, encoding="utf-8")
    replacement = provider + '\n[mcp_servers.other]\ncommand = "other-server"\n'
    original_signature = guard_module._signature
    calls = 0

    def racing_signature(path: Path):
        nonlocal calls
        calls += 1
        if calls == 2:
            path.write_text(replacement, encoding="utf-8")
        return original_signature(path)

    monkeypatch.setattr(guard_module, "_signature", racing_signature)
    first = reconcile_codex_mcp(config, install, python_executable="/opt/python")

    assert first["ok"] is False
    assert first["reason"] == "codex_config_changed_during_reconcile"
    assert config.read_text(encoding="utf-8") == replacement

    monkeypatch.setattr(guard_module, "_signature", original_signature)
    second = reconcile_codex_mcp(config, install, python_executable="/opt/python")
    updated = config.read_text(encoding="utf-8")
    assert second["ok"] is True
    assert "[mcp_servers.other]" in updated
    assert "[mcp_servers.time-library]" in updated


def test_guard_registration_uses_discovery_bridge_and_no_fixed_http_endpoint(tmp_path: Path):
    install, config = _fixture(tmp_path)
    config.write_text("[model_providers.custom]\nname = \"relay\"\n", encoding="utf-8")

    result = reconcile_codex_mcp(config, install, python_executable="/opt/python")
    updated = config.read_text(encoding="utf-8")

    assert result["ok"] is True
    assert "codex_mcp_bridge.py" in updated
    assert "window_binding_registry.json" in updated
    assert f'"--root", "{install}"' in updated
    assert "9850" not in updated
    assert "9851" not in updated
    assert "http://" not in updated


def test_guard_preserves_and_repairs_utf8_bom_config(tmp_path: Path):
    install, config = _fixture(tmp_path)
    provider = '\ufeff[model_providers.custom]\r\nname = "relay"\r\n'
    config.write_bytes(provider.encode("utf-8"))

    result = reconcile_codex_mcp(config, install, python_executable="C:/Python/python.exe")
    updated_bytes = config.read_bytes()
    updated = updated_bytes.decode("utf-8")

    assert result["ok"] is True
    assert updated_bytes.startswith("\ufeff[model_providers.custom]\r\n".encode("utf-8"))
    assert "[mcp_servers.time-library]" in updated
    assert "C:/Python/python.exe" in updated


def test_guard_watch_retries_when_registration_assets_appear_later(tmp_path: Path):
    install = tmp_path / "time-library"
    (install / "tools").mkdir(parents=True)
    (install / "config").mkdir()
    config = tmp_path / "codex" / "config.toml"
    config.parent.mkdir()
    config.write_text('[model_providers.custom]\nname = "relay"\n', encoding="utf-8")

    process = subprocess.Popen(
        [
            sys.executable,
            str(GUARD),
            "--watch",
            "--interval",
            "0.2",
            "--config",
            str(config),
            "--install-root",
            str(install),
            "--python-executable",
            "/opt/python",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        time.sleep(0.35)
        (install / "tools" / "codex_mcp_bridge.py").write_text("# fixture bridge\n", encoding="utf-8")
        (install / "config" / "window_binding_registry.json").write_text("{}\n", encoding="utf-8")
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if "[mcp_servers.time-library]" in config.read_text(encoding="utf-8"):
                break
            time.sleep(0.1)
        assert "[mcp_servers.time-library]" in config.read_text(encoding="utf-8")
    finally:
        process.terminate()
        process.wait(timeout=5)

    assert process.returncode == 0
    output = process.stdout.read() if process.stdout else ""
    assert any('"reason": "registration_assets_missing"' in line for line in output.splitlines())
    assert any('"write_performed": true' in line for line in output.splitlines())
