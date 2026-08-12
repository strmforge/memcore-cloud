#!/usr/bin/env python3
"""Keep the Time Library Codex MCP entry alive across external config rewrites.

Codex stores MCP servers in the same user TOML file that provider/relay tools
often regenerate.  This tool owns only the ``time-library`` table and its two
approval tables.  It never parses, logs, or reconstructs the rest of the user
configuration from a separate snapshot.

The default action is a single reconciliation.  Installers run that action
once; a user-level service may run ``--watch`` to reconcile after a later
external replacement of config.toml.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import shutil
import signal
import stat
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Sequence


DEFAULT_SERVER = "time-library"
DEFAULT_INTERVAL_SECONDS = 2.0
DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_APPROVED_TOOLS = (
    "time_library_recall",
    "time_library_delivery_ack",
)
GUARD_DISABLED_FILENAME = "time-library-mcp-guard.disabled"
BRIDGE_FILENAME = "codex_mcp_bridge.py"
REGISTRY_RELATIVE_PATH = Path("config") / "window_binding_registry.json"

_TABLE_HEADER_RE = re.compile(r"^\s*(\[\[.*\]\]|\[[^\[].*\])(?:\s*#.*)?$")


@dataclass(frozen=True)
class _Section:
    start: int
    end: int
    kind: str
    header: str


def _load_toml() -> Any:
    """Return the stdlib TOML loader, or the compatible optional loader."""

    try:
        import tomllib

        return tomllib
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore[no-redef]

            return tomllib
        except ImportError:
            return None


def _parse_toml(text: str) -> tuple[dict[str, Any] | None, str | None]:
    tomllib = _load_toml()
    if tomllib is None:
        return None, "toml_parser_unavailable"
    # Windows PowerShell 5 commonly emits UTF-8 with a BOM. Keep the
    # original bytes for the surgical rewrite, but ignore the marker only
    # while parsing and validating the TOML document.
    parse_text = text[1:] if text.startswith("\ufeff") else text
    try:
        data = tomllib.loads(parse_text)
    except Exception:
        return None, "invalid_toml"
    if not isinstance(data, dict):
        return None, "invalid_toml_root"
    return data, None


def _quoted(value: str) -> str:
    # JSON basic strings are valid TOML basic strings and correctly escape
    # Windows separators, quotes, and non-ASCII paths.
    return json.dumps(str(value), ensure_ascii=False)


def _array(values: Sequence[str]) -> str:
    return "[" + ", ".join(_quoted(value) for value in values) + "]"


def _inline_table(values: dict[str, str]) -> str:
    return "{ " + ", ".join(f"{key} = {_quoted(value)}" for key, value in values.items()) + " }"


def _is_approval_assignment(line: str) -> bool:
    stripped = line.lstrip()
    return bool(re.match(r"approval_mode\s*=", stripped))


def _server_header_variants(server: str) -> set[str]:
    return {
        f"mcp_servers.{server}",
        f'mcp_servers."{server}"',
        f"mcp_servers.'{server}'",
    }


def _tool_header_variants(server: str, tool: str) -> set[str]:
    return {
        f"mcp_servers.{server}.tools.{tool}",
        f'mcp_servers."{server}".tools.{tool}',
        f"mcp_servers.'{server}'.tools.{tool}",
    }


def _legacy_env_header_variants(server: str) -> set[str]:
    return {f"{key}.env" for key in _server_header_variants(server)}


def _header_parts(line: str) -> tuple[str, bool] | None:
    match = _TABLE_HEADER_RE.match(line.rstrip("\r\n"))
    if not match:
        return None
    raw = match.group(1)
    if raw.startswith("[[") and raw.endswith("]]"):
        return raw[2:-2].strip(), True
    return raw[1:-1].strip(), False


def _advance_toml_string_state(line: str, state: str | None) -> str | None:
    """Track multiline TOML strings so their contents cannot become headers."""

    index = 0
    while index < len(line):
        if state is not None:
            if line.startswith(state, index):
                index += 3
                state = None
            elif state == '"""' and line[index] == "\\":
                index += 2
            else:
                index += 1
            continue

        if line[index] == "#":
            break
        if line.startswith('"""', index):
            state = '"""'
            index += 3
            continue
        if line.startswith("'''", index):
            state = "'''"
            index += 3
            continue
        if line[index] == '"':
            index += 1
            while index < len(line):
                if line[index] == "\\":
                    index += 2
                elif line[index] == '"':
                    index += 1
                    break
                else:
                    index += 1
            continue
        if line[index] == "'":
            index += 1
            while index < len(line):
                if line[index] == "'":
                    index += 1
                    break
                index += 1
            continue
        index += 1
    return state


def _classify_header(
    header: str,
    *,
    server: str,
    approved_tools: Sequence[str],
) -> str:
    if header in _server_header_variants(server):
        return "server"
    if header in _legacy_env_header_variants(server):
        return "legacy_env"
    for tool in approved_tools:
        if header in _tool_header_variants(server, tool):
            return f"tool:{tool}"
    server_prefixes = tuple(f"{key}." for key in _server_header_variants(server))
    if header.startswith(server_prefixes):
        return "unexpected_subsection"
    return "other"


def _sections(
    lines: Sequence[str], *, server: str, approved_tools: Sequence[str]
) -> list[_Section]:
    headers: list[tuple[int, str, str]] = []
    string_state: str | None = None
    for index, line in enumerate(lines):
        if string_state is None:
            parts = _header_parts(line)
            if parts is not None:
                inner, is_array = parts
                if is_array:
                    managed_prefixes = tuple(
                        f"{key}." for key in _server_header_variants(server)
                    )
                    kind = (
                        "unexpected_subsection"
                        if inner in _server_header_variants(server)
                        or inner.startswith(managed_prefixes)
                        else "other"
                    )
                else:
                    kind = _classify_header(
                        inner, server=server, approved_tools=approved_tools
                    )
                headers.append((index, inner, kind))
        string_state = _advance_toml_string_state(line, string_state)
    result: list[_Section] = []
    for offset, (start, header, kind) in enumerate(headers):
        end = headers[offset + 1][0] if offset + 1 < len(headers) else len(lines)
        result.append(_Section(start=start, end=end, kind=kind, header=header))
    return result


def _iter_strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, child in value.items():
            yield from _iter_strings(key)
            yield from _iter_strings(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _iter_strings(child)


def _normal_path(value: str, *, base: Path) -> str:
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = base / candidate
    try:
        return os.path.normcase(str(candidate.resolve(strict=False)))
    except OSError:
        return os.path.normcase(str(candidate.absolute()))


def _server_is_owned(server_data: Any, *, bridge: Path, config_path: Path) -> bool:
    if not isinstance(server_data, dict):
        return False
    expected = _normal_path(str(bridge), base=config_path.parent)
    args = server_data.get("args")
    if not isinstance(args, list):
        # Only adopt the shape emitted by this installer. Searching every
        # string in the table would let an unrelated same-name server become
        # owned merely because a description or environment value mentioned
        # the bridge filename.
        return False
    install_root = bridge.parent.parent
    for value in args:
        if not isinstance(value, str):
            continue
        if not value.casefold().endswith(BRIDGE_FILENAME.casefold()):
            continue
        if (
            _normal_path(value, base=config_path.parent) == expected
            or _normal_path(value, base=install_root) == expected
        ):
            return True
    return False


def _registration_block(
    *,
    server: str,
    bridge: Path,
    registry: Path,
    python_executable: str,
    timeout_seconds: int,
    approved_tools: Sequence[str],
    existing_tool_bodies: dict[str, Sequence[str]],
    newline: str,
) -> str:
    command_args = [
        str(bridge),
        "--root",
        str(bridge.parent.parent),
        "--timeout",
        str(timeout_seconds),
        "--window-binding-registry",
        str(registry),
        "--binding-key",
        "codex",
    ]
    env = {
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
        "MEMCORE_ROOT": str(bridge.parent.parent),
        "MEMCORE_WINDOW_BINDING_REGISTRY": str(registry),
    }
    lines = [
        f"[mcp_servers.{server}]{newline}",
        f"command = {_quoted(python_executable)}{newline}",
        f"args = {_array(command_args)}{newline}",
        f"env = {_inline_table(env)}{newline}",
    ]
    for tool in approved_tools:
        body = list(existing_tool_bodies.get(tool, ()))
        while body and not body[-1].strip():
            body.pop()
        approval_indexes = [
            index for index, line in enumerate(body) if _is_approval_assignment(line)
        ]
        if len(approval_indexes) > 1:
            raise ValueError(f"duplicate_codex_mcp_approval_mode:{tool}")
        if approval_indexes:
            body[approval_indexes[0]] = f'approval_mode = "approve"{newline}'
        else:
            body.append(f'approval_mode = "approve"{newline}')
        lines.extend(
            [
                newline,
                f"[mcp_servers.{server}.tools.{tool}]{newline}",
                *body,
            ]
        )
    return "".join(lines)


def _replace_sections(
    lines: list[str],
    *,
    sections: Sequence[_Section],
    block: str,
    newline: str,
) -> str:
    server_sections = [section for section in sections if section.kind == "server"]
    tool_sections = [section for section in sections if section.kind.startswith("tool:")]
    if len(server_sections) > 1:
        raise ValueError("duplicate_codex_mcp_server_sections")
    seen_tools = {section.kind for section in tool_sections}
    if len(seen_tools) != len(tool_sections):
        raise ValueError("duplicate_codex_mcp_tool_sections")

    if not server_sections:
        if tool_sections:
            raise ValueError("unsectioned_codex_mcp_tool_sections")
        updated = list(lines)
        # Keep the foreign file byte-for-byte intact when the relay removed
        # the owned table.  A terminating newline already separates the
        # existing document from the new table; adding blank lines here would
        # make the foreign projection appear changed on every recovery.
        if updated and not updated[-1].endswith(("\n", "\r")):
            updated.append(newline)
        updated.extend(block.splitlines(keepends=True))
        return "".join(updated)

    first = server_sections[0]
    managed = [
        section
        for section in sections
        if section.kind in {"server", "legacy_env"} or section.kind.startswith("tool:")
    ]
    ranges = sorted((section.start, section.end) for section in managed)
    output: list[str] = []
    cursor = 0
    for start, end in ranges:
        if start < cursor:
            continue
        if start == first.start:
            output.extend(lines[cursor:start])
            output.extend(block.splitlines(keepends=True))
        else:
            output.extend(lines[cursor:start])
        cursor = end
    output.extend(lines[cursor:])
    return "".join(output)


def _validate_registration_shape(
    data: dict[str, Any], *, server: str, bridge: Path
) -> tuple[bool, str | None]:
    mcp_servers = data.get("mcp_servers")
    if mcp_servers is not None and not isinstance(mcp_servers, dict):
        return False, "mcp_servers_not_table"
    if isinstance(mcp_servers, dict) and server in mcp_servers:
        if not isinstance(mcp_servers[server], dict):
            return False, "codex_mcp_server_not_table"
        # The caller handles ownership; this only checks that the table is
        # structurally representable.
    return True, None


def _signature(path: Path) -> tuple[Any, ...]:
    try:
        info = path.stat()
    except OSError:
        return ("missing",)
    try:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        # Keep a changing metadata signature even when a relay has the file
        # temporarily open.  Reconciliation will fail closed on the read and
        # the watcher will retry when the file becomes readable.
        digest = "unreadable"
    return ("file", info.st_ino, info.st_mtime_ns, info.st_ctime_ns, info.st_size, digest)


def _read_config(path: Path) -> tuple[str | None, str | None]:
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return None, "codex_config_not_found"
    except OSError:
        return None, "codex_config_unreadable"
    try:
        return raw.decode("utf-8"), None
    except UnicodeDecodeError:
        return None, "codex_config_not_utf8"


def _atomic_write(path: Path, text: str, *, mode: int) -> None:
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="",
            dir=path.parent,
            prefix=f".{path.name}.time-library-guard-",
            delete=False,
        ) as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
            temporary_path = Path(handle.name)
        os.chmod(temporary_path, mode)
        os.replace(temporary_path, path)
        temporary_path = None
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
        except OSError:
            directory_fd = None
        if directory_fd is not None:
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


@contextlib.contextmanager
def _exclusive_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        fcntl = None
        try:
            import fcntl as _fcntl

            fcntl = _fcntl
        except ImportError:
            pass
        msvcrt = None
        if fcntl is None:
            try:
                import msvcrt as _msvcrt

                msvcrt = _msvcrt
            except ImportError:
                pass
        if fcntl is not None:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        elif msvcrt is not None:
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
        else:
            raise RuntimeError("config_lock_unsupported")
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
            elif msvcrt is not None:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def _disabled_path(config_path: Path, explicit: Path | None) -> Path:
    return explicit.expanduser() if explicit else config_path.parent / GUARD_DISABLED_FILENAME


def _result(
    *,
    ok: bool,
    changed: bool = False,
    reason: str = "",
    write_performed: bool = False,
    backup_created: bool = False,
    server: str = DEFAULT_SERVER,
) -> dict[str, object]:
    return {
        "ok": ok,
        "changed": changed,
        "write_performed": write_performed,
        "backup_created": backup_created,
        "server": server,
        "reason": reason,
    }


def _reconcile_text(
    original: str,
    *,
    config_path: Path,
    install_root: Path,
    python_executable: str,
    server: str,
    timeout_seconds: int,
    approved_tools: Sequence[str],
) -> tuple[str | None, str]:
    data, parse_error = _parse_toml(original)
    if parse_error:
        return None, parse_error
    assert data is not None
    valid, shape_error = _validate_registration_shape(data, server=server, bridge=install_root / "tools" / BRIDGE_FILENAME)
    if not valid:
        return None, shape_error or "invalid_config_shape"

    newline = "\r\n" if "\r\n" in original else "\n"
    lines = original.splitlines(keepends=True)
    sections = _sections(lines, server=server, approved_tools=approved_tools)
    if any(section.kind == "unexpected_subsection" for section in sections):
        return None, "unexpected_codex_mcp_subsection"
    server_sections = [section for section in sections if section.kind == "server"]
    tool_sections = [section for section in sections if section.kind.startswith("tool:")]
    if len(server_sections) > 1:
        return None, "duplicate_codex_mcp_server_sections"
    if len({section.kind for section in tool_sections}) != len(tool_sections):
        return None, "duplicate_codex_mcp_tool_sections"

    mcp_servers = data.get("mcp_servers")
    semantic_server_present = isinstance(mcp_servers, dict) and server in mcp_servers
    bridge = install_root / "tools" / BRIDGE_FILENAME
    if not server_sections:
        if semantic_server_present or tool_sections:
            return None, "unsectioned_codex_mcp_server"
    else:
        raw_server = mcp_servers.get(server) if isinstance(mcp_servers, dict) else None
        if not _server_is_owned(raw_server, bridge=bridge, config_path=config_path):
            return None, "codex_mcp_server_name_conflict"

    block = _registration_block(
        server=server,
        bridge=bridge,
        registry=install_root / REGISTRY_RELATIVE_PATH,
        python_executable=python_executable,
        timeout_seconds=timeout_seconds,
        approved_tools=approved_tools,
        existing_tool_bodies={
            section.kind.split(":", 1)[1]: lines[section.start + 1 : section.end]
            for section in tool_sections
        },
        newline=newline,
    )
    try:
        updated = _replace_sections(lines, sections=sections, block=block, newline=newline)
    except ValueError as exc:
        return None, str(exc)
    if updated == original:
        return updated, "already_current"
    # Validate the exact bytes we are about to install before replacing the
    # user's file.  This is the final fail-closed guard against bad quoting.
    _, updated_error = _parse_toml(updated)
    if updated_error:
        return None, "generated_invalid_toml"
    return updated, "reconciled"


def reconcile_codex_mcp(
    config_path: Path,
    install_root: Path,
    *,
    python_executable: str = "python3",
    server: str = DEFAULT_SERVER,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    approved_tools: Sequence[str] = DEFAULT_APPROVED_TOOLS,
    create_if_missing: bool = False,
    disabled_path: Path | None = None,
) -> dict[str, object]:
    """Reconcile one config file without touching unrelated TOML sections."""

    config_path = config_path.expanduser()
    install_root = install_root.expanduser()
    disabled = _disabled_path(config_path, disabled_path)
    if disabled.is_file():
        return _result(ok=True, reason="disabled", server=server)
    bridge = install_root / "tools" / BRIDGE_FILENAME
    registry = install_root / REGISTRY_RELATIVE_PATH
    if not bridge.is_file() or not registry.is_file():
        return _result(ok=False, reason="registration_assets_missing", server=server)
    if config_path.is_symlink():
        return _result(ok=False, reason="codex_config_symlink_refused", server=server)
    if not config_path.exists() and not create_if_missing:
        return _result(ok=False, reason="codex_config_not_found", server=server)

    config_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = config_path.with_name(config_path.name + ".time-library-mcp-guard.lock")
    with _exclusive_lock(lock_path):
        if config_path.is_symlink():
            return _result(ok=False, reason="codex_config_symlink_refused", server=server)
        if config_path.exists():
            observed_signature = _signature(config_path)
            original, read_error = _read_config(config_path)
            if read_error:
                return _result(ok=False, reason=read_error, server=server)
            assert original is not None
            mode = stat.S_IMODE(config_path.stat().st_mode)
        else:
            if not create_if_missing:
                return _result(ok=False, reason="codex_config_not_found", server=server)
            original = ""
            mode = 0o600
            observed_signature = ("missing",)
        updated, reason = _reconcile_text(
            original,
            config_path=config_path,
            install_root=install_root,
            python_executable=python_executable,
            server=server,
            timeout_seconds=timeout_seconds,
            approved_tools=approved_tools,
        )
        if updated is None:
            return _result(ok=False, reason=reason, server=server)
        if updated == original:
            return _result(ok=True, reason=reason, server=server)

        # A relay may replace the whole file while we are parsing it.  Never
        # replace a newer file with a reconciliation based on an older read;
        # the watcher will retry against the new signature.
        if _signature(config_path) != observed_signature:
            return _result(
                ok=False,
                reason="codex_config_changed_during_reconcile",
                server=server,
            )

        backup_path = config_path.with_name(config_path.name + ".time-library-mcp-guard.backup")
        backup_created = False
        if config_path.exists() and not backup_path.exists():
            shutil.copy2(config_path, backup_path)
            try:
                os.chmod(backup_path, mode)
            except OSError:
                pass
            backup_created = True
        _atomic_write(config_path, updated, mode=mode)
        return _result(
            ok=True,
            changed=True,
            reason=reason,
            write_performed=True,
            backup_created=backup_created,
            server=server,
        )


def _watch(
    config_path: Path,
    install_root: Path,
    *,
    python_executable: str,
    server: str,
    timeout_seconds: int,
    interval_seconds: float,
    create_if_missing: bool,
    disabled_path: Path | None,
) -> int:
    stopped = False

    def _stop(_signum: int, _frame: Any) -> None:
        nonlocal stopped
        stopped = True

    for signal_name in ("SIGTERM", "SIGINT"):
        signal_value = getattr(signal, signal_name, None)
        if signal_value is not None:
            signal.signal(signal_value, _stop)

    last_signature: tuple[Any, ...] | None = None
    last_disabled: bool | None = None
    last_result_key: str | None = None
    retry_at = 0.0
    while not stopped:
        current_signature = _signature(config_path)
        current_disabled = _disabled_path(config_path, disabled_path).is_file()
        changed = current_signature != last_signature or current_disabled != last_disabled
        retry_due = last_result_key is not None and time.monotonic() >= retry_at
        if changed or retry_due:
            try:
                result = reconcile_codex_mcp(
                    config_path,
                    install_root,
                    python_executable=python_executable,
                    server=server,
                    timeout_seconds=timeout_seconds,
                    create_if_missing=create_if_missing,
                    disabled_path=disabled_path,
                )
            except Exception as exc:  # pragma: no cover - service containment
                result = _result(ok=False, reason=f"guard_exception:{type(exc).__name__}", server=server)
            # Retry failures even when the config signature is unchanged: a
            # relay can hold the file briefly, or an install can restore the
            # bridge/registry after the first poll. Suppress identical retry
            # lines so a persistent malformed file cannot flood service logs.
            result_key = json.dumps(result, ensure_ascii=False, sort_keys=True)
            if changed or result_key != last_result_key:
                print(result_key, flush=True)
            last_result_key = result_key
            last_signature = current_signature
            last_disabled = current_disabled
            if result.get("ok"):
                retry_at = float("inf")
            else:
                retry_at = time.monotonic() + interval_seconds
            if result.get("reason") == "codex_config_changed_during_reconcile":
                # Do not mark the raced file as handled; the next poll must
                # reconcile the replacement that won the race.
                last_signature = None
                retry_at = time.monotonic()
        time.sleep(interval_seconds)
    return 0


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--install-root", type=Path, required=True)
    parser.add_argument("--python-executable", default="python3")
    parser.add_argument("--server", default=DEFAULT_SERVER)
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--interval", type=float, default=DEFAULT_INTERVAL_SECONDS)
    parser.add_argument("--create-if-missing", action="store_true")
    parser.add_argument("--disabled-file", type=Path)
    parser.add_argument("--watch", action="store_true")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Perform one reconciliation (the default; useful for explicit installer calls).",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.timeout < 1 or args.timeout > 300:
        print("invalid --timeout", file=sys.stderr)
        return 2
    if args.interval < 0.2 or args.interval > 60:
        print("invalid --interval", file=sys.stderr)
        return 2
    if args.watch and args.once:
        print("--watch and --once are mutually exclusive", file=sys.stderr)
        return 2
    if args.watch:
        return _watch(
            args.config.expanduser(),
            args.install_root.expanduser(),
            python_executable=args.python_executable,
            server=args.server,
            timeout_seconds=args.timeout,
            interval_seconds=args.interval,
            create_if_missing=args.create_if_missing,
            disabled_path=args.disabled_file,
        )
    try:
        result = reconcile_codex_mcp(
            args.config,
            args.install_root,
            python_executable=args.python_executable,
            server=args.server,
            timeout_seconds=args.timeout,
            create_if_missing=args.create_if_missing,
            disabled_path=args.disabled_file,
        )
    except Exception as exc:
        result = _result(ok=False, reason=f"guard_exception:{type(exc).__name__}", server=args.server)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
