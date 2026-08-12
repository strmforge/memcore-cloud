import importlib.util
import hashlib
import io
import json
import os
import socket
import stat
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

import src.single_port_runtime as single_port_runtime
from src.port_discovery import (
    front_door_url,
    port_file_path,
    read_port,
    resolve_client_url,
    write_port_atomic,
)
from src.single_port_runtime import Target, create_server
from src.single_port_runtime import acquire_front_door_lock


ROOT = Path(__file__).resolve().parents[1]


def _load_tool(name):
    path = ROOT / "tools" / name
    spec = importlib.util.spec_from_file_location(f"single_port_{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _EchoHandler(BaseHTTPRequestHandler):
    service = "unknown"

    def log_message(self, _format, *_args):
        return

    def _send(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length).decode("utf-8") if length else ""
        payload = json.dumps({
            "service": self.service,
            "path": self.path,
            "body": body,
            "front_door": self.headers.get("X-Time-Library-Front-Door"),
        }).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Mcp-Session-Id", f"{self.service}-session")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    do_GET = _send
    do_POST = _send


class _HealthHandler(BaseHTTPRequestHandler):
    payload = {}

    def log_message(self, _format, *_args):
        return

    def do_GET(self):
        body = json.dumps(self.payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _start_echo(service):
    handler = type(f"{service.title()}Handler", (_EchoHandler,), {"service": service})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _start_health(payload):
    handler = type("HealthHandler", (_HealthHandler,), {"payload": payload})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _request(url, body=None):
    data = None if body is None else body.encode("utf-8")
    request = urllib.request.Request(url, data=data, method="GET" if data is None else "POST")
    with urllib.request.urlopen(request, timeout=3) as response:
        return json.loads(response.read().decode("utf-8")), dict(response.headers)


def test_port_discovery_atomic_write_and_legacy_endpoint_migration(tmp_path):
    path = write_port_atomic(9988, tmp_path)
    assert path == port_file_path(tmp_path)
    assert path.read_text(encoding="ascii") == "9988\n"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert read_port(tmp_path) == 9988
    assert front_door_url("mcp", tmp_path) == "http://127.0.0.1:9988/mcp"
    assert resolve_client_url(
        "/mcp",
        endpoint="http://127.0.0.1:9851/mcp?startup_catalog=deferred",
        root=tmp_path,
        verify=False,
    ) == "http://127.0.0.1:9988/mcp?startup_catalog=deferred"
    assert resolve_client_url(
        "/mcp",
        endpoint="http://127.0.0.1:12345/custom",
        root=tmp_path,
        verify=False,
    ) == "http://127.0.0.1:12345/custom"


def test_front_door_lock_rejects_a_second_process_for_the_same_install_root(tmp_path):
    first = acquire_front_door_lock(tmp_path)
    try:
        lock_path = tmp_path / "runtime" / "front_door.lock"
        assert stat.S_IMODE(lock_path.stat().st_mode) == 0o600
        lock_data = json.loads(lock_path.read_text(encoding="ascii"))
        assert lock_data["pid"] == os.getpid()
        assert lock_data["process_fingerprint"]
        with pytest.raises(RuntimeError, match="already running"):
            acquire_front_door_lock(tmp_path)
    finally:
        first.release()
    assert not lock_path.exists()

    lock_path.write_text(
        json.dumps({"pid": os.getpid(), "process_fingerprint": "reused-pid"}),
        encoding="ascii",
    )
    replacement = acquire_front_door_lock(tmp_path)
    replacement.release()


def test_windows_process_fingerprint_does_not_spawn_powershell():
    source = (ROOT / "src" / "single_port_runtime.py").read_text(encoding="utf-8")
    fingerprint = source.split("def _windows_process_fingerprint", 1)[1].split(
        "def _process_fingerprint", 1
    )[0]

    assert 'ctypes.WinDLL("kernel32"' in fingerprint
    assert "GetProcessTimes" in fingerprint
    assert "powershell.exe" not in fingerprint


def test_windows_process_exists_uses_native_fingerprint_not_os_kill(monkeypatch):
    monkeypatch.setattr(single_port_runtime.os, "name", "nt")
    monkeypatch.setattr(single_port_runtime, "_windows_process_fingerprint", lambda pid: "ticks" if pid == 42 else "")

    def fail_if_called(*_args):
        pytest.fail("os.kill must not be used as a Windows process-existence probe")

    monkeypatch.setattr(single_port_runtime.os, "kill", fail_if_called)

    assert single_port_runtime._process_exists(42) is True
    assert single_port_runtime._process_exists(43) is False


def test_windows_process_exists_fails_closed_when_native_query_is_denied(monkeypatch):
    monkeypatch.setattr(single_port_runtime.os, "name", "nt")

    def deny_query(_pid):
        raise PermissionError("access denied")

    monkeypatch.setattr(single_port_runtime, "_windows_process_fingerprint", deny_query)

    assert single_port_runtime._process_exists(42) is True


def test_legacy_windows_datetime_ticks_fingerprint_matches_current_filetime():
    current_filetime = "134128728123456789"
    legacy_ticks = str(
        int(current_filetime) + single_port_runtime.WINDOWS_FILETIME_TO_DATETIME_TICKS
    )

    assert single_port_runtime._process_fingerprints_match(
        legacy_ticks,
        current_filetime,
        "",
        platform_name="nt",
    ) is True
    assert single_port_runtime._process_fingerprints_match(
        str(int(legacy_ticks) + 1),
        current_filetime,
        "",
        platform_name="nt",
    ) is False


def test_discovery_rejects_a_stale_port_owned_by_another_service(tmp_path):
    wrong, wrong_thread = _start_health({"ok": True, "service": "other-service"})
    right, right_thread = _start_health({
        "ok": True,
        "service": "time-library-front-door",
        "user_visible_address_count": 1,
    })
    try:
        write_port_atomic(wrong.server_address[1], tmp_path)
        with pytest.raises(RuntimeError, match="identity check failed"):
            resolve_client_url("/mcp", root=tmp_path)
        write_port_atomic(right.server_address[1], tmp_path)
        assert resolve_client_url("/mcp", root=tmp_path) == f"http://127.0.0.1:{right.server_address[1]}/mcp"
    finally:
        wrong.shutdown()
        wrong.server_close()
        right.shutdown()
        right.server_close()
        wrong_thread.join(timeout=2)
        right_thread.join(timeout=2)


def test_discovery_waits_for_restarting_front_door_without_sending_a_request(tmp_path):
    reserved = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    reserved.bind(("127.0.0.1", 0))
    port = reserved.getsockname()[1]
    reserved.close()
    write_port_atomic(port, tmp_path)
    started = threading.Event()
    holder = {}

    def delayed_start():
        time.sleep(0.15)
        server = ThreadingHTTPServer(("127.0.0.1", port), _HealthHandler)
        server.RequestHandlerClass.payload = {
            "ok": True,
            "service": "time-library-front-door",
            "user_visible_address_count": 1,
        }
        holder["server"] = server
        started.set()
        server.serve_forever()

    thread = threading.Thread(target=delayed_start, daemon=True)
    thread.start()
    try:
        resolved = resolve_client_url(
            "/mcp",
            root=tmp_path,
            wait_timeout=1.0,
            retry_interval=0.02,
        )
        assert resolved == f"http://127.0.0.1:{port}/mcp"
        assert started.is_set()
    finally:
        if started.wait(timeout=2):
            holder["server"].shutdown()
            holder["server"].server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize("tool_name", ["codex_mcp_bridge.py", "claude_desktop_mcp_bridge.py"])
def test_stdio_bridges_reread_discovery_for_every_request(tmp_path, monkeypatch, tool_name):
    bridge = _load_tool(tool_name)
    monkeypatch.setenv("MEMCORE_ROOT", str(tmp_path))
    endpoints = []

    monkeypatch.setattr(
        bridge,
        "resolve_client_url",
        lambda path, **kwargs: front_door_url(path, kwargs.get("root")),
    )

    def fake_forward(endpoint, *_args, **_kwargs):
        endpoints.append(endpoint)
        return {"jsonrpc": "2.0", "id": 1, "result": {}}

    monkeypatch.setattr(bridge, "_forward", fake_forward)
    request = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    write_port_atomic(9988, tmp_path)
    bridge._forward_discovered("", request, 1, True)
    write_port_atomic(9989, tmp_path)
    bridge._forward_discovered("", request, 1, True)

    assert endpoints == ["http://127.0.0.1:9988/mcp", "http://127.0.0.1:9989/mcp"]


def test_codex_bridge_explicit_root_beats_stale_environment(monkeypatch):
    bridge = _load_tool("codex_mcp_bridge.py")
    observed_roots = []
    monkeypatch.setenv("MEMCORE_ROOT", "/stale/installation")

    def fake_resolve(path, **kwargs):
        observed_roots.append(kwargs.get("root"))
        return "http://127.0.0.1:9988/mcp"

    monkeypatch.setattr(bridge, "resolve_client_url", fake_resolve)
    monkeypatch.setattr(
        bridge,
        "_forward",
        lambda endpoint, *_args, **_kwargs: {"jsonrpc": "2.0", "id": 1, "result": {}},
    )
    bridge._forward_discovered(
        "",
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        1,
        True,
        root="/current/installation",
    )

    assert observed_roots == ["/current/installation"]


def test_front_door_waits_for_restarting_internal_service_and_forwards_body_once():
    reserved = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    reserved.bind(("127.0.0.1", 0))
    target_port = reserved.getsockname()[1]
    reserved.close()

    class CountingRawHandler(_EchoHandler):
        service = "raw"
        request_count = 0

        def _send(self):
            type(self).request_count += 1
            super()._send()

        do_GET = _send
        do_POST = _send

    targets = {
        name: Target("127.0.0.1", target_port)
        for name in ("p3", "p4", "p6", "raw", "dialog")
    }
    preferred = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    preferred.bind(("127.0.0.1", 0))
    front_port = preferred.getsockname()[1]
    preferred.close()
    facade, selected = create_server(preferred_port=front_port, max_attempts=1, targets=targets)
    facade_thread = threading.Thread(target=facade.serve_forever, daemon=True)
    facade_thread.start()
    started = threading.Event()
    holder = {}

    def delayed_start():
        time.sleep(0.15)
        server = ThreadingHTTPServer(("127.0.0.1", target_port), CountingRawHandler)
        holder["server"] = server
        started.set()
        server.serve_forever()

    target_thread = threading.Thread(target=delayed_start, daemon=True)
    target_thread.start()
    try:
        payload, _headers = _request(
            f"http://127.0.0.1:{selected}/mcp",
            '{"jsonrpc":"2.0","id":1,"method":"tools/list"}',
        )
        assert payload["service"] == "raw"
        assert CountingRawHandler.request_count == 1
    finally:
        facade.shutdown()
        facade.server_close()
        facade_thread.join(timeout=2)
        if started.wait(timeout=2):
            holder["server"].shutdown()
            holder["server"].server_close()
        target_thread.join(timeout=2)


@pytest.mark.parametrize("tool_name", ["codex_mcp_bridge.py", "claude_desktop_mcp_bridge.py"])
def test_stdio_bridges_fresh_initialize_unverified_session_after_delayed_restart_and_dispatch_once(tool_name):
    bridge = _load_tool(tool_name)
    reserved = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    reserved.bind(("127.0.0.1", 0))
    target_port = reserved.getsockname()[1]
    reserved.close()

    class InitialMcpHandler(BaseHTTPRequestHandler):
        def log_message(self, _format, *_args):
            return

        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            request = json.loads(self.rfile.read(length).decode("utf-8"))
            if request["method"] == "notifications/initialized":
                self.send_response(202)
                self.end_headers()
                return
            body = json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": {}}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Mcp-Session-Id", "session-before-restart")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    class RestartedMcpHandler(BaseHTTPRequestHandler):
        business_dispatch_count = 0

        def log_message(self, _format, *_args):
            return

        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            request = json.loads(self.rfile.read(length).decode("utf-8"))
            method = request["method"]
            session_id = self.headers.get("Mcp-Session-Id")
            if method == "tools/call" and session_id == "session-before-restart":
                body = json.dumps({
                    "jsonrpc": "2.0",
                    "id": request["id"],
                    "error": {
                        "code": -32001,
                        "message": "MCP session not found; reinitialize",
                        "data": {
                            "contract": "time_library.mcp_session_rejection.v1",
                            "reason": "session_not_found",
                            "request_dispatched": False,
                            "safe_to_retry_after_initialize": True,
                        },
                    },
                }).encode()
                self.send_response(404)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if method == "initialize" and session_id is None:
                body = json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": {}}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Mcp-Session-Id", "session-after-restart")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if method == "notifications/initialized" and session_id == "session-after-restart":
                self.send_response(202)
                self.end_headers()
                return
            assert method == "tools/call"
            assert session_id == "session-after-restart"
            type(self).business_dispatch_count += 1
            body = json.dumps({
                "jsonrpc": "2.0",
                "id": request["id"],
                "result": {"recovered": True},
            }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    initial = ThreadingHTTPServer(("127.0.0.1", target_port), InitialMcpHandler)
    initial_thread = threading.Thread(target=initial.serve_forever, daemon=True)
    initial_thread.start()
    targets = {
        name: Target("127.0.0.1", target_port)
        for name in ("p3", "p4", "p6", "raw", "dialog")
    }
    preferred = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    preferred.bind(("127.0.0.1", 0))
    front_port = preferred.getsockname()[1]
    preferred.close()
    facade, selected = create_server(preferred_port=front_port, max_attempts=1, targets=targets)
    facade_thread = threading.Thread(target=facade.serve_forever, daemon=True)
    facade_thread.start()
    restarted = threading.Event()
    holder = {}

    session = bridge._McpHttpSession()
    endpoint = f"http://127.0.0.1:{selected}/mcp"
    initialize = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {"clientInfo": {"name": "restart-test", "version": "1"}},
    }
    initialized = {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
    try:
        bridge._forward(endpoint, initialize, 3, False, http_session=session)
        bridge._forward(endpoint, initialized, 3, False, http_session=session)
        assert session.session_id == "session-before-restart"
        initial.shutdown()
        initial.server_close()
        initial_thread.join(timeout=2)

        def delayed_restart():
            time.sleep(0.15)
            server = ThreadingHTTPServer(("127.0.0.1", target_port), RestartedMcpHandler)
            holder["server"] = server
            restarted.set()
            server.serve_forever()

        restarted_thread = threading.Thread(target=delayed_restart, daemon=True)
        restarted_thread.start()
        result = bridge._forward(
            endpoint,
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "read"}},
            3,
            False,
            http_session=session,
        )
        assert result == {"jsonrpc": "2.0", "id": 2, "result": {"recovered": True}}
        assert session.session_id == "session-after-restart"
        assert RestartedMcpHandler.business_dispatch_count == 1
    finally:
        facade.shutdown()
        facade.server_close()
        facade_thread.join(timeout=2)
        if restarted.wait(timeout=2):
            holder["server"].shutdown()
            holder["server"].server_close()
        if "restarted_thread" in locals():
            restarted_thread.join(timeout=2)
        if initial_thread.is_alive():
            initial.shutdown()
            initial.server_close()
            initial_thread.join(timeout=2)


@pytest.mark.parametrize("tool_name", ["codex_mcp_bridge.py", "claude_desktop_mcp_bridge.py"])
def test_stdio_bridges_do_not_replay_when_internal_service_drops_response_after_dispatch(tool_name):
    bridge = _load_tool(tool_name)

    class DropAfterDispatchHandler(BaseHTTPRequestHandler):
        business_dispatch_count = 0

        def log_message(self, _format, *_args):
            return

        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            self.rfile.read(length)
            type(self).business_dispatch_count += 1
            self.connection.shutdown(socket.SHUT_RDWR)
            self.connection.close()

    target = ThreadingHTTPServer(("127.0.0.1", 0), DropAfterDispatchHandler)
    target_thread = threading.Thread(target=target.serve_forever, daemon=True)
    target_thread.start()
    targets = {
        name: Target("127.0.0.1", target.server_address[1])
        for name in ("p3", "p4", "p6", "raw", "dialog")
    }
    preferred = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    preferred.bind(("127.0.0.1", 0))
    front_port = preferred.getsockname()[1]
    preferred.close()
    facade, selected = create_server(preferred_port=front_port, max_attempts=1, targets=targets)
    facade_thread = threading.Thread(target=facade.serve_forever, daemon=True)
    facade_thread.start()
    session = bridge._McpHttpSession()
    endpoint = f"http://127.0.0.1:{selected}/mcp"
    session.endpoint = endpoint
    session.session_id = "live-session"
    session.initialize_request = {
        "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}
    }
    try:
        result = bridge._forward(
            endpoint,
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "write"}},
            3,
            False,
            http_session=session,
        )
        assert result["error"]["code"] == -32603
        assert result["error"]["message"] == "internal_service_unavailable"
        assert DropAfterDispatchHandler.business_dispatch_count == 1
    finally:
        facade.shutdown()
        facade.server_close()
        facade_thread.join(timeout=2)
        target.shutdown()
        target.server_close()
        target_thread.join(timeout=2)


def test_front_door_fails_within_grace_when_internal_service_never_starts(monkeypatch):
    monkeypatch.setattr(single_port_runtime, "INTERNAL_SERVICE_CONNECT_GRACE_SECONDS", 0.05)
    reserved = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    reserved.bind(("127.0.0.1", 0))
    target_port = reserved.getsockname()[1]
    reserved.close()
    targets = {
        name: Target("127.0.0.1", target_port)
        for name in ("p3", "p4", "p6", "raw", "dialog")
    }
    preferred = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    preferred.bind(("127.0.0.1", 0))
    front_port = preferred.getsockname()[1]
    preferred.close()
    facade, selected = create_server(preferred_port=front_port, max_attempts=1, targets=targets)
    facade_thread = threading.Thread(target=facade.serve_forever, daemon=True)
    facade_thread.start()
    started = time.monotonic()
    try:
        with pytest.raises(urllib.error.HTTPError) as error:
            _request(
                f"http://127.0.0.1:{selected}/mcp",
                '{"jsonrpc":"2.0","id":1,"method":"tools/list"}',
            )
        elapsed = time.monotonic() - started
        payload = json.loads(error.value.read().decode("utf-8"))
        assert error.value.code == 502
        assert payload["error"] == "internal_service_unavailable"
        assert payload["service"] == "raw"
        assert elapsed < 1.0
    finally:
        facade.shutdown()
        facade.server_close()
        facade_thread.join(timeout=2)


@pytest.mark.parametrize("tool_name", ["codex_mcp_bridge.py", "claude_desktop_mcp_bridge.py"])
def test_stdio_bridges_reinitialize_before_forwarding_to_a_new_endpoint(monkeypatch, tool_name):
    bridge = _load_tool(tool_name)
    requests = []
    session_count = 0

    class FakeResponse:
        status = 200

        def __init__(self, session_id=""):
            self.headers = {"Mcp-Session-Id": session_id} if session_id else {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"jsonrpc":"2.0","id":1,"result":{}}'

    def fake_urlopen(request, timeout):
        nonlocal session_count
        body = json.loads(request.data.decode("utf-8"))
        method = body["method"]
        requests.append((request.full_url, method, request.get_header("Mcp-session-id"), timeout))
        if method == "initialize":
            session_count += 1
            return FakeResponse(f"session-{session_count}")
        return FakeResponse()

    monkeypatch.setattr(bridge.urllib.request, "urlopen", fake_urlopen)
    session = bridge._McpHttpSession()
    initialize = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    tools_list = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
    bridge._forward("http://127.0.0.1:9988/mcp", initialize, 3, False, http_session=session)
    bridge._forward("http://127.0.0.1:9988/mcp", tools_list, 3, False, http_session=session)
    bridge._forward("http://127.0.0.1:9989/mcp", tools_list, 3, False, http_session=session)

    assert requests == [
        ("http://127.0.0.1:9988/mcp", "initialize", None, 3),
        ("http://127.0.0.1:9988/mcp", "tools/list", "session-1", 3),
        ("http://127.0.0.1:9989/mcp", "initialize", None, 3),
        ("http://127.0.0.1:9989/mcp", "tools/list", "session-2", 3),
    ]


@pytest.mark.parametrize("tool_name", ["codex_mcp_bridge.py", "claude_desktop_mcp_bridge.py"])
@pytest.mark.parametrize("verified_connection", [False, True])
def test_stdio_bridges_recover_stale_session_once_and_retry_original_request(
    monkeypatch,
    capsys,
    tool_name,
    verified_connection,
):
    bridge = _load_tool(tool_name)
    requests = []
    initialize_count = 0
    stale_returned = False

    class FakeResponse:
        def __init__(self, status, payload=b"", session_id=""):
            self.status = status
            self.payload = payload
            self.headers = {"Mcp-Session-Id": session_id} if session_id else {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return self.payload

    def fake_urlopen(request, timeout):
        nonlocal initialize_count, stale_returned
        body = json.loads(request.data.decode("utf-8"))
        method = body["method"]
        session_id = request.get_header("Mcp-session-id")
        requests.append((method, session_id, body.get("id"), timeout))
        if method == "initialize":
            initialize_count += 1
            payload = json.dumps({"jsonrpc": "2.0", "id": body["id"], "result": {}}).encode()
            return FakeResponse(200, payload, f"session-{initialize_count}")
        if method == "notifications/initialized":
            return FakeResponse(202)
        if not stale_returned:
            stale_returned = True
            payload = json.dumps({
                "jsonrpc": "2.0",
                "id": body["id"],
                "error": {
                    "code": -32001,
                    "message": "MCP session not found; reinitialize",
                    "data": {
                        "contract": "time_library.mcp_session_rejection.v1",
                        "reason": "session_not_found",
                        "request_dispatched": False,
                        "safe_to_retry_after_initialize": True,
                    },
                },
            }).encode()
            raise urllib.error.HTTPError(
                request.full_url,
                404,
                "Not Found",
                {},
                io.BytesIO(payload),
            )
        payload = json.dumps({"jsonrpc": "2.0", "id": body["id"], "result": {"recovered": True}}).encode()
        return FakeResponse(200, payload)

    monkeypatch.setattr(bridge.urllib.request, "urlopen", fake_urlopen)
    session = bridge._McpHttpSession()
    endpoint = "http://127.0.0.1:9988/mcp"
    bridge._forward(
        endpoint,
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"clientInfo": {"name": "test"}}},
        3,
        False,
        http_session=session,
    )
    bridge._forward(
        endpoint,
        {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        3,
        False,
        http_session=session,
    )
    session.verified_connection = verified_connection
    result = bridge._forward(
        endpoint,
        {"jsonrpc": "2.0", "id": 9, "method": "tools/list", "params": {}},
        3,
        False,
        http_session=session,
    )

    assert result == {"jsonrpc": "2.0", "id": 9, "result": {"recovered": True}}
    assert requests == [
        ("initialize", None, 1, 3),
        ("notifications/initialized", "session-1", None, 3),
        ("tools/list", "session-1", 9, 3),
        ("initialize", "session-1" if verified_connection else None, 1, 3),
        ("notifications/initialized", "session-2", None, 3),
        ("tools/list", "session-2", 9, 3),
    ]
    assert session.session_id == "session-2"
    captured = capsys.readouterr()
    expected_mode = "verified_resume" if verified_connection else "fresh_initialize"
    assert f"MCP session recovery started mode={expected_mode}" in captured.err
    assert "MCP session recovery completed" in captured.err


@pytest.mark.parametrize("tool_name", ["codex_mcp_bridge.py", "claude_desktop_mcp_bridge.py"])
def test_stdio_bridges_mark_session_verified_from_self_report_response(monkeypatch, tool_name):
    bridge = _load_tool(tool_name)

    class FakeResponse:
        status = 200

        def __init__(self, payload, session_id=""):
            self.payload = payload
            self.headers = {"Mcp-Session-Id": session_id} if session_id else {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return self.payload

    def fake_urlopen(request, timeout):
        body = json.loads(request.data.decode("utf-8"))
        if body["method"] == "initialize":
            payload = json.dumps({"jsonrpc": "2.0", "id": body["id"], "result": {}}).encode()
            return FakeResponse(payload, "session-1")
        payload = json.dumps({
            "jsonrpc": "2.0",
            "id": body["id"],
            "result": {
                "structuredContent": {
                    "contract": "time_library_platform_self_report_receipt.v1",
                    "self_report_verified": True,
                    "connection_receipt": {
                        "ok": True,
                        "contract": "time_library.host_connection_receipt.v1",
                        "transport_session_sha256": hashlib.sha256(b"session-1").hexdigest(),
                    },
                }
            },
        }).encode()
        return FakeResponse(payload)

    monkeypatch.setattr(bridge.urllib.request, "urlopen", fake_urlopen)
    session = bridge._McpHttpSession()
    endpoint = "http://127.0.0.1:9988/mcp"
    bridge._forward(
        endpoint,
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        3,
        False,
        http_session=session,
    )
    bridge._forward(
        endpoint,
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "time_library_reading_area",
                "arguments": {"action": "self_report_connect"},
            },
        },
        3,
        False,
        http_session=session,
    )

    assert session.verified_connection is True


@pytest.mark.parametrize("tool_name", ["codex_mcp_bridge.py", "claude_desktop_mcp_bridge.py"])
@pytest.mark.parametrize(
    "invalid_case",
    [
        "unrelated_action",
        "missing_connection_receipt",
        "connection_receipt_not_ok",
        "connection_receipt_contract_mismatch",
        "transport_session_mismatch",
        "self_report_contract_mismatch",
    ],
)
def test_stdio_bridges_do_not_trust_unbound_self_report_verified_flags(tool_name, invalid_case):
    bridge = _load_tool(tool_name)
    session = bridge._McpHttpSession()
    session.session_id = "session-1"
    request = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": "time_library_reading_area",
            "arguments": {"action": "self_report_connect"},
        },
    }
    structured = {
        "contract": "time_library_platform_self_report_receipt.v1",
        "self_report_verified": True,
        "connection_receipt": {
            "ok": True,
            "contract": "time_library.host_connection_receipt.v1",
            "transport_session_sha256": hashlib.sha256(b"session-1").hexdigest(),
        },
    }
    if invalid_case == "unrelated_action":
        request["params"]["arguments"]["action"] = "whiteboard_list"
    elif invalid_case == "missing_connection_receipt":
        structured.pop("connection_receipt")
    elif invalid_case == "connection_receipt_not_ok":
        structured["connection_receipt"]["ok"] = False
    elif invalid_case == "connection_receipt_contract_mismatch":
        structured["connection_receipt"]["contract"] = "wrong.contract"
    elif invalid_case == "transport_session_mismatch":
        structured["connection_receipt"]["transport_session_sha256"] = hashlib.sha256(
            b"other-session"
        ).hexdigest()
    else:
        structured["contract"] = "wrong.contract"

    session.observe_response(request, {"jsonrpc": "2.0", "id": 2, "result": {
        "structuredContent": structured,
    }})

    assert session.verified_connection is False


@pytest.mark.parametrize("tool_name", ["codex_mcp_bridge.py", "claude_desktop_mcp_bridge.py"])
@pytest.mark.parametrize(
    "resume_rejection_reason",
    [
        "verified_host_connection_required",
        "verified_host_resume_expired",
        "verified_host_resume_already_consumed",
        "verified_host_resume_identity_mismatch",
    ],
)
def test_stdio_bridges_require_reverification_and_drop_rejected_resume_bearer(
    monkeypatch,
    tool_name,
    resume_rejection_reason,
):
    bridge = _load_tool(tool_name)
    requests = []
    initialize_count = 0

    class FakeResponse:
        def __init__(self, status, payload=b"", session_id=""):
            self.status = status
            self.payload = payload
            self.headers = {"Mcp-Session-Id": session_id} if session_id else {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return self.payload

    def http_error(request, status, payload):
        raise urllib.error.HTTPError(
            request.full_url,
            status,
            "Rejected",
            {},
            io.BytesIO(json.dumps(payload).encode()),
        )

    def fake_urlopen(request, timeout):
        nonlocal initialize_count
        body = json.loads(request.data.decode("utf-8"))
        method = body["method"]
        session_id = request.get_header("Mcp-session-id")
        requests.append((method, session_id, timeout))
        if method == "initialize" and session_id is None:
            initialize_count += 1
            return FakeResponse(
                200,
                json.dumps({"jsonrpc": "2.0", "id": body["id"], "result": {}}).encode(),
                f"session-{initialize_count}",
            )
        if method == "initialize":
            return http_error(
                request,
                409,
                {
                    "jsonrpc": "2.0",
                    "id": body["id"],
                    "error": {
                        "code": -32002,
                        "message": "resume rejected",
                        "data": {
                            "contract": "time_library.mcp_resume_rejection.v1",
                            "reason": resume_rejection_reason,
                            "request_dispatched": False,
                            "session_issued": False,
                            "safe_to_retry_without_user_reverification": False,
                        },
                    },
                },
            )
        if method == "tools/list" and session_id == "session-2":
            return FakeResponse(
                200,
                json.dumps({"jsonrpc": "2.0", "id": body["id"], "result": {
                    "reinitialized_unverified": True,
                }}).encode(),
            )
        return http_error(
            request,
            404,
            {
                "jsonrpc": "2.0",
                "id": body["id"],
                "error": {
                    "code": -32001,
                    "message": "session not found",
                    "data": {
                        "contract": "time_library.mcp_session_rejection.v1",
                        "reason": "session_not_found",
                        "request_dispatched": False,
                        "safe_to_retry_after_initialize": True,
                    },
                },
            },
        )

    monkeypatch.setattr(bridge.urllib.request, "urlopen", fake_urlopen)
    session = bridge._McpHttpSession()
    endpoint = "http://127.0.0.1:9988/mcp"
    bridge._forward(
        endpoint,
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        3,
        False,
        http_session=session,
    )
    session.verified_connection = True
    result = bridge._forward(
        endpoint,
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        3,
        False,
        http_session=session,
    )
    state_after_rejection = {
        "session_id": session.session_id,
        "resume_session_id": session.resume_session_id,
        "verified_connection": session.verified_connection,
        "recovery_failures": session.recovery_failures,
        "next_recovery_at": session.next_recovery_at,
    }
    next_explicit_request = bridge._forward(
        endpoint,
        {"jsonrpc": "2.0", "id": 3, "method": "tools/list", "params": {}},
        3,
        False,
        http_session=session,
    )

    assert result["error"]["code"] == -32002
    assert result["error"]["data"] == {
        "contract": "time_library.mcp_resume_rejection.v1",
        "reason": resume_rejection_reason,
        "request_dispatched": False,
        "session_issued": False,
        "reverification_required": True,
        "safe_to_retry_without_user_reverification": False,
    }
    assert state_after_rejection == {
        "session_id": "",
        "resume_session_id": "",
        "verified_connection": False,
        "recovery_failures": 0,
        "next_recovery_at": 0.0,
    }
    assert next_explicit_request == {
        "jsonrpc": "2.0",
        "id": 3,
        "result": {"reinitialized_unverified": True},
    }
    assert requests == [
        ("initialize", None, 3),
        ("tools/list", "session-1", 3),
        ("initialize", "session-1", 3),
        ("initialize", None, 3),
        ("tools/list", "session-2", 3),
    ]
    assert session.session_id == "session-2"
    assert session.verified_connection is False


@pytest.mark.parametrize("tool_name", ["codex_mcp_bridge.py", "claude_desktop_mcp_bridge.py"])
def test_stdio_bridges_never_fresh_initialize_while_verified_bearer_is_missing(
    monkeypatch,
    tool_name,
):
    bridge = _load_tool(tool_name)
    requests = []

    def unexpected_urlopen(request, timeout):
        requests.append((request.full_url, timeout))
        raise AssertionError("verified state without a bearer must not reach HTTP")

    monkeypatch.setattr(bridge.urllib.request, "urlopen", unexpected_urlopen)
    session = bridge._McpHttpSession()
    endpoint = "http://127.0.0.1:9988/mcp"
    session.endpoint = endpoint
    session.remember_request({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {"clientInfo": {"name": "test"}},
    })
    session.verified_connection = True

    result = bridge._forward(
        endpoint,
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        3,
        False,
        http_session=session,
    )

    assert result["error"]["code"] == -32002
    assert result["error"]["data"]["reason"] == "verified_host_resume_bearer_missing"
    assert result["error"]["data"]["request_dispatched"] is False
    assert requests == []
    assert session.verified_connection is False


@pytest.mark.parametrize("tool_name", ["codex_mcp_bridge.py", "claude_desktop_mcp_bridge.py"])
def test_stdio_bridges_preserve_rotated_verified_bearer_across_second_restart(
    monkeypatch,
    tool_name,
):
    bridge = _load_tool(tool_name)
    requests = []
    initialize_count = 0
    dispatch_count = 0

    class FakeResponse:
        def __init__(self, status, payload=b"", session_id=""):
            self.status = status
            self.payload = payload
            self.headers = {"Mcp-Session-Id": session_id} if session_id else {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return self.payload

    def session_not_found(request, body):
        payload = json.dumps({
            "jsonrpc": "2.0",
            "id": body["id"],
            "error": {
                "code": -32001,
                "message": "session not found",
                "data": {
                    "contract": "time_library.mcp_session_rejection.v1",
                    "reason": "session_not_found",
                    "request_dispatched": False,
                    "safe_to_retry_after_initialize": True,
                },
            },
        }).encode()
        raise urllib.error.HTTPError(
            request.full_url,
            404,
            "Not Found",
            {},
            io.BytesIO(payload),
        )

    def fake_urlopen(request, timeout):
        nonlocal dispatch_count, initialize_count
        body = json.loads(request.data.decode("utf-8"))
        method = body["method"]
        session_id = request.get_header("Mcp-session-id")
        requests.append((method, session_id, body.get("id")))
        if method == "initialize":
            initialize_count += 1
            payload = json.dumps({"jsonrpc": "2.0", "id": body["id"], "result": {}}).encode()
            return FakeResponse(200, payload, f"session-{initialize_count}")
        if method == "notifications/initialized":
            return FakeResponse(202)
        if session_id in {"session-1", "session-2"}:
            return session_not_found(request, body)
        dispatch_count += 1
        payload = json.dumps({
            "jsonrpc": "2.0",
            "id": body["id"],
            "result": {"dispatch_count": dispatch_count},
        }).encode()
        return FakeResponse(200, payload)

    monkeypatch.setattr(bridge.urllib.request, "urlopen", fake_urlopen)
    session = bridge._McpHttpSession()
    endpoint = "http://127.0.0.1:9988/mcp"
    initialize_request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {"clientInfo": {"name": "test"}},
    }
    bridge._forward(endpoint, initialize_request, 3, False, http_session=session)
    bridge._forward(
        endpoint,
        {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        3,
        False,
        http_session=session,
    )
    session.observe_response(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "time_library_reading_area",
                "arguments": {"action": "self_report_connect"},
            },
        },
        {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {"structuredContent": {
                "contract": "time_library_platform_self_report_receipt.v1",
                "self_report_verified": True,
                "connection_receipt": {
                    "ok": True,
                    "contract": "time_library.host_connection_receipt.v1",
                    "transport_session_sha256": hashlib.sha256(b"session-1").hexdigest(),
                },
            }},
        },
    )
    call = {
        "jsonrpc": "2.0",
        "id": 9,
        "method": "tools/call",
        "params": {"name": "read_only_probe", "arguments": {}},
    }

    first = bridge._forward(endpoint, call, 3, False, http_session=session)

    assert first["error"]["code"] == -32001
    assert first["error"]["data"]["request_dispatched"] is False
    assert dispatch_count == 0
    assert session.session_id == ""
    assert session.resume_session_id == "session-2"
    assert session.verified_connection is True
    session.next_recovery_at = 0.0

    second = bridge._forward(endpoint, call, 3, False, http_session=session)

    assert second == {"jsonrpc": "2.0", "id": 9, "result": {"dispatch_count": 1}}
    assert dispatch_count == 1
    assert session.session_id == "session-3"
    assert session.resume_session_id == ""
    assert session.verified_connection is True
    assert requests == [
        ("initialize", None, 1),
        ("notifications/initialized", "session-1", None),
        ("tools/call", "session-1", 9),
        ("initialize", "session-1", 1),
        ("notifications/initialized", "session-2", None),
        ("tools/call", "session-2", 9),
        ("initialize", "session-2", 1),
        ("notifications/initialized", "session-3", None),
        ("tools/call", "session-3", 9),
    ]


@pytest.mark.parametrize("tool_name", ["codex_mcp_bridge.py", "claude_desktop_mcp_bridge.py"])
def test_stdio_bridges_fail_closed_on_malformed_resume_rejection(monkeypatch, tool_name):
    bridge = _load_tool(tool_name)
    requests = []

    class FakeResponse:
        status = 200

        def __init__(self, payload, session_id=""):
            self.payload = payload
            self.headers = {"Mcp-Session-Id": session_id} if session_id else {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return self.payload

    def fake_urlopen(request, timeout):
        body = json.loads(request.data.decode("utf-8"))
        method = body["method"]
        session_id = request.get_header("Mcp-session-id")
        requests.append((method, session_id))
        if method == "initialize" and session_id is None:
            payload = json.dumps({"jsonrpc": "2.0", "id": body["id"], "result": {}}).encode()
            return FakeResponse(payload, "session-1")
        if method == "initialize":
            payload = json.dumps({
                "jsonrpc": "2.0",
                "id": body["id"],
                "error": {
                    "code": -32002,
                    "message": "malformed resume rejection",
                    "data": {
                        "contract": "time_library.mcp_resume_rejection.v1",
                        "reason": "verified_host_resume_expired",
                        "request_dispatched": False,
                        "session_issued": False,
                    },
                },
            }).encode()
            raise urllib.error.HTTPError(
                request.full_url,
                409,
                "Conflict",
                {},
                io.BytesIO(payload),
            )
        payload = json.dumps({
            "jsonrpc": "2.0",
            "id": body["id"],
            "error": {
                "code": -32001,
                "message": "session not found",
                "data": {
                    "contract": "time_library.mcp_session_rejection.v1",
                    "reason": "session_not_found",
                    "request_dispatched": False,
                    "safe_to_retry_after_initialize": True,
                },
            },
        }).encode()
        raise urllib.error.HTTPError(
            request.full_url,
            404,
            "Not Found",
            {},
            io.BytesIO(payload),
        )

    monkeypatch.setattr(bridge.urllib.request, "urlopen", fake_urlopen)
    session = bridge._McpHttpSession()
    endpoint = "http://127.0.0.1:9988/mcp"
    bridge._forward(
        endpoint,
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        3,
        False,
        http_session=session,
    )
    session.verified_connection = True
    call = {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
        "name": "read_only_probe",
    }}

    first = bridge._forward(endpoint, call, 3, False, http_session=session)
    requests_after_first = list(requests)
    second = bridge._forward(endpoint, call, 3, False, http_session=session)

    assert first["error"]["code"] == -32001
    assert first["error"]["data"]["request_dispatched"] is False
    assert second["error"]["code"] == -32000
    assert requests == requests_after_first == [
        ("initialize", None),
        ("tools/call", "session-1"),
        ("initialize", "session-1"),
    ]
    assert session.session_id == ""
    assert session.resume_session_id == "session-1"
    assert session.verified_connection is True
    assert session.recovery_failures == 1


@pytest.mark.parametrize("tool_name", ["codex_mcp_bridge.py", "claude_desktop_mcp_bridge.py"])
@pytest.mark.parametrize("unsafe_case", ["http_200_error", "post_dispatch_404"])
def test_stdio_bridges_do_not_retry_unsafe_session_like_errors(monkeypatch, tool_name, unsafe_case):
    bridge = _load_tool(tool_name)
    requests = []

    class FakeResponse:
        def __init__(self, payload, session_id=""):
            self.status = 200
            self.payload = payload
            self.headers = {"Mcp-Session-Id": session_id} if session_id else {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return self.payload

    def fake_urlopen(request, timeout):
        body = json.loads(request.data.decode("utf-8"))
        requests.append((body["method"], request.get_header("Mcp-session-id")))
        if body["method"] == "initialize":
            payload = json.dumps({"jsonrpc": "2.0", "id": body["id"], "result": {}}).encode()
            return FakeResponse(payload, "session-1")
        error = {
            "jsonrpc": "2.0",
            "id": body["id"],
            "error": {
                "code": -32001,
                "message": "MCP session not found",
                "data": {
                    "contract": "time_library.mcp_session_rejection.v1",
                    "reason": "session_not_found",
                    "request_dispatched": unsafe_case != "http_200_error",
                    "safe_to_retry_after_initialize": True,
                },
            },
        }
        payload = json.dumps(error).encode()
        if unsafe_case == "post_dispatch_404":
            raise urllib.error.HTTPError(
                request.full_url,
                404,
                "Not Found",
                {},
                io.BytesIO(payload),
            )
        return FakeResponse(payload)

    monkeypatch.setattr(bridge.urllib.request, "urlopen", fake_urlopen)
    session = bridge._McpHttpSession()
    endpoint = "http://127.0.0.1:9988/mcp"
    bridge._forward(
        endpoint,
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        3,
        False,
        http_session=session,
    )
    result = bridge._forward(
        endpoint,
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "write"}},
        3,
        False,
        http_session=session,
    )

    assert result["error"]["code"] == -32001
    assert requests == [("initialize", None), ("tools/call", "session-1")]


@pytest.mark.parametrize("tool_name", ["codex_mcp_bridge.py", "claude_desktop_mcp_bridge.py"])
def test_stdio_bridges_do_not_forward_original_or_storm_when_reinitialize_fails(monkeypatch, tool_name):
    bridge = _load_tool(tool_name)
    requests = []

    class FakeResponse:
        status = 200

        def __init__(self, payload, session_id=""):
            self.payload = payload
            self.headers = {"Mcp-Session-Id": session_id} if session_id else {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return self.payload

    def fake_urlopen(request, timeout):
        body = json.loads(request.data.decode("utf-8"))
        requests.append((request.full_url, body["method"], request.get_header("Mcp-session-id")))
        if request.full_url.endswith(":9988/mcp"):
            payload = json.dumps({"jsonrpc": "2.0", "id": body["id"], "result": {}}).encode()
            return FakeResponse(payload, "session-1")
        raise urllib.error.HTTPError(
            request.full_url,
            503,
            "Unavailable",
            {},
            io.BytesIO(b'{"error":"not ready"}'),
        )

    monkeypatch.setattr(bridge.urllib.request, "urlopen", fake_urlopen)
    session = bridge._McpHttpSession()
    bridge._forward(
        "http://127.0.0.1:9988/mcp",
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        3,
        False,
        http_session=session,
    )
    call = {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "write"}}
    first = bridge._forward(
        "http://127.0.0.1:9989/mcp",
        call,
        3,
        False,
        http_session=session,
    )
    second = bridge._forward(
        "http://127.0.0.1:9989/mcp",
        call,
        3,
        False,
        http_session=session,
    )

    assert first["error"]["code"] == -32000
    assert second["error"]["code"] == -32000
    assert requests == [
        ("http://127.0.0.1:9988/mcp", "initialize", None),
        ("http://127.0.0.1:9989/mcp", "initialize", None),
    ]


@pytest.mark.parametrize("tool_name", ["codex_mcp_bridge.py", "claude_desktop_mcp_bridge.py"])
def test_stdio_bridges_retry_only_once_when_new_session_is_also_rejected(monkeypatch, tool_name):
    bridge = _load_tool(tool_name)
    requests = []
    initialize_count = 0

    class FakeResponse:
        status = 200

        def __init__(self, payload, session_id=""):
            self.payload = payload
            self.headers = {"Mcp-Session-Id": session_id} if session_id else {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return self.payload

    def fake_urlopen(request, timeout):
        nonlocal initialize_count
        body = json.loads(request.data.decode("utf-8"))
        requests.append((body["method"], request.get_header("Mcp-session-id")))
        if body["method"] == "initialize":
            initialize_count += 1
            payload = json.dumps({"jsonrpc": "2.0", "id": body["id"], "result": {}}).encode()
            return FakeResponse(payload, f"session-{initialize_count}")
        payload = json.dumps({
            "jsonrpc": "2.0",
            "id": body["id"],
            "error": {
                "code": -32001,
                "message": "MCP session not found",
                "data": {
                    "contract": "time_library.mcp_session_rejection.v1",
                    "reason": "session_not_found",
                    "request_dispatched": False,
                    "safe_to_retry_after_initialize": True,
                },
            },
        }).encode()
        raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, io.BytesIO(payload))

    monkeypatch.setattr(bridge.urllib.request, "urlopen", fake_urlopen)
    session = bridge._McpHttpSession()
    endpoint = "http://127.0.0.1:9988/mcp"
    bridge._forward(
        endpoint,
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        3,
        False,
        http_session=session,
    )
    result = bridge._forward(
        endpoint,
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        3,
        False,
        http_session=session,
    )
    requests_after_first = list(requests)
    second = bridge._forward(
        endpoint,
        {"jsonrpc": "2.0", "id": 3, "method": "tools/list", "params": {}},
        3,
        False,
        http_session=session,
    )

    assert result["error"]["code"] == -32001
    assert second["error"]["code"] == -32000
    assert requests == [
        ("initialize", None),
        ("tools/list", "session-1"),
        ("initialize", None),
        ("tools/list", "session-2"),
    ]
    assert requests == requests_after_first
    assert session.recovery_failures == 1
    assert session.next_recovery_at > 0
    assert session.session_id == ""
    assert session.resume_session_id == ""


def test_single_port_routes_and_moves_when_preferred_port_is_occupied(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMCORE_ROOT", str(tmp_path))
    services = {}
    threads = []
    targets = {}
    for name in ("p3", "p4", "p6", "raw", "dialog"):
        server, thread = _start_echo(name)
        services[name] = server
        threads.append(thread)
        targets[name] = Target("127.0.0.1", server.server_address[1])

    occupied = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    occupied.bind(("127.0.0.1", 0))
    occupied.listen(1)
    preferred = occupied.getsockname()[1]
    facade, selected = create_server(preferred_port=preferred, max_attempts=3, targets=targets)
    assert selected == preferred + 1
    write_port_atomic(selected, tmp_path)
    facade_thread = threading.Thread(target=facade.serve_forever, daemon=True)
    facade_thread.start()

    try:
        cases = {
            "/": "p6",
            "/api/health": "p6",
            "/mcp?startup_catalog=deferred": "raw",
            "/api/v1/raw/query": "raw",
            "/catalog-inject": "p4",
            "/reading-area/catalog": "p4",
            "/entry/openclaw-before-dispatch": "dialog",
            "/recall": "p3",
        }
        for path, expected in cases.items():
            payload, headers = _request(f"http://127.0.0.1:{selected}{path}", "{}" if path != "/" else None)
            assert payload["service"] == expected
            assert payload["front_door"] == str(selected)
            assert headers["Mcp-Session-Id"] == f"{expected}-session"
        health, _ = _request(f"http://127.0.0.1:{selected}/health")
        assert health["service"] == "time-library-front-door"
        assert health["user_visible_address_count"] == 1
        assert read_port(tmp_path) == selected
    finally:
        facade.shutdown()
        facade.server_close()
        occupied.close()
        for server in services.values():
            server.shutdown()
            server.server_close()

    returned, returned_port = create_server(preferred_port=preferred, max_attempts=1, targets=targets)
    try:
        assert returned_port == preferred
    finally:
        returned.server_close()
