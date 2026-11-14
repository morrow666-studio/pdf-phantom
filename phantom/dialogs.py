"""Các hộp thoại chức năng: gộp, tách, xuất ảnh, đánh số trang, đầu/chân trang,
dấu chìm, bảo mật, nén, in nhiều trang/tờ, PDF -> Word."""
import os

import pymupdf as fitz
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap, QImage, QFont
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGridLayout, QLabel,
                               QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QCheckBox, QRadioButton,
                               QButtonGroup, QPushButton, QDialogButtonBox, QGroupBox, QSlider,
                               QTabWidget, QWidget, QMessageBox, QPlainTextEdit, QFileDialog, QToolButton,
                               QSizePolicy)

from . import ops_pages as op
from .annots import ColorButton
from .util import config, FONT_LABELS, parse_pages, human_size
from .widgets import FileList, ask_save, ask_dir, run_task, done_message
from .viewer import pix_to_qimage


def buttons(dlg, ok_text="Thực hiện", extra=None):
    bb = QDialogButtonBox()
    ok = bb.addButton(ok_text, QDialogButtonBox.AcceptRole)
    ok.setObjectName("primary")
    bb.addButton("Đóng", QDialogButtonBox.RejectRole)
    bb.accepted.connect(dlg.accept)
    bb.rejected.connect(dlg.reject)
    return bb


def font_combo(default="times"):
    c = QComboBox()
    for k, v in FONT_LABELS.items():
        c.addItem(v, k)
    idx = list(FONT_LABELS).index(default) if default in FONT_LABELS else 0
    c.setCurrentIndex(idx)
    return c


# ================================================================== GỘP
class MergeDialog(QDialog):
    def __init__(self, parent=None, initial=None):
        super().__init__(parent)
        self.setWindowTitle("Gộp file PDF và ảnh")
        self.resize(760, 560)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Kéo thả file PDF / ảnh vào danh sách, sắp xếp thứ tự rồi bấm Gộp:"))
        self.files = FileList("PDF và ảnh (*.pdf *.png *.jpg *.jpeg *.bmp *.tif *.tiff *.gif *.webp)")
        if initial:
            self.files.add(initial)
        lay.addWidget(self.files, 1)

        g = QGroupBox("Chữ ký số trong file gộp")
        gl = QVBoxLayout(g)
        self.m_normal = QRadioButton("Gộp thường – giữ HÌNH chữ ký/con dấu (chữ ký số mất hiệu lực xác thực)")
        self.m_attach = QRadioButton("Gộp + ĐÍNH KÈM bản gốc vào file – chữ ký số của từng file vẫn hợp lệ 100% "
                                     "(mở bằng Adobe/Foxit: biểu tượng kẹp giấy)")
        self.m_append = QRadioButton("Nối trang vào sau file ĐÃ KÝ đầu tiên (cập nhật gia tăng) – chữ ký của "
                                     "file đầu vẫn kiểm tra được cho phần đã ký")
        self.m_attach.setChecked(True)
        for w in (self.m_normal, self.m_attach, self.m_append):
            gl.addWidget(w)
        lay.addWidget(g)

        g2 = QGroupBox("Tuỳ chọn")
        f = QGridLayout(g2)
        self.img_fit = QComboBox()
        self.img_fit.addItems(["Ảnh: giữ khổ theo ảnh", "Ảnh: đặt vừa khổ A4", "Ảnh: đặt vừa khổ A3"])
        self.img_fit.setCurrentIndex(1)
        self.margin = QSpinBox(minimum=0, maximum=50, value=5, suffix=" mm")
        self.bookmarks = QCheckBox("Tạo dấu trang (bookmark) theo tên file")
        self.bookmarks.setChecked(True)
        f.addWidget(self.img_fit, 0, 0)
        f.addWidget(QLabel("Lề ảnh:"), 0, 1)
        f.addWidget(self.margin, 0, 2)
        f.addWidget(self.bookmarks, 1, 0, 1, 3)
        lay.addWidget(g2)
        lay.addWidget(buttons(self, "Gộp file"))

    def run(self):
        files = self.files.paths()
        if len(files) < 1:
            QMessageBox.warning(self, "Gộp file", "Hãy thêm ít nhất 1 file.")
            return None
        out = ask_save(self, "Lưu file gộp", "File_gop.pdf")
        if not out:
            return None
        fit = ["image", "paper", "paper"][self.img_fit.currentIndex()]
        paper = "A3" if self.img_fit.currentIndex() == 2 else "A4"
        if self.m_append.isChecked():
            first = files[0]
            if not first.lower().endswith(".pdf"):
                QMessageBox.warning(self, "Gộp", "File đầu tiên phải là PDF đã ký.")
                return None
            ok, res = run_task(self, "Đang gộp…", lambda progress=None: op.append_signed(first, files[1:], out))
        else:
            ok, res = run_task(self, "Đang gộp…", op.merge_files, files, out, image_fit=fit,
                               margin_mm=self.margin.value(), paper=paper, bookmarks=self.bookmarks.isChecked(),
                               keep_sig_look=True, attach_originals=self.m_attach.isChecked())
        if ok and res:
            done_message(self, f"Đã gộp {len(files)} file.\n{out}", out)
        return out if ok else None


# ================================================================== TÁCH
class SplitDialog(QDialog):
    """Tách PDF – có chế độ TỰ CHỌN TRANG (mỗi dòng 1 file, đặt tên được) và XEM TRƯỚC kết quả."""
    MODES = [("free", "Tự chọn trang – mỗi dòng là 1 file"),
             ("ranges", "Theo dải – mỗi dải là 1 file"),
             ("cuts", "Cắt tại các trang"),
             ("every", "Mỗi file gồm N trang"),
             ("single", "Mỗi trang thành 1 file"),
             ("oddeven", "Trang lẻ / trang chẵn (2 file)"),
             ("bookmarks", "Theo dấu trang (bookmark) cấp 1"),
             ("size", "Theo dung lượng tối đa")]

    def __init__(self, parent=None, path=None, page_count=0, tab=None, selected=None):
        super().__init__(parent)
        self.setWindowTitle("Tách file PDF")
        self.setMinimumSize(720, 560)
        self.path, self.tab = path, tab
        self._src = None
        lay = QVBoxLayout(self)
        row = QHBoxLayout()
        self.src = QLineEdit(path or "")
        self.src.setReadOnly(bool(tab))
        b = QPushButton("Chọn file khác…")
        b.clicked.connect(self.pick)
        row.addWidget(QLabel("File nguồn:"))
        row.addWidget(self.src, 1)
        row.addWidget(b)
        lay.addLayout(row)
        self.use_open = QCheckBox("Dùng bản đang mở (gồm cả thay đổi chưa lưu)")
        self.use_open.setChecked(bool(tab))
        self.use_open.setVisible(bool(tab))
        self.use_open.toggled.connect(self.refresh)
        self.info = QLabel("")
        r2 = QHBoxLayout()
        r2.addWidget(self.use_open)
        r2.addStretch()
        r2.addWidget(self.info)
        lay.addLayout(r2)

        body = QHBoxLayout()
        left = QVBoxLayout()
        left.addWidget(QLabel("<b>Cách tách</b>"))
        self.mode = QComboBox()
        for k, t in self.MODES:
            self.mode.addItem(t, k)
        left.addWidget(self.mode)
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color:#555;")
        left.addWidget(self.hint)
        self.free = QPlainTextEdit()
        self.free.setPlaceholderText("Hồ sơ nghiệm thu: 1-5, 8\nBản vẽ: 10-14\n20, 3, 4")
        f = self.free.font()
        f.setPointSize(f.pointSize() + 1)
        self.free.setFont(f)
        left.addWidget(self.free, 1)
        fb = QHBoxLayout()
        self.b_sel = QPushButton("+ Thêm trang đang chọn")
        self.b_sel.setToolTip("Chọn trang ở bảng Trang bên trái (Ctrl/Shift + bấm) rồi bấm nút này -> thêm 1 dòng")
        self.b_sel.clicked.connect(self.add_selected)
        self.b_cur = QPushButton("+ Trang đang xem")
        self.b_cur.clicked.connect(lambda: self._add_line([self.tab.view.current_page]) if self.tab else None)
        fb.addWidget(self.b_sel)
        fb.addWidget(self.b_cur)
        fb.addStretch()
        self.free_btns = QWidget()
        self.free_btns.setLayout(fb)
        fb.setContentsMargins(0, 0, 0, 0)
        left.addWidget(self.free_btns)
        self.value = QLineEdit()
        left.addWidget(self.value)
        self.every = QSpinBox(minimum=1, maximum=9999, value=1, suffix=" trang / file")
        left.addWidget(self.every)
        self.size = QDoubleSpinBox(minimum=0.2, maximum=500, value=10, suffix=" MB / file")
        left.addWidget(self.size)
        self.rest = QCheckBox("Gom các trang CHƯA chọn thành 1 file 'Con lai'")
        left.addWidget(self.rest)
        body.addLayout(left, 3)

        right = QVBoxLayout()
        right.addWidget(QLabel("<b>Xem trước kết quả</b>"))
        from PySide6.QtWidgets import QListWidget
        self.preview = QListWidget()
        right.addWidget(self.preview, 1)
        self.summary = QLabel()
        right.addWidget(self.summary)
        body.addLayout(right, 2)
        lay.addLayout(body, 1)

        fl = QFormLayout()
        dr = QHBoxLayout()
        src_dir = os.path.dirname(path) if path else ""
        self.out_dir = QLineEdit(config().get("split_dir") or src_dir or config().get("last_dir", ""))
        self.out_dir.setPlaceholderText("Chọn thư mục lưu các file sau khi tách")
        bo = QPushButton("Chọn…")
        bo.clicked.connect(self.pick_out)
        bs = QPushButton("Cùng thư mục file gốc")
        bs.setEnabled(bool(src_dir))
        bs.clicked.connect(lambda: self.out_dir.setText(src_dir))
        dr.addWidget(self.out_dir, 1)
        dr.addWidget(bo)
        dr.addWidget(bs)
        fl.addRow("<b>Lưu vào:</b>", dr)
        self.tpl = QLineEdit(config().get("split_tpl", "{name}_{i}"))
        fl.addRow("Đặt tên file:", self.tpl)
        note = QLabel("<i>{name} tên gốc · {i} số thứ tự · {start}-{end} trang đầu/cuối · "
                      "dòng có tên ('Hồ sơ A: …') thì file mang tên đó</i>")
        note.setWordWrap(True)
        fl.addRow("", note)
        lay.addLayout(fl)
        self.bb = buttons(self, "Tách file")
        lay.addWidget(self.bb)

        self._timer = QTimer(self, singleShot=True, interval=250, timeout=self.refresh)
        for w in (self.free.textChanged, self.value.textChanged, self.every.valueChanged, self.size.valueChanged,
                  self.rest.toggled, self.tpl.textChanged):
            w.connect(lambda *_: self._timer.start())
        self.mode.currentIndexChanged.connect(self.mode_changed)
        last = config().get("split_mode", "free")
        if selected and len(selected) > 0 and tab:
            last = "free"
            self._add_line(selected)
        self.mode.setCurrentIndex(max(0, self.mode.findData(last)))
        self.mode_changed()

    # ---------------------------------------------------------------- nguồn
    def source(self):
        """-> fitz.Document để xem trước (bản đang mở hoặc file trên đĩa)."""
        if self.tab and self.use_open.isChecked():
            return self.tab.pdf.doc
        p = self.src.text()
        if self._src is None or self._src[0] != p:
            try:
                self._src = (p, fitz.open(p))
            except Exception:
                self._src = (p, None)
        return self._src[1]

    def pick(self):
        p, _ = QFileDialog.getOpenFileName(self, "Chọn PDF", config().get("last_dir", ""), "PDF (*.pdf)")
        if p:
            self.src.setText(p)
            self.use_open.setChecked(False)
            self.use_open.setVisible(False)
            self.b_sel.setEnabled(False)
            self.b_cur.setEnabled(False)
            self.refresh()

    def _add_line(self, pages):
        from .ops_pages import describe_pages
        if not pages:
            return
        txt = self.free.toPlainText().rstrip()
        self.free.setPlainText((txt + "\n" if txt else "") + describe_pages(sorted(pages)))
        self.mode.setCurrentIndex(self.mode.findData("free"))

    def add_selected(self):
        if not self.tab:
            return
        main = self.parent()
        try:
            pages = main._sel_pages()
        except Exception:
            pages = []
        if not pages:
            QMessageBox.information(self, "Tách", "Chọn trang ở bảng Trang bên trái trước (Ctrl hoặc Shift + bấm).")
            return
        self._add_line(pages)

    # ---------------------------------------------------------------- giao diện
    HINTS = {
        "free": "Mỗi dòng là 1 file. Ghi số trang bất kỳ, cách nhau dấu phẩy, dải dùng gạch ngang. "
                "Muốn đặt tên file: ghi tên rồi dấu hai chấm.\nThứ tự trang giữ đúng như gõ "
                "(gõ '5, 1-2' → file có trang 5, 1, 2). Dòng bắt đầu bằng # là ghi chú.",
        "ranges": "Mỗi dải là 1 file, vd: 1-3, 4-10, 11-   (11- = từ trang 11 đến hết)",
        "cuts": "Ghi các trang BẮT ĐẦU file mới, vd: 5, 12  →  1-4 | 5-11 | 12-hết",
        "every": "Chia đều mỗi file N trang (trang cuối có thể ít hơn).",
        "single": "Mỗi trang thành 1 file riêng.",
        "oddeven": "2 file: các trang lẻ (1, 3, 5…) và các trang chẵn (2, 4, 6…) – tiện in 2 mặt thủ công.",
        "bookmarks": "Mỗi dấu trang cấp 1 thành 1 file, tên file theo tên dấu trang.",
        "size": "Gom trang sao cho mỗi file không vượt dung lượng (gửi email, tải lên cổng hồ sơ).",
    }

    def mode_changed(self, *_):
        m = self.mode.currentData()
        self.hint.setText(self.HINTS.get(m, ""))
        self.free.setVisible(m == "free")
        self.free_btns.setVisible(m == "free")
        self.value.setVisible(m in ("ranges", "cuts"))
        self.value.setPlaceholderText({"ranges": "vd: 1-3, 4-10, 11-", "cuts": "vd: 5, 12, 20"}.get(m, ""))
        self.every.setVisible(m == "every")
        self.size.setVisible(m == "size")
        self.rest.setVisible(m in ("free", "ranges"))
        self.refresh()

    def _value(self):
        m = self.mode.currentData()
        return {"free": self.free.toPlainText(), "ranges": self.value.text(), "cuts": self.value.text(),
                "every": self.every.value(), "size": self.size.value()}.get(m, "")

    def refresh(self):
        from PySide6.QtGui import QColor
        from .ops_pages import describe_pages
        self.preview.clear()
        ok_btn = self.bb.buttons()[0]
        src = self.source()
        if src is None:
            self.info.setText("")
            self.summary.setText("Chưa chọn file nguồn.")
            ok_btn.setEnabled(False)
            return
        n = src.page_count
        self.info.setText(f"Tổng số trang: <b>{n}</b>")
        m = self.mode.currentData()
        if m == "size":
            self.preview.addItem("(Số file tính khi tách – theo dung lượng thực tế)")
            self.summary.setText("")
            ok_btn.setEnabled(True)
            self.groups = None
            return
        try:
            if m in ("free", "ranges", "cuts") and not str(self._value()).strip():
                raise ValueError("Chưa nhập số trang.")
            groups = op.plan_split(src, m, self._value(), self.rest.isChecked())
        except Exception as e:
            self.preview.addItem("⚠ " + str(e))
            self.preview.item(0).setForeground(QColor("#C62828"))
            self.summary.setText("")
            ok_btn.setEnabled(False)
            self.groups = None
            return
        name = os.path.splitext(self.tab.pdf.name if (self.tab and self.use_open.isChecked())
                                else os.path.basename(self.src.text()))[0]
        tpl = self.tpl.text() or "{name}_{i}"
        seen = {}
        self.names = []
        for i, (title, g) in enumerate(groups, 1):
            try:
                fname = tpl.format(name=name, i=f"{i:02d}", start=g[0] + 1, end=g[-1] + 1, title=title)
            except Exception:
                fname = f"{name}_{i:02d}"
            if title and "{title}" not in tpl:
                fname = f"{name}_{title}"
            seen[fname] = seen.get(fname, 0) + 1
            if seen[fname] > 1:
                fname += f"_{seen[fname]}"
            self.names.append(fname + ".pdf")
            self.preview.addItem(f"{i}. {fname}.pdf   –  trang {describe_pages(g)}  ({len(g)} tr)")
        used = {p for _, g in groups for p in g}
        dup = sum(len(g) for _, g in groups) - len(used)
        txt = f"<b>{len(groups)}</b> file · dùng {len(used)}/{n} trang"
        if dup > 0:
            txt += f" · <span style='color:#EF6C00'>{dup} trang lặp ở nhiều file</span>"
        if len(used) < n and m in ("free", "ranges") and not self.rest.isChecked():
            txt += f" · <span style='color:#777'>{n - len(used)} trang không tách</span>"
        self.summary.setText(txt)
        ok_btn.setEnabled(bool(groups))
        self.groups = groups

    def pick_out(self):
        d = QFileDialog.getExistingDirectory(self, "Chọn thư mục lưu các file tách", self.out_dir.text())
        if d:
            self.out_dir.setText(os.path.normpath(d))

    def accept(self):
        """Bấm 'Tách file': HỎI THƯ MỤC LƯU TRƯỚC (hộp chọn thư mục hiện ngay trên cửa sổ tách),
        huỷ thì giữ nguyên cửa sổ để chỉnh tiếp."""
        if not self.bb.buttons()[0].isEnabled():
            return
        if not (self.tab and self.use_open.isChecked()) and not os.path.isfile(self.src.text()):
            QMessageBox.warning(self, "Tách", "Chưa chọn file nguồn.")
            return
        start = self.out_dir.text() if os.path.isdir(self.out_dir.text()) else config().get("last_dir", "")
        out = QFileDialog.getExistingDirectory(self, "Lưu các file tách vào thư mục nào?", start)
        if not out:
            return
        out = os.path.normpath(out)
        self.out_dir.setText(out)
        exist = [n for n in getattr(self, "names", []) if os.path.exists(os.path.join(out, n))]
        if exist:
            r = QMessageBox.question(self, "Tách file",
                                     f"Thư mục đã có {len(exist)} file trùng tên:\n  " + "\n  ".join(exist[:6]) +
                                     ("\n  …" if len(exist) > 6 else "") + "\n\nGhi đè các file này?")
            if r != QMessageBox.Yes:
                return
        main = self.parent() or self
        self.hide()
        self.run(out, parent=main)
        super().accept()

    def run(self, out=None, parent=None):
        parent = parent or self
        m = self.mode.currentData()
        cfg = config()
        cfg["split_mode"] = m
        cfg["split_tpl"] = self.tpl.text()
        if out is None:
            out = ask_dir(parent, "Chọn thư mục lưu các file tách")
            if not out:
                return
        cfg["split_dir"] = out
        cfg["last_dir"] = out
        cfg.save()
        kw = dict(rest=self.rest.isChecked())
        if self.tab and self.use_open.isChecked():
            kw.update(data=self.tab.pdf.doc.tobytes(), name=os.path.splitext(self.tab.pdf.name)[0])
            path = None
        else:
            path = self.src.text()
            if not os.path.isfile(path):
                QMessageBox.warning(parent, "Tách", "Chưa chọn file nguồn.")
                return
        ok, res = run_task(parent, "Đang tách…", op.split_pdf, path, out, m, self._value(), self.tpl.text(), **kw)
        if ok and res:
            done_message(parent, f"Đã tách thành {len(res)} file, lưu tại:\n{out}", folder=out)
        return res if ok else None


# ============================================================== PDF -> ẢNH
class ToImageDialog(QDialog):
    def __init__(self, parent=None, doc=None, current=0):
        super().__init__(parent)
        self.doc = doc
        self.setWindowTitle("Xuất PDF thành ảnh")
        self.setMinimumWidth(480)
        f = QFormLayout(self)
        self.rng = QLineEdit(placeholderText="Để trống = tất cả; vd 1-3,5")
        cur = QPushButton("Trang hiện tại")
        cur.clicked.connect(lambda: self.rng.setText(str(current + 1)))
        r = QHBoxLayout()
        r.addWidget(self.rng)
        r.addWidget(cur)
        f.addRow("Trang:", r)
        self.fmt = QComboBox()
        self.fmt.addItems(["png", "jpg", "tif", "bmp", "webp"])
        f.addRow("Định dạng:", self.fmt)
        self.dpi = QComboBox(editable=True)
        self.dpi.addItems(["72", "96", "150", "200", "300", "400", "600"])
        self.dpi.setCurrentText("200")
        f.addRow("Độ phân giải (DPI):", self.dpi)
        self.q = QSlider(Qt.Horizontal, minimum=30, maximum=100, value=90)
        self.ql = QLabel("90")
        self.q.valueChanged.connect(lambda v: self.ql.setText(str(v)))
        r2 = QHBoxLayout()
        r2.addWidget(self.q)
        r2.addWidget(self.ql)
        f.addRow("Chất lượng JPG/WebP:", r2)
        self.gray = QCheckBox("Ảnh thang xám (nhẹ hơn)")
        self.alpha = QCheckBox("Nền trong suốt (PNG)")
        f.addRow(self.gray)
        f.addRow(self.alpha)
        self.est = QLabel()
        f.addRow("Kích thước ảnh:", self.est)
        self.dpi.currentTextChanged.connect(self.estimate)
        self.estimate()
        f.addRow(buttons(self, "Xuất ảnh"))

    def estimate(self):
        try:
            d = int(self.dpi.currentText())
            r = self.doc[0].rect
            self.est.setText(f"~ {int(r.width * d / 72)} × {int(r.height * d / 72)} px (trang 1)")
        except Exception:
            self.est.setText("")

    def run(self):
        try:
            pages = parse_pages(self.rng.text(), self.doc.page_count)
            dpi = int(self.dpi.currentText())
        except Exception as e:
            QMessageBox.warning(self, "Xuất ảnh", str(e))
            return
        out = ask_dir(self, "Chọn thư mục lưu ảnh")
        if not out:
            return
        data = self.doc.tobytes()
        name = self.doc.name

        def job(progress=None):
            d = fitz.open("pdf", data)
            d.name if False else None
            res = op.pdf_to_images(d, out, pages, dpi, self.fmt.currentText(), self.q.value(),
                                   self.gray.isChecked(), self.alpha.isChecked(),
                                   name_tpl=os.path.splitext(os.path.basename(name or "tai_lieu"))[0] + "_trang_{p}",
                                   progress=progress)
            return res
        ok, res = run_task(self, "Đang xuất ảnh…", job)
        if ok and res:
            done_message(self, f"Đã xuất {len(res)} ảnh.", folder=out)


# ============================================================ ĐÁNH SỐ TRANG
class PageNumberDialog(QDialog):
    PRESETS = ["{n}", "Trang {n}", "Trang {n}/{total}", "Trang {n} / {total}", "- {n} -", "{n}/{total}",
               "Page {n} of {total}", "Tờ {n}", "[{n}]"]
    STYLES = [("1, 2, 3", "1"), ("01, 02, 03", "01"), ("001, 002", "001"), ("i, ii, iii", "i"),
              ("I, II, III", "I"), ("a, b, c", "a"), ("A, B, C", "A")]
    POS = [("top-left", "↖ Trên trái"), ("top-center", "↑ Trên giữa"), ("top-right", "↗ Trên phải"),
           ("bottom-left", "↙ Dưới trái"), ("bottom-center", "↓ Dưới giữa"), ("bottom-right", "↘ Dưới phải")]

    def __init__(self, parent=None, doc=None, current=0):
        super().__init__(parent)
        self.doc = doc
        self.current = current
        self.setWindowTitle("Đánh số trang")
        self.resize(900, 640)
        c = dict(op.PN_DEFAULTS)
        c.update(config().get("page_number", {}))
        main = QHBoxLayout(self)
        left = QVBoxLayout()
        main.addLayout(left, 0)

        g1 = QGroupBox("Định dạng số")
        f1 = QFormLayout(g1)
        self.tpl = QComboBox(editable=True)
        self.tpl.addItems(self.PRESETS)
        self.tpl.setCurrentText(c["template"])
        f1.addRow("Mẫu:", self.tpl)
        f1.addRow("", QLabel("<i>{n} số trang · {total} tổng số · {date} ngày hôm nay</i>"))
        self.style = QComboBox()
        for lbl, v in self.STYLES:
            self.style.addItem(lbl, v)
        self.style.setCurrentIndex([v for _, v in self.STYLES].index(c["style"]) if c["style"] in
                                   [v for _, v in self.STYLES] else 0)
        f1.addRow("Kiểu số:", self.style)
        self.start = QSpinBox(minimum=0, maximum=99999, value=int(c["start"]))
        f1.addRow("Bắt đầu từ số:", self.start)
        self.total_mode = QComboBox()
        self.total_mode.addItems(["Tổng = số trang được đánh", "Tổng = toàn bộ trang của file"])
        self.total_mode.setCurrentIndex(0 if c["total_mode"] == "applied" else 1)
        f1.addRow("Cách tính {total}:", self.total_mode)
        left.addWidget(g1)

        g2 = QGroupBox("Vị trí")
        gl = QGridLayout(g2)
        self.pos_grp = QButtonGroup(self)
        for i, (k, lbl) in enumerate(self.POS):
            b = QToolButton(text=lbl, checkable=True)
            b.setMinimumWidth(110)
            b.setProperty("key", k)
            self.pos_grp.addButton(b, i)
            gl.addWidget(b, i // 3, i % 3)
            if k == c["position"]:
                b.setChecked(True)
        self.mx = QDoubleSpinBox(minimum=0, maximum=100, value=float(c["margin_x"]), suffix=" mm")
        self.my = QDoubleSpinBox(minimum=0, maximum=100, value=float(c["margin_y"]), suffix=" mm")
        gl.addWidget(QLabel("Cách mép ngang:"), 2, 0)
        gl.addWidget(self.mx, 2, 1)
        gl.addWidget(QLabel("Cách mép dọc:"), 3, 0)
        gl.addWidget(self.my, 3, 1)
        self.mirror = QCheckBox("Đối xứng trang chẵn/lẻ (in 2 mặt: số luôn ở mép ngoài)")
        self.mirror.setChecked(bool(c["mirror"]))
        gl.addWidget(self.mirror, 4, 0, 1, 3)
        left.addWidget(g2)

        g3 = QGroupBox("Phạm vi")
        f3 = QFormLayout(g3)
        self.rng = QLineEdit(c.get("range", ""), placeholderText="Để trống = tất cả; vd 3-20")
        f3.addRow("Áp dụng cho trang:", self.rng)
        self.skip_first = QCheckBox("Không đánh số trang đầu tiên (trang bìa)")
        self.skip_first.setChecked(bool(c["skip_first"]))
        self.count_skipped = QCheckBox("…nhưng vẫn tính trang bìa vào số thứ tự")
        self.count_skipped.setChecked(bool(c["count_skipped"]))
        f3.addRow(self.skip_first)
        f3.addRow(self.count_skipped)
        left.addWidget(g3)

        g4 = QGroupBox("Phông chữ")
        f4 = QGridLayout(g4)
        self.font = font_combo(c["font"])
        self.size = QDoubleSpinBox(minimum=5, maximum=72, value=float(c["size"]))
        self.bold = QCheckBox("Đậm")
        self.bold.setChecked(bool(c["bold"]))
        self.italic = QCheckBox("Nghiêng")
        self.italic.setChecked(bool(c["italic"]))
        self.color = ColorButton(c["color"])
        self.box = QCheckBox("Khung viền")
        self.box.setChecked(bool(c["box"]))
        f4.addWidget(self.font, 0, 0, 1, 2)
        f4.addWidget(self.size, 0, 2)
        f4.addWidget(self.bold, 1, 0)
        f4.addWidget(self.italic, 1, 1)
        f4.addWidget(self.color, 1, 2)
        f4.addWidget(self.box, 2, 0)
        left.addWidget(g4)
        left.addStretch()

        right = QVBoxLayout()
        main.addLayout(right, 1)
        right.addWidget(QLabel("<b>Xem trước</b>"))
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumSize(360, 460)
        self.preview.setStyleSheet("background:#8A8F99; border-radius:6px;")
        right.addWidget(self.preview, 1)
        nav = QHBoxLayout()
        self.pv_page = QSpinBox(minimum=1, maximum=doc.page_count, value=current + 1, prefix="Trang ")
        nav.addWidget(self.pv_page)
        nav.addStretch()
        right.addLayout(nav)
        self.save_def = QCheckBox("Lưu thiết lập này làm mặc định")
        self.save_def.setChecked(True)
        right.addWidget(self.save_def)
        right.addWidget(buttons(self, "Đánh số trang"))

        self.timer = QTimer(self, singleShot=True, interval=150, timeout=self.update_preview)
        for w in (self.tpl, self.style, self.total_mode, self.font):
            (w.currentTextChanged if hasattr(w, "currentTextChanged") else w.currentIndexChanged).connect(
                lambda *_: self.timer.start())
        for w in (self.start, self.mx, self.my, self.size, self.pv_page):
            w.valueChanged.connect(lambda *_: self.timer.start())
        for w in (self.mirror, self.skip_first, self.count_skipped, self.bold, self.italic, self.box):
            w.toggled.connect(lambda *_: self.timer.start())
        self.rng.textChanged.connect(lambda *_: self.timer.start())
        self.pos_grp.idClicked.connect(lambda *_: self.timer.start())
        self.color.clicked.connect(lambda *_: QTimer.singleShot(50, self.timer.start))
        self.update_preview()

    def config(self):
        b = self.pos_grp.checkedButton()
        return {
            "template": self.tpl.currentText(), "style": self.style.currentData(),
            "position": b.property("key") if b else "bottom-center", "start": self.start.value(),
            "range": self.rng.text(), "skip_first": self.skip_first.isChecked(),
            "count_skipped": self.count_skipped.isChecked(), "mirror": self.mirror.isChecked(),
            "font": self.font.currentData(), "size": self.size.value(), "bold": self.bold.isChecked(),
            "italic": self.italic.isChecked(), "color": self.color.color, "margin_x": self.mx.value(),
            "margin_y": self.my.value(), "total_mode": "applied" if self.total_mode.currentIndex() == 0 else "doc",
            "box": self.box.isChecked(),
        }

    def update_preview(self):
        try:
            p = self.pv_page.value() - 1
            tmp = fitz.open()
            tmp.insert_pdf(self.doc, from_page=0, to_page=self.doc.page_count - 1) \
                if self.doc.page_count <= 60 else None
            if tmp.page_count == 0:
                # tài liệu lớn: chỉ chép trang cần xem, nhưng giữ đúng chỉ số bằng trang trắng
                for i in range(self.doc.page_count):
                    if i == p:
                        tmp.insert_pdf(self.doc, from_page=i, to_page=i)
                    else:
                        r = self.doc[i].rect
                        tmp.new_page(width=r.width, height=r.height)
            op.add_page_numbers(tmp, self.config())
            page = tmp[p]
            zoom = min(self.preview.width() / page.rect.width, self.preview.height() / page.rect.height) * 0.95
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
            self.preview.setPixmap(QPixmap.fromImage(pix_to_qimage(pix)))
            tmp.close()
        except Exception as e:
            self.preview.setText(f"Lỗi xem trước:\n{e}")

    def apply(self, pdfdoc):
        c = self.config()
        if self.save_def.isChecked():
            config()["page_number"] = c
            config().save()
        pdfdoc.snapshot()
        n = op.add_page_numbers(pdfdoc.doc, c)
        pdfdoc.commit("content")
        return n


# ======================================================= ĐẦU TRANG / CHÂN TRANG
class HeaderFooterDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Đầu trang / Chân trang")
        self.setMinimumWidth(620)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("<i>Có thể dùng: {n} số trang · {total} tổng · {date} ngày · {file} tên file</i>"))
        g = QGridLayout()
        self.fields = {}
        for r, v in enumerate(("top", "bottom")):
            g.addWidget(QLabel("<b>Đầu trang</b>" if v == "top" else "<b>Chân trang</b>"), r * 2, 0, 1, 3)
            for c, h in enumerate(("left", "center", "right")):
                e = QLineEdit(placeholderText={"left": "Trái", "center": "Giữa", "right": "Phải"}[h])
                self.fields[f"{v}-{h}"] = e
                g.addWidget(e, r * 2 + 1, c)
        lay.addLayout(g)
        f = QFormLayout()
        self.font = font_combo("times")
        self.size = QDoubleSpinBox(minimum=5, maximum=48, value=10)
        self.color = ColorButton("#000000")
        self.margin = QDoubleSpinBox(minimum=0, maximum=60, value=10, suffix=" mm")
        self.rng = QLineEdit(placeholderText="Để trống = tất cả")
        self.line = QCheckBox("Kẻ đường phân cách")
        for lbl, w in (("Phông:", self.font), ("Cỡ chữ:", self.size), ("Màu:", self.color),
                       ("Cách mép:", self.margin), ("Trang:", self.rng)):
            f.addRow(lbl, w)
        f.addRow(self.line)
        lay.addLayout(f)
        lay.addWidget(buttons(self, "Áp dụng"))

    def apply(self, pdfdoc):
        items = {k: e.text() for k, e in self.fields.items() if e.text().strip()}
        if not items:
            return 0
        pdfdoc.snapshot()
        n = op.add_header_footer(pdfdoc.doc, items, self.font.currentData(), self.size.value(),
                                 self.color.color, self.margin.value(), self.rng.text(), self.line.isChecked())
        pdfdoc.commit("content")
        return n


class WatermarkDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Dấu chìm (Watermark)")
        f = QFormLayout(self)
        self.text = QLineEdit("BẢN NHÁP")
        self.font = font_combo("arial")
        self.size = QSpinBox(minimum=8, maximum=300, value=72)
        self.color = ColorButton("#C00000")
        self.op = QSpinBox(minimum=3, maximum=100, value=15, suffix=" %")
        self.angle = QSpinBox(minimum=-90, maximum=90, value=45, suffix="°")
        self.rng = QLineEdit(placeholderText="Để trống = tất cả")
        for lbl, w in (("Nội dung:", self.text), ("Phông:", self.font), ("Cỡ chữ:", self.size), ("Màu:", self.color),
                       ("Độ đậm:", self.op), ("Góc xoay:", self.angle), ("Trang:", self.rng)):
            f.addRow(lbl, w)
        f.addRow(buttons(self, "Đóng dấu chìm"))

    def apply(self, pdfdoc):
        pdfdoc.snapshot()
        n = op.add_watermark(pdfdoc.doc, self.text.text(), self.size.value(), self.color.color,
                             self.op.value() / 100, self.angle.value(), self.rng.text(), self.font.currentData())
        pdfdoc.commit("content")
        return n


# ================================================================ BẢO MẬT
class SecurityDialog(QDialog):
    PERMS = [("print", "In"), ("print_hq", "In chất lượng cao"), ("copy", "Sao chép nội dung"),
             ("modify", "Chỉnh sửa nội dung"), ("annotate", "Thêm ghi chú"), ("form", "Điền biểu mẫu"),
             ("assemble", "Chèn/xoá/xoay trang"), ("accessibility", "Trình đọc màn hình")]

    def __init__(self, parent=None, pdfdoc=None):
        super().__init__(parent)
        self.pdf = pdfdoc
        self.setWindowTitle("Bảo mật tài liệu")
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        tabs = QTabWidget()
        lay.addWidget(tabs)
        # --- đặt mật khẩu
        w = QWidget()
        f = QFormLayout(w)
        self.upw = QLineEdit(echoMode=QLineEdit.Password, placeholderText="Mật khẩu để MỞ file (có thể để trống)")
        self.upw2 = QLineEdit(echoMode=QLineEdit.Password, placeholderText="Nhập lại")
        self.opw = QLineEdit(echoMode=QLineEdit.Password, placeholderText="Mật khẩu CHỦ SỞ HỮU (để đổi quyền)")
        show = QCheckBox("Hiện mật khẩu")
        show.toggled.connect(lambda v: [e.setEchoMode(QLineEdit.Normal if v else QLineEdit.Password)
                                        for e in (self.upw, self.upw2, self.opw)])
        f.addRow("Mật khẩu mở file:", self.upw)
        f.addRow("Nhập lại:", self.upw2)
        f.addRow("Mật khẩu quyền:", self.opw)
        f.addRow(show)
        g = QGroupBox("Cho phép người xem:")
        gl = QGridLayout(g)
        self.perm_cb = {}
        for i, (k, lbl) in enumerate(self.PERMS):
            cb = QCheckBox(lbl)
            cb.setChecked(k in ("print", "print_hq", "accessibility"))
            self.perm_cb[k] = cb
            gl.addWidget(cb, i // 2, i % 2)
        f.addRow(g)
        self.method = QComboBox()
        self.method.addItems(["AES 256-bit (khuyên dùng)", "AES 128-bit", "RC4 128-bit (tương thích cũ)"])
        f.addRow("Mã hoá:", self.method)
        self.strip = QCheckBox("Xoá thông tin ẩn (tác giả, phần mềm tạo, metadata)")
        f.addRow(self.strip)
        b = QPushButton("Lưu bản có mật khẩu…")
        b.setObjectName("primary")
        b.clicked.connect(self.encrypt)
        f.addRow(b)
        tabs.addTab(w, "Đặt mật khẩu / quyền")
        # --- gỡ
        w2 = QWidget()
        v2 = QVBoxLayout(w2)
        st = "File đang mở CÓ mã hoá." if (pdfdoc and pdfdoc.doc.is_encrypted) else "File đang mở không có mật khẩu."
        v2.addWidget(QLabel(st + "\nLưu bản không mật khẩu (cần đã mở được file bằng mật khẩu đúng):"))
        b2 = QPushButton("Lưu bản đã gỡ mật khẩu…")
        b2.clicked.connect(self.decrypt)
        v2.addWidget(b2)
        v2.addStretch()
        tabs.addTab(w2, "Gỡ mật khẩu")
        # --- che thông tin
        w3 = QWidget()
        f3 = QFormLayout(w3)
        self.needle = QLineEdit(placeholderText="vd: số CCCD, số tài khoản, đơn giá…")
        f3.addRow("Tìm và che vĩnh viễn:", self.needle)
        f3.addRow(QLabel("<i>Chữ bị che sẽ bị XOÁ HẲN khỏi file (không khôi phục, không copy được).\n"
                         "Có thể che vùng bất kỳ bằng công cụ 'Che thông tin' ở tab Ghi chú.</i>"))
        b3 = QPushButton("Che tất cả")
        b3.clicked.connect(self.redact)
        f3.addRow(b3)
        tabs.addTab(w3, "Che thông tin nhạy cảm")
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.button(QDialogButtonBox.Close).setText("Đóng")
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def encrypt(self):
        if self.upw.text() != self.upw2.text():
            QMessageBox.warning(self, "Mật khẩu", "Hai lần nhập mật khẩu mở file không khớp.")
            return
        if not self.upw.text() and not self.opw.text():
            QMessageBox.warning(self, "Mật khẩu", "Hãy nhập ít nhất 1 mật khẩu.")
            return
        out = ask_save(self, "Lưu file bảo mật", os.path.splitext(self.pdf.name)[0] + "_baomat.pdf")
        if not out:
            return
        perms = [k for k, cb in self.perm_cb.items() if cb.isChecked()]
        method = ["aes256", "aes128", "rc4"][self.method.currentIndex()]
        tmp = fitz.open("pdf", self.pdf.doc.tobytes())
        op.save_encrypted(tmp, out, self.upw.text(), self.opw.text(), perms, method, self.strip.isChecked())
        tmp.close()
        done_message(self, "Đã lưu file có bảo mật.", out)

    def decrypt(self):
        out = ask_save(self, "Lưu file không mật khẩu", os.path.splitext(self.pdf.name)[0] + "_mo.pdf")
        if out:
            op.save_decrypted(self.pdf.doc, out)
            done_message(self, "Đã gỡ mật khẩu.", out)

    def redact(self):
        t = self.needle.text().strip()
        if not t:
            return
        self.pdf.snapshot()
        n = op.redact_text(self.pdf.doc, t)
        self.pdf.commit("content")
        QMessageBox.information(self, "Che thông tin", f"Đã che {n} vị trí.")


class CompressDialog(QDialog):
    def __init__(self, parent=None, pdfdoc=None):
        super().__init__(parent)
        self.pdf = pdfdoc
        self.setWindowTitle("Nén / giảm dung lượng PDF")
        f = QFormLayout(self)
        size = len(pdfdoc.original_bytes or b"")
        f.addRow(QLabel(f"Dung lượng hiện tại: <b>{human_size(size)}</b>"))
        self.level = QComboBox()
        self.level.addItems(["Nhẹ – ảnh 200 DPI, chất lượng 85", "Vừa – ảnh 150 DPI, chất lượng 70 (khuyên dùng)",
                             "Mạnh – ảnh 100 DPI, chất lượng 55", "Rất mạnh – ảnh 72 DPI, chất lượng 45"])
        self.level.setCurrentIndex(1)
        self.gray = QCheckBox("Chuyển ảnh sang thang xám")
        f.addRow("Mức nén:", self.level)
        f.addRow(self.gray)
        f.addRow(buttons(self, "Nén và lưu…"))

    def run(self):
        dpi, q = [(200, 85), (150, 70), (100, 55), (72, 45)][self.level.currentIndex()]
        out = ask_save(self, "Lưu file nén", os.path.splitext(self.pdf.name)[0] + "_nen.pdf")
        if not out:
            return
        data = self.pdf.doc.tobytes()
        gray = self.gray.isChecked()

        def job(progress=None):
            d = fitz.open("pdf", data)
            op.compress(d, out, dpi, q, gray)
            return os.path.getsize(out)
        ok, res = run_task(self, "Đang nén…", job)
        if ok:
            done_message(self, f"Đã nén: {human_size(len(data))} → {human_size(res)}", out)


# ============================================================ N-UP
class NupDialog(QDialog):
    def __init__(self, parent=None, pdfdoc=None):
        super().__init__(parent)
        self.pdf = pdfdoc
        self.setWindowTitle("In nhiều trang trên 1 tờ")
        self.resize(820, 560)
        main = QHBoxLayout(self)
        f = QFormLayout()
        main.addLayout(f)
        self.n = QComboBox()
        for k in (2, 4, 6, 8, 9, 12, 16):
            self.n.addItem(f"{k} trang / tờ", k)
        self.n.setCurrentIndex(1)
        self.paper = QComboBox()
        self.paper.addItems(["A4", "A3", "A5", "Letter"])
        self.orient = QComboBox()
        self.orient.addItems(["Tự động", "Dọc", "Ngang"])
        self.order = QComboBox()
        self.order.addItems(["Ngang (trái → phải)", "Dọc (trên → dưới)"])
        self.margin = QDoubleSpinBox(minimum=0, maximum=40, value=5, suffix=" mm")
        self.gap = QDoubleSpinBox(minimum=0, maximum=40, value=3, suffix=" mm")
        self.border = QCheckBox("Kẻ khung từng trang")
        self.border.setChecked(True)
        self.rng = QLineEdit(placeholderText="Để trống = tất cả")
        for lbl, w in (("Số trang/tờ:", self.n), ("Khổ giấy:", self.paper), ("Hướng giấy:", self.orient),
                       ("Thứ tự:", self.order), ("Lề:", self.margin), ("Khoảng cách:", self.gap), ("Trang:", self.rng)):
            f.addRow(lbl, w)
        f.addRow(self.border)
        bp = QPushButton("In…")
        bp.setObjectName("primary")
        bs = QPushButton("Lưu thành PDF…")
        bp.clicked.connect(self.do_print)
        bs.clicked.connect(self.do_save)
        f.addRow(bp)
        f.addRow(bs)
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setStyleSheet("background:#8A8F99; border-radius:6px;")
        self.preview.setMinimumSize(420, 500)
        main.addWidget(self.preview, 1)
        for w in (self.n, self.paper, self.orient, self.order):
            w.currentIndexChanged.connect(self.update_preview)
        for w in (self.margin, self.gap):
            w.valueChanged.connect(self.update_preview)
        self.border.toggled.connect(self.update_preview)
        self.rng.editingFinished.connect(self.update_preview)
        QTimer.singleShot(0, self.update_preview)

    def build(self):
        pages = parse_pages(self.rng.text(), self.pdf.page_count)
        land = {0: None, 1: False, 2: True}[self.orient.currentIndex()]
        return op.nup(self.pdf.doc, self.n.currentData(), self.paper.currentText(), land, self.margin.value(),
                      self.gap.value(), self.border.isChecked(), "row" if self.order.currentIndex() == 0 else "col",
                      pages)

    def update_preview(self):
        try:
            d = self.build()
            pg = d[0]
            z = min(self.preview.width() / pg.rect.width, self.preview.height() / pg.rect.height) * 0.95
            self.preview.setPixmap(QPixmap.fromImage(pix_to_qimage(pg.get_pixmap(matrix=fitz.Matrix(z, z)))))
            self.preview.setToolTip(f"{d.page_count} tờ")
        except Exception as e:
            self.preview.setText(str(e))

    def do_save(self):
        out = ask_save(self, "Lưu PDF in nhiều trang", os.path.splitext(self.pdf.name)[0] + f"_{self.n.currentData()}trang_to.pdf")
        if out:
            self.build().save(out, garbage=3, deflate=True)
            done_message(self, "Đã lưu.", out)

    def do_print(self):
        from .printing import print_document
        print_document(self, self.build(), title=self.pdf.name)


# ============================================================ PDF -> WORD
IMG_EXT = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp", ".gif", ".jfif")


class ToWordDialog(QDialog):
    """PDF / PDF scan / ảnh chụp -> Word: đọc chữ và viết lại thành văn bản sửa được."""

    def __init__(self, parent=None, path=None, page_count=0, modified=False, files=None):
        super().__init__(parent)
        self.setWindowTitle("Chuyển PDF / ảnh sang Word (đọc chữ, sửa được)")
        self.setMinimumWidth(640)
        lay = QVBoxLayout(self)
        g = QGroupBox("Nguồn")
        gl = QVBoxLayout(g)
        self.r_cur = QRadioButton(f"File đang mở: {os.path.basename(path) if path else '(chưa lưu)'}")
        self.r_files = QRadioButton("Chọn file PDF / ảnh (kéo thả vào danh sách, sắp xếp thứ tự):")
        self.files = FileList("PDF và ảnh (*.pdf *.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp)")
        self.files.setEnabled(False)
        self.r_files.toggled.connect(self.files.setEnabled)
        self.path = path
        if files:
            self.files.add(files)
        if path and not files:
            self.r_cur.setChecked(True)
        else:
            self.r_cur.setEnabled(bool(path))
            self.r_files.setChecked(True)
        gl.addWidget(self.r_cur)
        gl.addWidget(self.r_files)
        gl.addWidget(self.files)
        self.merge = QCheckBox("Gộp tất cả vào 1 file Word (mỗi ảnh / file thành các trang nối tiếp)")
        self.merge.setChecked(True)
        gl.addWidget(self.merge)
        lay.addWidget(g)
        f = QFormLayout()
        self.rng = QLineEdit(placeholderText="Để trống = tất cả (chỉ áp dụng cho PDF)")
        f.addRow("Trang:", self.rng)
        self.mode = QComboBox()
        self.mode.addItems(["Tự động – trang scan/ảnh thì ĐỌC CHỮ, trang có chữ thật thì lấy chữ gốc (khuyên dùng)",
                            "Luôn đọc chữ từ hình (OCR) – dựng lại văn bản, bỏ qua mọi lớp chữ có sẵn",
                            "PDF xuất từ Word/Excel – giữ nguyên định dạng, ảnh, bảng gốc (không OCR)"])
        f.addRow("Cách chuyển:", self.mode)
        self.layout_box = QComboBox()
        self.layout_box.addItems(["Giống bản gốc nhất – giữ đúng vị trí dòng, chỗ xuống dòng, cỡ chữ (khuyên dùng)",
                                  "Liền mạch – vẫn đúng cỡ chữ, lề, khoảng cách nhưng tự xuống dòng khi sửa nội dung"])
        self.layout_box.setCurrentIndex(0 if config().get("word_layout", "exact") == "exact" else 1)
        f.addRow("Bố cục:", self.layout_box)
        self.pre = QCheckBox("Tự nắn phẳng, khử bóng, chỉnh nghiêng ảnh chụp trước khi đọc chữ")
        self.pre.setChecked(True)
        f.addRow(self.pre)
        self.font = QComboBox()
        self.font.addItems(["Times New Roman", "Arial"])
        self.font.setCurrentIndex(0 if config().get("default_font", "times") == "times" else 1)
        f.addRow("Phông chữ Word:", self.font)
        lay.addLayout(f)
        note = QLabel("<i>Kết quả là văn bản Word gõ lại hoàn toàn (sửa được từng chữ): giữ khổ giấy, lề, căn "
                      "giữa/phải/đều, thụt đầu dòng, cỡ chữ, quốc hiệu 2 cột, bảng kẻ khung. Chữ viết tay, con dấu "
                      "đè chữ, ảnh mờ có thể đọc sai – nên soát lại.</i>")
        note.setWordWrap(True)
        lay.addWidget(note)
        lay.addWidget(buttons(self, "Chuyển sang Word"))

    def run(self, current_bytes=None):
        from . import ops_ocr
        mode = ["auto", "ocr", "text"][self.mode.currentIndex()]
        pre = self.pre.isChecked()
        layout = "exact" if self.layout_box.currentIndex() == 0 else "flow"
        config()["word_layout"] = layout
        config()["default_font"] = "times" if self.font.currentIndex() == 0 else "arial"
        srcs = [self.path] if self.r_cur.isChecked() else self.files.paths()
        if not srcs:
            QMessageBox.information(self, "Word", "Hãy chọn file PDF hoặc ảnh.")
            return
        merge = self.merge.isChecked() and len(srcs) > 1
        if len(srcs) == 1 or merge:
            name = os.path.splitext(os.path.basename(srcs[0]))[0] + (" (gop)" if merge else "") + ".docx"
            out = ask_save(self, "Lưu file Word", name, "Word (*.docx)")
            if not out:
                return
            outs = [out]
        else:
            d = ask_dir(self, "Chọn thư mục lưu file Word")
            if not d:
                return
            outs = [os.path.join(d, os.path.splitext(os.path.basename(s))[0] + ".docx") for s in srcs]
        rng = self.rng.text()

        def job(progress=None):
            if merge:
                return [ops_ocr.files_to_word(srcs, outs[0], mode=mode, page_range=rng, preprocess=pre,
                                              progress=progress, layout=layout)]
            res = []
            for k, (s, o) in enumerate(zip(srcs, outs)):
                cb = (lambda i, n_, m, k=k: progress(i, n_, f"[{k + 1}/{len(srcs)}] {m}"))
                ops_ocr.files_to_word([s], o, mode=mode, page_range=rng, preprocess=pre, progress=cb, layout=layout)
                res.append(o)
            return res
        ok, res = run_task(self, "Đang đọc chữ và dựng file Word…", job)
        if ok and res:
            done_message(self, f"Đã tạo {len(res)} file Word (chữ sửa được).", res[0] if len(res) == 1 else None,
                         folder=os.path.dirname(res[0]))


class OcrLayerDialog(QDialog):
    def __init__(self, parent=None, pdfdoc=None):
        super().__init__(parent)
        self.pdf = pdfdoc
        self.setWindowTitle("Nhận dạng chữ (OCR) – PDF tìm kiếm được")
        f = QFormLayout(self)
        f.addRow(QLabel("Thêm lớp chữ ẩn lên các trang scan để tìm kiếm (Ctrl+F), bôi đen, sao chép được.\n"
                        "Hình ảnh trang giữ nguyên."))
        self.rng = QLineEdit(placeholderText="Để trống = tất cả")
        self.lang = QComboBox()
        self.lang.addItems(["vie+eng", "vie", "eng"])
        self.lang.setCurrentText(config().get("ocr_lang", "vie+eng"))
        f.addRow("Trang:", self.rng)
        f.addRow("Ngôn ngữ:", self.lang)
        f.addRow(buttons(self, "Nhận dạng"))

    def run(self):
        from . import ops_ocr
        pages = parse_pages(self.rng.text(), self.pdf.page_count)
        lang = self.lang.currentText()
        data = self.pdf.doc.tobytes()
        holder = {}

        def job(progress=None):
            d = fitz.open("pdf", data)
            n = ops_ocr.add_ocr_layer(d, pages, lang=lang, progress=progress)
            holder["bytes"] = d.tobytes(garbage=3, deflate=True)
            return n
        ok, n = run_task(self, "Đang nhận dạng chữ…", job)
        if ok:
            self.pdf.snapshot()
            self.pdf._restore(holder["bytes"])
            self.pdf.commit("reload")
            QMessageBox.information(self, "OCR", f"Đã nhận dạng {n} trang scan.\n"
                                                 "Trang có sẵn chữ được bỏ qua.")
