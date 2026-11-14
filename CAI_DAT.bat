@echo off
chcp 65001 >nul
title Cai dat PDF Phantom
echo ============================================================
echo    CAI DAT PDF PHANTOM - phan mem PDF mien phi, khong quang cao
echo ============================================================
echo.
echo  Qua trinh tu dong (lan dau mat khoang 5-15 phut, can Internet):
echo   1. Kiem tra / cai Python 3.12
echo   2. Tai thu vien va dong goi thanh PDF Phantom.exe
echo   3. Cai vao may, tao bieu tuong Desktop + menu Start
echo.
echo  Khong can quyen Administrator. Bam phim bat ky de bat dau...
pause >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\install.ps1"
if errorlevel 1 (
  echo.
  echo  CAI DAT CHUA THANH CONG. Xem file nhat ky: %LOCALAPPDATA%\PDFPhantom\install.log
  echo  Chup man hinh loi gui lai de duoc ho tro.
  pause
  exit /b 1
)
echo.
echo  HOAN TAT! Mo PDF Phantom tu bieu tuong ngoai Desktop.
pause
