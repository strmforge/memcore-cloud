#Requires -Version 5.1
param(
    [string]$InstallRoot = "$env:LOCALAPPDATA\time-library",
    [switch]$StartWatcher,
    [switch]$Backfill,
    [switch]$NoStatusWrite,
    [switch]$Json,
    [switch]$Quiet,
    [switch]$StartupActivationOnly,
    [switch]$SkipScheduledTaskChecks,
    [switch]$SkipCodexMcpGuardTaskCheck,
    [switch]$RequireBackgroundRecoveryAfterBoot
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = [Console]::OutputEncoding

$RuntimeDir = Join-Path $InstallRoot "runtime"
$LogDir = Join-Path $InstallRoot "logs"
$StatusPath = Join-Path $RuntimeDir "guardian-status.json"
$GuardianLog = Join-Path $LogDir "guardian.out.log"
$GuardianErr = Join-Path $LogDir "guardian.err.log"
$GuardianLogMaxBytes = 5MB
$GuardianLogRetention = 2
$RecordGuardianCacheMaxAgeSeconds = 1800
$WatcherPidStartToleranceSeconds = 120
$ServicePidStartToleranceSeconds = 120
$HermesHome = if ($env:HERMES_HOME) { $env:HERMES_HOME } else { Join-Path $env:LOCALAPPDATA "hermes" }
$DialogEntryToken = if ($env:MEMCORE_DIALOG_ENTRY_TOKEN) { $env:MEMCORE_DIALOG_ENTRY_TOKEN } else { "" }
$FrontDoorPort = 9850
$InternalP3Port = 19300
$InternalP4Port = 19400
$InternalP6Port = 19500
$InternalRawPort = 19510
$InternalDialogPort = 19600

New-Item -ItemType Directory -Force -Path $RuntimeDir | Out-Null
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$GuardianLockPath = Join-Path $RuntimeDir "guardian.lock"
try {
    $script:GuardianLockStream = [System.IO.File]::Open(
        $GuardianLockPath,
        [System.IO.FileMode]::OpenOrCreate,
        [System.IO.FileAccess]::ReadWrite,
        [System.IO.FileShare]::None
    )
    $lockText = "pid=$PID started_at=$((Get-Date).ToUniversalTime().ToString('o'))`n"
    $lockBytes = [System.Text.Encoding]::UTF8.GetBytes($lockText)
    $script:GuardianLockStream.SetLength(0)
    $script:GuardianLockStream.Write($lockBytes, 0, $lockBytes.Length)
    $script:GuardianLockStream.Flush()
} catch [System.IO.IOException] {
    if ($Json) {
        [ordered]@{
            ok = $true
            tool = "windows_guardian"
            skipped = $true
            reason = "guardian_already_running"
            install_root = $InstallRoot
            generated_at = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
            measurement_status = "partial"
            full_health_check = $false
            background_recovery_after_boot_required = [bool]$RequireBackgroundRecoveryAfterBoot
            not_measured_layers = @("guardian_concurrent_run")
            checks = @()
        } | ConvertTo-Json -Depth 4
    }
    exit 0
}

function Now-Iso {
    return (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
}

function New-Report {
    return [ordered]@{
        ok = $true
        tool = "windows_guardian"
        install_root = $InstallRoot
        generated_at = Now-Iso
        start_watcher_requested = [bool]$StartWatcher
        backfill_requested = [bool]$Backfill
        measurement_status = "complete"
        full_health_check = $true
        background_recovery_after_boot_required = [bool]$RequireBackgroundRecoveryAfterBoot
        startup_activation_only = [bool]$StartupActivationOnly
        not_measured_layers = @()
        checks = @()
    }
}

$Report = New-Report
$script:RecordGuardianStatusAttempted = $false

function Add-Check {
    param(
        [string]$Name,
        [bool]$Ok,
        [string]$Detail = "",
        [object]$Data = $null
    )
    $entry = [ordered]@{
        name = $Name
        ok = $Ok
        detail = $Detail
    }
    if ($null -ne $Data) { $entry["data"] = $Data }
    $script:Report.checks += $entry
    if (-not $Ok) { $script:Report.ok = $false }
    if (-not $Quiet -and -not $Json) {
        $mark = if ($Ok) { "ok" } else { "fail" }
        Write-Host ("[{0}] {1} {2}" -f $mark, $Name, $Detail)
    }
}

function Add-NotMeasuredCheck {
    param(
        [string]$Name,
        [string]$Detail
    )
    $script:Report.measurement_status = "partial"
    $script:Report.full_health_check = $false
    if ($Name -notin @($script:Report.not_measured_layers)) {
        $script:Report.not_measured_layers += $Name
    }
    $script:Report.checks += [ordered]@{
        name = $Name
        ok = $null
        measurement_status = "not_measured"
        detail = $Detail
    }
    if (-not $Quiet -and -not $Json) {
        Write-Host ("[not_measured] {0} {1}" -f $Name, $Detail)
    }
}

function Ensure-GuardianHealthTaskSchedule {
    $taskName = "MemcoreCloudGuardianHealth"
    try {
        $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
        if (-not $task) {
            Add-Check -Name "guardian_health_schedule" -Ok $false -Detail "task is missing"
            return
        }
        $settingsEnabled = ($null -ne $task.Settings) -and [bool]$task.Settings.Enabled
        $enabled = ([string]$task.State -ne "Disabled") -and $settingsEnabled
        Add-Check `
            -Name "guardian_health_enabled" `
            -Ok $enabled `
            -Detail ("state=" + [string]$task.State + "; settings_enabled=" + [string]$settingsEnabled)
        if (-not $enabled) { return }
        $principalOk = ([string]$task.Principal.LogonType -eq "S4U")
        Add-Check `
            -Name "guardian_health_principal" `
            -Ok $principalOk `
            -Detail ("principal_logon_type=" + [string]$task.Principal.LogonType)
        $intervals = @($task.Triggers | ForEach-Object { [string]$_.Repetition.Interval })
        if ($intervals -contains "PT5M") {
            Add-Check -Name "guardian_health_schedule" -Ok $true -Detail "interval=PT5M"
        } else {
            $trigger = New-ScheduledTaskTrigger `
                -Once `
                -At (Get-Date).AddMinutes(5) `
                -RepetitionInterval (New-TimeSpan -Minutes 5) `
                -RepetitionDuration (New-TimeSpan -Days 3650)
            Set-ScheduledTask -TaskName $taskName -Trigger $trigger | Out-Null
            Add-Check -Name "guardian_health_schedule" -Ok $true -Detail "migrated interval to PT5M"
        }

        $task = Get-ScheduledTask -TaskName $taskName -ErrorAction Stop
        $info = Get-ScheduledTaskInfo -TaskName $taskName -ErrorAction Stop
        $lastRun = [datetime]$info.LastRunTime
        $lastResult = [uint32]$info.LastTaskResult
        $running = ([string]$task.State -eq "Running")
        $recent = ($lastRun -gt (Get-Date).AddMinutes(-20))
        $postBoot = $true
        $bootDetail = ""
        if ($RequireBackgroundRecoveryAfterBoot) {
            $lastBoot = [datetime](Get-CimInstance Win32_OperatingSystem -ErrorAction Stop).LastBootUpTime
            $postBoot = ($lastRun -gt $lastBoot)
            $bootDetail = "; last_boot=" + $lastBoot.ToString("o") + "; post_boot=" + [string]$postBoot
        }
        $executionOk = ($recent -and $postBoot -and ($running -or ($lastResult -eq 0)))
        Add-Check `
            -Name "guardian_health_execution" `
            -Ok $executionOk `
            -Detail ("state=" + [string]$task.State + "; last_run=" + $lastRun.ToString("o") + "; last_result=" + ("{0} (0x{1:X8})" -f [uint64]$lastResult, [uint64]$lastResult) + "; recent_20m=" + [string]$recent + $bootDetail)
    } catch {
        Add-Check -Name "guardian_health_schedule" -Ok $false -Detail ("validation failed: " + $_.Exception.Message)
    }
}

function Test-CodexMcpGuardTaskOwned {
    param([object]$Task)
    if ($null -eq $Task) { return $false }
    $actions = @($Task.Actions)
    if ($actions.Count -ne 1) { return $false }

    $python = Get-VenvPython
    if (-not $python) { return $false }
    $guard = Join-Path $InstallRoot "tools\codex_mcp_config_guard.py"
    $execute = Normalize-PathText -Text ([string]$actions[0].Execute)
    $arguments = Normalize-PathText -Text ([string]$actions[0].Arguments)
    if ($execute -ne (Normalize-PathText -Text $python)) { return $false }
    if (-not $arguments.Contains((Normalize-PathText -Text $guard))) { return $false }
    if (-not $arguments.Contains((Normalize-PathText -Text $InstallRoot))) { return $false }
    return ([string]$actions[0].Arguments -match '(?i)(?:^|\s)--watch(?:\s|$)')
}

function Get-CodexMcpGuardProcesses {
    $guard = Join-Path $InstallRoot "tools\codex_mcp_config_guard.py"
    $processes = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)
    return @($processes | Where-Object {
        $commandLine = [string]$_.CommandLine
        (-not [string]::IsNullOrWhiteSpace($commandLine)) -and
            (Test-CommandLineHasInstallRoot -CommandLine $commandLine) -and
            ($commandLine -match ([regex]::Escape($guard))) -and
            ($commandLine -match '(?i)(?:^|\s)--watch(?:\s|$)')
    })
}

function Ensure-CodexMcpGuardTaskHealth {
    $taskName = "MemcoreCloudCodexMcpGuard"
    $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if (-not $task) {
        Add-NotMeasuredCheck `
            -Name "codex_mcp_guard_task" `
            -Detail "task is missing; Codex guard applicability and background recovery are not measured"
        return
    }
    if (-not (Test-CodexMcpGuardTaskOwned -Task $task)) {
        Add-Check -Name "codex_mcp_guard_task" -Ok $false -Detail "task action does not match this install root"
        return
    }

    $principalOk = ([string]$task.Principal.LogonType -eq "S4U")
    $scheduleChanged = $false
    $scheduleOk = $true
    $intervals = @($task.Triggers | ForEach-Object { [string]$_.Repetition.Interval })
    if ($intervals -notcontains "PT5M") {
        try {
            $periodicTrigger = New-ScheduledTaskTrigger `
                -Once `
                -At (Get-Date).AddMinutes(1) `
                -RepetitionInterval (New-TimeSpan -Minutes 5) `
                -RepetitionDuration (New-TimeSpan -Days 3650)
            $triggers = @($task.Triggers) + @($periodicTrigger)
            Set-ScheduledTask -TaskName $taskName -Trigger $triggers | Out-Null
            $scheduleChanged = $true
            $task = Get-ScheduledTask -TaskName $taskName -ErrorAction Stop
        } catch {
            $scheduleOk = $false
        }
    }

    $reconcileAttempted = $false
    $reconcileOk = $false
    $guardProcesses = @(Get-CodexMcpGuardProcesses)
    if ([string]$task.State -ne "Running" -or $guardProcesses.Count -eq 0) {
        try {
            Start-ScheduledTask -TaskName $taskName -ErrorAction Stop
            for ($attempt = 0; $attempt -lt 20; $attempt++) {
                Start-Sleep -Milliseconds 250
                $task = Get-ScheduledTask -TaskName $taskName -ErrorAction Stop
                $guardProcesses = @(Get-CodexMcpGuardProcesses)
                if ([string]$task.State -eq "Running" -and $guardProcesses.Count -gt 0) { break }
            }
        } catch { }
    }

    if ($guardProcesses.Count -eq 0) {
        $reconcileAttempted = $true
        # A user-interactive task can be terminated with its session.  The
        # health task is already a durable scheduled entry, so reconcile once
        # here instead of making config recovery depend on a long-lived session.
        $python = Get-VenvPython
        $guard = Join-Path $InstallRoot "tools\codex_mcp_config_guard.py"
        $codexHome = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE ".codex" }
        $config = Join-Path $codexHome "config.toml"
        if ($python -and (Test-Path -LiteralPath $config) -and (Test-Path -LiteralPath $guard)) {
            try {
                & $python $guard `
                    --once `
                    --config $config `
                    --install-root $InstallRoot `
                    --python-executable $python *> $null
                $reconcileOk = ($LASTEXITCODE -eq 0)
            } catch { $reconcileOk = $false }
        }
    }

    if ($reconcileAttempted) {
        for ($attempt = 0; $attempt -lt 40; $attempt++) {
            Start-Sleep -Milliseconds 250
            $task = Get-ScheduledTask -TaskName $taskName -ErrorAction Stop
            $guardProcesses = @(Get-CodexMcpGuardProcesses)
            if ([string]$task.State -eq "Running" -and $guardProcesses.Count -gt 0) { break }
        }
    }

    if ($reconcileAttempted) {
        Add-Check `
            -Name "codex_mcp_guard_reconcile" `
            -Ok $reconcileOk `
            -Detail ("one_shot_reconcile=" + [string]$reconcileOk + "; this repairs current config once but does not prove the scheduled watcher")
    }

    $running = ([string]$task.State -eq "Running")
    $settingsEnabled = ($null -ne $task.Settings) -and [bool]$task.Settings.Enabled
    $enabled = ([string]$task.State -ne "Disabled") -and $settingsEnabled
    $postBoot = $true
    $bootDetail = ""
    if ($RequireBackgroundRecoveryAfterBoot) {
        $info = Get-ScheduledTaskInfo -TaskName $taskName -ErrorAction Stop
        $lastRun = [datetime]$info.LastRunTime
        $lastBoot = [datetime](Get-CimInstance Win32_OperatingSystem -ErrorAction Stop).LastBootUpTime
        $postBoot = ($lastRun -gt $lastBoot)
        $bootDetail = "; last_run=" + $lastRun.ToString("o") + "; last_boot=" + $lastBoot.ToString("o") + "; post_boot=" + [string]$postBoot
    }
    $schedule = if ($scheduleChanged) { "periodic recovery trigger installed" } else { "periodic recovery trigger present" }
    Add-Check `
        -Name "codex_mcp_guard_task" `
        -Ok ($scheduleOk -and $principalOk -and $enabled -and $postBoot -and $running -and ($guardProcesses.Count -gt 0)) `
        -Detail ($schedule + "; principal_logon_type=" + [string]$task.Principal.LogonType + "; state=" + [string]$task.State + "; settings_enabled=" + [string]$settingsEnabled + "; guard_processes=" + [string]$guardProcesses.Count + "; one_shot_reconcile=" + [string]$reconcileOk + $bootDetail)
}

function ConvertFrom-JsonOutput {
    param([string]$Text)
    $trimmed = $Text.Trim()
    if ([string]::IsNullOrWhiteSpace($trimmed)) {
        throw "empty JSON output"
    }
    try {
        return $trimmed | ConvertFrom-Json
    } catch { }

    $start = -1
    $depth = 0
    $inString = $false
    $escaped = $false
    for ($i = 0; $i -lt $Text.Length; $i++) {
        $ch = $Text[$i]
        if ($start -lt 0) {
            if ($ch -eq "{") {
                $start = $i
                $depth = 1
            }
            continue
        }
        if ($inString) {
            if ($escaped) {
                $escaped = $false
            } elseif ($ch -eq "\") {
                $escaped = $true
            } elseif ($ch -eq '"') {
                $inString = $false
            }
            continue
        }
        if ($ch -eq '"') {
            $inString = $true
        } elseif ($ch -eq "{") {
            $depth += 1
        } elseif ($ch -eq "}") {
            $depth -= 1
            if ($depth -eq 0) {
                $candidate = $Text.Substring($start, $i - $start + 1)
                return ($candidate | ConvertFrom-Json)
            }
        }
    }
    throw "no balanced JSON object found"
}

function Write-Utf8NoBom {
    param([string]$Path, [string]$Text)
    $enc = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Text, $enc)
}

function Invoke-BoundedLogRotation {
    param(
        [string]$Path,
        [long]$MaxBytes = $GuardianLogMaxBytes,
        [int]$Retention = $GuardianLogRetention
    )
    $result = [ordered]@{
        ok = $true
        rotated = $false
        path = $Path
        archived_bytes = 0
        retention = $Retention
        error = ""
    }
    if (-not (Test-Path -LiteralPath $Path)) { return [pscustomobject]$result }
    try {
        $item = Get-Item -LiteralPath $Path
        if ([int64]$item.Length -lt $MaxBytes) { return [pscustomobject]$result }

        $result.archived_bytes = [int64]$item.Length
        for ($generation = $Retention; $generation -ge 2; $generation--) {
            $older = "$Path.$($generation - 1).gz"
            $newer = "$Path.$generation.gz"
            if (Test-Path -LiteralPath $newer) {
                Remove-Item -LiteralPath $newer -Force
            }
            if (Test-Path -LiteralPath $older) {
                Move-Item -LiteralPath $older -Destination $newer -Force
            }
        }

        $archive = "$Path.1.gz"
        $temporary = "$archive.$PID.tmp"
        if (Test-Path -LiteralPath $temporary) {
            Remove-Item -LiteralPath $temporary -Force
        }
        $inputStream = $null
        $outputStream = $null
        $gzipStream = $null
        try {
            $inputStream = [System.IO.File]::Open(
                $Path,
                [System.IO.FileMode]::Open,
                [System.IO.FileAccess]::Read,
                [System.IO.FileShare]::Read
            )
            $outputStream = [System.IO.File]::Open(
                $temporary,
                [System.IO.FileMode]::CreateNew,
                [System.IO.FileAccess]::Write,
                [System.IO.FileShare]::None
            )
            $gzipStream = [System.IO.Compression.GZipStream]::new(
                $outputStream,
                [System.IO.Compression.CompressionMode]::Compress,
                $true
            )
            $inputStream.CopyTo($gzipStream)
        } finally {
            if ($gzipStream) { $gzipStream.Dispose() }
            if ($outputStream) { $outputStream.Dispose() }
            if ($inputStream) { $inputStream.Dispose() }
        }
        if (Test-Path -LiteralPath $archive) {
            Remove-Item -LiteralPath $archive -Force
        }
        Move-Item -LiteralPath $temporary -Destination $archive
        Write-Utf8NoBom -Path $Path -Text ""
        $result.rotated = $true
    } catch {
        if ($temporary -and (Test-Path -LiteralPath $temporary)) {
            Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
        }
        $result.ok = $false
        $result.error = $_.Exception.Message
    }
    return [pscustomobject]$result
}

function Add-LogRotationResult {
    param(
        [string]$Name,
        [object]$Result
    )
    if (-not $Result.ok) {
        Add-Check -Name ($Name + "_log_rotation") -Ok $false -Detail $Result.error
    } elseif ($Result.rotated) {
        Add-Check `
            -Name ($Name + "_log_rotation") `
            -Ok $true `
            -Detail ("archived " + [string]$Result.archived_bytes + " bytes") `
            -Data ([ordered]@{
                archived_bytes = [int64]$Result.archived_bytes
                retention = [int]$Result.retention
                compressed = $true
            })
    }
}

function Get-FileSha256 {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return "" }
    try {
        return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    } catch {
        return ""
    }
}

function Get-ServiceHashPath {
    param([string]$Name)
    return (Join-Path $RuntimeDir "$Name.source.sha256")
}

function Get-StoredServiceHash {
    param([string]$Name)
    $path = Get-ServiceHashPath -Name $Name
    if (-not (Test-Path -LiteralPath $path)) { return "" }
    try {
        return (Get-Content -LiteralPath $path -Raw -Encoding UTF8).Trim().ToLowerInvariant()
    } catch {
        return ""
    }
}

function Set-StoredServiceHash {
    param([string]$Name, [string]$Hash)
    if ([string]::IsNullOrWhiteSpace($Hash)) { return }
    Write-Utf8NoBom -Path (Get-ServiceHashPath -Name $Name) -Text ($Hash + "`n")
}

function Get-DialogEntryHost {
    $cfgPath = Join-Path $InstallRoot "config\memcore.json"
    if (-not (Test-Path -LiteralPath $cfgPath)) { return "127.0.0.1" }
    try {
        $cfg = Get-Content -LiteralPath $cfgPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($cfg.services -and $cfg.services.dialog_entry_host) {
            $dialogHost = [string]$cfg.services.dialog_entry_host
            if (-not [string]::IsNullOrWhiteSpace($dialogHost)) { return $dialogHost.Trim() }
        }
    } catch { }
    return "127.0.0.1"
}

function Get-DialogEntryEndpointUrl {
    $cfgPath = Join-Path $InstallRoot "config\memcore.json"
    if (-not (Test-Path -LiteralPath $cfgPath)) { return "" }
    try {
        $cfg = Get-Content -LiteralPath $cfgPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($cfg.services -and $cfg.services.dialog_entry_endpoint_url) {
            $url = [string]$cfg.services.dialog_entry_endpoint_url
            if (-not [string]::IsNullOrWhiteSpace($url)) { return $url.Trim() }
        }
    } catch { }
    return ""
}

function Test-DialogEntryNeedsToken {
    $dialogHost = Get-DialogEntryHost
    if (($dialogHost -ne "127.0.0.1") -and ($dialogHost -ne "localhost") -and ($dialogHost -ne "::1")) {
        return $true
    }
    $endpoint = Get-DialogEntryEndpointUrl
    if ([string]::IsNullOrWhiteSpace($endpoint)) { return $false }
    return ($endpoint -notmatch "127\.0\.0\.1|localhost|\[::1\]")
}

function New-DialogEntryTokenValue {
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $bytes = New-Object byte[] 32
    try {
        $rng.GetBytes($bytes)
    } finally {
        $rng.Dispose()
    }
    return ([Convert]::ToBase64String($bytes).TrimEnd("=") -replace "\+", "-" -replace "/", "_")
}

function Ensure-DialogEntryToken {
    if (-not (Test-DialogEntryNeedsToken)) { return $script:DialogEntryToken }
    $tokenPath = Join-Path $RuntimeDir "dialog_entry_token"
    if ([string]::IsNullOrWhiteSpace($script:DialogEntryToken) -and (Test-Path -LiteralPath $tokenPath)) {
        $script:DialogEntryToken = (Get-Content -LiteralPath $tokenPath -Raw -Encoding UTF8).Trim()
    }
    if ([string]::IsNullOrWhiteSpace($script:DialogEntryToken)) {
        $script:DialogEntryToken = New-DialogEntryTokenValue
    }
    Write-Utf8NoBom -Path $tokenPath -Text ($script:DialogEntryToken + "`n")
    Add-Check -Name "dialog_entry_token_file" -Ok $true -Detail "present"
    return $script:DialogEntryToken
}

function Test-ServiceSourceChanged {
    param([string]$Name, [string]$Path)
    $current = Get-FileSha256 -Path $Path
    if ([string]::IsNullOrWhiteSpace($current)) { return $false }
    $stored = Get-StoredServiceHash -Name $Name
    if ([string]::IsNullOrWhiteSpace($stored)) { return $true }
    return ($stored -ne $current)
}

function Write-GuardianStatus {
    if (-not $NoStatusWrite) {
        Add-LogRotationResult `
            -Name "guardian_out" `
            -Result (Invoke-BoundedLogRotation -Path $GuardianLog)
        Add-LogRotationResult `
            -Name "guardian_err" `
            -Result (Invoke-BoundedLogRotation -Path $GuardianErr)
    }
    $jsonText = $script:Report | ConvertTo-Json -Depth 12
    if (-not $NoStatusWrite) {
        $shouldWriteStatus = $true
        if (Test-Path -LiteralPath $StatusPath) {
            try {
                $existing = Get-Content -LiteralPath $StatusPath -Raw -Encoding UTF8 | ConvertFrom-Json
                if ($existing.generated_at -and ([string]$existing.generated_at -gt [string]$script:Report.generated_at)) {
                    $shouldWriteStatus = $false
                }
            } catch { }
        }
        if ($shouldWriteStatus) {
            Set-Content -LiteralPath $StatusPath -Value ($jsonText + "`n") -Encoding UTF8
        }
        Add-Content -LiteralPath $GuardianLog -Value ((Now-Iso) + " " + ($script:Report | ConvertTo-Json -Depth 12 -Compress)) -Encoding UTF8
    }
    if ($Json) { Write-Output $jsonText }
}

function Fail-Guardian {
    param([string]$Name, [string]$Detail)
    Add-Check -Name $Name -Ok $false -Detail $Detail
    Write-GuardianStatus
    exit 1
}

function Get-VenvPython {
    $python = Join-Path $InstallRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $python)) {
        Fail-Guardian -Name "venv_python" -Detail "missing: $python"
    }
    return $python
}

function Get-ProcessTree {
    param([object[]]$Processes, [int[]]$RootProcessIds)
    $ids = New-Object "System.Collections.Generic.HashSet[int]"
    $queue = New-Object "System.Collections.Generic.Queue[int]"
    foreach ($rootPid in $RootProcessIds) {
        if ($ids.Add([int]$rootPid)) { $queue.Enqueue([int]$rootPid) }
    }
    while ($queue.Count -gt 0) {
        $parent = $queue.Dequeue()
        foreach ($proc in $Processes) {
            if ([int]$proc.ParentProcessId -eq $parent) {
                if ($ids.Add([int]$proc.ProcessId)) {
                    $queue.Enqueue([int]$proc.ProcessId)
                }
            }
        }
    }
    # Keep the HashSet intact when it contains only one process id.
    return ,$ids
}

function Get-ProcessStartTimeUtc {
    param([object]$Process)
    try {
        if ($Process.CreationDate -is [DateTime]) {
            return ([DateTime]$Process.CreationDate).ToUniversalTime()
        }
        return [System.Management.ManagementDateTimeConverter]::ToDateTime(
            [string]$Process.CreationDate
        ).ToUniversalTime()
    } catch { return $null }
}

function Stop-ProcessTreeByRoots {
    param([object[]]$RootProcesses)
    $processes = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)
    $rootIds = @($RootProcesses | ForEach-Object { [int]$_.ProcessId })
    if ($rootIds.Count -eq 0) { return }
    $treeIds = Get-ProcessTree -Processes $processes -RootProcessIds $rootIds
    $ordered = @($processes | Where-Object { $treeIds.Contains([int]$_.ProcessId) } | Sort-Object ProcessId -Descending)
    foreach ($proc in $ordered) {
        try {
            Stop-Process -Id ([int]$proc.ProcessId) -Force -ErrorAction SilentlyContinue
        } catch { }
    }
}

function Format-ProcessIdList {
    param([int[]]$ProcessIds)
    $ids = @($ProcessIds | Where-Object { $_ -gt 0 } | Sort-Object -Unique)
    if ($ids.Count -eq 0) { return "" }
    return ($ids -join ",")
}

function Get-ValidPidFileProcessIds {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return @() }
    try {
        $raw = (Get-Content -LiteralPath $Path -Raw -Encoding UTF8).Trim()
        $parsedPid = 0
        if ([int]::TryParse($raw, [ref]$parsedPid) -and $parsedPid -gt 0) {
            $proc = Get-CimInstance Win32_Process -Filter ("ProcessId = " + [string]$parsedPid) -ErrorAction SilentlyContinue
            if ($null -ne $proc) { return @([int]$parsedPid) }
        }
    } catch { }
    return @()
}

function Get-PortListenerProcessIds {
    param([int]$Port)
    if ($Port -le 0) { return @() }
    $ids = @()
    try {
        $ids += @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue | ForEach-Object {
            [int]$_.OwningProcess
        })
    } catch {
        try {
            $lines = @(netstat -ano | Select-String ":$Port " | Select-String "LISTENING")
            foreach ($line in $lines) {
                $parts = @(([string]$line).Trim() -split "\s+")
                if ($parts.Count -gt 0) {
                    $parsedPid = 0
                    if ([int]::TryParse($parts[$parts.Count - 1], [ref]$parsedPid)) {
                        $ids += [int]$parsedPid
                    }
                }
            }
        } catch { }
    }
    return @($ids | Where-Object { $_ -gt 0 } | Sort-Object -Unique)
}

function Get-PortListenerProcessSummaries {
    param([int]$Port)
    $ids = @(Get-PortListenerProcessIds -Port $Port)
    if ($ids.Count -eq 0) { return @() }
    $summaries = @()
    foreach ($listenerPid in @($ids)) {
        $proc = Get-CimInstance Win32_Process -Filter ("ProcessId = " + [string]$listenerPid) -ErrorAction SilentlyContinue
        if ($null -eq $proc) {
            $summaries += [ordered]@{
                pid = [int]$listenerPid
                name = "unknown"
                parent_pid = 0
                command_has_install_root = $false
                is_wslrelay = $false
            }
            continue
        }
        $cmd = [string]$proc.CommandLine
        $summaries += [ordered]@{
            pid = [int]$proc.ProcessId
            name = [string]$proc.Name
            parent_pid = [int]$proc.ParentProcessId
            command_has_install_root = (Test-CommandLineHasInstallRoot -CommandLine $cmd)
            is_wslrelay = ([string]$proc.Name -ieq "wslrelay.exe")
        }
    }
    return @($summaries)
}

function Add-PortOwnerDiagnostic {
    param(
        [string]$Name,
        [int]$Port
    )
    if ($Port -le 0) { return }
    $owners = @(Get-PortListenerProcessSummaries -Port $Port)
    if ($owners.Count -eq 0) {
        Add-Check `
            -Name ($Name + "_port_owner") `
            -Ok $true `
            -Detail ("no listener owner found for " + [string]$Port)
        return
    }
    $summary = @($owners | ForEach-Object {
        ([string]$_.name) + "#" + ([string]$_.pid)
    }) -join ", "
    Add-Check `
        -Name ($Name + "_port_owner") `
        -Ok $true `
        -Detail ("listener owner(s) for " + [string]$Port + ": " + $summary) `
        -Data ([ordered]@{
            port = $Port
            owners = @($owners)
            any_install_root_owner = @($owners | Where-Object { $_.command_has_install_root }).Count -gt 0
            any_wslrelay_owner = @($owners | Where-Object { $_.is_wslrelay }).Count -gt 0
        })
}

function Test-ProcessTreeContainsAny {
    param(
        [object]$TreeIds,
        [int[]]$ProcessIds
    )
    foreach ($candidatePid in @($ProcessIds)) {
        if ($candidatePid -gt 0 -and $TreeIds.Contains([int]$candidatePid)) { return $true }
    }
    return $false
}

function Get-RootProcessesForMatches {
    param(
        [object[]]$AllProcesses,
        [object[]]$MatchingProcesses
    )
    $matchIds = @{}
    foreach ($proc in @($MatchingProcesses)) {
        $matchIds[[int]$proc.ProcessId] = $true
    }
    $roots = @()
    foreach ($proc in @($MatchingProcesses)) {
        $parentId = 0
        try { $parentId = [int]$proc.ParentProcessId } catch { $parentId = 0 }
        if (-not $matchIds.ContainsKey($parentId)) {
            $roots += $proc
        }
    }
    return @($roots | Sort-Object ProcessId -Unique)
}

function Select-CanonicalServiceRoot {
    param(
        [object[]]$AllProcesses,
        [object[]]$RootProcesses,
        [int[]]$PreferredProcessIds = @(),
        [int[]]$PidFileProcessIds = @()
    )
    if ($RootProcesses.Count -eq 0) { return $null }
    $venvPython = Normalize-PathText -Text (Join-Path $InstallRoot ".venv\Scripts\python.exe")
    $ranked = @()
    foreach ($root in @($RootProcesses)) {
        $treeIds = Get-ProcessTree -Processes $AllProcesses -RootProcessIds @([int]$root.ProcessId)
        $treeProcesses = @($AllProcesses | Where-Object { $treeIds.Contains([int]$_.ProcessId) })
        $score = 0
        if (Test-ProcessTreeContainsAny -TreeIds $treeIds -ProcessIds $PreferredProcessIds) {
            $score += 10000
        }
        if (Test-ProcessTreeContainsAny -TreeIds $treeIds -ProcessIds $PidFileProcessIds) {
            $score += 5000
        }
        foreach ($proc in $treeProcesses) {
            $cmd = Normalize-PathText -Text ([string]$proc.CommandLine)
            if (-not [string]::IsNullOrWhiteSpace($cmd) -and $cmd.Contains($venvPython)) {
                $score += 1000
                break
            }
        }
        foreach ($proc in $treeProcesses) {
            $cmd = [string]$proc.CommandLine
            if ($cmd -match "\.cmd") {
                $score += 100
                break
            }
        }
        $start = Get-ProcessStartTimeUtc -Process $root
        if ($null -eq $start) { $start = [DateTime]::MinValue }
        $ranked += [pscustomobject]@{
            Root = $root
            Score = $score
            Start = $start
        }
    }
    $selected = @($ranked | Sort-Object `
        @{Expression = { $_.Score }; Descending = $true}, `
        @{Expression = { $_.Start }; Descending = $true}, `
        @{Expression = { [int]$_.Root.ProcessId }; Descending = $false} |
        Select-Object -First 1)
    if ($selected.Count -eq 0) { return $null }
    return $selected[0].Root
}

function Stop-DuplicateServiceProcessRoots {
    param(
        [string]$Name,
        [object[]]$MatchingProcesses,
        [int[]]$PreferredProcessIds = @(),
        [string]$PidPath = ""
    )
    $processes = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)
    $roots = @(Get-RootProcessesForMatches -AllProcesses $processes -MatchingProcesses $MatchingProcesses)
    if ($roots.Count -le 1) { return @($MatchingProcesses) }
    $pidFileIds = @()
    if (-not [string]::IsNullOrWhiteSpace($PidPath)) {
        $pidFileIds = @(Get-ValidPidFileProcessIds -Path $PidPath)
    }
    $keep = Select-CanonicalServiceRoot `
        -AllProcesses $processes `
        -RootProcesses $roots `
        -PreferredProcessIds $PreferredProcessIds `
        -PidFileProcessIds $pidFileIds
    if ($null -eq $keep) { return @($MatchingProcesses) }

    $keepId = [int]$keep.ProcessId
    $dropRoots = @($roots | Where-Object { [int]$_.ProcessId -ne $keepId })
    $dropIds = @($dropRoots | ForEach-Object { [int]$_.ProcessId })
    if ($dropRoots.Count -gt 0) {
        Stop-ProcessTreeByRoots -RootProcesses $dropRoots
    }
    Add-Check `
        -Name ($Name + "_duplicate_processes") `
        -Ok $true `
        -Detail ("kept root PID " + [string]$keepId + "; stopped roots " + (Format-ProcessIdList -ProcessIds $dropIds)) `
        -Data ([ordered]@{
            kept_root_pid = $keepId
            stopped_root_pids = @($dropIds)
            preferred_pids = @($PreferredProcessIds)
            pid_file_pids = @($pidFileIds)
        })
    Start-Sleep -Milliseconds 500
    return @()
}

function Normalize-PathText {
    param([string]$Text)
    $normalized = ([string]$Text).Replace("\", "/").ToLowerInvariant()
    return [regex]::Replace($normalized, "/+", "/")
}

function Test-CommandLineHasInstallRoot {
    param([string]$CommandLine)
    if ([string]::IsNullOrWhiteSpace($CommandLine)) { return $false }
    $normalizedCommand = Normalize-PathText -Text $CommandLine
    $normalizedRoot = Normalize-PathText -Text $InstallRoot
    return $normalizedCommand.Contains($normalizedRoot)
}

function Test-P0WatcherCommandLine {
    param([string]$CommandLine)
    if ([string]::IsNullOrWhiteSpace($CommandLine)) { return $false }
    if (-not (Test-CommandLineHasInstallRoot -CommandLine $CommandLine)) { return $false }
    if ($CommandLine -match "p0-watcher\.cmd") { return $true }
    return (($CommandLine -match "memcore-cloud\.py") -and ($CommandLine -match "--watch"))
}

function Get-P0WatcherPidAnchorProcesses {
    param([object[]]$Processes)
    $pidPath = Join-Path $RuntimeDir "p0-watcher.pid"
    $pidIds = @(Get-ValidPidFileProcessIds -Path $pidPath)
    if ($pidIds.Count -eq 0) { return @() }
    $pidFileTime = (Get-Item -LiteralPath $pidPath).LastWriteTimeUtc
    $anchors = @()
    foreach ($watcherPid in $pidIds) {
        $proc = @($Processes | Where-Object { [int]$_.ProcessId -eq [int]$watcherPid } | Select-Object -First 1)
        if ($proc.Count -eq 0) { continue }
        $candidate = $proc[0]
        if ([string]$candidate.Name -notmatch "^python(?:w)?\.exe$") { continue }
        $commandLine = [string]$candidate.CommandLine
        if (-not [string]::IsNullOrWhiteSpace($commandLine)) {
            if (Test-P0WatcherCommandLine -CommandLine $commandLine) {
                $anchors += $candidate
            }
            continue
        }
        $started = Get-ProcessStartTimeUtc -Process $candidate
        if ($null -eq $started) { continue }
        $delta = [Math]::Abs(($pidFileTime - $started).TotalSeconds)
        if ($delta -le $WatcherPidStartToleranceSeconds) {
            $anchors += $candidate
        }
    }
    return @($anchors)
}

function Test-PortListening {
    param([int]$Port)
    if ($Port -le 0) { return $true }
    try {
        $conn = @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
        return ($conn.Count -gt 0)
    } catch {
        $lines = @(netstat -ano | Select-String ":$Port " | Select-String "LISTENING")
        return ($lines.Count -gt 0)
    }
}

function Test-MemcoreServicePortReady {
    param(
        [string]$Name,
        [int]$Port
    )
    if (-not (Test-PortListening -Port $Port)) { return $false }
    if (($Name -ne "raw-gateway") -or ($Port -le 0)) { return $true }
    try {
        $health = Invoke-RestMethod -Uri ("http://127.0.0.1:" + [string]$Port + "/health") -TimeoutSec 5
        return (
            ($health.ok -eq $true) -and
            ([string]$health.service -eq "raw_consumption_gateway") -and
            ($health.preflight -eq $true) -and
            (Test-RawGatewayHealthVersion -Health $health) -and
            (Test-RawGatewayHealthIdentity -Health $health)
        )
    } catch {
        return $false
    }
}

function Get-InstallVersion {
    $versionPath = Join-Path $InstallRoot "VERSION"
    if (-not (Test-Path -LiteralPath $versionPath)) { return "" }
    try {
        return (Get-Content -LiteralPath $versionPath -Raw -Encoding UTF8).Trim()
    } catch {
        return ""
    }
}

function Test-RawGatewayHealthVersion {
    param([object]$Health)
    if ($null -eq $Health) { return $false }
    $expectedVersion = Get-InstallVersion
    $actualVersion = [string]$Health.version
    if ([string]::IsNullOrWhiteSpace($expectedVersion)) { return $false }
    if ([string]::IsNullOrWhiteSpace($actualVersion)) { return $false }
    return ($actualVersion.Trim() -eq $expectedVersion)
}

function Test-RawGatewayHealthIdentity {
    param([object]$Health)
    if ($null -eq $Health) { return $false }
    $scriptPath = Join-Path $InstallRoot "src\raw_consumption_gateway.py"
    $expectedHash = Get-FileSha256 -Path $scriptPath
    $sourcePath = [string]$Health.source_path
    $sourceHash = ([string]$Health.source_sha256).ToLowerInvariant()
    if ([string]::IsNullOrWhiteSpace($sourcePath)) { return $false }
    if ([string]::IsNullOrWhiteSpace($sourceHash)) { return $false }
    if ([string]::IsNullOrWhiteSpace($expectedHash)) { return $false }
    if ((Normalize-PathText -Text $sourcePath) -ne (Normalize-PathText -Text $scriptPath)) { return $false }
    return ($sourceHash -eq $expectedHash)
}

function Test-MemcoreServiceCommandLine {
    param(
        [string]$CommandLine,
        [string]$Name,
        [string]$ScriptName
    )
    if ([string]::IsNullOrWhiteSpace($CommandLine)) { return $false }
    if (-not (Test-CommandLineHasInstallRoot -CommandLine $CommandLine)) { return $false }
    if ($CommandLine -match ([regex]::Escape("$Name.cmd"))) { return $true }
    if ($CommandLine -match ([regex]::Escape($ScriptName))) { return $true }
    return $false
}

function Resolve-MemcoreServicePort {
    param(
        [string]$Name,
        [int]$ConfiguredPort
    )
    if ($ConfiguredPort -gt 0) { return $ConfiguredPort }
    if ($Name -ne "front-door") { return 0 }
    $portPath = Join-Path $RuntimeDir "front_door_port"
    if (-not (Test-Path -LiteralPath $portPath)) { return 0 }
    try {
        $discoveredPort = 0
        $raw = (Get-Content -LiteralPath $portPath -Raw -Encoding UTF8).Trim()
        if ([int]::TryParse($raw, [ref]$discoveredPort) -and $discoveredPort -gt 0) {
            return $discoveredPort
        }
    } catch { }
    return 0
}

function Get-MemcoreServicePidAnchorProcesses {
    param(
        [object[]]$Processes,
        [string]$Name,
        [string]$ScriptName,
        [int]$Port
    )
    $pidPath = Join-Path $RuntimeDir "$Name.pid"
    $pidIds = @(Get-ValidPidFileProcessIds -Path $pidPath)
    if ($pidIds.Count -eq 0) { return @() }
    $pidFileTime = (Get-Item -LiteralPath $pidPath).LastWriteTimeUtc
    $venvPython = Normalize-PathText -Text (Join-Path $InstallRoot ".venv\Scripts\python.exe")
    $listenerIds = @(Get-PortListenerProcessIds -Port $Port)
    $anchors = @()
    foreach ($servicePid in $pidIds) {
        $proc = @($Processes | Where-Object { [int]$_.ProcessId -eq [int]$servicePid } | Select-Object -First 1)
        if ($proc.Count -eq 0) { continue }
        $candidate = $proc[0]
        if ([string]$candidate.Name -notmatch "^python(?:w)?\.exe$") { continue }
        $commandLine = [string]$candidate.CommandLine
        if (-not [string]::IsNullOrWhiteSpace($commandLine)) {
            if (-not (Test-MemcoreServiceCommandLine `
                -CommandLine $commandLine `
                -Name $Name `
                -ScriptName $ScriptName)) {
                continue
            }
        } else {
            $executablePath = Normalize-PathText -Text ([string]$candidate.ExecutablePath)
            if (
                (-not [string]::IsNullOrWhiteSpace($executablePath)) -and
                $executablePath -ne $venvPython
            ) {
                continue
            }
            $started = Get-ProcessStartTimeUtc -Process $candidate
            if ($null -eq $started) { continue }
            $delta = [Math]::Abs(($pidFileTime - $started).TotalSeconds)
            if ($delta -gt $ServicePidStartToleranceSeconds) { continue }
        }
        if ($Port -gt 0) {
            $treeIds = Get-ProcessTree -Processes $Processes -RootProcessIds @([int]$candidate.ProcessId)
            if (-not (Test-ProcessTreeContainsAny -TreeIds $treeIds -ProcessIds $listenerIds)) {
                continue
            }
        }
        $anchors += $candidate
    }
    return @($anchors)
}

function Get-MemcoreServiceProcesses {
    param(
        [string]$Name,
        [string]$ScriptName,
        [int]$Port = 0
    )
    $processes = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)
    $commandAnchors = @($processes | Where-Object {
        Test-MemcoreServiceCommandLine `
            -CommandLine ([string]$_.CommandLine) `
            -Name $Name `
            -ScriptName $ScriptName
    })
    $pidAnchors = @(Get-MemcoreServicePidAnchorProcesses `
        -Processes $processes `
        -Name $Name `
        -ScriptName $ScriptName `
        -Port $Port)
    $anchorIds = @(
        @($commandAnchors) + @($pidAnchors) |
            ForEach-Object { [int]$_.ProcessId } |
            Sort-Object -Unique
    )
    if ($anchorIds.Count -eq 0) { return @() }
    $treeIds = Get-ProcessTree -Processes $processes -RootProcessIds $anchorIds
    return @($processes | Where-Object { $treeIds.Contains([int]$_.ProcessId) })
}

function Set-MemcoreServicePidAnchor {
    param(
        [string]$Name,
        [object[]]$Processes
    )
    if ($Name -eq "p0-watcher") { return }
    $venvPython = Normalize-PathText -Text (Join-Path $InstallRoot ".venv\Scripts\python.exe")
    $pythonCandidates = @($Processes | Where-Object {
        [string]$_.Name -match "^python(?:w)?\.exe$"
    })
    if ($pythonCandidates.Count -eq 0) { return }

    $pidPath = Join-Path $RuntimeDir "$Name.pid"
    $currentPid = 0
    if (Test-Path -LiteralPath $pidPath) {
        [void][int]::TryParse(
            (Get-Content -LiteralPath $pidPath -Raw -Encoding UTF8).Trim(),
            [ref]$currentPid
        )
    }
    $candidates = @($pythonCandidates | Where-Object {
        [int]$_.ProcessId -eq $currentPid
    })
    if ($candidates.Count -eq 0) {
        $candidates = @($pythonCandidates | Where-Object {
            (Normalize-PathText -Text ([string]$_.ExecutablePath)) -eq $venvPython
        } | Sort-Object ProcessId)
    }
    if ($candidates.Count -eq 0) {
        $pythonIds = New-Object 'System.Collections.Generic.HashSet[int]'
        foreach ($candidate in $pythonCandidates) {
            [void]$pythonIds.Add([int]$candidate.ProcessId)
        }
        $candidates = @($pythonCandidates | Where-Object {
            -not $pythonIds.Contains([int]$_.ParentProcessId)
        } | Sort-Object ProcessId)
    }
    if ($candidates.Count -eq 0) { return }
    $canonical = $candidates[0]
    $canonicalPid = [int]$canonical.ProcessId
    if ($currentPid -ne $canonicalPid) {
        Set-Content -LiteralPath $pidPath -Value ([string]$canonicalPid) -Encoding ASCII
    }
    $started = Get-ProcessStartTimeUtc -Process $canonical
    if ($null -ne $started) {
        [System.IO.File]::SetLastWriteTimeUtc($pidPath, $started)
    }
}

function Get-StartedServiceProcessTree {
    param(
        [int]$RootProcessId,
        [int]$Port
    )
    if ($RootProcessId -le 0 -or $Port -le 0) { return @() }
    $processes = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)
    $root = @($processes | Where-Object { [int]$_.ProcessId -eq $RootProcessId } | Select-Object -First 1)
    if ($root.Count -eq 0) { return @() }
    $treeIds = Get-ProcessTree -Processes $processes -RootProcessIds @($RootProcessId)
    $listenerIds = @(Get-PortListenerProcessIds -Port $Port)
    if (-not (Test-ProcessTreeContainsAny -TreeIds $treeIds -ProcessIds $listenerIds)) {
        return @()
    }
    return @($processes | Where-Object { $treeIds.Contains([int]$_.ProcessId) })
}

function Get-P0WatcherTree {
    $processes = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)
    $commandAnchors = @($processes | Where-Object {
        Test-P0WatcherCommandLine -CommandLine ([string]$_.CommandLine)
    })
    $pidAnchors = @(Get-P0WatcherPidAnchorProcesses -Processes $processes)
    $anchorIds = @(
        @($commandAnchors) + @($pidAnchors) |
            ForEach-Object { [int]$_.ProcessId } |
            Sort-Object -Unique
    )
    if ($anchorIds.Count -eq 0) { return @() }
    $treeIds = Get-ProcessTree -Processes $processes -RootProcessIds $anchorIds
    return @($processes | Where-Object { $treeIds.Contains([int]$_.ProcessId) })
}

function Get-P0WatcherProcesses {
    return @(Get-P0WatcherTree)
}

function Test-ProcessesOlderThanFile {
    param(
        [object[]]$Processes,
        [string]$Path
    )
    if (-not (Test-Path -LiteralPath $Path)) { return $false }
    if ($Processes.Count -eq 0) { return $false }
    $mtime = (Get-Item -LiteralPath $Path).LastWriteTimeUtc
    foreach ($proc in $Processes) {
        $start = Get-ProcessStartTimeUtc -Process $proc
        if ($null -ne $start -and $start -lt $mtime) {
            return $true
        }
    }
    return $false
}

function Ensure-P0WatcherCommand {
    $cmdPath = Join-Path $RuntimeDir "p0-watcher.cmd"
    $python = Get-VenvPython
    $watcher = Join-Path $InstallRoot "src\memcore-cloud.py"
    if (-not (Test-Path -LiteralPath $watcher)) {
        Fail-Guardian -Name "watcher_script" -Detail "missing: $watcher"
    }
    $out = Join-Path $LogDir "p0-watcher.out.log"
    $err = Join-Path $LogDir "p0-watcher.err.log"
    $lines = @(
        "@echo off",
        "cd /d `"$InstallRoot`"",
        "set `"MEMCORE_ROOT=$InstallRoot`"",
        "set `"MEMCORE_INSTALL_ROOT=$InstallRoot`"",
        "set `"PYTHONPATH=$InstallRoot`"",
        "set `"PYTHONIOENCODING=utf-8`"",
        "set `"MEMCORE_WATCHER_RESOURCE_PROFILE=light`"",
        "set `"MEMCORE_WATCHER_SOURCE_DEFAULT=all`"",
        "set `"MEMCORE_WATCHER_INTERVAL_MS=5000`"",
        "`"$python`" -u `"$watcher`" --watch --source all 1>>`"$out`" 2>>`"$err`""
    )
    Write-Utf8NoBom -Path $cmdPath -Text (($lines -join "`r`n") + "`r`n")
    Add-Check -Name "p0_watcher_cmd_refreshed" -Ok $true -Detail $cmdPath
    return $cmdPath
}

function Ensure-MemcoreServiceCommand {
    param(
        [string]$Name,
        [string]$ArgLine,
        [switch]$IncludeDialogEntryToken
    )
    $cmdPath = Join-Path $RuntimeDir "$Name.cmd"
    $python = Get-VenvPython
    $out = Join-Path $LogDir "$Name.out.log"
    $err = Join-Path $LogDir "$Name.err.log"
    $lines = @(
        "@echo off",
        "cd /d `"$InstallRoot`"",
        "set `"MEMCORE_ROOT=$InstallRoot`"",
        "set `"MEMCORE_INSTALL_ROOT=$InstallRoot`"",
        "set `"PYTHONPATH=$InstallRoot`"",
        "set `"PYTHONIOENCODING=utf-8`"",
        "set `"HERMES_HOME=$HermesHome`""
    )
    if ($IncludeDialogEntryToken -and $DialogEntryToken) {
        $lines += "set `"MEMCORE_DIALOG_ENTRY_TOKEN=$DialogEntryToken`""
    }
    $lines += "`"$python`" $ArgLine 1>>`"$out`" 2>>`"$err`""
    Write-Utf8NoBom -Path $cmdPath -Text (($lines -join "`r`n") + "`r`n")
    Add-Check -Name ($Name + "_cmd_refreshed") -Ok $true -Detail $cmdPath
    return $cmdPath
}

function Start-HiddenCommandProcess {
    param([string]$CmdPath)
    $command = "$env:ComSpec /c `"`"$CmdPath`"`""
    $startup = ([WMIClass]"Win32_ProcessStartup").CreateInstance()
    $startup.ShowWindow = 0
    $result = ([WMIClass]"Win32_Process").Create($command, $InstallRoot, $startup)
    if ($result.ReturnValue -ne 0) {
        Fail-Guardian -Name "process_start" -Detail ("WMI create failed for " + $CmdPath + " return=" + [string]$result.ReturnValue)
    }
    return [int]$result.ProcessId
}

function Start-P0WatcherIfMissing {
    $running = Get-P0WatcherProcesses
    $watcher = Join-Path $InstallRoot "src\memcore-cloud.py"
    if ($running.Count -gt 1) {
        Stop-DuplicateServiceProcessRoots `
            -Name "p0_watcher" `
            -MatchingProcesses $running `
            -PidPath (Join-Path $RuntimeDir "p0-watcher.pid") | Out-Null
        $running = Get-P0WatcherProcesses
    }
    if (
        (Test-ProcessesOlderThanFile -Processes $running -Path $watcher) -or
        (($running.Count -gt 0) -and (Test-ServiceSourceChanged -Name "p0-watcher" -Path $watcher))
    ) {
        Stop-ProcessTreeByRoots -RootProcesses $running
        Add-Check -Name "p0_watcher_restart" -Ok $true -Detail "source file newer than running process or source hash changed"
        $running = @()
    }
    if ($running.Count -gt 0) {
        Set-StoredServiceHash -Name "p0-watcher" -Hash (Get-FileSha256 -Path $watcher)
        Add-Check -Name "p0_watcher_process" -Ok $true -Detail ("already running PID " + [string]$running[0].ProcessId)
        return
    }
    $cmdPath = Ensure-P0WatcherCommand
    Start-HiddenCommandProcess -CmdPath $cmdPath | Out-Null
    $after = @()
    for ($i = 0; $i -lt 10; $i++) {
        Start-Sleep -Seconds 1
        $after = @(Get-P0WatcherProcesses)
        if ($after.Count -gt 0) { break }
    }
    if ($after.Count -eq 0) {
        Fail-Guardian -Name "p0_watcher_start" -Detail "start attempted but watcher process was not found"
    }
    Set-StoredServiceHash -Name "p0-watcher" -Hash (Get-FileSha256 -Path $watcher)
    Add-Check `
        -Name "p0_watcher_start" `
        -Ok $true `
        -Detail ("started service tree with " + [string]$after.Count + " process(es)") `
        -Data ([ordered]@{ service_tree_process_count = [int]$after.Count })
}

function Start-MemcoreServiceIfMissing {
    param(
        [string]$Name,
        [string]$ScriptName,
        [string]$ArgLine,
        [int]$Port = 0,
        [int]$StartupTimeoutSeconds = 20,
        [switch]$IncludeDialogEntryToken
    )
    $scriptPath = Join-Path $InstallRoot ("src\" + $ScriptName)
    if (-not (Test-Path -LiteralPath $scriptPath)) {
        Fail-Guardian -Name ($Name + "_script") -Detail "missing: $scriptPath"
    }

    $cmdPath = Ensure-MemcoreServiceCommand `
        -Name $Name `
        -ArgLine $ArgLine `
        -IncludeDialogEntryToken:$IncludeDialogEntryToken
    $runtimePort = Resolve-MemcoreServicePort -Name $Name -ConfiguredPort $Port
    $running = @(Get-MemcoreServiceProcesses -Name $Name -ScriptName $ScriptName -Port $runtimePort)
    if ($running.Count -gt 1) {
        Stop-DuplicateServiceProcessRoots `
            -Name $Name `
            -MatchingProcesses $running `
            -PreferredProcessIds @(Get-PortListenerProcessIds -Port $runtimePort) `
            -PidPath (Join-Path $RuntimeDir "$Name.pid") | Out-Null
        $running = @(Get-MemcoreServiceProcesses -Name $Name -ScriptName $ScriptName -Port $runtimePort)
    }
    if (
        (Test-ProcessesOlderThanFile -Processes $running -Path $scriptPath) -or
        (($running.Count -gt 0) -and (Test-ServiceSourceChanged -Name $Name -Path $scriptPath))
    ) {
        Stop-ProcessTreeByRoots -RootProcesses $running
        Add-Check -Name ($Name + "_restart") -Ok $true -Detail "source file newer than running process or source hash changed"
        $running = @()
    }
    $portReady = Test-MemcoreServicePortReady -Name $Name -Port $runtimePort
    if (($running.Count -gt 0) -and (-not $portReady) -and ($runtimePort -gt 0)) {
        Add-PortOwnerDiagnostic -Name $Name -Port $runtimePort
        Stop-ProcessTreeByRoots -RootProcesses $running
        Add-Check -Name ($Name + "_restart") -Ok $true -Detail ("port health check failed or wrong owner: " + [string]$runtimePort)
        $running = @()
    }
    if (($running.Count -gt 0) -and $portReady) {
        Set-MemcoreServicePidAnchor -Name $Name -Processes $running
        Set-StoredServiceHash -Name $Name -Hash (Get-FileSha256 -Path $scriptPath)
        Add-Check -Name ($Name + "_process") -Ok $true -Detail ("already running PID " + [string]$running[0].ProcessId)
        if ($runtimePort -gt 0) {
            Add-Check -Name ($Name + "_port") -Ok $true -Detail ("listening " + [string]$runtimePort)
        }
        return
    }

    $rootPid = Start-HiddenCommandProcess -CmdPath $cmdPath
    $after = @()
    $ready = $false
    for ($i = 0; $i -lt $StartupTimeoutSeconds; $i++) {
        Start-Sleep -Seconds 1
        $runtimePort = Resolve-MemcoreServicePort -Name $Name -ConfiguredPort $Port
        $after = @(Get-MemcoreServiceProcesses -Name $Name -ScriptName $ScriptName -Port $runtimePort)
        if ($after.Count -eq 0) {
            $after = @(Get-StartedServiceProcessTree -RootProcessId $rootPid -Port $runtimePort)
        }
        $ready = ($runtimePort -gt 0) -and (Test-MemcoreServicePortReady -Name $Name -Port $runtimePort)
        if (($after.Count -gt 0) -and $ready) { break }
    }
    if ($after.Count -eq 0) {
        Fail-Guardian -Name ($Name + "_start") -Detail "start attempted but process was not found"
    }
    if (-not $ready) {
        Add-PortOwnerDiagnostic -Name $Name -Port $runtimePort
        Fail-Guardian -Name ($Name + "_port") -Detail ("start attempted but port is not listening: " + [string]$runtimePort)
    }
    Set-MemcoreServicePidAnchor -Name $Name -Processes $after
    Set-StoredServiceHash -Name $Name -Hash (Get-FileSha256 -Path $scriptPath)
    Add-Check -Name ($Name + "_start") -Ok $true -Detail ("started PID " + [string]$after[0].ProcessId)
    if ($runtimePort -gt 0) {
        Add-Check -Name ($Name + "_port") -Ok $true -Detail ("listening " + [string]$runtimePort)
    }
}

function Start-RuntimeServicesIfMissing {
    $env:MEMCORE_ROOT = $InstallRoot
    $env:MEMCORE_INSTALL_ROOT = $InstallRoot
    $env:PYTHONPATH = $InstallRoot
    $env:PYTHONIOENCODING = "utf-8"
    $env:HERMES_HOME = $HermesHome
    $script:DialogEntryToken = Ensure-DialogEntryToken
    $dialogEntryHost = Get-DialogEntryHost

    Start-MemcoreServiceIfMissing `
        -Name "p3-recall" `
        -ScriptName "p3_recall.py" `
        -ArgLine "-u `"$InstallRoot\src\p3_recall.py`" serve --port $InternalP3Port" `
        -Port $InternalP3Port `
        -StartupTimeoutSeconds 120
    Start-MemcoreServiceIfMissing `
        -Name "p4-provider" `
        -ScriptName "p4_provider.py" `
        -ArgLine "-u `"$InstallRoot\src\p4_provider.py`" --port $InternalP4Port" `
        -Port $InternalP4Port
    Start-MemcoreServiceIfMissing `
        -Name "p6-console" `
        -ScriptName "p6_console.py" `
        -ArgLine "-u `"$InstallRoot\src\p6_console.py`" --host 127.0.0.1 --port $InternalP6Port" `
        -Port $InternalP6Port
    Start-MemcoreServiceIfMissing `
        -Name "raw-gateway" `
        -ScriptName "raw_consumption_gateway.py" `
        -ArgLine "-u `"$InstallRoot\src\raw_consumption_gateway.py`" --port $InternalRawPort" `
        -Port $InternalRawPort
    Start-MemcoreServiceIfMissing `
        -Name "dialog-entry" `
        -ScriptName "dialog_entry_proxy.py" `
        -ArgLine "-u `"$InstallRoot\src\dialog_entry_proxy.py`" --host 127.0.0.1 --port $InternalDialogPort" `
        -Port $InternalDialogPort `
        -IncludeDialogEntryToken
    Start-MemcoreServiceIfMissing `
        -Name "front-door" `
        -ScriptName "single_port_runtime.py" `
        -ArgLine "-u `"$InstallRoot\src\single_port_runtime.py`" --host 127.0.0.1 --preferred-port $FrontDoorPort" `
        -Port 0
}

function Invoke-RecordGuardianApi {
    param(
        [string]$Path,
        [string]$Method = "Get",
        [string]$Body = ""
    )
    $port = (Get-Content (Join-Path $InstallRoot "runtime\front_door_port") -ErrorAction SilentlyContinue | Select-Object -First 1).Trim()
    if (-not $port) { return $null }
    $uri = "http://127.0.0.1:$port" + $Path
    if ($Method -eq "Post") {
        $tokenPath = Join-Path $RuntimeDir "console_token"
        $headers = @{}
        if (Test-Path -LiteralPath $tokenPath) {
            $token = (Get-Content -LiteralPath $tokenPath -Raw -Encoding UTF8).Trim()
            if (-not [string]::IsNullOrWhiteSpace($token)) {
                $headers["X-Memcore-Console-Token"] = $token
                $headers["Origin"] = "http://127.0.0.1:$port"
            }
        }
        return Invoke-RestMethod `
            -Method Post `
            -Uri $uri `
            -Body $Body `
            -Headers $headers `
            -ContentType "application/json" `
            -TimeoutSec 10
    }
    return Invoke-RestMethod -Uri $uri -TimeoutSec 10
}

function ConvertTo-SafeRecordGuardianSummary {
    param([object]$Status)
    if ($null -eq $Status -or $null -eq $Status.summary) { return $null }
    $summary = $Status.summary
    $lostSourceCount = [int]($summary.lost_source_count)
    $triageFields = @(
        "lost_source_recoverable_count",
        "lost_source_unrecoverable_count",
        "lost_source_not_measured_count"
    )
    $summaryFields = @($summary.PSObject.Properties.Name)
    $hasCompleteTriage = @($triageFields | Where-Object { $_ -in $summaryFields }).Count -eq $triageFields.Count
    $recoverableCount = [int]($summary.lost_source_recoverable_count)
    $unrecoverableCount = [int]($summary.lost_source_unrecoverable_count)
    $notMeasuredCount = [int]($summary.lost_source_not_measured_count)
    if ((-not $hasCompleteTriage) -or (($recoverableCount + $unrecoverableCount + $notMeasuredCount) -ne $lostSourceCount)) {
        $recoverableCount = 0
        $unrecoverableCount = $lostSourceCount
        $notMeasuredCount = 0
    }
    return [ordered]@{
        record_count = [int]($summary.record_count)
        physical_record_count = [int]($summary.physical_record_count)
        logical_record_count = [int]($summary.logical_record_count)
        layout_variant_count = [int]($summary.layout_variant_count)
        record_guarded_count = [int]($summary.record_guarded_count)
        raw_lagging_or_missing_count = [int]($summary.raw_lagging_or_missing_count)
        raw_catching_up_count = [int]($summary.raw_catching_up_count)
        raw_attention_count = [int]($summary.raw_attention_count)
        raw_source_divergence_count = [int]($summary.raw_source_divergence_count)
        raw_divergence_generation_active_count = [int]($summary.raw_divergence_generation_active_count)
        raw_metadata_only_divergence_count = [int]($summary.raw_metadata_only_divergence_count)
        raw_source_regression_count = [int]($summary.raw_source_regression_count)
        raw_monotonic_probe_incomplete_count = [int]($summary.raw_monotonic_probe_incomplete_count)
        lost_source_count = $lostSourceCount
        lost_source_recoverable_count = $recoverableCount
        lost_source_unrecoverable_count = $unrecoverableCount
        lost_source_not_measured_count = $notMeasuredCount
        lost_source_one_sided_count = [int]($summary.lost_source_one_sided_count)
        lost_source_non_conversation_count = [int]($summary.lost_source_non_conversation_count)
        lost_raw_count = [int]($summary.lost_raw_count)
        corrupt_record_count = [int]($summary.corrupt_record_count)
        backfill_recommended_count = [int]($summary.backfill_recommended_count)
    }
}

function ConvertTo-SafeRecoverabilityProbe {
    param([object]$Probe)
    if ($null -eq $Probe) { return $null }
    $fields = @(
        "candidate_count",
        "candidate_limit",
        "per_file_byte_limit",
        "round_byte_limit",
        "targeted_scan_count",
        "cache_hit_count",
        "canonical_cache_hit_count",
        "measured_count",
        "not_measured_count",
        "bytes_read",
        "budget_exhausted_count",
        "one_sided_count",
        "non_conversation_count"
    )
    $propertyNames = @($Probe.PSObject.Properties.Name)
    if ("canonical_cache_status" -notin $propertyNames) { return $null }
    $safe = [ordered]@{ schema = "recoverability_probe.v1" }
    foreach ($field in $fields) {
        if ($field -notin $propertyNames) { return $null }
        $rawValue = $Probe.PSObject.Properties[$field].Value
        $isInteger = (
            ($rawValue -is [byte]) -or
            ($rawValue -is [sbyte]) -or
            ($rawValue -is [int16]) -or
            ($rawValue -is [uint16]) -or
            ($rawValue -is [int32]) -or
            ($rawValue -is [uint32]) -or
            ($rawValue -is [int64]) -or
            ($rawValue -is [uint64])
        )
        if (-not $isInteger) { return $null }
        try {
            $decimalValue = [decimal]$rawValue
        } catch {
            return $null
        }
        if (($decimalValue -lt 0) -or ($decimalValue -gt [int]::MaxValue)) { return $null }
        $value = [int]$decimalValue
        $safe[$field] = $value
    }
    $cacheStatus = [string]$Probe.PSObject.Properties["canonical_cache_status"].Value
    if ([string]::IsNullOrWhiteSpace($cacheStatus)) { return $null }
    $safe["canonical_cache_status"] = if ($cacheStatus -in @("available", "not_applicable", "not_needed")) {
        $cacheStatus
    } else {
        "unavailable"
    }
    return $safe
}

function ConvertTo-SafeRecordGuardianScope {
    param([object]$Scope)
    if ($null -eq $Scope) { return $null }
    $fields = @($Scope.PSObject.Properties.Name)
    if (("population_complete" -notin $fields) -or ("summary_is_sample" -notin $fields)) { return $null }
    return [ordered]@{
        population_complete = [bool]$Scope.population_complete
        summary_is_sample = [bool]$Scope.summary_is_sample
        detail_limit = [int]$Scope.detail_limit
        population_limit_per_source = [int]$Scope.population_limit_per_source
        targeted_refresh = [bool]$Scope.targeted_refresh
        trend_comparison_key = [string]$Scope.trend_comparison_key
    }
}

function Get-CachedRecordGuardianEvidence {
    param([switch]$AllowStale)
    if (-not (Test-Path -LiteralPath $StatusPath)) { return $null }
    try {
        $existing = Get-Content -LiteralPath $StatusPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $evidence = $existing.record_guardian
        if ($null -eq $evidence -or -not $evidence.available -or $null -eq $evidence.summary) { return $null }
        $observed = [DateTime]::Parse([string]$evidence.observed_at).ToUniversalTime()
        $age = [int][Math]::Max(0, ((Get-Date).ToUniversalTime() - $observed).TotalSeconds)
        $fresh = ($age -le $RecordGuardianCacheMaxAgeSeconds)
        if (-not $fresh -and -not $AllowStale) { return $null }
        $summary = ConvertTo-SafeRecordGuardianSummary -Status ([pscustomobject]@{ summary = $evidence.summary })
        $summaryScope = ConvertTo-SafeRecordGuardianScope -Scope $evidence.summary_scope
        $recoverabilityProbe = ConvertTo-SafeRecoverabilityProbe -Probe $evidence.recoverability_probe
        if ($null -eq $summary) { return $null }
        return [ordered]@{
            available = $true
            fresh = $fresh
            evidence_source = $(if ($fresh) { "guardian_status_cache" } else { "stale_guardian_status_cache" })
            generated_at = [string]$evidence.generated_at
            observed_at = [string]$evidence.observed_at
            cache_age_seconds = $age
            last_refresh_attempt_at = [string]$evidence.last_refresh_attempt_at
            refresh_attempt_age_seconds = Get-RecordGuardianRefreshAttemptAge -Evidence $evidence
            scan_mode = "fast"
            read_only = $true
            details_persisted = $false
            summary = $summary
            summary_scope = $summaryScope
            recoverability_probe = $recoverabilityProbe
        }
    } catch {
        return $null
    }
}

function Get-RecordGuardianRefreshAttemptAge {
    param([object]$Evidence)
    if ($null -eq $Evidence) { return -1 }
    $attemptText = [string]$Evidence.last_refresh_attempt_at
    if ([string]::IsNullOrWhiteSpace($attemptText)) { return -1 }
    try {
        $attempt = [DateTime]::Parse($attemptText).ToUniversalTime()
        return [int][Math]::Max(0, ((Get-Date).ToUniversalTime() - $attempt).TotalSeconds)
    } catch {
        return -1
    }
}

function Get-ThrottledRecordGuardianEvidence {
    if (-not (Test-Path -LiteralPath $StatusPath)) { return $null }
    try {
        $existing = Get-Content -LiteralPath $StatusPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $evidence = $existing.record_guardian
        $attemptAge = Get-RecordGuardianRefreshAttemptAge -Evidence $evidence
        if ($attemptAge -lt 0 -or $attemptAge -gt $RecordGuardianCacheMaxAgeSeconds) { return $null }

        $summary = ConvertTo-SafeRecordGuardianSummary -Status ([pscustomobject]@{ summary = $evidence.summary })
        $summaryScope = ConvertTo-SafeRecordGuardianScope -Scope $evidence.summary_scope
        $recoverabilityProbe = ConvertTo-SafeRecoverabilityProbe -Probe $evidence.recoverability_probe
        $available = [bool]$evidence.available -and $null -ne $summary
        $observedText = [string]$evidence.observed_at
        $cacheAge = -1
        if ($available -and -not [string]::IsNullOrWhiteSpace($observedText)) {
            try {
                $observed = [DateTime]::Parse($observedText).ToUniversalTime()
                $cacheAge = [int][Math]::Max(0, ((Get-Date).ToUniversalTime() - $observed).TotalSeconds)
            } catch {
                $cacheAge = -1
            }
        }
        $fresh = $available -and $cacheAge -ge 0 -and $cacheAge -le $RecordGuardianCacheMaxAgeSeconds
        return [ordered]@{
            available = $available
            fresh = $fresh
            evidence_source = $(
                if ($fresh) { "guardian_status_cache" }
                elseif ($available) { "stale_guardian_status_cache" }
                else { "api_unavailable" }
            )
            generated_at = [string]$evidence.generated_at
            observed_at = $observedText
            cache_age_seconds = $cacheAge
            last_refresh_attempt_at = [string]$evidence.last_refresh_attempt_at
            refresh_attempt_age_seconds = $attemptAge
            refresh_throttled = $true
            scan_mode = "fast"
            read_only = $true
            details_persisted = $false
            summary = $(if ($available) { $summary } else { $null })
            summary_scope = $(if ($available) { $summaryScope } else { $null })
            recoverability_probe = $(if ($available) { $recoverabilityProbe } else { $null })
        }
    } catch {
        return $null
    }
}

function Update-RecordGuardianEvidence {
    if ($NoStatusWrite) { return }
    $staleEvidence = Get-CachedRecordGuardianEvidence -AllowStale
    if (-not $Backfill) {
        $cached = Get-CachedRecordGuardianEvidence
        if ($null -ne $cached) {
            $script:Report["record_guardian"] = $cached
            Add-Check -Name "record_guardian_summary" -Ok $true -Detail ("cached age_seconds=" + [string]$cached.cache_age_seconds)
            return
        }
        $throttled = Get-ThrottledRecordGuardianEvidence
        if ($null -ne $throttled) {
            $script:Report["record_guardian"] = $throttled
            Add-Check -Name "record_guardian_summary" -Ok $true -Detail ("refresh throttled attempt_age_seconds=" + [string]$throttled.refresh_attempt_age_seconds + "; product health not inferred")
            return
        }
    }

    $attemptedAt = Now-Iso
    $script:RecordGuardianStatusAttempted = $true
    try {
        $status = Invoke-RecordGuardianApi -Path "/api/v1/records/guardian/status?limit=80&mode=fast&compact=1&gaps=0"
        $summary = ConvertTo-SafeRecordGuardianSummary -Status $status
        $summaryScope = ConvertTo-SafeRecordGuardianScope -Scope $status.summary_scope
        $recoverabilityProbe = ConvertTo-SafeRecoverabilityProbe -Probe $status.recoverability_probe
        if ($null -eq $summary) { throw "summary unavailable" }
        $script:RecordGuardianStatus = $status
        $script:Report["record_guardian"] = [ordered]@{
            available = $true
            fresh = $true
            evidence_source = "fast_compact_api"
            generated_at = [string]$status.generated_at
            observed_at = Now-Iso
            cache_age_seconds = 0
            last_refresh_attempt_at = $attemptedAt
            refresh_attempt_age_seconds = 0
            scan_mode = "fast"
            read_only = $true
            details_persisted = $false
            summary = $summary
            summary_scope = $summaryScope
            recoverability_probe = $recoverabilityProbe
        }
        Add-Check -Name "record_guardian_summary" -Ok $true -Detail ("fresh guarded=" + [string]$summary.record_guarded_count + "/" + [string]$summary.record_count)
    } catch {
        if ($null -ne $staleEvidence) {
            $script:Report["record_guardian"] = $staleEvidence
            $script:Report["record_guardian"].last_refresh_attempt_at = $attemptedAt
            $script:Report["record_guardian"].refresh_attempt_age_seconds = 0
            Add-Check -Name "record_guardian_summary" -Ok $true -Detail ("stale cache age_seconds=" + [string]$staleEvidence.cache_age_seconds + "; product health not inferred")
        } else {
            $script:Report["record_guardian"] = [ordered]@{
                available = $false
                fresh = $false
                evidence_source = "api_unavailable"
                generated_at = ""
                observed_at = Now-Iso
                cache_age_seconds = -1
                last_refresh_attempt_at = $attemptedAt
                refresh_attempt_age_seconds = 0
                scan_mode = "fast"
                read_only = $true
                details_persisted = $false
                summary = $null
            }
            Add-Check -Name "record_guardian_summary" -Ok $true -Detail "evidence unavailable; product health not inferred"
        }
    }
}

function Invoke-RecordGuardianBackfillIfNeeded {
    $status = $script:RecordGuardianStatus
    if ($null -eq $status) {
        if ($script:RecordGuardianStatusAttempted) {
            Add-Check -Name "record_guardian_status" -Ok $true -Detail "P6 guardian API already attempted; fallback to connector"
            return $false
        }
        try {
            $status = Invoke-RecordGuardianApi -Path "/api/v1/records/guardian/status?limit=80&mode=fast&compact=1&gaps=0"
        } catch {
            Add-Check -Name "record_guardian_status" -Ok $true -Detail "P6 guardian API unavailable; fallback to connector"
            return $false
        }
    }

    if (-not $status.summary) {
        Add-Check -Name "record_guardian_status" -Ok $true -Detail "P6 guardian API returned incomplete status; fallback to connector"
        return $false
    }

    $summary = $status.summary
    $missing = 0
    $catchingUp = 0
    $backfillNeeded = 0
    if ($null -ne $summary.raw_lagging_or_missing_count) { $missing = [int]$summary.raw_lagging_or_missing_count }
    if ($null -ne $summary.raw_catching_up_count) { $catchingUp = [int]$summary.raw_catching_up_count }
    if ($null -ne $summary.backfill_recommended_count) { $backfillNeeded = [int]$summary.backfill_recommended_count }

    if (($backfillNeeded -le 0) -and ($missing -le 0)) {
        Add-Check `
            -Name "record_guardian_backfill" `
            -Ok $true `
            -Detail ("not needed guarded=" + [string]$summary.record_guarded_count + "/" + [string]$summary.record_count + " catching_up=" + [string]$catchingUp)
        return $true
    }

    try {
        $body = @{ limit = 80 } | ConvertTo-Json -Depth 4 -Compress
        $result = Invoke-RecordGuardianApi -Path "/api/v1/records/guardian/backfill" -Method "Post" -Body $body
    } catch {
        Add-Check -Name "record_guardian_backfill" -Ok $false -Detail ("P6 guardian backfill failed: " + $_.Exception.Message)
        return $true
    }
    if (-not $result.ok) {
        Add-Check -Name "record_guardian_backfill" -Ok $false -Detail "P6 guardian backfill returned not ok"
        return $true
    }
    Add-Check -Name "record_guardian_backfill" -Ok $true -Detail ("ran changed=" + [string]($result.results | Measure-Object).Count + " recommended=" + [string]$backfillNeeded)
    return $true
}

function Invoke-CodexRawBackfillIfNeeded {
    if (Invoke-RecordGuardianBackfillIfNeeded) {
        return
    }

    $python = Get-VenvPython
    $connector = Join-Path $InstallRoot "src\codex_local_connector.py"
    $p0 = Join-Path $InstallRoot "src\memcore-cloud.py"
    if (-not (Test-Path -LiteralPath $connector)) {
        Add-Check -Name "codex_backfill" -Ok $true -Detail "codex connector missing; skipped"
        return
    }
    if (-not (Test-Path -LiteralPath $p0)) {
        Fail-Guardian -Name "p0_script" -Detail "missing: $p0"
    }

    $env:MEMCORE_ROOT = $InstallRoot
    $env:MEMCORE_INSTALL_ROOT = $InstallRoot
    $env:PYTHONPATH = $InstallRoot
    $env:PYTHONIOENCODING = "utf-8"

    $statusText = (& $python $connector --status 2>&1 | Out-String)
    if ($LASTEXITCODE -ne 0) {
        Add-Check -Name "codex_backfill_status" -Ok $false -Detail ("status failed: " + $statusText.Trim())
        return
    }
    $payload = $null
    try {
        $payload = ConvertFrom-JsonOutput -Text $statusText
    } catch {
        Add-Check -Name "codex_backfill_status" -Ok $false -Detail ("status returned non-JSON: " + $_.Exception.Message)
        return
    }
    $rawSync = $payload.raw_sync
    $rawStatus = if ($rawSync -and $rawSync.status) { [string]$rawSync.status } else { "unknown" }
    if ($rawStatus -notin @("raw_missing", "raw_lagging_sla_breach")) {
        Add-Check -Name "codex_backfill" -Ok $true -Detail ("not needed raw_sync=" + $rawStatus)
        return
    }

    $missing = if ($rawSync.missing_or_stale_count) { [string]$rawSync.missing_or_stale_count } else { "unknown" }
    $scanText = (& $python $p0 --scan --source codex 2>&1 | Out-String)
    if ($LASTEXITCODE -ne 0) {
        Add-Check -Name "codex_backfill" -Ok $false -Detail ("scan failed missing/stale=" + $missing + " " + $scanText.Trim())
        return
    }
    Add-Check -Name "codex_backfill" -Ok $true -Detail ("ran because " + $rawStatus + " missing/stale=" + $missing)
}

function Invoke-ScheduledTaskCoverageChecks {
    if ($StartupActivationOnly) {
        Add-NotMeasuredCheck `
            -Name "scheduled_task_startup_convergence" `
            -Detail "AtLogOn activation runs concurrently with background task startup; periodic S4U Guardian performs the full scheduled-task check"
        return
    }
    if ($SkipScheduledTaskChecks) {
        Add-NotMeasuredCheck `
            -Name "scheduled_tasks" `
            -Detail "explicit preservation override; scheduled-task contract not measured and background recovery not inferred"
        return
    }

    Ensure-GuardianHealthTaskSchedule
    if ($SkipCodexMcpGuardTaskCheck) {
        Add-NotMeasuredCheck `
            -Name "codex_mcp_guard_task" `
            -Detail "explicit preserved-guard override; principal not measured and product health not inferred"
    } else {
        Ensure-CodexMcpGuardTaskHealth
    }
}

try {
    if (-not (Test-Path -LiteralPath $InstallRoot)) {
        Fail-Guardian -Name "install_root" -Detail "missing: $InstallRoot"
    }
    Add-Check -Name "install_root" -Ok $true -Detail $InstallRoot
    Invoke-ScheduledTaskCoverageChecks
    if ($StartWatcher) {
        Start-P0WatcherIfMissing
        Start-RuntimeServicesIfMissing
    }
    Update-RecordGuardianEvidence
    if ($Backfill) { Invoke-CodexRawBackfillIfNeeded }
} catch {
    Add-Check -Name "guardian_exception" -Ok $false -Detail ($_.Exception.Message)
    Add-Content -LiteralPath $GuardianErr -Value ((Now-Iso) + " " + $_.Exception.ToString()) -Encoding UTF8
    Write-GuardianStatus
    exit 1
}

Write-GuardianStatus
if (-not $Report.ok) { exit 1 }
