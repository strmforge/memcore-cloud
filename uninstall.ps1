#Requires -Version 5.1
# ============================================================
# Time Library Uninstaller (Windows)
# Usage:
#   .\uninstall.ps1
#   .\uninstall.ps1 -InstallDir "D:\Apps\time-library"
# ============================================================
# This removes ONLY the software installation.
# User data (memory/, raw/, zhiyi/, output/) is preserved.

param(
    [string]$InstallDir = ""
)

$ErrorActionPreference = "Stop"

if (-not $InstallDir) {
    if (-not [string]::IsNullOrWhiteSpace($env:TIME_LIBRARY_INSTALL_DIR)) {
        $InstallDir = $env:TIME_LIBRARY_INSTALL_DIR
    } elseif (-not [string]::IsNullOrWhiteSpace($env:TIME_LIBRARY_ROOT)) {
        $InstallDir = $env:TIME_LIBRARY_ROOT
    } elseif (-not [string]::IsNullOrWhiteSpace($env:MEMCORE_INSTALL_DIR)) {
        $InstallDir = $env:MEMCORE_INSTALL_DIR
    } elseif (-not [string]::IsNullOrWhiteSpace($env:MEMCORE_ROOT)) {
        $InstallDir = $env:MEMCORE_ROOT
    } else {
        $newDefault = Join-Path $env:LOCALAPPDATA "time-library"
        $legacyDefault = Join-Path $env:LOCALAPPDATA "memcore-cloud"
        if ((Test-Path -LiteralPath $newDefault) -or -not (Test-Path -LiteralPath $legacyDefault)) {
            $InstallDir = $newDefault
        } else {
            $InstallDir = $legacyDefault
        }
    }
}

function info($msg) { Write-Host "[time-library] $msg" }
function warn($msg) { Write-Host "[time-library WARNING] $msg" }
function error_exit($msg) { Write-Host "[time-library ERROR] $msg" >&2; exit 1 }

if (-not (Test-Path $InstallDir)) {
    error_exit "Installation directory does not exist: $InstallDir"
}

Write-Host ""
Write-Host "=============================================="
Write-Host " Time Library Uninstaller (Windows)"
Write-Host "=============================================="
Write-Host ""
info "Install directory: $InstallDir"
Write-Host ""
Write-Host "This will remove the software at $InstallDir."
Write-Host ""
Write-Host "The following user data will be PRESERVED (not deleted):"
Write-Host "  - memory/"
Write-Host "  - raw/"
Write-Host "  - zhiyi/"
Write-Host "  - xingce/"
Write-Host "  - output/"
Write-Host "  - config/"
Write-Host "  - any backup directories"
Write-Host ""
Write-Host "Remove software only? [Y/n]"
$confirm = Read-Host
if ($confirm -eq "n") { Write-Host "Aborted."; exit 0 }

# Unregister user-mode autostart and guardian tasks.
foreach ($TaskName in @(
    "MemcoreCloudConsole",
    "MemcoreCloudGuardianLogon",
    "MemcoreCloudGuardianHealth",
    "MemcoreCloudCodexMcpGuard",
    "MemcoreCloudTray"
)) {
    $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($existing) {
        info "Removing Scheduled Task '$TaskName'..."
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
        info "Scheduled Task removed."
    }
}

# Stop running Time Library processes for this install root.
info "Stopping Time Library processes if running..."
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object {
        $cmd = [string]$_.CommandLine
        $cmd -and (
            $cmd -like "*$InstallDir\src\*.py*" -or
            $cmd -like "*$InstallDir\runtime\*.cmd*" -or
            $cmd -like "*$InstallDir\tools\windows_guardian.ps1*" -or
            $cmd -like "*$InstallDir\tools\codex_mcp_config_guard.py*" -or
            $cmd -like "*$InstallDir\tools\windows_tray.ps1*"
        )
    } |
    ForEach-Object {
        Stop-Process -Id ([int]$_.ProcessId) -Force -ErrorAction SilentlyContinue
    }

# Also try netstat-based fallback (find process on 9850 port)
try {
    $connections = netstat -ano | Select-String ":9850 " | Select-String "LISTENING"
    if ($connections) {
        foreach ($c in $connections) {
            $parts = $c.ToString().Trim().Split() -ne ''
            $listenerPid = $parts[-1]
            if ($listenerPid) { Stop-Process -Id $listenerPid -Force -ErrorAction SilentlyContinue }
        }
    }
} catch { }

# Remove software files while preserving local data.
info "Removing software from $InstallDir (preserving local data)..."
$softwareItems = @(
    "src",
    "web",
    "tools",
    "scripts",
    "docs",
    "packaging",
    "system",
    "tests",
    "runtime",
    ".venv",
    "VERSION",
    "README.md",
    "README.en.md",
    "README.zh-CN.md",
    "LICENSE",
    "CHANGELOG.md",
    "install.sh",
    "install.ps1",
    "uninstall.sh",
    "uninstall.ps1",
    "requirements.txt",
    "requirements-core.txt",
    "requirements-vector.txt",
    "requirements-dev.txt",
    "PACKAGING.md",
    "CURRENT_BASELINE.md",
    "CURRENT_STATE.md",
    ("AGENTS" + ".md"),
    "update_staging"
)
foreach ($item in $softwareItems) {
    $path = Join-Path $InstallDir $item
    if (Test-Path -LiteralPath $path) {
        Remove-Item -LiteralPath $path -Recurse -Force -ErrorAction SilentlyContinue
    }
}
Get-ChildItem -LiteralPath $InstallDir -Filter "*.py" -File -ErrorAction SilentlyContinue |
    Remove-Item -Force -ErrorAction SilentlyContinue
foreach ($configName in @(
    "alias_map.json",
    "model_config.json",
    "feature_flags.json",
    "window_binding_registry.json",
    "init_state.json"
)) {
    $path = Join-Path (Join-Path $InstallDir "config") $configName
    if (Test-Path -LiteralPath $path) {
        Remove-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue
    }
}

Write-Host ""
Write-Host "=============================================="
Write-Host " Uninstallation complete!"
Write-Host "=============================================="
Write-Host ""
Write-Host "Software removed. Your data has been preserved."
Write-Host ""
Write-Host "To reinstall, run:"
Write-Host "  iwr https://github.com/strmforge/time-library/releases/download/v2026.8.13/install.ps1 -OutFile .\install.ps1"
Write-Host "  .\install.ps1"
Write-Host ""
