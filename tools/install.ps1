# Bộ cài PDF Phantom cho Windows 10/11 (không cần quyền Admin)
$ErrorActionPreference = "Continue"   # lệnh ngoài (pip, PyInstaller) ghi log ra stderr - không coi là lỗi
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ProgressPreference = "SilentlyContinue"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Src      = Split-Path -Parent $PSScriptRoot                     # thư mục mã nguồn
$Work     = Join-Path $env:LOCALAPPDATA "PDFPhantom"
$Venv     = Join-Path $Work "build_env"
$Target   = Join-Path $env:LOCALAPPDATA "Programs\PDF Phantom"
$Log      = Join-Path $Work "install.log"
New-Item -ItemType Directory -Force -Path $Work | Out-Null
Start-Transcript -Path $Log -Force | Out-Null

function Step($t) { Write-Host ""; Write-Host ">>> $t" -ForegroundColor Cyan }
function Ok($t)   { Write-Host "    [OK] $t" -ForegroundColor Green }

try {
    # ---------------------------------------------------------------- 1. Python
    Step "1/5 Kiem tra Python 3.12"
    $py = $null
    foreach ($cand in @("py -3.12", "python3.12", "python")) {
        try {
            $v = & cmd /c "$cand --version 2>&1"
            if ($v -match "Python 3\.(1[0-3])") { $py = $cand; break }
        } catch {}
    }
    if (-not $py) {
        Write-Host "    Chua co Python phu hop -> tai Python 3.12 tu python.org ..."
        $inst = Join-Path $Work "python-3.12.10-amd64.exe"
        Invoke-WebRequest "https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe" -OutFile $inst -ErrorAction Stop
        Start-Process $inst -ArgumentList "/quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_test=0" -Wait
        $py = "py -3.12"
        $env:Path = [Environment]::GetEnvironmentVariable("Path", "User") + ";" + $env:Path
    }
    Ok "Dung: $py ($(& cmd /c "$py --version 2>&1"))"

    # ------------------------------------------------------- 2. Môi trường build
    Step "2/5 Tao moi truong va tai thu vien (lan dau mat vai phut)"
    if (-not (Test-Path (Join-Path $Venv "Scripts\python.exe"))) {
        & cmd /c "$py -m venv `"$Venv`""
    }
    if (-not (Test-Path (Join-Path $Venv "Scripts\python.exe"))) { throw "Khong tao duoc moi truong Python." }
    $vpy = Join-Path $Venv "Scripts\python.exe"
    & $vpy -m pip install --upgrade pip --quiet --disable-pip-version-check
    & $vpy -m pip install -r (Join-Path $Src "requirements.txt") pyinstaller --quiet --disable-pip-version-check
    if ($LASTEXITCODE -ne 0) { throw "Khong tai duoc thu vien (kiem tra Internet / proxy cong ty)." }
    # USB Token: tuỳ chọn, lỗi không dừng cài đặt
    & $vpy -m pip install python-pkcs11 --quiet --disable-pip-version-check
    if ($LASTEXITCODE -eq 0) { Ok "Ho tro USB Token: co" } else { Write-Host "    [!] Khong cai duoc python-pkcs11 -> ky so bang USB Token tam thoi chua dung duoc (file .pfx van dung duoc)" -ForegroundColor Yellow }
    Ok "Thu vien da san sang"

    # ---------------------------------------------------------------- 3. Đóng gói
    Step "3/5 Dong goi PDF Phantom.exe"
    $dist = Join-Path $Work "dist"
    $buildw = Join-Path $Work "build"
    Push-Location $Src
    & $vpy -m PyInstaller --noconfirm --clean --log-level WARN --distpath $dist --workpath $buildw "PDFPhantom.spec"
    Pop-Location
    if ($LASTEXITCODE -ne 0) { throw "Dong goi that bai." }
    Ok "Da tao $dist\PDF Phantom"

    # ------------------------------------------------------------------ 4. Cài đặt
    Step "4/5 Cai vao $Target"
    Get-Process "PDF Phantom" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 500
    if (Test-Path $Target) { Remove-Item -Recurse -Force (Join-Path $Target "_internal") -ErrorAction SilentlyContinue }
    New-Item -ItemType Directory -Force -Path $Target | Out-Null
    Copy-Item -Recurse -Force (Join-Path $dist "PDF Phantom\*") $Target -ErrorAction Stop
    foreach ($d in @("tessdata", "plugins")) {
        $s = Join-Path $Src $d
        if (Test-Path $s) { Copy-Item -Recurse -Force $s $Target }
    }
    # Dữ liệu OCR tiếng Việt: tải nếu bộ cài không kèm sẵn
    $td = Join-Path $Target "tessdata"
    New-Item -ItemType Directory -Force -Path $td | Out-Null
    foreach ($lang in @("vie", "eng")) {
        $f = Join-Path $td "$lang.traineddata"
        if (-not (Test-Path $f) -or (Get-Item $f).Length -lt 100000) {
            Write-Host "    Tai du lieu OCR: $lang ..."
            try { Invoke-WebRequest "https://raw.githubusercontent.com/tesseract-ocr/tessdata_best/main/$lang.traineddata" -OutFile $f -ErrorAction Stop }
            catch { Write-Host "    [!] Khong tai duoc $lang.traineddata - OCR se khong dung duoc" -ForegroundColor Yellow }
        }
    }
    Copy-Item -Force (Join-Path $PSScriptRoot "uninstall.ps1") $Target
    Ok "Da cai dat"

    # ---------------------------------------------------- 5. Lối tắt + liên kết PDF
    Step "5/5 Tao bieu tuong va lien ket file PDF"
    $exe = Join-Path $Target "PDF Phantom.exe"
    $ws = New-Object -ComObject WScript.Shell
    $desk = [Environment]::GetFolderPath("Desktop")
    $start = Join-Path ([Environment]::GetFolderPath("Programs")) "PDF Phantom.lnk"
    foreach ($lnkPath in @((Join-Path $desk "PDF Phantom.lnk"), $start)) {
        $l = $ws.CreateShortcut($lnkPath)
        $l.TargetPath = $exe
        $l.WorkingDirectory = $Target
        $l.IconLocation = "$exe,0"
        $l.Description = "PDF Phantom - doc, ghi chu, gop, tach, chuyen doi, ky so PDF"
        $l.Save()
    }
    # Đăng ký "Mở bằng" cho .pdf (người dùng chọn làm mặc định trong Windows)
    $cls = "HKCU:\Software\Classes"
    New-Item -Force "$cls\PDFPhantom.Document\shell\open\command" | Out-Null
    Set-ItemProperty "$cls\PDFPhantom.Document" "(default)" "Tài liệu PDF"
    New-Item -Force "$cls\PDFPhantom.Document\DefaultIcon" | Out-Null
    Set-ItemProperty "$cls\PDFPhantom.Document\DefaultIcon" "(default)" "`"$exe`",0"
    Set-ItemProperty "$cls\PDFPhantom.Document\shell\open\command" "(default)" "`"$exe`" `"%1`""
    New-Item -Force "$cls\.pdf\OpenWithProgids" | Out-Null
    New-ItemProperty -Force -Path "$cls\.pdf\OpenWithProgids" -Name "PDFPhantom.Document" -Value ([byte[]]@()) -PropertyType Binary | Out-Null
    New-Item -Force "$cls\Applications\PDF Phantom.exe\shell\open\command" | Out-Null
    Set-ItemProperty "$cls\Applications\PDF Phantom.exe\shell\open\command" "(default)" "`"$exe`" `"%1`""
    New-Item -Force "$cls\Applications\PDF Phantom.exe\SupportedTypes" | Out-Null
    foreach ($e in @(".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp")) {
        New-ItemProperty -Force -Path "$cls\Applications\PDF Phantom.exe\SupportedTypes" -Name $e -Value "" | Out-Null
    }
    # Gỡ cài đặt trong Settings > Apps
    $un = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\PDFPhantom"
    New-Item -Force $un | Out-Null
    Set-ItemProperty $un "DisplayName" "PDF Phantom"
    Set-ItemProperty $un "DisplayVersion" "1.4.6"
    Set-ItemProperty $un "Publisher" "Nguyen Van Luan - PC1 My Dinh"
    Set-ItemProperty $un "DisplayIcon" "`"$exe`",0"
    Set-ItemProperty $un "InstallLocation" $Target
    Set-ItemProperty $un "UninstallString" "powershell -NoProfile -ExecutionPolicy Bypass -File `"$Target\uninstall.ps1`""
    Set-ItemProperty $un "NoModify" 1 -Type DWord
    Set-ItemProperty $un "NoRepair" 1 -Type DWord
    Ok "Xong"

    Step "Tu kiem tra phan mem"
    $p = Start-Process $exe -ArgumentList "--selftest" -Wait -PassThru -WindowStyle Hidden
    $res = Get-Content (Join-Path $env:APPDATA "PDFPhantom\selftest.txt") -Encoding UTF8 -ErrorAction SilentlyContinue
    $res | ForEach-Object { Write-Host "    $_" }

    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Green
    Write-Host " DA CAI DAT XONG PDF PHANTOM" -ForegroundColor Green
    Write-Host " - Mo tu bieu tuong 'PDF Phantom' ngoai Desktop" -ForegroundColor Green
    Write-Host " - Dat lam phan mem mac dinh mo PDF: chuot phai file PDF >" -ForegroundColor Green
    Write-Host "   Open with > Choose another app > PDF Phantom > Always" -ForegroundColor Green
    Write-Host "============================================================" -ForegroundColor Green
    Start-Process $exe
    Stop-Transcript | Out-Null
    exit 0
}
catch {
    Write-Host ""
    Write-Host "LOI: $($_.Exception.Message)" -ForegroundColor Red
    Stop-Transcript | Out-Null
    exit 1
}
