# install_windows_task.ps1 — keep the job scraper running on this Windows PC.
#
# Registers a Task Scheduler task "JobScraper" that:
#   * starts the scheduler daemon (no console window) when you log on,
#   * wakes the PC at 20:55 every day so the 21:00 IST digest is sent,
#   * restarts it if it crashes.
#
# Usage (PowerShell, from the repo root, after scripts\setup_venv.ps1):
#     powershell -ExecutionPolicy Bypass -File scripts\install_windows_task.ps1
# Remove:
#     powershell -ExecutionPolicy Bypass -File scripts\install_windows_task.ps1 -Uninstall
param([switch]$Uninstall)
$ErrorActionPreference = "Stop"
$TaskName = "JobScraper"
$Repo = Split-Path -Parent $PSScriptRoot

if ($Uninstall) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed task '$TaskName'."
    return
}

$Pythonw = Join-Path $Repo "jobs\Scripts\pythonw.exe"
if (-not (Test-Path $Pythonw)) { throw "Virtual environment not found. Run scripts\setup_venv.ps1 first." }

$Action   = New-ScheduledTaskAction -Execute $Pythonw -Argument "-m jobscraper daemon" -WorkingDirectory $Repo
$AtLogon  = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
# 20:55 local time; set Windows to India Standard Time or change this to 21:00 IST in your zone.
$Nightly  = New-ScheduledTaskTrigger -Daily -At "20:55"
$Settings = New-ScheduledTaskSettingsSet -WakeToRun -StartWhenAvailable -AllowStartIfOnBatteries `
            -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew `
            -RestartCount 10 -RestartInterval (New-TimeSpan -Minutes 5) `
            -ExecutionTimeLimit ([TimeSpan]::Zero)

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger @($AtLogon, $Nightly) `
    -Settings $Settings -Description "Company job scraper: scans, LeetCode company sync, 21:00 IST Gmail digest" `
    -Force | Out-Null

Start-ScheduledTask -TaskName $TaskName
Write-Host "Task '$TaskName' installed and started. Logs: $Repo\logs\jobscraper.log"
