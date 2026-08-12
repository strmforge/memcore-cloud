#Requires -Version 5.1
param(
    [string]$InstallerPath = "",
    [string]$InstallerText = ""
)

$ErrorActionPreference = "Stop"

function Assert-Equal {
    param([object]$Actual, [object]$Expected, [string]$Name)
    if ($Actual -ne $Expected) {
        throw "$Name expected=$Expected actual=$Actual"
    }
}

function New-RunSample {
    param(
        [string]$State,
        [datetime]$LastRunTime,
        [uint32]$LastTaskResult,
        [bool]$ReadStable = $true,
        [bool]$ObservedRunning = $false
    )
    return [pscustomobject]@{
        ReadStable = $ReadStable
        ObservedRunning = $ObservedRunning
        State = $State
        LastRunTime = $LastRunTime
        LastTaskResult = $LastTaskResult
    }
}

$tokens = $null
$parseErrors = $null
$ast = if ([string]::IsNullOrWhiteSpace($InstallerText)) {
    if ([string]::IsNullOrWhiteSpace($InstallerPath)) {
        $InstallerPath = Join-Path (Split-Path -Parent $PSScriptRoot) "tools\windows_full_install.ps1"
    }
    [System.Management.Automation.Language.Parser]::ParseFile(
        $InstallerPath,
        [ref]$tokens,
        [ref]$parseErrors
    )
} else {
    [System.Management.Automation.Language.Parser]::ParseInput(
        $InstallerText,
        [ref]$tokens,
        [ref]$parseErrors
    )
}
if ($parseErrors.Count -ne 0) {
    throw "installer parse failed: $($parseErrors[0].Message)"
}

$requiredFunctions = @(
    "Get-BackgroundScheduledTaskRunSample",
    "Test-BackgroundScheduledTaskRunSampleEqual",
    "Get-BackgroundScheduledTaskRunDecision",
    "Stop-BackgroundScheduledTaskRun",
    "Assert-BackgroundScheduledTaskRun",
    "Assert-LongRunningBackgroundScheduledTask",
    "Get-WindowsGuardianTaskArguments"
)
$definitions = @{}
foreach ($name in $requiredFunctions) {
    $matches = @($ast.FindAll({
        param($node)
        ($node -is [System.Management.Automation.Language.FunctionDefinitionAst]) -and
            ($node.Name -eq $name)
    }, $true))
    if ($matches.Count -ne 1) { throw "expected one production function named $name" }
    $definitions[$name] = $matches[0].Extent.Text
}

Invoke-Expression $definitions["Get-BackgroundScheduledTaskRunSample"]
Invoke-Expression $definitions["Test-BackgroundScheduledTaskRunSampleEqual"]
Invoke-Expression $definitions["Get-BackgroundScheduledTaskRunDecision"]
Invoke-Expression $definitions["Stop-BackgroundScheduledTaskRun"]
Invoke-Expression $definitions["Assert-LongRunningBackgroundScheduledTask"]
Invoke-Expression $definitions["Get-WindowsGuardianTaskArguments"]

$before = [datetime]"2026-08-04T10:00:00"
$after = $before.AddMinutes(1)

function Get-ScheduledTask {
    [CmdletBinding()]
    param([string]$TaskName)
    return [pscustomobject]@{ State = "Queued" }
}
function Get-ScheduledTaskInfo {
    [CmdletBinding()]
    param([string]$TaskName)
    return [pscustomobject]@{
        LastRunTime = $before
        LastTaskResult = [uint32]0
    }
}
$queuedSample = Get-BackgroundScheduledTaskRunSample -TaskName "MockQueuedTask"
Assert-Equal `
    -Actual $queuedSample.ObservedRunning `
    -Expected $false `
    -Name "baseline_queued_not_observed_running"
Assert-Equal -Actual $queuedSample.ReadStable -Expected $true -Name "queued_read_stable"
Assert-Equal -Actual $queuedSample.State -Expected "Queued" -Name "queued_state_preserved"

$oldSuccess = New-RunSample -State "Ready" -LastRunTime $before -LastTaskResult 0
$newSuccess = New-RunSample -State "Ready" -LastRunTime $after -LastTaskResult 0
$oldFailure = New-RunSample -State "Ready" -LastRunTime $before -LastTaskResult ([uint32]2147943785)
$newFailure = New-RunSample -State "Ready" -LastRunTime $after -LastTaskResult ([uint32]2147943785)
$disabled = New-RunSample -State "Disabled" -LastRunTime $after -LastTaskResult 0
$running = New-RunSample -State "Running" -LastRunTime $after -LastTaskResult 0 -ObservedRunning $true
$unstable = New-RunSample -State "Ready" -LastRunTime $after -LastTaskResult 0 -ReadStable $false

$cases = @(
    [pscustomobject]@{ Name = "same_result_rerun"; Baseline = $false; RunObserved = $true; Previous = $newSuccess; Current = $newSuccess; Expected = "success" },
    [pscustomobject]@{ Name = "preexisting_running_completed"; Baseline = $true; RunObserved = $true; Previous = $oldSuccess; Current = $oldSuccess; Expected = "success" },
    [pscustomobject]@{ Name = "interleaved_snapshot"; Baseline = $false; RunObserved = $true; Previous = $running; Current = $newSuccess; Expected = "wait" },
    [pscustomobject]@{ Name = "unstable_read"; Baseline = $false; RunObserved = $true; Previous = $newSuccess; Current = $unstable; Expected = "wait" },
    [pscustomobject]@{ Name = "delayed_start_old_error"; Baseline = $false; RunObserved = $false; Previous = $oldFailure; Current = $oldFailure; Expected = "wait" },
    [pscustomobject]@{ Name = "disabled"; Baseline = $false; RunObserved = $true; Previous = $disabled; Current = $disabled; Expected = "disabled" },
    [pscustomobject]@{ Name = "old_success"; Baseline = $false; RunObserved = $false; Previous = $oldSuccess; Current = $oldSuccess; Expected = "wait" },
    [pscustomobject]@{ Name = "running"; Baseline = $false; RunObserved = $true; Previous = $running; Current = $running; Expected = "wait" },
    [pscustomobject]@{ Name = "stable_failure"; Baseline = $false; RunObserved = $true; Previous = $newFailure; Current = $newFailure; Expected = "failed" }
)

foreach ($case in $cases) {
    $actual = Get-BackgroundScheduledTaskRunDecision `
        -BeforeRun $before `
        -BaselineRunObserved $case.Baseline `
        -RunObserved $case.RunObserved `
        -PreviousSample $case.Previous `
        -CurrentSample $case.Current
    Assert-Equal -Actual $actual -Expected $case.Expected -Name $case.Name
}

$assertSource = $definitions["Assert-BackgroundScheduledTaskRun"]
$stopCallCount = ([regex]::Matches($assertSource, "Stop-BackgroundScheduledTaskRun")).Count
if ($stopCallCount -lt 2) {
    throw "assertion path must stop the task after start failure and terminal/timeout failure"
}
if ($assertSource -notmatch '\[int\]\$TimeoutSeconds\s*=\s*600') {
    throw "assertion path must cover the registered 10-minute execution budget"
}

$normalGuardianArgs = Get-WindowsGuardianTaskArguments `
    -HiddenGuardian "C:\TimeLibrary\tools\windows_hidden_guardian.vbs" `
    -Root "C:\TimeLibrary" `
    -SkipCodexGuardTaskCheck $false `
    -StartupActivationOnly $false
$preservedGuardianArgs = Get-WindowsGuardianTaskArguments `
    -HiddenGuardian "C:\TimeLibrary\tools\windows_hidden_guardian.vbs" `
    -Root "C:\TimeLibrary" `
    -SkipCodexGuardTaskCheck $true `
    -StartupActivationOnly $false
$logonGuardianArgs = Get-WindowsGuardianTaskArguments `
    -HiddenGuardian "C:\TimeLibrary\tools\windows_hidden_guardian.vbs" `
    -Root "C:\TimeLibrary" `
    -SkipCodexGuardTaskCheck $false `
    -StartupActivationOnly $true
Assert-Equal `
    -Actual ($normalGuardianArgs -match "SkipCodexMcpGuardTaskCheck") `
    -Expected $false `
    -Name "installed_guard_requires_full_check"
Assert-Equal `
    -Actual ($preservedGuardianArgs -match "SkipCodexMcpGuardTaskCheck") `
    -Expected $true `
    -Name "preserved_guard_action_is_partial"
Assert-Equal `
    -Actual ($logonGuardianArgs -match "StartupActivationOnly") `
    -Expected $true `
    -Name "logon_action_defers_background_task_convergence"
Assert-Equal `
    -Actual ($logonGuardianArgs -match "SkipCodexMcpGuardTaskCheck") `
    -Expected $false `
    -Name "logon_action_uses_explicit_activation_mode"

$script:MockTaskStates = New-Object "System.Collections.Generic.Queue[string]"
$script:MockTaskStates.Enqueue("Running")
$script:MockTaskStates.Enqueue("Ready")
$script:MockStopCalls = 0
function Stop-ScheduledTask {
    [CmdletBinding()]
    param([string]$TaskName)
    $script:MockStopCalls += 1
}
function Get-ScheduledTask {
    [CmdletBinding()]
    param([string]$TaskName)
    $state = if ($script:MockTaskStates.Count -gt 0) {
        $script:MockTaskStates.Dequeue()
    } else {
        "Ready"
    }
    return [pscustomobject]@{ State = $state }
}
function Start-Sleep { param([int]$Milliseconds) }

$stopped = Stop-BackgroundScheduledTaskRun -TaskName "MockTask" -TimeoutSeconds 2
Assert-Equal -Actual $stopped -Expected $true -Name "bounded_stop_reaches_terminal"
Assert-Equal -Actual $script:MockStopCalls -Expected 1 -Name "bounded_stop_requested"

$script:MockTaskStates.Clear()
$script:MockTaskStates.Enqueue("Running")
$notStopped = Stop-BackgroundScheduledTaskRun -TaskName "MockTask" -TimeoutSeconds 0
Assert-Equal -Actual $notStopped -Expected $false -Name "bounded_stop_timeout"
Assert-Equal -Actual $script:MockStopCalls -Expected 2 -Name "timeout_stop_requested"

function Get-ScheduledTask {
    [CmdletBinding()]
    param([string]$TaskName)
    throw "mock task query failure"
}
$unconfirmedStop = Stop-BackgroundScheduledTaskRun -TaskName "MockTask" -TimeoutSeconds 1
Assert-Equal -Actual $unconfirmedStop -Expected $false -Name "stop_query_failure_is_unconfirmed"

Invoke-Expression $definitions["Assert-BackgroundScheduledTaskRun"]
$script:SampleCalls = 0
$script:AssertStopCalls = 0
function Get-BackgroundScheduledTaskRunSample {
    param([string]$TaskName)
    $script:SampleCalls += 1
    if ($script:SampleCalls -eq 1) {
        return New-RunSample -State "Ready" -LastRunTime $before -LastTaskResult 0
    }
    throw "mock sample failure"
}
function Start-ScheduledTask {
    [CmdletBinding()]
    param([string]$TaskName)
}
function Stop-BackgroundScheduledTaskRun {
    param([string]$TaskName, [int]$TimeoutSeconds = 30)
    $script:AssertStopCalls += 1
    return $true
}
function Die { param([string]$Message) throw "EXPECTED_DIE|$Message" }
function Info { param([string]$Message) }
try {
    Assert-BackgroundScheduledTaskRun -TaskName "MockTask" -TimeoutSeconds 1
    throw "sampling exception unexpectedly passed"
} catch {
    if ($_.Exception.Message -notmatch '^EXPECTED_DIE\|.*sampling failed after start') { throw }
}
Assert-Equal -Actual $script:AssertStopCalls -Expected 1 -Name "sampling_failure_stops_task"

$script:SampleCalls = 0
$script:AssertStopCalls = 0
function Get-BackgroundScheduledTaskRunSample {
    param([string]$TaskName)
    $script:SampleCalls += 1
    if ($script:SampleCalls -eq 1) {
        return New-RunSample `
            -State "Running" `
            -LastRunTime $before `
            -LastTaskResult 0 `
            -ObservedRunning $true
    }
    return New-RunSample -State "Ready" -LastRunTime $before -LastTaskResult 0
}
function Start-ScheduledTask {
    [CmdletBinding()]
    param([string]$TaskName)
    throw "already running"
}
Assert-BackgroundScheduledTaskRun -TaskName "MockTask" -TimeoutSeconds 1
Assert-Equal -Actual $script:AssertStopCalls -Expected 0 -Name "preexisting_run_is_not_stopped"

$script:LongRunningStartCalls = 0
function Get-ScheduledTask {
    [CmdletBinding()]
    param([string]$TaskName)
    return [pscustomobject]@{ State = "Running" }
}
function Get-ScheduledTaskInfo {
    [CmdletBinding()]
    param([string]$TaskName)
    return [pscustomobject]@{
        LastRunTime = $after
        LastTaskResult = [uint32]0
    }
}
function Get-OwnedInstallProcessRecords {
    param([string]$Root = "")
    return @([pscustomobject]@{ Role = "codex-mcp-guard" })
}
function Start-ScheduledTask {
    [CmdletBinding()]
    param([string]$TaskName)
    $script:LongRunningStartCalls += 1
}
Assert-LongRunningBackgroundScheduledTask `
    -TaskName "MockCodexGuard" `
    -Role "codex-mcp-guard" `
    -TimeoutSeconds 1
Assert-Equal `
    -Actual $script:LongRunningStartCalls `
    -Expected 1 `
    -Name "long_running_guard_demand_start"

$script:LongRunningTaskQueries = 0
$script:LongRunningStartCalls = 0
function Get-ScheduledTask {
    [CmdletBinding()]
    param([string]$TaskName)
    $script:LongRunningTaskQueries += 1
    $state = if ($script:LongRunningTaskQueries -eq 1) { "Ready" } else { "Running" }
    return [pscustomobject]@{ State = $state }
}
function Get-ScheduledTaskInfo {
    [CmdletBinding()]
    param([string]$TaskName)
    return [pscustomobject]@{
        LastRunTime = $after
        LastTaskResult = [uint32]0
    }
}
function Get-OwnedInstallProcessRecords {
    param([string]$Root = "")
    if ($script:LongRunningTaskQueries -ge 2) {
        return @([pscustomobject]@{ Role = "codex-mcp-guard" })
    }
    return @()
}
function Start-ScheduledTask {
    [CmdletBinding()]
    param([string]$TaskName)
    $script:LongRunningStartCalls += 1
}
Assert-LongRunningBackgroundScheduledTask `
    -TaskName "MockCodexGuardStartsProcess" `
    -Role "codex-mcp-guard" `
    -TimeoutSeconds 1
Assert-Equal `
    -Actual $script:LongRunningStartCalls `
    -Expected 1 `
    -Name "long_running_guard_observed_new_process"

$script:LongRunningStopCalls = 0
function Get-ScheduledTask {
    [CmdletBinding()]
    param([string]$TaskName)
    return [pscustomobject]@{ State = "Ready" }
}
function Get-ScheduledTaskInfo {
    [CmdletBinding()]
    param([string]$TaskName)
    return [pscustomobject]@{
        LastRunTime = $before
        LastTaskResult = [uint32]0
    }
}
function Get-OwnedInstallProcessRecords {
    param([string]$Root = "")
    return @()
}
function Start-ScheduledTask {
    [CmdletBinding()]
    param([string]$TaskName)
}
function Stop-BackgroundScheduledTaskRun {
    param([string]$TaskName, [int]$TimeoutSeconds = 30)
    $script:LongRunningStopCalls += 1
    return $true
}
function Die { param([string]$Message) throw "EXPECTED_LONG_RUNNING_DIE|$Message" }
try {
    Assert-LongRunningBackgroundScheduledTask `
        -TaskName "MockCodexGuardTimeout" `
        -Role "codex-mcp-guard" `
        -TimeoutSeconds 0
    throw "long-running timeout unexpectedly passed"
} catch {
    if ($_.Exception.Message -notmatch '^EXPECTED_LONG_RUNNING_DIE\|.*did not reach Running') { throw }
}
Assert-Equal `
    -Actual $script:LongRunningStopCalls `
    -Expected 1 `
    -Name "long_running_timeout_stops_task"

Write-Output "windows_scheduled_task_state_machine: PASS"
