#define AppName "GitHubLauncher"
#ifndef AppVersion
#define AppVersion "1.0.0"
#endif
#define AppPublisher "GitHubLauncher"

[Setup]
AppId={{A17BB820-8D4B-4510-B984-390B84262489}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
OutputDir=dist
OutputBaseFilename=GitHubLauncher-Setup
SetupIconFile=assets\githublauncher.ico
UninstallDisplayIcon={app}\GitHubLauncher.exe
ArchitecturesInstallIn64BitMode=x64
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest

[Files]
Source: "dist\GitHubLauncher.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\GitHubLauncher"; Filename: "{app}\GitHubLauncher.exe"
Name: "{autodesktop}\GitHubLauncher"; Filename: "{app}\GitHubLauncher.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"

[Run]
Filename: "{app}\GitHubLauncher.exe"; Description: "Launch GitHubLauncher"; Flags: postinstall nowait skipifsilent
