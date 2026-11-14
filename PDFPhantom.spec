# -*- mode: python ; coding: utf-8 -*-
# Cấu hình đóng gói PyInstaller cho PDF Phantom (chạy: pyinstaller PDFPhantom.spec)
import sys
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

datas, binaries, hiddenimports = [], [], []
for pkg in ("pdf2docx", "pyhanko", "pyhanko_certvalidator", "docx", "pymupdf_fonts", "uharfbuzz", "fontTools", "ezdxf"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        pass
try:
    hiddenimports += collect_submodules("pkcs11")
except Exception:
    pass
datas += [("assets", "assets")]
hiddenimports += ["PySide6.QtPrintSupport", "PySide6.QtNetwork", "asn1crypto", "tzlocal", "oscrypto"]

a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "matplotlib", "IPython", "pytest", "scipy", "pandas", "sklearn", "torch", "gi", "PyQt5", "PyQt6", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
              "PySide6.Qt3DCore", "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtMultimedia", "PySide6.QtCharts",
              "PySide6.QtDataVisualization", "PySide6.QtPdf"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="PDF Phantom",
    icon="assets/icon.ico",
    console=False,
    version=None,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="PDF Phantom")
