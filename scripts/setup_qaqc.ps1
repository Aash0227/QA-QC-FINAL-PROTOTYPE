# setup_qaqc.ps1 - canonical one-time installer for a QA department laptop.
# Launched by scripts\QAQC_Setup.bat (or manually:
#   powershell -ExecutionPolicy Bypass -File scripts\setup_qaqc.ps1)
# No admin required - everything is user-scope. Safe to re-run: every step is idempotent.
$ErrorActionPreference = "Continue"   # log-and-continue; the summary at the end flags failures
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$logDir = Join-Path $repoRoot "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
Start-Transcript -Path (Join-Path $logDir "setup.log") -Append | Out-Null

$manual = @()   # human steps the QA person still has to do
$failed = @()   # steps that failed

function Step($msg) { Write-Host "`n== $msg ==" -ForegroundColor Cyan }
function Ok($msg)   { Write-Host "[OK] $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "[MANUAL STEP NEEDED] $msg" -ForegroundColor Yellow }
function Bad($msg)  { Write-Host "[FAILED] $msg" -ForegroundColor Red; $script:failed += $msg }

Write-Host "== QA-QC laptop installer ==" -ForegroundColor Cyan
Write-Host "Repo: $repoRoot  ($(Get-Date -Format 'yyyy-MM-dd HH:mm'))"

# ---------------------------------------------------------------- 1. Python 3.11
# Vendored PIL/fitz are compiled for 3.11 - any other version will crash.
Step "Checking Python 3.11"
$v = & py -3.11 --version 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "Python 3.11 not found - downloading and installing it now (user-scope, no admin)..."
    $pyUrl = "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
    $pyExe = Join-Path $env:TEMP "python-3.11.9-amd64.exe"
    try {
        Invoke-WebRequest -Uri $pyUrl -OutFile $pyExe -UseBasicParsing
        $p = Start-Process -FilePath $pyExe -ArgumentList "/quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_test=0" -Wait -PassThru
        if ($p.ExitCode -ne 0) { throw "installer exit code $($p.ExitCode)" }
        # Installer updates the machine PATH, not this session's - patch it in.
        $env:Path = [Environment]::GetEnvironmentVariable("Path","User") + ";" + [Environment]::GetEnvironmentVariable("Path","Machine")
        $v = & py -3.11 --version 2>&1
        if ($LASTEXITCODE -ne 0) { throw "py -3.11 still not found after install" }
        Ok "installed $v"
    } catch {
        Bad "Python 3.11 auto-install failed ($_). Install it from https://www.python.org/downloads/release/python-3119/ (tick 'py launcher'), then re-run QAQC_Setup.bat."
    }
} else {
    Ok $v
}

# ---------------------------------------------------------------- 2. Backend dependencies
if ($failed.Count -eq 0) {
    Step "Installing backend dependencies (this takes a few minutes)"
    & py -3.11 -m pip install -r "$repoRoot\backend\requirements.txt"
    if ($LASTEXITCODE -ne 0) { Bad "pip install failed - see output above." } else { Ok "dependencies installed" }
}

# ---------------------------------------------------------------- 3. .env (never overwrite)
Step "Checking .env configuration"
if (-not (Test-Path "$repoRoot\.env")) {
    try {
        Copy-Item "$repoRoot\.env.example" "$repoRoot\.env"
        Ok "created .env from .env.example"
        Warn ".env was just created - your API key must be added to it (one-time)."
        $manual += "Add your OPENROUTER_API_KEY to $repoRoot\.env (see EMPLOYEE_SETUP.md, 'API key'). Ask engineering for the key."
    } catch { Bad "could not create .env ($_)" }
} else {
    Ok ".env already exists (left untouched)"
    if (-not (Select-String -Path "$repoRoot\.env" -Pattern 'OPENROUTER_API_KEY=.+' -Quiet)) {
        Warn ".env exists but OPENROUTER_API_KEY looks empty."
        $manual += "Add your OPENROUTER_API_KEY to $repoRoot\.env (see EMPLOYEE_SETUP.md, 'API key')."
    }
}

# ---------------------------------------------------------------- 4. Startup shortcut
Step "Setting up auto-start at login"
try {
    $startup = [Environment]::GetFolderPath("Startup")
    $lnkPath = Join-Path $startup "QAQC-Backend.lnk"
    $shell = New-Object -ComObject WScript.Shell
    $lnk = $shell.CreateShortcut($lnkPath)
    $lnk.TargetPath = "powershell.exe"
    $lnk.Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Minimized -File `"$repoRoot\run_backend.ps1`" -Prod"
    $lnk.WorkingDirectory = $repoRoot
    $lnk.Description = "QA-QC backend (http://127.0.0.1:8077)"
    $lnk.Save()
    Ok "startup shortcut: $lnkPath (backend starts minimized at every login)"
} catch { Bad "startup shortcut failed ($_)" }

# ---------------------------------------------------------------- 5. pyRevit exporter extension
Step "Checking pyRevit + QA-QC exporter"
$pyrevitExtDir = "$env:APPDATA\pyRevit\Extensions"
$bundledExt = Join-Path $repoRoot "tools\LivioQAQC.extension"
if (-not (Test-Path $pyrevitExtDir)) {
    Warn "pyRevit is not installed on this computer."
    $manual += "Install pyRevit: download pyRevit from https://github.com/pyrevitlabs/pyRevit/releases and run the installer (no admin needed). Then re-run QAQC_Setup.bat to install the QA-QC exporter."
} elseif (Test-Path $bundledExt) {
    # ponytail: `pyrevit extend` clones from git URLs; a local bundled folder just gets
    # copied - works with or without the pyrevit CLI and is idempotent.
    $dest = Join-Path $pyrevitExtDir (Split-Path $bundledExt -Leaf)
    if (-not (Test-Path $dest)) {
        try { Copy-Item $bundledExt $dest -Recurse; Ok "QA-QC exporter installed to $dest" }
        catch { Bad "could not copy exporter to $dest ($_)" }
    } else { Ok "QA-QC exporter already installed ($dest)" }
} else {
    Warn "pyRevit is installed but no bundled exporter found at tools\qaqc_pyrevit.extension."
    $manual += "Ask engineering for the QA-QC exporter folder, then copy it into $pyrevitExtDir\ and restart Revit."
}

# ---------------------------------------------------------------- 6. revitMCP add-in
Step "Checking revitMCP add-in"
$mcpDir = "$env:APPDATA\Autodesk\Revit\Addins\2023\revit_mcp_plugin"
$bundledMcp = Join-Path $repoRoot "tools\revit_mcp_plugin"
if (Test-Path $mcpDir) {
    Ok "revitMCP add-in present ($mcpDir)"
} elseif (Test-Path $bundledMcp) {
    try {
        New-Item -ItemType Directory -Force -Path (Split-Path $mcpDir -Parent) | Out-Null
        Copy-Item $bundledMcp $mcpDir -Recurse
        Ok "revitMCP add-in installed to $mcpDir"
    } catch { Bad "could not copy revitMCP add-in ($_)" }
} else {
    Warn "revitMCP add-in not found."
    $manual += "Install revitMCP: copy the 'revit_mcp_plugin' folder (get it from engineering) into %APPDATA%\Autodesk\Revit\Addins\2023\ - then restart Revit."
}

# ---------------------------------------------------------------- 7. NonicaTab PRO (cannot automate)
Step "Checking NonicaTab PRO"
if (Test-Path "C:\NONICAPRO") {
    Ok "NonicaTab PRO found (C:\NONICAPRO)"
} else {
    Warn "NonicaTab PRO not detected."
    $manual += "Install NonicaTab PRO: run the licensed NonicaTab PRO installer (engineering has the license + installer). This cannot be automated - it is proprietary licensed software."
}

# First-launch Revit add-in approval is unavoidable and applies whenever add-ins were installed.
if (($manual -join " ") -match "revitMCP|pyRevit|exporter" -or (Test-Path $mcpDir)) {
    $manual += "First Revit launch after setup: Revit will ask 'Do you want to load this add-in?' for each new add-in - click 'Always Load' each time (one-time)."
}

# ---------------------------------------------------------------- Summary
Step "SETUP SUMMARY"
if ($failed.Count -eq 0) { Write-Host "All automatic steps completed." -ForegroundColor Green }
else {
    Write-Host "Some steps FAILED:" -ForegroundColor Red
    $failed | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }
    Write-Host "Fix the items above (or send logs\setup.log to engineering) and re-run QAQC_Setup.bat."
}
if ($manual.Count -gt 0) {
    Write-Host "`nThings that still need a human (one-time each):" -ForegroundColor Yellow
    $i = 1
    $manual | ForEach-Object { Write-Host "  $i. $_" -ForegroundColor Yellow; $i++ }
} else {
    Write-Host "No manual steps remaining - this laptop is fully ready." -ForegroundColor Green
}
Write-Host "`nDaily use: sign in -> open your Revit model -> turn the 2 switches ON -> open http://127.0.0.1:8077"
Write-Host "Full guide: docs\EMPLOYEE_SETUP.md   Log: logs\setup.log"

Stop-Transcript | Out-Null
if ($failed.Count -gt 0) { exit 1 } else { exit 0 }
