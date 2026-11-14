"""Hộp thoại cho bản vẽ: In vùng bản vẽ (đúng tỉ lệ / vừa khổ) và Xuất PDF -> CAD (DXF/DWG)."""
import os

import pymupdf as fitz
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QVBoxLayout, QFormLayout, QGroupBox, QLabel, QComboBox,
                               QRadioButton, QButtonGroup, QDoubleSpinBox, QSpinBox, QCheckBox, QLineEdit,
                               QPushButton, QMessageBox, QFileDialog, QDialogButtonBox, QGridLayout)

from . import ops_cad as oc
from .util import config, parse_pages
from .viewer import pix_to_qimage
from .widgets import ask_save, ask_dir, run_task, done_message

ODA_URL = "https://www.opendesign.com/guestfiles/oda_file_converter"


# ======================================================== IN VÙNG BẢN VẼ
class PrintRegionDialog(QDialog):
    def __init__(self, parent, pdfdoc, pno, rect):
        super().__init__(parent)
        self.pdf, self.pno, self.rect = pdfdoc, pno, fitz.Rect(rect)
        self.setWindowTitle("In vùng bản vẽ")
        self.resize(980, 640)
        page = pdfdoc.doc[pno]
        self.drawing_scale = oc.detect_scale(page)
        main = QHBoxLayout(self)
        left = QVBoxLayout()
        main.addLayout(left)
        w_mm, h_mm = self.rect.width * oc.PT2MM, self.rect.height * oc.PT2MM
        left.addWidget(QLabel(f"<b>Vùng chọn:</b> {w_mm:.0f} × {h_mm:.0f} mm (trên khổ giấy gốc), trang {pno + 1}"))

        g = QGroupBox("Khổ giấy in")
        f = QFormLayout(g)
        self.paper = QComboBox()
        self.paper.addItems(list(oc.PAPERS))
        self.paper.setCurrentText("A4")
        self.orient = QComboBox()
        self.orient.addItems(["Tự động theo vùng chọn", "Dọc", "Ngang"])
        self.margin = QDoubleSpinBox(minimum=0, maximum=50, value=8, suffix=" mm")
        f.addRow("Khổ:", self.paper)
        f.addRow("Hướng:", self.orient)
        f.addRow("Lề:", self.margin)
        left.addWidget(g)

        g2 = QGroupBox("Tỉ lệ in")
        gl = QVBoxLayout(g2)
        self.grp = QButtonGroup(self)
        self.r_fit = QRadioButton("Phóng vừa khổ giấy (to nhất có thể)")
        self.r_actual = QRadioButton("ĐÚNG TỈ LỆ bản vẽ gốc (100% – đo thước trên giấy vẫn đúng)")
        self.r_pct = QRadioButton("Tỉ lệ tuỳ chọn:")
        self.pct = QDoubleSpinBox(minimum=1, maximum=2000, value=100, suffix=" %", decimals=1)
        row = QHBoxLayout()
        row.addWidget(self.r_pct)
        row.addWidget(self.pct)
        for i, r in enumerate((self.r_fit, self.r_actual, self.r_pct)):
            self.grp.addButton(r, i)
        self.r_fit.setChecked(True)
        gl.addWidget(self.r_fit)
        gl.addWidget(self.r_actual)
        gl.addLayout(row)
        self.scale_in = QSpinBox(minimum=0, maximum=100000, value=self.drawing_scale or 0, prefix="1 : ",
                                 specialValueText="(không rõ)")
        rr = QHBoxLayout()
        rr.addWidget(QLabel("Tỉ lệ bản vẽ gốc:"))
        rr.addWidget(self.scale_in)
        gl.addLayout(rr)
        self.info = QLabel()
        self.info.setWordWrap(True)
        gl.addWidget(self.info)
        left.addWidget(g2)

        g3 = QGroupBox("Trình bày")
        f3 = QFormLayout(g3)
        self.frame = QCheckBox("Kẻ khung quanh vùng in")
        self.note = QCheckBox("Ghi chú tỉ lệ và nguồn ở chân giấy")
        self.note.setChecked(True)
        f3.addRow(self.frame)
        f3.addRow(self.note)
        left.addWidget(g3)
        left.addStretch()
        bb = QHBoxLayout()
        bp = QPushButton("In…")
        bp.setObjectName("primary")
        bp.clicked.connect(self.do_print)
        bs = QPushButton("Lưu PDF…")
        bs.clicked.connect(self.do_save)
        bc = QPushButton("Đóng")
        bc.clicked.connect(self.reject)
        bb.addStretch()
        for b in (bs, bp, bc):
            bb.addWidget(b)
        left.addLayout(bb)

        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumSize(480, 580)
        self.preview.setStyleSheet("background:#8A8F99; border-radius:6px;")
        main.addWidget(self.preview, 1)
        self.timer = QTimer(self, singleShot=True, interval=120, timeout=self.update_preview)
        for w in (self.paper, self.orient):
            w.currentIndexChanged.connect(lambda *_: self.timer.start())
        for w in (self.margin, self.pct, self.scale_in):
            w.valueChanged.connect(lambda *_: self.timer.start())
        self.grp.idClicked.connect(lambda *_: self.timer.start())
        for w in (self.frame, self.note):
            w.toggled.connect(lambda *_: self.timer.start())
        QTimer.singleShot(0, self.update_preview)

    def build(self):
        mode = ["fit", "actual", "percent"][self.grp.checkedId()]
        orient = ["auto", "portrait", "landscape"][self.orient.currentIndex()]
        # tính trước tỉ lệ để ghi chú
        tmp, s, over = oc.region_on_paper(self.pdf.doc, self.pno, self.rect, self.paper.currentText(), orient,
                                          mode, self.pct.value(), self.margin.value())
        note = ""
        n = self.scale_in.value()
        if self.note.isChecked():
            note = f"{self.pdf.name} – trang {self.pno + 1} – in {s * 100:.1f}% so với bản gốc"
            if n:
                note += f" – tỉ lệ in thực tế 1:{n / s:.0f}"
        out, s, over = oc.region_on_paper(self.pdf.doc, self.pno, self.rect, self.paper.currentText(), orient,
                                          mode, self.pct.value(), self.margin.value(), self.frame.isChecked(), note)
        return out, s, over

    def update_preview(self):
        try:
            out, s, over = self.build()
            n = self.scale_in.value()
            txt = f"Thu phóng: <b>{s * 100:.1f}%</b> so với bản gốc."
            if n:
                txt += f" Bản vẽ gốc 1:{n} → in ra tương đương <b>1:{n / s:.0f}</b>."
            if over:
                txt += "<br><span style='color:#C62828'><b>Vùng chọn lớn hơn khổ giấy – phần thừa sẽ bị cắt.</b> " \
                       "Chọn khổ lớn hơn hoặc giảm tỉ lệ.</span>"
            self.info.setText(txt)
            pg = out[0]
            z = min(self.preview.width() / pg.rect.width, self.preview.height() / pg.rect.height) * 0.95
            self.preview.setPixmap(QPixmap.fromImage(pix_to_qimage(pg.get_pixmap(matrix=fitz.Matrix(z, z)))))
        except Exception as e:
            self.preview.setText(str(e))

    def do_print(self):
        from .printing import print_document
        out, s, over = self.build()
        # Vừa khổ: vẫn in đúng khổ giấy đã chọn; Đúng tỉ lệ: in 1:1 không co giãn
        print_document(self, out, f"Vùng bản vẽ - {self.pdf.name}", exact=True)

    def do_save(self):
        out, s, over = self.build()
        p = ask_save(self, "Lưu vùng bản vẽ", os.path.splitext(self.pdf.name)[0] +
                     f"_vung_tr{self.pno + 1}_{self.paper.currentText()}.pdf")
        if p:
            out.save(p, garbage=3, deflate=True)
            done_message(self, "Đã lưu.", p)


# ============================================================ PDF -> CAD
class CadExportDialog(QDialog):
    def __init__(self, parent, pdfdoc, pno, rect=None):
        super().__init__(parent)
        self.pdf, self.pno, self.rect = pdfdoc, pno, rect
        self.setWindowTitle("Xuất bản vẽ PDF sang CAD (DWG / DXF)")
        self.setMinimumWidth(640)
        page = pdfdoc.doc[pno]
        lay = QVBoxLayout(self)

        g0 = QGroupBox("Phạm vi")
        f0 = QFormLayout(g0)
        self.scope = QComboBox()
        if rect is not None:
            self.scope.addItem(f"Vùng đã chọn trên trang {pno + 1}", "region")
        self.scope.addItem(f"Trang hiện tại ({pno + 1})", "page")
        self.scope.addItem("Nhiều trang (mỗi trang 1 file)…", "pages")
        self.pages = QLineEdit(placeholderText="vd 1-5, 8")
        self.pages.setEnabled(False)
        self.scope.currentIndexChanged.connect(lambda *_: self.pages.setEnabled(self.scope.currentData() == "pages"))
        f0.addRow("Xuất:", self.scope)
        f0.addRow("Các trang:", self.pages)
        lay.addWidget(g0)

        g = QGroupBox("Tỉ lệ – quy đổi về kích thước thật")
        gl = QGridLayout(g)
        self.grp = QButtonGroup(self)
        self.r_scale = QRadioButton("Theo tỉ lệ bản vẽ:")
        self.scale = QSpinBox(minimum=1, maximum=100000, value=oc.detect_scale(page) or 100, prefix="1 : ")
        auto = oc.detect_scale(page)
        self.r_cal = QRadioButton("Hiệu chỉnh theo kích thước đã biết:")
        self.meas = QComboBox()
        for d, lbl in oc.measure_lines(page):
            self.meas.addItem(f"Đường đo dài {d:.2f} mm trên giấy  {('(' + lbl + ')') if lbl else ''}", d)
        self.real = QDoubleSpinBox(minimum=0.001, maximum=1e9, decimals=2, value=6000)
        self.r_paper = QRadioButton("Giữ kích thước trên giấy (1:1, đơn vị mm giấy)")
        for i, r in enumerate((self.r_scale, self.r_cal, self.r_paper)):
            self.grp.addButton(r, i)
        self.r_scale.setChecked(True)
        gl.addWidget(self.r_scale, 0, 0)
        gl.addWidget(self.scale, 0, 1)
        gl.addWidget(QLabel(f"<i>{'Tự nhận được tỉ lệ 1:' + str(auto) + ' từ chữ trên bản vẽ' if auto else 'Không tự nhận được tỉ lệ – nhập theo khung tên'}</i>"), 1, 0, 1, 2)
        gl.addWidget(self.r_cal, 2, 0, 1, 2)
        if self.meas.count():
            gl.addWidget(self.meas, 3, 0, 1, 2)
            gl.addWidget(QLabel("Kích thước thật của đường đo này:"), 4, 0)
            gl.addWidget(self.real, 4, 1)
        else:
            self.r_cal.setEnabled(False)
            gl.addWidget(QLabel("<i>Để dùng cách này: đóng hộp thoại, dùng công cụ <b>Ghi chú → Đo kích thước</b> "
                                "kéo theo 1 kích thước đã ghi trên bản vẽ (vd trục 6000), rồi mở lại.</i>"), 3, 0, 1, 2)
        gl.addWidget(self.r_paper, 5, 0, 1, 2)
        self.unit = QComboBox()
        self.unit.addItems(["mm", "cm", "m"])
        gl.addWidget(QLabel("Đơn vị bản vẽ CAD:"), 6, 0)
        gl.addWidget(self.unit, 6, 1)
        lay.addWidget(g)

        g2 = QGroupBox("Nội dung")
        f2 = QGridLayout(g2)
        self.text = QCheckBox("Chữ (TEXT, phông Arial – hiển thị tiếng Việt)")
        self.fill = QCheckBox("Vùng tô đặc (HATCH)")
        self.layers = QCheckBox("Tách layer theo màu nét")
        self.circles = QCheckBox("Nhận dạng đường tròn (CIRCLE)")
        self.frame = QCheckBox("Vẽ khung khổ giấy (layer KHUNG_GIAY)")
        for i, cb in enumerate((self.text, self.fill, self.layers, self.circles, self.frame)):
            cb.setChecked(True)
            f2.addWidget(cb, i // 2, i % 2)
        lay.addWidget(g2)

        g3 = QGroupBox("Định dạng file")
        f3 = QFormLayout(g3)
        self.fmt = QComboBox()
        self.fmt.addItem("DWG – AutoCAD 2018 (cần ODA File Converter miễn phí)", ("DWG", "ACAD2018"))
        self.fmt.addItem("DWG – AutoCAD 2013", ("DWG", "ACAD2013"))
        self.fmt.addItem("DWG – AutoCAD 2010", ("DWG", "ACAD2010"))
        self.fmt.addItem("DWG – AutoCAD 2007", ("DWG", "ACAD2007"))
        self.fmt.addItem("DXF – AutoCAD 2018 (mở trực tiếp bằng AutoCAD, không cần cài thêm)", ("DXF", ""))
        oda = oc.find_oda()
        if not oda:
            self.fmt.setCurrentIndex(4)
        f3.addRow("Lưu dạng:", self.fmt)
        self.oda_lbl = QLabel(f"ODA File Converter: {oda}" if oda else
                              f"<span style='color:#C62828'>Chưa cài ODA File Converter</span> – "
                              f"<a href='{ODA_URL}'>tải miễn phí</a> để xuất thẳng DWG, hoặc chọn DXF.")
        self.oda_lbl.setOpenExternalLinks(True)
        self.oda_lbl.setWordWrap(True)
        bo = QPushButton("Chỉ đường dẫn ODA…")
        bo.clicked.connect(self.pick_oda)
        f3.addRow(self.oda_lbl)
        f3.addRow(bo)
        lay.addWidget(g3)
        note = QLabel("<i>Lưu ý: PDF chỉ chứa nét vẽ – kích thước (DIM), block, hatch mẫu, layer gốc của CAD "
                      "không còn trong PDF nên sẽ thành nét/hatch thường. Ảnh scan không chuyển được thành nét.</i>")
        note.setWordWrap(True)
        lay.addWidget(note)
        bb = QDialogButtonBox()
        ok = bb.addButton("Xuất file CAD…", QDialogButtonBox.AcceptRole)
        ok.setObjectName("primary")
        bb.addButton("Đóng", QDialogButtonBox.RejectRole)
        bb.accepted.connect(self.run)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def pick_oda(self):
        p, _ = QFileDialog.getOpenFileName(self, "Chọn ODAFileConverter.exe", r"C:\Program Files\ODA",
                                           "ODAFileConverter.exe (ODAFileConverter.exe)")
        if p:
            config()["oda_path"] = p
            config().save()
            self.oda_lbl.setText(f"ODA File Converter: {p}")

    def scale_value(self):
        mode = self.grp.checkedId()
        if mode == 0:
            return float(self.scale.value())
        if mode == 1:
            paper_mm = self.meas.currentData() or 1
            return self.real.value() / paper_mm      # thật (mm) / giấy (mm)
        return 1.0

    def run(self):
        kind, ver = self.fmt.currentData()
        if kind == "DWG" and not oc.find_oda():
            r = QMessageBox.question(self, "Chưa có ODA File Converter",
                                     "Để lưu thẳng DWG cần cài ODA File Converter (miễn phí, của Open Design Alliance).\n\n"
                                     "Yes: mở trang tải về\nNo: lưu dạng DXF (AutoCAD mở được, rồi Save As DWG)")
            if r == QMessageBox.Yes:
                import webbrowser
                webbrowser.open(ODA_URL)
                return
            kind = "DXF"
        scale = self.scale_value()
        scope = self.scope.currentData()
        base = os.path.splitext(self.pdf.name)[0]
        ext = ".dwg" if kind == "DWG" else ".dxf"
        if scope == "pages":
            try:
                pages = parse_pages(self.pages.text(), self.pdf.page_count)
            except Exception as e:
                QMessageBox.warning(self, "Trang", str(e))
                return
            d = ask_dir(self, "Thư mục lưu file CAD")
            if not d:
                return
            jobs = [(p, os.path.join(d, f"{base}_trang{p + 1:02d}{ext}"), None) for p in pages]
        else:
            out = ask_save(self, "Lưu file CAD", f"{base}_trang{self.pno + 1}{ext}",
                           "AutoCAD DWG (*.dwg)" if kind == "DWG" else "AutoCAD DXF (*.dxf)")
            if not out:
                return
            jobs = [(self.pno, out, self.rect if scope == "region" else None)]
        data = self.pdf.doc.tobytes()
        opts = dict(scale=scale, unit=self.unit.currentText(), include_text=self.text.isChecked(),
                    include_fill=self.fill.isChecked(), layer_by_color=self.layers.isChecked(),
                    detect_circles=self.circles.isChecked(), frame=self.frame.isChecked())

        def job(progress=None):
            import tempfile
            doc = fitz.open("pdf", data)
            res = []
            for k, (p, outp, clip) in enumerate(jobs):
                dxf = outp if kind == "DXF" else os.path.join(tempfile.gettempdir(), f"phantom_{k}.dxf")
                st = oc.pdf_to_dxf(doc, p, dxf, clip=clip,
                                   progress=lambda i, n, m: progress(i, n, f"[{k + 1}/{len(jobs)}] {m}"), **opts)
                if st is None:
                    break
                if kind == "DWG":
                    progress(0, 0, "Chuyển DXF → DWG (ODA File Converter)…")
                    oc.dxf_to_dwg(dxf, outp, ver)
                    os.remove(dxf)
                res.append((outp, st))
            return res
        ok, res = run_task(self, "Đang xuất bản vẽ CAD…", job)
        if ok and res:
            outp, st = res[0]
            w, h = st["size"]
            u = self.unit.currentText()
            msg = (f"Đã xuất {len(res)} file {kind}.\n\nTỉ lệ 1:{scale:g} – đơn vị {u}. Khung giấy = {w:,.0f} × {h:,.0f} {u}.\n"
                   f"Trang 1: {st['line'] + st['polyline']} nét, {st['circle']} đường tròn, {st['text']} chữ, "
                   f"{st['hatch']} vùng tô.\n\nKiểm tra trong CAD: lệnh DIST đo 1 kích thước đã biết.")
            done_message(self, msg, outp if len(res) == 1 else None, folder=os.path.dirname(outp))
            config()["cad_scale"] = scale
            config().save()
            self.accept()
