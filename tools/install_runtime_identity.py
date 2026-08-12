#!/usr/bin/env python3
"""Conservative service ownership checks used by platform installers."""

from __future__ import annotations

import argparse
import os
import plistlib
import re
import shlex
import sys
from pathlib import Path
from typing import Iterable, Sequence


RUNTIME_ENTRYPOINTS = (
    "memcore-cloud.py",
    "p3_recall.py",
    "p4_provider.py",
    "p6_console.py",
    "raw_consumption_gateway.py",
    "dialog_entry_proxy.py",
    "single_port_runtime.py",
)
DIRECT_RUNTIME_ENTRYPOINTS = ("runtime/memcore-menu-bar",)
TOOL_RUNTIME_ENTRYPOINTS = ("tools/codex_mcp_config_guard.py",)


def _resolved(value: str | os.PathLike[str]) -> Path:
    return Path(value).expanduser().resolve(strict=False)


def known_entrypoints(roots: Iterable[str | os.PathLike[str]]) -> set[Path]:
    roots = tuple(root for root in roots if str(root or "").strip())
    script_entrypoints = {
        _resolved(root) / "src" / name
        for root in roots
        for name in RUNTIME_ENTRYPOINTS
    }
    direct_entrypoints = {
        _resolved(root) / relative
        for root in roots
        for relative in DIRECT_RUNTIME_ENTRYPOINTS
    }
    tool_entrypoints = {
        _resolved(root) / relative
        for root in roots
        for relative in TOOL_RUNTIME_ENTRYPOINTS
    }
    return script_entrypoints | direct_entrypoints | tool_entrypoints


def _unwrap_env(argv: Sequence[str]) -> list[str]:
    values = [str(value) for value in argv if str(value)]
    if not values or Path(values[0]).name != "env":
        return values
    index = 1
    while index < len(values):
        value = values[index]
        if value == "--":
            index += 1
            break
        if value.startswith("-") or ("=" in value and not value.startswith(("/", "."))):
            index += 1
            continue
        break
    return values[index:]


def command_entrypoint(argv: Sequence[str]) -> Path | None:
    values = _unwrap_env(argv)
    if not values:
        return None
    executable = Path(values[0]).name.casefold()
    if re.fullmatch(r"(?:python|pythonw|pypy)(?:\d+(?:\.\d+)*)?", executable):
        index = 1
        while index < len(values):
            value = values[index]
            if value in {"-c", "-m"}:
                return None
            if value in {"-W", "-X"}:
                index += 2
                continue
            if value.startswith("-"):
                index += 1
                continue
            return _resolved(value)
        return None
    return _resolved(values[0])


def argv_targets_install_roots(
    argv: Sequence[str], roots: Iterable[str | os.PathLike[str]]
) -> bool:
    entrypoint = command_entrypoint(argv)
    return entrypoint is not None and entrypoint in known_entrypoints(roots)


def launchctl_arguments(definition: str) -> list[str]:
    arguments: list[str] = []
    in_arguments = False
    for raw_line in str(definition or "").splitlines():
        line = raw_line.strip()
        if line == "arguments = {":
            in_arguments = True
            continue
        if in_arguments and line == "}":
            break
        if in_arguments and line:
            arguments.append(line)
    return arguments


def launchctl_targets_install_roots(
    definition: str, roots: Iterable[str | os.PathLike[str]]
) -> bool:
    return argv_targets_install_roots(launchctl_arguments(definition), roots)


def plist_targets_install_roots(
    path: str | os.PathLike[str], roots: Iterable[str | os.PathLike[str]]
) -> bool:
    try:
        with Path(path).open("rb") as handle:
            payload = plistlib.load(handle)
    except (OSError, plistlib.InvalidFileException):
        return False
    arguments = payload.get("ProgramArguments")
    return isinstance(arguments, list) and argv_targets_install_roots(arguments, roots)


def systemd_arguments(definition: str, unit_path: str | os.PathLike[str] = "") -> list[str]:
    text = str(definition or "").strip()
    if text:
        match = re.search(r"argv\[\]=(.*?)(?:\s*;\s*[A-Za-z_]+\s*=|\s*}\s*$)", text)
        if match:
            try:
                return shlex.split(match.group(1))
            except ValueError:
                return []
        return []
    if not unit_path:
        return []
    try:
        lines = Path(unit_path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines:
        if line.startswith("ExecStart="):
            try:
                return shlex.split(line.split("=", 1)[1])
            except ValueError:
                return []
    return []


def systemd_targets_install_roots(
    definition: str,
    roots: Iterable[str | os.PathLike[str]],
    *,
    unit_path: str | os.PathLike[str] = "",
) -> bool:
    return argv_targets_install_roots(systemd_arguments(definition, unit_path), roots)


def macos_ps_command_targets_install_roots(
    command: str, roots: Iterable[str | os.PathLike[str]]
) -> bool:
    executable, separator, remainder = str(command or "").strip().partition(" ")
    if not separator:
        return _resolved(executable) in known_entrypoints(roots) if executable else False
    executable_name = Path(executable).name.casefold()
    if not re.fullmatch(r"(?:python|pythonw|pypy)(?:\d+(?:\.\d+)*)?", executable_name):
        return False
    remaining = remainder.lstrip()
    while True:
        match = re.match(r"^-(?:B|E|I|O|OO|P|R|s|S|u|v|V|x)(?:\s+|$)", remaining)
        if not match:
            break
        remaining = remaining[match.end() :].lstrip()
    return any(remaining == str(path) or remaining.startswith(str(path) + " ") for path in known_entrypoints(roots))


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("launchctl", "plist", "systemd"))
    parser.add_argument("--root", action="append", required=True)
    parser.add_argument("--path", default="")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.mode == "launchctl":
        matched = launchctl_targets_install_roots(sys.stdin.read(), args.root)
    elif args.mode == "plist":
        matched = plist_targets_install_roots(args.path, args.root)
    else:
        matched = systemd_targets_install_roots(sys.stdin.read(), args.root, unit_path=args.path)
    return 0 if matched else 1


if __name__ == "__main__":
    raise SystemExit(main())
