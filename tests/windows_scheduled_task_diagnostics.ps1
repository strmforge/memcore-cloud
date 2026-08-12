#Requires -Version 5.1
param(
    [string]$GuardianPath = "",
    [string]$GuardianText = "",
    [string]$NativeSmokePath = "",
    [string]$NativeSmokeText = ""
)

$ErrorActionPreference = "Stop"

function Assert-True {
    param([bool]$Condition, [string]$Name)
    if (-not $Condition) { throw $Name }
}

function Get-TestScriptAst {
    param([string]$Path, [string]$Text)
    $tokens = $null
    $errors = $null
    $ast = if ([string]::IsNullOrWhiteSpace($Text)) {
        [System.Management.Automation.Language.Parser]::ParseFile(
            $Path,
            [ref]$tokens,
            [ref]$errors
        )
    } else {
        [System.Management.Automation.Language.Parser]::ParseInput(
            $Text,
            [ref]$tokens,
            [ref]$errors
        )
    }
    if ($errors.Count -ne 0) { throw "parse failed: $($errors[0].Message)" }
    return $ast
}

function Get-TestFunctionSource {
    param([object]$Ast, [string]$Name)
    $matches = @($Ast.FindAll({
        param($node)
        ($node -is [System.Management.Automation.Language.FunctionDefinitionAst]) -and
            ($node.Name -eq $Name)
    }, $true))
    if ($matches.Count -ne 1) { throw "expected one production function named $Name" }
    return $matches[0].Extent.Text
}

if ([string]::IsNullOrWhiteSpace($GuardianText) -and [string]::IsNullOrWhiteSpace($GuardianPath)) {
    $GuardianPath = Join-Path (Split-Path -Parent $PSScriptRoot) "tools\windows_guardian.ps1"
}
if ([string]::IsNullOrWhiteSpace($NativeSmokeText) -and [string]::IsNullOrWhiteSpace($NativeSmokePath)) {
    $NativeSmokePath = Join-Path (Split-Path -Parent $PSScriptRoot) "tools\windows_native_smoke.ps1"
}

$guardianAst = Get-TestScriptAst -Path $GuardianPath -Text $GuardianText
$smokeAst = Get-TestScriptAst -Path $NativeSmokePath -Text $NativeSmokeText
Invoke-Expression (Get-TestFunctionSource -Ast $guardianAst -Name "Ensure-CodexMcpGuardTaskHealth")
Invoke-Expression (Get-TestFunctionSource -Ast $guardianAst -Name "Ensure-GuardianHealthTaskSchedule")
Invoke-Expression (Get-TestFunctionSource -Ast $guardianAst -Name "Invoke-ScheduledTaskCoverageChecks")
Invoke-Expression (Get-TestFunctionSource -Ast $guardianAst -Name "ConvertTo-SafeRecoverabilityProbe")
Invoke-Expression (Get-TestFunctionSource -Ast $smokeAst -Name "Test-ScheduledTaskPresent")
Invoke-Expression (Get-TestFunctionSource -Ast $smokeAst -Name "Merge-WindowsGuardianCoverage")

$script:Checks = @()
$script:NotMeasured = @()
function Add-Check {
    param([string]$Name, [bool]$Ok, [string]$Detail = "", [object]$Data = $null)
    $script:Checks += [pscustomobject]@{ Name = $Name; Ok = $Ok; Detail = $Detail }
}
function Add-NotMeasuredCheck {
    param([string]$Name, [string]$Detail)
    $script:NotMeasured += [pscustomobject]@{ Name = $Name; Detail = $Detail }
    if ($null -ne $script:Report) {
        $script:Report.measurement_status = "partial"
        $script:Report.full_smoke = $false
        if ($Name -notin @($script:Report.not_measured_layers)) {
            $script:Report.not_measured_layers += $Name
        }
    }
}
function Get-ScheduledTask {
    [CmdletBinding()]
    param([string]$TaskName)
    return $null
}

Ensure-CodexMcpGuardTaskHealth
Assert-True -Condition ($script:NotMeasured.Count -eq 1) -Name "missing guard must emit one not_measured check"
Assert-True -Condition ($script:NotMeasured[0].Name -eq "codex_mcp_guard_task") -Name "missing guard check name"
Assert-True -Condition ($script:NotMeasured[0].Detail -match "applicability") -Name "missing guard applicability detail"
Assert-True -Condition ($script:Checks.Count -eq 0) -Name "missing guard must not emit ok=true"

$probeFields = @(
    "candidate_count", "candidate_limit", "per_file_byte_limit", "round_byte_limit",
    "targeted_scan_count", "cache_hit_count", "canonical_cache_hit_count",
    "measured_count", "not_measured_count", "bytes_read", "budget_exhausted_count",
    "one_sided_count", "non_conversation_count"
)
$validProbe = [ordered]@{ canonical_cache_status = "sqlite_open_failed:private-detail" }
foreach ($field in $probeFields) { $validProbe[$field] = 0 }
$safeProbe = ConvertTo-SafeRecoverabilityProbe -Probe ([pscustomobject]$validProbe)
Assert-True -Condition ($safeProbe.schema -eq "recoverability_probe.v1") -Name "recoverability probe schema"
Assert-True -Condition ($safeProbe.canonical_cache_status -eq "unavailable") -Name "recoverability cache detail redacted"
$stringProbe = [ordered]@{}
foreach ($key in $validProbe.Keys) { $stringProbe[$key] = $validProbe[$key] }
$stringProbe["bytes_read"] = "4096"
Assert-True `
    -Condition ($null -eq (ConvertTo-SafeRecoverabilityProbe -Probe ([pscustomobject]$stringProbe))) `
    -Name "recoverability string counter must fail closed"
$boolProbe = [ordered]@{}
foreach ($key in $validProbe.Keys) { $boolProbe[$key] = $validProbe[$key] }
$boolProbe["bytes_read"] = $true
Assert-True `
    -Condition ($null -eq (ConvertTo-SafeRecoverabilityProbe -Probe ([pscustomobject]$boolProbe))) `
    -Name "recoverability boolean counter must fail closed"

$script:Checks = @()
function Get-ScheduledTask {
    [CmdletBinding()]
    param([string]$TaskName)
    return [pscustomobject]@{
        State = "Disabled"
        Settings = [pscustomobject]@{ Enabled = $true }
    }
}
Ensure-GuardianHealthTaskSchedule
$disabledGuardian = @($script:Checks | Where-Object { $_.Name -eq "guardian_health_enabled" })
Assert-True -Condition ($disabledGuardian.Count -eq 1) -Name "disabled Guardian check missing"
Assert-True -Condition (-not $disabledGuardian[0].Ok) -Name "disabled Guardian must fail"

$script:Checks = @()
function Get-ScheduledTask {
    [CmdletBinding()]
    param([string]$TaskName)
    return [pscustomobject]@{
        State = "Running"
        Settings = [pscustomobject]@{ Enabled = $false }
    }
}
Ensure-GuardianHealthTaskSchedule
$settingsDisabledGuardian = @($script:Checks | Where-Object { $_.Name -eq "guardian_health_enabled" })
Assert-True -Condition ($settingsDisabledGuardian.Count -eq 1) -Name "settings-disabled Guardian check missing"
Assert-True -Condition (-not $settingsDisabledGuardian[0].Ok) -Name "running but settings-disabled Guardian must fail"

$script:HealthTaskCalls = 0
$script:GuardTaskCalls = 0
$script:NotMeasured = @()
function Ensure-GuardianHealthTaskSchedule { $script:HealthTaskCalls += 1 }
function Ensure-CodexMcpGuardTaskHealth { $script:GuardTaskCalls += 1 }

$StartupActivationOnly = $true
$SkipScheduledTaskChecks = $false
$SkipCodexMcpGuardTaskCheck = $false
Invoke-ScheduledTaskCoverageChecks
Assert-True -Condition ($script:HealthTaskCalls -eq 0) -Name "startup activation must defer GuardianHealth convergence"
Assert-True -Condition ($script:GuardTaskCalls -eq 0) -Name "startup activation must defer Codex guard convergence"
Assert-True -Condition ($script:NotMeasured.Count -eq 1) -Name "startup activation must expose one not_measured layer"
Assert-True -Condition ($script:NotMeasured[0].Name -eq "scheduled_task_startup_convergence") -Name "startup activation layer name"

$StartupActivationOnly = $false
$script:NotMeasured = @()
Invoke-ScheduledTaskCoverageChecks
Assert-True -Condition ($script:HealthTaskCalls -eq 1) -Name "periodic coverage must check GuardianHealth"
Assert-True -Condition ($script:GuardTaskCalls -eq 1) -Name "periodic coverage must check Codex guard"
Assert-True -Condition ($script:NotMeasured.Count -eq 0) -Name "periodic coverage must remain complete"

$script:LastFailure = ""
function Fail-Smoke {
    param([string]$Name, [string]$Detail)
    $script:LastFailure = "$Name|$Detail"
    throw "EXPECTED_SMOKE_FAILURE"
}
function Add-Check {
    param([string]$Name, [bool]$Ok, [string]$Detail = "", [object]$Data = $null)
}
$script:Report = [ordered]@{
    measurement_status = "complete"
    full_smoke = $true
    not_measured_layers = @()
    checks = @()
}
$partialPayload = [pscustomobject]@{
    ok = $true
    measurement_status = "partial"
    full_health_check = $false
    not_measured_layers = @("guardian_concurrent_run")
    generated_at = "2026-08-04T10:00:00Z"
}

$script:LastFailure = ""
$invalidGeneratedAtPayload = [pscustomobject]@{
    ok = $true
    measurement_status = "complete"
    full_health_check = $true
    not_measured_layers = @()
    generated_at = [datetime]"2026-08-04T10:00:00Z"
}
try {
    Merge-WindowsGuardianCoverage `
        -Payload $invalidGeneratedAtPayload `
        -Source "invalid_generated_at_type"
    throw "generated_at non-string unexpectedly passed coverage validation"
} catch {
    if ($_.Exception.Message -ne "EXPECTED_SMOKE_FAILURE") { throw }
}
Assert-True `
    -Condition ($script:LastFailure -match "generated_at must be a non-empty string") `
    -Name "generated_at non-string must fail"

$script:LastFailure = ""
$coverage = Merge-WindowsGuardianCoverage -Payload $partialPayload -Source "mock_nested"
Assert-True -Condition ($coverage -eq "partial") -Name "nested partial coverage result"
Assert-True -Condition (-not $script:Report.full_smoke) -Name "nested partial must clear full_smoke"
Assert-True `
    -Condition ("windows_guardian:guardian_concurrent_run" -in @($script:Report.not_measured_layers)) `
    -Name "nested partial layer must propagate"

$script:LastFailure = ""
try {
    Merge-WindowsGuardianCoverage `
        -Payload ([pscustomobject]@{ ok = $true; skipped = $true; reason = "guardian_already_running" }) `
        -Source "legacy_skip"
    throw "legacy Guardian skip unexpectedly passed coverage validation"
} catch {
    if ($_.Exception.Message -ne "EXPECTED_SMOKE_FAILURE") { throw }
}
Assert-True -Condition ($script:LastFailure -match "payload is missing") -Name "legacy skip without coverage must fail"

function Get-ScheduledTask {
    [CmdletBinding()]
    param([string]$TaskName)
    return $null
}
try {
    Test-ScheduledTaskPresent -Name "MemcoreCloudCodexMcpGuard" -ExpectedLogonType "S4U"
    throw "missing required Codex guard unexpectedly passed"
} catch {
    if ($_.Exception.Message -ne "EXPECTED_SMOKE_FAILURE") { throw }
}
Assert-True -Condition ($script:LastFailure -match "scheduled_task_MemcoreCloudCodexMcpGuard\|missing") -Name "normal smoke must fail on missing guard"

$task = [pscustomobject]@{
    State = "Ready"
    Settings = [pscustomobject]@{ Enabled = $true }
    Principal = [pscustomobject]@{ LogonType = "S4U" }
    Actions = @([pscustomobject]@{
        Execute = "C:\Windows\System32\wscript.exe"
        Arguments = "C:\TimeLibrary\tools\windows_hidden_guardian.vbs"
    })
}
function Get-ScheduledTask {
    [CmdletBinding()]
    param([string]$TaskName)
    return $task
}
function Get-ScheduledTaskInfo {
    [CmdletBinding()]
    param([string]$TaskName)
    return [pscustomobject]@{
        LastRunTime = [datetime]"2026-08-04T09:00:00"
        LastTaskResult = [uint32]0
    }
}
function Get-CimInstance {
    [CmdletBinding()]
    param([string]$ClassName)
    return [pscustomobject]@{ LastBootUpTime = [datetime]"2026-08-04T10:00:00" }
}
$script:LastFailure = ""
try {
    Test-ScheduledTaskPresent `
        -Name "MemcoreCloudGuardianHealth" `
        -ExpectedLogonType "S4U" `
        -RequireRunAfterBoot
    throw "pre-boot success unexpectedly passed post-boot acceptance"
} catch {
    if ($_.Exception.Message -ne "EXPECTED_SMOKE_FAILURE") { throw }
}
Assert-True -Condition ($script:LastFailure -match "has not run after this boot") -Name "pre-boot success must fail post-boot acceptance"

$task.State = "Disabled"
$script:LastFailure = ""
try {
    Test-ScheduledTaskPresent -Name "MemcoreCloudGuardianHealth" -ExpectedLogonType "S4U"
    throw "disabled Guardian task unexpectedly passed"
} catch {
    if ($_.Exception.Message -ne "EXPECTED_SMOKE_FAILURE") { throw }
}
Assert-True -Condition ($script:LastFailure -match "disabled state=Disabled") -Name "disabled native task must fail"

$task.State = "Running"
$task.Settings.Enabled = $false
$script:LastFailure = ""
try {
    Test-ScheduledTaskPresent -Name "MemcoreCloudGuardianHealth" -ExpectedLogonType "S4U"
    throw "running but settings-disabled Guardian task unexpectedly passed"
} catch {
    if ($_.Exception.Message -ne "EXPECTED_SMOKE_FAILURE") { throw }
}
Assert-True -Condition ($script:LastFailure -match "settings_enabled=False") -Name "settings-disabled native task must fail"

$guardianSource = if ([string]::IsNullOrWhiteSpace($GuardianText)) {
    Get-Content -LiteralPath $GuardianPath -Raw -Encoding UTF8
} else { $GuardianText }
$smokeSource = if ([string]::IsNullOrWhiteSpace($NativeSmokeText)) {
    Get-Content -LiteralPath $NativeSmokePath -Raw -Encoding UTF8
} else { $NativeSmokeText }
Assert-True `
    -Condition ($guardianSource -match 'if \(\$SkipCodexMcpGuardTaskCheck\)[\s\S]+Add-NotMeasuredCheck[\s\S]+Ensure-CodexMcpGuardTaskHealth') `
    -Name "Guardian explicit skip must remain not_measured"
Assert-True `
    -Condition ($smokeSource -match 'if \(\$SkipCodexGuardTaskCheck\)[\s\S]+Add-NotMeasuredCheck[\s\S]+MemcoreCloudCodexMcpGuard') `
    -Name "native smoke explicit skip must remain not_measured"

Write-Output "windows_scheduled_task_diagnostics: PASS"
