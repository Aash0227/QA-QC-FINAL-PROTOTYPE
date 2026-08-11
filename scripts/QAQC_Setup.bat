@echo off
REM ============================================================
REM  QA-QC One-Click Setup
REM  Double-click this file. That's it. No admin rights needed.
REM ============================================================
title QA-QC Setup
cd /d "%~dp0.."

echo.
echo  ============================================
echo    QA-QC System - One-Time Computer Setup
echo  ============================================
echo.
echo  This will install everything the QA-QC tool needs.
echo  It takes about 5-10 minutes. You only do this ONCE.
echo.
echo  Please do not close this window...
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_qaqc.ps1"
set RC=%ERRORLEVEL%

echo.
if "%RC%"=="0" (
    echo  ============================================
    echo    SETUP FINISHED - see summary above.
    echo  ============================================
) else (
    echo  ============================================
    echo    SETUP HAD A PROBLEM ^(error %RC%^).
    echo    Take a photo of this window and send it
    echo    to the engineering team. The log file is:
    echo    %~dp0..\logs\setup.log
    echo  ============================================
)
echo.
echo  Press any key to close this window.
pause >nul
