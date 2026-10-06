# run_daemon.ps1 — run the scheduler in this terminal (Ctrl+C to stop).
#     powershell -ExecutionPolicy Bypass -File scripts\run_daemon.ps1
Set-Location (Split-Path -Parent $PSScriptRoot)
& .\jobs\Scripts\python.exe -m jobscraper daemon
