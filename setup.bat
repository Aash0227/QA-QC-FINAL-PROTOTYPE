@echo off
REM ============================================================
REM  Livio QA-QC ??? one-time laptop setup
REM  Double-click this file. No admin required.
REM  Installs Python 3.11 (if needed) and pip dependencies.
REM  You still install pyRevit, Nonica Pro, and Revit MCP yourself.
REM ============================================================
title Livio QA-QC Setup
cd /d "%~dp0"

echo.
echo  ============================================
echo    Livio QA-QC ??? One-Time Setup
echo  ============================================
echo.
echo  This installs Python 3.11 and backend packages.
echo  It does NOT install pyRevit, Nonica Pro, or Revit MCP.
echo  Please do not close this window...
echo.

REM Extract the PowerShell block below the marker into a temp file.
REM (cmd caret-continuation into powershell -Command breaks; this stays one .bat)
set "LIVIO_QAQC_ROOT=%cd%"
set "LIVIO_SETUP_PS1=%TEMP%\livio_qaqc_setup_%RANDOM%%RANDOM%.ps1"
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$p='%~f0'; $o=$env:LIVIO_SETUP_PS1; $t=Get-Content -LiteralPath $p -Raw; $m='##### BEGIN POWERSHELL #####'; $i=$t.LastIndexOf($m); if($i -lt 0){throw 'setup marker missing'}; Set-Content -LiteralPath $o -Value $t.Substring($i+$m.Length) -Encoding UTF8"
if errorlevel 1 (
  echo Failed to prepare setup script.
  set RC=1
  goto :done
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%LIVIO_SETUP_PS1%"
set RC=%ERRORLEVEL%
del "%LIVIO_SETUP_PS1%" >nul 2>&1

:done
echo.
if "%RC%"=="0" (
  echo  ============================================
  echo    SETUP FINISHED
  echo  ============================================
) else (
  echo  ============================================
  echo    SETUP HAD A PROBLEM ^(error %RC%^).
  echo    Take a photo of this window and send it
  echo    to the engineering team.
  echo  ============================================
)
echo.
echo  Press any key to close this window.
pause >nul
exit /b %RC%

##### BEGIN POWERSHELL #####
$ErrorActionPreference = "Stop"
$root = $env:LIVIO_QAQC_ROOT
if (-not $root) { $root = (Get-Location).Path }
if (-not (Test-Path (Join-Path $root "backend\requirements.txt"))) {
    throw "Cannot find backend\requirements.txt. Run setup.bat from the unzipped project folder."
}
Set-Location $root

Write-Host "== Checking Python 3.11 ==" -ForegroundColor Cyan
$ok = $false
try {
    $v = & py -3.11 --version 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[OK] $v" -ForegroundColor Green
        $ok = $true
    }
} catch {}

if (-not $ok) {
    Write-Host "Python 3.11 not found - downloading installer (user-scope)..." -ForegroundColor Yellow
    $pyUrl = "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
    $pyExe = Join-Path $env:TEMP "python-3.11.9-amd64.exe"
    Invoke-WebRequest -Uri $pyUrl -OutFile $pyExe -UseBasicParsing
    $p = Start-Process -FilePath $pyExe -ArgumentList "/quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_test=0" -Wait -PassThru
    if ($p.ExitCode -ne 0) { throw "Python installer failed with exit code $($p.ExitCode)" }
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "User") + ";" + [Environment]::GetEnvironmentVariable("Path", "Machine")
    $v = & py -3.11 --version 2>&1
    if ($LASTEXITCODE -ne 0) { throw "py -3.11 still not found after install" }
    Write-Host "[OK] installed $v" -ForegroundColor Green
}

Write-Host ""
Write-Host "== Installing backend dependencies ==" -ForegroundColor Cyan
& py -3.11 -m pip install -r (Join-Path $root "backend\requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }
Write-Host "[OK] dependencies installed" -ForegroundColor Green

Write-Host ""
Write-Host "== Checking .env ==" -ForegroundColor Cyan
$envPath = Join-Path $root ".env"
$example = Join-Path $root ".env.example"
if (-not (Test-Path $envPath)) {
    if (-not (Test-Path $example)) { throw ".env.example missing" }
    Copy-Item $example $envPath
    Write-Host "[OK] created .env from .env.example" -ForegroundColor Green
    Write-Host "[MANUAL] Add OPENROUTER_API_KEY to .env if you use AI features." -ForegroundColor Yellow
} else {
    Write-Host "[OK] .env already exists (left untouched)" -ForegroundColor Green
}

Write-Host ""
Write-Host "== MANUAL STEPS (you do these yourself) ==" -ForegroundColor Yellow
Write-Host "  1. Install pyRevit"
Write-Host "  2. Install Nonica Pro"
Write-Host "  3. Install Revit MCP"
Write-Host "  4. (Optional) Put OPENROUTER_API_KEY in .env"
Write-Host ""
Write-Host "Daily use: run backend-start.ps1, then open http://127.0.0.1:8077" -ForegroundColor Cyan
Write-Host "[OK] Setup finished." -ForegroundColor Green
exit 0
