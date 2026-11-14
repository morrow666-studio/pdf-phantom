# Gỡ cài đặt PDF Phantom (giữ lại cài đặt cá nhân trong %APPDATA%\PDFPhantom)
$Target = Join-Path $env:LOCALAPPDATA "Programs\PDF Phantom"
Add-Type -AssemblyName System.Windows.Forms
$r = [System.Windows.Forms.MessageBox]::Show("Go cai dat PDF Phantom khoi may?", "PDF Phantom", "YesNo", "Question")
if ($r -ne "Yes") { exit 0 }
Get-Process "PDF Phantom" -ErrorAction SilentlyContinue | Stop-Process -Force
Remove-Item -Force (Join-Path ([Environment]::GetFolderPath("Desktop")) "PDF Phantom.lnk") -ErrorAction SilentlyContinue
Remove-Item -Force (Join-Path ([Environment]::GetFolderPath("Programs")) "PDF Phantom.lnk") -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force "HKCU:\Software\Classes\PDFPhantom.Document" -ErrorAction SilentlyContinue
Remove-ItemProperty -Path "HKCU:\Software\Classes\.pdf\OpenWithProgids" -Name "PDFPhantom.Document" -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force "HKCU:\Software\Classes\Applications\PDF Phantom.exe" -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\PDFPhantom" -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force (Join-Path $env:LOCALAPPDATA "PDFPhantom\build_env") -ErrorAction SilentlyContinue
Start-Sleep -Milliseconds 300
Remove-Item -Recurse -Force $Target -ErrorAction SilentlyContinue
[System.Windows.Forms.MessageBox]::Show("Da go PDF Phantom.", "PDF Phantom") | Out-Null
