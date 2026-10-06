# setup_venv.ps1 — create the "jobs" virtual environment and install dependencies (Windows).
# Usage (from the repo root, in PowerShell):
#     powershell -ExecutionPolicy Bypass -File scripts\setup_venv.ps1
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

if (-not (Test-Path "jobs\Scripts\python.exe")) {
    Write-Host "Creating virtual environment 'jobs'..."
    py -3 -m venv jobs
}
& .\jobs\Scripts\python.exe -m pip install --upgrade pip
& .\jobs\Scripts\python.exe -m pip install -r requirements.txt

foreach ($pair in @(
    @(".env.example", ".env"),
    @("job_preference.example.md", "job_preference.md"),
    @("resume_details.example.md", "resume_details.md")
)) {
    if ((Test-Path $pair[0]) -and -not (Test-Path $pair[1])) {
        Copy-Item $pair[0] $pair[1]
        Write-Host "Created $($pair[1]) from $($pair[0]) - edit it with your details."
    }
}
Write-Host ""
Write-Host "Done. Activate with:  .\jobs\Scripts\Activate.ps1"
