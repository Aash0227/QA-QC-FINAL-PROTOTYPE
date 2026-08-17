; qaqc.iss - Inno Setup 6 script for the Livio QA-QC desktop installer.
;
; Build with scripts\build_installer.ps1 (which builds frontend/dist first and
; passes AppVersion in) rather than compiling this file directly - the installer
; must never ship a stale or missing UI bundle.
;
; Deliberate choices, and why:
;
;   Thin, not bundled. Python is NOT packed into the installer. scripts\setup_qaqc.ps1
;   already installs Python 3.11 user-scope, pip-installs the requirements, seeds
;   .env and wires the pyRevit exporter, and it is idempotent. Duplicating that
;   here would create a second thing to keep in sync with backend\requirements.txt.
;
;   User-scope. PrivilegesRequired=lowest, installs under {localappdata}. Nothing
;   this app does needs administrator rights, and requiring them would put the
;   install out of reach of the QA laptops it is meant for.
;
;   No Windows service, no firewall rule. The backend must run in the user's
;   interactive session to reach the Revit bridge (session 0 breaks it silently),
;   and it binds 127.0.0.1, which never triggers a Windows Defender prompt. Both
;   are load-bearing decisions from docs\DEPLOY.md, not oversights.
;
;   User data is never destroyed silently. artifacts\ (every uploaded drawing
;   set, calibration and review comment) and .env (an API key) are removed on
;   uninstall only after an explicit prompt.

#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif

#define AppName "Livio QA-QC"
#define AppPublisher "Livio Building Systems Inc."
#define SrcRoot ".."

[Setup]
; Fixed AppId: this is what makes the next version upgrade in place instead of
; installing a second copy alongside. Never change it.
AppId={{7C4E1B92-3F5A-4D18-9E27-0A6B5C8D4F31}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={localappdata}\Livio\QA-QC
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#SrcRoot}\dist
OutputBaseFilename=LivioQAQC-Setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName={#AppName}
; Refuse to run while the backend is up: overwriting backend\app while uvicorn
; has it imported produces a half-updated install that fails at the next restart.
CloseApplications=yes
RestartApplications=no
SetupLogging=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"
Name: "runsetup"; Description: "Install Python 3.11 and dependencies now (required on a new machine)"; GroupDescription: "First-time setup:"

[Files]
; Backend source. Compiled caches are excluded: they are rebuilt on first import
; and shipping them risks a stale .pyc shadowing an updated .py.
Source: "{#SrcRoot}\backend\*"; DestDir: "{app}\backend"; Flags: ignoreversion recursesubdirs createallsubdirs; \
  Excludes: "__pycache__,*.pyc,.pytest_cache"

; The BUILT UI only. The source tree under frontend\src imports bare specifiers
; ("three", "gsap") that only a bundler can resolve, so shipping it would give a
; blank page if it were ever served. config.frontend_dir() finds dist\index.html
; here and serves it.
Source: "{#SrcRoot}\frontend\dist\*"; DestDir: "{app}\frontend\dist"; Flags: ignoreversion recursesubdirs createallsubdirs

Source: "{#SrcRoot}\scripts\*"; DestDir: "{app}\scripts"; Flags: ignoreversion recursesubdirs createallsubdirs; \
  Excludes: "__pycache__,*.pyc"
Source: "{#SrcRoot}\tools\*"; DestDir: "{app}\tools"; Flags: ignoreversion recursesubdirs createallsubdirs; \
  Excludes: "__pycache__,*.pyc"
Source: "{#SrcRoot}\docs\*"; DestDir: "{app}\docs"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#SrcRoot}\run_backend.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SrcRoot}\README.md"; DestDir: "{app}"; Flags: ignoreversion
; onlyifdoesntexist: .env holds the operator's API key. An upgrade must never
; overwrite it.
Source: "{#SrcRoot}\.env.example"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SrcRoot}\.env.example"; DestDir: "{app}"; DestName: ".env"; Flags: onlyifdoesntexist

[Icons]
; The shortcut target is the launcher, never uvicorn directly: it handles the
; already-running case, port conflicts, and reports failures in a dialog.
Name: "{group}\{#AppName}"; Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; \
  Parameters: "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File ""{app}\scripts\launch_qaqc.ps1"""; \
  WorkingDir: "{app}"; Comment: "Start Livio QA-QC and open it in your browser"
Name: "{group}\Livio QA-QC documentation"; Filename: "{app}\docs"
Name: "{group}\Re-run first-time setup"; Filename: "{app}\scripts\QAQC_Setup.bat"; WorkingDir: "{app}\scripts"; \
  Comment: "Reinstall Python dependencies and the Revit add-ins"
Name: "{autodesktop}\{#AppName}"; Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; \
  Parameters: "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File ""{app}\scripts\launch_qaqc.ps1"""; \
  WorkingDir: "{app}"; Tasks: desktopicon

[Run]
; Shown with progress and skippable: on a machine that already has Python 3.11
; and the dependencies, this is a no-op that still takes a minute.
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; \
  Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\scripts\setup_qaqc.ps1"""; \
  WorkingDir: "{app}"; StatusMsg: "Installing Python 3.11 and dependencies (this can take a few minutes)..."; \
  Flags: waituntilterminated runhidden; Tasks: runsetup
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; \
  Parameters: "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File ""{app}\scripts\launch_qaqc.ps1"""; \
  WorkingDir: "{app}"; Description: "Start {#AppName} now"; Flags: postinstall nowait skipifsilent

[UninstallDelete]
; Regenerable or machine-local: logs, the UI bundle, Python caches, and the
; auto-start shortcut setup_qaqc.ps1 drops into the Startup folder.
Type: filesandordirs; Name: "{app}\logs"
Type: filesandordirs; Name: "{app}\frontend"
Type: filesandordirs; Name: "{app}\backend\__pycache__"
Type: filesandordirs; Name: "{app}\backend\.pytest_cache"
Type: files; Name: "{userstartup}\QAQC-Backend.lnk"

[Code]
{ Uninstall must not quietly destroy a reviewer's work. artifacts\ holds every
  uploaded drawing set, calibration and review resolution; .env holds an API
  key. Both are removed only if the person uninstalling says so, and the prompt
  states plainly what is at stake. Default is No. }
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    DataDir := ExpandConstant('{app}\artifacts');
    if DirExists(DataDir) then
    begin
      if MsgBox('Also delete your QA-QC project data?' + #13#10#13#10 +
                'This removes every uploaded drawing set, Revit export, calibration ' +
                'and review comment in:' + #13#10 + DataDir + #13#10#13#10 +
                'Choose No to keep them for a future reinstall.',
                mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(DataDir, True, True, True);
    end;
    if FileExists(ExpandConstant('{app}\.env')) then
    begin
      if MsgBox('Also delete your saved settings (.env)?' + #13#10#13#10 +
                'This file contains your OpenRouter API key.',
                mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DeleteFile(ExpandConstant('{app}\.env'));
    end;
  end;
end;
