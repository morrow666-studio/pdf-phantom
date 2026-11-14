; Tạo 1 file Setup.exe duy nhất để chia sẻ cho đồng nghiệp (tuỳ chọn).
; Cách dùng: sau khi chạy CAI_DAT.bat thành công, cài Inno Setup (jrsoftware.org, miễn phí),
; mở file này và bấm Build -> ra file Output\PDFPhantom_Setup_1.0.0.exe
#define AppName "PDF Phantom"
#define AppVer "1.4.6"
#define BuildDir GetEnv("LOCALAPPDATA") + "\PDFPhantom\dist\PDF Phantom"

[Setup]
AppId={{6C3CE1A0-0DF0-4A11-9C1E-0A0A0A0A0001}
AppName={#AppName}
AppVersion={#AppVer}
AppPublisher=Nguyen Van Luan - PC1 My Dinh
DefaultDirName={localappdata}\Programs\PDF Phantom
DefaultGroupName=PDF Phantom
PrivilegesRequired=lowest
OutputBaseFilename=PDFPhantom_Setup_{#AppVer}
SetupIconFile=assets\icon.ico
UninstallDisplayIcon={app}\PDF Phantom.exe
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ChangesAssociations=yes

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Tao bieu tuong ngoai Desktop"; Flags: checkedonce

[Files]
Source: "{#BuildDir}\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion
Source: "tessdata\*"; DestDir: "{app}\tessdata"; Flags: recursesubdirs ignoreversion skipifsourcedoesntexist
Source: "plugins\*"; DestDir: "{app}\plugins"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\PDF Phantom"; Filename: "{app}\PDF Phantom.exe"
Name: "{userdesktop}\PDF Phantom"; Filename: "{app}\PDF Phantom.exe"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Classes\PDFPhantom.Document"; ValueType: string; ValueData: "PDF Document"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\PDFPhantom.Document\DefaultIcon"; ValueType: string; ValueData: """{app}\PDF Phantom.exe"",0"
Root: HKCU; Subkey: "Software\Classes\PDFPhantom.Document\shell\open\command"; ValueType: string; ValueData: """{app}\PDF Phantom.exe"" ""%1"""
Root: HKCU; Subkey: "Software\Classes\.pdf\OpenWithProgids"; ValueType: binary; ValueName: "PDFPhantom.Document"; ValueData: ""; Flags: uninsdeletevalue

[Run]
Filename: "{app}\PDF Phantom.exe"; Description: "Mo PDF Phantom"; Flags: nowait postinstall skipifsilent
