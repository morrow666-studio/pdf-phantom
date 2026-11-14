"""Khung hiển thị PDF: cuộn liên tục, phóng to mượt (render vùng nhìn thấy độ nét cao),
công cụ chuột cho ghi chú / chọn vùng / sửa chữ / chọn văn bản."""
import math

import pymupdf as fitz
from PySide6.QtCore import Qt, QRectF, QPointF, Signal, QTimer, QSizeF
from PySide6.QtGui import (QImage, QPixmap, QPainter, QColor, QPen, QBrush, QPainterPath,
                           QCursor, QKeySequence, QGuiApplication)  # noqa
from PySide6.QtWidgets import (QGraphicsView, QGraphicsScene, QGraphicsItem, QGraphicsRectItem,
                               QGraphicsPathItem, QGraphicsLineItem, QMenu, QApplication)

GAP = 14
IMG_DROP = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tif", ".tiff")
MAX_BASE_PX = 1600          # ảnh nền toàn trang tối đa (px cạnh dài)
RECT_TOOLS = {"text", "rect", "ellipse", "whiteout", "redact", "region", "crop", "sign_area",
              "image", "stamp", "symbol", "highlight", "underline", "strike", "squiggly", "select_text"}
LINE_TOOLS = {"line", "arrow", "measure"}
POLY_TOOLS = {"polygon", "cloud", "polyline"}
CLICK_TOOLS = {"note", "edittext", "addtext"}


def pix_to_qimage(pix):
    fmt = QImage.Format_RGBA8888 if pix.alpha else QImage.Format_RGB888
    return QImage(pix.samples, pix.width, pix.height, pix.stride, fmt).copy()


class PageItem(QGraphicsItem):
    def __init__(self, view, pno):
        super().__init__()
        self.view = view
        self.pno = pno
        self.w = self.h = 100.0          # kích thước trang (pt, đã xoay)
        self.base = None                 # QPixmap toàn trang (độ phân giải vừa)
        self.base_zoom = 0
        self.hi = None                   # (QRectF scene-local, QPixmap) vùng nét cao
        self.overlays = []               # [(QRectF local, QColor)] kết quả tìm kiếm, chọn chữ
        self.setFlag(QGraphicsItem.ItemUsesExtendedStyleOption, True)

    def boundingRect(self):
        z = self.view.zoom
        return QRectF(-4, -4, self.w * z + 10, self.h * z + 10)

    def page_rect(self):
        z = self.view.zoom
        return QRectF(0, 0, self.w * z, self.h * z)

    def paint(self, p, opt, widget=None):
        r = self.page_rect()
        p.fillRect(r.translated(3, 3), QColor(0, 0, 0, 60))
        p.fillRect(r, Qt.white)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        if self.base is not None:
            p.drawPixmap(r, self.base, QRectF(self.base.rect()))
        else:
            p.setPen(QColor("#9E9E9E"))
            p.drawText(r, Qt.AlignCenter, "Đang hiển thị trang…")
        if self.hi is not None:
            hr, hp = self.hi
            z = self.view.zoom
            target = QRectF(hr.x() * z, hr.y() * z, hr.width() * z, hr.height() * z)
            p.drawPixmap(target, hp, QRectF(hp.rect()))
        z = self.view.zoom
        for rr, col in self.overlays:
            p.fillRect(QRectF(rr.x() * z, rr.y() * z, rr.width() * z, rr.height() * z), col)
        if self.view.current_page == self.pno and self.view.show_current_frame:
            p.setPen(QPen(QColor(239, 108, 0, 120), 2))
            p.drawRect(r.adjusted(-1, -1, 1, 1))


class DocView(QGraphicsView):
    pageChanged = Signal(int)
    zoomChanged = Signal(float)
    toolFinished = Signal(str, int, object)        # tool, page, data
    annotSelected = Signal(object)                 # (pno, xref) | None
    annotEditRequest = Signal(int, int)            # pno, xref
    stampEditRequest = Signal(int, int)            # bấm đúp ảnh/con dấu -> xoay, co giãn
    stampCopyRequest = Signal(int, int)            # Ctrl+C trên ảnh đang chọn
    stampDupRequest = Signal(int, int)             # nhân bản sang trang / file khác
    stampGroupDeleteRequest = Signal(int, int)     # xoá ảnh ở mọi trang cùng nhóm
    annotMoved = Signal(int, int, object)          # pno, xref, new rect (visible coords)
    annotDeleteRequest = Signal(int, int)
    contextAction = Signal(str, object)            # action, payload
    textSelected = Signal(str)
    signatureClicked = Signal(str)
    placementStarted = Signal(object)
    placementFinished = Signal(bool)
    pasteRequest = Signal(object)                  # vị trí chuột (toạ độ viewport)
    imageDropped = Signal(int, object, str)        # trang, điểm, đường dẫn ảnh
    filesDropped = Signal(list)

    def __init__(self, pdfdoc, parent=None):
        super().__init__(parent)
        self.pdf = pdfdoc
        self.scene_ = QGraphicsScene(self)
        self.setScene(self.scene_)
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setViewportUpdateMode(QGraphicsView.SmartViewportUpdate)
        self.setTransformationAnchor(QGraphicsView.NoAnchor)
        self.setDragMode(QGraphicsView.NoDrag)
        self.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self.zoom = 1.0
        self.fit_mode = "width"          # 'width' | 'page' | None
        self.items = []
        self.current_page = 0
        self.show_current_frame = False
        self.tool = "select"
        self.tool_opts = {}
        self._drag = None
        self._preview = None
        self._poly_pts = []
        self.selected = None             # (pno, xref)
        self._sel_item = None
        self.selected_text = ""
        self.search_hits = []
        self.render_timer = QTimer(self, singleShot=True, interval=40, timeout=self.render_visible)
        self._pan = None                 # (điểm bắt đầu, giá trị thanh cuộn)
        self._space = False
        self._key_hold = {}              # phím -> (thời điểm nhấn, đã kích hoạt)
        from PySide6.QtCore import QElapsedTimer
        self._clock = QElapsedTimer()
        self._clock.start()
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAcceptDrops(True)
        self.verticalScrollBar().setSingleStep(40)
        self.horizontalScrollBar().setSingleStep(40)
        self.verticalScrollBar().valueChanged.connect(self._on_scroll)
        self.horizontalScrollBar().valueChanged.connect(lambda *_: self.render_timer.start())
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)      # nhận di chuột khi không bấm -> hiện thông tin khi rê chuột
        self._sig_frame = None
        self.placement = None
        self._place_cb = None
        self.build()

    # ------------------------------------------------------------- dựng cảnh
    def build(self, keep_pos=True):
        cur = self.current_page
        self.scene_.clear()
        self._preview = None
        self._sel_item = None
        self.items = []
        for i in range(self.pdf.page_count):
            it = PageItem(self, i)
            r = self.pdf[i].rect
            it.w, it.h = r.width, r.height
            self.scene_.addItem(it)
            self.items.append(it)
        self.layout_pages()
        if self.fit_mode:
            QTimer.singleShot(0, self.apply_fit)
        if keep_pos:
            QTimer.singleShot(0, lambda: self.goto(min(cur, self.pdf.page_count - 1)))
        self.render_timer.start()

    def layout_pages(self):
        z = self.zoom
        maxw = max((it.w for it in self.items), default=600) * z
        y = GAP
        for it in self.items:
            it.prepareGeometryChange()
            it.setPos((maxw - it.w * z) / 2 + GAP, y)
            y += it.h * z + GAP
        self.scene_.setSceneRect(0, 0, maxw + 2 * GAP, y)
        self._update_selection_frame()
        if getattr(self, "placement", None) is not None:
            self.placement.update()

    def refresh(self, kind="content", pages=None):
        if kind in ("pages", "reload") or len(self.items) != self.pdf.page_count:
            self.build()
            return
        for it in self.items:
            if pages is None or it.pno in pages:
                r = self.pdf[it.pno].rect
                if (r.width, r.height) != (it.w, it.h):
                    it.w, it.h = r.width, r.height
                    self.layout_pages()
                it.base = None
                it.hi = None
                it.update()
        self._update_selection_frame()
        self.render_visible()

    # --------------------------------------------------------------- zoom
    @property
    def unit(self):
        """Hệ số để 100% = đúng kích thước thật trên màn hình (1:1)."""
        return max(0.5, self.logicalDpiX() / 72.0)

    def set_zoom(self, z, anchor=None, fit=None):
        z = max(0.05, min(z, 24.0))
        self.fit_mode = fit
        if abs(z - self.zoom) < 1e-4:
            return
        vp = self.viewport().rect()
        anchor = QPointF(anchor) if anchor is not None else QPointF(vp.width() / 2, vp.height() / 2)
        # điểm trên trang đang nằm dưới con trỏ -> giữ nguyên dưới con trỏ sau khi phóng
        it, pt = self.page_at(anchor.toPoint())
        scene_pt = self.mapToScene(anchor.toPoint())
        old = self.zoom
        self.zoom = z
        for i in self.items:
            i.hi = None
        self.layout_pages()
        if it is not None:
            new_scene = self.to_scene(it, pt)
        else:
            f = z / old
            new_scene = QPointF(scene_pt.x() * f, scene_pt.y() * f)
        # căn lại bằng cách tính offset thực tế giữa scene và viewport
        cur = self.mapFromScene(new_scene)
        self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() + int(round(cur.x() - anchor.x())))
        self.verticalScrollBar().setValue(self.verticalScrollBar().value() + int(round(cur.y() - anchor.y())))
        self.zoomChanged.emit(z)
        self.viewport().update()
        self.render_timer.start()

    # ------------------------------------------------------------- đặt ảnh tương tác
    def start_placement(self, pno, png, rect, on_done, opacity=1.0):
        """on_done(ok: bool, png, rect, opacity) được gọi khi Enter / Esc."""
        from .placement import Placement
        if self.placement is not None:
            self.finish_placement(False)
        self.placement = Placement(self, pno, png, rect, opacity)
        self._place_cb = on_done
        self.setFocus()
        self.placementStarted.emit(self.placement)
        return self.placement

    def finish_placement(self, ok=True):
        pl = self.placement
        if pl is None:
            return
        self.placement = None
        cb, self._place_cb = self._place_cb, None
        png, rect = pl.result() if ok else (None, None)
        opacity = pl.opacity
        pno = pl.pno
        pl.remove()
        self.placementFinished.emit(ok)
        if cb:
            cb(ok, pno, png, rect, opacity)

    def zoom_actual(self, anchor=None):
        """Tỉ lệ 1:1 (100% kích thước thật)."""
        self.set_zoom(self.unit, anchor)

    def toggle_actual(self):
        """Giữ phím ↑/↓: 1:1 <-> vừa trang."""
        if abs(self.zoom - self.unit) / self.unit < 0.02:
            self.fit_mode = "page"
            self.apply_fit()
        else:
            pno = self.current_page
            self.zoom_actual()
            # đưa đầu trang hiện tại lên màn hình
            it = self.items[pno]
            x = self.to_scene(it, QPointF(it.w / 2, 0)).x()
            self.centerOn(x, self.mapToScene(self.viewport().rect().center()).y())
            self.goto(pno)

    def zoom_to_rect(self, it, rect):
        """Phóng vừa khung chọn (kính lúp)."""
        vp = self.viewport().rect()
        z = min(vp.width() / max(rect.width(), 5), vp.height() / max(rect.height(), 5)) * 0.95
        self.set_zoom(z)
        c = self.to_scene(it, rect.center())
        self.centerOn(c)
        self.render_timer.start()

    def apply_fit(self):
        if not self.items:
            return
        vp = self.viewport().width() - 2 * GAP - 4
        vh = self.viewport().height() - 2 * GAP
        it = self.items[min(self.current_page, len(self.items) - 1)]
        if self.fit_mode == "width":
            maxw = max(i.w for i in self.items)
            self.set_zoom(vp / maxw, fit="width")
        elif self.fit_mode == "page":
            self.set_zoom(min(vp / it.w, vh / it.h), fit="page")
            self.goto(self.current_page)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.fit_mode:
            self.apply_fit()
        self.render_timer.start()

    def wheelEvent(self, e):
        dy = e.angleDelta().y() or e.angleDelta().x()
        if e.modifiers() & Qt.ControlModifier:
            f = 1.0016 ** dy                    # 1 nấc chuột (120) ~ 21%; touchpad mượt
            self.set_zoom(self.zoom * f, anchor=e.position())
            return
        if e.modifiers() & Qt.ShiftModifier:
            sb = self.horizontalScrollBar()
            sb.setValue(sb.value() - int(dy * 0.8))
            return
        super().wheelEvent(e)

    # ------------------------------------------------------------ điều hướng
    def goto(self, pno, y_pt=None):
        if not self.items:
            return
        pno = max(0, min(pno, len(self.items) - 1))
        it = self.items[pno]
        y = it.pos().y() - GAP / 2 + (y_pt * self.zoom if y_pt else 0)
        self.verticalScrollBar().setValue(int(y))
        self._set_current(pno)

    def _on_scroll(self, *_):
        self.render_timer.start()
        if not self.items:
            return
        center = self.mapToScene(self.viewport().rect().center()).y()
        top = self.mapToScene(0, 0).y()
        probe = top + (center - top) * 0.6
        for it in self.items:
            y0 = it.pos().y()
            if y0 <= probe <= y0 + it.h * self.zoom + GAP:
                self._set_current(it.pno)
                break

    def _set_current(self, pno):
        if pno != self.current_page:
            old = self.current_page
            self.current_page = pno
            if old < len(self.items):
                self.items[old].update()
            self.items[pno].update()
            self.pageChanged.emit(pno)

    # ------------------------------------------------------------- render
    def visible_items(self):
        rect = self.mapToScene(self.viewport().rect()).boundingRect()
        out = []
        for it in self.items:
            r = QRectF(it.pos(), QSizeF(it.w * self.zoom, it.h * self.zoom))
            if r.intersects(rect):
                out.append((it, r.intersected(rect)))
        return out

    def render_visible(self):
        dpr = self.devicePixelRatioF()
        vis = self.visible_items()
        # render trước 1 trang trên/dưới để cuộn mượt
        idx = [it.pno for it, _ in vis]
        extra = []
        if idx:
            for p in (min(idx) - 1, max(idx) + 1):
                if 0 <= p < len(self.items):
                    extra.append(self.items[p])
        for it, vrect in vis:
            self._render_base(it)
            self._render_hi(it, vrect, dpr)
        for it in extra:
            self._render_base(it)

    def _render_base(self, it):
        import time as _t
        z = self.zoom * self.devicePixelRatioF()
        target = min(z, MAX_BASE_PX / max(it.w, it.h))
        if it.base is not None and abs(it.base_zoom - target) / target < 0.25:
            return
        heavy = getattr(it, "heavy", False)
        if it.base is None and heavy:
            # trang nặng: hiện bản thô trước cho nhanh
            target_q = min(target, 700 / max(it.w, it.h))
            if target_q < target * 0.9:
                self._do_render_base(it, target_q)
                self.render_timer.start()
                return
        t0 = _t.time()
        busy = heavy
        if busy:
            QGuiApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self._do_render_base(it, target)
        finally:
            if busy:
                QGuiApplication.restoreOverrideCursor()
        if _t.time() - t0 > 0.6:
            it.heavy = True                      # lần sau: vẽ thô trước, hạn chế vẽ nét

    def _do_render_base(self, it, target):
        try:
            page = self.pdf[it.pno]
            pix = page.get_pixmap(matrix=fitz.Matrix(target, target), annots=True)
            it.base = QPixmap.fromImage(pix_to_qimage(pix))
            it.base_zoom = target
            it.update()
        except Exception:
            pass

    def _render_hi(self, it, vrect, dpr):
        z = self.zoom * dpr
        if getattr(it, "heavy", False) and it.base is not None and it.base_zoom >= z * 0.7:
            it.hi = None
            return
        if it.base is not None and it.base_zoom >= z * 0.98:
            it.hi = None
            return
        # vùng hiển thị (toạ độ trang, pt) + biên 25%
        loc = QRectF(vrect.x() - it.pos().x(), vrect.y() - it.pos().y(), vrect.width(), vrect.height())
        r = fitz.Rect(loc.x() / self.zoom, loc.y() / self.zoom, loc.right() / self.zoom, loc.bottom() / self.zoom)
        mx, my = r.width * 0.25, r.height * 0.25
        r = fitz.Rect(r.x0 - mx, r.y0 - my, r.x1 + mx, r.y1 + my) & fitz.Rect(0, 0, it.w, it.h)
        if it.hi is not None:
            hr, _ = it.hi
            if hr.contains(QRectF(loc.x() / self.zoom, loc.y() / self.zoom, loc.width() / self.zoom,
                                  loc.height() / self.zoom)) and getattr(it, "hi_zoom", 0) == z:
                return
        try:
            page = self.pdf[it.pno]
            clip = (r * page.derotation_matrix).normalize() if page.rotation else r
            # render theo trang đã xoay: dùng clip trên toạ độ hiển thị
            pix = page.get_pixmap(matrix=fitz.Matrix(z, z), clip=_unrot_clip(page, r), annots=True)
            it.hi = (QRectF(r.x0, r.y0, r.width, r.height), QPixmap.fromImage(pix_to_qimage(pix)))
            it.hi_zoom = z
            it.update()
        except Exception:
            it.hi = None

    # ----------------------------------------------------------- toạ độ
    def page_at(self, view_pos):
        sp = self.mapToScene(view_pos)
        for it in self.items:
            r = QRectF(it.pos(), QSizeF(it.w * self.zoom, it.h * self.zoom))
            if r.contains(sp):
                return it, QPointF((sp.x() - it.pos().x()) / self.zoom, (sp.y() - it.pos().y()) / self.zoom)
        return None, None

    def page_point(self, it, view_pos):
        sp = self.mapToScene(view_pos)
        x = (sp.x() - it.pos().x()) / self.zoom
        y = (sp.y() - it.pos().y()) / self.zoom
        return QPointF(max(0, min(x, it.w)), max(0, min(y, it.h)))

    def to_scene(self, it, pt):
        return QPointF(it.pos().x() + pt.x() * self.zoom, it.pos().y() + pt.y() * self.zoom)

    # ------------------------------------------------------------- công cụ
    def set_tool(self, tool, **opts):
        self.cancel_poly()
        self.tool = tool
        self.tool_opts = opts
        self.setDragMode(QGraphicsView.NoDrag)
        self.viewport().setCursor(self._tool_cursor())

    def _tool_cursor(self):
        if self.tool == "hand":
            return Qt.OpenHandCursor
        if self.tool == "zoom":
            from PySide6.QtGui import QCursor
            return Qt.CrossCursor
        return {"select": Qt.ArrowCursor, "edittext": Qt.IBeamCursor, "addtext": Qt.IBeamCursor,
                "select_text": Qt.IBeamCursor, "note": Qt.PointingHandCursor}.get(self.tool, Qt.CrossCursor)

    def cancel_poly(self):
        self._poly_pts = []
        self._clear_preview()

    def _clear_preview(self):
        if self._preview is not None:
            try:
                self.scene_.removeItem(self._preview)
            except Exception:
                pass
            self._preview = None

    def _pen(self):
        c = QColor(self.tool_opts.get("color", "#E53935"))
        pen = QPen(c, max(1.0, self.tool_opts.get("width", 1.5) * self.zoom))
        pen.setCosmetic(False)
        return pen

    def _start_pan(self, e):
        self._pan = (e.position(), self.horizontalScrollBar().value(), self.verticalScrollBar().value())
        self.viewport().setCursor(Qt.ClosedHandCursor)

    def mousePressEvent(self, e):
        self.setFocus()
        if e.button() == Qt.MiddleButton or (e.button() == Qt.LeftButton and (self._space or self.tool == "hand")):
            self._start_pan(e)
            return
        if self.placement is not None and e.button() == Qt.LeftButton:
            it = self.items[self.placement.pno]
            pt = self.page_point(it, e.position().toPoint())
            raw = QPointF((self.mapToScene(e.position().toPoint()).x() - it.pos().x()) / self.zoom,
                          (self.mapToScene(e.position().toPoint()).y() - it.pos().y()) / self.zoom)
            if not self.placement.press(raw, e.modifiers()):
                self.finish_placement(True)              # bấm ra ngoài ảnh = hoàn tất
            return
        if self.tool == "zoom" and e.button() in (Qt.LeftButton, Qt.RightButton):
            it, pt = self.page_at(e.position().toPoint())
            out = e.button() == Qt.RightButton or bool(e.modifiers() & Qt.AltModifier)
            if out:
                self.set_zoom(self.zoom / 1.5, anchor=e.position())
                return
            if it is not None:
                self._drag = {"mode": "zoombox", "it": it, "start": pt, "pos": e.position()}
            return
        if e.button() == Qt.RightButton:
            return super().mousePressEvent(e)
        it, pt = self.page_at(e.position().toPoint())
        if it is None:
            self.select_annot(None)
            return super().mousePressEvent(e)
        self._set_current(it.pno)
        tool = self.tool
        if tool == "select" and e.button() == Qt.LeftButton:
            sh = self.sig_at(e.position().toPoint())
            if sh is not None:
                self.signatureClicked.emit(sh[2])
                return
        if tool == "select":
            hit = self.annot_at(it, pt)
            if hit is not None:
                self.select_annot((it.pno, hit[0]))
                self._drag = {"mode": "move", "it": it, "start": pt, "rect": hit[1],
                              "resize": _near_corner(hit[1], pt, 8 / self.zoom)}
                return
            self.select_annot(None)
            self._drag = {"mode": "seltext", "it": it, "start": pt}
            self._clear_text_selection()
            return
        if tool in CLICK_TOOLS:
            self.toolFinished.emit(tool, it.pno, {"point": (pt.x(), pt.y())})
            return
        if tool in POLY_TOOLS:
            if self._poly_pts and self._poly_pts[0][0] != it.pno:
                self.cancel_poly()
            self._poly_pts.append((it.pno, pt))
            self._update_poly_preview(it, pt)
            return
        if tool == "ink":
            path = QPainterPath(self.to_scene(it, pt))
            self._preview = self.scene_.addPath(path, self._pen())
            self._drag = {"mode": "ink", "it": it, "pts": [pt], "strokes": self.tool_opts.get("_strokes", [])}
            return
        self._drag = {"mode": "draw", "it": it, "start": pt}

    def mouseMoveEvent(self, e):
        if self._pan is not None:
            p0, h0, v0 = self._pan
            d = e.position() - p0
            self.horizontalScrollBar().setValue(int(h0 - d.x()))
            self.verticalScrollBar().setValue(int(v0 - d.y()))
            return
        if self.placement is not None:
            it = self.items[self.placement.pno]
            sp = self.mapToScene(e.position().toPoint())
            raw = QPointF((sp.x() - it.pos().x()) / self.zoom, (sp.y() - it.pos().y()) / self.zoom)
            if self.placement._drag:
                self.placement.move(raw, QGuiApplication.keyboardModifiers())
            else:
                self.viewport().setCursor(self.placement.cursor_for(raw))
            return
        d = self._drag
        if d is None and self._sig_hover(e):
            return super().mouseMoveEvent(e)
        if d is None:
            if self.tool in POLY_TOOLS and self._poly_pts:
                pno = self._poly_pts[0][0]
                it = self.items[pno]
                self._update_poly_preview(it, self.page_point(it, e.position().toPoint()))
            elif self.tool == "select":
                it, pt = self.page_at(e.position().toPoint())
                cur = Qt.ArrowCursor
                if it is not None:
                    hit = self.annot_at(it, pt)
                    if hit is not None:
                        cur = Qt.SizeFDiagCursor if _near_corner(hit[1], pt, 8 / self.zoom) else Qt.SizeAllCursor
                        self._annot_tip(it.pno, hit[0], e)
                    else:
                        from PySide6.QtWidgets import QToolTip
                        QToolTip.hideText()
                        if self._has_text_at(it, pt):
                            cur = Qt.IBeamCursor
                self.viewport().setCursor(cur)
            return super().mouseMoveEvent(e)
        it = d["it"]
        pt = self.page_point(it, e.position().toPoint())
        if d["mode"] == "ink":
            d["pts"].append(pt)
            path = QPainterPath(self.to_scene(it, d["pts"][0]))
            for p in d["pts"][1:]:
                path.lineTo(self.to_scene(it, p))
            self._preview.setPath(path)
            return
        a = self.to_scene(it, d["start"])
        b = self.to_scene(it, pt)
        self._clear_preview()
        if d["mode"] == "move":
            r = d["rect"]
            dx, dy = pt.x() - d["start"].x(), pt.y() - d["start"].y()
            if d["resize"]:
                nr = QRectF(r.x0, r.y0, max(5, r.width + dx), max(5, r.height + dy))
            else:
                nr = QRectF(r.x0 + dx, r.y0 + dy, r.width, r.height)
            sr = QRectF(self.to_scene(it, nr.topLeft()), self.to_scene(it, nr.bottomRight()))
            self._preview = self.scene_.addRect(sr, QPen(QColor("#EF6C00"), 1.5, Qt.DashLine))
            d["new"] = nr
            return
        if d["mode"] == "zoombox":
            self._preview = self.scene_.addRect(QRectF(a, b).normalized(), QPen(QColor("#EF6C00"), 1.5, Qt.DashLine),
                                                QBrush(QColor(239, 108, 0, 25)))
            return
        if d["mode"] == "seltext":
            self._preview = self.scene_.addRect(QRectF(a, b).normalized(), QPen(QColor(30, 120, 255, 150), 1),
                                                QBrush(QColor(30, 120, 255, 30)))
            return
        if self.tool in LINE_TOOLS:
            self._preview = self.scene_.addLine(a.x(), a.y(), b.x(), b.y(), self._pen())
            if self.tool == "measure":
                from PySide6.QtWidgets import QGraphicsSimpleTextItem
                dist = math.hypot(pt.x() - d["start"].x(), pt.y() - d["start"].y())
                txt = self.tool_opts.get("fmt", lambda v: f"{v:.1f}")(dist)
                ti = QGraphicsSimpleTextItem(txt, self._preview)
                ti.setBrush(QColor("#E53935"))
                ti.setPos((a + b) / 2)
            return
        pen = self._pen()
        rect = QRectF(a, b).normalized()
        if self.tool == "ellipse":
            self._preview = self.scene_.addEllipse(rect, pen)
        elif self.tool in ("highlight", "underline", "strike", "squiggly", "select_text"):
            self._preview = self.scene_.addRect(rect, QPen(QColor(255, 180, 0), 1), QBrush(QColor(255, 220, 0, 60)))
        elif self.tool == "whiteout":
            self._preview = self.scene_.addRect(rect, QPen(QColor("#999"), 1, Qt.DashLine), QBrush(Qt.white))
        elif self.tool == "redact":
            self._preview = self.scene_.addRect(rect, QPen(Qt.red, 1), QBrush(QColor(0, 0, 0, 140)))
        else:
            if self.tool in ("region", "crop", "sign_area", "stamp", "image", "symbol", "text"):
                pen = QPen(QColor("#EF6C00"), 1.5, Qt.DashLine)
            self._preview = self.scene_.addRect(rect, pen)

    def mouseReleaseEvent(self, e):
        if self.placement is not None and self._pan is None:
            self.placement.release()
            return
        if self._pan is not None:
            self._pan = None
            self.viewport().setCursor(Qt.OpenHandCursor if (self._space or self.tool == "hand") else
                                      self._tool_cursor())
            return
        d = self._drag
        self._drag = None
        if d is not None and d.get("mode") == "zoombox":
            self._clear_preview()
            it = d["it"]
            pt = self.page_point(it, e.position().toPoint())
            s0 = d["start"]
            r = QRectF(s0, pt).normalized()
            if r.width() < 6 and r.height() < 6:
                self.set_zoom(self.zoom * 1.5, anchor=e.position())
            else:
                self.zoom_to_rect(it, r)
            return
        if d is None:
            return super().mouseReleaseEvent(e)
        it = d["it"]
        pt = self.page_point(it, e.position().toPoint())
        if d["mode"] == "ink":
            pts = [(p.x(), p.y()) for p in d["pts"]]
            self._clear_preview()
            if len(pts) > 1:
                self.toolFinished.emit("ink", it.pno, {"points": [pts]})
            return
        self._clear_preview()
        if d["mode"] == "move":
            if "new" in d and self.selected:
                nr = d["new"]
                self.annotMoved.emit(self.selected[0], self.selected[1],
                                     fitz.Rect(nr.left(), nr.top(), nr.right(), nr.bottom()))
            return
        s = d["start"]
        rect = fitz.Rect(min(s.x(), pt.x()), min(s.y(), pt.y()), max(s.x(), pt.x()), max(s.y(), pt.y()))
        if d["mode"] == "seltext":
            if rect.width > 2 or rect.height > 2:
                self.select_text(it.pno, rect)
            return
        if self.tool in LINE_TOOLS:
            if rect.width + rect.height < 3:
                return
            self.toolFinished.emit(self.tool, it.pno, {"p1": (s.x(), s.y()), "p2": (pt.x(), pt.y())})
            return
        tiny = rect.width < 4 and rect.height < 4
        if tiny:
            if self.tool in ("text", "stamp", "image", "symbol", "sign_area"):
                w, h = self.tool_opts.get("default_size", (160, 40))
                rect = fitz.Rect(s.x(), s.y(), s.x() + w, s.y() + h)
            else:
                return
        self.toolFinished.emit(self.tool, it.pno, {"rect": rect})

    def mouseDoubleClickEvent(self, e):
        if self.placement is not None:
            self.finish_placement(True)
            return
        if self.tool in POLY_TOOLS and len(self._poly_pts) >= 2:
            pno = self._poly_pts[0][0]
            pts = [(p.x(), p.y()) for _, p in self._poly_pts]
            # bỏ điểm trùng do double-click
            if len(pts) > 2 and abs(pts[-1][0] - pts[-2][0]) < 2 and abs(pts[-1][1] - pts[-2][1]) < 2:
                pts.pop()
            self.cancel_poly()
            self.toolFinished.emit(self.tool, pno, {"points": pts})
            return
        if self.tool == "select":
            it, pt = self.page_at(e.position().toPoint())
            if it is not None:
                hit = self.annot_at(it, pt)
                if hit is not None:
                    is_stamp = self._sel_is_stamp((it.pno, hit[0]))
                    (self.stampEditRequest if is_stamp else self.annotEditRequest).emit(it.pno, hit[0])
                    return
                # double-click chữ -> chọn từ
                w = self._word_at(it, pt)
                if w:
                    self.select_text(it.pno, fitz.Rect(w[:4]))
        super().mouseDoubleClickEvent(e)

    def _update_poly_preview(self, it, cur):
        self._clear_preview()
        pts = [p for _, p in self._poly_pts] + [cur]
        path = QPainterPath(self.to_scene(it, pts[0]))
        for p in pts[1:]:
            path.lineTo(self.to_scene(it, p))
        self._preview = self.scene_.addPath(path, self._pen())

    HOLD_MS = 450

    def keyPressEvent(self, e):
        k = e.key()
        mods = e.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier | Qt.AltModifier)
        pl = self.placement
        if pl is not None:
            step = 0.1 if mods & Qt.ControlModifier else (5.0 if mods & Qt.ShiftModifier else 0.5)
            moves = {Qt.Key_Left: (-step, 0), Qt.Key_Right: (step, 0), Qt.Key_Up: (0, -step), Qt.Key_Down: (0, step)}
            if k in moves:
                pl.nudge(*moves[k])
                return
            big = bool(mods & Qt.ShiftModifier)
            if k == Qt.Key_BracketLeft:
                pl.rotate_by(-15 if big else -1)
                return
            if k == Qt.Key_BracketRight:
                pl.rotate_by(15 if big else 1)
                return
            if k in (Qt.Key_Plus, Qt.Key_Equal):
                pl.scale_by(1.10 if big else 1.01)
                return
            if k == Qt.Key_Minus:
                pl.scale_by(1 / 1.10 if big else 1 / 1.01)
                return
            if k in (Qt.Key_Return, Qt.Key_Enter):
                self.finish_placement(True)
                return
            if k in (Qt.Key_Escape, Qt.Key_Delete):
                self.finish_placement(False)
                return
        if k == Qt.Key_Space and not e.isAutoRepeat() and self._pan is None:
            self._space = True
            self.viewport().setCursor(Qt.OpenHandCursor)
            return
        if k == Qt.Key_Space:
            return
        if not mods and k in (Qt.Key_Left, Qt.Key_Right):
            self.goto(self.current_page + (1 if k == Qt.Key_Right else -1))
            return
        if not mods and k in (Qt.Key_Up, Qt.Key_Down):
            st = self._key_hold.get(k)
            if not e.isAutoRepeat() or st is None:
                self._key_hold[k] = [self._clock.elapsed(), False]
            else:
                if not st[1] and self._clock.elapsed() - st[0] >= self.HOLD_MS:
                    st[1] = True
                    self.toggle_actual()
                if st[1]:
                    return
            sb = self.verticalScrollBar()
            sb.setValue(sb.value() + (60 if k == Qt.Key_Down else -60))
            return
        if e.matches(QKeySequence.Paste):
            self.pasteRequest.emit(self.mapFromGlobal(QCursor.pos()))
            return
        if mods == Qt.ControlModifier and k == Qt.Key_1:
            self.zoom_actual()
            return
        if e.key() == Qt.Key_Escape:
            self.cancel_poly()
            self.select_annot(None)
            self._clear_text_selection()
            return
        if e.key() in (Qt.Key_Delete, Qt.Key_Backspace) and self.selected:
            self.annotDeleteRequest.emit(*self.selected)
            return
        if e.matches(QKeySequence.Copy) and self.selected and self._sel_is_stamp():
            self.stampCopyRequest.emit(*self.selected)
            return
        if e.matches(QKeySequence.Copy) and self.selected_text:
            QGuiApplication.clipboard().setText(self.selected_text)
            return
        if e.key() in (Qt.Key_Return, Qt.Key_Enter) and self.tool in POLY_TOOLS and len(self._poly_pts) >= 2:
            pno = self._poly_pts[0][0]
            pts = [(p.x(), p.y()) for _, p in self._poly_pts]
            self.cancel_poly()
            self.toolFinished.emit(self.tool, pno, {"points": pts})
            return
        if e.key() == Qt.Key_PageDown:
            self.goto(self.current_page + 1)
            return
        if e.key() == Qt.Key_PageUp:
            self.goto(self.current_page - 1)
            return
        if e.key() == Qt.Key_Home and e.modifiers() & Qt.ControlModifier:
            self.goto(0)
            return
        if e.key() == Qt.Key_End and e.modifiers() & Qt.ControlModifier:
            self.goto(len(self.items) - 1)
            return
        super().keyPressEvent(e)


    def keyReleaseEvent(self, e):
        k = e.key()
        if k == Qt.Key_Space and not e.isAutoRepeat():
            self._space = False
            if self._pan is None:
                self.viewport().setCursor(self._tool_cursor())
            return
        if k in (Qt.Key_Up, Qt.Key_Down) and not e.isAutoRepeat():
            self._key_hold.pop(k, None)
            return
        super().keyReleaseEvent(e)

    def focusOutEvent(self, e):
        self._space = False
        self._key_hold.clear()
        super().focusOutEvent(e)

    # ------------------------------------------------------------ kéo thả ảnh / file vào trang
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() or e.mimeData().hasImage():
            e.acceptProposedAction()
        else:
            e.ignore()

    def dragMoveEvent(self, e):
        e.acceptProposedAction()

    def dropEvent(self, e):
        md = e.mimeData()
        pos = e.position().toPoint()
        files = [u.toLocalFile() for u in md.urls() if u.isLocalFile()] if md.hasUrls() else []
        imgs = [f for f in files if f.lower().endswith(IMG_DROP)]
        if imgs and len(files) == 1:
            it, pt = self.page_at(pos)
            if it is not None:
                e.acceptProposedAction()
                self.imageDropped.emit(it.pno, (pt.x(), pt.y()), imgs[0])
                return
        e.acceptProposedAction()
        self.filesDropped.emit(files)

    def _sel_is_stamp(self, sel=None):
        sel = sel or self.selected
        try:
            page = self.pdf.doc[sel[0]]
            a = page.load_annot(sel[1])
            return a is not None and a.type[0] == fitz.PDF_ANNOT_STAMP
        except Exception:
            return False

    def contextMenuEvent(self, e):
        it, pt = self.page_at(e.pos())
        m = QMenu(self)
        if it is not None:
            hit = self.annot_at(it, pt)
            if hit is not None:
                self.select_annot((it.pno, hit[0]))
                m.addAction("Thuộc tính ghi chú…", lambda: self.annotEditRequest.emit(it.pno, hit[0]))
                if self._sel_is_stamp((it.pno, hit[0])):
                    m.addAction("Xoay / co giãn / dịch chuyển ảnh…",
                                lambda: self.stampEditRequest.emit(it.pno, hit[0]))
                    m.addAction("Sao chép ảnh  (Ctrl+C → Ctrl+V ở trang / file khác)",
                                lambda: self.stampCopyRequest.emit(it.pno, hit[0]))
                    m.addAction("Nhân bản sang các trang / file khác…",
                                lambda: self.stampDupRequest.emit(it.pno, hit[0]))
                    from .annots import stamp_group
                    if stamp_group(self.pdf.doc, hit[0]):
                        m.addAction("Xoá ảnh này ở MỌI trang (cùng nhóm nhân bản)",
                                    lambda: self.stampGroupDeleteRequest.emit(it.pno, hit[0]))
                m.addAction("Xoá ghi chú", lambda: self.annotDeleteRequest.emit(it.pno, hit[0]))
                m.addSeparator()
            if self.selected_text:
                m.addAction("Sao chép chữ", lambda: QGuiApplication.clipboard().setText(self.selected_text))
                m.addAction("Tô sáng", lambda: self.contextAction.emit("markup", "highlight"))
                m.addAction("Gạch chân", lambda: self.contextAction.emit("markup", "underline"))
                m.addAction("Gạch ngang", lambda: self.contextAction.emit("markup", "strike"))
                m.addAction("Hỏi Claude về đoạn chọn", lambda: self.contextAction.emit("ask_ai", self.selected_text))
                m.addSeparator()
            m.addAction("Sửa chữ tại đây", lambda: self.toolFinished.emit("edittext", it.pno, {"point": (pt.x(), pt.y())}))
            m.addAction("Thêm chữ tại đây", lambda: self.toolFinished.emit("addtext", it.pno, {"point": (pt.x(), pt.y())}))
            m.addAction("Thêm ghi chú dán", lambda: self.toolFinished.emit("note", it.pno, {"point": (pt.x(), pt.y())}))
            m.addSeparator()
            m.addAction("Xoay trang phải", lambda: self.contextAction.emit("rotate", (it.pno, 90)))
            m.addAction("Xoay trang trái", lambda: self.contextAction.emit("rotate", (it.pno, -90)))
            m.addAction("Xoá trang này", lambda: self.contextAction.emit("delete_page", it.pno))
            m.addAction("Xuất trang thành ảnh", lambda: self.contextAction.emit("page_image", it.pno))
        m.exec(e.globalPos())

    # ------------------------------------------------------------ ghi chú
    def annot_at(self, it, pt):
        """Trả về (xref, rect hiển thị) của ghi chú dưới điểm (ưu tiên ghi chú nhỏ nhất)."""
        page = self.pdf[it.pno]
        best = None
        rm = page.rotation_matrix
        p = fitz.Point(pt.x(), pt.y())
        for a in page.annots():
            if a.type[0] in (fitz.PDF_ANNOT_POPUP, fitz.PDF_ANNOT_LINK, fitz.PDF_ANNOT_WIDGET):
                continue
            r = (a.rect * rm).normalize()
            rr = fitz.Rect(r.x0 - 3, r.y0 - 3, r.x1 + 3, r.y1 + 3)
            if rr.contains(p):
                if best is None or r.get_area() < best[1].get_area():
                    best = (a.xref, r)
        return best

    def _annot_tip(self, pno, xref, e):
        """Di chuột lên ghi chú -> hiện nội dung (vd thông tin chữ ký số)."""
        from PySide6.QtWidgets import QToolTip
        try:
            a = self.pdf[pno].load_annot(xref)
            txt = (a.info.get("content") or "").strip() if a else ""
        except Exception:
            txt = ""
        if txt:
            QToolTip.showText(e.globalPosition().toPoint(), txt[:900], self.viewport())

    def select_annot(self, sel):
        self.selected = sel
        self._update_selection_frame()
        self.annotSelected.emit(sel)

    def _update_selection_frame(self):
        if self._sel_item is not None:
            try:
                self.scene_.removeItem(self._sel_item)
            except Exception:
                pass
            self._sel_item = None
        if not self.selected or self.selected[0] >= len(self.items):
            return
        pno, xref = self.selected
        page = self.pdf[pno]
        a = page.load_annot(xref) if xref else None
        if a is None:
            self.selected = None
            return
        it = self.items[pno]
        r = (a.rect * page.rotation_matrix).normalize()
        sr = QRectF(self.to_scene(it, QPointF(r.x0, r.y0)), self.to_scene(it, QPointF(r.x1, r.y1)))
        item = QGraphicsRectItem(sr.adjusted(-3, -3, 3, 3))
        item.setPen(QPen(QColor("#EF6C00"), 1.5, Qt.DashLine))
        self.scene_.addItem(item)
        h = QGraphicsRectItem(QRectF(sr.right() - 2, sr.bottom() - 2, 8, 8), item)
        h.setBrush(QColor("#EF6C00"))
        h.setPen(QPen(Qt.white, 1))
        self._sel_item = item

    # ------------------------------------------------------- chọn văn bản
    def _words(self, pno):
        cache = getattr(self, "_word_cache", {})
        self._word_cache = cache
        key = (pno, id(self.pdf.doc))
        if key not in cache:
            page = self.pdf[pno]
            rm = page.rotation_matrix
            ws = []
            for w in page.get_text("words", sort=True):
                r = (fitz.Rect(w[:4]) * rm).normalize()
                ws.append((r.x0, r.y0, r.x1, r.y1, w[4], w[5], w[6], w[7]))
            cache[key] = ws
        return cache[key]

    def invalidate_words(self):
        self._word_cache = {}
        self._sig_rects = {}

    # ------------------------------------------------------- chữ ký số: rê chuột hiện thông tin
    def _sig_widgets(self, pno):
        cache = getattr(self, "_sig_rects", None)
        if cache is None:
            cache = self._sig_rects = {}
        if pno not in cache:
            out = []
            try:
                page = self.pdf[pno]
                rm = page.rotation_matrix
                for w in page.widgets() or []:
                    if w.field_type == fitz.PDF_WIDGET_TYPE_SIGNATURE:
                        out.append(((fitz.Rect(w.rect) * rm).normalize(), w.field_name))
            except Exception:
                pass
            cache[pno] = out
        return cache[pno]

    def _sig_infos(self):
        """Đọc & kiểm tra chữ ký của file (1 lần, lưu lại)."""
        pdf = self.pdf
        key = (len(pdf.original_bytes or b""), pdf.modified)
        if getattr(pdf, "_sig_infos_key", None) != key:
            from . import siginfo
            data = pdf.original_bytes if (pdf.original_bytes and not pdf.modified) else pdf.doc.tobytes()
            QGuiApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                infos = siginfo.collect(data)
            except Exception:
                infos = []
            finally:
                QGuiApplication.restoreOverrideCursor()
            pdf._sig_infos = {i["field"]: i for i in infos}
            pdf._sig_infos_key = key
        return pdf._sig_infos

    def sig_at(self, view_pos):
        it, pt = self.page_at(view_pos)
        if it is None:
            return None
        for r, name in self._sig_widgets(it.pno):
            if r.contains(fitz.Point(pt.x(), pt.y())):
                return it, r, name
        return None

    def _sig_hover(self, e):
        from PySide6.QtWidgets import QToolTip
        hit = self.sig_at(e.position().toPoint())
        old = getattr(self, "_sig_frame", None)
        if hit is None:
            if old is not None:
                self.scene_.removeItem(old)
                self._sig_frame = None
                QToolTip.hideText()
            return False
        it, r, name = hit
        info = self._sig_infos().get(name)
        ok = bool(info and info.get("ok"))
        if old is None or getattr(self, "_sig_frame_key", None) != (it.pno, name):
            if old is not None:
                self.scene_.removeItem(old)
            sr = QRectF(self.to_scene(it, QPointF(r.x0, r.y0)), self.to_scene(it, QPointF(r.x1, r.y1)))
            col = QColor("#2E7D32") if ok else QColor("#C62828")
            fr = QGraphicsRectItem(sr.adjusted(-3, -3, 3, 3))
            fr.setPen(QPen(col, 2, Qt.DashLine))
            fill = QColor(col)
            fill.setAlpha(28)
            fr.setBrush(QBrush(fill))
            self.scene_.addItem(fr)
            self._sig_frame = fr
            self._sig_frame_key = (it.pno, name)
        if info:
            from . import siginfo
            head = "✔ CHỮ KÝ SỐ HỢP LỆ" if ok else "✘ CHỮ KÝ SỐ KHÔNG HỢP LỆ / NỘI DUNG ĐÃ BỊ SỬA"
            txt = head + "\n" + siginfo.describe(info, merged=False).split("\n", 1)[1] + \
                f"\nNgười ký: {info.get('signer', '')}\n(Bấm để xem chi tiết)"
        else:
            txt = f"Ô chữ ký số '{name}' – chưa ký hoặc không đọc được chữ ký."
        QToolTip.showText(e.globalPosition().toPoint(), txt, self.viewport())
        self.viewport().setCursor(Qt.PointingHandCursor)
        return True

    def _word_at(self, it, pt):
        for w in self._words(it.pno):
            if w[0] <= pt.x() <= w[2] and w[1] <= pt.y() <= w[3]:
                return w
        return None

    def _has_text_at(self, it, pt):
        # chỉ dùng chữ đã đọc sẵn – không đọc chữ của trang chỉ vì rê chuột (trang bản vẽ nặng bị treo)
        cache = getattr(self, "_word_cache", {})
        if (it.pno, id(self.pdf.doc)) not in cache:
            return False
        return self._word_at(it, pt) is not None

    def select_text(self, pno, rect):
        ws = [w for w in self._words(pno) if fitz.Rect(w[:4]).intersects(rect)]
        self._clear_text_selection()
        if not ws:
            return
        it = self.items[pno]
        it.overlays = [(QRectF(w[0], w[1], w[2] - w[0], w[3] - w[1]), QColor(30, 120, 255, 70)) for w in ws]
        it.update()
        lines, last = [], None
        for w in ws:
            key = (w[5], w[6])
            if key != last:
                lines.append([])
                last = key
            lines[-1].append(w[4])
        self.selected_text = "\n".join(" ".join(l) for l in lines)
        self.sel_page = pno
        self.sel_rects = [fitz.Rect(w[:4]) for w in ws]
        self.textSelected.emit(self.selected_text)

    def _clear_text_selection(self):
        for it in self.items:
            if it.overlays:
                it.overlays = []
                it.update()
        self.selected_text = ""
        self.sel_rects = []
        self.search_hits = []

    def show_hits(self, hits, current=None):
        """hits: [(pno, Rect hiển thị)]"""
        for it in self.items:
            it.overlays = []
        for i, (pno, r) in enumerate(hits):
            col = QColor(255, 120, 0, 120) if i == current else QColor(255, 220, 0, 110)
            self.items[pno].overlays.append((QRectF(r.x0, r.y0, r.width, r.height), col))
        for it in self.items:
            it.update()
        if current is not None and hits:
            pno, r = hits[current]
            self.goto(pno, max(0, r.y0 - 80))


def position_fix(e):
    return e.position()


def _near_corner(r, pt, tol):
    return abs(pt.x() - r.x1) < tol * 2 and abs(pt.y() - r.y1) < tol * 2


def _unrot_clip(page, r_visible):
    """Clip cho get_pixmap phải theo toạ độ trang đã xoay? PyMuPDF dùng toạ độ hiển thị
    (sau xoay) cho clip khi trang có rotation -> giữ nguyên."""
    return r_visible
