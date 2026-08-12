#!/usr/bin/env python3
"""Deprecated compatibility entry point for the Codex MCP config guard.

Older installers called this helper after ``codex mcp add`` to adjust approval
tables.  Keeping a second TOML writer would recreate the same race that the
guard fixes, so this entry point now delegates to
``codex_mcp_config_guard.reconcile_codex_mcp`` and refuses to guess an install
root when the existing server is not an owned Time Library bridge.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

try:
    from tools.codex_mcp_config_guard import (
        BRIDGE_FILENAME,
        DEFAULT_APPROVED_TOOLS,
        REGISTRY_RELATIVE_PATH,
        _parse_toml,
        reconcile_codex_mcp,
    )
except ModuleNotFoundError:  # direct execution from an installed tools directory
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tools.codex_mcp_config_guard import (
        BRIDGE_FILENAME,
        DEFAULT_APPROVED_TOOLS,
        REGISTRY_RELATIVE_PATH,
        _parse_toml,
        reconcile_codex_mcp,
    )


DEFAULT_SERVER = "time-library"


def _legacy_result(*, error: str, server: str) -> dict[str, object]:
    return {
        "ok": False,
        "changed": False,
        "write_performed": False,
        "backup_created": False,
        "server": server,
        "error": error,
        "reason": error,
        "deprecated": True,
        "implementation": "codex_mcp_config_guard",
    }


def _infer_install_root(config_path: Path, *, server: str) -> tuple[Path | None, str | None, str | None]:
    """Find an installed bridge without inspecting or printing sensitive values."""

    try:
        original = config_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None, None, "codex_config_not_found"
    except OSError:
        return None, None, "codex_config_unreadable"
    data, parse_error = _parse_toml(original)
    if parse_error:
        return None, None, parse_error
    assert data is not None
    servers = data.get("mcp_servers")
    if not isinstance(servers, dict) or not isinstance(servers.get(server), dict):
        return None, None, "codex_mcp_server_section_missing"
    server_data = servers[server]
    args = server_data.get("args")
    command = server_data.get("command")
    command_text = command if isinstance(command, str) and command.strip() else None
    if not isinstance(args, list):
        return None, command_text, "codex_mcp_guard_required"
    for value in args:
        if not isinstance(value, str) or not value.casefold().endswith(BRIDGE_FILENAME.casefold()):
            continue
        candidate = Path(value).expanduser()
        if not candidate.is_absolute():
            continue
        candidate = candidate.resolve(strict=False)
        if candidate.name.casefold() != BRIDGE_FILENAME.casefold() or not candidate.is_file():
            continue
        install_root = candidate.parent.parent
        if (install_root / REGISTRY_RELATIVE_PATH).is_file():
            return install_root, command_text, None
    return None, command_text, "codex_mcp_guard_required"


def configure_codex_mcp_policy(
    config_path: Path,
    *,
    server: str = DEFAULT_SERVER,
    approved_tools: Sequence[str] = DEFAULT_APPROVED_TOOLS,
    install_root: Path | None = None,
    python_executable: str | None = None,
) -> dict[str, object]:
    """Delegate legacy approval updates to the single guarded writer.

    ``install_root`` is optional only for compatibility.  When omitted, it is
    inferred from an existing absolute bridge argument; otherwise the function
    fails closed instead of editing a same-name foreign MCP table.
    """

    config_path = config_path.expanduser()
    inferred_command: str | None = None
    if install_root is None:
        install_root, inferred_command, error = _infer_install_root(config_path, server=server)
        if error:
            return _legacy_result(error=error, server=server)
    if install_root is None:
        return _legacy_result(error="codex_mcp_guard_required", server=server)

    result = dict(
        reconcile_codex_mcp(
            config_path,
            install_root,
            python_executable=python_executable or inferred_command or "python3",
            server=server,
            approved_tools=tuple(approved_tools),
        )
    )
    result["deprecated"] = True
    result["implementation"] = "codex_mcp_config_guard"
    if not result.get("ok"):
        result["error"] = result.get("reason") or "codex_mcp_guard_failed"
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--server", default=DEFAULT_SERVER)
    parser.add_argument("--install-root", type=Path)
    parser.add_argument("--python-executable")
    parser.add_argument("--approve-tool", action="append", default=[])
    args = parser.parse_args()
    approved_tools = tuple(args.approve_tool) or DEFAULT_APPROVED_TOOLS
    result = configure_codex_mcp_policy(
        args.config,
        server=args.server,
        approved_tools=approved_tools,
        install_root=args.install_root,
        python_executable=args.python_executable,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
