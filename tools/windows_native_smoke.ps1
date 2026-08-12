#Requires -Version 5.1
param(
    [string]$InstallRoot = "$env:LOCALAPPDATA\time-library",
    [string]$RawGatewayUrl = "",
    [switch]$SkipCodex,
    [switch]$SkipScheduledTaskChecks,
    [switch]$SkipCodexGuardTaskCheck,
    [switch]$RequireBackgroundRecoveryAfterBoot,
    [switch]$Json
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = [Console]::OutputEncoding

$frontDoorPortFile = Join-Path $InstallRoot "runtime\front_door_port"
if ([string]::IsNullOrWhiteSpace($RawGatewayUrl) -and (Test-Path -LiteralPath $frontDoorPortFile)) {
    $frontDoorPort = (Get-Content -LiteralPath $frontDoorPortFile -Raw -Encoding ASCII).Trim()
    if ($frontDoorPort -match '^\d{1,5}$') { $RawGatewayUrl = "http://127.0.0.1:$frontDoorPort" }
}

$Report = [ordered]@{
    tool = "windows_native_smoke"
    target = "native_windows"
    install_root = $InstallRoot
    raw_gateway_url = $RawGatewayUrl
    ok = $false
    measurement_status = "complete"
    full_smoke = $true
    background_recovery_after_boot_required = [bool]$RequireBackgroundRecoveryAfterBoot
    not_measured_layers = @()
    checks = @()
}

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
    if (-not $Json) {
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
    $script:Report.full_smoke = $false
    if ($Name -notin @($script:Report.not_measured_layers)) {
        $script:Report.not_measured_layers += $Name
    }
    $script:Report.checks += [ordered]@{
        name = $Name
        ok = $null
        measurement_status = "not_measured"
        detail = $Detail
    }
    if (-not $Json) {
        Write-Host ("[not_measured] {0} {1}" -f $Name, $Detail)
    }
}

function Finish-Report {
    param([bool]$Ok)
    $script:Report.ok = $Ok
    if ($Json) {
        $script:Report | ConvertTo-Json -Depth 12
    }
    if ($Ok) { exit 0 }
    exit 1
}

function Fail-Smoke {
    param([string]$Name, [string]$Detail)
    Add-Check -Name $Name -Ok $false -Detail $Detail
    Finish-Report -Ok $false
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

function Test-PathRequired {
    param([string]$Name, [string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        Fail-Smoke -Name $Name -Detail "missing: $Path"
    }
    Add-Check -Name $Name -Ok $true -Detail $Path
}

function Read-Version {
    $versionPath = Join-Path $InstallRoot "VERSION"
    Test-PathRequired -Name "install_root" -Path $InstallRoot
    Test-PathRequired -Name "version_file" -Path $versionPath
    $version = (Get-Content -LiteralPath $versionPath -Raw -Encoding UTF8).Trim()
    Add-Check -Name "version" -Ok $true -Detail $version
    $script:Report["version"] = $version
}

function Smoke-Http {
    param([string]$Name, [string]$Url)
    try {
        $resp = Invoke-WebRequest -Uri $Url -TimeoutSec 6 -UseBasicParsing
        Add-Check -Name $Name -Ok $true -Detail ("HTTP {0}" -f [int]$resp.StatusCode)
    } catch {
        Fail-Smoke -Name $Name -Detail $_.Exception.Message
    }
}

function Test-ZhiyiModelBinding {
    $consoleUrl = $RawGatewayUrl
    $bindingPath = Join-Path $InstallRoot "config\zhiyi_model_binding.user.json"
    $bindingStampBefore = $null
    if (Test-Path -LiteralPath $bindingPath) {
        $bindingStampBefore = (Get-Item -LiteralPath $bindingPath).LastWriteTimeUtc.Ticks
    }

    try {
        $resp = Invoke-WebRequest -Uri ($consoleUrl + "/") -TimeoutSec 8 -UseBasicParsing
        $html = [string]$resp.Content
    } catch {
        Fail-Smoke -Name "zhiyi_model_ui" -Detail $_.Exception.Message
    }

    $requiredUi = @(
        "zhiyi.modelTitle",
        "zhiyi-model-provider",
        "zhiyi-model-provider-id",
        "zhiyi-model-name",
        "zhiyi-model-base-url",
        "zhiyi-model-api-key-env",
        "/api/v1/zhiyi/model-options",
        "/api/v1/zhiyi/model-binding/apply"
    )
    $missingUi = @()
    foreach ($needle in $requiredUi) {
        if ($html -notlike ("*" + $needle + "*")) { $missingUi += $needle }
    }
    if ($missingUi.Count -gt 0) {
        Fail-Smoke -Name "zhiyi_model_ui" -Detail ("missing: " + ($missingUi -join ","))
    }

    $forbiddenUi = @("本机工具识别模型", "Local Tool Recognition Model", "recognition-model")
    $leakedUi = @()
    foreach ($needle in $forbiddenUi) {
        if ($html -like ("*" + $needle + "*")) { $leakedUi += $needle }
    }
    if ($leakedUi.Count -gt 0) {
        Fail-Smoke -Name "zhiyi_model_ui" -Detail ("legacy standalone recognition model UI leaked: " + ($leakedUi -join ","))
    }
    Add-Check -Name "zhiyi_model_ui" -Ok $true -Detail "unified Zhiyi model controls present"

    try {
        $options = Invoke-RestMethod -Uri ($consoleUrl + "/api/v1/zhiyi/model-options") -TimeoutSec 10
    } catch {
        Fail-Smoke -Name "zhiyi_model_options" -Detail $_.Exception.Message
    }
    $optionCount = @($options.options).Count
    if ($optionCount -lt 1) {
        Fail-Smoke -Name "zhiyi_model_options" -Detail "no model options returned"
    }
    if (-not $options.user_default) {
        Fail-Smoke -Name "zhiyi_model_options" -Detail "missing user_default state"
    }
    Add-Check -Name "zhiyi_model_options" -Ok $true -Detail ("options=" + [string]$optionCount)

    $body = [ordered]@{
        manual_override = $true
        provider = "Manual"
        provider_id = "manual-openai-compatible"
        model_name = "memcore-smoke-model"
        base_url = "http://127.0.0.1:9/v1"
        api_key_env = "MEMCORE_ZHIYI_API_KEY"
        save_as_user_default = $true
    } | ConvertTo-Json -Depth 10 -Compress
    try {
        $plan = Invoke-RestMethod `
            -Uri ($consoleUrl + "/api/v1/zhiyi/model-binding/dry-run") `
            -Method Post `
            -ContentType "application/json" `
            -Body $body `
            -TimeoutSec 10
    } catch {
        Fail-Smoke -Name "zhiyi_model_binding_dry_run" -Detail $_.Exception.Message
    }
    if (-not $plan.ok) {
        Fail-Smoke -Name "zhiyi_model_binding_dry_run" -Detail "plan not ok"
    }
    if ($plan.dry_run -ne $true) {
        Fail-Smoke -Name "zhiyi_model_binding_dry_run" -Detail "dry_run flag is not true"
    }
    if ($plan.write_performed -ne $false -or $plan.config_write_performed -ne $false -or $plan.runtime_binding_write_performed -ne $false) {
        Fail-Smoke -Name "zhiyi_model_binding_dry_run" -Detail "dry-run attempted to write"
    }
    $would = $plan.would_write_user_default
    if (-not $would) {
        Fail-Smoke -Name "zhiyi_model_binding_dry_run" -Detail "missing would_write_user_default"
    }
    if ($would.model_name -ne "memcore-smoke-model") {
        Fail-Smoke -Name "zhiyi_model_binding_dry_run" -Detail "manual model was not preserved"
    }
    if ($would.api_key_env -ne "MEMCORE_ZHIYI_API_KEY") {
        Fail-Smoke -Name "zhiyi_model_binding_dry_run" -Detail "API key env name was not preserved"
    }
    if ($would.secrets_stored -ne $false) {
        Fail-Smoke -Name "zhiyi_model_binding_dry_run" -Detail "dry-run claims a secret would be stored"
    }
    if ($would.model_call_performed -ne $false) {
        Fail-Smoke -Name "zhiyi_model_binding_dry_run" -Detail "dry-run claims a model call was performed"
    }
    if ($would.applies_to -notcontains "evidence_bound_analysis" -or $would.applies_to -notcontains "local_tool_identification") {
        Fail-Smoke -Name "zhiyi_model_binding_dry_run" -Detail "unified Zhiyi model does not cover local tool identification"
    }

    $bindingStampAfter = $null
    if (Test-Path -LiteralPath $bindingPath) {
        $bindingStampAfter = (Get-Item -LiteralPath $bindingPath).LastWriteTimeUtc.Ticks
    }
    if ($bindingStampBefore -ne $bindingStampAfter) {
        Fail-Smoke -Name "zhiyi_model_binding_dry_run" -Detail "dry-run changed zhiyi_model_binding.user.json"
    }

    $script:Report["zhiyi_model"] = [ordered]@{
        option_count = [int]$optionCount
        user_default_configured = [bool]$options.user_default.configured
        dry_run_write_performed = [bool]$plan.write_performed
        secrets_stored = [bool]$would.secrets_stored
        model_call_performed = [bool]$would.model_call_performed
    }
    Add-Check -Name "zhiyi_model_binding_dry_run" -Ok $true -Detail "no write, no secret, no model call"
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
    return $ids
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

function Get-AuthorizedP0WatcherProcesses {
    $processes = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)
    $roots = @($processes | Where-Object {
        Test-P0WatcherCommandLine -CommandLine ([string]$_.CommandLine)
    })
    if ($roots.Count -eq 0) { return @() }
    $treeIds = Get-ProcessTree -Processes $processes -RootProcessIds @($roots | ForEach-Object { [int]$_.ProcessId })
    return @($processes | Where-Object { $treeIds.Contains([int]$_.ProcessId) })
}

function Invoke-CapabilityCheck {
    $endpoint = ($RawGatewayUrl.TrimEnd("/") + "/mcp")
    $body = [ordered]@{
        jsonrpc = "2.0"
        id = "windows-native-smoke"
        method = "tools/call"
        params = [ordered]@{
            name = "zhiyi_recall"
            arguments = [ordered]@{
                query = "capability check"
                mode = "capability_check"
                consumer = "windows-native-smoke"
                request_id = "windows-native-smoke-capability"
            }
        }
    } | ConvertTo-Json -Depth 10 -Compress

    try {
        $resp = Invoke-RestMethod -Uri $endpoint -Method Post -ContentType "application/json" -Body $body -TimeoutSec 10
    } catch {
        Fail-Smoke -Name "capability_check" -Detail $_.Exception.Message
    }

    if ($resp.error) {
        Fail-Smoke -Name "capability_check" -Detail ($resp.error | ConvertTo-Json -Compress)
    }
    if (-not $resp.result) {
        Fail-Smoke -Name "capability_check" -Detail "missing JSON-RPC result"
    }

    $payload = $resp.result.structuredContent
    if (-not $payload -and $resp.result.content -and $resp.result.content.Count -gt 0) {
        try {
            $payload = $resp.result.content[0].text | ConvertFrom-Json
        } catch {
            Fail-Smoke -Name "capability_check" -Detail "result content is not JSON"
        }
    }
    if (-not $payload) {
        Fail-Smoke -Name "capability_check" -Detail "missing structuredContent"
    }

    $tools = @($payload.mcp_tools)
    $problems = @()
    if ($payload.mode -ne "capability_check") { $problems += "mode" }
    if ($payload.service -ne "raw_consumption_gateway") { $problems += "service" }
    if ($payload.server -ne "time-library") { $problems += "server" }
    if ($payload.read_only -ne $true) { $problems += "read_only" }
    if ($payload.recall_performed -ne $false) { $problems += "recall_performed" }
    if ($payload.raw_excerpt_returned -ne $false) { $problems += "raw_excerpt_returned" }
    if (-not ($tools -contains "zhiyi_recall")) { $problems += "mcp_tools" }

    if ($problems.Count -gt 0) {
        Fail-Smoke -Name "capability_check" -Detail ("unexpected fields: " + ($problems -join ","))
    }

    $script:Report["capability"] = [ordered]@{
        service = [string]$payload.service
        server = [string]$payload.server
        version = [string]$payload.version
        read_only = [bool]$payload.read_only
        recall_performed = [bool]$payload.recall_performed
        raw_excerpt_returned = [bool]$payload.raw_excerpt_returned
        mcp_tools = $tools
    }
    Add-Check -Name "capability_check" -Ok $true -Detail ("version " + [string]$payload.version)
}

function Invoke-WorkPreflightCheck {
    $endpoint = ($RawGatewayUrl.TrimEnd("/") + "/mcp")
    $body = [ordered]@{
        jsonrpc = "2.0"
        id = "windows-native-smoke-work-preflight"
        method = "tools/call"
        params = [ordered]@{
            name = "zhiyi_recall"
            arguments = [ordered]@{
                query = "开始施工前先查已有机制"
                mode = "work_preflight"
                consumer = "windows-native-smoke"
                source_system = "codex"
                request_id = "windows-native-smoke-work-preflight"
                limit = 1
                excerpt_chars = 80
            }
        }
    } | ConvertTo-Json -Depth 10 -Compress

    try {
        $resp = Invoke-RestMethod -Uri $endpoint -Method Post -ContentType "application/json" -Body $body -TimeoutSec 10
    } catch {
        Fail-Smoke -Name "work_preflight" -Detail $_.Exception.Message
    }

    if ($resp.error) {
        Fail-Smoke -Name "work_preflight" -Detail ($resp.error | ConvertTo-Json -Compress)
    }
    if (-not $resp.result) {
        Fail-Smoke -Name "work_preflight" -Detail "missing JSON-RPC result"
    }

    $payload = $resp.result.structuredContent
    if (-not $payload -and $resp.result.content -and $resp.result.content.Count -gt 0) {
        try {
            $payload = $resp.result.content[0].text | ConvertFrom-Json
        } catch {
            Fail-Smoke -Name "work_preflight" -Detail "result content is not JSON"
        }
    }
    if (-not $payload) {
        Fail-Smoke -Name "work_preflight" -Detail "missing structuredContent"
    }

    $problems = @()
    if ($payload.mode -ne "work_preflight") { $problems += "mode" }
    if ($payload.contract -ne "agent_work_preflight.v2026.6.20") { $problems += "contract" }
    if ($payload.source_preflight_contract -ne "zhixing_preflight.v2026.6.20") { $problems += "source_preflight_contract" }
    if ($payload.prompt_class -ne "task") { $problems += "prompt_class" }
    if ($payload.should_intervene -ne $true) { $problems += "should_intervene" }
    if ($payload.read_only -ne $true) { $problems += "read_only" }
    if ($payload.write_performed -ne $false) { $problems += "write_performed" }
    if ($payload.model_call_performed -ne $false) { $problems += "model_call_performed" }
    if ($payload.raw_excerpt_returned -ne $false) { $problems += "raw_excerpt_returned" }
    if ($payload.consumer_receipt.receipt_scope -ne "agent_work_preflight_read_only") { $problems += "receipt_scope" }
    if (-not (@("diagnostic_gap", "already_built_but_forgotten", "built_but_miswired") -contains $payload.classification)) {
        $problems += "classification"
    }

    if ($problems.Count -gt 0) {
        Fail-Smoke -Name "work_preflight" -Detail ("unexpected fields: " + ($problems -join ","))
    }

    $script:Report["work_preflight"] = [ordered]@{
        mode = [string]$payload.mode
        classification = [string]$payload.classification
        decision = [string]$payload.decision
        prompt_class = [string]$payload.prompt_class
        should_intervene = [bool]$payload.should_intervene
        recall_status = [string]$payload.recall_status
        memory_scope = [string]$payload.memory_scope
        scope_missing = [bool]$payload.scope_missing
    }
    Add-Check -Name "work_preflight" -Ok $true -Detail (([string]$payload.classification) + "/" + ([string]$payload.decision))
}

function Find-CodexCli {
    $cmd = Get-Command codex -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }

    $codexHome = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE ".codex" }
    $candidateFiles = New-Object System.Collections.Generic.List[string]
    foreach ($base in @($codexHome, (Join-Path $env:USERPROFILE ".codex"))) {
        if ($base) {
            $candidateFiles.Add((Join-Path $base "chrome-native-hosts-v2.json"))
            $candidateFiles.Add((Join-Path $base "chrome-native-hosts.json"))
        }
    }
    if ($env:LOCALAPPDATA) {
        $candidateFiles.Add((Join-Path $env:LOCALAPPDATA "OpenAI\Codex\chrome-native-hosts-v2.json"))
        $candidateFiles.Add((Join-Path $env:LOCALAPPDATA "OpenAI\Codex\chrome-native-hosts.json"))
    }
    if ($env:APPDATA) {
        $candidateFiles.Add((Join-Path $env:APPDATA "OpenAI\Codex\chrome-native-hosts-v2.json"))
        $candidateFiles.Add((Join-Path $env:APPDATA "OpenAI\Codex\chrome-native-hosts.json"))
    }

    foreach ($file in ($candidateFiles | Select-Object -Unique)) {
        if (-not (Test-Path -LiteralPath $file)) { continue }
        try {
            $data = Get-Content -LiteralPath $file -Raw -Encoding UTF8 | ConvertFrom-Json
            $entries = @()
            if ($data.entries) {
                $entries = @($data.entries)
            } elseif ($data.chromeNativeHosts) {
                $entries = @($data.chromeNativeHosts)
            } elseif ($data.paths -or $data.path -or $data.codexCliPath) {
                $entries = @($data)
            }
            foreach ($entry in $entries) {
                $candidate = $null
                if ($entry.paths -and $entry.paths.codexCliPath) {
                    $candidate = [string]$entry.paths.codexCliPath
                } elseif ($entry.codexCliPath) {
                    $candidate = [string]$entry.codexCliPath
                } elseif ($entry.path) {
                    $candidate = [string]$entry.path
                }
                if ($candidate -and (Test-Path -LiteralPath $candidate)) {
                    return $candidate
                }
            }
        } catch { }
    }
    return $null
}

function Convert-TomlScalarForSmoke {
    param([string]$Value)
    $text = ([string]$Value).Trim()
    if ($text -match '^"((?:\\"|[^"])*)"') {
        return ($matches[1] -replace '\\"', '"')
    }
    if ($text -match "^'([^']*)'") {
        return $matches[1]
    }
    if ($text -match "^(true|false)\b") {
        return ($matches[1].ToLowerInvariant() -eq "true")
    }
    return (($text -split "\s+#", 2)[0]).Trim()
}

function Read-CodexConfigForSmoke {
    $codexHome = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE ".codex" }
    $configPath = Join-Path $codexHome "config.toml"
    if (-not (Test-Path -LiteralPath $configPath)) {
        return [ordered]@{
            path = $configPath
            exists = $false
            model = ""
            model_provider = ""
            provider_section_exists = $false
            base_url = ""
            wire_api = ""
        }
    }

    $top = @{}
    $sections = @{}
    $currentSection = ""
    foreach ($line in (Get-Content -LiteralPath $configPath -Encoding UTF8)) {
        $trimmed = ([string]$line).Trim()
        if ([string]::IsNullOrWhiteSpace($trimmed) -or $trimmed.StartsWith("#")) { continue }
        if ($trimmed -match "^\[([^\]]+)\]\s*$") {
            $currentSection = $matches[1].Trim()
            if (-not $sections.ContainsKey($currentSection)) { $sections[$currentSection] = @{} }
            continue
        }
        if ($trimmed -notmatch "^([A-Za-z0-9_.-]+)\s*=\s*(.+)$") { continue }
        $key = $matches[1]
        $value = Convert-TomlScalarForSmoke -Value $matches[2]
        if ([string]::IsNullOrWhiteSpace($currentSection)) {
            $top[$key] = $value
        } elseif ($sections.ContainsKey($currentSection)) {
            $sections[$currentSection][$key] = $value
        }
    }

    $provider = [string]($top["model_provider"])
    $sectionName = if ($provider) { "model_providers." + $provider } else { "" }
    $section = if ($sectionName -and $sections.ContainsKey($sectionName)) { $sections[$sectionName] } else { @{} }
    return [ordered]@{
        path = $configPath
        exists = $true
        model = [string]($top["model"])
        model_provider = $provider
        provider_section = $sectionName
        provider_section_exists = [bool]($sectionName -and $sections.ContainsKey($sectionName))
        base_url = [string]($section["base_url"])
        wire_api = [string]($section["wire_api"])
    }
}

function Get-HttpStatusCodeForSmoke {
    param(
        [string]$Url,
        [string]$Method = "Get",
        [string]$Body = ""
    )
    try {
        if ($Method -eq "Post") {
            $resp = Invoke-WebRequest -Uri $Url -Method Post -ContentType "application/json" -Body $Body -TimeoutSec 15 -UseBasicParsing
        } else {
            $resp = Invoke-WebRequest -Uri $Url -TimeoutSec 8 -UseBasicParsing
        }
        return [int]$resp.StatusCode
    } catch {
        $response = $_.Exception.Response
        if ($response -and $response.StatusCode) {
            return [int]$response.StatusCode
        }
        return 0
    }
}

function Test-CodexProviderBucket {
    if ($SkipCodex) {
        Add-Check -Name "codex_provider_bucket" -Ok $true -Detail "skipped"
        return
    }

    $config = Read-CodexConfigForSmoke
    if (-not $config.exists) {
        Add-Check -Name "codex_provider_bucket" -Ok $true -Detail ("Codex config missing; provider route probe skipped: " + [string]$config.path)
        $script:Report["codex_provider_bucket"] = [ordered]@{
            config_path = [string]$config.path
            exists = $false
            route_probe_required = $false
            reason = "codex_config_missing"
        }
        return
    }
    if ([string]::IsNullOrWhiteSpace($config.model_provider)) {
        Add-Check -Name "codex_provider_bucket" -Ok $true -Detail "no explicit provider bucket; official/default Codex route"
        $script:Report["codex_provider_bucket"] = [ordered]@{
            config_path = [string]$config.path
            exists = $true
            model = [string]$config.model
            model_provider = ""
            provider_bucket_matches_section = $false
            route_probe_required = $false
            reason = "official_or_default_codex_route"
        }
        return
    }
    Add-Check -Name "codex_provider_bucket" -Ok $true -Detail ("model_provider=" + [string]$config.model_provider)

    if (-not $config.provider_section_exists) {
        Fail-Smoke -Name "provider_bucket_matches_section" -Detail ("missing [" + [string]$config.provider_section + "]")
    }
    Add-Check -Name "provider_bucket_matches_section" -Ok $true -Detail ("found [" + [string]$config.provider_section + "]")

    if ([string]::IsNullOrWhiteSpace($config.base_url)) {
        Fail-Smoke -Name "codex_provider_bucket" -Detail "selected provider section is missing base_url"
    }
    if ([string]::IsNullOrWhiteSpace($config.wire_api)) {
        Fail-Smoke -Name "codex_provider_bucket" -Detail "selected provider section is missing wire_api"
    }

    $base = ([string]$config.base_url).TrimEnd("/")
    $usesLocalRelayProxy = (
        $base -eq "http://127.0.0.1:15721/v1" -or
        $base -eq "http://localhost:15721/v1"
    )
    if ($usesLocalRelayProxy) {
        Add-Check -Name "codex_provider_route_binding" -Ok $true -Detail ("selected [" + [string]$config.provider_section + "] owns the local relay route; provider bucket names are host-defined")
    }

    $modelsStatus = $null
    $responsesStatus = $null
    $healthStatus = $null
    if ($usesLocalRelayProxy) {
        $proxyRoot = $base.Substring(0, $base.Length - 3)
        $healthStatus = Get-HttpStatusCodeForSmoke -Url ($proxyRoot + "/health")
        if ($healthStatus -ne 200) {
            Fail-Smoke -Name "codex_local_proxy_health" -Detail ("HTTP " + [string]$healthStatus)
        }
        Add-Check -Name "codex_local_proxy_health" -Ok $true -Detail "HTTP 200"

        $modelsStatus = Get-HttpStatusCodeForSmoke -Url ($base + "/models")
        Add-Check -Name "models_404_not_fatal" -Ok $true -Detail ("HTTP " + [string]$modelsStatus + " diagnostic only")

        $probeModel = if ([string]::IsNullOrWhiteSpace($config.model)) { "gpt-5.5" } else { [string]$config.model }
        $body = [ordered]@{
            model = $probeModel
            input = "Say OK only."
            max_output_tokens = 8
        } | ConvertTo-Json -Depth 8 -Compress
        $responsesStatus = Get-HttpStatusCodeForSmoke -Url ($base + "/responses") -Method "Post" -Body $body
        if ($responsesStatus -ne 200) {
            Fail-Smoke -Name "codex_responses_probe" -Detail ("HTTP " + [string]$responsesStatus)
        }
        Add-Check -Name "codex_responses_probe" -Ok $true -Detail "HTTP 200"
    }

    $script:Report["codex_provider_bucket"] = [ordered]@{
        config_path = [string]$config.path
        model = [string]$config.model
        model_provider = [string]$config.model_provider
        provider_bucket_matches_section = [bool]$config.provider_section_exists
        provider_bucket_name_is_route_identity = $false
        base_url = [string]$config.base_url
        wire_api = [string]$config.wire_api
        local_relay_route = [bool]$usesLocalRelayProxy
        health_status = $healthStatus
        models_status = $modelsStatus
        models_404_not_fatal = $true
        responses_status = $responsesStatus
    }
}

function Test-CodexMcp {
    if ($SkipCodex) {
        Add-Check -Name "codex_mcp" -Ok $true -Detail "skipped"
        return
    }

    $codexExe = Find-CodexCli
    if (-not $codexExe) {
        Fail-Smoke -Name "codex_cli" -Detail "codex.exe not found from PATH or native-host metadata"
    }
    Add-Check -Name "codex_cli" -Ok $true -Detail $codexExe

    $output = & $codexExe mcp list 2>&1
    $exitCode = $LASTEXITCODE
    $text = ($output | Out-String)
    if ($exitCode -ne 0) {
        Fail-Smoke -Name "codex_mcp" -Detail ("codex mcp list failed: " + $text.Trim())
    }
    if ($text -notmatch "time-library") {
        Fail-Smoke -Name "codex_mcp" -Detail "time-library not found in codex mcp list"
    }
    Add-Check -Name "codex_mcp" -Ok $true -Detail "time-library enabled"
}

function Test-P0Watcher {
    $watcherCmdPath = Join-Path $InstallRoot "runtime\p0-watcher.cmd"
    if (-not (Test-Path -LiteralPath $watcherCmdPath)) {
        Fail-Smoke -Name "p0_watcher_source_scope" -Detail "runtime p0-watcher.cmd is missing"
    }
    $watcherCmdText = Get-Content -LiteralPath $watcherCmdPath -Raw -Encoding UTF8
    $watcherContractPatterns = [ordered]@{
        resource_profile = '(?im)^\s*set\s+"MEMCORE_WATCHER_RESOURCE_PROFILE=light"\s*$'
        source_default = '(?im)^\s*set\s+"MEMCORE_WATCHER_SOURCE_DEFAULT=all"\s*$'
        interval_ms = '(?im)^\s*set\s+"MEMCORE_WATCHER_INTERVAL_MS=5000"\s*$'
        source_argument = '(?im)^.*--watch\s+--source\s+all(?:\s|$).*$'
    }
    $missingContractFields = @()
    foreach ($entry in $watcherContractPatterns.GetEnumerator()) {
        if ($watcherCmdText -notmatch $entry.Value) {
            $missingContractFields += [string]$entry.Key
        }
    }
    if ($missingContractFields.Count -gt 0) {
        Fail-Smoke -Name "p0_watcher_source_scope" -Detail ("watcher launcher contract missing or invalid: " + ($missingContractFields -join ","))
    }
    Add-Check -Name "p0_watcher_source_scope" -Ok $true -Detail "light profile, all registered sources, 5000ms interval"

    $tree = @(Get-AuthorizedP0WatcherProcesses)
    $watchers = @($tree | Where-Object {
        Test-P0WatcherCommandLine -CommandLine ([string]$_.CommandLine)
    })
    if ($watchers.Count -eq 0) {
        Fail-Smoke -Name "p0_watcher_process" -Detail "p0 watcher is not running; local Codex/OpenClaw/Kiro records will not be captured continuously"
    }
    Add-Check -Name "p0_watcher_process" -Ok $true -Detail ("authorized tree PID " + [string]$watchers[0].ProcessId)
}

function Test-ScheduledTaskPresent {
    param(
        [string]$Name,
        [bool]$Required = $true,
        [string]$ExpectedLogonType = "",
        [switch]$RequireRecentSuccessfulRun,
        [switch]$RequireRunAfterBoot
    )
    $task = Get-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue
    if (-not $task) {
        if ($Required) {
            Fail-Smoke -Name ("scheduled_task_" + $Name) -Detail "missing"
        }
        Add-Check -Name ("scheduled_task_" + $Name) -Ok $false -Detail "missing"
        return
    }
    $settingsEnabled = ($null -ne $task.Settings) -and [bool]$task.Settings.Enabled
    $ok = ($task.State -ne "Disabled") -and $settingsEnabled
    if (-not $ok -and $Required) {
        Fail-Smoke `
            -Name ("scheduled_task_" + $Name) `
            -Detail ("disabled state=" + [string]$task.State + "; settings_enabled=" + [string]$settingsEnabled)
    }
    if (
        (-not [string]::IsNullOrWhiteSpace($ExpectedLogonType)) -and
        ([string]$task.Principal.LogonType -ne $ExpectedLogonType)
    ) {
        Fail-Smoke `
            -Name ("scheduled_task_" + $Name) `
            -Detail ("expected principal_logon_type=" + $ExpectedLogonType + "; actual=" + [string]$task.Principal.LogonType)
    }
    $actionArgs = (@($task.Actions | ForEach-Object { [string]$_.Arguments }) -join " ")
    $actionExe = (@($task.Actions | ForEach-Object { [string]$_.Execute }) -join " ")
    if ($Name -match "^MemcoreCloudGuardian") {
        if ($actionExe -notmatch "wscript\.exe") {
            Fail-Smoke -Name ("scheduled_task_" + $Name) -Detail "guardian task must use wscript hidden launcher; powershell.exe can flash a console window"
        }
        if ($actionArgs -notmatch "windows_hidden_guardian\.vbs") {
            Fail-Smoke -Name ("scheduled_task_" + $Name) -Detail "guardian hidden launcher is missing"
        }
    }
    if (($Name -eq "MemcoreCloudTray") -and ($actionArgs -notmatch "-WindowStyle\s+Hidden")) {
        Fail-Smoke -Name ("scheduled_task_" + $Name) -Detail "tray task action is not hidden; a console window may flash"
    }
    $runDetail = ""
    if ($RequireRecentSuccessfulRun -or $RequireRunAfterBoot) {
        $info = Get-ScheduledTaskInfo -TaskName $Name -ErrorAction Stop
        $lastRun = [datetime]$info.LastRunTime
        $lastResult = [uint32]$info.LastTaskResult
        $running = ([string]$task.State -eq "Running")
        if ($RequireRecentSuccessfulRun) {
            $recent = ($lastRun -gt (Get-Date).AddMinutes(-20))
            if ((-not $recent) -or ((-not $running) -and ($lastResult -ne 0))) {
                Fail-Smoke `
                    -Name ("scheduled_task_" + $Name) `
                    -Detail ("background task has no recent successful execution; state=" + [string]$task.State + "; last_run=" + $lastRun.ToString("o") + "; last_result=" + ("{0} (0x{1:X8})" -f [uint64]$lastResult, [uint64]$lastResult) + "; inspect SeBatchLogonRight/SeDenyBatchLogonRight and TaskScheduler Operational events")
            }
            $runDetail += "; recent_20m=" + [string]$recent
        }
        if ($RequireRunAfterBoot) {
            $lastBoot = [datetime](Get-CimInstance Win32_OperatingSystem -ErrorAction Stop).LastBootUpTime
            $postBoot = ($lastRun -gt $lastBoot)
            if (-not $postBoot) {
                Fail-Smoke `
                    -Name ("scheduled_task_" + $Name) `
                    -Detail ("background task has not run after this boot; last_run=" + $lastRun.ToString("o") + "; last_boot=" + $lastBoot.ToString("o"))
            }
            $runDetail += "; last_boot=" + $lastBoot.ToString("o") + "; post_boot=" + [string]$postBoot
        }
        $runDetail = "; last_run=" + $lastRun.ToString("o") + "; last_result=" + ("{0} (0x{1:X8})" -f [uint64]$lastResult, [uint64]$lastResult) + $runDetail
    }
    Add-Check `
        -Name ("scheduled_task_" + $Name) `
        -Ok $ok `
        -Detail ("state=" + [string]$task.State + "; settings_enabled=" + [string]$settingsEnabled + "; principal_logon_type=" + [string]$task.Principal.LogonType + $runDetail)
}

function Merge-WindowsGuardianCoverage {
    param(
        [object]$Payload,
        [string]$Source
    )
    if ($null -eq $Payload) {
        Fail-Smoke -Name "windows_guardian_coverage" -Detail "$Source payload is missing"
    }
    $fields = @($Payload.PSObject.Properties.Name)
    foreach ($field in @("ok", "measurement_status", "full_health_check", "not_measured_layers", "generated_at")) {
        if ($field -notin $fields) {
            Fail-Smoke -Name "windows_guardian_coverage" -Detail "$Source payload is missing $field"
        }
    }
    if ($Payload.ok -isnot [bool]) {
        Fail-Smoke -Name "windows_guardian_coverage" -Detail "$Source ok must be boolean"
    }
    if ($Payload.measurement_status -isnot [string]) {
        Fail-Smoke -Name "windows_guardian_coverage" -Detail "$Source measurement_status must be a string"
    }
    if ($Payload.full_health_check -isnot [bool]) {
        Fail-Smoke -Name "windows_guardian_coverage" -Detail "$Source full_health_check must be boolean"
    }
    if ($Payload.not_measured_layers -isnot [System.Array]) {
        Fail-Smoke -Name "windows_guardian_coverage" -Detail "$Source not_measured_layers must be an array"
    }
    if (
        ($Payload.generated_at -isnot [string]) -or
        [string]::IsNullOrWhiteSpace([string]$Payload.generated_at)
    ) {
        Fail-Smoke -Name "windows_guardian_coverage" -Detail "$Source generated_at must be a non-empty string"
    }
    try {
        [void]([datetime]$Payload.generated_at)
    } catch {
        Fail-Smoke -Name "windows_guardian_coverage" -Detail "$Source generated_at is invalid"
    }
    $measurementStatus = [string]$Payload.measurement_status
    $notMeasuredLayers = @($Payload.not_measured_layers)
    if ($measurementStatus -notin @("complete", "partial")) {
        Fail-Smoke -Name "windows_guardian_coverage" -Detail "$Source measurement_status must be complete or partial"
    }
    if (@($notMeasuredLayers | Where-Object { ($_ -isnot [string]) -or [string]::IsNullOrWhiteSpace($_) }).Count -gt 0) {
        Fail-Smoke -Name "windows_guardian_coverage" -Detail "$Source not_measured_layers must contain non-empty strings"
    }
    if (
        ($measurementStatus -eq "complete") -and
        ((-not [bool]$Payload.full_health_check) -or ($notMeasuredLayers.Count -ne 0))
    ) {
        Fail-Smoke -Name "windows_guardian_coverage" -Detail "$Source complete coverage is inconsistent"
    }
    if (
        ($measurementStatus -eq "partial") -and
        ([bool]$Payload.full_health_check -or ($notMeasuredLayers.Count -eq 0))
    ) {
        Fail-Smoke -Name "windows_guardian_coverage" -Detail "$Source partial coverage is inconsistent"
    }
    if (-not [bool]$Payload.ok) {
        Fail-Smoke -Name "windows_guardian_run" -Detail "$Source Guardian payload reported ok=false"
    }
    foreach ($layer in $notMeasuredLayers) {
        $name = "windows_guardian:" + [string]$layer
        if ($name -notin @($script:Report.not_measured_layers)) {
            Add-NotMeasuredCheck `
                -Name $name `
                -Detail ("nested Guardian coverage is partial: " + [string]$layer)
        }
    }
    return $measurementStatus
}

function Test-GuardianAndTray {
    $consoleUrl = $RawGatewayUrl
    $guardian = Join-Path $InstallRoot "tools\windows_guardian.ps1"
    $hiddenGuardian = Join-Path $InstallRoot "tools\windows_hidden_guardian.vbs"
    $tray = Join-Path $InstallRoot "tools\windows_tray.ps1"
    Test-PathRequired -Name "windows_guardian_script" -Path $guardian
    Test-PathRequired -Name "windows_hidden_guardian_launcher" -Path $hiddenGuardian
    Test-PathRequired -Name "windows_tray_script" -Path $tray

    if ($SkipScheduledTaskChecks) {
        Add-NotMeasuredCheck `
            -Name "scheduled_tasks" `
            -Detail "explicit -NoAutostart preservation path; scheduled-task contract not measured and background recovery not inferred"
    } else {
        Test-ScheduledTaskPresent -Name "MemcoreCloudGuardianLogon" -ExpectedLogonType "Interactive"
        Test-ScheduledTaskPresent `
            -Name "MemcoreCloudGuardianHealth" `
            -ExpectedLogonType "S4U" `
            -RequireRecentSuccessfulRun `
            -RequireRunAfterBoot:$RequireBackgroundRecoveryAfterBoot
        if ($SkipCodexGuardTaskCheck) {
            Add-NotMeasuredCheck `
                -Name "scheduled_task_MemcoreCloudCodexMcpGuard" `
                -Detail "explicit preserved-guard path; principal not measured"
        } else {
            Test-ScheduledTaskPresent `
                -Name "MemcoreCloudCodexMcpGuard" `
                -ExpectedLogonType "S4U" `
                -RequireRunAfterBoot:$RequireBackgroundRecoveryAfterBoot
        }
        Test-ScheduledTaskPresent -Name "MemcoreCloudTray" -ExpectedLogonType "Interactive" -Required:$false
    }

    $powershellExe = Join-Path $PSHOME "powershell.exe"
    $guardianArgs = @(
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $guardian,
        "-InstallRoot", $InstallRoot, "-StartWatcher", "-Json"
    )
    if ($SkipCodex) {
        $guardianArgs += "-NoStatusWrite"
    } else {
        $guardianArgs += "-Backfill"
    }
    if ($SkipScheduledTaskChecks) {
        $guardianArgs += "-SkipScheduledTaskChecks"
    }
    if ($SkipCodexGuardTaskCheck) {
        $guardianArgs += "-SkipCodexMcpGuardTaskCheck"
    }
    if ($RequireBackgroundRecoveryAfterBoot) {
        $guardianArgs += "-RequireBackgroundRecoveryAfterBoot"
    }
    $guardianInvocationStarted = (Get-Date).ToUniversalTime()
    $output = & $powershellExe @guardianArgs 2>&1
    $exitCode = $LASTEXITCODE
    $text = ($output | Out-String)
    if ($exitCode -ne 0) {
        Fail-Smoke -Name "windows_guardian_run" -Detail $text.Trim()
    }
    try {
        $payload = $text | ConvertFrom-Json
    } catch {
        Fail-Smoke -Name "windows_guardian_run" -Detail "guardian returned non-JSON"
    }
    $payloadCoverage = Merge-WindowsGuardianCoverage -Payload $payload -Source "process_output"
    $payloadFields = @($payload.PSObject.Properties.Name)
    if (("skipped" -in $payloadFields) -and [bool]$payload.skipped) {
        if ([string]$payload.reason -ne "guardian_already_running") {
            Fail-Smoke -Name "windows_guardian_run" -Detail ("unexpected Guardian skip reason: " + [string]$payload.reason)
        }
        if ($payloadCoverage -ne "partial") {
            Fail-Smoke -Name "windows_guardian_coverage" -Detail "concurrent Guardian skip must be partial"
        }
        return
    }
    $statusPath = Join-Path $InstallRoot "runtime\guardian-status.json"
    if ($SkipCodex) {
        $statusPayload = $payload
    } else {
        Test-PathRequired -Name "windows_guardian_status" -Path $statusPath
        try {
            $statusPayload = Get-Content -LiteralPath $statusPath -Raw -Encoding UTF8 | ConvertFrom-Json
        } catch {
            Fail-Smoke -Name "guardian_status_content" -Detail "guardian-status.json is not valid JSON"
        }
        try {
            $statusWriteTime = (Get-Item -LiteralPath $statusPath -ErrorAction Stop).LastWriteTimeUtc
        } catch {
            Fail-Smoke -Name "guardian_status_content" -Detail "guardian-status.json metadata is unavailable"
        }
        $statusCoverage = Merge-WindowsGuardianCoverage -Payload $statusPayload -Source "status_file"
        try {
            $statusGeneratedAt = ([datetime]$statusPayload.generated_at).ToUniversalTime()
        } catch {
            Fail-Smoke -Name "guardian_status_content" -Detail "guardian-status.json generated_at is invalid"
        }
        if ($statusGeneratedAt -lt $guardianInvocationStarted.AddSeconds(-1)) {
            Fail-Smoke `
                -Name "guardian_status_content" `
                -Detail ("guardian-status.json is stale for this invocation; generated_at=" + $statusGeneratedAt.ToString("o") + "; invocation_started=" + $guardianInvocationStarted.ToString("o"))
        }
        if ($statusWriteTime -lt $guardianInvocationStarted) {
            Fail-Smoke `
                -Name "guardian_status_content" `
                -Detail ("guardian-status.json was not written by this invocation; last_write=" + $statusWriteTime.ToString("o") + "; invocation_started=" + $guardianInvocationStarted.ToString("o"))
        }
    }
    if ($SkipCodex) {
        try {
            $recordStatus = Invoke-RestMethod `
                -Uri ($consoleUrl + "/api/v1/records/guardian/status?limit=80&mode=fast&compact=1") `
                -UseBasicParsing `
                -TimeoutSec 60
        } catch {
            Fail-Smoke -Name "guardian_record_attention" -Detail ("record Guardian query failed: " + $_.Exception.Message)
        }
        $summary = $recordStatus.summary
        $lostSourceCount = [int]$summary.lost_source_count
        $triageFields = @(
            "lost_source_recoverable_count",
            "lost_source_unrecoverable_count",
            "lost_source_not_measured_count"
        )
        $summaryFields = @($summary.PSObject.Properties.Name)
        $hasCompleteTriage = @($triageFields | Where-Object { $_ -in $summaryFields }).Count -eq $triageFields.Count
        $lostSourceRecoverable = [int]$summary.lost_source_recoverable_count
        $lostSourceUnrecoverable = [int]$summary.lost_source_unrecoverable_count
        $lostSourceNotMeasured = [int]$summary.lost_source_not_measured_count
        $lostSourceOneSided = [int]$summary.lost_source_one_sided_count
        $lostSourceNonConversation = [int]$summary.lost_source_non_conversation_count
        if ((-not $hasCompleteTriage) -or (($lostSourceRecoverable + $lostSourceUnrecoverable + $lostSourceNotMeasured) -ne $lostSourceCount)) {
            $lostSourceUnrecoverable = $lostSourceCount
        }
        if (($lostSourceOneSided + $lostSourceNonConversation) -gt $lostSourceRecoverable) {
            Fail-Smoke -Name "guardian_recoverability_subtypes" -Detail "recoverable subtype counts exceed lost_source_recoverable_count"
        }
        if ($null -eq $recordStatus.summary_scope) {
            Fail-Smoke -Name "guardian_summary_scope" -Detail "summary scope evidence is missing"
        } elseif ($recordStatus.summary_scope.summary_is_sample) {
            Add-Check -Name "guardian_summary_scope" -Ok $true -Detail "bounded population sample; trend comparison must use scope key"
        } else {
            Add-Check -Name "guardian_summary_scope" -Ok $true -Detail "population complete"
        }
        $attention = [int]$summary.raw_attention_count +
            $lostSourceUnrecoverable +
            [int]$summary.lost_raw_count +
            [int]$summary.corrupt_record_count
        if ($attention -gt 0) {
            $detail = (
                "record attention preserved; raw_attention={0} lost_source_unrecoverable={1} lost_raw={2} corrupt={3}" -f
                [int]$summary.raw_attention_count,
                $lostSourceUnrecoverable,
                [int]$summary.lost_raw_count,
                [int]$summary.corrupt_record_count
            )
            Add-Check -Name "guardian_status_attention" -Ok $true -Detail $detail -Data $summary
        } elseif (-not $statusPayload.ok -or -not $recordStatus.ok) {
            Fail-Smoke -Name "guardian_status_content" -Detail "Guardian is not ok without record-attention evidence"
        } else {
            Add-Check -Name "guardian_status_content" -Ok $true -Detail "ok"
        }
    } elseif (-not $statusPayload.ok) {
        Fail-Smoke -Name "guardian_status_content" -Detail "guardian status file is not ok"
    } else {
        Add-Check -Name "guardian_status_content" -Ok $true -Detail "ok"
    }
    $guardianDetail = if ($script:Report.measurement_status -eq "partial") {
        "measured checks passed; nested Guardian coverage is partial"
    } else {
        "ok"
    }
    Add-Check -Name "windows_guardian_run" -Ok $true -Detail $guardianDetail
}

function Test-CodexCaptureStatus {
    if ($SkipCodex) {
        Add-Check -Name "codex_capture_status" -Ok $true -Detail "skipped"
        return
    }

    $python = Join-Path $InstallRoot ".venv\Scripts\python.exe"
    $connector = Join-Path $InstallRoot "src\codex_local_connector.py"
    Test-PathRequired -Name "codex_connector" -Path $connector
    if (-not (Test-Path -LiteralPath $python)) {
        Fail-Smoke -Name "codex_capture_status" -Detail "missing venv python: $python"
    }

    $env:MEMCORE_ROOT = $InstallRoot
    $env:MEMCORE_INSTALL_ROOT = $InstallRoot
    $env:PYTHONPATH = $InstallRoot
    $payload = $null
    $lastText = ""
    $lastExitCode = 0
    $captureStatusMaxAttempts = 8
    $captureStatusPollMilliseconds = 5000
    for ($attempt = 1; $attempt -le $captureStatusMaxAttempts; $attempt++) {
        $payload = $null
        $output = & $python $connector --status 2>&1
        $lastExitCode = $LASTEXITCODE
        $lastText = ($output | Out-String)
        if ($lastExitCode -eq 0) {
            try {
                $payload = ConvertFrom-JsonOutput -Text $lastText
            } catch { }
        }
        if ($payload) {
            $candidateRawSync = $payload.raw_sync
            $candidateStatus = if ($candidateRawSync -and $candidateRawSync.status) {
                [string]$candidateRawSync.status
            } else {
                ""
            }
            if (($candidateStatus -notin @("raw_missing", "raw_lagging_sla_breach")) -or ($attempt -eq $captureStatusMaxAttempts)) {
                break
            }
            $reportedInterval = 0
            try { $reportedInterval = [int]$payload.poll_interval_milliseconds } catch { }
            if ($reportedInterval -gt 0) {
                $captureStatusPollMilliseconds = [Math]::Max(1000, [Math]::Min(5000, $reportedInterval))
            }
            Start-Sleep -Milliseconds $captureStatusPollMilliseconds
            continue
        }
        if ($attempt -lt $captureStatusMaxAttempts) {
            Start-Sleep -Milliseconds 750
        }
    }
    if ($lastExitCode -ne 0) {
        Fail-Smoke -Name "codex_capture_status" -Detail ("codex connector status failed: " + $lastText.Trim())
    }
    if (-not $payload) {
        Fail-Smoke -Name "codex_capture_status" -Detail "codex connector status returned non-JSON"
    }

    if (-not $payload.capture_independent_of_mcp) {
        Fail-Smoke -Name "codex_capture_status" -Detail "codex capture must be independent of Skill/MCP consumer config"
    }
    if (-not $payload.reachable) {
        Fail-Smoke -Name "codex_capture_status" -Detail "Codex sessions root not reachable"
    }

    $rawSync = $payload.raw_sync
    if (-not $rawSync) {
        Fail-Smoke -Name "codex_capture_status" -Detail "missing raw_sync status"
    }
    if ($rawSync.status -in @("raw_missing", "raw_lagging_sla_breach")) {
        $detail = (
            "Codex source records remain ahead after {0} bounded checks; status={1} missing/stale={2} lag_bytes={3} lag_ms={4} sla_breaches={5}" -f
            $captureStatusMaxAttempts,
            [string]$rawSync.status,
            [string]$rawSync.missing_or_stale_count,
            [string]$rawSync.raw_archive_total_lag_bytes,
            [string]$rawSync.raw_archive_max_lag_milliseconds,
            [string]$rawSync.raw_lag_sla_breach_count
        )
        Fail-Smoke -Name "codex_capture_status" -Detail $detail
    }
    if ($rawSync.status -eq "source_unreachable") {
        Fail-Smoke -Name "codex_capture_status" -Detail "Codex source records are unreachable"
    }

    $script:Report["codex_capture"] = [ordered]@{
        independent_of_mcp = [bool]$payload.capture_independent_of_mcp
        status = [string]$rawSync.status
        latest_source_mtime = [string]$rawSync.latest_source_mtime
        latest_raw_mtime = [string]$rawSync.latest_raw_mtime
        missing_or_stale_count = [int]$rawSync.missing_or_stale_count
        raw_archive_max_lag_bytes = [int]$rawSync.raw_archive_max_lag_bytes
        raw_archive_max_lag_milliseconds = [int]$rawSync.raw_archive_max_lag_milliseconds
        raw_lag_sla_breach_count = [int]$rawSync.raw_lag_sla_breach_count
    }
    Add-Check -Name "codex_capture_status" -Ok $true -Detail ("raw_sync=" + [string]$rawSync.status)
}

function Test-CodexConsumerMcpOptional {
    if ($SkipCodex) {
        Add-Check -Name "codex_consumer_mcp_optional" -Ok $true -Detail "skipped"
        return
    }

    $codexExe = Find-CodexCli
    if (-not $codexExe) {
        Add-Check -Name "codex_consumer_mcp_optional" -Ok $false -Detail "codex.exe not found; capture status is checked separately"
        return
    }

    $output = & $codexExe mcp list 2>&1
    $exitCode = $LASTEXITCODE
    $text = ($output | Out-String)
    if ($exitCode -ne 0) {
        Add-Check -Name "codex_consumer_mcp_optional" -Ok $false -Detail ("codex mcp list failed: " + $text.Trim())
        return
    }
    if ($text -notmatch "time-library") {
        Add-Check -Name "codex_consumer_mcp_optional" -Ok $false -Detail "time-library missing from Codex consumer MCP; local capture still uses source files"
        return
    }
    Add-Check -Name "codex_consumer_mcp_optional" -Ok $true -Detail "time-library enabled"
}

Read-Version
Test-P0Watcher
Test-GuardianAndTray
Smoke-Http -Name "front_door_health" -Url ($RawGatewayUrl.TrimEnd("/") + "/health")
Smoke-Http -Name "front_door_console_health" -Url ($RawGatewayUrl.TrimEnd("/") + "/api/health")
Test-ZhiyiModelBinding
Invoke-CapabilityCheck
Invoke-WorkPreflightCheck
Test-CodexProviderBucket
Test-CodexCaptureStatus
Test-CodexConsumerMcpOptional

Finish-Report -Ok $true
