import plistlib

from tools.install_runtime_identity import (
    argv_targets_install_roots,
    known_entrypoints,
    launchctl_targets_install_roots,
    macos_ps_command_targets_install_roots,
    plist_targets_install_roots,
    systemd_targets_install_roots,
)


def test_launchctl_ownership_uses_service_entrypoint_not_unrelated_argument(tmp_path):
    root_a = tmp_path / "install A"
    root_b = tmp_path / "install B"
    definition = f"""
    program = {root_b}/.venv/bin/python
    arguments = {{
        {root_b}/.venv/bin/python
        {root_b}/src/p3_recall.py
        --config
        {root_a}/config/memcore.json
    }}
    """

    assert launchctl_targets_install_roots(definition, [root_b]) is True
    assert launchctl_targets_install_roots(definition, [root_a]) is False


def test_plist_ownership_uses_service_entrypoint_not_unrelated_argument(tmp_path):
    root_a = tmp_path / "install A"
    root_b = tmp_path / "install B"
    path = tmp_path / "service.plist"
    path.write_bytes(
        plistlib.dumps(
            {
                "ProgramArguments": [
                    str(root_b / ".venv/bin/python"),
                    str(root_b / "src/raw_consumption_gateway.py"),
                    "--config",
                    str(root_a / "config/memcore.json"),
                ]
            }
        )
    )

    assert plist_targets_install_roots(path, [root_b]) is True
    assert plist_targets_install_roots(path, [root_a]) is False


def test_systemd_ownership_uses_service_entrypoint_not_unrelated_argument(tmp_path):
    root_a = tmp_path / "install-a"
    root_b = tmp_path / "install-b"
    definition = (
        f"{{ path=/usr/bin/python3 ; argv[]=/usr/bin/python3 {root_b}/src/p6_console.py "
        f"--config {root_a}/config/memcore.json ; ignore_errors=no ; }}"
    )

    assert systemd_targets_install_roots(definition, [root_b]) is True
    assert systemd_targets_install_roots(definition, [root_a]) is False


def test_systemd_unit_fallback_is_entrypoint_scoped(tmp_path):
    root = tmp_path / "install"
    unit = tmp_path / "time-library.service"
    unit.write_text(
        f"[Service]\nExecStart=/usr/bin/python3 {root}/src/single_port_runtime.py --host 127.0.0.1\n",
        encoding="utf-8",
    )

    assert systemd_targets_install_roots("", [root], unit_path=unit) is True


def test_process_matching_rejects_editors_and_argument_lures(tmp_path):
    root = tmp_path / "Time Library"
    entrypoint = root / "src/p3_recall.py"

    assert argv_targets_install_roots(["/usr/bin/python3", str(entrypoint), "serve"], [root]) is True
    assert argv_targets_install_roots(["/usr/bin/vim", str(entrypoint)], [root]) is False
    assert argv_targets_install_roots(
        ["/usr/bin/python3", "/tmp/checker.py", "--inspect", str(entrypoint)],
        [root],
    ) is False
    assert macos_ps_command_targets_install_roots(
        f"/usr/bin/python3 {entrypoint} serve --port 19300",
        [root],
    ) is True
    assert macos_ps_command_targets_install_roots(f"/usr/bin/vim {entrypoint}", [root]) is False
    assert macos_ps_command_targets_install_roots(
        f"/usr/bin/python3 /tmp/checker.py --inspect {entrypoint}",
        [root],
    ) is False


def test_codex_mcp_guard_is_an_owned_runtime_entrypoint(tmp_path):
    root = tmp_path / "Time Library"
    guard = root / "tools/codex_mcp_config_guard.py"

    assert guard in known_entrypoints([root])
    assert guard in known_entrypoints(iter([root]))
    assert argv_targets_install_roots(["/usr/bin/python3", str(guard), "--watch"], [root]) is True
    assert argv_targets_install_roots(
        ["/usr/bin/python3", "/tmp/checker.py", "--inspect", str(guard)], [root]
    ) is False


def test_macos_menu_bar_is_a_known_direct_runtime_entrypoint(tmp_path):
    root = tmp_path / "Time Library"
    other = tmp_path / "Other Library"
    definition = f"""
    program = {root}/runtime/memcore-menu-bar
    arguments = {{
        {root}/runtime/memcore-menu-bar
    }}
    """

    assert launchctl_targets_install_roots(definition, [root]) is True
    assert launchctl_targets_install_roots(definition, [other]) is False
