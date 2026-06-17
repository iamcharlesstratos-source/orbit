# Register / unregister a daily Windows scheduled task for Orbit (Product Research Agent).
#
# Usage:
#   .\register_daily_task.ps1                       # default 06:00
#   .\register_daily_task.ps1 -Time "07:30"         # custom time
#   .\register_daily_task.ps1 -Remove               # uninstall
#   .\register_daily_task.ps1 -RunNow               # trigger immediately
#
# No admin required (per-user task).

param(
    [string]$Time = "06:00",
    [switch]$Remove = $false,
    [switch]$RunNow = $false,
    [string]$TaskName = "OrbitDailyScrape"
)

$ErrorActionPreference = "Stop"
$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Definition

# ---- Remove path ----
if ($Remove) {
    try {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction Stop
        Write-Host "OK Removed scheduled task '$TaskName'." -ForegroundColor Green
    } catch {
        Write-Host "(No existing task '$TaskName' found, or removal failed.)" -ForegroundColor Yellow
    }
    exit 0
}

# ---- RunNow path ----
if ($RunNow) {
    try {
        Start-ScheduledTask -TaskName $TaskName -ErrorAction Stop
        Write-Host "OK Triggered task '$TaskName' to run now." -ForegroundColor Green
    } catch {
        Write-Host "ERROR: Task '$TaskName' is not registered. Run without -RunNow first." -ForegroundColor Red
        exit 1
    }
    exit 0
}

# ---- Register / re-register path ----
if ($Time -notmatch '^([01][0-9]|2[0-3]):[0-5][0-9]$') {
    Write-Host "ERROR: -Time must be HH:mm (e.g. 06:30). Got: $Time" -ForegroundColor Red
    exit 1
}

$python = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $python) {
    $python = (Get-Command py -ErrorAction SilentlyContinue).Source
}
if (-not $python) {
    Write-Host "ERROR: python not found on PATH." -ForegroundColor Red
    exit 1
}

$runScript = Join-Path $projectDir "run_daily.ps1"

# Wrapper that does scrape + diff + notify
$wrapper = @"
Set-Location -Path "$projectDir"
& "$python" "$projectDir\main.py"
& "$python" "$projectDir\main.py" --diff
& "$python" "$projectDir\main.py" --notify
"@

Set-Content -Path $runScript -Value $wrapper -Encoding utf8

# Build the trigger from HH:mm
$hour, $minute = $Time -split ':'
$at = [DateTime]::Today.AddHours([int]$hour).AddMinutes([int]$minute)

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$runScript`"" `
    -WorkingDirectory $projectDir

$trigger = New-ScheduledTaskTrigger -Daily -At $at

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopOnIdleEnd `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1) `
    -RestartCount 1 `
    -RestartInterval (New-TimeSpan -Minutes 15)

$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask `
    -TaskName $TaskName `
    -Description "Daily PH Meta Ads Library scrape + diff + notify" `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Force | Out-Null

Write-Host ""
Write-Host "OK Daily scrape scheduled at $Time" -ForegroundColor Green
Write-Host "Task name : $TaskName"
Write-Host "Wrapper   : $runScript"
Write-Host "Logs      : $projectDir\logs\agent.log"
Write-Host ""
Write-Host "Manage:"
Write-Host "  Run now      : .\register_daily_task.ps1 -RunNow"
Write-Host "  Change time  : .\register_daily_task.ps1 -Time 07:30"
Write-Host "  Remove       : .\register_daily_task.ps1 -Remove"
Write-Host "  Query        : Get-ScheduledTask -TaskName $TaskName"
