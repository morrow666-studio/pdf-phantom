"""Thanh THUỘC TÍNH (dưới ribbon) – chỉnh chuyên nghiệp, áp dụng ngay:
- Khi chọn 1 ghi chú: màu nét, màu nền, độ dày, kiểu nét (liền/gạch/chấm/đám mây), độ mờ, đầu mũi tên,
  phông/cỡ/màu chữ (hộp chữ), xoay & co giãn ảnh/con dấu.
- Khi không chọn gì: chỉnh KIỂU MẶC ĐỊNH cho công cụ đang dùng (ghi chú vẽ mới sẽ theo kiểu này).
- Khi đang ĐẶT ẢNH: ô gõ số X, Y, Rộng, Cao (mm), Góc xoay (°), Giữ tỉ lệ, Độ mờ, Hoàn tất / Huỷ.
"""
import math

import pymupdf as fitz
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QColor, QPixmap, QIcon, QPainter, QPen
from PySide6.QtWidgets import (QToolBar, QWidget, QHBoxLayout, QLabel, QToolButton, QMenu, QWidgetAction,
                               QGridLayout, QColorDialog, QDoubleSpinBox, QComboBox, QSlider, QPushButton,
                               QCheckBox, QStackedWidget, QFrame)

from . import annots as A

PALETTE = ["#000000", "#424242", "#9E9E9E", "#FFFFFF", "#C62828", "#E53935", "#F4511E", "#EF6C00",
           "#F9A825", "#FDD835", "#7CB342", "#2E7D32", "#00897B", "#0288D1", "#1565C0", "#283593",
           "#6A1B9A", "#AD1457", "#FFCDD2", "#FFF9C4", "#C8E6C9", "#BBDEFB", "#E1BEE7", "#FFE0B2"]
DASH = [("Liền", None), ("Gạch", [6, 3]), ("Gạch ngắn", [3, 2]), ("Chấm", [1, 2]), ("Gạch chấm", [6, 3, 1, 3]),
        ("Đám mây", "cloud")]
ENDS = ["None", "OpenArrow", "ClosedArrow", "Circle", "Square", "Diamond", "Butt", "Slash"]
ENDS_VI = {"None": "Không", "OpenArrow": "Mũi tên hở", "ClosedArrow": "Mũi tên đặc", "Circle": "Tròn",
           "Square": "Vuông", "Diamond": "Thoi", "Butt": "Gạch ngang", "Slash": "Gạch chéo"}
FONTS = [("Helv", "Arial"), ("TiRo", "Times"), ("Cour", "Courier")]


def mm(pt):
    return pt * 25.4 / 72.0


def pt(mm_):
    return mm_ * 72.0 / 25.4


class ColorTool(QToolButton):
    """Nút màu: bảng màu nhanh + màu khác + (tuỳ chọn) không màu."""

    def __init__(self, label, allow_none=False, on_change=None):
        super().__init__()
        self.label, self.allow_none, self.on_change = label, allow_none, on_change
        self.color = ""
        self.setPopupMode(QToolButton.InstantPopup)
        self.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.setText(label)
        m = QMenu(self)
        w = QWidget()
        g = QGridLayout(w)
        g.setSpacing(2)
        g.setContentsMargins(4, 4, 4, 4)
        for i, c in enumerate(PALETTE):
            b = QToolButton()
            b.setFixedSize(20, 20)
            b.setStyleSheet(f"background:{c}; border:1px solid #999; border-radius:3px;")
            b.setToolTip(c)
            b.clicked.connect(lambda _=False, c=c: (m.close(), self.pick(c)))
            g.addWidget(b, i // 8, i % 8)
        wa = QWidgetAction(m)
        wa.setDefaultWidget(w)
        m.addAction(wa)
        m.addAction("Màu khác…", self.custom)
        if allow_none:
            m.addAction("Không màu (trong suốt)", lambda: self.pick(""))
        self.setMenu(m)
        self.set_color("")

    def set_color(self, c):
        self.color = c or ""
        pm = QPixmap(18, 18)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        if self.color:
            p.fillRect(1, 1, 16, 16, QColor(self.color))
            p.setPen(QPen(QColor("#777"), 1))
            p.drawRect(1, 1, 15, 15)
        else:
            p.setPen(QPen(QColor("#C62828"), 2))
            p.drawRect(2, 2, 14, 14)
            p.drawLine(2, 16, 16, 2)
        p.end()
        self.setIcon(QIcon(pm))

    def pick(self, c):
        self.set_color(c)
        if self.on_change:
            self.on_change(c)

    def custom(self):
        c = QColorDialog.getColor(QColor(self.color or "#FF0000"), self, self.label)
        if c.isValid():
            self.pick(c.name().upper())


class PropBar(QToolBar):
    def __init__(self, main):
        super().__init__("Thuộc tính")
        self.main = main
        self.setObjectName("propbar")
        self.setMovable(False)
        self.setIconSize(QSize(18, 18))
        self.tab = None
        self.sel = None              # (pno, xref)
        self.tool = "select"
        self._snap = False
        self._loading = False
        self.stack = QStackedWidget()
        self.addWidget(self.stack)
        self._build_annot()
        self._build_place()
        self.stack.setCurrentIndex(0)

    # ------------------------------------------------------------ giao diện
    def _row(self):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(6, 2, 6, 2)
        h.setSpacing(6)
        return w, h

    def _sep(self, h):
        f = QFrame()
        f.setFrameShape(QFrame.VLine)
        f.setStyleSheet("color:#CCC;")
        h.addWidget(f)

    def _build_annot(self):
        w, h = self._row()
        self.target = QLabel("Kiểu mặc định")
        self.target.setMinimumWidth(150)
        self.target.setStyleSheet("font-weight:600; color:#EF6C00;")
        h.addWidget(self.target)
        self.c_stroke = ColorTool("Nét", on_change=lambda c: self.change("stroke", c))
        self.c_fill = ColorTool("Nền", allow_none=True, on_change=lambda c: self.change("fill", c))
        h.addWidget(self.c_stroke)
        h.addWidget(self.c_fill)
        self._sep(h)
        h.addWidget(QLabel("Dày"))
        self.width_ = QDoubleSpinBox(minimum=0.0, maximum=30, singleStep=0.25, decimals=2, suffix=" pt")
        self.width_.setFixedWidth(78)
        self.width_.valueChanged.connect(lambda v: self.change("width", v))
        h.addWidget(self.width_)
        self.dash = QComboBox()
        for name, _ in DASH:
            self.dash.addItem(name)
        self.dash.currentIndexChanged.connect(lambda i: self.change("dash", i))
        h.addWidget(self.dash)
        self._sep(h)
        h.addWidget(QLabel("Độ mờ"))
        self.op = QSlider(Qt.Horizontal, minimum=5, maximum=100)
        self.op.setFixedWidth(90)
        self.op_lbl = QLabel("100%")
        self.op.valueChanged.connect(lambda v: (self.op_lbl.setText(f"{v}%"), self.change("opacity", v / 100)))
        h.addWidget(self.op)
        h.addWidget(self.op_lbl)
        self._sep(h)
        self.le_start = QComboBox()
        self.le_end = QComboBox()
        for k in ENDS:
            self.le_start.addItem(ENDS_VI[k], k)
            self.le_end.addItem(ENDS_VI[k], k)
        self.le_start.setToolTip("Đầu đường")
        self.le_end.setToolTip("Cuối đường")
        self.le_start.currentIndexChanged.connect(lambda *_: self.change("ends", None))
        self.le_end.currentIndexChanged.connect(lambda *_: self.change("ends", None))
        self.lbl_ends = QLabel("Đầu/cuối")
        for x in (self.lbl_ends, self.le_start, self.le_end):
            h.addWidget(x)
        self._sep(h)
        self.font = QComboBox()
        for k, v in FONTS:
            self.font.addItem(v, k)
        self.fsize = QDoubleSpinBox(minimum=4, maximum=200, decimals=1, suffix=" pt")
        self.fsize.setFixedWidth(72)
        self.c_text = ColorTool("Chữ", on_change=lambda c: self.change("text_color", c))
        self.font.currentIndexChanged.connect(lambda *_: self.change("font", self.font.currentData()))
        self.fsize.valueChanged.connect(lambda v: self.change("fontsize", v))
        for x in (self.font, self.fsize, self.c_text):
            h.addWidget(x)
        self._sep(h)
        self.b_stamp = QPushButton("Xoay / co giãn ảnh")
        self.b_stamp.setToolTip("Hoặc bấm đúp vào ảnh")
        self.b_stamp.clicked.connect(self.edit_stamp)
        h.addWidget(self.b_stamp)
        self.b_dup = QPushButton("Nhân bản sang trang / file…")
        self.b_dup.setObjectName("primary")
        self.b_dup.setToolTip("Đóng ảnh/con dấu này lên nhiều trang, hoặc sang các file PDF đang mở khác")
        self.b_dup.clicked.connect(lambda: self.tab and self.sel and self.tab.duplicate_stamp(*self.sel))
        h.addWidget(self.b_dup)
        self.b_copy = QPushButton("Sao chép (Ctrl+C)")
        self.b_copy.setToolTip("Sao chép ảnh – sang trang / file khác bấm Ctrl+V (dán đúng vị trí cũ)")
        self.b_copy.clicked.connect(lambda: self.tab and self.sel and self.tab.copy_stamp(*self.sel))
        h.addWidget(self.b_copy)
        self.b_more = QPushButton("Thêm…")
        self.b_more.setToolTip("Nội dung, tác giả, biểu tượng ghi chú…")
        self.b_more.clicked.connect(self.more)
        h.addWidget(self.b_more)
        self.b_default = QPushButton("Lưu làm mặc định")
        self.b_default.clicked.connect(self.save_default)
        h.addWidget(self.b_default)
        h.addStretch()
        self.stack.addWidget(w)

    def _build_place(self):
        w, h = self._row()
        lab = QLabel("ĐẶT ẢNH")
        lab.setStyleSheet("font-weight:700; color:#EF6C00;")
        h.addWidget(lab)
        self.px, self.py, self.pw, self.ph = [QDoubleSpinBox(minimum=-2000, maximum=5000, decimals=1, suffix=" mm")
                                              for _ in range(4)]
        self.pa = QDoubleSpinBox(minimum=-180, maximum=180, decimals=1, suffix=" °", singleStep=1)
        for lbl, sp in (("X", self.px), ("Y", self.py), ("Rộng", self.pw), ("Cao", self.ph), ("Góc", self.pa)):
            h.addWidget(QLabel(lbl))
            sp.setFixedWidth(84)
            sp.setKeyboardTracking(False)
            sp.valueChanged.connect(self.place_from_fields)
            h.addWidget(sp)
        self.pw.setMinimum(1)
        self.ph.setMinimum(1)
        self.pkeep = QCheckBox("Giữ tỉ lệ")
        self.pkeep.setChecked(True)
        self.pkeep.toggled.connect(lambda v: setattr(self.main.current_tab().view.placement, "keep_ratio", v)
                                   if self.main.current_tab() and self.main.current_tab().view.placement else None)
        h.addWidget(self.pkeep)
        h.addWidget(QLabel("Độ mờ"))
        self.pop = QSlider(Qt.Horizontal, minimum=5, maximum=100, value=100)
        self.pop.setFixedWidth(80)
        self.pop.valueChanged.connect(self.place_opacity)
        h.addWidget(self.pop)
        for txt, ang in (("⟲ 90°", -90), ("⟳ 90°", 90)):
            b = QPushButton(txt)
            b.setMinimumWidth(56)
            b.clicked.connect(lambda _=False, a=ang: self._pl() and self._pl().rotate_by(a))
            h.addWidget(b)
        ok = QPushButton("Hoàn tất (Enter)")
        ok.setObjectName("primary")
        ok.clicked.connect(lambda: self.main.current_tab() and self.main.current_tab().view.finish_placement(True))
        no = QPushButton("Huỷ (Esc)")
        no.clicked.connect(lambda: self.main.current_tab() and self.main.current_tab().view.finish_placement(False))
        ok.setMinimumWidth(120)
        no.setMinimumWidth(80)
        h.addWidget(ok)
        h.addWidget(no)
        hint = QLabel("ⓘ")
        hint.setToolTip("Kéo ảnh: di chuyển · kéo góc: co giãn (giữ Shift = giữ tỉ lệ) · kéo nút tròn: xoay "
                        "(Shift = bước 15°)\n← ↑ → ↓: dịch 0,5 pt · Ctrl+mũi tên: 0,1 pt · Shift+mũi tên: 5 pt\n"
                        "[ ]: xoay 1° (Shift 15°) · + −: phóng/thu 1% · Enter: hoàn tất · Esc: huỷ")
        hint.setStyleSheet("color:#EF6C00; font-size:14px;")
        h.addWidget(hint)
        h.addStretch()
        self.stack.addWidget(w)

    # ------------------------------------------------------------ đặt ảnh
    def _pl(self):
        if not hasattr(self.main, "tabs"):
            return None
        t = self.main.current_tab()
        return t.view.placement if t else None

    def on_place_start(self, pl):
        self.stack.setCurrentIndex(1)
        pl.keep_ratio = self.pkeep.isChecked()
        pl.changed.connect(self.place_to_fields)
        self.pop.blockSignals(True)
        self.pop.setValue(int(pl.opacity * 100))
        self.pop.blockSignals(False)
        self.place_to_fields()

    def on_place_end(self, ok):
        self.stack.setCurrentIndex(0)

    def place_to_fields(self):
        pl = self._pl()
        if pl is None:
            return
        self._loading = True
        a = math.radians(pl.angle)
        W = abs(pl.w * math.cos(a)) + abs(pl.h * math.sin(a))
        H = abs(pl.w * math.sin(a)) + abs(pl.h * math.cos(a))
        for sp, v in ((self.px, mm(pl.cx - W / 2)), (self.py, mm(pl.cy - H / 2)), (self.pw, mm(pl.w)),
                      (self.ph, mm(pl.h)), (self.pa, pl.angle)):
            sp.blockSignals(True)
            sp.setValue(v)
            sp.blockSignals(False)
        self._loading = False

    def place_from_fields(self, *_):
        pl = self._pl()
        if pl is None or self._loading:
            return
        sender = self.sender()
        nw, nh = pt(self.pw.value()), pt(self.ph.value())
        if self.pkeep.isChecked():
            if sender is self.pw:
                nh = nw * pl.h / pl.w
            elif sender is self.ph:
                nw = nh * pl.w / pl.h
        pl.w, pl.h = nw, nh
        pl.angle = self.pa.value()
        a = math.radians(pl.angle)
        W = abs(pl.w * math.cos(a)) + abs(pl.h * math.sin(a))
        H = abs(pl.w * math.sin(a)) + abs(pl.h * math.cos(a))
        pl.cx = pt(self.px.value()) + W / 2
        pl.cy = pt(self.py.value()) + H / 2
        pl.update()

    def place_opacity(self, v):
        pl = self._pl()
        if pl:
            pl.opacity = v / 100
            pl.update()

    # ------------------------------------------------------------ ghi chú
    def set_tab(self, tab):
        self.tab = tab
        self.sel = None
        self.load()

    def on_selection(self, tab, sel):
        if tab is not self.main.current_tab():
            return
        self.tab = tab
        if sel != self.sel:
            self._snap = False
        self.sel = sel
        self.load()

    def on_tool(self, tool):
        self.tool = tool
        if not self.sel:
            self.load()

    def annot(self):
        if not self.tab or not self.sel:
            return None, None
        try:
            page = self.tab.pdf.doc[self.sel[0]]
            return page, page.load_annot(self.sel[1])
        except Exception:
            return None, None

    def load(self):
        """Đưa thuộc tính ghi chú đang chọn (hoặc kiểu mặc định) lên thanh."""
        self._loading = True
        page, a = self.annot()
        st = A.style()
        if a is not None:
            t = a.type[0]
            self.target.setText(f"Ghi chú: {a.type[1]}")
            cols = a.colors or {}
            stroke = A.hexcol(cols.get("stroke"))
            fill = A.hexcol(cols.get("fill"))
            border = a.border or {}
            width = border.get("width", 1) if border.get("width", -1) >= 0 else 1
            dashes = border.get("dashes") or None
            clouds = max(border.get("clouds", 0) or 0, 0)
            op = a.opacity if a.opacity >= 0 else 1.0
            ends = a.line_ends or (0, 0)
            is_free = t == fitz.PDF_ANNOT_FREE_TEXT
            is_line = t in (fitz.PDF_ANNOT_LINE, fitz.PDF_ANNOT_POLY_LINE)
            is_stamp = t == fitz.PDF_ANNOT_STAMP
            has_fill = t in (fitz.PDF_ANNOT_SQUARE, fitz.PDF_ANNOT_CIRCLE, fitz.PDF_ANNOT_POLYGON,
                             fitz.PDF_ANNOT_FREE_TEXT, fitz.PDF_ANNOT_LINE, fitz.PDF_ANNOT_POLY_LINE)
            has_dash = t in (fitz.PDF_ANNOT_SQUARE, fitz.PDF_ANNOT_CIRCLE, fitz.PDF_ANNOT_POLYGON,
                             fitz.PDF_ANNOT_LINE, fitz.PDF_ANNOT_POLY_LINE, fitz.PDF_ANNOT_INK, fitz.PDF_ANNOT_FREE_TEXT)
            text_color = A._freetext_color(a) if is_free else None
            fsize = A._freetext_size(a) if is_free else None
            if is_free:                      # hộp chữ: /C là màu NỀN, viền dùng màu chữ
                fill, stroke = stroke, text_color
                fn = A._freetext_font(a)
                if fn and self.font.findData(fn) >= 0:
                    self.font.setCurrentIndex(self.font.findData(fn))
        else:
            tool = self.tool
            self.target.setText("Kiểu mặc định" + (f" – {tool}" if tool not in ("select", "hand", "zoom") else ""))
            stroke = st.get(tool, st["color"]) if tool in ("highlight", "underline", "strike", "squiggly") \
                else st["color"]
            fill, width, op = st.get("fill", ""), st["width"], st["opacity"]
            dashes = A.DASHES.get(st.get("dash"))
            clouds = 0
            ends = (0, A.LINE_ENDS.get(st.get("arrow_end"), 0))
            is_free = is_line = is_stamp = False
            has_fill = has_dash = True
            text_color, fsize = st["text_color"], st["fontsize"]
        self.c_stroke.set_color(stroke)
        self.c_fill.set_color(fill)
        self.width_.setValue(float(width))
        di = 5 if clouds else next((k for k, (_, d) in enumerate(DASH) if d == dashes), 0)
        self.dash.setCurrentIndex(di)
        self.op.setValue(int(round(op * 100)))
        self.op_lbl.setText(f"{int(round(op * 100))}%")
        inv = {v: k for k, v in A.LINE_ENDS.items()}
        self.le_start.setCurrentIndex(max(0, self.le_start.findData(inv.get(ends[0], "None"))))
        self.le_end.setCurrentIndex(max(0, self.le_end.findData(inv.get(ends[1], "None"))))
        if text_color:
            self.c_text.set_color(text_color)
        if fsize:
            self.fsize.setValue(float(fsize))
        sel = a is not None
        self.c_fill.setEnabled(has_fill)
        self.dash.setEnabled(has_dash)
        for x in (self.lbl_ends, self.le_start, self.le_end):
            x.setVisible(is_line or not sel)
        for x in (self.font, self.fsize, self.c_text):
            x.setVisible(is_free or not sel)
        self.c_stroke.setEnabled(not is_stamp and not is_free)
        self.c_stroke.setToolTip("Hộp chữ: viền dùng màu chữ" if is_free else "Màu nét")
        self.width_.setEnabled(not is_stamp)
        self.b_stamp.setVisible(is_stamp)
        self.b_dup.setVisible(is_stamp)
        self.b_copy.setVisible(is_stamp)
        if is_stamp and sel:
            self.main.flash("Ảnh đang chọn: 'Nhân bản sang trang / file…' để đóng lên nhiều trang · Ctrl+C rồi "
                            "Ctrl+V ở trang / file khác · bấm đúp để xoay, co giãn.", 8000)
        self.b_more.setVisible(sel)
        self.b_default.setVisible(sel)
        self._loading = False

    def change(self, key, value):
        if self._loading:
            return
        page, a = self.annot()
        if a is None:
            self._change_default(key, value)
            return
        if not self._snap:
            self.tab.pdf.snapshot()
            self._snap = True
            page, a = self.annot()
        t = a.type[0]
        cols = a.colors or {}
        try:
            if key == "stroke":
                a.set_colors(stroke=A.rgb(value), fill=cols.get("fill"))
            elif key == "fill":
                if t == fitz.PDF_ANNOT_FREE_TEXT:
                    a.update(fill_color=A.rgb(value) if value else None)
                    if not value:
                        a.parent.parent.xref_set_key(a.xref, "C", "null")
                        a.update()
                else:
                    a.set_colors(stroke=cols.get("stroke"), fill=A.rgb(value))
            elif key in ("width", "dash"):
                w = self.width_.value()
                name, d = DASH[self.dash.currentIndex()]
                if d == "cloud" and t in (fitz.PDF_ANNOT_SQUARE, fitz.PDF_ANNOT_CIRCLE, fitz.PDF_ANNOT_POLYGON):
                    a.set_border(width=w, clouds=2)
                else:
                    a.set_border(width=w, dashes=d if isinstance(d, list) else [], clouds=0)
            elif key == "opacity":
                a.set_opacity(value)
            elif key == "ends":
                a.set_line_ends(A.LINE_ENDS[self.le_start.currentData()], A.LINE_ENDS[self.le_end.currentData()])
            elif key in ("text_color", "fontsize", "font") and t == fitz.PDF_ANNOT_FREE_TEXT:
                a.update(fontsize=self.fsize.value(), fontname=self.font.currentData(),
                         text_color=A.rgb(self.c_text.color or "#000000"),
                         fill_color=A.rgb(self.c_fill.color) if self.c_fill.color else None)
            a.update()
        except Exception as e:
            self.main.flash(f"Không áp dụng được: {e}")
            return
        self.tab.pdf.set_modified(True)
        self.tab.view.refresh("annots", [self.sel[0]])
        self.main.doc_changed(self.tab, "annots")

    def _change_default(self, key, value):
        tool = self.tool
        if key == "stroke":
            A.save_style(tool if tool in ("highlight", "underline", "strike", "squiggly") else "color", value)
        elif key == "fill":
            A.save_style("fill", value)
        elif key in ("width", "dash"):
            A.save_style("width", self.width_.value())
            A.save_style("dash", ["solid", "dash", "dash", "dot", "dashdot", "solid"][self.dash.currentIndex()])
        elif key == "opacity":
            A.save_style("opacity", value)
        elif key == "ends":
            A.save_style("arrow_end", self.le_end.currentData())
        elif key == "text_color":
            A.save_style("text_color", value)
        elif key == "fontsize":
            A.save_style("fontsize", value)
        elif key == "font":
            A.save_style("font", value)
        # cập nhật màu / nét cho công cụ đang cầm
        self.main.set_tool(self.tool)

    def save_default(self):
        page, a = self.annot()
        if a is None:
            return
        A.save_style("color", self.c_stroke.color or "#E53935")
        A.save_style("fill", self.c_fill.color)
        A.save_style("width", self.width_.value())
        A.save_style("opacity", self.op.value() / 100)
        if self.fsize.isVisible():
            A.save_style("fontsize", self.fsize.value())
            A.save_style("text_color", self.c_text.color)
        self.main.flash("Đã lưu làm kiểu mặc định cho ghi chú mới.")

    def more(self):
        if self.tab and self.sel:
            self.tab.edit_annot(*self.sel)
            self.load()

    def edit_stamp(self):
        if self.tab and self.sel:
            pno, xref = self.sel
            self.tab.edit_stamp(pno, xref)
