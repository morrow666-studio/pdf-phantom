"""Chuyển trang PDF thành ẢNH ngay trong file, ghép lại đúng vị trí trang đó.

Dùng khi: khoá nội dung không cho sửa, gộp ghi chú/dấu/chữ ký vào trang, sửa lỗi phông chữ khi in,
trang bản vẽ nặng mở chậm, nộp hồ sơ yêu cầu dạng ảnh scan."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGroupBox, QRadioButton, QLineEdit, QComboBox,
                               QDialogButtonBox, QLabel, QCheckBox, QButtonGroup, QSlider, QFormLayout,
                               QProgressDialog, QApplication, QMessageBox)

from .util import parse_pages, config


class RasterDialog(QDialog):
    def __init__(self, main, tab, pages):
        super().__init__(main)
        self.setWindowTitle("Chuyển trang thành ảnh (ghép lại đúng trang)")
        self.setMinimumWidth(500)
        self.tab, self.sel = tab, pages
        cfg = config()
        v = QVBoxLayout(self)
        g = QGroupBox("Trang cần chuyển")
        gl = QVBoxLayout(g)
        self.grp = QButtonGroup(self)
        cur = tab.view.current_page
        sel_txt = ", ".join(str(p + 1) for p in pages[:12]) + ("…" if len(pages) > 12 else "")
        self.r_cur = QRadioButton(f"Trang đang xem ({cur + 1})")
        self.r_sel = QRadioButton(f"Các trang đang chọn: {sel_txt}")
        self.r_all = QRadioButton(f"Toàn bộ {tab.pdf.page_count} trang")
        self.r_list = QRadioButton("Các trang:")
        self.list = QLineEdit()
        self.list.setPlaceholderText("vd: 1-3, 7")
        self.list.textEdited.connect(lambda *_: self.r_list.setChecked(True))
        for k, r in enumerate((self.r_cur, self.r_sel, self.r_all, self.r_list)):
            self.grp.addButton(r, k)
        (self.r_sel if len(pages) > 1 else self.r_cur).setChecked(True)
        self.r_sel.setVisible(len(pages) > 1)
        for r in (self.r_cur, self.r_sel, self.r_all):
            gl.addWidget(r)
        h = QHBoxLayout()
        h.addWidget(self.r_list)
        h.addWidget(self.list, 1)
        gl.addLayout(h)
        v.addWidget(g)

        g2 = QGroupBox("Chất lượng ảnh")
        f = QFormLayout(g2)
        self.dpi = QComboBox()
        for d, txt in ((150, "150 dpi – nhẹ, xem trên máy"), (200, "200 dpi – cân bằng (khuyên dùng)"),
                       (300, "300 dpi – in ấn, hồ sơ nộp"), (400, "400 dpi – bản vẽ chi tiết"),
                       (600, "600 dpi – bản vẽ nét mảnh, file rất nặng")):
            self.dpi.addItem(txt, d)
        self.dpi.setCurrentIndex(max(0, self.dpi.findData(cfg.get("raster_dpi", 200))))
        f.addRow("Độ phân giải:", self.dpi)
        self.color = QComboBox()
        for k, txt in (("color", "Màu (giữ dấu đỏ, chữ ký xanh)"), ("gray", "Xám"),
                       ("bw", "Đen trắng (nhẹ nhất, như scan văn bản)")):
            self.color.addItem(txt, k)
        self.color.setCurrentIndex(max(0, self.color.findData(cfg.get("raster_color", "color"))))
        f.addRow("Màu:", self.color)
        self.fmt = QComboBox()
        self.fmt.addItem("JPEG – nhẹ", "jpg")
        self.fmt.addItem("PNG – nét tuyệt đối, nặng hơn", "png")
        self.fmt.setCurrentIndex(max(0, self.fmt.findData(cfg.get("raster_fmt", "jpg"))))
        f.addRow("Định dạng:", self.fmt)
        qh = QHBoxLayout()
        self.q = QSlider(Qt.Horizontal, minimum=40, maximum=100, value=int(cfg.get("raster_q", 85)))
        self.ql = QLabel(f"{self.q.value()}")
        self.q.valueChanged.connect(lambda x: self.ql.setText(str(x)))
        qh.addWidget(self.q, 1)
        qh.addWidget(self.ql)
        f.addRow("Chất lượng JPEG:", qh)
        self.color.currentIndexChanged.connect(self._sync)
        self.fmt.currentIndexChanged.connect(self._sync)
        v.addWidget(g2)

        g3 = QGroupBox("Tuỳ chọn")
        g3l = QVBoxLayout(g3)
        self.keep_text = QCheckBox("Giữ lớp chữ ẩn – vẫn tìm kiếm (Ctrl+F), bôi đen, copy chữ được")
        self.keep_text.setChecked(bool(cfg.get("raster_text", True)))
        self.merge = QCheckBox("Gộp ghi chú, con dấu, chữ ký trên trang vào ảnh (không sửa / xoá được nữa)")
        self.merge.setChecked(bool(cfg.get("raster_merge", True)))
        g3l.addWidget(self.keep_text)
        g3l.addWidget(self.merge)
        note = QLabel("<i>Trang giữ nguyên vị trí, khổ giấy, chiều xoay, dấu trang. Chữ ký số trên trang "
                      "chuyển thành hình (không còn hiệu lực xác thực). Ctrl+Z để hoàn tác.</i>")
        note.setWordWrap(True)
        g3l.addWidget(note)
        v.addWidget(g3)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Chuyển thành ảnh")
        bb.button(QDialogButtonBox.Cancel).setText("Huỷ")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self._sync()

    def _sync(self):
        bw = self.color.currentData() == "bw"
        self.fmt.setEnabled(not bw)
        self.q.setEnabled(not bw and self.fmt.currentData() == "jpg")

    def pages(self):
        k = self.grp.checkedId()
        n = self.tab.pdf.page_count
        if k == 0:
            return [self.tab.view.current_page]
        if k == 1:
            return list(self.sel)
        if k == 2:
            return list(range(n))
        txt = self.list.text().strip()
        return sorted(set(parse_pages(txt, n))) if txt else []

    def options(self):
        o = dict(dpi=self.dpi.currentData(), color=self.color.currentData(), fmt=self.fmt.currentData(),
                 jpg_quality=self.q.value(), keep_text=self.keep_text.isChecked(), merge_annots=self.merge.isChecked())
        cfg = config()
        for k, v in (("raster_dpi", o["dpi"]), ("raster_color", o["color"]), ("raster_fmt", o["fmt"]),
                     ("raster_q", o["jpg_quality"]), ("raster_text", o["keep_text"]),
                     ("raster_merge", o["merge_annots"])):
            cfg[k] = v
        cfg.save()
        return o


def rasterize(main, tab, pages, opts):
    """Chạy trên luồng giao diện (an toàn với tài liệu đang hiển thị), có thanh tiến trình + huỷ."""
    from .ops_pages import rasterize_pages
    if not pages:
        main.flash("Chưa chọn trang nào.")
        return 0
    pd = QProgressDialog("Đang chuyển trang thành ảnh…", "Dừng", 0, len(pages), main)
    pd.setWindowTitle("Chuyển trang thành ảnh")
    pd.setWindowModality(Qt.WindowModal)
    pd.setMinimumDuration(400)

    def prog(i, n, msg):
        pd.setValue(i)
        pd.setLabelText(f"Đang chuyển {msg}  ({i}/{n})")
        QApplication.processEvents()
        return not pd.wasCanceled()

    tab.pdf.snapshot()
    QApplication.setOverrideCursor(Qt.WaitCursor)
    try:
        n = rasterize_pages(tab.pdf.doc, pages, progress=prog, **opts)
    except Exception as e:
        QApplication.restoreOverrideCursor()
        pd.close()
        tab.pdf.undo()
        QMessageBox.critical(main, "Chuyển trang thành ảnh", f"Lỗi: {e}")
        return 0
    QApplication.restoreOverrideCursor()
    pd.close()
    tab.pdf.commit("reload")
    main.flash(f"Đã chuyển {n} trang thành ảnh, ghép lại đúng vị trí. Ctrl+Z để hoàn tác.", 10000)
    return n
