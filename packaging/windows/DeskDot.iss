; Inno Setup script for the DeskDot Windows installer (Inno Setup 6). Build from the repo root after PyInstaller:
;
;   iscc /DAppVersion=3.8.0 packaging\windows\DeskDot.iss      → packaging\build\installer\DeskDot-Setup-3.8.0-x64.exe
;
; Per-user install (no admin, no UAC prompt): %LOCALAPPDATA%\Programs\DeskDot. Settings and data live in
; %LOCALAPPDATA%\DeskDot (created by the app on first run) and are kept on uninstall and on updates.
; In-app updates run this installer with /SILENT /SUPPRESSMSGBOXES /CLOSEAPPLICATIONS; it starts DeskDot again.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define AppName "DeskDot"
#define AppExe "DeskDot.exe"
#define Src "..\build\dist\DeskDot"

[Setup]
; never change AppId: it's how Windows knows a new installer updates the same app
AppId={{7E3C1D2A-5B8F-4C61-9D2E-DE5D07A1C0DE}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=DeskDot
AppPublisherURL=https://idotmatrix.com
AppSupportURL=https://github.com/shivpatel2468/idotmatrix/issues
AppUpdatesURL=https://github.com/shivpatel2468/idotmatrix/releases
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\build\installer
OutputBaseFilename=DeskDot-Setup-{#AppVersion}-x64
SetupIconFile=..\build\deskdot.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
LicenseFile=..\..\LICENSE
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=force
RestartApplications=no
VersionInfoVersion={#AppVersion}
VersionInfoProductName={#AppName}
VersionInfoDescription={#AppName} installer

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"
Name: "autostart"; Description: "Start DeskDot when I sign in to Windows"; GroupDescription: "Start-up:"; Flags: unchecked

[InstallDelete]
; an update replaces the whole program folder (old Python modules must not linger)
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#Src}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autoprograms}\{#AppName} (simulated panel)"; Filename: "{app}\{#AppExe}"; Parameters: "serve --sim"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; the same value the launcher's "Start with login" tray item toggles (src/deskdot/launcher.py RUN_VALUE)
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "DeskDot Launcher"; ValueData: """{app}\{#AppExe}"" --background"; Tasks: autostart; Flags: uninsdeletevalue

[Run]
Filename: "{app}\{#AppExe}"; Description: "Open DeskDot now"; Flags: nowait postinstall skipifsilent
; after a silent in-app update: start DeskDot again (it reopens the studio tab)
Filename: "{app}\{#AppExe}"; Flags: nowait runasoriginaluser; Check: WizardSilent

[UninstallRun]
Filename: "{cmd}"; Parameters: "/C taskkill /IM {#AppExe} /T /F"; Flags: runhidden; RunOnceId: "StopDeskDot"

[UninstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Code]
function IsRunning(const Exe: String): Boolean;
var
  Locator, Service, Procs: Variant;
begin
  Result := False;
  try
    Locator := CreateOleObject('WbemScripting.SWbemLocator');
    Service := Locator.ConnectServer('.', 'root\CIMV2');
    Procs := Service.ExecQuery('SELECT ProcessId FROM Win32_Process WHERE Name = ''' + Exe + '''');
    Result := Procs.Count > 0;
  except
  end;
end;

{ An in-app update starts this installer and then the engine exits on its own (handing the panel its clock).
  Give it up to 20 s to do that before Restart Manager closes whatever is left. }
function InitializeSetup(): Boolean;
var
  I: Integer;
begin
  if WizardSilent then
  begin
    I := 0;
    while (I < 40) and IsRunning('{#AppExe}') do
    begin
      Sleep(500);
      I := I + 1;
    end;
  end;
  Result := True;
end;
