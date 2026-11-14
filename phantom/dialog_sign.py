"""Hộp thoại ký số: chọn chứng thư (file .pfx hoặc USB Token), thông tin & hình chữ ký."""
import os

import pymupdf as fitz
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QTabWidget, QWidget, QLabel,
                               QLineEdit, QPushButton, QComboBox, QCheckBox, QFileDialog, QMessageBox,
                               QPlainTextEdit, QGroupBox, QDialogButtonBox)

from . import ops_sign as sg
from .annots import ColorButton
from .util import config, user_dir
from .viewer import pix_to_qimage
from .widgets import ask_save, done_message


class SignDialog(QDialog):
    def __init__(self, parent=None, pdfdoc=None, pno=0, rect=None):
        super().__init__(parent)
        self.pdf = pdfdoc
        self.pno = pno
        self.rect = rect              # vùng chữ ký (toạ độ hiển thị) hoặc None = ký ẩn
        self.setWindowTitle("Ký số tài liệu")
        self.resize(760, 600)
        cfg = config()
        lay = QHBoxLayout(self)
        left = QVBoxLayout()
        lay.addLayout(left, 3)

        g = QGroupBox("1. Chứng thư số")
        gl = QVBoxLayout(g)
        self.tabs = QTabWidget()
        # --- USB token
        wt = QWidget()
        ft = QFormLayout(wt)
        self.dll = QComboBox(editable=True)
        self.dll.addItems([d for d in [cfg.get("pkcs11_dll")] if d] + sg.find_pkcs11_dlls())
        bd = QPushButton("…")
        bd.setProperty("small", True)
        bd.setFixedWidth(30)
        bd.clicked.connect(self.pick_dll)
        r = QHBoxLayout()
        r.addWidget(self.dll, 1)
        r.addWidget(bd)
        ft.addRow("Thư viện token (.dll):", r)
        self.pin = QLineEdit(echoMode=QLineEdit.Password, placeholderText="Mã PIN của USB Token")
        ft.addRow("Mã PIN:", self.pin)
        rb = QPushButton("Đọc chứng thư trong Token")
        rb.clicked.connect(self.read_token)
        ft.addRow(rb)
        self.certs = QComboBox()
        ft.addRow("Chứng thư:", self.certs)
        ft.addRow(QLabel("<i>Cắm USB Token và cài driver của nhà cung cấp (Viettel-CA, VNPT-CA, FPT-CA,\n"
                         "BKAV-CA, MISA…). Nếu không tự tìm thấy file .dll, bấm … và chọn trong\n"
                         "C:\\Windows\\System32 (tên thường chứa 'p11', 'pkcs11' hoặc 'csp11').</i>"))
        self.tabs.addTab(wt, "USB Token")
        # --- PFX
        wp = QWidget()
        fp = QFormLayout(wp)
        self.pfx = QLineEdit(cfg.get("last_pfx", ""))
        bp = QPushButton("…")
        bp.setProperty("small", True)
        bp.setFixedWidth(30)
        bp.clicked.connect(self.pick_pfx)
        r2 = QHBoxLayout()
        r2.addWidget(self.pfx, 1)
        r2.addWidget(bp)
        fp.addRow("File chứng thư (.pfx/.p12):", r2)
        self.pfx_pw = QLineEdit(echoMode=QLineEdit.Password)
        fp.addRow("Mật khẩu:", self.pfx_pw)
        bt = QPushButton("Tạo chứng thư THỬ NGHIỆM (không giá trị pháp lý)…")
        bt.clicked.connect(self.make_test)
        fp.addRow(bt)
        self.tabs.addTab(wp, "File .pfx / .p12")
        gl.addWidget(self.tabs)
        left.addWidget(g)

        g2 = QGroupBox("2. Thông tin ký")
        f2 = QFormLayout(g2)
        self.reason = QComboBox(editable=True)
        self.reason.addItems(["", "Phê duyệt", "Đồng ý", "Xác nhận", "Kiểm tra", "Nghiệm thu", "Ký thay"])
        self.location = QLineEdit(cfg.get("signer_location", ""))
        self.contact = QLineEdit()
        self.tsa = QLineEdit(cfg.get("tsa_url", ""), placeholderText="URL máy chủ dấu thời gian (TSA) – tuỳ chọn")
        self.certify = QCheckBox("Chứng nhận tài liệu (khoá, không cho sửa sau khi ký)")
        f2.addRow("Lý do:", self.reason)
        f2.addRow("Nơi ký:", self.location)
        f2.addRow("Liên hệ:", self.contact)
        f2.addRow("Dấu thời gian:", self.tsa)
        f2.addRow(self.certify)
        left.addWidget(g2)

        right = QVBoxLayout()
        lay.addLayout(right, 2)
        g3 = QGroupBox("3. Hình thức hiển thị")
        f3 = QFormLayout(g3)
        self.visible = QCheckBox("Hiển thị khung chữ ký trên trang")
        self.visible.setChecked(rect is not None)
        self.visible.setEnabled(rect is not None)
        f3.addRow(self.visible)
        self.img = QLineEdit(cfg.get("sig_image", ""), placeholderText="Ảnh chữ ký tay / con dấu (PNG nền trong)")
        bi = QPushButton("…")
        bi.setProperty("small", True)
        bi.setFixedWidth(30)
        bi.clicked.connect(self.pick_img)
        r3 = QHBoxLayout()
        r3.addWidget(self.img, 1)
        r3.addWidget(bi)
        f3.addRow("Ảnh:", r3)
        self.show_text = QCheckBox("Hiện thông tin chữ (người ký, ngày giờ…)")
        self.show_text.setChecked(True)
        f3.addRow(self.show_text)
        self.color = ColorButton(cfg.get("sig_color", "#C00000"))
        f3.addRow("Màu chữ:", self.color)
        self.name = QLineEdit(cfg.get("signer_name", ""), placeholderText="Tự lấy từ chứng thư nếu để trống")
        f3.addRow("Tên hiển thị:", self.name)
        right.addWidget(g3)
        right.addWidget(QLabel("<b>Xem trước khung chữ ký</b>"))
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumHeight(140)
        self.preview.setStyleSheet("background:white; border:1px dashed #aaa;")
        right.addWidget(self.preview)
        right.addStretch()
        bb = QDialogButtonBox()
        ok = bb.addButton("Ký và lưu…", QDialogButtonBox.AcceptRole)
        ok.setObjectName("primary")
        bb.addButton("Huỷ", QDialogButtonBox.RejectRole)
        bb.accepted.connect(self.do_sign)
        bb.rejected.connect(self.reject)
        right.addWidget(bb)
        self.tabs.setCurrentIndex(0 if self.dll.count() else 1)
        self.timer = QTimer(self, singleShot=True, interval=200, timeout=self.update_preview)
        for w in (self.img, self.name, self.location):
            w.textChanged.connect(lambda *_: self.timer.start())
        self.reason.currentTextChanged.connect(lambda *_: self.timer.start())
        self.show_text.toggled.connect(lambda *_: self.timer.start())
        self.color.clicked.connect(lambda *_: QTimer.singleShot(50, self.timer.start))
        self.update_preview()
        self.out_path = None

    # ---------------------------------------------------------------- chọn
    def pick_dll(self):
        p, _ = QFileDialog.getOpenFileName(self, "Chọn thư viện PKCS#11", r"C:\Windows\System32", "DLL (*.dll)")
        if p:
            self.dll.setCurrentText(p)

    def pick_pfx(self):
        p, _ = QFileDialog.getOpenFileName(self, "Chọn chứng thư", "", "Chứng thư (*.pfx *.p12)")
        if p:
            self.pfx.setText(p)

    def pick_img(self):
        p, _ = QFileDialog.getOpenFileName(self, "Chọn ảnh chữ ký / con dấu", "", "Ảnh (*.png *.jpg *.jpeg *.bmp)")
        if p:
            self.img.setText(p)

    def make_test(self):
        p = os.path.join(user_dir(), "ChungThu_ThuNghiem.pfx")
        name = self.name.text() or "Nguoi ky thu nghiem"
        sg.make_test_pfx(p, "1234", name)
        self.pfx.setText(p)
        self.pfx_pw.setText("1234")
        QMessageBox.information(self, "Chứng thư thử nghiệm",
                                f"Đã tạo: {p}\nMật khẩu: 1234\n\nChỉ dùng để thử tính năng, KHÔNG có giá trị pháp lý.")

    def read_token(self):
        try:
            certs = sg.list_token_certs(self.dll.currentText(), self.pin.text())
        except ImportError:
            QMessageBox.critical(self, "Token", "Thiếu thư viện python-pkcs11. Hãy chạy lại CAI_DAT.bat.")
            return
        except Exception as e:
            QMessageBox.critical(self, "Token", f"Không đọc được Token:\n{e}\n\nKiểm tra: đã cắm token, đúng file .dll, đúng PIN.")
            return
        self.certs.clear()
        for tok, label, cid, subj in certs:
            self.certs.addItem(f"{subj}", (tok, label, cid))
        if not certs:
            QMessageBox.warning(self, "Token", "Không tìm thấy chứng thư trong Token.")

    # -------------------------------------------------------------- xem trước
    def lines(self, name=None):
        if not self.show_text.isChecked():
            return []
        return sg.default_lines(name or self.name.text() or "(tên trong chứng thư)", self.reason.currentText(),
                                self.location.text())

    def update_preview(self):
        if self.rect is None:
            self.preview.setText("Ký ẩn (không có khung hiển thị).\nDùng công cụ 'Ký số' rồi kéo khung trên trang\n"
                                 "để chọn vị trí hiển thị chữ ký.")
            return
        try:
            w, h = self.rect.width, self.rect.height
            png = sg.make_appearance(w, h, self.lines(), self.img.text() if os.path.isfile(self.img.text()) else None,
                                     self.color.color, zoom=2)
            pm = QPixmap(png)
            self.preview.setPixmap(pm.scaled(self.preview.width() - 10, 160, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        except Exception as e:
            self.preview.setText(str(e))

    # ------------------------------------------------------------------- ký
    def do_sign(self):
        cfg = config()
        if self.pdf.modified or not self.pdf.path:
            r = QMessageBox.question(self, "Ký số", "Tài liệu có thay đổi chưa lưu. Các thay đổi sẽ được đưa vào bản ký.\n"
                                                   "Tiếp tục?")
            if r != QMessageBox.Yes:
                return
        out = ask_save(self, "Lưu file đã ký", os.path.splitext(self.pdf.name)[0] + "_daky.pdf")
        if not out:
            return
        # file nguồn: nếu chưa sửa thì dùng bản gốc để giữ các chữ ký cũ (ký nhiều lần)
        import tempfile
        src = os.path.join(tempfile.gettempdir(), "phantom_tosign.pdf")
        if self.pdf.modified or not self.pdf.original_bytes:
            self.pdf.doc.save(src, garbage=1)
        else:
            with open(src, "wb") as f:
                f.write(self.pdf.original_bytes)
        page = self.pdf.doc[self.pno]
        box = None
        ph = page.mediabox.height
        if self.rect is not None and self.visible.isChecked():
            r = (fitz.Rect(self.rect) * page.derotation_matrix).normalize()
            # cropbox có thể lệch mediabox
            off = page.cropbox_position
            box = (r.x0 + off.x, r.y0 + off.y, r.x1 + off.x, r.y1 + off.y)
        img = self.img.text() if os.path.isfile(self.img.text()) else None
        try:
            if self.tabs.currentIndex() == 1:
                signer = sg.load_pfx(self.pfx.text(), self.pfx_pw.text())
                name = self.name.text() or sg.signer_name(signer)
                sg.sign_pdf(src, out, signer, self.pno, box, ph, self.reason.currentText(), self.location.text(),
                            self.contact.text(), img, self.show_text.isChecked(), self.lines(name),
                            self.tsa.text() or None, certify=self.certify.isChecked(), text_color=self.color.color)
                cfg["last_pfx"] = self.pfx.text()
            else:
                data = self.certs.currentData()
                if not data:
                    QMessageBox.warning(self, "Ký số", "Hãy bấm 'Đọc chứng thư trong Token' và chọn chứng thư.")
                    return
                tok, label, cid = data
                with sg.TokenSigner(self.dll.currentText(), self.pin.text(), tok, label, cid) as signer:
                    name = self.name.text() or sg.signer_name(signer)
                    sg.sign_pdf(src, out, signer, self.pno, box, ph, self.reason.currentText(), self.location.text(),
                                self.contact.text(), img, self.show_text.isChecked(), self.lines(name),
                                self.tsa.text() or None, certify=self.certify.isChecked(), text_color=self.color.color)
                cfg["pkcs11_dll"] = self.dll.currentText()
        except Exception as e:
            QMessageBox.critical(self, "Ký số", f"Ký không thành công:\n{e}")
            return
        cfg["signer_location"] = self.location.text()
        cfg["tsa_url"] = self.tsa.text()
        cfg["sig_image"] = self.img.text()
        cfg["sig_color"] = self.color.color
        cfg.save()
        self.out_path = out
        self.accept()
        done_message(self.parent(), "Đã ký số thành công.\nFile đã ký: " + out, out)


class VerifyDialog(QDialog):
    def __init__(self, parent=None, path=None):
        super().__init__(parent)
        self.setWindowTitle("Kiểm tra chữ ký số")
        self.resize(640, 420)
        lay = QVBoxLayout(self)
        t = QPlainTextEdit(readOnly=True)
        try:
            res = sg.verify_pdf(path)
        except Exception as e:
            res = [f"Lỗi: {e}"]
        t.setPlainText("\n\n".join(res) + "\n\nGhi chú: phần mềm kiểm tra tính toàn vẹn nội dung sau khi ký. "
                       "Để xác minh chuỗi tin cậy của nhà cung cấp CA, dùng thêm Adobe Reader hoặc "
                       "phần mềm của CA / Bộ TT&TT.")
        lay.addWidget(t)
        b = QPushButton("Đóng")
        b.clicked.connect(self.accept)
        lay.addWidget(b, alignment=Qt.AlignRight)
