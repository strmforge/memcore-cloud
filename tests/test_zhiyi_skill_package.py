import importlib.util
import io
import json
import os
import re
import sys
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / "system" / "skills" / "time-library"
TIME_LIBRARY_SKILL_DIR = ROOT / "system" / "skills" / "time-library"
CLAUDE_SKILL_HELPER = ROOT / "tools" / "install_claude_desktop_skill.py"
CODEX_SKILL_STATUS = ROOT / "tools" / "codex_zhiyi_skill_status.py"


def _load_claude_skill_helper():
    sys.modules.pop("install_claude_desktop_skill_under_test", None)
    spec = importlib.util.spec_from_file_location(
        "install_claude_desktop_skill_under_test",
        CLAUDE_SKILL_HELPER,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _load_codex_skill_status():
    sys.modules.pop("codex_zhiyi_skill_status_under_test", None)
    spec = importlib.util.spec_from_file_location(
        "codex_zhiyi_skill_status_under_test",
        CODEX_SKILL_STATUS,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_zhiyi_skill_package_is_platform_neutral():
    skill = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    lowered = skill.lower()
    compact_skill = re.sub(r"\s+", " ", skill)

    assert "version: 2026.8.13" in skill
    assert "prompt_version: 6" in skill
    assert "description: >-" in skill
    assert "Use when the user refers" in skill
    assert "already-built work" in skill
    assert "already built" in skill
    assert "forgotten" in skill
    assert "argument-hint" in skill
    assert "When To Use" in skill
    assert "not as an imagination layer" in skill
    assert "local archivist" in skill
    assert "source-backed memory" in skill
    assert "standing active memory routing rule" in skill
    assert "Default Contract" in skill
    assert "Platform-Neutral Connection" in skill
    assert "action=self_report_connect" in skill
    assert "proof_library_id" in skill
    assert "Never recall private memory merely to prove installation" in compact_skill
    assert '"mode":"preflight"' in skill
    assert "Call `time_library_recall`" in skill
    assert "If `time_library_recall` is not available" in skill
    assert "MCP/tool connection is missing" in skill
    assert "current window/session first" in skill
    assert "same project/workspace" in compact_skill
    assert "same workstream/task" in compact_skill
    assert "stable preferences/tool facts" in skill
    assert "Treat raw-pool/global as explicit only" in skill
    assert "scope_missing=true" in skill
    assert "recall_status=window_identity_required" in skill
    assert "Do not say there is no memory" in skill
    assert "installed, tested, released" in skill
    assert "定论" in skill
    assert "下一步" in skill
    assert "接下来呢" in skill
    assert "还有吗" in skill
    assert "然后呢" in skill
    assert "next step" in skill
    assert "what else" in skill
    assert "then what" in skill
    assert "short ongoing-work prompts" in skill
    assert "preferences and intent experience" in skill
    assert "work experience" in skill
    assert "toolbook" in skill
    assert "errata" in skill
    assert "Reading Area" in skill
    assert "capability_check" in skill
    assert "library_id" in skill
    assert "rank_reason" in skill
    assert "codex only" not in lowered
    assert "only supports codex" not in lowered
    assert "openclaw" in lowered
    assert "hermes" in lowered
    assert "codex" in lowered
    assert "claude" in lowered
    assert "mcp" in lowered


def test_time_library_skill_primary_entrypoint_exists_without_removing_legacy_alias():
    skill = (TIME_LIBRARY_SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    metadata = (TIME_LIBRARY_SKILL_DIR / "agents" / "openai.yaml").read_text(encoding="utf-8")

    assert "name: time-library" in skill
    assert "# Time Library" in skill
    assert "call time_library_recall before answering" in skill
    assert "legacy alias `zhiyi_recall`" in skill
    assert "MCP/tool connection is missing" in skill
    assert "reading area is a read-only" in skill
    assert "`raw`" in skill and "`zhiyi`" in skill and "`xingce`" in skill
    assert "value: \"time-library\"" in metadata
    assert "call time_library_recall first" in metadata
    assert "legacy zhiyi_recall" in metadata
    assert (SKILL_DIR / "SKILL.md").exists()


def test_zhiyi_skill_declares_mcp_as_connection_layer():
    metadata = (SKILL_DIR / "agents" / "openai.yaml").read_text(encoding="utf-8")
    metadata_lowered = metadata.lower()
    try:
        import yaml  # type: ignore
    except Exception:
        yaml = None

    if yaml is not None:
        parsed = yaml.safe_load(metadata)
        default_prompt = parsed["interface"]["default_prompt"]
        assert len(default_prompt) <= 1024
        assert "call time_library_recall first" in default_prompt
        assert "MCP/tool connection is missing" in default_prompt

    assert "time-library" in metadata
    assert "Time Library" in metadata
    assert "Use for prior decisions, corrections, already-built work, status, and next steps" in metadata
    assert "memory-dependent answers" in metadata
    assert "previous decisions" in metadata_lowered
    assert "already-built work" in metadata
    assert "call time_library_recall first" in metadata_lowered
    assert "standing active memory rule" in metadata
    assert "one-time setup note" in metadata
    assert "capability check" in metadata
    assert "capability_check" in metadata
    assert "MCP/tool connection is missing" in metadata
    assert "same project/workspace" in metadata
    assert "same workstream/task" in metadata
    assert "stable preferences/tool facts" in metadata
    assert "raw-pool/global only when explicitly requested" in metadata
    assert "window scope is unbound" in metadata
    assert "install/test/release status" in metadata
    assert "type: \"mcp\"" in metadata
    assert 'discovery_file: "<TIME_LIBRARY_ROOT>/runtime/front_door_port"' in metadata
    assert 'mcp_path: "/mcp"' in metadata
    assert "discovery://" not in metadata


def test_readme_install_prompts_teach_agents_to_install_and_call_recall():
    for relative in ["README.md", "README.en.md"]:
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert "You are installing Time Library for me on this machine." in text
        assert "Repository: https://github.com/strmforge/time-library" in text
        assert "standing memory rule" in text
        assert "not just a one-time setup note" in text
        assert "register the MCP tool named time-library" in text
        assert '{"query":"capability check","mode":"capability_check"}' in text
        assert "Keep this rule active from now on" in text
        assert "call time_library_recall before answering" in text
        assert "do not reinstall it" in text
        assert "host report is authoritative" in text
        assert "self_report_connect" in text
        assert "proof_library_id" in text
        assert "next step" in text
        assert "what else" in text
        assert "then what" in text
        assert "MCP/tool connection is missing" in text
        assert "guessing from memory" in text
        assert "current window/session first" in text
        assert "same project/workspace" in text
        assert "same workstream/task" in text
        assert "stable preferences/tool facts" in text
        assert "raw-pool/global" in text
        assert "do not claim there is no memory" in text

    zh = (ROOT / "README.zh-CN.md").read_text(encoding="utf-8")
    root = (ROOT / "README.md").read_text(encoding="utf-8")
    for text in (zh, root):
        assert "你正在帮我在这台机器安装 Time Library" in text
        assert "仓库：https://github.com/strmforge/time-library" in text
        assert "长期记忆规则" in text
        assert "注册名为 time-library 的 MCP 工具" in text
        assert '{"query":"capability check","mode":"capability_check"}' in text
        assert "请持续遵守这条规则" in text
        assert "请先调用 time_library_recall" in text
        assert "下一步/接下来呢/还有吗/然后呢" in text
        assert "当前窗口/session 优先" in text
        assert "同项目/同工作区" in text
        assert "同工作流/同任务" in text
        assert "稳定偏好/工具事实" in text
        assert "raw-pool/global" in text
        assert "不要说没有记忆" in text
        assert "不要凭印象猜" in text


def test_full_installers_install_codex_skill_and_register_mcp_when_available():
    for relative in [
        "tools/macos_full_install.sh",
        "tools/linux_full_install.sh",
        "tools/windows_full_install.ps1",
    ]:
        text = (ROOT / relative).read_text(encoding="utf-8")
        normalized = text.replace("\\", "/")
        assert "time-library" in text
        assert "time-library" in text
        assert "system/skills/time-library" in normalized
        assert "Hermes skill installed" in text
        assert "Hermes skill:" in text
        assert "Codex skill installed" in text
        assert "Moved stale Codex Time Library skill backup out of active skills" in text
        assert "skills-backups" in text
        assert "time-library.backup" in text
        assert "time-library.backup" in text
        assert "Codex skill:" in text
        assert "front-door discovery" in text or "front_door_port" in text
        assert "Codex MCP registered" in text
        assert "codex_mcp_bridge.py" in text
        assert "codex_mcp_config_guard.py" in text
        assert "protected relay-preserving guard" in text
        assert "Codex MCP config guard" in text
        assert "codex mcp add time-library" not in text
        assert "codex mcp remove time-library" not in text
        assert "--create --json" in text
        assert "receipt_url" in text
        assert "enable_receipts" in text
        assert "enable_queue_prefetch" in text
        assert "Claude Desktop MCP" in text
        assert "claude_desktop_mcp_bridge.py" in text
        assert "install_claude_desktop_skill.py" in text
        assert "claude_desktop_config.json" in text
        assert "install_claude_code_preflight_hook.py" in text
        assert "claude_code_preflight_hook.py" in text
        assert "UserPromptSubmit" in text or "Claude Code preflight hook" in text
        assert "Claude Code preflight hook:" in text
        assert '"type": "stdio"' in text
        assert '"PYTHONIOENCODING": "utf-8"' in text
        assert '"PYTHONUTF8": "1"' in text
        assert "MEMCORE_ROOT" in text
        assert "MEMCORE_WINDOW_BINDING_REGISTRY" in text
        assert "MEMCORE_CLAUDE_DESKTOP_CANONICAL_WINDOW_ID" in text
        assert "MEMCORE_CLAUDE_DESKTOP_SESSION_ID" in text
        assert "--window-binding-registry" in text
        assert "--binding-key" in text
        assert "chrome-native-hosts-v2.json" in text
        assert "chrome-native-hosts.json" in text
        assert "claude_desktop" in text
        assert "--create --json" in text
        assert "p0_watcher_resource_profile" in text
        assert "p0_watcher_source_default" in text
        assert "all" in text
        assert "--watch --source all" in text
        if relative.endswith(".ps1"):
            assert "Find-CodexCli" in text
            assert "$codexExe" in text
            assert "Install-ClaudeCodePreflightHook" in text
            assert "Get-RuntimePython" in text
            assert "p0_watcher_interval_milliseconds = 5000" in text
            assert "interval_milliseconds = 5000" in text
            assert "interval_seconds = 1" not in text
        else:
            assert "find_codex_cli" in text
            assert "codex_exe" in text
            assert "install_claude_code_preflight_hook" in text
            assert '"p0_watcher_interval_milliseconds": int(' in text
            assert '"interval_milliseconds": int(raw_ingest.get("interval_milliseconds") or 5000)' in text
            assert '"interval_seconds": int(raw_ingest.get("interval_seconds") or 1)' not in text
            assert "capability_smoke" in text
            assert '"method": "tools/call"' in text
            assert '"name": "time_library_recall"' in text
            assert '"mode": "capability_check"' in text
            assert '"consumer": "unix-install-smoke"' in text
            assert "recall_performed" in text
            assert "raw_excerpt_returned" in text
            assert "capability_check: ok version" in text


def test_windows_guardian_preserves_source_all_watcher_contract():
    text = (ROOT / "tools" / "windows_guardian.ps1").read_text(encoding="utf-8")
    installer = (ROOT / "tools" / "windows_full_install.ps1").read_text(encoding="utf-8")
    smoke = (ROOT / "tools" / "windows_native_smoke.ps1").read_text(encoding="utf-8")

    assert "MEMCORE_WATCHER_SOURCE_DEFAULT=all" in text
    assert "--watch --source all" in text
    assert "MEMCORE_WATCHER_SOURCE_DEFAULT=codex" not in text
    installer_start = installer.split("function Start-MemcoreService {", 1)[1].split(
        "function Start-RestoredScheduledTask {", 1
    )[0]
    assert 'if ($Name -eq "p0-watcher")' in installer_start
    assert "MEMCORE_WATCHER_RESOURCE_PROFILE=light" in installer_start
    assert "MEMCORE_WATCHER_SOURCE_DEFAULT=all" in installer_start
    assert "MEMCORE_WATCHER_INTERVAL_MS=5000" in installer_start
    assert "[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)" in text
    assert "$OutputEncoding = [Console]::OutputEncoding" in text
    assert "[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)" in smoke
    assert "$OutputEncoding = [Console]::OutputEncoding" in smoke
    assert "[switch]$NoStatusWrite" in text
    assert "if (-not $NoStatusWrite)" in text
    assert "if ($Json) { Write-Output $jsonText }" in text
    assert "[int]$StartupTimeoutSeconds = 20" in text
    assert "for ($i = 0; $i -lt $StartupTimeoutSeconds; $i++)" in text
    assert "-StartupTimeoutSeconds 120" in text
    assert '"-StartWatcher", "-Json"' in smoke
    assert 'if ($SkipCodex) {' in smoke
    assert '$guardianArgs += "-NoStatusWrite"' in smoke
    assert '$guardianArgs += "-Backfill"' in smoke
    assert "/api/v1/records/guardian/status?limit=80&mode=fast&compact=1" in smoke
    assert "$summary.raw_attention_count" in smoke
    assert "record attention preserved; raw_attention={0}" in smoke
    assert "Guardian is not ok without record-attention evidence" in smoke
    assert "p0_watcher_source_scope" in smoke
    assert "MEMCORE_WATCHER_RESOURCE_PROFILE=light" in smoke
    assert "MEMCORE_WATCHER_SOURCE_DEFAULT=all" in smoke
    assert "MEMCORE_WATCHER_INTERVAL_MS=5000" in smoke
    assert "$missingContractFields" in smoke
    assert "watcher launcher contract missing or invalid" in smoke
    assert "--watch\\s+--source\\s+all" in smoke
    assert '$would.applies_to -notcontains "evidence_bound_analysis"' in smoke
    assert '$would.applies_to -notcontains "zhiyi_frontstage"' not in smoke


def test_windows_guardian_uses_watcher_owned_pid_anchor_and_bounded_logs():
    text = (ROOT / "tools" / "windows_guardian.ps1").read_text(encoding="utf-8")
    watcher_start = text.split("function Start-P0WatcherIfMissing {", 1)[1].split(
        "function Start-MemcoreServiceIfMissing {", 1
    )[0]

    assert "return ,$ids" in text
    assert "Get-P0WatcherPidAnchorProcesses" in text
    assert "$WatcherPidStartToleranceSeconds = 120" in text
    assert "$delta -le $WatcherPidStartToleranceSeconds" in text
    assert 'Name -notmatch "^python(?:w)?\\.exe$"' in text
    assert "Start-HiddenCommandProcess -CmdPath $cmdPath | Out-Null" in watcher_start
    assert "Set-Content" not in watcher_start

    assert "$GuardianLogMaxBytes = 5MB" in text
    assert "$GuardianLogRetention = 2" in text
    assert "function Invoke-BoundedLogRotation" in text
    assert "[System.IO.Compression.GZipStream]::new" in text
    assert 'Write-Utf8NoBom -Path $Path -Text ""' in text
    assert 'Invoke-BoundedLogRotation -Path $GuardianLog' in text
    assert 'Invoke-BoundedLogRotation -Path $GuardianErr' in text


def test_windows_guardian_persists_safe_bounded_record_summary_without_implicit_backfill():
    text = (ROOT / "tools" / "windows_guardian.ps1").read_text(encoding="utf-8")
    evidence = text.split("function ConvertTo-SafeRecordGuardianSummary {", 1)[1].split(
        "function Invoke-RecordGuardianBackfillIfNeeded {", 1
    )[0]
    normal_flow = text.split("try {", 1)[-1]

    assert "$RecordGuardianCacheMaxAgeSeconds = 1800" in text
    assert "function Update-RecordGuardianEvidence" in evidence
    assert "function Get-ThrottledRecordGuardianEvidence" in evidence
    assert "fast_compact_api" in evidence
    assert "details_persisted = $false" in evidence
    assert "guardian_status_cache" in evidence
    assert "stale_guardian_status_cache" in evidence
    assert "last_refresh_attempt_at" in evidence
    assert "refresh_attempt_age_seconds" in evidence
    assert "refresh_throttled = $true" in evidence
    assert "refresh throttled attempt_age_seconds=" in evidence
    assert "$script:RecordGuardianStatusAttempted = $true" in evidence
    assert "P6 guardian API already attempted; fallback to connector" in text
    for field in (
        "raw_attention_count",
        "raw_divergence_generation_active_count",
        "lost_source_count",
        "lost_source_recoverable_count",
        "lost_source_unrecoverable_count",
        "lost_source_not_measured_count",
        "lost_raw_count",
        "backfill_recommended_count",
    ):
        assert field in evidence
    assert "$hasCompleteTriage" in evidence
    assert "$unrecoverableCount = $lostSourceCount" in evidence
    assert evidence.count(
        "ConvertTo-SafeRecordGuardianSummary -Status ([pscustomobject]@{ summary = $evidence.summary })"
    ) == 2
    for forbidden in ("records =", "session_id", "source_path", "raw_path"):
        assert forbidden not in evidence
    assert "Update-RecordGuardianEvidence" in normal_flow
    assert "if ($Backfill) { Invoke-CodexRawBackfillIfNeeded }" in normal_flow


def test_windows_native_smoke_fails_closed_on_incomplete_lost_source_triage():
    text = (ROOT / "tools" / "windows_native_smoke.ps1").read_text(encoding="utf-8")
    evidence = text.split("function Test-GuardianAndTray {", 1)[1].split(
        "function Test-CodexCaptureStatus {", 1
    )[0]

    for field in (
        "lost_source_recoverable_count",
        "lost_source_unrecoverable_count",
        "lost_source_not_measured_count",
    ):
        assert field in evidence
    assert "$hasCompleteTriage" in evidence
    assert "$lostSourceRecoverable + $lostSourceUnrecoverable + $lostSourceNotMeasured" in evidence
    assert "$lostSourceUnrecoverable = $lostSourceCount" in evidence


def test_windows_guardian_uses_service_owned_pid_and_port_anchors():
    guardian = (ROOT / "tools" / "windows_guardian.ps1").read_text(encoding="utf-8")
    installer = (ROOT / "tools" / "windows_full_install.ps1").read_text(encoding="utf-8")

    assert "$ServicePidStartToleranceSeconds = 120" in guardian
    assert "Get-MemcoreServicePidAnchorProcesses" in guardian
    assert "Resolve-MemcoreServicePort" in guardian
    assert "Test-ProcessTreeContainsAny -TreeIds $treeIds -ProcessIds $listenerIds" in guardian
    assert "(-not [string]::IsNullOrWhiteSpace($executablePath)) -and" in guardian
    assert "$executablePath -ne $venvPython" in guardian
    assert 'Join-Path $InstallRoot ".venv\\Scripts\\python.exe"' in guardian
    assert "Set-MemcoreServicePidAnchor" in guardian
    assert '[System.IO.File]::SetLastWriteTimeUtc($pidPath, $started)' in guardian
    assert "$currentPid -ne $canonicalPid" in guardian
    assert "-not $pythonIds.Contains([int]$_.ParentProcessId)" in guardian
    assert "Get-StartedServiceProcessTree" in guardian
    service_start = guardian.split("function Start-MemcoreServiceIfMissing {", 1)[1].split(
        "function Start-RuntimeServicesIfMissing {", 1
    )[0]
    assert "Get-StartedServiceProcessTree -RootProcessId $rootPid -Port $runtimePort" in service_start
    assert 'Set-Content -LiteralPath (Join-Path $RuntimeDir "$Name.pid")' not in service_start
    assert "$ready = ($runtimePort -gt 0)" in service_start
    assert "Set-CanonicalStartedServicePid" in installer
    canonicalizer = installer.split("function Set-CanonicalStartedServicePid {", 1)[1].split(
        "function Start-MemcoreService {", 1
    )[0]
    assert 'if ($Name -eq "p0-watcher") { return }' in canonicalizer
    assert "Get-OwnedInstallProcessRecords" in canonicalizer
    assert "ExecutablePath" in canonicalizer
    assert '[System.IO.File]::SetLastWriteTimeUtc($PidPath, $started)' in canonicalizer


def test_codex_zhiyi_skill_status_reports_duplicate_backups_and_mcp(tmp_path):
    helper = _load_codex_skill_status()
    codex_home = tmp_path / ".codex"
    main = codex_home / "skills" / "time-library"
    backup = codex_home / "skills" / "time-library.backup.20260601"
    main.mkdir(parents=True)
    backup.mkdir(parents=True)
    (main / "SKILL.md").write_text(
        '---\nname: time-library\nversion: 2026.6.15\ndescription: Old local memory library\n---\n',
        encoding="utf-8",
    )
    (backup / "SKILL.md").write_text(
        '---\nname: time-library\nversion: 2026.6.1\ndescription: backup\n---\n',
        encoding="utf-8",
    )
    (codex_home / "config.toml").write_text(
        '[mcp_servers.time-library]\n'
        'command = "python3"\n'
        'args = ["codex_mcp_bridge.py", "--endpoint", "http://127.0.0.1:9851/mcp"]\n',
        encoding="utf-8",
    )

    status = helper.build_status(codex_home=codex_home, repo_root=ROOT)

    assert status["ok"] is False
    assert status["matching_skill_count"] == 2
    assert status["backup_skill_count"] == 1
    assert "backup_skill_dirs_in_active_root" in status["issues"]
    assert "duplicate_same_name_skills" in status["issues"]
    assert "main_description_not_use_when" in status["issues"]
    assert "active_skill_version_drift" in status["issues"]
    assert status["mcp"]["mcp_present"] is True
    assert status["mcp"]["uses_codex_mcp_bridge"] is True
    assert "Move time-library.backup" in status["recommendation"]
    assert "time-library.backup" in status["recommendation"]


def test_codex_skill_status_accepts_primary_time_library_skill_and_legacy_mcp(tmp_path):
    helper = _load_codex_skill_status()
    codex_home = tmp_path / ".codex"
    main = codex_home / "skills" / "time-library"
    main.mkdir(parents=True)
    (main / "SKILL.md").write_text(
        '---\nname: time-library\nversion: 2026.8.13\nprompt_version: 6\ndescription: Use when prior context matters; call time_library_recall.\n---\n',
        encoding="utf-8",
    )
    (codex_home / "config.toml").write_text(
        '[mcp_servers.time-library]\n'
        'command = "python3"\n'
        'args = ["codex_mcp_bridge.py", "--endpoint", "http://127.0.0.1:9851/mcp"]\n',
        encoding="utf-8",
    )

    status = helper.build_status(codex_home=codex_home, repo_root=ROOT)

    assert status["ok"] is True
    assert status["primary_skill_count"] == 1
    assert status["legacy_skill_count"] == 0
    assert status["primary_skill"]["name"] == "time-library"
    assert status["repo_skill"]["name"] == "time-library"
    assert "repo_legacy_skill" not in status
    assert status["mcp"]["mcp_present"] is True
    assert "time-library" in status["mcp"]["mcp_server_names"]


def test_windows_installer_ignores_windowsapps_python_placeholder():
    windows = (ROOT / "tools" / "windows_full_install.ps1").read_text(encoding="utf-8")

    assert "$exe.Source -notmatch \"\\\\WindowsApps\\\\\"" in windows
    assert 'Join-Path $env:LOCALAPPDATA "Programs\\Python"' in windows
    assert '"C:\\Program Files"' in windows
    assert '"C:\\Program Files (x86)"' in windows
    assert "Get-ChildItem $root -Recurse -Filter python.exe" in windows
    assert 'Where-Object { $_.FullName -notmatch "\\\\WindowsApps\\\\" }' in windows
    assert "Test-PythonCandidate -Path $candidate.FullName" in windows


def test_windows_installer_registers_mcp_with_runtime_venv_python():
    windows = (ROOT / "tools" / "windows_full_install.ps1").read_text(encoding="utf-8")

    assert "function Get-RuntimePython" in windows
    assert 'Join-Path $InstallRoot ".venv\\Scripts\\python.exe"' in windows
    assert "Test-PythonCandidate -Path $venvPython" in windows

    codex_section = windows.split("function Install-CodexMcp", 1)[1].split(
        "function Install-ClaudeDesktopMcp",
        1,
    )[0]
    claude_section = windows.split("function Install-ClaudeDesktopMcp", 1)[1].split(
        "function Start-MemcoreService",
        1,
    )[0]

    assert "$python = Get-RuntimePython" in codex_section
    assert "$python = Find-Python" not in codex_section
    assert "runtime python not found" in codex_section

    assert "$python = Get-RuntimePython" in claude_section
    assert "$python = Find-Python" not in claude_section
    assert "runtime python not found" in claude_section
    assert '"command": sys.executable' in claude_section


def test_windows_native_smoke_is_repeatable_no_recall_and_not_vm_based():
    smoke = (ROOT / "tools" / "windows_native_smoke.ps1").read_text(encoding="utf-8")
    installer = (ROOT / "tools" / "windows_full_install.ps1").read_text(encoding="utf-8")
    guardian = (ROOT / "tools" / "windows_guardian.ps1").read_text(encoding="utf-8")
    hidden_guardian = (ROOT / "tools" / "windows_hidden_guardian.vbs").read_text(encoding="utf-8")
    tray = (ROOT / "tools" / "windows_tray.ps1").read_text(encoding="utf-8")
    uninstaller = (ROOT / "uninstall.ps1").read_text(encoding="utf-8")
    wiki = (ROOT / "docs" / "wiki" / "Native-Windows-Codex.md").read_text(encoding="utf-8")
    guardian_section = smoke.split("function Test-GuardianAndTray {", 1)[1].split(
        "function Test-CodexCaptureStatus", 1
    )[0]

    assert 'tool = "windows_native_smoke"' in smoke
    assert 'target = "native_windows"' in smoke
    assert 'method = "tools/call"' in smoke
    assert 'name = "zhiyi_recall"' in smoke
    assert 'mode = "capability_check"' in smoke
    assert 'mode = "work_preflight"' in smoke
    assert 'consumer = "windows-native-smoke"' in smoke
    assert "Invoke-WorkPreflightCheck" in smoke
    assert "agent_work_preflight.v2026.6.20" in smoke
    assert "zhixing_preflight.v2026.6.20" in smoke
    assert "agent_work_preflight_read_only" in smoke
    assert "should_intervene" in smoke
    assert "prompt_class" in smoke
    assert "recall_performed" in smoke
    assert "raw_excerpt_returned" in smoke
    assert "read_only" in smoke
    assert "Find-CodexCli" in smoke
    assert "chrome-native-hosts-v2.json" in smoke
    assert "chrome-native-hosts.json" in smoke
    assert "codex mcp list" in smoke
    assert '-InstallRoot `"$InstallRoot`" -Json' in installer
    assert 'windows_native_smoke.ps1`" -InstallRoot `"$InstallRoot`"' in installer
    assert "endpoint_url = sys.argv[3] if len(sys.argv) > 3 else" in installer
    assert "dialog_entry_token = sys.argv[4] if len(sys.argv) > 4 else" in installer
    assert "p0_watcher_process" in smoke
    assert "Get-AuthorizedP0WatcherProcesses" in smoke
    assert "Test-P0WatcherCommandLine" in smoke
    assert "Test-CommandLineHasInstallRoot" in smoke
    assert "authorized tree PID" in smoke
    assert "codex_capture_status" in smoke
    assert "Test-CodexCaptureStatus" in smoke
    assert "ConvertFrom-JsonOutput" in smoke
    assert "no balanced JSON object found" in smoke
    assert "capture_independent_of_mcp" in smoke
    assert "$consoleUrl = $RawGatewayUrl" in guardian_section
    assert "raw_sync" in smoke
    assert "$captureStatusMaxAttempts = 8" in smoke
    assert "$captureStatusPollMilliseconds = 5000" in smoke
    assert 'Start-Sleep -Milliseconds $captureStatusPollMilliseconds' in smoke
    assert 'raw_missing", "raw_lagging_sla_breach"' in smoke
    assert "Codex source records remain ahead after {0} bounded checks" in smoke
    assert "raw_archive_total_lag_bytes" in smoke
    assert "raw_archive_max_lag_milliseconds" in smoke
    assert "raw_lag_sla_breach_count" in smoke
    assert "codex_consumer_mcp_optional" in smoke
    assert "local capture still uses source files" in smoke
    assert "Test-CodexProviderBucket" in smoke
    assert "codex_provider_bucket" in smoke
    assert "provider_bucket_matches_section" in smoke
    assert "codex_provider_route_binding" in smoke
    assert "provider_bucket_name_is_route_identity = $false" in smoke
    assert 'ToLowerInvariant() -ne "token"' not in smoke
    assert "127.0.0.1:15721" in smoke
    assert "codex_local_proxy_health" in smoke
    assert "models_404_not_fatal" in smoke
    assert "diagnostic only" in smoke
    assert "codex_responses_probe" in smoke
    assert "provider bucket names are host-defined" in smoke
    assert "Read-CodexConfigForSmoke" in smoke
    assert "Convert-TomlScalarForSmoke" in smoke
    assert "Get-HttpStatusCodeForSmoke" in smoke
    assert "Test-ZhiyiModelBinding" in smoke
    assert "zhiyi_model_ui" in smoke
    assert "/api/v1/zhiyi/model-options" in smoke
    assert "/api/v1/zhiyi/model-binding/dry-run" in smoke
    assert "zhiyi_model_binding.user.json" in smoke
    assert "MEMCORE_ZHIYI_API_KEY" in smoke
    assert "secrets_stored" in smoke
    assert "model_call_performed" in smoke
    assert "本机工具识别模型" in smoke
    assert "Local Tool Recognition Model" in smoke
    assert "windows_guardian_script" in smoke
    assert "windows_hidden_guardian_launcher" in smoke
    assert "windows_tray_script" in smoke
    assert "MemcoreCloudGuardianLogon" in smoke
    assert "MemcoreCloudGuardianHealth" in smoke
    assert "MemcoreCloudTray" in smoke
    assert "guardian task must use wscript hidden launcher" in smoke
    assert "guardian hidden launcher is missing" in smoke
    assert "tray task action is not hidden; a console window may flash" in smoke
    assert "windows_guardian_run" in smoke
    assert "guardian-status.json" in smoke
    assert "guardian_status_content" in smoke
    assert "guardian status file is not ok" in smoke
    assert "windows_guardian.ps1" in installer
    assert "windows_hidden_guardian.vbs" in installer
    assert "windows_tray.ps1" in installer
    assert "Register-WindowsAutostart" in installer
    assert "New-ScheduledTaskTrigger -AtLogOn" in installer
    assert "RepetitionInterval (New-TimeSpan -Minutes 5)" in installer
    assert "$guardPeriodicTrigger = New-ScheduledTaskTrigger" in installer
    assert "$guardTriggers = @($guardLogonTrigger, $guardPeriodicTrigger)" in installer
    assert "-Trigger $guardTriggers" in installer
    assert "MemcoreCloudGuardianLogon" in installer
    assert "MemcoreCloudGuardianHealth" in installer
    assert "MemcoreCloudTray" in installer
    assert "System32\\wscript.exe" in installer
    assert 'New-ScheduledTaskAction -Execute $wscriptExe -Argument $guardianLogonArgs' in installer
    assert 'New-ScheduledTaskAction -Execute $wscriptExe -Argument $guardianHealthArgs' in installer
    assert "-STA -ExecutionPolicy Bypass -WindowStyle Hidden" in installer
    assert "Start-ScheduledTask -TaskName \"MemcoreCloudTray\"" in installer
    assert "MemcoreCloudGuardianLogon" in uninstaller
    assert "MemcoreCloudGuardianHealth" in uninstaller
    assert "MemcoreCloudTray" in uninstaller
    assert "windows_tray.ps1" in uninstaller
    assert "windows_guardian.ps1" in uninstaller
    assert "windows_guardian" in guardian
    assert "windows_guardian.ps1" in hidden_guardian
    assert "exitCode = shell.Run(commandLine, 0, True)" in hidden_guardian
    assert "WScript.Quit exitCode" in hidden_guardian
    assert "-StartWatcher -Quiet" in hidden_guardian
    assert "-StartWatcher -Backfill -Quiet" not in hidden_guardian
    assert "guardian_already_running" in guardian
    assert "[System.IO.File]::Open" in guardian
    assert "[System.IO.FileShare]::None" in guardian
    assert "Ensure-GuardianHealthTaskSchedule" in guardian
    assert "Ensure-CodexMcpGuardTaskHealth" in guardian
    assert "Test-CodexMcpGuardTaskOwned" in guardian
    assert "Get-CodexMcpGuardProcesses" in guardian
    assert 'Add-Check -Name "codex_mcp_guard_task"' in guardian
    assert 'Start-ScheduledTask -TaskName $taskName -ErrorAction Stop' in guardian
    assert "--once" in guardian
    assert "one_shot_reconcile" in guardian
    assert '"migrated interval to PT5M"' in guardian
    assert "shouldWriteStatus" in guardian
    assert "existing.generated_at" in guardian
    assert "p0-watcher.cmd" in guardian
    assert "Get-P0WatcherTree" in guardian
    assert "Test-P0WatcherCommandLine" in guardian
    assert "Normalize-PathText" in guardian
    assert "[regex]::Replace($normalized, \"/+\", \"/\")" in guardian
    assert "[regex]::Replace($normalized, \"/+\", \"/\")" in smoke
    assert "Test-CommandLineHasInstallRoot" in guardian
    assert "Test-ProcessesOlderThanFile" in guardian
    assert "Stop-ProcessTreeByRoots" in guardian
    assert "Get-FileSha256" in guardian
    assert "Test-ServiceSourceChanged" in guardian
    assert ".source.sha256" in guardian
    assert "source file newer than running process or source hash changed" in guardian
    assert "Get-PortListenerProcessIds" in guardian
    assert "Get-PortListenerProcessSummaries" in guardian
    assert "$listenerPid" in guardian
    assert "foreach ($pid in" not in guardian
    assert "Add-PortOwnerDiagnostic" in guardian
    assert "any_wslrelay_owner" in guardian
    assert "is_wslrelay" in guardian
    assert "Test-MemcoreServicePortReady" in guardian
    assert "Test-RawGatewayHealthIdentity" in guardian
    assert "Get-InstallVersion" in guardian
    assert "Test-RawGatewayHealthVersion" in guardian
    assert '([string]$health.service -eq "raw_consumption_gateway")' in guardian
    assert "$health.preflight -eq $true" in guardian
    assert "$Health.version" in guardian
    assert "$Health.source_path" in guardian
    assert "$Health.source_sha256" in guardian
    assert 'Join-Path $InstallRoot "src\\raw_consumption_gateway.py"' in guardian
    assert "Select-CanonicalServiceRoot" in guardian
    assert "Stop-DuplicateServiceProcessRoots" in guardian
    assert "_duplicate_processes" in guardian
    assert "kept root PID" in guardian
    assert "p0_watcher_cmd_refreshed" in guardian
    assert "Start-RuntimeServicesIfMissing" in guardian
    assert "Start-MemcoreServiceIfMissing" in guardian
    assert "Start-HiddenCommandProcess" in guardian
    assert '([WMIClass]"Win32_Process").Create' in guardian
    assert "Start-Process -FilePath $env:ComSpec" not in guardian
    assert 'Name "p3-recall"' in guardian
    assert 'ScriptName "p3_recall.py"' in guardian
    assert 'Name "p4-provider"' in guardian
    assert 'ScriptName "p4_provider.py"' in guardian
    assert 'Name "p6-console"' in guardian
    assert 'ScriptName "p6_console.py"' in guardian
    assert 'Name "raw-gateway"' in guardian
    assert 'ScriptName "raw_consumption_gateway.py"' in guardian
    assert 'Name "dialog-entry"' in guardian
    assert 'ScriptName "dialog_entry_proxy.py"' in guardian
    assert "Test-PortListening" in guardian
    assert "19300" in guardian
    assert "19400" in guardian
    assert "19500" in guardian
    assert "19510" in guardian
    assert "19600" in guardian
    assert "--scan --source codex" in guardian
    assert "guardian-status.json" in guardian
    assert "NotifyIcon" in tray
    assert "time-library-emblem.ico" in tray
    assert "time-library-emblem.png" in tray
    assert "time_library_emblem.ico" in tray
    assert "time_library_emblem.png" in tray
    assert "time_library-logo.jpg" not in tray
    assert "time_library_logo.png" not in tray
    assert "CurrentUICulture" in tray
    assert "function U" in tray
    assert 'open_console = (U "6253 5F00 63A7 5236 53F0")' in tray
    assert 'run_guardian_now = (U "7ACB 5373 5B88 62A4 8865 626B")' in tray
    assert 'record_guard_label = (U "8BB0 5F55 5B88 62A4 FF1A")' in tray
    assert 'record_catching_up_label = (U "6B63 5728 8FFD 5C3E FF1A")' in tray
    assert 'record_backfill_needed_label = (U "5EFA 8BAE 56DE 586B FF1A")' in tray
    assert 'pause_guardian = (U "6682 505C 5B88 62A4 4EFB 52A1")' in tray
    assert 'exit_tray = (U "9000 51FA 6258 76D8 56FE 6807")' in tray
    assert 'open_console = "Open Console"' in tray
    assert 'run_guardian_now = "Run Guardian Now"' in tray
    assert 'record_guard_label = "Record Guard: "' in tray
    assert "/api/v1/records/guardian/status?limit=80&mode=fast&compact=1" in tray
    assert "/api/v1/records/guardian/backfill" in tray
    assert "Invoke-RecordGuardianBackfill" in tray
    assert "New-FallbackTimeLibraryIcon" in tray
    assert "New-TimeLibraryTrayIcon" in tray
    assert 'DrawString("M"' not in tray
    assert "SystemIcons]::Shield" not in tray
    assert "SystemIcons]::Warning" not in tray
    assert "SystemIcons" not in tray
    assert "ConvertFrom-JsonOutput" in guardian
    assert "no balanced JSON object found" in guardian
    assert "Invoke-RecordGuardianBackfillIfNeeded" in guardian
    assert "/api/v1/records/guardian/status?limit=80&mode=fast&compact=1" in guardian
    assert "/api/v1/records/guardian/backfill" in guardian
    assert "console_token" in guardian
    assert "X-Memcore-Console-Token" in guardian
    assert "Write-Utf8NoBom" in guardian
    assert "[System.IO.File]::WriteAllText" in guardian
    forbidden = [
        "Invoke-Command " + "-VMName",
        "Get-" + "VM",
        "Hyper" + "-V",
        ".".join(["172", "22"]),
        ".".join(["172", "18"]),
        ".".join(["192", "168"]),
        "C:" + "\\Users\\" + "Example",
    ]
    for fragment in forbidden:
        assert fragment not in smoke
    assert "windows_native_smoke.ps1" in installer
    assert "Run-NativeSmoke" in installer
    assert "if ($Ok) { exit 0 }" in smoke
    assert "exit 1" in smoke
    assert 'if ($SkipCodex) { $nativeArgs += " -SkipCodex" }' in installer
    assert "Start-Process -FilePath $powershellExe -ArgumentList $nativeArgs" in installer
    assert "-Wait -PassThru -NoNewWindow" in installer
    assert "-RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath" in installer
    assert "$lastExitCode = [int]$process.ExitCode" in installer
    assert "@(& $powershellExe @nativeArgs" not in installer
    assert "$maxAttempts = 4" in installer
    assert 'Warn "Native Windows smoke attempt $attempt failed; waiting for services to settle"' in installer
    assert "Start-Sleep -Seconds 3" in installer
    assert 'Die "Native Windows smoke failed after $maxAttempts attempts' in installer
    assert "windows_native_smoke.ps1" in wiki
    assert "does not run real recall" in wiki


def test_windows_powershell_scripts_do_not_assign_reserved_pid_variable():
    for path in sorted(ROOT.rglob("*.ps1")):
        if any(part in {".git", ".venv", "__pycache__"} for part in path.parts):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        assert not re.search(r"(?im)^\s*\$pid\s*=", text), path
        assert not re.search(r"(?im)foreach\s*\(\s*\$pid\b", text), path


def test_windows_claude_mcp_status_scans_all_known_config_locations_and_redacts_secrets():
    status = (ROOT / "tools" / "windows_claude_mcp_status.ps1").read_text(encoding="utf-8")

    assert 'tool = "windows_claude_mcp_status"' in status
    assert "CLAUDE_DESKTOP_HOME" in status
    assert "claude_desktop_config.json" in status
    assert "mcpServers" in status
    assert "time-library" in status
    assert "claude_desktop_mcp_bridge.py" in status
    assert "front_door_port" in status
    assert "Claude_pzs8sxrjxfjjc" in status
    assert "Claude-*" in status
    assert "Claude_*" in status
    assert "AppData\\Roaming\\Claude" in status
    assert "AppData\\Local\\Claude" in status
    assert "MEMCORE_ROOT" in status
    assert "MEMCORE_WINDOW_BINDING_REGISTRY" in status
    assert "MEMCORE_CLAUDE_DESKTOP_CANONICAL_WINDOW_ID" in status
    assert "MEMCORE_CLAUDE_DESKTOP_SESSION_ID" in status
    assert "--window-binding-registry" in status
    assert "--binding-key" in status
    assert "claude_desktop" in status
    assert "[redacted]" in status
    assert "secret_fields_redacted" in status
    assert "found_config_count" in status
    assert "mcp_present_count" in status
    assert "healthy_config_count" in status
    assert "ConvertTo-Json" in status
    assert "foreach ($candidateHome in $homes)" in status
    assert "foreach ($home in $homes)" not in status
    assert "param([string]$ClaudeHome)" in status
    assert "Inspect-ClaudeHome -ClaudeHome $candidateHome" in status
    assert "param([string]$Home)" not in status
    assert "Inspect-ClaudeHome -Home" not in status
    assert "[object[]]$Values" in status
    assert "$serverArgs" in status
    assert "Test-ArgContains -Values $serverArgs" in status
    assert "Get-ArgAfter -Values $serverArgs" in status
    assert "[object[]]$Args" not in status
    assert "$args =" not in status


def test_macos_installer_adds_menu_bar_status_icon():
    mac = (ROOT / "tools" / "macos_full_install.sh").read_text(encoding="utf-8")
    menu_bar = (ROOT / "tools" / "macos_menu_bar.swift").read_text(encoding="utf-8")
    uninstaller = (ROOT / "uninstall.sh").read_text(encoding="utf-8")

    assert "macos_menu_bar.swift" in mac
    assert "build_menu_bar_helper" in mac
    assert "swiftc" in mac
    assert "runtime/memcore-menu-bar" in mac
    assert "com.memcorecloud.menu-bar" in mac
    assert '"ProcessType": "Interactive"' in mac
    assert "write_menu_bar_launch_agent" in mac
    assert 'MENU_BAR_STATUS="installed"' in mac
    assert 'MENU_BAR_STATUS="not_installed"' in mac
    assert "Menu bar: ${MENU_BAR_STATUS}" in mac
    assert "menu-bar-build.err.log" in mac

    assert "NSStatusBar.system.statusItem" in menu_bar
    assert "NSApp.setActivationPolicy(.accessory)" in menu_bar
    assert "front_door_port" in menu_bar
    assert "time-library-emblem.icns" in menu_bar
    assert "time-library-emblem.png" in menu_bar
    assert "time_library_emblem.icns" in menu_bar
    assert "time_library_emblem.png" in menu_bar
    assert 'button.toolTip = "Time Library"' in menu_bar
    assert 'button.title = "M"' not in menu_bar
    assert "Run Catch-up Now" in menu_bar
    assert "打开控制台" in menu_bar
    assert "/api/v1/records/guardian/status?limit=80&mode=fast&compact=1" in menu_bar
    assert "/api/v1/records/guardian/backfill" in menu_bar
    assert "consoleToken()" in menu_bar
    assert "X-Memcore-Console-Token" in menu_bar
    assert '"recordGuard": "记录守护"' in menu_bar
    assert '"recordGuard": "Record Guard"' in menu_bar
    assert "backfill_recommend_after_milliseconds" not in menu_bar

    assert "Application Support/time-library" in uninstaller
    assert "Application Support/memcore-cloud" in uninstaller
    assert "com.memcorecloud.menu-bar" in uninstaller
    assert "Remove Time Library LaunchAgents" in uninstaller
    assert "runtime" in uninstaller


def test_codex_mcp_bridge_is_installed_for_current_window_routing():
    bridge = (ROOT / "tools" / "codex_mcp_bridge.py").read_text(encoding="utf-8")
    mac = (ROOT / "tools" / "macos_full_install.sh").read_text(encoding="utf-8")
    linux = (ROOT / "tools" / "linux_full_install.sh").read_text(encoding="utf-8")
    windows = (ROOT / "tools" / "windows_full_install.ps1").read_text(encoding="utf-8")

    assert "stdio bridge for Codex" in bridge
    assert "CODEX_THREAD_ID" in bridge
    assert "MEMCORE_CODEX_SESSION_ID" in bridge
    assert "MEMCORE_CODEX_CANONICAL_WINDOW_ID" in bridge
    assert '"--root"' in bridge
    assert "consumer\", \"codex\"" in bridge
    assert 'mode in {"preflight", "work_preflight", "agent_work_preflight"}' in bridge
    assert "codex_compact" in bridge
    for text in (mac, linux, windows):
        assert "codex_mcp_bridge.py" in text
        assert "codex_mcp_config_guard.py" in text
        assert "protected relay-preserving guard" in text
        assert "codex mcp add time-library" not in text
        assert "codex mcp remove time-library" not in text
        assert "front_door_port" in text or "front-door discovery" in text
        assert "--window-binding-registry" in text
        assert "--binding-key" in text
        assert "--root" in text
        assert "codex" in text
        assert "MEMCORE_WINDOW_BINDING_REGISTRY" in text
        assert "chrome-native-hosts-v2.json" in text
        assert "chrome-native-hosts.json" in text
        assert "--url http://127.0.0.1:9851/mcp" not in text
        assert '--url "http://127.0.0.1:9851/mcp"' not in text


def test_codex_mcp_guard_is_generic_and_failure_preserving_across_installers():
    mac = (ROOT / "tools" / "macos_full_install.sh").read_text(encoding="utf-8")
    linux = (ROOT / "tools" / "linux_full_install.sh").read_text(encoding="utf-8")
    windows = (ROOT / "tools" / "windows_full_install.ps1").read_text(encoding="utf-8")

    for text in (mac, linux, windows):
        assert "codex_mcp_config_guard.py" in text
        assert "--watch" in text
        assert "--create-if-missing" in text
        assert "existing host configuration and guard were left unchanged" in text
        assert "codex mcp add time-library" not in text
        assert "codex mcp remove time-library" not in text
        assert "relay-preserving guard" in text

    for text, marker in (
        (mac, "install_codex_mcp_guard_launchagent()"),
        (linux, "install_codex_mcp_guard_service()"),
    ):
        section = text.split(marker, 1)[1].split("\n}", 1)[0]
        assert "CODEX_MCP_GUARD_STATUS" in section
        assert '!= "installed"' in section
        assert "guard unchanged" in section
        assert "remove_codex_mcp_guard" not in section
        assert "--watch" in section
        assert "--create-if-missing" not in section

    windows_autostart = windows.split("function Register-WindowsAutostart", 1)[1].split(
        "function Run-Smoke", 1
    )[0]
    assert "Restore-PreviousCodexMcpGuardTask" in windows_autostart
    assert 'if ($CodexMcpGuardStatus -eq "installed")' in windows_autostart
    assert "Register-ScheduledTask -TaskName $snapshot.TaskName -Xml $snapshot.Xml" in windows
    assert '$guardArgs = "`"$guardScript`" --watch' in windows_autostart
    guard_args_line = next(
        line for line in windows_autostart.splitlines() if "$guardArgs =" in line
    )
    assert "--create-if-missing" not in guard_args_line
    main = windows.split('Info "Source: $SourceRoot"', 1)[1]
    assert main.index("try { Install-CodexMcp }") < main.index("\n        Register-WindowsAutostart")


def test_codex_catalog_points_to_guarded_merge_not_whole_file_cli_rewrite():
    catalog = json.loads((ROOT / "config/platform_catalog.json").read_text(encoding="utf-8"))
    storage = json.loads(
        (ROOT / "config/platform_storage_patterns.verified.json").read_text(encoding="utf-8")
    )
    codex_catalog = next(item for item in catalog["entries"] if item["id"] == "codex")

    assert "codex mcp add" not in codex_catalog["mcp"]["preferred_apply"]
    assert "guard" in codex_catalog["mcp"]["preferred_apply"].lower()
    preferred = storage["entries"]["codex"]["auto_connect"]["preferred_apply"]
    assert "codex mcp add" not in preferred
    assert "guard" in preferred.lower()


def test_claude_code_mcp_is_migrated_from_fixed_http_to_stdio_discovery():
    mac = (ROOT / "tools" / "macos_full_install.sh").read_text(encoding="utf-8")
    linux = (ROOT / "tools" / "linux_full_install.sh").read_text(encoding="utf-8")
    windows = (ROOT / "tools" / "windows_full_install.ps1").read_text(encoding="utf-8")

    for text in (mac, linux, windows):
        assert "claude_desktop_mcp_bridge.py" in text
        assert "claude_code_cli" in text
        assert "bak-time_library-port-discovery-" in text
        assert "Claude Code MCP migrated to per-request front-door discovery" in text
        assert "MEMCORE_WINDOW_BINDING_REGISTRY" in text
    assert "mcp remove time-library -s user" in mac
    assert "mcp add -s user time-library" in mac
    assert "mcp remove time-library -s user" in linux
    assert "mcp add -s user time-library" in linux
    assert "mcp remove time-library -s user" in windows
    assert '"mcp", "add", "-s", "user", "time-library"' in windows


def test_openclaw_discovery_uses_esm_compatible_filesystem_import():
    plugin = (ROOT / "system" / "openclaw" / "plugins" / "time-library-native" / "index.js").read_text(encoding="utf-8")

    assert 'import { readFileSync } from "node:fs";' in plugin
    assert 'require("fs")' not in plugin
    assert "front_door_port" in plugin
    assert "/.local/share/time-library/runtime/front_door_port" in plugin
    assert "verifyFrontDoor" in plugin
    assert 'body?.service === "time-library-front-door"' in plugin


def test_installers_only_stop_known_time_library_processes():
    linux = (ROOT / "tools" / "linux_full_install.sh").read_text(encoding="utf-8")
    identity = (ROOT / "tools" / "install_runtime_identity.py").read_text(encoding="utf-8")
    windows = (ROOT / "tools" / "windows_full_install.ps1").read_text(encoding="utf-8")

    assert "argv_targets_install_roots" in linux
    assert '"single_port_runtime.py"' in identity
    assert "function Stop-Port" not in windows
    assert "netstat -ano" not in windows
    assert 'Get-ChildItem $pidDir -Filter "*.pid"' not in windows
    assert "$knownEntrypoints" in windows
    assert 'Join-Path $Root "src\\single_port_runtime.py"' in windows


def test_installers_refresh_only_stale_claude_desktop_bridge_children():
    helper = (ROOT / "tools" / "refresh_claude_desktop_mcp_bridges.py").read_text(encoding="utf-8")
    installers = [
        (ROOT / "tools" / "macos_full_install.sh").read_text(encoding="utf-8"),
        (ROOT / "tools" / "linux_full_install.sh").read_text(encoding="utf-8"),
        (ROOT / "tools" / "windows_full_install.ps1").read_text(encoding="utf-8"),
    ]

    assert "claude_desktop_mcp_bridge.py" in helper
    assert '"host_process_stopped": False' in helper
    assert "Claude.app" not in helper
    for installer in installers:
        assert "refresh_claude_desktop_mcp_bridges.py" in installer


def test_unix_installers_require_semantic_health_not_only_http_200():
    for name in ("macos_full_install.sh", "linux_full_install.sh"):
        installer = (ROOT / "tools" / name).read_text(encoding="utf-8")
        assert "health_acceptance_smoke" in installer
        assert '("p0raw", "p0watcher", "p2zhiyi", "p2sourceRef", "p3recall", "p4provider")' in installer
        run_smoke = installer.split("run_smoke() {", 1)[1].split("\n}", 1)[0]
        assert "health_acceptance_smoke" in run_smoke


def test_hermes_fallback_resolves_platform_native_install_roots():
    hermes = (ROOT / "system" / "hermes" / "plugins" / "time_library" / "__init__.py").read_text(encoding="utf-8")

    assert 'sys.platform == "win32"' in hermes
    assert 'sys.platform == "darwin"' in hermes
    assert 'Path.home() / ".local" / "share" / "time-library"' in hermes


def test_codex_mcp_bridge_adds_thread_id_as_session_without_guessing():
    sys.modules.pop("codex_mcp_bridge_under_test", None)
    spec = importlib.util.spec_from_file_location(
        "codex_mcp_bridge_under_test",
        ROOT / "tools" / "codex_mcp_bridge.py",
    )
    bridge = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(bridge)

    request = {
        "jsonrpc": "2.0",
        "id": 27,
        "method": "tools/call",
        "params": {"name": "zhiyi_recall", "arguments": {"query": "Codex 当前窗口"}},
    }
    gateway_response = {
        "jsonrpc": "2.0",
        "id": 27,
        "result": {
            "content": [{"type": "text", "text": "{}"}],
            "structuredContent": {
                "ok": True,
                "consumer": "codex",
                "memory_scope": "active",
                "tiandao_context_package_valid": True,
                "tiandao_context_package": {
                    "schema": "tiandao_context_package.v1",
                    "query_hash": "codex-query-hash",
                    "source_system": "codex",
                    "canonical_window_id": "codex-thread-27",
                    "session_id": "codex-thread-27",
                    "intent_mode": "evidence",
                    "memory_context_mode": "mode_a",
                    "scope_enforced": True,
                    "memory_write": False,
                    "contract_role": "memory_context_candidate",
                    "consumer": "codex",
                    "memory_scope": "active",
                    "memory_base_scope": "active_layered",
                    "active_layers_used": ["current_session"],
                    "permission_boundary": {"memory_write_enabled": False, "read_only": True},
                    "validation": {"valid": True, "violations": []},
                    "matched_memories": [{"raw_excerpt_returned": True}],
                    "raw_projection": {"raw_items_count": 1},
                },
                "matched_count": 0,
                "items": [],
            },
            "isError": False,
        },
    }

    with patch.dict(os.environ, {"CODEX_THREAD_ID": "codex-thread-27"}, clear=False):
        with patch.object(bridge.urllib.request, "urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.status = 200
            urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(
                gateway_response,
                ensure_ascii=False,
            ).encode("utf-8")
            result = bridge._forward("http://127.0.0.1:9851/mcp", request, 30, True)

    forwarded_body = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))
    forwarded_args = forwarded_body["params"]["arguments"]
    assert forwarded_args["consumer"] == "codex"
    assert forwarded_args["memory_scope"] == "active"
    assert forwarded_args["session_id"] == "codex-thread-27"
    assert "canonical_window_id" not in forwarded_args
    assert forwarded_args["limit"] == 3
    assert forwarded_args["excerpt_chars"] == 240
    assert forwarded_args["response_budget"] == "compact"
    structured = result["result"]["structuredContent"]
    assert structured["response_budget"]["mode"] == "codex_compact"
    assert structured["tiandao_context_package_valid"] is True
    assert structured["tiandao_context_package"]["schema"] == "tiandao_context_package.v1"
    assert structured["tiandao_context_package"]["memory_context_mode"] == "mode_a"
    assert structured["tiandao_context_package"]["validation"]["valid"] is True
    assert "matched_memories" not in structured["tiandao_context_package"]
    assert "raw_projection" not in structured["tiandao_context_package"]


def test_codex_mcp_bridge_adds_registry_current_window_binding(tmp_path):
    sys.modules.pop("codex_mcp_bridge_under_test", None)
    spec = importlib.util.spec_from_file_location(
        "codex_mcp_bridge_under_test",
        ROOT / "tools" / "codex_mcp_bridge.py",
    )
    bridge = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(bridge)

    registry_path = tmp_path / "window_binding_registry.json"
    registry_path.write_text(
        json.dumps(
            {
                "current_windows": {
                    "codex": {
                        "canonical_window_id": "codex-project-1",
                        "session_id": "codex-session-1",
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    request = {
        "jsonrpc": "2.0",
        "id": 28,
        "method": "tools/call",
        "params": {"name": "zhiyi_recall", "arguments": {"query": "Codex registry"}},
    }
    gateway_response = {
        "jsonrpc": "2.0",
        "id": 28,
        "result": {
            "content": [{"type": "text", "text": "{}"}],
            "structuredContent": {"ok": True, "matched_count": 0, "items": []},
            "isError": False,
        },
    }

    with patch.dict(os.environ, {}, clear=True):
        with patch.object(bridge.urllib.request, "urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.status = 200
            urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(
                gateway_response,
                ensure_ascii=False,
            ).encode("utf-8")
            bridge._forward(
                "http://127.0.0.1:9851/mcp",
                request,
                30,
                True,
                registry_path=str(registry_path),
            )

    forwarded_body = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))
    forwarded_args = forwarded_body["params"]["arguments"]
    assert forwarded_args["consumer"] == "codex"
    assert forwarded_args["memory_scope"] == "active"
    assert forwarded_args["canonical_window_id"] == "codex-project-1"
    assert forwarded_args["session_id"] == "codex-session-1"


def test_codex_mcp_bridge_defaults_preflight_to_window_scope_when_bound(tmp_path):
    sys.modules.pop("codex_mcp_bridge_under_test", None)
    spec = importlib.util.spec_from_file_location(
        "codex_mcp_bridge_under_test",
        ROOT / "tools" / "codex_mcp_bridge.py",
    )
    bridge = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(bridge)

    registry_path = tmp_path / "window_binding_registry.json"
    registry_path.write_text(
        json.dumps(
            {
                "current_windows": {
                    "codex": {
                        "canonical_window_id": "codex-window-fast",
                        "session_id": "codex-session-fast",
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    request = {
        "jsonrpc": "2.0",
        "id": 29,
        "method": "tools/call",
        "params": {
            "name": "zhiyi_recall",
            "arguments": {"query": "继续发布前检查", "mode": "preflight"},
        },
    }
    gateway_response = {
        "jsonrpc": "2.0",
        "id": 29,
        "result": {
            "content": [{"type": "text", "text": "{}"}],
            "structuredContent": {"ok": True, "mode": "preflight", "decision": "silent"},
            "isError": False,
        },
    }

    with patch.dict(os.environ, {}, clear=True):
        with patch.object(bridge.urllib.request, "urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.status = 200
            urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(
                gateway_response,
                ensure_ascii=False,
            ).encode("utf-8")
            bridge._forward(
                "http://127.0.0.1:9851/mcp",
                request,
                30,
                True,
                registry_path=str(registry_path),
            )

    forwarded_body = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))
    forwarded_args = forwarded_body["params"]["arguments"]
    assert forwarded_args["mode"] == "preflight"
    assert forwarded_args["consumer"] == "codex"
    assert forwarded_args["memory_scope"] == "window"
    assert forwarded_args["canonical_window_id"] == "codex-window-fast"
    assert forwarded_args["session_id"] == "codex-session-fast"

    work_request = {
        "jsonrpc": "2.0",
        "id": 30,
        "method": "tools/call",
        "params": {
            "name": "zhiyi_recall",
            "arguments": {"query": "开始施工前先查已有机制", "mode": "work_preflight"},
        },
    }
    work_gateway_response = {
        "jsonrpc": "2.0",
        "id": 30,
        "result": {
            "content": [{"type": "text", "text": "{}"}],
            "structuredContent": {"ok": True, "mode": "work_preflight", "classification": "actually_missing"},
            "isError": False,
        },
    }
    with patch.dict(os.environ, {}, clear=True):
        with patch.object(bridge.urllib.request, "urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.status = 200
            urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(
                work_gateway_response,
                ensure_ascii=False,
            ).encode("utf-8")
            bridge._forward(
                "http://127.0.0.1:9851/mcp",
                work_request,
                30,
                True,
                registry_path=str(registry_path),
            )

    forwarded_body = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))
    forwarded_args = forwarded_body["params"]["arguments"]
    assert forwarded_args["mode"] == "work_preflight"
    assert forwarded_args["consumer"] == "codex"
    assert forwarded_args["memory_scope"] == "window"
    assert forwarded_args["canonical_window_id"] == "codex-window-fast"
    assert forwarded_args["session_id"] == "codex-session-fast"


def test_codex_mcp_bridge_compacts_preflight_payload():
    sys.modules.pop("codex_mcp_bridge_under_test", None)
    spec = importlib.util.spec_from_file_location(
        "codex_mcp_bridge_under_test",
        ROOT / "tools" / "codex_mcp_bridge.py",
    )
    bridge = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(bridge)

    request = {
        "jsonrpc": "2.0",
        "id": 71,
        "method": "tools/call",
        "params": {
            "name": "zhiyi_recall",
            "arguments": {"query": "继续平台配置", "mode": "preflight"},
        },
    }
    payload = {
        "ok": True,
        "mode": "preflight",
        "version": "2026.6.20",
        "contract": "zhixing_preflight.v2026.6.20",
        "auto_entry_contract": "zhixing_auto_entry.v2026.6.20",
        "auto_entry_state": "enter",
        "auto_entry_allowed": True,
        "auto_retreat_allowed": False,
        "auto_entry_reason": "proactive_resurfacing_required",
        "auto_entry_triggered_by": ["prompt:continuation", "shelf:xingce"],
        "auto_retreat_reason": "",
        "context_delivery_mode": "compact_source_anchors",
        "next_action": "apply_must_surface_before_answer",
        "agent_instruction": "Use must_surface, do_not_repeat, and acceptance_checks before answering; do not expose raw excerpts.",
        "consumer": "codex",
        "query": "继续平台配置",
        "read_only": True,
        "write_performed": False,
        "raw_write_performed": False,
        "zhiyi_write_performed": False,
        "xingce_write_performed": False,
        "platform_write_performed": False,
        "model_call_performed": False,
        "recall_performed": True,
        "raw_excerpt_returned": False,
        "decision": "surface",
        "prompt_class": "continuation",
        "confidence": 0.85,
        "min_surface_score": 45,
        "top_score": 85,
        "preflight_score_policy": "library_index_projection_is_soft_navigation_signal_only",
        "library_index_projection_soft_weight_policy": "soft_rank_signal_only_raw_evidence_required",
        "library_index_projection_soft_weight": 6,
        "preflight_score_profile": [
            {
                "library_id": "ZX-XINGCE-2",
                "library_shelf": "xingce",
                "score": 79,
                "base_score": 73,
                "surface_eligibility_score": 73,
                "surface_eligible": True,
                "library_index_projection_soft_weight_applied": True,
                "library_index_projection_soft_weight": 6,
                "library_index_projection_soft_weight_policy": "soft_rank_signal_only_raw_evidence_required",
                "components": [
                    {"name": "shelf", "value": 55, "reason": "xingce action strategy"},
                    {"name": "library_index_projection", "value": 6, "reason": "navigation hint"},
                ],
            }
        ],
        "silence_reason": "",
        "should_recall": True,
        "should_surface": True,
        "proactive_resurfacing_required": True,
        "xingce_focus": ["action_strategy"],
        "must_surface": [
            {
                "library_id": "ZX-XINGCE-2",
                "library_shelf": "xingce",
                "library_index_projection_soft_weight_applied": True,
                "library_index_projection_soft_weight": 6,
                "library_index_projection_soft_weight_policy": "soft_rank_signal_only_raw_evidence_required",
            }
        ],
        "do_not_repeat": ["不要重复旧坑"],
        "acceptance_checks": ["跑 smoke"],
        "matched_count": 1,
        "source_refs_count": 1,
        "raw_items_count": 1,
        "raw_recall_trajectory_contract": "raw_recall_trajectory.v2026.6.17",
        "raw_recall_trajectory_policy": "retrieval_steps_are_diagnostics_not_evidence",
        "raw_recall_trajectory": [
            {
                "step": "catalog_index_projection",
                "layer": "L1_library_index_projection",
                "status": "hit",
                "used": True,
                "authority": "navigation_hint_only_raw_evidence_required",
            }
        ],
        "library_index_projection_contract": "library_index_projection_receipt.v2026.6.17",
        "library_index_projection_policy": "navigation_hint_only_raw_evidence_required",
        "library_index_projection_used": True,
        "library_index_projection_refs_count": 1,
        "library_index_projection_refs": [
            {
                "projection_kind": "library_index_projection",
                "authority": "navigation_hint_only_raw_evidence_required",
                "source_path": "raw/probe_logs/platform-index.jsonl",
            }
        ],
        "fast_window_preflight": True,
        "fast_recall_path": "canonical_window_index",
        "fast_window_index_status": "hit_recent_context",
        "zhiyi_layer_skipped_for_fast_preflight": True,
        "consumer_receipt": {
            "consumer": "codex",
            "read_only": True,
            "write_performed": False,
            "receipt_scope": "zhixing_preflight_read_only",
            "library_index_projection_used": True,
            "library_index_projection_refs_count": 1,
            "library_index_projection_policy": "navigation_hint_only_raw_evidence_required",
            "library_index_projection_soft_weight_policy": "soft_rank_signal_only_raw_evidence_required",
            "library_index_projection_soft_weight": 6,
            "preflight_score_policy": "library_index_projection_is_soft_navigation_signal_only",
            "raw_recall_trajectory_contract": "raw_recall_trajectory.v2026.6.17",
            "raw_recall_trajectory_policy": "retrieval_steps_are_diagnostics_not_evidence",
        },
    }
    gateway_response = {
        "jsonrpc": "2.0",
        "id": 71,
        "result": {
            "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
            "structuredContent": payload,
            "isError": False,
        },
    }

    with patch.object(bridge.urllib.request, "urlopen") as urlopen:
        urlopen.return_value.__enter__.return_value.status = 200
        urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(
            gateway_response,
            ensure_ascii=False,
        ).encode("utf-8")
        result = bridge._forward("http://127.0.0.1:9851/mcp", request, 30, True)

    structured = result["result"]["structuredContent"]
    assert structured["response_budget"]["mode"] == "codex_preflight_compact"
    assert structured["decision"] == "surface"
    assert structured["auto_entry_contract"] == "zhixing_auto_entry.v2026.6.20"
    assert structured["auto_entry_state"] == "enter"
    assert structured["auto_entry_allowed"] is True
    assert structured["auto_retreat_allowed"] is False
    assert structured["auto_entry_reason"] == "proactive_resurfacing_required"
    assert structured["auto_entry_triggered_by"] == ["prompt:continuation", "shelf:xingce"]
    assert structured["context_delivery_mode"] == "compact_source_anchors"
    assert structured["next_action"] == "apply_must_surface_before_answer"
    assert structured["prompt_class"] == "continuation"
    assert structured["confidence"] == 0.85
    assert structured["should_surface"] is True
    assert structured["must_surface"][0]["library_id"] == "ZX-XINGCE-2"
    assert structured["must_surface"][0]["library_index_projection_soft_weight_applied"] is True
    assert structured["must_surface"][0]["library_index_projection_soft_weight"] == 6
    assert structured["preflight_score_policy"] == "library_index_projection_is_soft_navigation_signal_only"
    assert structured["library_index_projection_soft_weight_policy"] == "soft_rank_signal_only_raw_evidence_required"
    assert structured["library_index_projection_soft_weight"] == 6
    assert structured["preflight_score_profile"][0]["library_id"] == "ZX-XINGCE-2"
    assert structured["preflight_score_profile"][0]["base_score"] == 73
    assert structured["library_index_projection_used"] is True
    assert structured["library_index_projection_policy"] == "navigation_hint_only_raw_evidence_required"
    assert structured["library_index_projection_refs_count"] == 1
    assert structured["library_index_projection_refs"][0]["authority"] == "navigation_hint_only_raw_evidence_required"
    assert structured["raw_recall_trajectory"][0]["step"] == "catalog_index_projection"
    assert structured["consumer_receipt"]["preflight_score_policy"] == "library_index_projection_is_soft_navigation_signal_only"
    assert structured["consumer_receipt"]["library_index_projection_soft_weight"] == 6
    assert structured["fast_window_preflight"] is True
    assert structured["fast_recall_path"] == "canonical_window_index"
    assert structured["fast_window_index_status"] == "hit_recent_context"
    assert structured["zhiyi_layer_skipped_for_fast_preflight"] is True


def test_codex_mcp_bridge_compacts_work_preflight_payload():
    sys.modules.pop("codex_mcp_bridge_under_test", None)
    spec = importlib.util.spec_from_file_location(
        "codex_mcp_bridge_under_test",
        ROOT / "tools" / "codex_mcp_bridge.py",
    )
    bridge = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(bridge)

    request = {
        "jsonrpc": "2.0",
        "id": 72,
        "method": "tools/call",
        "params": {
            "name": "zhiyi_recall",
            "arguments": {"query": "开始施工前先查已有机制", "mode": "work_preflight"},
        },
    }
    payload = {
        "ok": True,
        "mode": "work_preflight",
        "version": "2026.6.20",
        "contract": "agent_work_preflight.v2026.6.20",
        "source_preflight_contract": "zhixing_preflight.v2026.6.20",
        "consumer": "codex",
        "query": "开始施工前先查已有机制",
        "read_only": True,
        "write_performed": False,
        "raw_write_performed": False,
        "zhiyi_write_performed": False,
        "xingce_write_performed": False,
        "platform_write_performed": False,
        "model_call_performed": False,
        "classification": "already_built_but_forgotten",
        "classification_options": ["actually_missing", "already_built_but_forgotten", "built_but_miswired", "diagnostic_gap"],
        "should_intervene": True,
        "intervention_level": "must_surface",
        "decision": "surface",
        "prompt_class": "continuation",
        "recall_status": "preflight_surface_required",
        "memory_scope": "active",
        "active_layers_used": ["same_project_workspace"],
        "preflight_score_policy": "library_index_projection_is_soft_navigation_signal_only",
        "library_index_projection_soft_weight_policy": "soft_rank_signal_only_raw_evidence_required",
        "library_index_projection_soft_weight": 6,
        "preflight_score_profile": [
            {
                "library_id": "ZX-XINGCE-WORK",
                "library_shelf": "xingce",
                "score": 79,
                "base_score": 73,
                "surface_eligible": True,
                "library_index_projection_soft_weight_applied": True,
                "library_index_projection_soft_weight": 6,
            }
        ],
        "library_index_projection_contract": "library_index_projection_receipt.v2026.6.17",
        "library_index_projection_policy": "navigation_hint_only_raw_evidence_required",
        "library_index_projection_used": True,
        "library_index_projection_refs_count": 1,
        "library_index_projection_refs": [
            {
                "projection_kind": "library_index_projection",
                "authority": "navigation_hint_only_raw_evidence_required",
                "source_path": "raw/probe_logs/work.jsonl",
            }
        ],
        "evidence": [
            {
                "library_id": "ZX-XINGCE-WORK",
                "library_shelf": "xingce",
                "title": "已有开工自检",
                "summary": "已有机制，不要新造。",
                "source_system": "codex",
                "source_path": "raw/probe_logs/work.jsonl",
                "raw_evidence_status": "raw_offset",
                "library_index_projection_soft_weight_applied": True,
                "library_index_projection_soft_weight": 6,
                "library_index_projection_soft_weight_policy": "soft_rank_signal_only_raw_evidence_required",
                "raw_excerpt": "this must be omitted",
                "library_card": {"large": "x" * 1000},
                "typed_graph": {"large": "y" * 1000},
            }
        ],
        "do_not_repeat": ["不要新造旁路知识层"],
        "acceptance_checks": ["先查现有入口"],
        "changed_behavior": ["Check the existing mechanism before creating a new one."],
        "agent_instruction": "Start from the existing feature.",
        "next_action": "inspect_existing_mechanism_before_editing",
        "source_refs_required": True,
        "raw_excerpt_returned": False,
        "preflight_receipt": {"large": "p" * 1000},
        "consumer_receipt": {
            "consumer": "codex",
            "read_only": True,
            "write_performed": False,
            "memory_write": False,
            "platform_write": False,
            "receipt_scope": "agent_work_preflight_read_only",
            "used_library_ids": ["ZX-XINGCE-WORK"],
            "library_index_projection_used": True,
            "library_index_projection_refs_count": 1,
            "library_index_projection_policy": "navigation_hint_only_raw_evidence_required",
            "library_index_projection_soft_weight_policy": "soft_rank_signal_only_raw_evidence_required",
            "library_index_projection_soft_weight": 6,
            "preflight_score_policy": "library_index_projection_is_soft_navigation_signal_only",
        },
    }
    gateway_response = {
        "jsonrpc": "2.0",
        "id": 72,
        "result": {
            "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
            "structuredContent": payload,
            "isError": False,
        },
    }

    with patch.object(bridge.urllib.request, "urlopen") as urlopen:
        urlopen.return_value.__enter__.return_value.status = 200
        urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(
            gateway_response,
            ensure_ascii=False,
        ).encode("utf-8")
        result = bridge._forward("http://127.0.0.1:9851/mcp", request, 30, True)

    structured = result["result"]["structuredContent"]
    text_payload = json.loads(result["result"]["content"][0]["text"])
    assert structured == text_payload
    assert structured["mode"] == "work_preflight"
    assert structured["classification"] == "already_built_but_forgotten"
    assert structured["should_intervene"] is True
    assert structured["evidence"][0]["library_id"] == "ZX-XINGCE-WORK"
    assert structured["evidence"][0]["library_index_projection_soft_weight_applied"] is True
    assert structured["evidence"][0]["library_index_projection_soft_weight"] == 6
    assert "raw_excerpt" not in structured["evidence"][0]
    assert "library_card" not in structured["evidence"][0]
    assert "typed_graph" not in structured["evidence"][0]
    assert "preflight_receipt" not in structured
    assert structured["preflight_score_policy"] == "library_index_projection_is_soft_navigation_signal_only"
    assert structured["library_index_projection_soft_weight_policy"] == "soft_rank_signal_only_raw_evidence_required"
    assert structured["library_index_projection_soft_weight"] == 6
    assert structured["preflight_score_profile"][0]["library_id"] == "ZX-XINGCE-WORK"
    assert structured["library_index_projection_used"] is True
    assert structured["library_index_projection_refs"][0]["authority"] == "navigation_hint_only_raw_evidence_required"
    assert structured["response_budget"]["mode"] == "codex_work_preflight_compact"
    assert structured["consumer_receipt"]["receipt_scope"] == "agent_work_preflight_read_only"
    assert structured["consumer_receipt"]["memory_write"] is False
    assert structured["consumer_receipt"]["platform_write"] is False
    assert structured["consumer_receipt"]["preflight_score_policy"] == "library_index_projection_is_soft_navigation_signal_only"
    assert structured["consumer_receipt"]["library_index_projection_soft_weight"] == 6


def test_installers_allow_skipping_codex_mcp_without_user_learning_mcp():
    mac = (ROOT / "tools" / "macos_full_install.sh").read_text(encoding="utf-8")
    linux = (ROOT / "tools" / "linux_full_install.sh").read_text(encoding="utf-8")
    windows = (ROOT / "tools" / "windows_full_install.ps1").read_text(encoding="utf-8")
    wrapper = (ROOT / "install.ps1").read_text(encoding="utf-8")

    assert "--skip-codex" in mac
    assert "--skip-codex" in linux
    assert "[switch]$SkipCodex" in windows
    assert "[switch]$SkipCodex" in wrapper
    assert "$env:TIME_LIBRARY_INSTALL_DIR" in wrapper
    assert "$env:MEMCORE_INSTALL_DIR" in wrapper
    assert "$installerArgs = @{}" in wrapper
    assert '$installerArgs["InstallRoot"] = $Dir' in wrapper
    assert '$installerArgs["SkipCodex"] = $true' in wrapper
    assert "$args +=" not in wrapper


def test_claude_desktop_bridge_and_skip_option_are_installed():
    bridge = (ROOT / "tools" / "claude_desktop_mcp_bridge.py").read_text(encoding="utf-8")
    mac = (ROOT / "tools" / "macos_full_install.sh").read_text(encoding="utf-8")
    linux = (ROOT / "tools" / "linux_full_install.sh").read_text(encoding="utf-8")
    windows = (ROOT / "tools" / "windows_full_install.ps1").read_text(encoding="utf-8")
    wrapper = (ROOT / "install.ps1").read_text(encoding="utf-8")

    assert "stdio bridge for Claude Desktop" in bridge
    assert "front-door discovery file" in bridge
    assert "Content-Length:" in bridge
    assert 'encode("utf-8")' in bridge
    assert "sys.stdout.buffer" in bridge or 'getattr(sys.stdout, "buffer", None)' in bridge
    assert "DEFAULT_TIMEOUT_SECONDS = 30.0" in bridge
    assert "--full-recall-response" in bridge
    assert "--window-binding-registry" in bridge
    assert "MEMCORE_WINDOW_BINDING_REGISTRY" in bridge
    assert "current_windows" in bridge
    assert "--skip-claude-desktop" in mac
    assert "--skip-claude-desktop" in linux
    assert "[switch]$SkipClaudeDesktop" in windows
    assert "[switch]$SkipClaudeDesktop" in wrapper
    assert '$installerArgs["SkipClaudeDesktop"] = $true' in wrapper
    assert '& $installer @installerArgs' in wrapper
    assert 'Where-Object { $_.Name -like "Claude-*" }' in windows
    for text in (mac, linux, windows):
        assert '"--timeout", "30"' in text
        assert '"--window-binding-registry"' in text
        assert '"--binding-key", "claude_desktop"' in text
        assert '"PYTHONIOENCODING": "utf-8"' in text
        assert '"PYTHONUTF8": "1"' in text
        assert '"MEMCORE_ROOT": str(install_root)' in text
        assert '"MEMCORE_WINDOW_BINDING_REGISTRY": str(registry_path)' in text


def test_claude_desktop_bridge_writes_utf8_json_lines():
    sys.modules.pop("claude_desktop_mcp_bridge_under_test", None)
    spec = importlib.util.spec_from_file_location(
        "claude_desktop_mcp_bridge_under_test",
        ROOT / "tools" / "claude_desktop_mcp_bridge.py",
    )
    bridge = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(bridge)

    class FakeStdout:
        def __init__(self):
            self.buffer = io.BytesIO()

        def flush(self):
            pass

    fake_stdout = FakeStdout()
    with patch.object(bridge.sys, "stdout", fake_stdout):
        bridge._write_message({"jsonrpc": "2.0", "id": 1, "result": {"text": "中文召回正常"}})

    payload = fake_stdout.buffer.getvalue()
    assert payload.endswith(b"\n")
    assert not payload.startswith(b"Content-Length:")
    decoded = json.loads(payload.decode("utf-8"))
    assert decoded["result"]["text"] == "中文召回正常"
    assert b"\\u4e2d\\u6587" not in payload


def test_claude_desktop_bridge_compacts_recall_payload_for_stdio(tmp_path):
    sys.modules.pop("claude_desktop_mcp_bridge_under_test", None)
    spec = importlib.util.spec_from_file_location(
        "claude_desktop_mcp_bridge_under_test",
        ROOT / "tools" / "claude_desktop_mcp_bridge.py",
    )
    bridge = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(bridge)

    request = {
        "jsonrpc": "2.0",
        "id": 7,
        "method": "tools/call",
        "params": {"name": "zhiyi_recall", "arguments": {"query": "Time Library"}},
    }
    payload = {
        "ok": True,
        "consumer": "claude_desktop_windows",
        "query": "Time Library",
        "zhixing_library": {"large": "x" * 5000},
        "hybrid_recall": {"large": "y" * 5000},
        "matched_count": 1,
        "source_refs_count": 1,
        "raw_items_count": 1,
        "current_window_binding_applied": True,
        "current_window_binding_key": "claude_desktop",
        "current_window_binding_fields": ["canonical_window_id", "session_id", "project_id"],
        "tiandao_context_package_valid": True,
        "tiandao_context_package": {
            "schema": "tiandao_context_package.v1",
            "query_hash": "claude-query-hash",
            "source_system": "claude_desktop",
            "canonical_window_id": "claude-window-1",
            "session_id": "claude-session-1",
            "intent_mode": "evidence",
            "memory_context_mode": "mode_b",
            "scope_enforced": True,
            "memory_write": False,
            "contract_role": "memory_context_candidate",
            "consumer": "claude_desktop",
            "memory_scope": "active",
            "memory_base_scope": "active_layered",
            "active_layers_used": ["same_project_workspace"],
            "current_window_binding_applied": True,
            "current_window_binding_key": "claude_desktop",
            "current_window_binding_fields": ["canonical_window_id", "session_id", "project_id"],
            "source_refs": [
                {
                    "ref_id": "ref-1",
                    "source_system": "claude_desktop",
                    "artifact_type": "claude_desktop_session_jsonl",
                    "ref_path": "memory/claude_desktop/local/claude_desktop/s1.jsonl",
                    "evidence_hash": "hash-1",
                    "raw_evidence_status": "raw",
                }
            ],
            "permission_boundary": {"memory_write_enabled": False, "read_only": True},
            "capability_profile": {"adapter": "RawConsumptionGateway", "can_write_memory": False},
            "adapter_verdict": {"adapter_verdict": "READY_FOR_MEMORY_CONTEXT_CANDIDATE"},
            "validation": {"valid": True, "violations": []},
            "matched_memories": [{"raw_excerpt_returned": True}],
            "raw_projection": {"raw_items_count": 1},
        },
        "items": [
            {
                "library_id": "ZX-1",
                "library_shelf": "raw",
                "memory_type": "case_memory",
                "source_system": "claude_desktop",
                "source_path": "memory/claude_desktop/local/claude_desktop/s1.jsonl",
                "msg_ids": ["m1"],
                "summary": "s" * 2000,
                "raw_excerpt": "r" * 2000,
                "library_card": {"large": "z" * 5000},
                "typed_graph": {"large": "g" * 5000},
            }
        ],
        "consumer_receipt": {
            "consumer": "claude_desktop_windows",
            "request_id": "r1",
            "read_only": True,
            "write_performed": False,
            "used_source_refs": [{"source_path": "too-large-for-stdio"}],
        },
    }
    gateway_response = {
        "jsonrpc": "2.0",
        "id": 7,
        "result": {
            "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
            "structuredContent": payload,
            "isError": False,
        },
    }

    with patch.object(bridge.urllib.request, "urlopen") as urlopen:
        urlopen.return_value.__enter__.return_value.status = 200
        urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(
            gateway_response,
            ensure_ascii=False,
        ).encode("utf-8")
        result = bridge._forward(
            "http://127.0.0.1:9851/mcp",
            request,
            30,
            True,
            registry_path=str(tmp_path / "empty-window-binding-registry.json"),
        )

    forwarded_body = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))
    forwarded_args = forwarded_body["params"]["arguments"]
    assert forwarded_args["consumer"] == "claude_desktop"
    assert forwarded_args["memory_scope"] == "active"
    assert "canonical_window_id" not in forwarded_args
    assert "session_id" not in forwarded_args
    assert forwarded_args["limit"] == 3
    assert forwarded_args["excerpt_chars"] == 240
    assert forwarded_args["response_budget"] == "compact"
    structured = result["result"]["structuredContent"]
    text_payload = json.loads(result["result"]["content"][0]["text"])
    assert structured == text_payload
    assert "zhixing_library" not in structured
    assert "hybrid_recall" not in structured
    assert "library_card" not in structured["items"][0]
    assert "typed_graph" not in structured["items"][0]
    assert structured["current_window_binding_applied"] is True
    assert structured["current_window_binding_key"] == "claude_desktop"
    assert structured["current_window_binding_fields"] == ["canonical_window_id", "session_id", "project_id"]
    assert structured["tiandao_context_package_valid"] is True
    tiandao_pkg = structured["tiandao_context_package"]
    assert tiandao_pkg["schema"] == "tiandao_context_package.v1"
    assert tiandao_pkg["memory_context_mode"] == "mode_b"
    assert tiandao_pkg["source_refs"][0]["ref_id"] == "ref-1"
    assert tiandao_pkg["permission_boundary"]["memory_write_enabled"] is False
    assert tiandao_pkg["adapter_verdict"]["adapter_verdict"] == "READY_FOR_MEMORY_CONTEXT_CANDIDATE"
    assert "matched_memories" not in tiandao_pkg
    assert "raw_projection" not in tiandao_pkg
    assert "raw_excerpt" not in structured["items"][0]
    assert "items.raw_excerpt" in structured["response_budget"]["omitted_large_fields"]
    assert structured["response_budget"]["mode"] == "claude_desktop_compact"
    assert "used_source_refs" not in structured["consumer_receipt"]


def test_claude_desktop_bridge_compacts_preflight_payload_for_stdio(tmp_path):
    sys.modules.pop("claude_desktop_mcp_bridge_under_test", None)
    spec = importlib.util.spec_from_file_location(
        "claude_desktop_mcp_bridge_under_test",
        ROOT / "tools" / "claude_desktop_mcp_bridge.py",
    )
    bridge = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(bridge)

    request = {
        "jsonrpc": "2.0",
        "id": 70,
        "method": "tools/call",
        "params": {
            "name": "zhiyi_recall",
            "arguments": {"query": "继续平台配置", "mode": "preflight"},
        },
    }
    payload = {
        "ok": True,
        "mode": "preflight",
        "version": "2026.6.20",
        "contract": "zhixing_preflight.v2026.6.20",
        "auto_entry_contract": "zhixing_auto_entry.v2026.6.20",
        "auto_entry_state": "enter",
        "auto_entry_allowed": True,
        "auto_retreat_allowed": False,
        "auto_entry_reason": "proactive_resurfacing_required",
        "auto_entry_triggered_by": ["prompt:continuation", "shelf:xingce"],
        "auto_retreat_reason": "",
        "context_delivery_mode": "compact_source_anchors",
        "next_action": "apply_must_surface_before_answer",
        "agent_instruction": "Use must_surface, do_not_repeat, and acceptance_checks before answering; do not expose raw excerpts.",
        "consumer": "claude_desktop",
        "query": "继续平台配置",
        "read_only": True,
        "write_performed": False,
        "raw_write_performed": False,
        "zhiyi_write_performed": False,
        "xingce_write_performed": False,
        "platform_write_performed": False,
        "model_call_performed": False,
        "recall_performed": True,
        "raw_excerpt_returned": False,
        "decision": "surface",
        "prompt_class": "continuation",
        "confidence": 0.87,
        "min_surface_score": 45,
        "top_score": 87,
        "preflight_score_policy": "library_index_projection_is_soft_navigation_signal_only",
        "library_index_projection_soft_weight_policy": "soft_rank_signal_only_raw_evidence_required",
        "library_index_projection_soft_weight": 6,
        "preflight_score_profile": [
            {
                "library_id": "ZX-XINGCE-1",
                "library_shelf": "xingce",
                "score": 81,
                "base_score": 75,
                "surface_eligibility_score": 75,
                "surface_eligible": True,
                "library_index_projection_soft_weight_applied": True,
                "library_index_projection_soft_weight": 6,
            }
        ],
        "silence_reason": "",
        "should_recall": True,
        "should_surface": True,
        "source_refs_required": True,
        "proactive_resurfacing_required": True,
        "zhiyi_focus": ["source_backed_intent"],
        "xingce_focus": ["action_strategy", "acceptance_checks"],
        "must_surface": [
            {
                "library_id": "ZX-XINGCE-1",
                "library_shelf": "xingce",
                "title": "Hermes profile config",
                "summary": "先查 profile config",
                "source_system": "codex",
                "source_path": "raw/probe_logs/hermes.jsonl",
                "raw_evidence_status": "raw_offset",
                "rank_reason": "source_refs available; shelf=xingce",
                "library_index_projection_soft_weight_applied": True,
                "library_index_projection_soft_weight": 6,
                "library_index_projection_soft_weight_policy": "soft_rank_signal_only_raw_evidence_required",
                "raw_excerpt": "this must be omitted",
                "library_card": {"large": "x" * 1000},
                "typed_graph": {"large": "y" * 1000},
            }
        ],
        "do_not_repeat": ["不要改 root config 当默认继承"],
        "acceptance_checks": ["hermes profile show"],
        "recall_status": "preflight_surface_required",
        "reason": "matched source-backed Zhiyi/Xingce evidence should be surfaced before answering",
        "memory_scope": "active",
        "memory_base_scope": "active_layered",
        "matched_count": 1,
        "source_refs_count": 1,
        "raw_items_count": 1,
        "raw_recall_trajectory_contract": "raw_recall_trajectory.v2026.6.17",
        "raw_recall_trajectory_policy": "retrieval_steps_are_diagnostics_not_evidence",
        "raw_recall_trajectory": [
            {
                "step": "catalog_index_projection",
                "layer": "L1_library_index_projection",
                "status": "hit",
                "used": True,
                "authority": "navigation_hint_only_raw_evidence_required",
            }
        ],
        "library_index_projection_contract": "library_index_projection_receipt.v2026.6.17",
        "library_index_projection_policy": "navigation_hint_only_raw_evidence_required",
        "library_index_projection_used": True,
        "library_index_projection_refs_count": 1,
        "library_index_projection_refs": [
            {
                "projection_kind": "library_index_projection",
                "authority": "navigation_hint_only_raw_evidence_required",
                "source_path": "raw/probe_logs/hermes.jsonl",
            }
        ],
        "fast_window_preflight": True,
        "fast_recall_path": "canonical_window_index",
        "fast_window_index_status": "hit_recent_context",
        "zhiyi_layer_skipped_for_fast_preflight": True,
        "zhixing_library": {"large": "z" * 1000},
        "hybrid_recall": {"large": "h" * 1000},
        "consumer_receipt": {
            "consumer": "claude_desktop",
            "request_id": "preflight-1",
            "read_only": True,
            "write_performed": False,
            "items_count": 1,
            "source_refs_count": 1,
            "raw_items_count": 1,
            "receipt_scope": "zhixing_preflight_read_only",
            "used_library_ids": ["ZX-XINGCE-1"],
            "library_index_projection_used": True,
            "library_index_projection_refs_count": 1,
            "library_index_projection_policy": "navigation_hint_only_raw_evidence_required",
            "library_index_projection_soft_weight_policy": "soft_rank_signal_only_raw_evidence_required",
            "library_index_projection_soft_weight": 6,
            "preflight_score_policy": "library_index_projection_is_soft_navigation_signal_only",
            "raw_recall_trajectory_contract": "raw_recall_trajectory.v2026.6.17",
            "raw_recall_trajectory_policy": "retrieval_steps_are_diagnostics_not_evidence",
        },
    }
    gateway_response = {
        "jsonrpc": "2.0",
        "id": 70,
        "result": {
            "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
            "structuredContent": payload,
            "isError": False,
        },
    }

    with patch.object(bridge.urllib.request, "urlopen") as urlopen:
        urlopen.return_value.__enter__.return_value.status = 200
        urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(
            gateway_response,
            ensure_ascii=False,
        ).encode("utf-8")
        result = bridge._forward(
            "http://127.0.0.1:9851/mcp",
            request,
            30,
            True,
            registry_path=str(tmp_path / "empty-window-binding-registry.json"),
        )

    forwarded_body = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))
    forwarded_args = forwarded_body["params"]["arguments"]
    assert forwarded_args["mode"] == "preflight"
    assert forwarded_args["consumer"] == "claude_desktop"
    assert forwarded_args["memory_scope"] == "active"
    structured = result["result"]["structuredContent"]
    text_payload = json.loads(result["result"]["content"][0]["text"])
    assert structured == text_payload
    assert structured["mode"] == "preflight"
    assert structured["decision"] == "surface"
    assert structured["auto_entry_contract"] == "zhixing_auto_entry.v2026.6.20"
    assert structured["auto_entry_state"] == "enter"
    assert structured["auto_entry_allowed"] is True
    assert structured["auto_retreat_allowed"] is False
    assert structured["auto_entry_reason"] == "proactive_resurfacing_required"
    assert structured["auto_entry_triggered_by"] == ["prompt:continuation", "shelf:xingce"]
    assert structured["context_delivery_mode"] == "compact_source_anchors"
    assert structured["next_action"] == "apply_must_surface_before_answer"
    assert structured["prompt_class"] == "continuation"
    assert structured["confidence"] == 0.87
    assert structured["should_surface"] is True
    assert structured["proactive_resurfacing_required"] is True
    assert structured["do_not_repeat"] == ["不要改 root config 当默认继承"]
    assert structured["acceptance_checks"] == ["hermes profile show"]
    assert structured["must_surface"][0]["library_id"] == "ZX-XINGCE-1"
    assert structured["must_surface"][0]["library_index_projection_soft_weight_applied"] is True
    assert structured["must_surface"][0]["library_index_projection_soft_weight"] == 6
    assert "raw_excerpt" not in structured["must_surface"][0]
    assert "library_card" not in structured["must_surface"][0]
    assert "typed_graph" not in structured["must_surface"][0]
    assert "zhixing_library" not in structured
    assert "hybrid_recall" not in structured
    assert structured["preflight_score_policy"] == "library_index_projection_is_soft_navigation_signal_only"
    assert structured["library_index_projection_soft_weight_policy"] == "soft_rank_signal_only_raw_evidence_required"
    assert structured["preflight_score_profile"][0]["base_score"] == 75
    assert structured["library_index_projection_used"] is True
    assert structured["library_index_projection_refs"][0]["authority"] == "navigation_hint_only_raw_evidence_required"
    assert structured["raw_recall_trajectory"][0]["step"] == "catalog_index_projection"
    assert structured["fast_window_preflight"] is True
    assert structured["fast_recall_path"] == "canonical_window_index"
    assert structured["fast_window_index_status"] == "hit_recent_context"
    assert structured["zhiyi_layer_skipped_for_fast_preflight"] is True
    assert structured["response_budget"]["mode"] == "claude_desktop_preflight_compact"
    assert structured["consumer_receipt"]["receipt_scope"] == "zhixing_preflight_read_only"
    assert structured["consumer_receipt"]["preflight_score_policy"] == "library_index_projection_is_soft_navigation_signal_only"
    assert structured["consumer_receipt"]["library_index_projection_soft_weight"] == 6


def test_claude_desktop_bridge_compacts_work_preflight_payload_for_stdio(tmp_path):
    sys.modules.pop("claude_desktop_mcp_bridge_under_test", None)
    spec = importlib.util.spec_from_file_location(
        "claude_desktop_mcp_bridge_under_test",
        ROOT / "tools" / "claude_desktop_mcp_bridge.py",
    )
    bridge = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(bridge)

    request = {
        "jsonrpc": "2.0",
        "id": 73,
        "method": "tools/call",
        "params": {
            "name": "zhiyi_recall",
            "arguments": {"query": "win-node-a Claude 召回先查接线", "mode": "agent_work_preflight"},
        },
    }
    payload = {
        "ok": True,
        "mode": "work_preflight",
        "version": "2026.6.20",
        "contract": "agent_work_preflight.v2026.6.20",
        "source_preflight_contract": "zhixing_preflight.v2026.6.20",
        "consumer": "claude_desktop",
        "query": "win-node-a Claude 召回先查接线",
        "read_only": True,
        "write_performed": False,
        "raw_write_performed": False,
        "zhiyi_write_performed": False,
        "xingce_write_performed": False,
        "platform_write_performed": False,
        "model_call_performed": False,
        "classification": "built_but_miswired",
        "classification_options": ["actually_missing", "already_built_but_forgotten", "built_but_miswired", "diagnostic_gap"],
        "should_intervene": True,
        "intervention_level": "must_surface",
        "decision": "surface",
        "prompt_class": "correction",
        "recall_status": "preflight_surface_required",
        "memory_scope": "active",
        "source_collection_filter": "claude_all",
        "current_window_binding_applied": True,
        "current_window_binding_fields": ["canonical_window_id", "session_id"],
        "preflight_score_policy": "library_index_projection_is_soft_navigation_signal_only",
        "library_index_projection_soft_weight_policy": "soft_rank_signal_only_raw_evidence_required",
        "library_index_projection_soft_weight": 6,
        "preflight_score_profile": [
            {
                "library_id": "ZX-XINGCE-WINDOWS-CLAUDE",
                "library_shelf": "xingce",
                "score": 83,
                "base_score": 77,
                "surface_eligible": True,
                "library_index_projection_soft_weight_applied": True,
                "library_index_projection_soft_weight": 6,
            }
        ],
        "library_index_projection_contract": "library_index_projection_receipt.v2026.6.17",
        "library_index_projection_policy": "navigation_hint_only_raw_evidence_required",
        "library_index_projection_used": True,
        "library_index_projection_refs_count": 1,
        "library_index_projection_refs": [
            {
                "projection_kind": "library_index_projection",
                "authority": "navigation_hint_only_raw_evidence_required",
                "source_path": "raw/probe_logs/win-node-a-claude.jsonl",
            }
        ],
        "evidence": [
            {
                "library_id": "ZX-XINGCE-WINDOWS-CLAUDE",
                "library_shelf": "xingce",
                "summary": "source_system 错配导致召回去错抽屉。",
                "source_system": "claude_desktop",
                "source_path": "raw/probe_logs/win-node-a-claude.jsonl",
                "raw_evidence_status": "raw_offset",
                "library_index_projection_soft_weight_applied": True,
                "library_index_projection_soft_weight": 6,
                "library_index_projection_soft_weight_policy": "soft_rank_signal_only_raw_evidence_required",
                "raw_excerpt": "this must be omitted",
                "library_card": {"large": "x" * 1000},
                "typed_graph": {"large": "y" * 1000},
            }
        ],
        "changed_behavior": ["Debug wiring, routing, or host-specific config before adding features."],
        "agent_instruction": "Inspect the connection path and host/window binding before changing core behavior.",
        "next_action": "inspect_connection_path_before_feature_work",
        "raw_excerpt_returned": False,
        "consumer_receipt": {
            "consumer": "claude_desktop",
            "read_only": True,
            "write_performed": False,
            "memory_write": False,
            "platform_write": False,
            "receipt_scope": "agent_work_preflight_read_only",
            "used_library_ids": ["ZX-XINGCE-WINDOWS-CLAUDE"],
            "library_index_projection_used": True,
            "library_index_projection_refs_count": 1,
            "library_index_projection_policy": "navigation_hint_only_raw_evidence_required",
            "library_index_projection_soft_weight_policy": "soft_rank_signal_only_raw_evidence_required",
            "library_index_projection_soft_weight": 6,
            "preflight_score_policy": "library_index_projection_is_soft_navigation_signal_only",
        },
    }
    gateway_response = {
        "jsonrpc": "2.0",
        "id": 73,
        "result": {
            "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
            "structuredContent": payload,
            "isError": False,
        },
    }

    with patch.object(bridge.urllib.request, "urlopen") as urlopen:
        urlopen.return_value.__enter__.return_value.status = 200
        urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(
            gateway_response,
            ensure_ascii=False,
        ).encode("utf-8")
        result = bridge._forward(
            "http://127.0.0.1:9851/mcp",
            request,
            30,
            True,
            registry_path=str(tmp_path / "empty-window-binding-registry.json"),
        )

    forwarded_body = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))
    forwarded_args = forwarded_body["params"]["arguments"]
    assert forwarded_args["mode"] == "agent_work_preflight"
    assert forwarded_args["consumer"] == "claude_desktop"
    assert forwarded_args["memory_scope"] == "active"
    structured = result["result"]["structuredContent"]
    text_payload = json.loads(result["result"]["content"][0]["text"])
    assert structured == text_payload
    assert structured["mode"] == "work_preflight"
    assert structured["classification"] == "built_but_miswired"
    assert structured["source_collection_filter"] == "claude_all"
    assert structured["current_window_binding_applied"] is True
    assert structured["evidence"][0]["library_id"] == "ZX-XINGCE-WINDOWS-CLAUDE"
    assert structured["evidence"][0]["library_index_projection_soft_weight_applied"] is True
    assert structured["evidence"][0]["library_index_projection_soft_weight"] == 6
    assert "raw_excerpt" not in structured["evidence"][0]
    assert "library_card" not in structured["evidence"][0]
    assert "typed_graph" not in structured["evidence"][0]
    assert structured["preflight_score_policy"] == "library_index_projection_is_soft_navigation_signal_only"
    assert structured["library_index_projection_soft_weight_policy"] == "soft_rank_signal_only_raw_evidence_required"
    assert structured["preflight_score_profile"][0]["library_id"] == "ZX-XINGCE-WINDOWS-CLAUDE"
    assert structured["library_index_projection_used"] is True
    assert structured["library_index_projection_refs"][0]["authority"] == "navigation_hint_only_raw_evidence_required"
    assert structured["response_budget"]["mode"] == "claude_desktop_work_preflight_compact"
    assert structured["consumer_receipt"]["receipt_scope"] == "agent_work_preflight_read_only"
    assert structured["consumer_receipt"]["preflight_score_policy"] == "library_index_projection_is_soft_navigation_signal_only"
    assert structured["consumer_receipt"]["library_index_projection_soft_weight"] == 6


def test_claude_desktop_bridge_preserves_window_identity_hint():
    sys.modules.pop("claude_desktop_mcp_bridge_under_test", None)
    spec = importlib.util.spec_from_file_location(
        "claude_desktop_mcp_bridge_under_test",
        ROOT / "tools" / "claude_desktop_mcp_bridge.py",
    )
    bridge = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(bridge)

    request = {
        "jsonrpc": "2.0",
        "id": 17,
        "method": "tools/call",
        "params": {"name": "zhiyi_recall", "arguments": {"query": "Claude 新窗口"}},
    }
    payload = {
        "ok": True,
        "consumer": "claude_desktop_windows",
        "query": "Claude 新窗口",
        "memory_scope": "window",
        "memory_base_scope": "window",
        "scope_missing": True,
        "recall_status": "window_identity_required",
        "window_binding_hint": (
            "Current-window recall is the default, but this client did not provide "
            "a canonical_window_id or session_id. This is not proof that memory is empty."
        ),
        "missing_scope_fields": ["canonical_window_id", "session_id"],
        "agent_boundary": "active_window_first_explicit_broad_scope",
        "injection_boundary": "window_scope_required_for_default_recall",
        "recall_performed": False,
        "raw_excerpt_returned": False,
        "matched_count": 0,
        "source_refs_count": 0,
        "raw_items_count": 0,
        "items": [],
        "zhixing_library": {"large": "x" * 5000},
        "hybrid_recall": {"large": "y" * 5000},
    }
    gateway_response = {
        "jsonrpc": "2.0",
        "id": 17,
        "result": {
            "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
            "structuredContent": payload,
            "isError": False,
        },
    }

    with patch.object(bridge.urllib.request, "urlopen") as urlopen:
        urlopen.return_value.__enter__.return_value.status = 200
        urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(
            gateway_response,
            ensure_ascii=False,
        ).encode("utf-8")
        result = bridge._forward("http://127.0.0.1:9851/mcp", request, 30, True)

    structured = result["result"]["structuredContent"]
    text_payload = json.loads(result["result"]["content"][0]["text"])
    assert structured == text_payload
    assert structured["scope_missing"] is True
    assert structured["recall_status"] == "window_identity_required"
    assert "not proof that memory is empty" in structured["window_binding_hint"]
    assert structured["missing_scope_fields"] == ["canonical_window_id", "session_id"]
    assert structured["recall_performed"] is False
    assert structured["raw_excerpt_returned"] is False
    assert "zhixing_library" not in structured
    assert "hybrid_recall" not in structured


def test_claude_desktop_bridge_preserves_explicit_recall_budget():
    sys.modules.pop("claude_desktop_mcp_bridge_under_test", None)
    spec = importlib.util.spec_from_file_location(
        "claude_desktop_mcp_bridge_under_test",
        ROOT / "tools" / "claude_desktop_mcp_bridge.py",
    )
    bridge = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(bridge)

    request = {
        "jsonrpc": "2.0",
        "id": 8,
        "method": "tools/call",
        "params": {
            "name": "zhiyi_recall",
            "arguments": {
                "query": "test",
                "limit": 1,
                "excerpt_chars": 40,
            },
        },
    }
    gateway_response = {
        "jsonrpc": "2.0",
        "id": 8,
        "result": {
            "content": [{"type": "text", "text": "{}"}],
            "structuredContent": {"ok": True, "matched_count": 0, "items": []},
            "isError": False,
        },
    }

    with patch.object(bridge.urllib.request, "urlopen") as urlopen:
        urlopen.return_value.__enter__.return_value.status = 200
        urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(
            gateway_response,
            ensure_ascii=False,
        ).encode("utf-8")
        bridge._forward("http://127.0.0.1:9851/mcp", request, 30, True)

    forwarded_body = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))
    forwarded_args = forwarded_body["params"]["arguments"]
    assert forwarded_args["consumer"] == "claude_desktop"
    assert forwarded_args["memory_scope"] == "active"
    assert forwarded_args["limit"] == 1
    assert forwarded_args["excerpt_chars"] == 40


def test_claude_desktop_bridge_adds_explicit_window_binding_without_guessing():
    sys.modules.pop("claude_desktop_mcp_bridge_under_test", None)
    spec = importlib.util.spec_from_file_location(
        "claude_desktop_mcp_bridge_under_test",
        ROOT / "tools" / "claude_desktop_mcp_bridge.py",
    )
    bridge = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(bridge)

    request = {
        "jsonrpc": "2.0",
        "id": 18,
        "method": "tools/call",
        "params": {"name": "zhiyi_recall", "arguments": {"query": "test"}},
    }
    gateway_response = {
        "jsonrpc": "2.0",
        "id": 18,
        "result": {
            "content": [{"type": "text", "text": "{}"}],
            "structuredContent": {"ok": True, "matched_count": 0, "items": []},
            "isError": False,
        },
    }

    with patch.object(bridge.urllib.request, "urlopen") as urlopen:
        urlopen.return_value.__enter__.return_value.status = 200
        urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(
            gateway_response,
            ensure_ascii=False,
        ).encode("utf-8")
        bridge._forward(
            "http://127.0.0.1:9851/mcp",
            request,
            30,
            True,
            canonical_window_id="claude-official-1",
            session_id="claude-official-1",
        )

    forwarded_body = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))
    forwarded_args = forwarded_body["params"]["arguments"]
    assert forwarded_args["consumer"] == "claude_desktop"
    assert forwarded_args["memory_scope"] == "active"
    assert forwarded_args["canonical_window_id"] == "claude-official-1"
    assert forwarded_args["session_id"] == "claude-official-1"


def test_claude_desktop_bridge_adds_registry_current_window_binding(tmp_path):
    sys.modules.pop("claude_desktop_mcp_bridge_under_test", None)
    spec = importlib.util.spec_from_file_location(
        "claude_desktop_mcp_bridge_under_test",
        ROOT / "tools" / "claude_desktop_mcp_bridge.py",
    )
    bridge = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(bridge)

    registry_path = tmp_path / "window_binding_registry.json"
    registry_path.write_text(
        json.dumps(
            {
                "current_windows": {
                    "claude_desktop": {
                        "canonical_window_id": "claude-official-2",
                        "session_id": "claude-session-2",
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    request = {
        "jsonrpc": "2.0",
        "id": 19,
        "method": "tools/call",
        "params": {"name": "zhiyi_recall", "arguments": {"query": "test"}},
    }
    gateway_response = {
        "jsonrpc": "2.0",
        "id": 19,
        "result": {
            "content": [{"type": "text", "text": "{}"}],
            "structuredContent": {"ok": True, "matched_count": 0, "items": []},
            "isError": False,
        },
    }

    with patch.object(bridge.urllib.request, "urlopen") as urlopen:
        urlopen.return_value.__enter__.return_value.status = 200
        urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(
            gateway_response,
            ensure_ascii=False,
        ).encode("utf-8")
        bridge._forward(
            "http://127.0.0.1:9851/mcp",
            request,
            30,
            True,
            registry_path=str(registry_path),
        )

    forwarded_body = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))
    forwarded_args = forwarded_body["params"]["arguments"]
    assert forwarded_args["consumer"] == "claude_desktop"
    assert forwarded_args["memory_scope"] == "active"
    assert forwarded_args["canonical_window_id"] == "claude-official-2"
    assert forwarded_args["session_id"] == "claude-session-2"


def test_claude_desktop_bridge_defaults_preflight_to_window_scope_when_bound(tmp_path):
    sys.modules.pop("claude_desktop_mcp_bridge_under_test", None)
    spec = importlib.util.spec_from_file_location(
        "claude_desktop_mcp_bridge_under_test",
        ROOT / "tools" / "claude_desktop_mcp_bridge.py",
    )
    bridge = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(bridge)

    registry_path = tmp_path / "window_binding_registry.json"
    registry_path.write_text(
        json.dumps(
            {
                "current_windows": {
                    "claude_desktop": {
                        "canonical_window_id": "claude-window-fast",
                        "session_id": "claude-session-fast",
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    request = {
        "jsonrpc": "2.0",
        "id": 20,
        "method": "tools/call",
        "params": {
            "name": "zhiyi_recall",
            "arguments": {"query": "继续发布前检查", "mode": "preflight"},
        },
    }
    gateway_response = {
        "jsonrpc": "2.0",
        "id": 20,
        "result": {
            "content": [{"type": "text", "text": "{}"}],
            "structuredContent": {"ok": True, "mode": "preflight", "decision": "silent"},
            "isError": False,
        },
    }

    with patch.dict(os.environ, {}, clear=True):
        with patch.object(bridge.urllib.request, "urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.status = 200
            urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(
                gateway_response,
                ensure_ascii=False,
            ).encode("utf-8")
            bridge._forward(
                "http://127.0.0.1:9851/mcp",
                request,
                30,
                True,
                registry_path=str(registry_path),
            )

    forwarded_body = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))
    forwarded_args = forwarded_body["params"]["arguments"]
    assert forwarded_args["mode"] == "preflight"
    assert forwarded_args["consumer"] == "claude_desktop"
    assert forwarded_args["memory_scope"] == "window"
    assert forwarded_args["canonical_window_id"] == "claude-window-fast"
    assert forwarded_args["session_id"] == "claude-session-fast"


def test_claude_desktop_bridge_normalizes_bare_gateway_error_to_jsonrpc():
    sys.modules.pop("claude_desktop_mcp_bridge_under_test", None)
    spec = importlib.util.spec_from_file_location(
        "claude_desktop_mcp_bridge_under_test",
        ROOT / "tools" / "claude_desktop_mcp_bridge.py",
    )
    bridge = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(bridge)

    request = {
        "jsonrpc": "2.0",
        "id": 9,
        "method": "tools/call",
        "params": {"name": "zhiyi_recall", "arguments": {"query": "test"}},
    }
    bare_gateway_error = {"ok": False, "error": "simulated gateway failure"}

    with patch.object(bridge.urllib.request, "urlopen") as urlopen:
        urlopen.return_value.__enter__.return_value.status = 200
        urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(
            bare_gateway_error,
            ensure_ascii=False,
        ).encode("utf-8")
        result = bridge._forward("http://127.0.0.1:9851/mcp", request, 30, True)

    assert result == {
        "jsonrpc": "2.0",
        "id": 9,
        "error": {"code": -32603, "message": "simulated gateway failure"},
    }
    assert "ok" not in result


def test_claude_desktop_bridge_normalizes_invalid_jsonrpc_error_id():
    sys.modules.pop("claude_desktop_mcp_bridge_under_test", None)
    spec = importlib.util.spec_from_file_location(
        "claude_desktop_mcp_bridge_under_test",
        ROOT / "tools" / "claude_desktop_mcp_bridge.py",
    )
    bridge = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(bridge)

    request = {
        "jsonrpc": "2.0",
        "id": 10,
        "method": "tools/call",
        "params": {"name": "zhiyi_recall", "arguments": {"query": "test"}},
    }
    invalid_gateway_error = {
        "jsonrpc": "2.0",
        "id": None,
        "error": {"code": -32603, "message": "bad upstream id"},
    }

    with patch.object(bridge.urllib.request, "urlopen") as urlopen:
        urlopen.return_value.__enter__.return_value.status = 200
        urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(
            invalid_gateway_error,
            ensure_ascii=False,
        ).encode("utf-8")
        result = bridge._forward("http://127.0.0.1:9851/mcp", request, 30, True)

    assert result == {
        "jsonrpc": "2.0",
        "id": 10,
        "error": {"code": -32603, "message": "bad upstream id"},
    }


def test_installers_report_claude_skill_update_only_when_installed_count_positive():
    mac = (ROOT / "tools" / "macos_full_install.sh").read_text(encoding="utf-8")
    linux = (ROOT / "tools" / "linux_full_install.sh").read_text(encoding="utf-8")
    windows = (ROOT / "tools" / "windows_full_install.ps1").read_text(encoding="utf-8")

    for text in (mac, linux):
        assert "installed_count" in text
        assert "SKILL_RESULT=" in text
        assert "Claude Desktop skill not updated:" in text
        assert 'if [[ "$skill_status" == 0:* ]]' in text

    assert "ConvertFrom-Json" in windows
    assert "installed_count -gt 0" in windows
    assert "Claude Desktop skill not updated for" in windows


def test_installers_wait_for_slow_large_library_services_before_smoke_fails():
    mac = (ROOT / "tools" / "macos_full_install.sh").read_text(encoding="utf-8")
    linux = (ROOT / "tools" / "linux_full_install.sh").read_text(encoding="utf-8")
    windows = (ROOT / "tools" / "windows_full_install.ps1").read_text(encoding="utf-8")

    for text in (mac, linux):
        assert "max_wait" in text
        assert "time.monotonic()" in text
        assert "ok after {attempt} attempt(s)" in text
        assert "health_acceptance_smoke" in text
        assert "deadline = time.monotonic() + 240" in text
        assert '(last.get(name) or {}).get("status") != "passed"' in text
        assert "sleep 4" not in text
        assert "sleep 5" not in text

    assert "[int]$MaxWaitSeconds = 75" in windows
    assert "(Get-Date).AddSeconds($MaxWaitSeconds)" in windows
    assert "ok after $attempt attempt(s)" in windows
    assert 'Smoke-One -Name "front-door"' in windows
    assert "Start-Sleep -Seconds 5" not in windows


def test_linux_installer_disables_legacy_units_and_only_enables_current_units():
    linux = (ROOT / "tools" / "linux_full_install.sh").read_text(encoding="utf-8")
    identity = (ROOT / "tools" / "install_runtime_identity.py").read_text(encoding="utf-8")
    start_services = linux.split("start_user_services() {", 1)[1].split("\n}", 1)[0]
    install_files = linux.split("install_files() {", 1)[1].split("\n}", 1)[0]

    assert "current_service_names()" in linux
    assert "legacy_service_names()" in linux
    assert "service_names()" in linux
    assert "stop_stale_runtime_processes()" in linux
    assert '"raw_consumption_gateway.py"' in identity
    assert 'os.kill(pid, signal.SIGTERM)' in linux
    assert "stop_stale_runtime_processes" not in install_files
    assert 'if [[ "$SKIP_START" == "0" ]]; then' in linux
    assert "assert_user_service_ownership_available" in linux
    assert 'service_targets_install_root "$unit" || continue' in linux
    assert 'systemctl --user disable --now "$unit"' in start_services
    assert "done < <(legacy_service_names)" in start_services
    assert "done < <(current_service_names)" in start_services
    assert "done < <(service_names)" not in start_services
    assert "memcore-cloud-p0-watcher.service" in linux
    assert 'loginctl enable-linger "$USER"' in start_services
    assert "services will start only while the user is logged in" in start_services


def test_unix_installers_quiesce_owned_runtime_before_copy_and_fail_on_copy_error():
    cases = (
        ("macos_full_install.sh", "stop_old_launchagents"),
        ("linux_full_install.sh", "stop_user_services"),
    )
    for name, stop_call in cases:
        installer = (ROOT / "tools" / name).read_text(encoding="utf-8")
        main = installer.split('log "Source: ${SOURCE_ROOT}"', 1)[1]
        copy_runtime = installer.split("copy_runtime_data() {", 1)[1].split("\n}", 1)[0]
        migrate_state = installer.split("migrate_legacy_state_paths() {", 1)[1].split("\n}", 1)[0]

        assert main.index(stop_call) < main.index("install_files")
        assert '[[ "$SKIP_START" == "0" ]]' in main[: main.index("install_files")]
        assert "rsync -a" in copy_runtime
        assert "|| true" not in copy_runtime
        assert "install_state_migration.jsonl" in migrate_state
        assert 'receipt="$(python3' in migrate_state


def test_unix_installers_retire_legacy_plugin_config_during_upgrade():
    for name in ("macos_full_install.sh", "linux_full_install.sh"):
        installer = (ROOT / "tools" / name).read_text(encoding="utf-8")

        assert 'legacy_entry = "memcore-" + "zhiyi-native"' in installer
        assert "Path(path).expanduser().resolve() in stale_paths" in installer
        assert 'legacy_plugin = "memcore_" + "yifan" + "chen"' in installer
        assert "enabled[:] = [name for name in enabled if name != legacy_plugin]" in installer
        assert "plugins.pop(legacy_plugin, None)" in installer


def test_installers_keep_no_start_service_lifecycle_symmetric_and_root_scoped():
    mac = (ROOT / "tools" / "macos_full_install.sh").read_text(encoding="utf-8")
    linux = (ROOT / "tools" / "linux_full_install.sh").read_text(encoding="utf-8")
    windows = (ROOT / "tools" / "windows_full_install.ps1").read_text(encoding="utf-8")

    mac_stop = mac.split("stop_old_launchagents() {", 1)[1].split("\n}", 1)[0]
    linux_stop = linux.split("stop_user_services() {", 1)[1].split("\n}", 1)[0]
    windows_install = windows.split("function Install-Files {", 1)[1].split("\n}", 1)[0]
    windows_start = windows.split("function Start-Services {", 1)[1].split("\n}", 1)[0]

    assert '[[ "$SKIP_START" != "0" ]]' in mac_stop
    assert 'launchagent_targets_install_root "$label"' in mac_stop
    assert "assert_launchagent_ownership_available" in mac
    assert "belongs to another Time Library install root" in mac

    assert '[[ "$SKIP_START" != "0" ]]' in linux_stop
    assert 'service_targets_install_root "$unit"' in linux_stop
    assert "assert_user_service_ownership_available" in linux
    assert "belongs to another Time Library install root" in linux

    assert "Stop-OldProcesses" not in windows_install
    assert "Start-RuntimeRoles" in windows_start
    assert "Stop-OldProcesses" in windows.split("function Start-RuntimeRoles {", 1)[1].split("\n}", 1)[0]
    assert "Host integrations and LaunchAgent definitions preserved by --no-start staging mode" in mac
    assert "Host integrations and systemd user definitions preserved by --no-start staging mode" in linux
    assert "Host integrations and scheduled tasks preserved by -NoStart staging mode" in windows
    assert "Assert-ScheduledTaskOwnershipAvailable" in windows
    assert "Test-ScheduledTaskTargetsInstallRoot" in windows
    assert "Test-TaskActionRunsInstallEntrypoint" in windows
    assert "Test-ProcessRunsInstallEntrypoint" in windows
    assert "Test-TextTargetsInstallRoot" not in windows
    assert "install_runtime_identity.py" in mac
    assert "install_runtime_identity.py" in linux
    assert '[[ "$SKIP_START" == "1" || "$SKIP_OPENCLAW" == "1" ]]' in mac
    assert '[[ "$SKIP_START" == "1" || "$SKIP_OPENCLAW" == "1" ]]' in linux
    assert 'if ((-not $NoStart) -and (-not $NoAutostart))' in windows
    assert 'if ($NoStart -or $SkipHermes)' in windows


def test_unix_installer_capability_smoke_accepts_current_or_compatible_tool_name():
    mac = (ROOT / "tools" / "macos_full_install.sh").read_text(encoding="utf-8")
    linux = (ROOT / "tools" / "linux_full_install.sh").read_text(encoding="utf-8")

    for installer in (mac, linux):
        assert 'mcp_tools = set(payload.get("mcp_tools") or [])' in installer
        assert 'mcp_tools.intersection({"time_library_recall", "zhiyi_recall"})' in installer


def test_windows_installer_preserves_runtime_state_files_on_mirror_update():
    windows = (ROOT / "tools" / "windows_full_install.ps1").read_text(encoding="utf-8")

    assert '".checkpoint"' in windows
    assert '".checkpoint_p2.json"' in windows
    assert '"update_history.jsonl"' in windows


def test_installers_initialize_window_binding_registry_without_overwriting_existing_state():
    mac = (ROOT / "tools" / "macos_full_install.sh").read_text(encoding="utf-8")
    mac_write_config = mac.split("write_config() {", 1)[1].split("\n}", 1)[0]
    assert 'if [[ ! -f "${INSTALL_ROOT}/config/window_binding_registry.json" && -f "${INSTALL_ROOT}/config/default_window_binding_registry.json" ]]; then' in mac_write_config

    linux = (ROOT / "tools" / "linux_full_install.sh").read_text(encoding="utf-8")
    linux_write_config = linux.split("write_config() {", 1)[1].split("\n}", 1)[0]
    assert '[[ -f "${INSTALL_ROOT}/config/window_binding_registry.json" || ! -f "${INSTALL_ROOT}/config/default_window_binding_registry.json" ]] ||' in linux_write_config

    windows = (ROOT / "tools" / "windows_full_install.ps1").read_text(encoding="utf-8")
    write_config = windows.split("function Write-Config {", 1)[1].split("\n}", 1)[0]
    assert 'Copy-ConfigTemplate -Name "default_window_binding_registry.json" -Target "window_binding_registry.json"' in write_config


def test_windows_installer_passes_the_declared_argument_array_to_robocopy():
    windows = (ROOT / "tools" / "windows_full_install.ps1").read_text(encoding="utf-8")
    mirror_copy = windows.split("function Invoke-Robocopy {", 1)[1].split(
        "function Merge-PackagedConfig {", 1
    )[0]

    assert "$robocopyArgs = @(" in mirror_copy
    assert "& robocopy @robocopyArgs" in mirror_copy
    assert "& robocopy @args" not in mirror_copy


def test_windows_reinstall_prepares_venv_offline_and_rolls_back_failed_program_mirror():
    windows = (ROOT / "tools" / "windows_full_install.ps1").read_text(encoding="utf-8")
    main = windows.split('Info "Source: $SourceRoot"', 1)[1]
    prepare = windows.split("function Install-PythonEnv {", 1)[1].split(
        "function Activate-PythonEnv {", 1
    )[0]
    mirror = windows.split("function Invoke-Robocopy {", 1)[1].split(
        "function Merge-PackagedConfig {", 1
    )[0]

    assert main.index("Install-PythonEnv") < main.index("Install-Files")
    assert main.index("Install-Files") < main.index("Activate-PythonEnv")
    assert '".venv-build."' in prepare
    assert '".wheelhouse-stage."' in prepare
    assert "requirements-core.txt" in prepare
    assert prepare.count("$LASTEXITCODE -ne 0") >= 3
    assert "-m pip wheel --wheel-dir $wheelhouse" in prepare
    assert "Stop-OldProcesses" not in prepare
    assert "& $PreparedPython -m venv $venv" in windows
    assert "Move-Item -LiteralPath $PreparedVenv" not in windows
    activate = windows.split("function Activate-PythonEnv {", 1)[1].split(
        "function Remove-PreviousVenvBackup {", 1
    )[0]
    assert 'Join-Path $parent ("." + $leaf + ".venv-backup."' in activate
    assert '$backup = "$venv.backup.' not in activate
    assert "Wait-Process" in windows
    assert "Stop-ScheduledTask" in windows
    assert "Get-Content -LiteralPath $modelCfgPath -Raw -Encoding UTF8 | ConvertFrom-Json" in windows
    assert "Program mirror failed" in mirror
    assert "Get-ProgramMirrorArgs -From $RollbackPath -To $To" in mirror
    assert "prior program files were restored" in mirror
    assert "production files were not changed" in windows


def test_windows_upgrade_is_transactional_and_no_start_rejects_a_live_root():
    windows = (ROOT / "tools" / "windows_full_install.ps1").read_text(encoding="utf-8")
    main = windows.split('Info "Source: $SourceRoot"', 1)[1]
    rollback = windows.split("function Restore-InstallTransaction {", 1)[1].split(
        "function Remove-PreparedPythonAssets {", 1
    )[0]
    remove_tree = windows.split("function Remove-Tree {", 1)[1].split(
        "function Copy-ConfigTemplate {", 1
    )[0]

    assert "Assert-NoStartTargetIsOffline" in main
    assert "Begin-InstallCutover" in main
    assert "Restore-InstallTransaction" in main
    assert "Backup-TransactionState" in windows
    assert "Restore-TransactionState" in rollback
    assert "Invoke-Robocopy -From $ProgramBackup -To $InstallRoot" in rollback
    assert "PreviousVenvBackup" in rollback
    assert "Start-RuntimeRoles -Roles $RunningRuntimeRolesBeforeUpgrade" in rollback
    assert "Restore-ScheduledTaskSnapshots" in rollback
    assert "Remove-PreviousVenvBackup" in windows
    assert "Normalize-InstallRootPath" in windows
    assert "$ScheduledTaskSnapshotCaptured" in windows
    assert "scheduled task restore failed after retry" in windows
    assert "Assert-NoStartRuntimeAbsent -Root $targetRoot" in windows
    assert "[System.IO.Directory]::Move($stageRoot, $targetRoot)" in windows
    assert 'Die "Windows guardian script not found: $guardian"' in windows
    assert 'Die "Windows tray script not found: $tray"' in windows
    assert "Export-ScheduledTask" in windows
    assert "Register-ScheduledTask -TaskName $snapshot.TaskName -Xml $snapshot.Xml" in windows
    assert "Get-CimInstance Win32_Process -ErrorAction Stop" in windows
    assert "Time Library processes are still running after stop request" in windows
    assert "$maxAttempts = 20" in remove_tree
    assert "Start-Sleep -Milliseconds 250" in remove_tree
    assert "-NoStart requires a new install root" in windows
    assert "-ResetInstall refuses to delete an existing root" in main
    assert "-ResetInstall target appeared after preflight" in windows
    assert main.index("Start-Services") < main.index("Register-WindowsAutostart")
    assert main.index("Register-WindowsAutostart") < main.index("Run-Smoke")
    assert main.index("Run-Smoke") < main.index("Install-ClaudeCodeMcp")


def test_windows_claude_code_registration_passes_its_declared_argument_array():
    windows = (ROOT / "tools" / "windows_full_install.ps1").read_text(encoding="utf-8")
    install = windows.split("function Install-ClaudeCodeMcp {", 1)[1].split(
        "function Install-ClaudeDesktopMcp {", 1
    )[0]

    assert "$claudeArgs = @(" in install
    assert "& $claude.Source @claudeArgs" in install
    assert "$args = @(" not in install


def test_claude_desktop_skill_helper_updates_existing_legacy_skill_only(tmp_path):
    helper = _load_claude_skill_helper()
    claude_home = tmp_path / "Claude"
    plugin_root = claude_home / "local-agent-mode-sessions" / "skills-plugin" / "session-a" / "account-a"
    plugin_root.mkdir(parents=True)
    (plugin_root / "manifest.json").write_text(
        json.dumps(
            {
                "skills": [
                    {"skillId": "other-skill", "name": "Other", "enabled": True},
                    {
                        "skillId": "time-library",
                        "name": "Old Time Library",
                        "description": "old",
                        "enabled": False,
                    },
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    skill_src = tmp_path / "skill-src"
    skill_src.mkdir()
    (skill_src / "SKILL.md").write_text(
        "---\nname: time-library\nprompt_version: 2\n---\n",
        encoding="utf-8",
    )

    result = helper.install_skill(claude_home, skill_src)
    manifest = json.loads((plugin_root / "manifest.json").read_text(encoding="utf-8"))
    skills = {item["skillId"]: item for item in manifest["skills"]}

    assert result["ok"] is True
    assert result["reason"] == "installed"
    assert result["created_if_missing"] is False
    assert result["installed_count"] == 1
    assert skills["other-skill"]["name"] == "Other"
    assert skills["time-library"]["name"] == "Time Library"
    assert skills["time-library"]["enabled"] is True
    assert "previous decisions" in skills["time-library"]["description"]
    assert "install/test/release status" in skills["time-library"]["description"]
    assert "Standing active memory rule" in skills["time-library"]["description"]
    assert "Time Library MCP tool `time_library_recall`" in skills["time-library"]["description"]
    assert "skill is installed but recall cannot run yet" in skills["time-library"]["description"]
    assert "Preserve Claude Desktop" in skills["time-library"]["description"]
    assert (plugin_root / "skills" / "time-library" / "SKILL.md").exists()


def test_claude_desktop_skill_helper_creates_primary_time_library_skill(tmp_path):
    helper = _load_claude_skill_helper()
    claude_home = tmp_path / "Claude"
    plugin_root = claude_home / "local-agent-mode-sessions" / "skills-plugin" / "session-a" / "account-a"
    plugin_root.mkdir(parents=True)
    (plugin_root / "manifest.json").write_text('{"skills":[]}', encoding="utf-8")
    skill_src = tmp_path / "skill-src"
    skill_src.mkdir()
    (skill_src / "SKILL.md").write_text(
        "---\nname: time-library\nprompt_version: 5\n---\n",
        encoding="utf-8",
    )

    result = helper.install_skill(claude_home, skill_src, create=True)
    manifest = json.loads((plugin_root / "manifest.json").read_text(encoding="utf-8"))
    skills = {item["skillId"]: item for item in manifest["skills"]}

    assert result["ok"] is True
    assert result["reason"] == "installed"
    assert result["created_if_missing"] is True
    assert result["installed_count"] == 1
    assert result["skill_id"] == "time-library"
    assert skills["time-library"]["name"] == "Time Library"
    assert "time_library_recall" in skills["time-library"]["description"]
    assert (plugin_root / "skills" / "time-library" / "SKILL.md").exists()


def test_claude_desktop_skill_helper_does_not_create_missing_skill_by_default(tmp_path):
    helper = _load_claude_skill_helper()
    claude_home = tmp_path / "Claude"
    plugin_root = claude_home / "local-agent-mode-sessions" / "skills-plugin" / "session-a" / "account-a"
    plugin_root.mkdir(parents=True)
    (plugin_root / "manifest.json").write_text(
        '{"skills":[{"skillId":"other-skill","name":"Other","enabled":true}]}',
        encoding="utf-8",
    )
    skill_src = tmp_path / "skill-src"
    skill_src.mkdir()
    (skill_src / "SKILL.md").write_text(
        "---\nname: time-library\nprompt_version: 5\n---\n",
        encoding="utf-8",
    )

    result = helper.install_skill(claude_home, skill_src)
    manifest = json.loads((plugin_root / "manifest.json").read_text(encoding="utf-8"))

    assert result["ok"] is True
    assert result["reason"] == "skill_not_found"
    assert result["installed_count"] == 0
    assert [item["skillId"] for item in manifest["skills"]] == ["other-skill"]
    assert not (plugin_root / "skills" / "time-library").exists()


def test_claude_desktop_skill_helper_create_flag_creates_missing_skill(tmp_path):
    helper = _load_claude_skill_helper()
    claude_home = tmp_path / "Claude"
    plugin_root = claude_home / "local-agent-mode-sessions" / "skills-plugin" / "session-a" / "account-a"
    plugin_root.mkdir(parents=True)
    (plugin_root / "manifest.json").write_text('{"skills":[]}', encoding="utf-8")
    skill_src = tmp_path / "skill-src"
    skill_src.mkdir()
    (skill_src / "SKILL.md").write_text(
        "---\nname: time-library\nprompt_version: 5\n---\n",
        encoding="utf-8",
    )

    result = helper.install_skill(claude_home, skill_src, create=True)
    manifest = json.loads((plugin_root / "manifest.json").read_text(encoding="utf-8"))

    assert result["ok"] is True
    assert result["reason"] == "installed"
    assert result["created_if_missing"] is True
    assert result["installed_count"] == 1
    assert manifest["skills"][0]["skillId"] == "time-library"
    assert (plugin_root / "skills" / "time-library" / "SKILL.md").exists()
