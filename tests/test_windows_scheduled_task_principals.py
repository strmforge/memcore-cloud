import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _registration_call(script: str, task_name: str) -> str:
    marker = f'-TaskName "{task_name}"'
    marker_index = script.index(marker)
    start = script.rfind("Register-ScheduledTask", 0, marker_index)
    end = script.index("| Out-Null", marker_index) + len("| Out-Null")
    return script[start:end]


def test_windows_installer_splits_interactive_and_background_task_principals():
    installer = (ROOT / "tools" / "windows_full_install.ps1").read_text(
        encoding="utf-8"
    )
    autostart = installer.split("function Register-WindowsAutostart", 1)[1].split(
        "function Smoke-One", 1
    )[0]

    assert (
        "$interactivePrincipal = New-ScheduledTaskPrincipal "
        "-UserId $identity -LogonType Interactive -RunLevel Limited"
    ) in autostart
    assert (
        "$backgroundPrincipal = New-ScheduledTaskPrincipal "
        "-UserId $identity -LogonType S4U -RunLevel Limited"
    ) in autostart
    assert autostart.count("-LogonType Interactive") == 1
    assert autostart.count("-LogonType S4U") == 1
    assert "-LogonType Password" not in autostart
    assert "-LogonType ServiceAccount" not in autostart
    assert "function Assert-BackgroundScheduledTaskRun" in installer
    assert "function Assert-LongRunningBackgroundScheduledTask" in installer
    assert (
        'Assert-BackgroundScheduledTaskRun -TaskName "MemcoreCloudGuardianHealth"'
        in autostart
    )
    assert (
        'Assert-LongRunningBackgroundScheduledTask `\n'
        '            -TaskName "MemcoreCloudCodexMcpGuard" `\n'
        '            -Role "codex-mcp-guard"'
    ) in autostart
    assert "Get-OwnedInstallProcessRecords" in installer
    assert "Start-ScheduledTask -TaskName $TaskName -ErrorAction Stop" in installer
    assert "Check SeBatchLogonRight/SeDenyBatchLogonRight" in installer
    assert "function Get-BackgroundScheduledTaskRunSample" in installer
    assert "function Get-BackgroundScheduledTaskRunDecision" in installer
    assert "function Stop-BackgroundScheduledTaskRun" in installer
    assert "function Get-WindowsGuardianTaskArguments" in installer
    assert "-StartupActivationOnly $true" in autostart
    assert "-Action $guardianLogonAction" in autostart
    assert "-Action $guardianHealthAction" in autostart
    assert "[int]$TimeoutSeconds = 600" in installer
    assert "$beforeResult" not in installer
    assert "did not reach two stable terminal samples" in installer
    assert "Stop-ScheduledTask -TaskName $TaskName" in installer
    assert "Task stop could not be confirmed" in installer
    assert "SCHED_S_BATCH_LOGON_PROBLEM=0x0004131C" in installer
    assert "ERROR_LOGON_TYPE_NOT_GRANTED=0x80070569" in installer

    expected_principals = {
        "MemcoreCloudGuardianLogon": "$interactivePrincipal",
        "MemcoreCloudGuardianHealth": "$backgroundPrincipal",
        "MemcoreCloudCodexMcpGuard": "$backgroundPrincipal",
        "MemcoreCloudTray": "$interactivePrincipal",
    }
    for task_name, principal in expected_principals.items():
        registration = _registration_call(autostart, task_name)
        assert f"-Principal {principal}" in registration


def test_windows_task_principal_upgrade_keeps_transaction_and_preserve_boundaries():
    installer = (ROOT / "tools" / "windows_full_install.ps1").read_text(
        encoding="utf-8"
    )
    autostart = installer.split("function Register-WindowsAutostart", 1)[1].split(
        "function Smoke-One", 1
    )[0]
    rollback = installer.split("function Restore-InstallTransaction", 1)[1].split(
        "function Remove-PreparedPythonAssets", 1
    )[0]
    preserve_guard = installer.split(
        "function Restore-PreviousCodexMcpGuardTask", 1
    )[1].split("function Test-ScheduledTaskTargetsInstallRoot", 1)[0]
    main = installer.split('Info "Source: $SourceRoot"', 1)[1]

    assert autostart.index("if ($NoAutostart)") < autostart.index(
        "Unregister-MemcoreScheduledTasks"
    )
    assert autostart.index("Unregister-MemcoreScheduledTasks") < autostart.index(
        "$backgroundPrincipal = New-ScheduledTaskPrincipal"
    )
    assert "Snapshot-And-SuspendScheduledTasks" in installer
    assert (
        "Register-ScheduledTask -TaskName $snapshot.TaskName -Xml $snapshot.Xml"
        in installer
    )
    assert "Restore-ScheduledTaskSnapshots" in rollback
    assert "Restore-PreviousCodexMcpGuardTask" in autostart
    assert (
        "Register-ScheduledTask -TaskName $snapshot.TaskName -Xml $snapshot.Xml"
        in preserve_guard
    )
    assert "if (-not $NoStart)" in main
    assert "Register-WindowsAutostart" in main
    assert (
        'Info "Host integrations and scheduled tasks preserved by -NoStart staging mode"'
        in main
    )
    assert "if ($NoAutostart) { Restore-ScheduledTaskSnapshots }" in main
    assert (
        'if ($NoAutostart) { $nativeArgs += " -SkipScheduledTaskChecks" }'
        in installer
    )
    assert (
        'if ($CodexMcpGuardStatus -ne "installed") '
        '{ $nativeArgs += " -SkipCodexGuardTaskCheck" }'
        in installer
    )
    guard_registration = autostart.index('-TaskName "MemcoreCloudCodexMcpGuard"')
    codex_guard_demand_start = autostart.index(
        'Assert-LongRunningBackgroundScheduledTask `'
    )
    guardian_demand_start = autostart.index(
        'Assert-BackgroundScheduledTaskRun -TaskName "MemcoreCloudGuardianHealth"'
    )
    immediate_guardian = autostart.index("$guardianImmediateArgs = @(")
    assert guard_registration < codex_guard_demand_start < guardian_demand_start < immediate_guardian
    assert '$guardianImmediateArgs += "-SkipCodexMcpGuardTaskCheck"' in autostart
    assert "-SkipCodexGuardTaskCheck $skipCodexGuardTaskCheck" in autostart


def test_windows_runtime_diagnostics_fail_closed_on_background_principal_drift():
    guardian = (ROOT / "tools" / "windows_guardian.ps1").read_text(
        encoding="utf-8"
    )
    smoke = (ROOT / "tools" / "windows_native_smoke.ps1").read_text(
        encoding="utf-8"
    )

    assert '"guardian_health_principal"' in guardian
    assert '([string]$task.Principal.LogonType -eq "S4U")' in guardian
    assert "principal_logon_type=" in guardian
    assert '"guardian_health_execution"' in guardian
    assert '"guardian_health_enabled"' in guardian
    assert '([string]$task.State -ne "Disabled")' in guardian
    assert "Get-ScheduledTaskInfo -TaskName $taskName" in guardian
    assert "last_result=" in guardian
    assert "recent_20m=" in guardian
    assert "task is missing" in guardian
    assert '"codex_mcp_guard_reconcile"' in guardian
    assert "repairs current config once but does not prove the scheduled watcher" in guardian
    assert "task is missing; Codex guard applicability" in guardian
    assert 'Add-Check -Name "codex_mcp_guard_task" -Ok $true' not in guardian
    assert guardian.index("--once") < guardian.index(
        "for ($attempt = 0; $attempt -lt 40"
    )
    assert (
        "-Ok ($scheduleOk -and $principalOk -and $enabled -and $postBoot -and $running -and "
        "($guardProcesses.Count -gt 0))"
    ) in guardian
    assert 'not_measured_layers = @("guardian_concurrent_run")' in guardian
    assert "settings_enabled=" in guardian
    assert "function ConvertTo-SafeRecoverabilityProbe" in guardian
    assert 'schema = "recoverability_probe.v1"' in guardian
    assert "recoverability_probe = $recoverabilityProbe" in guardian
    assert "($rawValue -is [int64])" in guardian
    assert "($rawValue -is [uint64])" in guardian
    assert "if (-not $isInteger) { return $null }" in guardian
    assert "$decimalValue -gt [int]::MaxValue" in guardian
    assert "[switch]$SkipCodexMcpGuardTaskCheck" in guardian
    assert "[switch]$StartupActivationOnly" in guardian
    assert '"scheduled_task_startup_convergence"' in guardian
    assert "periodic S4U Guardian performs the full scheduled-task check" in guardian
    assert "[switch]$SkipScheduledTaskChecks" in guardian
    assert 'measurement_status = "complete"' in guardian
    assert "full_health_check = $true" in guardian
    assert 'measurement_status = "not_measured"' in guardian
    assert "explicit preserved-guard override; principal not measured" in guardian

    assert '[string]$ExpectedLogonType = ""' in smoke
    assert "[switch]$RequireRecentSuccessfulRun" in smoke
    assert "[switch]$RequireRunAfterBoot" in smoke
    assert "[switch]$RequireBackgroundRecoveryAfterBoot" in smoke
    assert '([string]$task.Principal.LogonType -ne $ExpectedLogonType)' in smoke
    assert "Get-ScheduledTaskInfo -TaskName $Name" in smoke
    assert "background task has no recent successful execution" in smoke
    assert "[switch]$SkipScheduledTaskChecks" in smoke
    assert "[switch]$SkipCodexGuardTaskCheck" in smoke
    assert 'measurement_status = "complete"' in smoke
    assert "full_smoke = $true" in smoke
    assert 'measurement_status = "not_measured"' in smoke
    assert "explicit -NoAutostart preservation path" in smoke
    assert (
        'Test-ScheduledTaskPresent -Name "MemcoreCloudGuardianLogon" '
        '-ExpectedLogonType "Interactive"'
    ) in smoke
    assert '-Name "MemcoreCloudGuardianHealth"' in smoke
    assert "-RequireRecentSuccessfulRun" in smoke
    assert "-RequireRunAfterBoot:$RequireBackgroundRecoveryAfterBoot" in smoke
    assert '-Name "MemcoreCloudCodexMcpGuard"' in smoke
    assert '-ExpectedLogonType "S4U" -Required:$false' not in smoke
    assert "background task has not run after this boot" in smoke
    assert "function Merge-WindowsGuardianCoverage" in smoke
    assert "guardian-status.json is stale for this invocation" in smoke
    assert "nested Guardian coverage is partial" in smoke
    assert (
        'Test-ScheduledTaskPresent -Name "MemcoreCloudTray" '
        '-ExpectedLogonType "Interactive" -Required:$false'
    ) in smoke

    hidden_guardian = (
        ROOT / "tools" / "windows_hidden_guardian.vbs"
    ).read_text(encoding="utf-8")
    assert "-StartWatcher -Quiet" in hidden_guardian
    assert "-Backfill" not in hidden_guardian
    assert "exitCode = shell.Run(commandLine, 0, True)" in hidden_guardian
    assert "WScript.Quit exitCode" in hidden_guardian
    assert 'argumentValue = "-skipcodexmcpguardtaskcheck"' in hidden_guardian
    assert 'argumentValue = "-startupactivationonly"' in hidden_guardian


def test_background_task_state_machine_has_behavioral_powershell_cases():
    harness = ROOT / "tests" / "windows_scheduled_task_state_machine.ps1"
    text = harness.read_text(encoding="utf-8")

    for case_name in (
        "same_result_rerun",
        "preexisting_running_completed",
        "baseline_queued_not_observed_running",
        "interleaved_snapshot",
        "delayed_start_old_error",
        "disabled",
        "old_success",
        "bounded_stop_timeout",
        "stop_query_failure_is_unconfirmed",
        "sampling_failure_stops_task",
        "preserved_guard_action_is_partial",
        "long_running_guard_observed_new_process",
        "long_running_timeout_stops_task",
    ):
        assert case_name in text

    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    if powershell:
        result = subprocess.run(
            [
                powershell,
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(harness),
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "windows_scheduled_task_state_machine: PASS" in result.stdout


def test_background_task_diagnostics_have_behavioral_powershell_cases():
    harness = ROOT / "tests" / "windows_scheduled_task_diagnostics.ps1"
    text = harness.read_text(encoding="utf-8")

    for evidence in (
        "missing guard must emit one not_measured check",
        "normal smoke must fail on missing guard",
        "pre-boot success must fail post-boot acceptance",
        "disabled native task must fail",
        "settings-disabled native task must fail",
        "nested partial must clear full_smoke",
        "generated_at non-string must fail",
        "recoverability string counter must fail closed",
        "recoverability boolean counter must fail closed",
        "startup activation must defer GuardianHealth convergence",
        "startup activation must defer Codex guard convergence",
        "periodic coverage must check GuardianHealth",
        "periodic coverage must check Codex guard",
    ):
        assert evidence in text

    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    if powershell:
        result = subprocess.run(
            [
                powershell,
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(harness),
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "windows_scheduled_task_diagnostics: PASS" in result.stdout


def test_no_autostart_skips_only_task_contract_and_surfaces_partial_result():
    installer = (ROOT / "tools" / "windows_full_install.ps1").read_text(
        encoding="utf-8"
    )
    guardian = (ROOT / "tools" / "windows_guardian.ps1").read_text(
        encoding="utf-8"
    )
    smoke = (ROOT / "tools" / "windows_native_smoke.ps1").read_text(
        encoding="utf-8"
    )
    smoke_flow = smoke.rsplit("\nRead-Version\n", 1)[1]
    guardian_run = smoke.split("function Test-GuardianAndTray", 1)[1].split(
        "function Test-CodexCaptureStatus", 1
    )[0]
    guardian_coverage = guardian.split(
        "function Invoke-ScheduledTaskCoverageChecks", 1
    )[1].split("\ntry {", 1)[0]
    guardian_flow = guardian.split(
        "try {\n    if (-not (Test-Path -LiteralPath $InstallRoot))", 1
    )[1]

    assert "Test-GuardianAndTray" in smoke_flow
    assert "if ($SkipScheduledTaskChecks)" not in smoke_flow
    assert "Test-PathRequired -Name \"windows_guardian_script\"" in guardian_run
    assert "windows_guardian_run" in guardian_run
    assert "guardian_status_content" in guardian_run
    assert '$guardianArgs += "-SkipScheduledTaskChecks"' in guardian_run
    assert "if ($SkipScheduledTaskChecks)" in guardian_coverage
    assert "Invoke-ScheduledTaskCoverageChecks" in guardian_flow
    assert "Update-RecordGuardianEvidence" in guardian_flow
    assert "measurement_status = \"partial\"" in smoke
    assert "full_smoke = $false" in smoke
    assert "measurement_status = \"partial\"" in guardian
    assert "full_health_check = $false" in guardian
    assert "required result fields are missing" in installer
    assert '"not_measured_layers" -notin $payloadFields' in installer
    assert "$lastPayload.not_measured_layers -isnot [System.Array]" in installer
    assert installer.index("not_measured_layers must be an array") < installer.index(
        "$notMeasuredLayers = @($lastPayload.not_measured_layers)"
    )
    assert "complete result has inconsistent measurement scope" in installer
    assert "partial result has inconsistent measurement scope" in installer
    assert "Native Windows smoke partial after $attempt attempt(s)" in installer
    assert "measured checks passed; not measured:" in installer


def test_native_windows_docs_state_s4u_scope_and_limitations():
    docs = (ROOT / "docs" / "wiki" / "Native-Windows-Codex.md").read_text(
        encoding="utf-8"
    )
    normalized_docs = " ".join(docs.split())

    assert "desktop roles and background recovery roles separate" in normalized_docs
    assert "use an S4U principal for the same OS user" in normalized_docs
    assert "no account password is stored" in normalized_docs
    assert "network credentials or access to encrypted files" in normalized_docs
    assert "waits for a completed result of zero" in normalized_docs
    assert "Operational event log" in normalized_docs
    assert "fails closed" in normalized_docs
    assert "reports that task layer as not measured" in normalized_docs
    assert "-RequireBackgroundRecoveryAfterBoot" in normalized_docs
    assert "later than the operating system's" in normalized_docs
    assert "does not reboot or sign out" in normalized_docs
    assert (
        "registered Guardian launcher also carries the same narrow skip flag"
        in normalized_docs
    )
    assert "Both `State` and `Settings.Enabled` are required" in normalized_docs
    assert "short JSON response is also explicitly `partial`" in normalized_docs
    assert "file write time from the current invocation" in normalized_docs
