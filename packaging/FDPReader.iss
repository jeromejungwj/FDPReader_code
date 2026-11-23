; FDP Reader 설치 파일. packaging\build.py 가 /DAppVersion 을 넘겨 컴파일함.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{89B0E1CD-D467-4E19-9009-9F2255321538}
AppName=FDP Reader
AppVersion={#AppVersion}
AppVerName=FDP Reader {#AppVersion}
AppPublisher=jeromejungwj
AppPublisherURL=https://github.com/jeromejungwj/FDPReader_code
AppSupportURL=https://github.com/jeromejungwj/FDPReader_code/issues
DefaultDirName={autopf}\FDP Reader
DefaultGroupName=FDP Reader
DisableProgramGroupPage=yes
; 관리자 권한 없이 현재 사용자에게 설치 (%LOCALAPPDATA%\Programs)
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
LicenseFile=..\LICENSE
SetupIconFile=..\build\FDPReader.ico
UninstallDisplayIcon={app}\FDPReader.exe
OutputBaseFilename=FDPReader-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\FDPReader\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\FDP Reader"; Filename: "{app}\FDPReader.exe"
Name: "{autodesktop}\FDP Reader"; Filename: "{app}\FDPReader.exe"; Tasks: desktopicon

[Registry]
; 앱의 "PDF 연결 프로그램으로 등록" 메뉴가 만든 항목만 제거 시 지움 (설치할 때는 만들지 않음)
Root: HKA; Subkey: "Software\Classes\FDPReader.pdf"; Flags: uninsdeletekey dontcreatekey
Root: HKA; Subkey: "Software\FDPReader"; Flags: uninsdeletekey dontcreatekey
Root: HKA; Subkey: "Software\Classes\.pdf\OpenWithProgids"; ValueType: none; ValueName: "FDPReader.pdf"; Flags: uninsdeletevalue dontcreatekey
Root: HKA; Subkey: "Software\RegisteredApplications"; ValueType: none; ValueName: "FDP Reader"; Flags: uninsdeletevalue dontcreatekey

[Run]
Filename: "{app}\FDPReader.exe"; Description: "{cm:LaunchProgram,FDP Reader}"; Flags: nowait postinstall skipifsilent
