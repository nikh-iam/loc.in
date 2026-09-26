#define AppName "loc.in"
#define AppVersion "1.1.1"

[Setup]
AppId={{D3179EBA-0C3F-430C-B643-CF055558D19D}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=loc.in
DefaultDirName={autopf}\loc.in
DefaultGroupName=loc.in
DisableProgramGroupPage=yes
OutputDir=..\release
OutputBaseFilename=loc.in Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\locin.exe
CloseApplications=yes
RestartApplications=no
SetupIconFile=locin.ico

[Files]
Source: "..\dist\locin\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\loc.in"; Filename: "{app}\locin.exe"
Name: "{autodesktop}\loc.in"; Filename: "{app}\locin.exe"

[Run]
; Scope ingress to Private/Domain profiles and directly attached subnets only.
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""loc.in LAN"""; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""loc.in Discovery"""; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""loc.in LAN"" dir=in action=allow program=""{app}\locin.exe"" protocol=TCP localport=80,8000 profile=private,domain remoteip=localsubnet"; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""loc.in Discovery"" dir=in action=allow program=""{app}\locin.exe"" protocol=UDP localport=5353 profile=private,domain remoteip=localsubnet"; Flags: runhidden
Filename: "{app}\locin.exe"; Description: "Launch loc.in"; Flags: nowait postinstall skipifsilent runasoriginaluser

[UninstallRun]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""loc.in LAN"""; Flags: runhidden; RunOnceId: "LocinLAN"
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""loc.in Discovery"""; Flags: runhidden; RunOnceId: "LocinDiscovery"
