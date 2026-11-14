"""Chèn ảnh vào trang có TỰ XOÁ PHÔNG NỀN (chữ ký tay, con dấu, logo chụp trên giấy trắng...).

Phím tắt trong cửa sổ chỉnh ảnh:
  B           bật / tắt xoá nền            [ hoặc -   giảm ngưỡng xoá     ] hoặc +   tăng ngưỡng
  E           chỉ xoá nền nối từ mép ảnh (giữ vùng trắng bên trong con dấu)
  C           cắt sát nội dung             R / Shift+R   xoay phải / trái 90°
  1 2 3 4     màu mực: giữ nguyên / xanh / đỏ / đen
  S           lưu ảnh đã xoá nền vào thư viện con dấu      Ctrl+Z hoàn tác
  Enter       chèn vào trang               Esc  huỷ
"""
import os

import numpy as np
import cv2
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPixmap, QPainter, QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QVBoxLayout, QLabel, QSlider, QCheckBox, QComboBox,
                               QPushButton, QGroupBox, QFormLayout, QSpinBox, QMessageBox)

from .util import user_dir

INK = {"Giữ nguyên màu": None, "Xanh mực (chữ ký)": (26, 61, 158), "Đỏ (con dấu)": (211, 47, 47),
       "Đen": (20, 20, 20)}


def load_any(src):
    """Đường dẫn / QImage / bytes -> mảng BGRA."""
    if isinstance(src, QImage):
        img = src.convertToFormat(QImage.Format_RGBA8888)
        arr = np.array(img.constBits(), dtype=np.uint8).reshape(img.height(), img.bytesPerLine())
        arr = arr[:, :img.width() * 4].reshape(img.height(), img.width(), 4)
        return cv2.cvtColor(arr, cv2.COLOR_RGBA2BGRA)
    if isinstance(src, (bytes, bytearray)):
        data = np.frombuffer(src, np.uint8)
    else:
        data = np.fromfile(src, dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_UNCHANGED)
    if img is None:
        raise RuntimeError("Không đọc được ảnh.")
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGRA)
    elif img.shape[2] == 3:
        img = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
    return img


def remove_background(bgra, threshold=28, soft=12, edge_only=False, flatten_light=True):
    """Xoá nền: ước lượng màu nền từ viền ảnh, pixel gần màu nền -> trong suốt (mềm mép).
    flatten_light: khử bóng/ánh sáng không đều (ảnh chụp giấy)."""
    bgr = bgra[:, :, :3].astype(np.float32)
    h, w = bgr.shape[:2]
    if flatten_light:
        # chia cho nền ước lượng (làm phẳng ánh sáng) – chỉ áp dụng khi nền sáng
        g = cv2.cvtColor(bgra[:, :, :3], cv2.COLOR_BGR2GRAY)
        k = max(15, (min(h, w) // 12) | 1)
        bg_est = cv2.medianBlur(cv2.dilate(g, np.ones((5, 5), np.uint8)), k if k % 2 else k + 1)
        if np.median(bg_est) > 140:
            ratio = 255.0 / np.maximum(bg_est.astype(np.float32), 1)
            bgr = np.clip(bgr * ratio[:, :, None], 0, 255)
    lab = cv2.cvtColor(bgr.astype(np.uint8), cv2.COLOR_BGR2LAB).astype(np.float32)
    border = np.concatenate([lab[0, :], lab[-1, :], lab[:, 0], lab[:, -1]])
    bg = np.median(border, axis=0)
    dist = np.sqrt(((lab - bg) ** 2).sum(axis=2))
    t0, t1 = float(threshold), float(threshold + soft)
    alpha = np.clip((dist - t0) / max(t1 - t0, 1), 0, 1)
    if edge_only:
        # chỉ xoá vùng nền nối liền với mép ảnh
        bgmask = (dist < t1).astype(np.uint8)
        n, lbl = cv2.connectedComponents(bgmask, connectivity=4)
        edge_lbls = set(np.unique(np.concatenate([lbl[0, :], lbl[-1, :], lbl[:, 0], lbl[:, -1]]))) - {0}
        keep = ~np.isin(lbl, list(edge_lbls))
        alpha = np.where(keep, 1.0, alpha)
    out = np.dstack([bgr.astype(np.uint8), (alpha * bgra[:, :, 3]).astype(np.uint8)])
    return out


def recolor(bgra, rgb):
    if rgb is None:
        return bgra
    out = bgra.copy()
    # giữ độ đậm nhạt: pixel càng tối càng đậm màu mực
    g = cv2.cvtColor(bgra[:, :, :3], cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
    strength = np.clip(1.15 - g, 0, 1)
    for c, v in zip((2, 1, 0), rgb):
        out[:, :, c] = (v * strength + 255 * (1 - strength)).clip(0, 255).astype(np.uint8)
    out[:, :, 3] = (bgra[:, :, 3].astype(np.float32) * np.clip(strength * 1.4, 0, 1)).astype(np.uint8)
    return out


def autocrop(bgra, pad=6):
    a = bgra[:, :, 3]
    ys, xs = np.where(a > 20)
    if len(xs) == 0:
        return bgra
    y0, y1 = max(0, ys.min() - pad), min(a.shape[0], ys.max() + pad + 1)
    x0, x1 = max(0, xs.min() - pad), min(a.shape[1], xs.max() + pad + 1)
    return bgra[y0:y1, x0:x1]


def to_qimage(bgra):
    rgba = cv2.cvtColor(bgra, cv2.COLOR_BGRA2RGBA)
    h, w = rgba.shape[:2]
    return QImage(rgba.data, w, h, w * 4, QImage.Format_RGBA8888).copy()


def png_bytes(bgra):
    ok, buf = cv2.imencode(".png", bgra)
    return buf.tobytes()


class ImageEditDialog(QDialog):
    """Xem trước trên nền ô caro; kết quả: self.result_png (PNG có kênh trong suốt)."""

    def __init__(self, parent, src, title="Chèn ảnh – tự xoá phông nền"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(980, 640)
        self.orig = load_any(src)
        # ảnh quá lớn -> thu về tối đa 2400 px để thao tác nhanh
        h, w = self.orig.shape[:2]
        s = 2400 / max(h, w)
        if s < 1:
            self.orig = cv2.resize(self.orig, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
        self.rot = 0
        self.history = []
        self.result_png = None
        self.result_size = None
        main = QHBoxLayout(self)
        self.view = QLabel()
        self.view.setAlignment(Qt.AlignCenter)
        self.view.setMinimumSize(560, 520)
        main.addWidget(self.view, 1)
        right = QVBoxLayout()
        main.addLayout(right)
        g = QGroupBox("Xoá phông nền")
        f = QFormLayout(g)
        self.on = QCheckBox("Tự xoá nền  (B)")
        self.on.setChecked(True)
        self.thr = QSlider(Qt.Horizontal, minimum=2, maximum=120, value=28)
        self.thr_lbl = QLabel("28")
        r = QHBoxLayout()
        r.addWidget(self.thr)
        r.addWidget(self.thr_lbl)
        self.edge = QCheckBox("Chỉ xoá nền nối từ mép ảnh  (E)")
        self.light = QCheckBox("Khử bóng / ánh sáng không đều")
        self.light.setChecked(True)
        f.addRow(self.on)
        f.addRow("Ngưỡng  ([ ]):", r)
        f.addRow(self.edge)
        f.addRow(self.light)
        right.addWidget(g)
        g2 = QGroupBox("Màu và khung")
        f2 = QFormLayout(g2)
        self.ink = QComboBox()
        self.ink.addItems(list(INK))
        self.crop = QCheckBox("Cắt sát nội dung  (C)")
        self.crop.setChecked(True)
        self.width_mm = QSpinBox(minimum=5, maximum=400, value=45, suffix=" mm")
        f2.addRow("Màu mực (1-4):", self.ink)
        f2.addRow(self.crop)
        f2.addRow("Rộng khi chèn:", self.width_mm)
        rb = QHBoxLayout()
        for t, a in (("⟲ Xoay (Shift+R)", -90), ("Xoay ⟳ (R)", 90)):
            b = QPushButton(t)
            b.clicked.connect(lambda _, a=a: self.rotate(a))
            rb.addWidget(b)
        f2.addRow(rb)
        right.addWidget(g2)
        keys = QLabel("<b>Phím tắt</b><br>B xoá nền · [ ] ngưỡng · E chỉ nền mép<br>C cắt sát · R / Shift+R xoay<br>"
                      "1-4 màu mực · S lưu vào thư viện<br>Ctrl+Z hoàn tác · Enter chèn · Esc huỷ")
        keys.setStyleSheet("color:#555;")
        right.addWidget(keys)
        right.addStretch()
        bs = QPushButton("Lưu vào thư viện con dấu (S)")
        bs.clicked.connect(self.save_library)
        right.addWidget(bs)
        bo = QPushButton("Chèn vào trang (Enter)")
        bo.setObjectName("primary")
        bo.clicked.connect(self.accept_insert)
        right.addWidget(bo)
        bc = QPushButton("Huỷ (Esc)")
        bc.clicked.connect(self.reject)
        right.addWidget(bc)
        self.timer = QTimer(self, singleShot=True, interval=60, timeout=self.update_preview)
        self.thr.valueChanged.connect(lambda v: (self.thr_lbl.setText(str(v)), self.timer.start()))
        for w in (self.on, self.edge, self.light, self.crop):
            w.toggled.connect(lambda *_: (self._push(), self.timer.start()))
        self.ink.currentIndexChanged.connect(lambda *_: (self._push(), self.timer.start()))
        self.thr.sliderReleased.connect(self._push)
        sc = [("B", lambda: self.on.toggle()), ("E", lambda: self.edge.toggle()), ("C", lambda: self.crop.toggle()),
              ("[", lambda: self.thr.setValue(self.thr.value() - 4)), ("-", lambda: self.thr.setValue(self.thr.value() - 4)),
              ("]", lambda: self.thr.setValue(self.thr.value() + 4)), ("+", lambda: self.thr.setValue(self.thr.value() + 4)),
              ("=", lambda: self.thr.setValue(self.thr.value() + 4)),
              ("R", lambda: self.rotate(90)), ("Shift+R", lambda: self.rotate(-90)), ("S", self.save_library),
              ("1", lambda: self.ink.setCurrentIndex(0)), ("2", lambda: self.ink.setCurrentIndex(1)),
              ("3", lambda: self.ink.setCurrentIndex(2)), ("4", lambda: self.ink.setCurrentIndex(3)),
              ("Return", self.accept_insert), ("Enter", self.accept_insert), ("Ctrl+Z", self.undo)]
        for k, fn in sc:
            QShortcut(QKeySequence(k), self, activated=fn)
        self._push()
        QTimer.singleShot(0, self.update_preview)

    # ------------------------------------------------------------- trạng thái
    def _state(self):
        return (self.on.isChecked(), self.thr.value(), self.edge.isChecked(), self.light.isChecked(),
                self.crop.isChecked(), self.ink.currentIndex(), self.rot)

    def _push(self):
        st = self._state()
        if not self.history or self.history[-1] != st:
            self.history.append(st)

    def undo(self):
        if len(self.history) < 2:
            return
        self.history.pop()
        on, thr, edge, light, crop, ink, rot = self.history[-1]
        for w in (self.on, self.thr, self.edge, self.light, self.crop, self.ink):
            w.blockSignals(True)
        self.on.setChecked(on)
        self.thr.setValue(thr)
        self.thr_lbl.setText(str(thr))
        self.edge.setChecked(edge)
        self.light.setChecked(light)
        self.crop.setChecked(crop)
        self.ink.setCurrentIndex(ink)
        self.rot = rot
        for w in (self.on, self.thr, self.edge, self.light, self.crop, self.ink):
            w.blockSignals(False)
        self.update_preview()

    def rotate(self, a):
        self.rot = (self.rot + a) % 360
        self._push()
        self.update_preview()

    def processed(self):
        img = self.orig
        if self.rot:
            img = np.ascontiguousarray(np.rot90(img, k=-(self.rot // 90) % 4))
        if self.on.isChecked():
            img = remove_background(img, self.thr.value(), 12, self.edge.isChecked(), self.light.isChecked())
        img = recolor(img, INK[self.ink.currentText()])
        if self.crop.isChecked():
            img = autocrop(img)
        return img

    def update_preview(self):
        img = self.processed()
        qi = to_qimage(img)
        W, H = self.view.width() - 10, self.view.height() - 10
        pm = QPixmap(W, H)
        p = QPainter(pm)
        cs = 12                                     # nền ô caro để thấy vùng trong suốt
        for y in range(0, H, cs):
            for x in range(0, W, cs):
                p.fillRect(x, y, cs, cs, QColor("#FFFFFF") if (x // cs + y // cs) % 2 else QColor("#D9D9D9"))
        sc = QPixmap.fromImage(qi).scaled(W - 20, H - 20, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        p.drawPixmap((W - sc.width()) // 2, (H - sc.height()) // 2, sc)
        p.end()
        self.view.setPixmap(pm)
        self.setWindowTitle(f"Chèn ảnh – tự xoá phông nền  ({img.shape[1]}×{img.shape[0]} px)")

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.timer.start()

    def save_library(self):
        d = os.path.join(user_dir(), "stamps")
        os.makedirs(d, exist_ok=True)
        n = len([f for f in os.listdir(d) if f.endswith(".png")]) + 1
        p = os.path.join(d, f"anh_xoa_nen_{n:03d}.png")
        with open(p, "wb") as f:
            f.write(png_bytes(self.processed()))
        QMessageBox.information(self, "Thư viện con dấu", f"Đã lưu: {p}\nDùng lại ở Ghi chú → Con dấu → Con dấu từ ảnh.")

    def accept_insert(self):
        img = self.processed()
        self.result_png = png_bytes(img)
        self.result_size = (img.shape[1], img.shape[0])
        self.accept()

    def insert_rect(self, x, y, rect=None):
        """Khung chèn (toạ độ trang, pt): theo khung kéo, hoặc theo bề rộng mm tại điểm bấm."""
        import pymupdf as fitz
        w_img, h_img = self.result_size
        if rect is not None and rect.width > 4 and rect.height > 4:
            return rect
        w = self.width_mm.value() * 72 / 25.4
        h = w * h_img / max(w_img, 1)
        return fitz.Rect(x - w / 2, y - h / 2, x + w / 2, y + h / 2)
