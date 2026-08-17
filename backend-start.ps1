# backend-start.ps1 — start Livio QA-QC and print the browser URL.
# Right-click → Run with PowerShell, or:
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\backend-start.ps1
#
# Leave this window open while you use the app.
# NOTE: Vendored PIL/fitz require Python 3.11 (not the machine-default python).
param(
    [int]$Port = 8077
)

$ErrorActionPreference = "Stop"
$repoRoot = $PSScriptRoot
Set-Location (Join-Path $repoRoot "backend")

$bindHost = if ($env:BIND_HOST) { $env:BIND_HOST } else { "127.0.0.1" }
$url = "http://${bindHost}:${Port}"

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  Livio QA-QC backend starting"
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Open in browser (copy/paste):" -ForegroundColor Green
Write-Host "  $url" -ForegroundColor Green
Write-Host ""
Write-Host "  Leave this window open while using the app."
Write-Host "  Press Ctrl+C to stop the backend."
Write-Host ""

$uvicornArgs = @(
    "-m", "uvicorn", "app.main:app",
    "--host", $bindHost,
    "--port", "$Port",
    "--workers", "1"
)

$pyLauncher = Get-Command py -ErrorAction SilentlyContinue
if ($pyLauncher) {
    & py -3.11 @uvicornArgs
} else {
    Write-Error @"
Python 3.11 was not found (py launcher missing).
Double-click setup.bat once in:
  $repoRoot
Then run this script again.
"@
}
