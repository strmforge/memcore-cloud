import base64
import hashlib
import importlib.util
import json
import os
import sqlite3
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_probe():
    sys.modules.pop("time_library_fleet_probe_under_test", None)
    path = ROOT / "tools" / "time_library_fleet_probe.py"
    spec = importlib.util.spec_from_file_location("time_library_fleet_probe_under_test", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_host_spec_is_parameterized_and_does_not_embed_private_topology():
    probe = _load_probe()
    spec = probe._host_spec(json.dumps({
        "alias": "host-a",
        "target": "root@host-a",
        "platform": "unix",
        "root": "/srv/time-library",
        "codex_applicable": False,
    }))

    assert spec.alias == "host-a"
    assert spec.target == "root@host-a"
    assert spec.codex_applicable is False
    source = (ROOT / "tools" / "time_library_fleet_probe.py").read_text(encoding="utf-8")
    private_names = (
        "windows" + "123",
        "windows" + "191",
        "n" + "100-haishuai",
        "h" + "730xd",
    )
    for private_name in private_names:
        assert private_name not in source
    assert '"raw_divergence_generation_active_count"' in probe.REMOTE_PROBE_SOURCE
    assert '"targeted_scan_count"' in probe.REMOTE_PROBE_SOURCE
    assert '"recoverability_probe"' in probe.REMOTE_PROBE_SOURCE


def test_local_probe_reports_safe_metadata_without_writing(tmp_path):
    probe = _load_probe()
    root = tmp_path / "time-library"
    (root / ".venv" / "bin").mkdir(parents=True)
    (root / ".venv" / "bin" / "python").symlink_to(Path(sys.executable))
    (root / "src").mkdir()
    (root / "runtime" / "fts5_recall").mkdir(parents=True)
    (root / "VERSION").write_text("2026.7.25\n", encoding="ascii")
    payload = b"fixture source\n"
    tracked = root / "src" / "tracked.py"
    tracked.write_bytes(payload)
    (root / "runtime" / "front_door_port").write_text("9\n", encoding="ascii")
    guardian = {
        "ok": True,
        "measurement_status": "complete",
        "full_health_check": True,
        "not_measured_layers": [],
        "generated_at": "2026-07-29T00:00:00Z",
        "checks": [{"name": "watcher", "ok": True, "detail": "must not leak"}],
        "record_guardian": {
            "available": True,
            "fresh": True,
            "evidence_source": "guardian_status_cache",
            "observed_at": "2026-07-29T00:00:00Z",
            "cache_age_seconds": 1,
            "last_refresh_attempt_at": "2026-07-29T00:00:00Z",
            "refresh_attempt_age_seconds": 1,
            "refresh_throttled": True,
            "summary": {"record_count": 2, "record_guarded_count": 2},
            "recoverability_probe": {
                "candidate_count": 2,
                "candidate_limit": 80,
                "per_file_byte_limit": 33554432,
                "round_byte_limit": 67108864,
                "targeted_scan_count": 1,
                "cache_hit_count": 0,
                "canonical_cache_hit_count": 1,
                "measured_count": 2,
                "not_measured_count": 0,
                "bytes_read": 4096,
                "budget_exhausted_count": 0,
                "one_sided_count": 1,
                "non_conversation_count": 0,
                "canonical_cache_status": "sqlite_open_failed:PrivatePath",
            },
        },
    }
    (root / "runtime" / "guardian-status.json").write_text(json.dumps(guardian), encoding="utf-8")
    index = root / "runtime" / "fts5_recall" / "p3_memories.sqlite3"
    con = sqlite3.connect(index)
    con.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT)")
    con.executemany(
        "INSERT INTO meta(key, value) VALUES (?, ?)",
        [
            ("doc_count", "2"),
            ("built_at", "2026-07-29T00:00:00Z"),
            ("contract", "fixture"),
            ("source_signature", "signed"),
        ],
    )
    con.commit()
    con.close()
    before = {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file() and not path.is_symlink()
    }
    ssh_config = tmp_path / "ssh-config"
    ssh_config.write_text("", encoding="ascii")
    spec = probe.HostSpec(
        alias="local",
        platform="unix",
        root=str(root),
        target="local",
        codex_applicable=False,
        local=True,
    )

    report = probe.run_fleet_probe(
        [spec],
        ssh_config=ssh_config,
        expected_version="2026.7.25",
        expected_sha256={"src/tracked.py": hashlib.sha256(payload).hexdigest()},
        total_deadline_seconds=5,
        host_timeout_seconds=4,
        connect_timeout_seconds=1,
    )

    evidence = report["hosts"][0]["evidence"]
    assert evidence["version_match"] is True
    assert evidence["sha_checks"]["src/tracked.py"]["match"] is True
    assert evidence["fts5"]["source_signature_present"] is True
    assert evidence["guardian"]["ok"] is True
    assert evidence["guardian"]["reported_ok"] is True
    assert evidence["guardian"]["coverage_complete"] is True
    assert evidence["guardian"]["record_guardian"]["summary"]["record_count"] == 2
    assert evidence["guardian"]["record_guardian"]["refresh_attempt_age_seconds"] == 1
    assert evidence["guardian"]["record_guardian"]["refresh_throttled"] is True
    recoverability_probe = evidence["guardian"]["record_guardian"]["recoverability_probe"]
    assert recoverability_probe["schema"] == "recoverability_probe.v1"
    assert recoverability_probe["targeted_scan_count"] == 1
    assert recoverability_probe["canonical_cache_hit_count"] == 1
    assert recoverability_probe["canonical_cache_status"] == "unavailable"
    assert evidence["recall_performed"] is False
    assert evidence["write_performed"] is False
    assert "must not leak" not in json.dumps(report)
    assert "PrivatePath" not in json.dumps(report)
    after = {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file() and not path.is_symlink()
    }
    assert after == before


def test_fleet_probe_preserves_partial_guardian_as_not_green(tmp_path):
    probe = _load_probe()
    root = tmp_path / "time-library"
    (root / "runtime").mkdir(parents=True)
    (root / "VERSION").write_text("2026.7.25\n", encoding="ascii")
    guardian = {
        "ok": True,
        "measurement_status": "partial",
        "full_health_check": False,
        "not_measured_layers": ["scheduled_tasks"],
        "generated_at": "2026-08-04T00:00:00Z",
        "checks": [
            {"name": "install_root", "ok": True},
            {
                "name": "scheduled_tasks",
                "ok": None,
                "measurement_status": "not_measured",
                "detail": "must not leak",
            },
        ],
    }
    (root / "runtime" / "guardian-status.json").write_text(
        json.dumps(guardian), encoding="utf-8"
    )
    ssh_config = tmp_path / "ssh-config"
    ssh_config.write_text("", encoding="ascii")
    spec = probe.HostSpec(
        alias="local",
        platform="unix",
        root=str(root),
        target="local",
        codex_applicable=False,
        local=True,
    )

    report = probe.run_fleet_probe(
        [spec],
        ssh_config=ssh_config,
        expected_version="2026.7.25",
        expected_sha256={},
        total_deadline_seconds=5,
        host_timeout_seconds=4,
        connect_timeout_seconds=1,
    )

    evidence = report["hosts"][0]["evidence"]["guardian"]
    assert evidence["reported_ok"] is True
    assert evidence["ok"] is False
    assert evidence["measurement_status"] == "partial"
    assert evidence["full_health_check"] is False
    assert evidence["coverage_schema"] == "v1"
    assert evidence["coverage_schema_valid"] is True
    assert evidence["coverage_complete"] is False
    assert evidence["not_measured_layers"] == ["scheduled_tasks"]
    assert evidence["not_measured_check_names"] == ["scheduled_tasks"]
    assert "must not leak" not in json.dumps(report)


def test_fleet_probe_fails_closed_on_stale_guardian_status(tmp_path):
    probe = _load_probe()
    root = tmp_path / "time-library"
    (root / "runtime").mkdir(parents=True)
    (root / "VERSION").write_text("2026.7.25\n", encoding="ascii")
    status_path = root / "runtime" / "guardian-status.json"
    status_path.write_text(
        json.dumps({
            "ok": True,
            "measurement_status": "complete",
            "full_health_check": True,
            "not_measured_layers": [],
            "checks": [{"name": "guardian_health_execution", "ok": True}],
        }),
        encoding="utf-8",
    )
    stale_epoch = time.time() - (21 * 60)
    os.utime(status_path, (stale_epoch, stale_epoch))
    ssh_config = tmp_path / "ssh-config"
    ssh_config.write_text("", encoding="ascii")
    spec = probe.HostSpec(
        alias="local",
        platform="unix",
        root=str(root),
        target="local",
        codex_applicable=False,
        local=True,
    )

    report = probe.run_fleet_probe(
        [spec],
        ssh_config=ssh_config,
        expected_version="2026.7.25",
        expected_sha256={},
        total_deadline_seconds=5,
        host_timeout_seconds=4,
        connect_timeout_seconds=1,
    )

    evidence = report["hosts"][0]["evidence"]["guardian"]
    assert evidence["reported_ok"] is True
    assert evidence["coverage_complete"] is True
    assert evidence["status_fresh"] is False
    assert evidence["status_age_seconds"] >= 20 * 60
    assert evidence["status_max_age_seconds"] == 20 * 60
    assert evidence["ok"] is False


def test_fleet_probe_fails_closed_on_legacy_null_guardian_check(tmp_path):
    probe = _load_probe()
    root = tmp_path / "time-library"
    (root / "runtime").mkdir(parents=True)
    (root / "VERSION").write_text("2026.7.25\n", encoding="ascii")
    (root / "runtime" / "guardian-status.json").write_text(
        json.dumps({
            "ok": True,
            "checks": [{"name": "scheduled_tasks", "ok": None}],
        }),
        encoding="utf-8",
    )
    ssh_config = tmp_path / "ssh-config"
    ssh_config.write_text("", encoding="ascii")
    spec = probe.HostSpec(
        alias="local",
        platform="unix",
        root=str(root),
        target="local",
        codex_applicable=False,
        local=True,
    )

    report = probe.run_fleet_probe(
        [spec],
        ssh_config=ssh_config,
        expected_version="2026.7.25",
        expected_sha256={},
        total_deadline_seconds=5,
        host_timeout_seconds=4,
        connect_timeout_seconds=1,
    )

    evidence = report["hosts"][0]["evidence"]["guardian"]
    assert evidence["reported_ok"] is True
    assert evidence["ok"] is False
    assert evidence["measurement_status"] == "legacy_partial"
    assert evidence["coverage_schema"] == "legacy_incomplete"
    assert evidence["coverage_complete"] is False


def test_fleet_deadline_returns_partial_instead_of_waiting_for_slow_host(tmp_path):
    probe = _load_probe()
    ssh_config = tmp_path / "ssh-config"
    ssh_config.write_text("", encoding="ascii")
    specs = [
        probe.HostSpec("fast", "unix", "/tmp/fast", "fast"),
        probe.HostSpec("slow", "unix", "/tmp/slow", "slow"),
    ]

    def fake_probe(spec, **_kwargs):
        if spec.alias == "slow":
            time.sleep(0.35)
        return {
            "alias": spec.alias,
            "platform": spec.platform,
            "reachable": True,
            "method_status": "ok",
        }

    started = time.monotonic()
    report = probe.run_fleet_probe(
        specs,
        ssh_config=ssh_config,
        expected_version="",
        expected_sha256={},
        total_deadline_seconds=0.1,
        host_timeout_seconds=0.1,
        connect_timeout_seconds=1,
        probe=fake_probe,
    )
    elapsed = time.monotonic() - started

    assert elapsed < 0.25
    assert report["deadline_exhausted"] is True
    assert {item["alias"] for item in report["hosts"]} == {"fast", "slow"}
    assert next(item for item in report["hosts"] if item["alias"] == "slow")["method_status"] == "deadline_exhausted"


def test_windows_command_uses_encoded_powershell_and_stdin_source():
    probe = _load_probe()
    spec = probe.HostSpec(
        alias="win",
        platform="windows",
        root="C:" + r"\Users\Example\AppData\Local\time-library",
        target="win",
    )

    command = probe._windows_remote_command(spec)
    encoded = command.rsplit(" ", 1)[-1]
    decoded = base64.b64decode(encoded).decode("utf-16le")

    assert "-EncodedCommand" in command
    assert "-InputFormat Text -OutputFormat Text" in command
    assert "$ProgressPreference='SilentlyContinue'" in decoded
    assert "$ErrorActionPreference='Continue'" in decoded
    assert "[Console]::In.ReadToEnd()" not in decoded
    assert "& $p - $r $c $a" in decoded
    assert ".venv\\Scripts\\python.exe" in decoded
    assert "Invoke-RestMethod" not in decoded


def test_remote_probe_accepts_nonzero_transport_with_valid_read_only_report(monkeypatch, tmp_path):
    probe = _load_probe()
    spec = probe.HostSpec(
        alias="win",
        platform="windows",
        root="C:" + r"\Users\Example\AppData\Local\time-library",
        target="win",
    )
    payload = {
        "read_only": True,
        "recall_performed": False,
        "raw_excerpt_returned": False,
        "write_performed": False,
        "root_exists": True,
        "version": "2026.8.7",
        "sha_checks": {},
        "services": {},
        "listeners": {},
        "health": {},
        "capability": {},
        "guardian": {},
        "fts5": {},
        "codex_registration": {},
    }
    seen = {}

    def fake_run(command, *, stdin, timeout):
        seen["command"] = command
        seen["stdin"] = stdin
        seen["timeout"] = timeout
        return 1, json.dumps(payload) + "\n", "#< CLIXML\nprogress", False

    monkeypatch.setattr(probe, "_run", fake_run)

    result = probe._probe_one(
        spec,
        ssh_config=tmp_path / "config",
        source="print('probe')\n",
        connect_timeout=5,
        host_timeout=10,
        deadline=time.monotonic() + 10,
    )

    assert result["reachable"] is True
    assert result["method_status"] == "ok"
    assert result["evidence"] == payload
    assert result["method_warnings"] == ["remote_exit_nonzero_with_valid_read_only_report"]
    assert result["transport_diagnostics"] == {
        "returncode": 1,
        "timed_out": False,
        "stdout_bytes": len((json.dumps(payload) + "\n").encode("utf-8")),
        "stderr_bytes": len("#< CLIXML\nprogress".encode("utf-8")),
        "stdout_report_detected": True,
        "stderr_clixml_detected": True,
    }
    assert "-T" in seen["command"]
    assert seen["stdin"] == "print('probe')\n"


def test_remote_probe_failure_keeps_only_sanitized_transport_diagnostics(monkeypatch, tmp_path):
    probe = _load_probe()
    spec = probe.HostSpec(
        alias="win",
        platform="windows",
        root="C:" + r"\Users\Example\AppData\Local\time-library",
        target="win",
    )

    monkeypatch.setattr(
        probe,
        "_run",
        lambda *_args, **_kwargs: (
            255,
            "",
            "#< CLIXML\nprivate-path-must-not-leak",
            False,
        ),
    )

    result = probe._probe_one(
        spec,
        ssh_config=tmp_path / "config",
        source="print('probe')\n",
        connect_timeout=5,
        host_timeout=10,
        deadline=time.monotonic() + 10,
    )

    assert result["reachable"] is False
    assert result["error"] == "remote_probe_failed"
    assert result["transport_diagnostics"] == {
        "returncode": 255,
        "timed_out": False,
        "stdout_bytes": 0,
        "stderr_bytes": len("#< CLIXML\nprivate-path-must-not-leak".encode("utf-8")),
        "stdout_report_detected": False,
        "stderr_clixml_detected": True,
    }
    assert "private-path-must-not-leak" not in json.dumps(result)


def test_remote_probe_nonzero_incomplete_read_only_json_stays_failed(monkeypatch, tmp_path):
    probe = _load_probe()
    spec = probe.HostSpec(
        alias="win",
        platform="windows",
        root="C:" + r"\Users\Example\AppData\Local\time-library",
        target="win",
    )
    incomplete = {
        "read_only": True,
        "recall_performed": False,
        "raw_excerpt_returned": False,
        "write_performed": False,
    }
    monkeypatch.setattr(
        probe,
        "_run",
        lambda *_args, **_kwargs: (1, json.dumps(incomplete), "", False),
    )

    result = probe._probe_one(
        spec,
        ssh_config=tmp_path / "config",
        source="print('probe')\n",
        connect_timeout=5,
        host_timeout=10,
        deadline=time.monotonic() + 10,
    )

    assert result["reachable"] is False
    assert result["error"] == "remote_probe_failed"
    assert result["transport_diagnostics"]["stdout_report_detected"] is True


def test_unix_command_uses_installed_runtime_python():
    probe = _load_probe()
    spec = probe.HostSpec(
        alias="unix",
        platform="unix",
        root="/srv/time library",
        target="unix",
    )

    command = probe._unix_remote_command(spec)

    assert command.startswith("'/srv/time library/.venv/bin/python' - ")


def test_remote_probe_source_falls_back_to_formal_codex_cli():
    probe = _load_probe()
    source = probe.REMOTE_PROBE_SOURCE

    assert 'shutil.which("codex")' in source
    assert '[codex, "mcp", "get", "time-library"]' in source
    assert '"evidence_source": "codex_mcp_get"' in source
    assert 'fields.get("command"' in source
