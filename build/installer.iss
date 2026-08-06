; GROMOV Restore+ — installer script for Inno Setup 6

#define MyAppName "GROMOV Restore+"
#define MyAppVersion "1.4.3"
#define MyAppPublisher "GROMOV"
#define MyAppExeName "GROMOV-RestorePlus.exe"

[Setup]
AppId={{C4A8E1F2-7B3D-4E9A-9C1F-2D5E6F708293}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\GROMOV\Restore+
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; Do not reuse a previous install dir (e.g. a one-off Temp verify path with the same AppId),
; otherwise silent/auto updates keep writing to Temp instead of Program Files.
UsePreviousAppDir=no
OutputDir=..\dist
OutputBaseFilename=GROMOV-RestorePlus-Setup
SetupIconFile=..\assets\icon.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
CloseApplications=yes
RestartApplications=no
ArchitecturesInstallIn64BitMode=x64

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; GroupDescription: "Дополнительно:"; Flags: checkedonce

[Files]
; Entire PyInstaller tree — must already contain tools\ and drivers\ (build_release.ps1 copies them).
Source: "..\dist\GROMOV-RestorePlus\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs restartreplace

; Explicit copies so a missing folder fails the build instead of shipping a broken Setup.
Source: "..\dist\GROMOV-RestorePlus\tools\*"; DestDir: "{app}\tools"; Flags: ignoreversion recursesubdirs createallsubdirs restartreplace
Source: "..\dist\GROMOV-RestorePlus\drivers\*"; DestDir: "{app}\drivers"; Flags: ignoreversion recursesubdirs createallsubdirs restartreplace

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; bat is required in the package; MSI inside drivers\ are optional (bat falls back to winget/Store).
Filename: "{app}\drivers\install_drivers.bat"; WorkingDir: "{app}\drivers"; Description: "Установить драйверы Apple для iPhone"; Flags: postinstall runascurrentuser skipifsilent nowait unchecked
Filename: "{app}\{#MyAppExeName}"; Description: "Запустить {#MyAppName}"; Flags: postinstall nowait skipifsilent

[Messages]
russian.WelcomeLabel2=Установит GROMOV Restore+ для восстановления приложений App Store на iPhone.%n%nПри необходимости можно установить драйверы Apple на последнем шаге.

[Code]
var
  WipeUserData: Boolean;

function InitializeUninstall(): Boolean;
begin
  WipeUserData := False;
  if MsgBox('Удалить также данные пользователя?' + #13#10 + #13#10 +
            '• скачанные IPA' + #13#10 +
            '• кэш и настройки' + #13#10 +
            '• логи и ключ сессии' + #13#10 + #13#10 +
            'Выберите «Да», чтобы полностью очистить %LOCALAPPDATA%\GROMOV\RestorePlus',
            mbConfirmation, MB_YESNO) = IDYES then
    WipeUserData := True;
  Result := True;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if (CurUninstallStep = usPostUninstall) and WipeUserData then
    DelTree(ExpandConstant('{localappdata}\GROMOV\RestorePlus'), True, True, True);
end;
