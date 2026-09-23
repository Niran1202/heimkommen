; Inno Setup script for the Heimkommen Windows installer.
; Build with: python desktop/build.py   (or: ISCC.exe desktop\installer.iss after the PyInstaller step)
; Installs per user (no administrator rights needed) into %LOCALAPPDATA%\Programs\Heimkommen.

#define AppName "Heimkommen"
#define AppVersion "1.0.0"
#define AppPublisher "Heimkommen project"
#define AppURL "https://github.com/Niran1202/heimkommen"

[Setup]
AppId={{6C1E5B7A-3F2D-4B8E-9A61-2D4F7C9E1A35}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=Output
OutputBaseFilename=Heimkommen-Setup-{#AppVersion}
SetupIconFile=build\resources\heimkommen.ico
UninstallDisplayIcon={app}\Heimkommen.exe
LicenseFile=..\LICENSE
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "german"; MessagesFile: "compiler:Languages\German.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "release\Heimkommen\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\Heimkommen.exe"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\Heimkommen.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Heimkommen.exe"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[Code]
// Ask whether to remove the user's data (account, saved trips, timetable copy) on uninstall.
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    DataDir := ExpandConstant('{localappdata}\Heimkommen');
    if DirExists(DataDir) then
      if MsgBox('Also delete your Heimkommen data (timetable copy and prediction history in ' + DataDir + ')?',
                mbConfirmation, MB_YESNO) = IDYES then
        DelTree(DataDir, True, True, True);
  end;
end;
