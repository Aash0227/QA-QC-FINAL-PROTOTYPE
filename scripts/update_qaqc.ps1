# update_qaqc.ps1 — pull the latest QA-QC release and refresh dependencies.
# Run from anywhere:  powershell -ExecutionPolicy Bypass -File <repo>\scripts\update_qaqc.ps1
$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

Write-Host "Pulling latest code..." -ForegroundColor Cyan
git pull
if ($LASTEXITCODE -ne 0) { Write-Error "git pull failed — resolve the conflict/error above, then re-run." }

Write-Host "Refreshing backend dependencies..."
& py -3.11 -m pip install -r "$repoRoot\backend\requirements.txt"
if ($LASTEXITCODE -ne 0) { Write-Error "pip install failed — see output above." }

Write-Host ""
Write-Host "[OK] Updated. If the backend is running, restart it to pick up changes:" -ForegroundColor Green
Write-Host "     close its console window, then run  .\run_backend.ps1 -Prod  (or sign out/in)."
