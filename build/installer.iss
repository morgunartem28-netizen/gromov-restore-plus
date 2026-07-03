; GROMOV Restore+ — installer script for Inno Setup 6

#define MyAppName "GROMOV Restore+"
#define MyAppVersion "1.1.0"
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
OutputDir=..\dist
OutputBaseFilename=GROMOV-RestorePlus-Setup
SetupIconFile=..\assets\icon.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; GroupDescription: "Дополнительно:"; Flags: checkedonce

[Files]
Source: "..\dist\GROMOV-RestorePlus\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\drivers\install_drivers.bat"; Description: "Установить драйверы Apple для iPhone"; Flags: postinstall runascurrentuser waituntilterminated skipifsilent
Filename: "{app}\{#MyAppExeName}"; Description: "Запустить {#MyAppName}"; Flags: postinstall nowait skipifsilent

[Messages]
russian.WelcomeLabel2=Установит GROMOV Restore+ для восстановления приложений App Store на iPhone.%n%nБудут установлены драйверы Apple и все необходимые компоненты.
