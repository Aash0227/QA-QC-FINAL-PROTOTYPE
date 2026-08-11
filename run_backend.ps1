# Launches the QA-QC Automated System prototype backend + UI on http://127.0.0.1:8077
# NOTE: This project vendors PIL/fitz/pymupdf compiled for Python 3.11, so it MUST
# run under Python 3.11 (the machine default `python` is 3.14 and will crash on PIL).
#
#   ./run_backend.ps1          dev  — auto-reload on file change (default, unchanged)
#   ./run_backend.ps1 -Prod    ship — one worker, no reload (DEPLOY.md "Process model")
param(
    [switch]$Prod,
    [int]$Port = 8077
)
$ErrorActionPreference = "Stop"
Set-Location "$PSScriptRoot\backend"

# §10: bind address honors $env:BIND_HOST (default 127.0.0.1 — localhost-only).
# Set BIND_HOST=0.0.0.0 to expose on the LAN; pair with QAQC_AUTH_TOKEN then.
$bindHost = if ($env:BIND_HOST) { $env:BIND_HOST } else { "127.0.0.1" }

$uvicornArgs = @("-m", "uvicorn", "app.main:app", "--host", $bindHost, "--port", "$Port")
if ($Prod) {
    # One worker: the artifact store and the Revit bridge lock are single-process,
    # and --reload would restart the server mid-pipeline on any file touch.
    $uvicornArgs += @("--workers", "1")
} else {
    $uvicornArgs += "--reload"
}

# Retention/log knobs (QAQC_EVIDENCE_CAP_MB, QAQC_LOG_MAX_BYTES, QAQC_LOG_BACKUPS)
# are deliberately not set here: the code defaults already match DEPLOY.md, so
# hardcoding them would only create a second place to keep in sync.

$py311 = "C:\Users\aashd\AppData\Local\Programs\Python\Python311\python.exe"
if (Test-Path $py311) {
    & $py311 @uvicornArgs
} else {
    & py -3.11 @uvicornArgs
}
