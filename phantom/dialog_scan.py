"""Hộp thoại scan ảnh chụp văn bản -> PDF như máy scan: tự tìm góc, kéo chỉnh 4 góc,
chọn chế độ màu, xoay, xem trước kết quả."""
import os

import numpy as np
import cv2
from PySide6.QtCore import Qt, QPointF, QRectF, QTimer, QSize
from PySide6.QtGui import QImage, QPixmap, QPen, QColor, QBrush, QPolygonF, QIcon
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QVBoxLayout, QListWidget, QListWidgetItem, QLabel,
                               QPushButton, QComboBox, QCheckBox, QGraphicsView, QGraphicsScene,
                               QGraphicsEllipseItem, QGraphicsPolygonItem, QGraphicsItem, QFileDialog,
                               QMessageBox, QSplitter, QWidget, QFormLayout, QSpinBox, QApplication)

from . import ops_scan as sc
from .util import config, tessdata_dir
from .widgets import ask_save, run_task, done_message


def cv_to_qimage(img):
    if img.ndim == 2:
        h, w = img.shape
        return QImage(img.data, w, h, img.strides[0], QImage.Format_Grayscale8).copy()
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    h, w, _ = rgb.shape
    return QImage(rgb.data, w, h, rgb.strides[0], QImage.Format_RGB888).copy()


class Handle(QGraphicsEllipseItem):
    def __init__(self, editor, idx, r):
        super().__init__(-r, -r, 2 * r, 2 * r)
        self.editor = editor
        self.idx = idx
        self.setBrush(QBrush(QColor(239, 108, 0, 160)))
        self.setPen(QPen(Qt.white, max(1, r / 5)))
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
        self.setCursor(Qt.SizeAllCursor)
        self.setZValue(10)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged:
            self.editor.handle_moved()
        return super().itemChange(change, value)


class CornerEditor(QGraphicsView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setRenderHints(self.renderHints())
        self.setStyleSheet("background:#2B2D33;")
        self.img = None
        self.handles = []
        self.poly = None
        self.on_change = None

    def load(self, img, quad):
        self.scene().clear()
        self.handles = []
        self.img = img
        pm = QPixmap.fromImage(cv_to_qimage(img))
        self.scene().addPixmap(pm)
        self.scene().setSceneRect(QRectF(pm.rect()))
        self.poly = QGraphicsPolygonItem()
        self.poly.setPen(QPen(QColor("#FF9800"), max(2, img.shape[1] / 400)))
        self.poly.setBrush(QBrush(QColor(239, 108, 0, 40)))
        self.scene().addItem(self.poly)
        r = max(8, img.shape[1] / 70)
        for i, (x, y) in enumerate(quad):
            h = Handle(self, i, r)
            h.setPos(float(x), float(y))
            self.scene().addItem(h)
            self.handles.append(h)
        self.handle_moved()
        self.fitInView(self.scene().sceneRect(), Qt.KeepAspectRatio)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.img is not None:
            self.fitInView(self.scene().sceneRect(), Qt.KeepAspectRatio)

    def handle_moved(self):
        if self.poly is None or len(self.handles) < 4:
            return
        self.poly.setPolygon(QPolygonF([h.pos() for h in self.handles]))
        if self.on_change:
            self.on_change()

    def quad(self):
        return np.array([[h.pos().x(), h.pos().y()] for h in self.handles], dtype="float32")


class ScanDialog(QDialog):
    def __init__(self, parent=None, files=None):
        super().__init__(parent)
        self.setWindowTitle("Scan ảnh chụp văn bản thành PDF")
        self.resize(1200, 760)
        self.pages = []          # dict(path, img, quad, mode, rotate)
        main = QHBoxLayout(self)
        # danh sách
        left = QVBoxLayout()
        self.list = QListWidget()
        self.list.setIconSize(QSize(90, 120))
        self.list.setFixedWidth(170)
        self.list.setDragDropMode(QListWidget.InternalMove)
        self.list.currentRowChanged.connect(self.show_page)
        left.addWidget(self.list)
        for txt, fn in (("+ Thêm ảnh…", self.add_dialog), ("Dán từ Clipboard", self.paste), ("Xoá ảnh", self.remove)):
            b = QPushButton(txt)
            b.clicked.connect(fn)
            left.addWidget(b)
        main.addLayout(left)
        # vùng chỉnh
        sp = QSplitter()
        self.editor = CornerEditor()
        self.editor.on_change = lambda: self.timer.start()
        sp.addWidget(self.editor)
        self.result = QLabel()
        self.result.setAlignment(Qt.AlignCenter)
        self.result.setStyleSheet("background:#8A8F99;")
        sp.addWidget(self.result)
        sp.setSizes([600, 420])
        mid = QVBoxLayout()
        mid.addWidget(QLabel("<b>Kéo 4 chấm tím vào 4 góc tờ giấy</b> – bên phải là kết quả sau khi nắn phẳng:"))
        mid.addWidget(sp, 1)
        main.addLayout(mid, 1)
        # tuỳ chọn
        right = QFormLayout()
        w = QWidget()
        w.setLayout(right)
        w.setFixedWidth(250)
        self.mode = QComboBox()
        for k, v in sc.MODES.items():
            self.mode.addItem(v, k)
        self.mode.currentIndexChanged.connect(self.mode_changed)
        right.addRow("Chế độ màu:", self.mode)
        self.paper = QComboBox()
        self.paper.addItems(["A4", "A3", "Theo ảnh"])
        right.addRow("Khổ giấy:", self.paper)
        self.force_ratio = QCheckBox("Ép đúng tỉ lệ khổ giấy")
        self.force_ratio.setChecked(True)
        self.force_ratio.toggled.connect(lambda *_: self.timer.start())
        right.addRow(self.force_ratio)
        self.deskew = QCheckBox("Tự chỉnh nghiêng dòng chữ")
        self.deskew.setChecked(True)
        self.deskew.toggled.connect(lambda *_: self.timer.start())
        right.addRow(self.deskew)
        rot = QHBoxLayout()
        for t, a in (("⟲ Xoay trái", -90), ("Xoay phải ⟳", 90)):
            b = QPushButton(t)
            b.clicked.connect(lambda _, a=a: self.rotate(a))
            rot.addWidget(b)
        right.addRow(rot)
        b = QPushButton("Tự tìm lại 4 góc")
        b.clicked.connect(self.redetect)
        right.addRow(b)
        b = QPushButton("Dùng cả ảnh (không cắt)")
        b.clicked.connect(self.full)
        right.addRow(b)
        b = QPushButton("Áp dụng chế độ cho tất cả")
        b.clicked.connect(self.apply_all)
        right.addRow(b)
        self.dpi = QSpinBox(minimum=100, maximum=400, value=200, suffix=" DPI")
        right.addRow("Độ phân giải:", self.dpi)
        self.ocr = QCheckBox("Nhận dạng chữ (OCR) – PDF tìm kiếm được")
        self.ocr.setChecked(bool(tessdata_dir()))
        self.ocr.setEnabled(bool(tessdata_dir()))
        right.addRow(self.ocr)
        save = QPushButton("Lưu thành PDF…")
        save.setObjectName("primary")
        save.clicked.connect(self.save_pdf)
        right.addRow(save)
        b = QPushButton("Lưu thành ảnh…")
        b.clicked.connect(self.save_images)
        right.addRow(b)
        main.addWidget(w)
        self.timer = QTimer(self, singleShot=True, interval=120, timeout=self.update_result)
        if files:
            self.add(files)

    # ------------------------------------------------------------- dữ liệu
    def add(self, files):
        for f in files:
            try:
                img = sc.imread(f)
            except Exception as e:
                QMessageBox.warning(self, "Scan", str(e))
                continue
            self._append(f, img)

    def _append(self, name, img):
        # thu nhỏ ảnh quá lớn để thao tác nhanh (giữ tối đa 3500 px)
        h, w = img.shape[:2]
        s = 3500 / max(h, w)
        if s < 1:
            img = cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
        quad = sc.detect_document(img)
        self.pages.append({"path": name, "img": img, "quad": quad, "mode": config().get("scan_mode", "doc_color"), "rotate": 0})
        it = QListWidgetItem(QIcon(QPixmap.fromImage(cv_to_qimage(cv2.resize(img, (90, int(90 * img.shape[0] / img.shape[1])))))),
                             os.path.basename(name))
        it.setData(Qt.UserRole, len(self.pages) - 1)
        self.list.addItem(it)
        if self.list.count() == 1:
            self.list.setCurrentRow(0)

    def add_dialog(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Chọn ảnh chụp văn bản", config().get("last_dir", ""),
                                                "Ảnh (*.jpg *.jpeg *.png *.bmp *.tif *.tiff *.webp *.heic)")
        if files:
            self.add(files)

    def paste(self):
        img = QApplication.clipboard().image()
        if img.isNull():
            QMessageBox.information(self, "Dán", "Clipboard không có ảnh.")
            return
        img = img.convertToFormat(QImage.Format_RGB888)
        arr = np.array(img.constBits(), dtype=np.uint8).reshape(img.height(), img.bytesPerLine())[:, :img.width() * 3]
        arr = cv2.cvtColor(arr.reshape(img.height(), img.width(), 3), cv2.COLOR_RGB2BGR)
        self._append(f"clipboard_{len(self.pages) + 1}.png", arr)

    def remove(self):
        r = self.list.currentRow()
        if r >= 0:
            self.list.takeItem(r)

    def cur(self):
        it = self.list.currentItem()
        return self.pages[it.data(Qt.UserRole)] if it else None

    def show_page(self, row):
        p = self.cur()
        if not p:
            return
        self.editor.load(p["img"], p["quad"])
        self.mode.blockSignals(True)
        self.mode.setCurrentIndex(list(sc.MODES).index(p["mode"]))
        self.mode.blockSignals(False)
        self.timer.start()

    def mode_changed(self):
        p = self.cur()
        if p:
            p["mode"] = self.mode.currentData()
            config()["scan_mode"] = p["mode"]
            self.timer.start()

    def rotate(self, a):
        p = self.cur()
        if p:
            p["rotate"] = (p["rotate"] + a) % 360
            self.timer.start()

    def redetect(self):
        p = self.cur()
        if p:
            p["quad"] = sc.detect_document(p["img"])
            self.editor.load(p["img"], p["quad"])

    def full(self):
        p = self.cur()
        if p:
            h, w = p["img"].shape[:2]
            p["quad"] = np.array([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]], dtype="float32")
            self.editor.load(p["img"], p["quad"])

    def apply_all(self):
        m = self.mode.currentData()
        for p in self.pages:
            p["mode"] = m

    def ratio(self):
        if not self.force_ratio.isChecked() or self.paper.currentIndex() == 2:
            return None
        return 297 / 210

    def processed(self, p, preview=False):
        img = p["img"]
        quad = p["quad"]
        if preview:
            s = 1000 / max(img.shape[:2])
            if s < 1:
                img = cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
                quad = quad * s
        return sc.process(img, quad, p["mode"], self.ratio(), self.deskew.isChecked(), p["rotate"])

    def update_result(self):
        p = self.cur()
        if not p:
            return
        p["quad"] = self.editor.quad()
        try:
            out = self.processed(p, preview=True)
            pm = QPixmap.fromImage(cv_to_qimage(out))
            self.result.setPixmap(pm.scaled(self.result.size() * 0.95, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        except Exception as e:
            self.result.setText(str(e))

    def ordered(self):
        return [self.pages[self.list.item(i).data(Qt.UserRole)] for i in range(self.list.count())]

    def save_pdf(self):
        if self.cur():
            self.cur()["quad"] = self.editor.quad()
        pages = self.ordered()
        if not pages:
            return
        out = ask_save(self, "Lưu PDF scan", "Scan.pdf")
        if not out:
            return
        paper = {0: "A4", 1: "A3", 2: "auto"}[self.paper.currentIndex()]
        ocr = self.ocr.isChecked()

        def job(progress=None):
            imgs = []
            for i, p in enumerate(pages):
                progress(i, len(pages) * 2, f"Xử lý ảnh {i + 1}")
                imgs.append(self.processed(p))
            import pymupdf as fitz
            sc.images_to_pdf(imgs, out, dpi=self.dpi.value(), paper=paper,
                             progress=lambda i, n, m: progress(len(pages) + i, len(pages) * 2, m))
            if ocr:
                from . import ops_ocr
                d = fitz.open(out)
                ops_ocr.add_ocr_layer(d, progress=lambda i, n, m: progress(i, n, m))
                d.saveIncr()
                d.close()
            return out
        ok, res = run_task(self, "Đang tạo PDF scan…", job)
        if ok:
            done_message(self, f"Đã tạo PDF scan {len(pages)} trang.", out)

    def save_images(self):
        if self.cur():
            self.cur()["quad"] = self.editor.quad()
        d = QFileDialog.getExistingDirectory(self, "Thư mục lưu ảnh", config().get("last_dir", ""))
        if not d:
            return
        for i, p in enumerate(self.ordered(), 1):
            sc.imwrite(os.path.join(d, f"scan_{i:03d}.jpg"), self.processed(p))
        done_message(self, "Đã lưu ảnh scan.", folder=d)
