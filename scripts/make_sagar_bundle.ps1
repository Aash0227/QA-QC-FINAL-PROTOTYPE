# Builds the deployable bundle for Sagar's workstation (deploy plan D3).
#
#   .\scripts\make_sagar_bundle.ps1            # -> dist\qaqc-sagar-bundle-<date>.zip
#   .\scripts\make_sagar_bundle.ps1 -Project country-side-ct
#
# Code comes from `git archive HEAD` — tracked files only, so no .git, no PAT,
# no node_modules, no 577 MB artifacts tree. The one seed workspace is copied in
# by hand (artifacts/projects/ is gitignored) minus evidence/ and pages/, which
# are regenerable caches (maintenance.py: "crops are regenerable from the PDFs").
# The real .env is never bundled — only .env.example.
param(
    [string]$Project = "madera",
    [string]$OutDir  = ""
)
$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent $PSScriptRoot
if (-not $OutDir) { $OutDir = Join-Path $repo "dist" }
$stamp = Get-Date -Format "yyyy-MM-dd"
$stage = Join-Path $OutDir "_stage-$stamp"
$zip   = Join-Path $OutDir "qaqc-sagar-bundle-$stamp.zip"

if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
if (Test-Path $zip)   { Remove-Item $zip -Force }
New-Item -ItemType Directory -Path $stage -Force | Out-Null

# --- (a) code: tracked files at HEAD, nothing else -------------------------
Write-Host "[1/5] git archive HEAD ..."
$codeZip = Join-Path $OutDir "_code-$stamp.zip"
if (Test-Path $codeZip) { Remove-Item $codeZip -Force }
& git -C $repo archive --format=zip -o $codeZip HEAD
if ($LASTEXITCODE -ne 0) { throw "git archive failed (exit $LASTEXITCODE)" }
Expand-Archive -Path $codeZip -DestinationPath $stage -Force
Remove-Item $codeZip -Force

# --- (b) seed workspace, minus the regenerable caches ----------------------
$src = Join-Path $repo "artifacts\projects\$Project"
if (-not (Test-Path $src)) { throw "seed workspace not found: $src" }
Write-Host "[2/5] copying artifacts\projects\$Project (excluding evidence\, pages\) ..."
$dst = Join-Path $stage "artifacts\projects\$Project"
& robocopy $src $dst /E /XD "evidence" "pages" /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy failed (exit $LASTEXITCODE)" }
$global:LASTEXITCODE = 0   # robocopy's 1..7 are successes, not errors

# --- (c) .env.example only — never the real .env --------------------------
Write-Host "[3/5] .env.example ..."
Copy-Item (Join-Path $repo ".env.example") (Join-Path $stage ".env.example") -Force
$leaked = Get-ChildItem $stage -Recurse -Force | Where-Object { $_.Name -eq ".env" }
if ($leaked) { throw "REFUSING TO SHIP: a real .env reached the staging dir" }

# --- (d) install instructions ---------------------------------------------
Write-Host "[4/5] BUNDLE_README.txt ..."
$readme = @"
QA-QC Automated System — install bundle ($stamp)
=================================================
Unzip to  C:\QA-QC-FINAL-PROTOTYPE\   (any path works; this one matches the docs)

1. Python 3.11 — required. PyMuPDF/Pillow here are compiled for 3.11 and will
   crash on 3.12+. Install from python.org with "Add python.exe to PATH".
       py -3.11 --version

2. Dependencies:
       cd C:\QA-QC-FINAL-PROTOTYPE\backend
       py -3.11 -m pip install -r requirements.txt

3. Create the .env file (NOT included in this bundle — it holds a secret):
       copy C:\QA-QC-FINAL-PROTOTYPE\.env.example C:\QA-QC-FINAL-PROTOTYPE\.env
   then edit it and set:
       OPENROUTER_API_KEY=<ask Ashwin>
   Leave BIND_HOST and QAQC_AUTH_TOKEN unset — localhost-only is the correct
   posture for this install. The app runs fine without the OpenRouter key; only
   the AI chat panel needs it, and it degrades honestly when absent.

4. Start the server:
       C:\QA-QC-FINAL-PROTOTYPE\run_backend.ps1 -Prod
   (-Prod = one worker, no auto-reload. To auto-start at logon: Win+R ->
    shell:startup -> shortcut to
      powershell.exe -ExecutionPolicy Bypass -File "C:\QA-QC-FINAL-PROTOTYPE\run_backend.ps1" -Prod
    set to Run: Minimized. Do NOT install it as a Windows service — services run
    in session 0 and cannot reach Revit's UI, which breaks every live feature.)

5. Open http://127.0.0.1:8077 in Chrome or Edge. The header should show the
   "$Project" project and STATS should be populated.

Revit live features — BOTH connectors must be ON, every session:
  * Nonica ribbon    -> A.I. Connector -> On
  * revitMCP ribbon  -> Open Server
  Then dismiss every open Revit dialog: any modal dialog (including revitMCP's
  own "Open Server" window) blocks all MCP calls. Greyed-out Revit buttons in
  the web app mean a connector is off — that is honest behavior, not a bug.

Included: application code (tracked files at git HEAD) + the "$Project" sample
workspace. The evidence\ and pages\ image caches were stripped — the app
regenerates them on demand from the source PDFs.
"@
Set-Content -Path (Join-Path $stage "BUNDLE_README.txt") -Value $readme -Encoding UTF8

# --- (e) zip ---------------------------------------------------------------
Write-Host "[5/5] compressing ..."
# Entries are written one at a time with '/' separators on purpose: both
# Compress-Archive and ZipFile.CreateFromDirectory on Windows PowerShell 5.1
# emit backslash entry names, which some unzip tools turn into single files
# literally called "backend\app\main.py".
Add-Type -AssemblyName System.IO.Compression.FileSystem
$prefix = (Resolve-Path $stage).Path.TrimEnd("\") + "\"
$archive = [System.IO.Compression.ZipFile]::Open(
    $zip, [System.IO.Compression.ZipArchiveMode]::Create)
try {
    foreach ($file in Get-ChildItem $stage -Recurse -File -Force) {
        $entry = $file.FullName.Substring($prefix.Length).Replace("\", "/")
        [void][System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
            $archive, $file.FullName, $entry,
            [System.IO.Compression.CompressionLevel]::Optimal)
    }
} finally {
    $archive.Dispose()
}
Remove-Item $stage -Recurse -Force

$mb = [math]::Round((Get-Item $zip).Length / 1MB, 1)
Write-Host ""
Write-Host "Bundle: $zip  ($mb MB)"
Write-Host "REMINDER: .env is NOT in this bundle by design. Create it on the"
Write-Host "target machine from .env.example and paste in OPENROUTER_API_KEY."
