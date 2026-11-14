"""Hộp thoại NHÂN BẢN ẢNH / CON DẤU sang các trang khác và sang các file PDF đang mở."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGroupBox, QRadioButton, QLineEdit, QComboBox,
                               QListWidget, QListWidgetItem, QDialogButtonBox, QLabel, QCheckBox, QButtonGroup)

from .util import parse_pages

POS_MODES = [("edge", "Giữ khoảng cách tới mép gần nhất – giữ cỡ ảnh (khuyên dùng)"),
             ("same", "Giữ nguyên toạ độ như trang gốc"),
             ("scale", "Co giãn theo khổ trang (trang khác khổ giấy)")]


class DuplicateDialog(QDialog):
    def __init__(self, main, tab, pno, parent=None):
        super().__init__(parent or main)
        self.setWindowTitle("Nhân bản ảnh sang trang / file khác")
        self.setMinimumWidth(520)
        self.main, self.tab, self.pno = main, tab, pno
        v = QVBoxLayout(self)
        v.addWidget(QLabel(f"Ảnh đang chọn ở <b>trang {pno + 1}</b> của <b>{tab.pdf.name}</b>."))

        g = QGroupBox("Các trang nhận ảnh")
        gl = QVBoxLayout(g)
        self.grp = QButtonGroup(self)
        self.r_all = QRadioButton("Tất cả các trang (bỏ qua trang đang có ảnh gốc)")
        self.r_odd = QRadioButton("Trang lẻ (1, 3, 5…)")
        self.r_even = QRadioButton("Trang chẵn (2, 4, 6…)")
        self.r_list = QRadioButton("Các trang:")
        self.pages = QLineEdit()
        self.pages.setPlaceholderText("vd: 2-5, 8, 10-12")
        self.pages.textEdited.connect(lambda *_: self.r_list.setChecked(True))
        for k, r in enumerate((self.r_all, self.r_odd, self.r_even, self.r_list)):
            self.grp.addButton(r, k)
        self.r_all.setChecked(True)
        gl.addWidget(self.r_all)
        gl.addWidget(self.r_odd)
        gl.addWidget(self.r_even)
        h = QHBoxLayout()
        h.addWidget(self.r_list)
        h.addWidget(self.pages, 1)
        gl.addLayout(h)
        v.addWidget(g)

        g2 = QGroupBox("Sang các file (đang mở trong PDF Phantom)")
        g2l = QVBoxLayout(g2)
        self.files = QListWidget()
        self.files.setMaximumHeight(140)
        for t in main._tabs():
            it = QListWidgetItem(t.pdf.name + ("  (file hiện tại)" if t is tab else f"  – {t.pdf.page_count} trang"))
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if t is tab else Qt.Unchecked)
            it.setData(Qt.UserRole, t)
            self.files.addItem(it)
        g2l.addWidget(self.files)
        g2l.addWidget(QLabel("<i>Muốn dán sang file chưa mở: mở file đó trước, hoặc chọn ảnh → Ctrl+C, "
                             "sang file kia → Ctrl+V.</i>"))
        v.addWidget(g2)

        g3 = QGroupBox("Vị trí trên trang nhận")
        g3l = QVBoxLayout(g3)
        self.pos = QComboBox()
        for k, txt in POS_MODES:
            self.pos.addItem(txt, k)
        g3l.addWidget(self.pos)
        self.group = QCheckBox("Gắn nhóm – sau này xoá / sửa được tất cả bản nhân cùng lúc")
        self.group.setChecked(True)
        g3l.addWidget(self.group)
        v.addWidget(g3)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Nhân bản")
        bb.button(QDialogButtonBox.Cancel).setText("Huỷ")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def targets(self):
        """-> [(tab, [pno...])]"""
        mode = self.grp.checkedId()
        out = []
        for i in range(self.files.count()):
            it = self.files.item(i)
            if it.checkState() != Qt.Checked:
                continue
            t = it.data(Qt.UserRole)
            n = t.pdf.page_count
            if mode == 0:
                pages = list(range(n))
            elif mode == 1:
                pages = list(range(0, n, 2))
            elif mode == 2:
                pages = list(range(1, n, 2))
            else:
                try:
                    pages = sorted(set(parse_pages(self.pages.text(), n))) if self.pages.text().strip() else []
                except Exception:
                    pages = []
            if t is self.tab:
                pages = [p for p in pages if p != self.pno]
            if pages:
                out.append((t, pages))
        return out
