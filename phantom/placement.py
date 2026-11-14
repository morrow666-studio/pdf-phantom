"""Chế độ ĐẶT ẢNH tương tác trên trang (sau khi dán / chèn / sửa ảnh):

- Kéo bên trong ảnh: di chuyển.          - Kéo tay nắm góc: co giãn (giữ SHIFT = giữ đúng tỉ lệ).
- Kéo tay nắm tròn phía trên: xoay (giữ SHIFT = bước 15°).
- Phím ← → ↑ ↓: dịch 0,5 pt · Ctrl+mũi tên: 0,1 pt (nhỏ nhất) · Shift+mũi tên: 5 pt.
- [ ]: xoay -1° / +1° (Shift: 15°) · + -: phóng / thu 1% (Shift: 10%).
- Enter hoặc bấm đúp: hoàn tất · Esc: huỷ.
"""
import io
import math

import pymupdf as fitz
from PySide6.QtCore import Qt, QPointF, QRectF, QObject, Signal
from PySide6.QtGui import QPixmap, QPen, QColor, QBrush, QTransform, QImage
from PySide6.QtWidgets import QGraphicsPixmapItem, QGraphicsRectItem, QGraphicsEllipseItem, QGraphicsLineItem

HANDLE = 9


class Placement(QObject):
    changed = Signal()
    finished = Signal(bool)        # True = hoàn tất, False = huỷ

    def __init__(self, view, pno, png, rect, opacity=1.0):
        super().__init__(view)
        self.view, self.pno, self.png = view, pno, png
        self.qimg = QImage.fromData(png)
        r = fitz.Rect(rect)
        self.cx, self.cy = (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2
        self.w, self.h = max(r.width, 2), max(r.height, 2)
        self.ratio = self.w / self.h
        self.angle = 0.0
        self.opacity = opacity
        self.keep_ratio = False          # bật tạm khi giữ Shift, hoặc tích ô "Giữ tỉ lệ"
        self._drag = None
        sc = view.scene_
        self.item = QGraphicsPixmapItem(QPixmap.fromImage(self.qimg))
        self.item.setTransformationMode(Qt.SmoothTransformation)
        self.item.setZValue(50)
        sc.addItem(self.item)
        self.frame = QGraphicsRectItem()
        self.frame.setPen(QPen(QColor("#EF6C00"), 1.2, Qt.DashLine))
        self.frame.setZValue(51)
        sc.addItem(self.frame)
        self.handles = []
        for _ in range(4):
            hnd = QGraphicsRectItem(-HANDLE / 2, -HANDLE / 2, HANDLE, HANDLE)
            hnd.setBrush(QBrush(QColor("#FFFFFF")))
            hnd.setPen(QPen(QColor("#EF6C00"), 1.5))
            hnd.setZValue(52)
            sc.addItem(hnd)
            self.handles.append(hnd)
        self.rot_line = QGraphicsLineItem()
        self.rot_line.setPen(QPen(QColor("#EF6C00"), 1.2))
        self.rot_line.setZValue(51)
        sc.addItem(self.rot_line)
        self.rot = QGraphicsEllipseItem(-6, -6, 12, 12)
        self.rot.setBrush(QBrush(QColor("#EF6C00")))
        self.rot.setPen(QPen(QColor("#FFFFFF"), 1.5))
        self.rot.setZValue(52)
        sc.addItem(self.rot)
        self.update()

    # ------------------------------------------------------------- hình học
    def _page_item(self):
        return self.view.items[self.pno]

    def local_to_page(self, lx, ly):
        """Toạ độ cục bộ (tâm ảnh, chưa xoay) -> toạ độ trang."""
        a = math.radians(self.angle)
        return (self.cx + lx * math.cos(a) - ly * math.sin(a), self.cy + lx * math.sin(a) + ly * math.cos(a))

    def page_to_local(self, x, y):
        a = math.radians(self.angle)
        dx, dy = x - self.cx, y - self.cy
        return (dx * math.cos(a) + dy * math.sin(a), -dx * math.sin(a) + dy * math.cos(a))

    def corners(self):
        hw, hh = self.w / 2, self.h / 2
        return [self.local_to_page(sx * hw, sy * hh) for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]

    def rot_point(self):
        return self.local_to_page(0, -self.h / 2 - 22 / self.view.zoom)

    def update(self):
        v = self.view
        it = self._page_item()
        z = v.zoom
        tl = v.to_scene(it, QPointF(0, 0))
        t = QTransform()
        t.translate(tl.x() + self.cx * z, tl.y() + self.cy * z)
        t.rotate(self.angle)
        t.scale(self.w * z / max(self.qimg.width(), 1), self.h * z / max(self.qimg.height(), 1))
        t.translate(-self.qimg.width() / 2, -self.qimg.height() / 2)
        self.item.setTransform(t)
        self.item.setOpacity(self.opacity)
        ft = QTransform()
        ft.translate(tl.x() + self.cx * z, tl.y() + self.cy * z)
        ft.rotate(self.angle)
        self.frame.setRect(QRectF(-self.w * z / 2, -self.h * z / 2, self.w * z, self.h * z))
        self.frame.setTransform(ft)
        for hnd, (x, y) in zip(self.handles, self.corners()):
            hnd.setPos(v.to_scene(it, QPointF(x, y)))
        rx, ry = self.rot_point()
        tx, ty = self.local_to_page(0, -self.h / 2)
        self.rot.setPos(v.to_scene(it, QPointF(rx, ry)))
        self.rot_line.setLine(v.to_scene(it, QPointF(tx, ty)).x(), v.to_scene(it, QPointF(tx, ty)).y(),
                              v.to_scene(it, QPointF(rx, ry)).x(), v.to_scene(it, QPointF(rx, ry)).y())
        self.changed.emit()

    def remove(self):
        sc = self.view.scene_
        for g in [self.item, self.frame, self.rot, self.rot_line] + self.handles:
            try:
                sc.removeItem(g)
            except Exception:
                pass

    # ------------------------------------------------------------- tương tác
    def hit(self, pt):
        """pt: toạ độ trang. -> 'rot' | ('corner', i) | 'move' | None"""
        tol = 9 / self.view.zoom
        rx, ry = self.rot_point()
        if math.hypot(pt.x() - rx, pt.y() - ry) < tol * 1.2:
            return "rot"
        for i, (x, y) in enumerate(self.corners()):
            if math.hypot(pt.x() - x, pt.y() - y) < tol:
                return ("corner", i)
        lx, ly = self.page_to_local(pt.x(), pt.y())
        if abs(lx) <= self.w / 2 and abs(ly) <= self.h / 2:
            return "move"
        return None

    def cursor_for(self, pt):
        h = self.hit(pt)
        if h == "rot":
            return Qt.CrossCursor
        if isinstance(h, tuple):
            return Qt.SizeFDiagCursor if h[1] in (0, 2) else Qt.SizeBDiagCursor
        if h == "move":
            return Qt.SizeAllCursor
        return Qt.ArrowCursor

    def press(self, pt, mods):
        h = self.hit(pt)
        if h is None:
            return False
        self._drag = {"h": h, "start": (pt.x(), pt.y()), "state": (self.cx, self.cy, self.w, self.h, self.angle)}
        return True

    def move(self, pt, mods):
        d = self._drag
        if not d:
            return
        cx0, cy0, w0, h0, a0 = d["state"]
        sx, sy = d["start"]
        shift = bool(mods & Qt.ShiftModifier)
        if d["h"] == "move":
            self.cx, self.cy = cx0 + pt.x() - sx, cy0 + pt.y() - sy
        elif d["h"] == "rot":
            ang = math.degrees(math.atan2(pt.y() - cy0, pt.x() - cx0)) + 90
            if shift:
                ang = round(ang / 15.0) * 15.0
            self.angle = ((ang + 180) % 360) - 180
        else:
            i = d["h"][1]
            # góc đối diện đứng yên
            self.cx, self.cy, self.w, self.h, self.angle = cx0, cy0, w0, h0, a0
            opp = self.corners()[(i + 2) % 4]
            lx, ly = self.page_to_local(pt.x(), pt.y())
            ox, oy = self.page_to_local(*opp)
            nw, nh = max(abs(lx - ox), 3), max(abs(ly - oy), 3)
            if shift or self.keep_ratio:
                s = max(nw / w0, nh / h0)
                nw, nh = w0 * s, h0 * s
            sxg = 1 if lx >= ox else -1
            syg = 1 if ly >= oy else -1
            mx, my = ox + sxg * nw / 2, oy + syg * nh / 2
            self.cx, self.cy = self.local_to_page(mx, my)
            self.w, self.h = nw, nh
        self.update()

    def release(self):
        self._drag = None

    def nudge(self, dx, dy):
        self.cx += dx
        self.cy += dy
        self.update()

    def rotate_by(self, da):
        self.angle = ((self.angle + da + 180) % 360) - 180
        self.update()

    def scale_by(self, f):
        self.w *= f
        self.h *= f
        self.update()

    # ------------------------------------------------------------- hoàn tất
    def result(self):
        """-> (png đã xoay, khung bao trên trang)"""
        from PIL import Image
        im = Image.open(io.BytesIO(self.png)).convert("RGBA")
        # kích thước điểm ảnh theo tỉ lệ khung đặt (co giãn không đều được)
        px_w = max(8, im.width)
        px_h = max(8, int(round(px_w * self.h / self.w)))
        im = im.resize((px_w, px_h), Image.LANCZOS)
        if abs(self.angle) > 0.01:
            im = im.rotate(-self.angle, resample=Image.BICUBIC, expand=True)
        a = math.radians(self.angle)
        W = abs(self.w * math.cos(a)) + abs(self.h * math.sin(a))
        H = abs(self.w * math.sin(a)) + abs(self.h * math.cos(a))
        b = io.BytesIO()
        im.save(b, "PNG")
        return b.getvalue(), fitz.Rect(self.cx - W / 2, self.cy - H / 2, self.cx + W / 2, self.cy + H / 2)
