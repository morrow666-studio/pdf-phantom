"""Hộp thoại Cài đặt."""
import os

from PySide6.QtWidgets import (QDialog, QVBoxLayout, QTabWidget, QWidget, QFormLayout, QComboBox, QLineEdit,
                               QPushButton, QHBoxLayout, QLabel, QDialogButtonBox, QFileDialog, QDoubleSpinBox)

from .util import config, tessdata_dir, user_dir
from .ops_sign import find_pkcs11_dlls


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Cài đặt PDF Phantom")
        self.setMinimumWidth(600)
        c = config()
        lay = QVBoxLayout(self)
        tabs = QTabWidget()
        lay.addWidget(tabs)

        w = QWidget()
        f = QFormLayout(w)
        self.theme = QComboBox()
        self.theme.addItems(["Sáng", "Tối"])
        self.theme.setCurrentIndex(0 if c.get("theme") == "light" else 1)
        f.addRow("Giao diện:", self.theme)
        self.font = QComboBox()
        self.font.addItems(["Times New Roman", "Arial"])
        self.font.setCurrentIndex(0 if c.get("default_font", "times") == "times" else 1)
        f.addRow("Phông mặc định (sửa chữ, Word):", self.font)
        self.signer = QLineEdit(c.get("signer_name", ""))
        f.addRow("Tên người dùng (ghi chú, chữ ký):", self.signer)
        tabs.addTab(w, "Chung")

        w = QWidget()
        f = QFormLayout(w)
        self.key = QLineEdit(c.get("claude_api_key", ""), echoMode=QLineEdit.Password,
                             placeholderText="sk-ant-…")
        f.addRow("API key Anthropic:", self.key)
        self.model = QComboBox(editable=True)
        self.model.addItems(["claude-sonnet-5-5", "claude-opus-5-5", "claude-haiku-5-5"])
        self.model.setCurrentText(c.get("claude_model", "claude-sonnet-5-5"))
        f.addRow("Model:", self.model)
        f.addRow(QLabel("<i>Lấy API key tại console.anthropic.com → API Keys (tính phí theo lượng dùng).\n"
                        "Sonnet: cân bằng tốc độ/chất lượng · Opus: mạnh nhất · Haiku: nhanh, rẻ.\n"
                        "Key chỉ lưu trên máy anh (%APPDATA%\\PDFPhantom\\config.json).</i>"))
        tabs.addTab(w, "Claude AI")

        w = QWidget()
        f = QFormLayout(w)
        self.lang = QComboBox()
        self.lang.addItems(["vie+eng", "vie", "eng"])
        self.lang.setCurrentText(c.get("ocr_lang", "vie+eng"))
        f.addRow("Ngôn ngữ OCR:", self.lang)
        td = tessdata_dir()
        f.addRow("Dữ liệu OCR:", QLabel(td or "CHƯA CÓ – chạy lại CAI_DAT.bat"))
        tabs.addTab(w, "Nhận dạng chữ")

        w = QWidget()
        f = QFormLayout(w)
        self.dll = QComboBox(editable=True)
        self.dll.addItems([d for d in [c.get("pkcs11_dll")] if d] + find_pkcs11_dlls())
        b = QPushButton("…")
        b.setProperty("small", True)
        b.clicked.connect(lambda: self._pick(self.dll))
        r = QHBoxLayout()
        r.addWidget(self.dll, 1)
        r.addWidget(b)
        f.addRow("Thư viện USB Token:", r)
        self.tsa = QLineEdit(c.get("tsa_url", ""))
        f.addRow("Máy chủ dấu thời gian:", self.tsa)
        self.loc = QLineEdit(c.get("signer_location", ""))
        f.addRow("Nơi ký mặc định:", self.loc)
        tabs.addTab(w, "Ký số")

        w = QWidget()
        f = QFormLayout(w)
        from .ops_cad import find_oda
        self.oda = QLineEdit(c.get("oda_path", "") or (find_oda() or ""),
                             placeholderText=r"C:\Program Files\ODA\ODAFileConverter 26.x\ODAFileConverter.exe")
        b2 = QPushButton("…")
        b2.setProperty("small", True)
        b2.clicked.connect(lambda: self._pick_exe(self.oda))
        r2 = QHBoxLayout()
        r2.addWidget(self.oda, 1)
        r2.addWidget(b2)
        f.addRow("ODA File Converter:", r2)
        f.addRow(QLabel("<i>Dùng để lưu thẳng file DWG. Tải miễn phí tại opendesign.com → ODA File Converter.\n"
                        "Không có vẫn xuất được DXF (AutoCAD mở trực tiếp).</i>"))
        tabs.addTab(w, "Bản vẽ CAD")

        w = QWidget()
        f = QFormLayout(w)
        self.upd = QLineEdit(c.get("update_url", ""), placeholderText="https://…/version.json (tuỳ chọn)")
        f.addRow("Địa chỉ kiểm tra cập nhật:", self.upd)
        f.addRow(QLabel(f"Thư mục dữ liệu: {user_dir()}"))
        tabs.addTab(w, "Cập nhật")

        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Save).setText("Lưu")
        bb.button(QDialogButtonBox.Cancel).setText("Huỷ")
        bb.accepted.connect(self.save)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _pick(self, combo):
        p, _ = QFileDialog.getOpenFileName(self, "Chọn DLL", r"C:\Windows\System32", "DLL (*.dll)")
        if p:
            combo.setCurrentText(p)

    def _pick_exe(self, edit):
        p, _ = QFileDialog.getOpenFileName(self, "Chọn chương trình", r"C:\Program Files", "Chương trình (*.exe)")
        if p:
            edit.setText(p)

    def save(self):
        c = config()
        c["oda_path"] = self.oda.text().strip()
        c["theme"] = "light" if self.theme.currentIndex() == 0 else "dark"
        c["default_font"] = "times" if self.font.currentIndex() == 0 else "arial"
        c["signer_name"] = self.signer.text()
        c["claude_api_key"] = self.key.text().strip()
        c["claude_model"] = self.model.currentText().strip()
        c["ocr_lang"] = self.lang.currentText()
        c["pkcs11_dll"] = self.dll.currentText()
        c["tsa_url"] = self.tsa.text().strip()
        c["signer_location"] = self.loc.text()
        c["update_url"] = self.upd.text().strip()
        c.save()
        self.accept()
