"""Bảng trang (thumbnail): kéo thả đổi thứ tự có vạch báo vị trí, nút lên/xuống ngay trên bảng,
phím tắt, kéo file PDF/ảnh từ ngoài vào để chèn, chế độ Sắp xếp trang toàn màn hình."""
import os

import pymupdf as fitz
from PySide6.QtCore import Qt, QSize, QTimer, QRect, QPoint
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor, QPen, QKeySequence
from PySide6.QtWidgets import (QListWidget, QListWidgetItem, QAbstractItemView, QWidget, QVBoxLayout, QHBoxLayout,
                               QToolButton, QMenu, QMessageBox, QDialog, QLabel, QSlider, QPushButton, QFileDialog,
                               QGridLayout, QSizePolicy)

from .theme import icon
from .util import config
from .viewer import pix_to_qimage

ACCENT = QColor("#F57C00")


class PageGrid(QListWidget):
    def __init__(self, panel, thumb=120):
        super().__init__()
        self.panel = panel
        self.tab = None
        self.thumb = thumb
        self.setViewMode(QListWidget.IconMode)
        self.setFlow(QListWidget.LeftToRight)
        self.setWrapping(True)
        self.setResizeMode(QListWidget.Adjust)
        self.setMovement(QListWidget.Static)
        self.setSpacing(8)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setDropIndicatorShown(False)
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setDefaultDropAction(Qt.CopyAction)
        self.setAutoScroll(True)
        self.setAutoScrollMargin(40)
        self.setUniformItemSizes(True)
        self.setWordWrap(True)
        self.setStyleSheet("QListWidget::item { border: 2px solid transparent; border-radius: 6px; padding: 2px; }"
                           "QListWidget::item:selected { background: #FFE0B2; border: 2px solid #F57C00; color: #000; }"
                           "QListWidget::item:hover:!selected { background: #FFF3E0; }")
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        if not panel.organizer:
            # thanh cuộn luôn chiếm chỗ -> bề rộng ổn định, không còn vòng lặp co giãn gây nhấp nháy
            self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        from PySide6.QtWidgets import QListView
        self.setLayoutMode(QListView.Batched)
        self.setBatchSize(60)
        self._fit_timer = QTimer(self, singleShot=True, interval=90, timeout=self._do_fit)
        self._last_fit = None
        self._nocache = {}
        self.auto_fit = not panel.organizer
        self.pref = thumb                     # cỡ mong muốn (Ctrl+cuộn)
        self._drop_idx = None
        self._hold = False
        self._timer = QTimer(self, singleShot=True, interval=30, timeout=self._render_some)
        self.verticalScrollBar().valueChanged.connect(lambda *_: self._timer.start())
        self.itemClicked.connect(self._clicked)
        self.itemDoubleClicked.connect(self._clicked)
        self.set_thumb(thumb)

    # --------------------------------------------------------------- dữ liệu
    def set_thumb(self, size, cell_w=None):
        size = max(60, min(int(size), 420))
        txt_h = self.fontMetrics().height() + 14
        grid = QSize(cell_w or (size + 24), int(size * 1.35) + txt_h + 12)
        if size == getattr(self, "thumb", None) and grid == self.gridSize():
            return
        changed = abs(size - getattr(self, "thumb", 0)) > 6
        self.thumb = size
        self.setUpdatesEnabled(False)
        self.setIconSize(QSize(self.thumb, int(self.thumb * 1.35)))
        self.setGridSize(grid)
        self.setUpdatesEnabled(True)
        if changed:
            self.invalidate()

    def fit_width(self):
        """Hẹn co giãn (gộp nhiều lệnh liên tiếp thành 1, tránh nhấp nháy)."""
        if self.auto_fit:
            self._fit_timer.start()

    def _do_fit(self):
        """Tự co hình trang theo bề rộng bảng, chia cột đều, căn giữa (cân xứng)."""
        if not self.auto_fit:
            return
        vw = self.viewport().width() - 4
        key = (vw, self.pref)
        if key == self._last_fit:
            return
        self._last_fit = key
        if vw < 60:
            return
        cols = max(1, int(vw // (self.pref + 34)))
        cell = int(vw // cols)
        self.set_thumb(cell - 28, cell)

    @property
    def _cache(self):
        """Bộ nhớ hình trang RIÊNG cho từng file (xref trang -> (khoá, QPixmap)).
        Trước đây dùng chung nên file mới mở hiện nhầm hình của file cũ (trùng số xref)."""
        pdf = getattr(self.tab, "pdf", None)
        if pdf is None:
            return self._nocache
        c = getattr(pdf, "_thumb_cache", None)
        if c is None:
            c = pdf._thumb_cache = {}
        return c

    def set_tab(self, tab):
        if tab is not self.tab:
            self.scrollToTop()
        self.tab = tab
        self.rebuild()

    def rebuild(self):
        sel = self.selected_rows()
        self.clear()
        if not self.tab:
            return
        ph = QPixmap(self.thumb, int(self.thumb * 1.35))
        ph.fill(QColor("#FFFFFF"))
        ver = getattr(self.tab.pdf, "version", 0)
        self.setUpdatesEnabled(False)
        for i in range(self.tab.pdf.page_count):
            try:
                xref = self.tab.pdf.doc[i].xref
            except Exception:
                xref = -i
            cached = self._cache.get(xref)
            icon_ = QIcon(cached[1]) if cached else QIcon(ph)
            if cached:
                icon_.addPixmap(cached[1], QIcon.Selected)
            it = QListWidgetItem(icon_, f"{i + 1}")
            it.setData(Qt.UserRole, i)
            it.setData(Qt.UserRole + 1, bool(cached and cached[0] == (ver, self.thumb)))
            it.setTextAlignment(Qt.AlignHCenter)
            it.setToolTip(f"Trang {i + 1} – kéo thả để đổi vị trí")
            self.addItem(it)
        self.setUpdatesEnabled(True)
        self.select_rows([r for r in sel if r < self.count()])
        self._timer.start()

    def invalidate(self):
        for i in range(self.count()):
            self.item(i).setData(Qt.UserRole + 1, False)
        self._timer.start()

    def _render_some(self):
        if not self.tab:
            return
        vr = self.viewport().rect().adjusted(0, -400, 0, 400)
        dpr = self.devicePixelRatioF()
        n = 0
        for i in range(self.count()):
            it = self.item(i)
            if it.data(Qt.UserRole + 1) or not self.visualItemRect(it).intersects(vr):
                continue
            try:
                page = self.tab.pdf.doc[i]
                z = self.thumb * 1.35 * dpr / max(page.rect.width, page.rect.height)
                z = min(z, self.thumb * dpr / page.rect.width)
                want_w = max(8, int(page.rect.width * z))
                vi = None
                try:
                    vi = self.tab.view.items[i]
                except Exception:
                    pass
                if vi is not None and vi.base is not None and vi.base.width() >= want_w:
                    pm = vi.base.scaledToWidth(want_w, Qt.SmoothTransformation)
                else:
                    pm = QPixmap.fromImage(pix_to_qimage(page.get_pixmap(matrix=fitz.Matrix(z, z), annots=True)))
                pm.setDevicePixelRatio(dpr)
                self._cache[page.xref] = ((getattr(self.tab.pdf, "version", 0), self.thumb), pm)
                ic = QIcon(pm)
                ic.addPixmap(pm, QIcon.Selected)          # không phủ màu lên hình trang khi chọn
                it.setIcon(ic)
                w, h = page.rect.width * 25.4 / 72, page.rect.height * 25.4 / 72
                it.setToolTip(f"Trang {i + 1}  ({w:.0f}×{h:.0f} mm)\nKéo thả để đổi vị trí · Ctrl+↑/↓ di chuyển")
                it.setData(Qt.UserRole + 1, True)
            except Exception:
                pass
            n += 1
            if n >= 8:
                self._timer.start()
                break

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if e.oldSize().width() != e.size().width():
            self.fit_width()
        self._timer.start()

    def _clicked(self, it):
        if self.tab and not (self.panel.organizer):
            self.tab.view.goto(self.row(it))

    def selected_rows(self):
        return sorted(self.row(i) for i in self.selectedItems())

    def selected_pages(self):
        rows = self.selected_rows()
        return rows or ([self.tab.view.current_page] if self.tab else [])

    def select_rows(self, rows):
        self.clearSelection()
        for r in rows:
            it = self.item(r)
            if it:
                it.setSelected(True)
        if rows and self.item(rows[0]):
            self.setCurrentItem(self.item(rows[0]), QItemSelectionModelNoUpdate())
            self.scrollToItem(self.item(rows[0]))

    # -------------------------------------------------------------- kéo thả
    def _single_column(self):
        if self.count() < 2:
            return True
        a, b = self.visualItemRect(self.item(0)), self.visualItemRect(self.item(1))
        return b.top() > a.top() + 5

    def _index_at(self, pos):
        if self.count() == 0:
            return 0
        best, bestd = 0, None
        for i in range(self.count()):
            r = self.visualItemRect(self.item(i))
            dx = max(r.left() - pos.x(), 0, pos.x() - r.right())
            dy = max(r.top() - pos.y(), 0, pos.y() - r.bottom())
            d = dx * dx + dy * dy * 4
            if bestd is None or d < bestd:
                best, bestd = i, d
        r = self.visualItemRect(self.item(best))
        if self._single_column():
            return best if pos.y() < r.center().y() else best + 1
        return best if pos.x() < r.center().x() else best + 1

    def dragEnterEvent(self, e):
        if e.source() is self or e.mimeData().hasUrls() or e.mimeData().hasFormat("application/x-pdfphantom-pages"):
            e.setDropAction(Qt.CopyAction)
            e.accept()
        else:
            e.ignore()

    def dragMoveEvent(self, e):
        super().dragMoveEvent(e)                 # cuộn tự động khi kéo tới mép
        if e.source() is self or e.mimeData().hasUrls():
            self._drop_idx = self._index_at(e.position().toPoint())
            self.viewport().update()
            e.setDropAction(Qt.CopyAction)
            e.accept()
        else:
            e.ignore()

    def dragLeaveEvent(self, e):
        self._drop_idx = None
        self.viewport().update()
        super().dragLeaveEvent(e)

    def dropEvent(self, e):
        idx = self._index_at(e.position().toPoint())
        self._drop_idx = None
        self.viewport().update()
        if e.source() is self:
            rows = self.selected_rows()
            e.setDropAction(Qt.CopyAction)       # không để Qt tự xoá item
            e.accept()
            QTimer.singleShot(0, lambda: self.panel.move_to(rows, idx))
        elif e.mimeData().hasFormat("application/x-pdfphantom-internal") and e.source() is not None:
            # kéo trang từ bảng trang của file khác (cửa sổ Sắp xếp) -> chép trang
            src = e.source()
            rows = src.selected_rows()
            e.accept()
            from . import pageclip

            def go():
                data = pageclip.pages_to_pdf(src.tab.pdf.doc, rows, src.tab.pdf.name)
                n = self.tab.pdf.insert_bytes(data, idx)
                self.panel._after(list(range(idx, idx + n)))
            QTimer.singleShot(0, go)
        elif e.mimeData().hasUrls():
            files = [u.toLocalFile() for u in e.mimeData().urls() if os.path.isfile(u.toLocalFile())]
            e.accept()
            QTimer.singleShot(0, lambda: self.panel.insert_files(files, idx))
        else:
            e.ignore()

    def paintEvent(self, e):
        super().paintEvent(e)
        if self._drop_idx is None or self.count() == 0:
            return
        p = QPainter(self.viewport())
        p.setRenderHint(QPainter.Antialiasing)
        pen = QPen(ACCENT, 4)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        i = self._drop_idx
        single = self._single_column()
        if i < self.count():
            r = self.visualItemRect(self.item(i))
            if single:
                y = r.top() - 4
                p.drawLine(r.left() + 6, y, r.right() - 6, y)
            else:
                x = r.left() - 5
                p.drawLine(x, r.top() + 4, x, r.bottom() - 4)
        else:
            r = self.visualItemRect(self.item(self.count() - 1))
            if single:
                y = r.bottom() + 4
                p.drawLine(r.left() + 6, y, r.right() - 6, y)
            else:
                x = r.right() + 5
                p.drawLine(x, r.top() + 4, x, r.bottom() - 4)
        p.end()

    # ----------------------------------------------------------- bàn phím, chuột
    def keyPressEvent(self, e):
        ctrl = e.modifiers() & Qt.ControlModifier
        k = e.key()
        if e.matches(QKeySequence.Copy):
            self.panel.copy()
            return
        if e.matches(QKeySequence.Cut):
            self.panel.cut()
            return
        if e.matches(QKeySequence.Paste):
            self.panel.paste()
            return
        if k == Qt.Key_Delete:
            self.panel.delete()
            return
        if ctrl and k in (Qt.Key_Up, Qt.Key_Left):
            self.panel.move_step(-1)
            return
        if ctrl and k in (Qt.Key_Down, Qt.Key_Right):
            self.panel.move_step(1)
            return
        if ctrl and k == Qt.Key_Home:
            self.panel.move_edge(top=True)
            return
        if ctrl and k == Qt.Key_End:
            self.panel.move_edge(top=False)
            return
        before = self.currentRow()
        super().keyPressEvent(e)
        # đi bằng phím mũi tên trong bảng -> trang chính đi theo
        if self.tab and not self.panel.organizer and self.currentRow() != before and self.currentRow() >= 0:
            self.tab.view.goto(self.currentRow())

    def wheel_step(self):
        return max(24, self.gridSize().height() // 4)

    def wheelEvent(self, e):
        dy = e.angleDelta().y()
        if e.modifiers() & Qt.ControlModifier:
            f = 1.12 if dy > 0 else 1 / 1.12
            self.pref = max(60, min(int(self.pref * f), 420))
            if self.auto_fit:
                self.fit_width()                     # gộp các nấc cuộn liên tiếp
            else:
                self.set_thumb(self.pref)
            self.panel.thumb_changed(self.pref)
            return
        # cuộn đều, chậm vừa phải: 1 nấc chuột = 1/4 chiều cao 1 trang thu nhỏ
        if not e.pixelDelta().isNull():
            step = -e.pixelDelta().y()
        else:
            step = -dy / 120.0 * self.wheel_step()
        sb = self.verticalScrollBar()
        sb.setValue(int(sb.value() + step))
        e.accept()

    def startDrag(self, actions):
        """Kéo trang: trong bảng = đổi vị trí; kéo ra Windows Explorer / Desktop = tạo file PDF từng trang."""
        from PySide6.QtGui import QDrag
        from PySide6.QtCore import QMimeData, QUrl
        rows = self.selected_rows()
        if not rows or not self.tab:
            return
        md = QMimeData()
        md.setData("application/x-pdfphantom-internal", b"1")
        try:
            if len(rows) <= 30:
                from . import pageclip
                import tempfile
                folder = tempfile.mkdtemp(prefix="trang_", dir=pageclip._tmpdir())
                files = pageclip.single_page_files(self.tab.pdf.doc, rows, folder,
                                                   os.path.splitext(self.tab.pdf.name)[0],
                                                   None if self.tab.pdf.modified else self.tab.pdf.original_bytes,
                                                   self.tab.pdf.name)
                md.setUrls([QUrl.fromLocalFile(f) for f in files])
        except Exception:
            pass
        drag = QDrag(self)
        drag.setMimeData(md)
        it = self.item(rows[0])
        if it is not None:
            pm = it.icon().pixmap(QSize(self.thumb // 2, int(self.thumb * 0.68)))
            drag.setPixmap(pm)
        drag.exec(Qt.CopyAction | Qt.MoveAction, Qt.CopyAction)

    def contextMenuEvent(self, e):
        if not self.tab:
            return
        it = self.itemAt(e.pos())
        if it and not it.isSelected():
            self.select_rows([self.row(it)])
        self.panel.menu().exec(e.globalPos())


def QItemSelectionModelNoUpdate():
    from PySide6.QtCore import QItemSelectionModel
    return QItemSelectionModel.NoUpdate


class PagePanel(QWidget):
    """Bảng trang + thanh nút thao tác. organizer=True: dùng trong cửa sổ Sắp xếp trang."""

    BUTTONS = [
        ("copy", "Sao chép trang (Ctrl+C)", lambda s: s.copy()),
        ("cut", "Cắt trang (Ctrl+X)", lambda s: s.cut()),
        ("paste", "Dán trang vào vị trí chuột / sau trang chọn (Ctrl+V)", lambda s: s.paste()),
        ("splitone", "Tách từng trang chọn thành file riêng…", lambda s: s.split_single()),
        ("split", "Tách file theo trang tự chọn…", lambda s: s.main.split(s.grid.selected_pages() or None)),
        ("raster", "Chuyển trang chọn thành ảnh (ghép lại đúng trang)…",
         lambda s: s.main.rasterize_pages(s.grid.selected_pages())),
        ("up", "Đưa trang lên (Ctrl+↑)", lambda s: s.move_step(-1)),
        ("down", "Đưa trang xuống (Ctrl+↓)", lambda s: s.move_step(1)),
        ("top", "Lên đầu tài liệu (Ctrl+Home)", lambda s: s.move_edge(True)),
        ("bottom", "Xuống cuối tài liệu (Ctrl+End)", lambda s: s.move_edge(False)),
        ("rotl", "Xoay trái 90°", lambda s: s.rotate(-90)),
        ("rotr", "Xoay phải 90°", lambda s: s.rotate(90)),
        ("dup", "Nhân bản trang", lambda s: s.duplicate()),
        ("blank", "Chèn trang trắng phía sau", lambda s: s.insert_blank()),
        ("insert", "Chèn file PDF / ảnh phía sau…", lambda s: s.insert_dialog()),
        ("extract", "Trích các trang chọn thành file…", lambda s: s.extract()),
        ("delete", "Xoá trang (Delete)", lambda s: s.delete()),
        ("organize", "Sắp xếp trang – xem lớn toàn màn hình", lambda s: s.open_organizer()),
    ]

    def __init__(self, main, organizer=False, thumb=None):
        super().__init__()
        self.main = main
        self.organizer = organizer
        lay = QVBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(3)
        bar = QGridLayout()
        bar.setSpacing(2)
        per_row = 16 if organizer else (len(self.BUTTONS) + 1) // 2
        for i, (ic, tip, fn) in enumerate(self.BUTTONS):
            if organizer and ic == "organize":
                continue
            b = QToolButton()
            b.setIcon(icon(ic, 20))
            b.setIconSize(QSize(20, 20))
            b.setToolTip(tip)
            b.setAutoRaise(True)
            b.clicked.connect(lambda _=False, f=fn: f(self))
            if organizer:
                b.setText(tip.split(" (")[0].split("…")[0])
                b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
                b.setIconSize(QSize(28, 28))
                b.setIcon(icon(ic, 28))
            bar.addWidget(b, i // per_row, i % per_row)
        lay.addLayout(bar)
        self.grid = PageGrid(self, thumb or config().get("thumb_size", 120))
        lay.addWidget(self.grid, 1)
        hint = QLabel("Kéo thả đổi vị trí · Ctrl+C/X/V chép/cắt/dán · Ctrl+cuộn: to/nhỏ" if not organizer else "")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#888; font-size:8pt;")
        if not organizer:
            lay.addWidget(hint)

    @property
    def tab(self):
        return self.grid.tab

    # ------------------------------------------------------- chép / cắt / dán
    def copy(self):
        if not self.tab:
            return 0
        from . import pageclip
        rows = self._rows()
        n = pageclip.copy_pages(self.tab, rows)
        self.main.flash(f"Đã sao chép {n} trang – chọn file/vị trí khác rồi bấm Ctrl+V để dán "
                        "(dán vào thư mục Windows sẽ ra file PDF).")
        return n

    def cut(self):
        if not self.tab:
            return
        rows = self._rows()
        if len(rows) >= self.tab.pdf.page_count:
            self.copy()
            self.main.flash("Đã sao chép toàn bộ trang (không thể cắt hết trang của file).")
            return
        self.copy()
        self.tab.pdf.delete(rows)
        if self.organizer:
            self.grid.rebuild()
        self.main.flash(f"Đã cắt {len(rows)} trang – di chuột tới vị trí cần dán rồi bấm Ctrl+V. (Ctrl+Z để hoàn tác)")

    def paste_index(self):
        """Vị trí dán: theo con trỏ chuột trên bảng trang / trên trang đang xem; mặc định sau trang chọn."""
        from PySide6.QtGui import QCursor
        g = self.grid
        vp_pos = g.viewport().mapFromGlobal(QCursor.pos())
        if g.viewport().rect().contains(vp_pos) and g.count():
            return g._index_at(vp_pos)
        if self.tab:
            v = self.tab.view
            vpos = v.viewport().mapFromGlobal(QCursor.pos())
            if v.viewport().rect().contains(vpos):
                it, pt = v.page_at(vpos)
                if it is not None:
                    return it.pno if pt.y() < it.h / 2 else it.pno + 1
        rows = g.selected_rows()
        if rows:
            return rows[-1] + 1
        return (self.tab.view.current_page + 1) if self.tab else 0

    def paste(self, at=None):
        if not self.tab:
            return
        from . import pageclip
        kind, data = pageclip.clipboard_content()
        if kind is None:
            self.main.flash("Bộ nhớ tạm chưa có trang / file / ảnh để dán.")
            return
        at = self.paste_index() if at is None else at
        if kind == "pages":
            n = self.tab.pdf.insert_bytes(data, at)
            if self.organizer:
                self.grid.rebuild()
            self._after(list(range(at, at + n)))
            self.main.flash(f"Đã dán {n} trang vào vị trí {at + 1}.")
        elif kind == "files":
            self.insert_files(data, at)
        elif kind == "stamp":
            # ảnh / con dấu đã sao chép -> đóng lên TẤT CẢ trang đang chọn, đúng vị trí như trang gốc
            rows = self.grid.selected_rows() or [min(at, self.tab.pdf.page_count - 1)]
            self.tab.stamp_on_pages(data, rows)
        elif kind == "image":
            import tempfile
            pth = os.path.join(tempfile.gettempdir(), "phantom_clip_image.png")
            data.save(pth)
            self.insert_files([pth], at)

    def split_single(self):
        """Tách từng trang chọn (hoặc tất cả) thành các file PDF riêng."""
        if not self.tab:
            return
        from .widgets import ask_dir, done_message
        from . import pageclip
        rows = self.grid.selected_rows()
        if len(rows) <= 1:
            r = QMessageBox.question(self, "Tách trang", f"Tách TẤT CẢ {self.tab.pdf.page_count} trang thành từng file "
                                     "riêng?\n(Chọn No = chỉ tách trang đang chọn)",
                                     QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel)
            if r == QMessageBox.Cancel:
                return
            rows = list(range(self.tab.pdf.page_count)) if r == QMessageBox.Yes else self._rows()
        d = ask_dir(self, "Chọn thư mục lưu các trang tách")
        if not d:
            return
        outs = pageclip.single_page_files(self.tab.pdf.doc, rows, d, os.path.splitext(self.tab.pdf.name)[0],
                                          None if self.tab.pdf.modified else self.tab.pdf.original_bytes,
                                          self.tab.pdf.name)
        done_message(self, f"Đã tách {len(outs)} trang thành {len(outs)} file PDF riêng.", folder=d)

    def thumb_changed(self, size):
        if not self.organizer:
            config()["thumb_size"] = size

    # ----------------------------------------------------------- thao tác
    def _rows(self):
        return self.grid.selected_pages()

    def hold_selection(self, ms=800):
        """Tạm giữ vùng chọn (không để việc cuộn trang chính làm mất chọn)."""
        self.grid._hold = True
        QTimer.singleShot(ms, lambda: setattr(self.grid, "_hold", False))

    def _after(self, new_rows):
        """Sau khi đổi trang: chọn lại các trang vừa di chuyển & cuộn tới."""
        self.hold_selection()
        self.grid.select_rows(new_rows)
        if self.tab and new_rows and not self.organizer:
            self.tab.view.goto(new_rows[0])
        QTimer.singleShot(50, lambda: self.grid.select_rows(new_rows))

    def _apply_order(self, order, new_rows):
        if order == list(range(len(order))):
            self.grid.select_rows(new_rows)
            return
        self.hold_selection()
        self.tab.pdf.reorder(order)
        if self.organizer:
            self.grid.rebuild()
        self._after(new_rows)

    def move_step(self, step):
        if not self.tab:
            return
        n = self.tab.pdf.page_count
        sel = set(self._rows())
        slots = [(p, p in sel) for p in range(n)]
        rng = range(1, n) if step < 0 else range(n - 2, -1, -1)
        for i in rng:
            j = i + step
            if slots[i][1] and not slots[j][1]:
                slots[i], slots[j] = slots[j], slots[i]
        order = [p for p, _ in slots]
        self._apply_order(order, [i for i, (p, s) in enumerate(slots) if s])

    def move_edge(self, top=True):
        if not self.tab:
            return
        n = self.tab.pdf.page_count
        sel = self._rows()
        rest = [p for p in range(n) if p not in sel]
        order = sel + rest if top else rest + sel
        new = list(range(len(sel))) if top else list(range(n - len(sel), n))
        self._apply_order(order, new)

    def move_to(self, rows, idx):
        """Kéo thả: đưa các trang chọn tới trước vị trí idx (chỉ số trước khi di chuyển)."""
        if not self.tab or not rows:
            return
        n = self.tab.pdf.page_count
        rest = [p for p in range(n) if p not in rows]
        before = sum(1 for r in rows if r < idx)
        to = max(0, min(idx - before, len(rest)))
        order = rest[:to] + rows + rest[to:]
        self._apply_order(order, list(range(to, to + len(rows))))
        self.main.flash(f"Đã chuyển {len(rows)} trang tới vị trí {to + 1}.")

    def rotate(self, angle):
        if self.tab:
            rows = self._rows()
            self.tab.pdf.rotate(rows, angle)
            if self.organizer:
                self.grid.invalidate()
            self.grid.select_rows(rows)

    def duplicate(self):
        if self.tab:
            rows = self._rows()
            self.tab.pdf.duplicate(rows)
            if self.organizer:
                self.grid.rebuild()

    def insert_blank(self):
        if self.tab:
            at = max(self._rows()) + 1
            self.tab.pdf.insert_blank(at, like=at - 1)
            if self.organizer:
                self.grid.rebuild()
            self._after([at])

    def insert_dialog(self):
        if not self.tab:
            return
        files, _ = QFileDialog.getOpenFileNames(self, "Chèn file", config().get("last_dir", ""),
                                                "PDF và ảnh (*.pdf *.png *.jpg *.jpeg *.bmp *.tif *.tiff)")
        if files:
            self.insert_files(files, max(self._rows()) + 1)

    def insert_files(self, files, at):
        if not self.tab or not files:
            return
        start = at
        for f in files:
            n0 = self.tab.pdf.page_count
            try:
                self.tab.pdf.insert_file(f, at)
            except Exception as e:
                QMessageBox.warning(self, "Chèn file", f"{os.path.basename(f)}: {e}")
                continue
            at += self.tab.pdf.page_count - n0
        if self.organizer:
            self.grid.rebuild()
        self._after(list(range(start, at)))
        self.main.flash(f"Đã chèn {at - start} trang tại vị trí {start + 1}.")

    def extract(self):
        if not self.tab:
            return
        from .widgets import ask_save, done_message
        rows = self._rows()
        p = ask_save(self, "Lưu các trang chọn", os.path.splitext(self.tab.pdf.name)[0] + "_trich.pdf")
        if p:
            self.tab.pdf.extract(rows, p)
            done_message(self, f"Đã trích {len(rows)} trang.", p)

    def delete(self):
        if not self.tab:
            return
        rows = self._rows()
        if QMessageBox.question(self, "Xoá trang", f"Xoá {len(rows)} trang: "
                                f"{', '.join(str(r + 1) for r in rows[:15])}{'…' if len(rows) > 15 else ''}?") \
                != QMessageBox.Yes:
            return
        try:
            self.tab.pdf.delete(rows)
        except Exception as e:
            QMessageBox.warning(self, "Xoá trang", str(e))
            return
        if self.organizer:
            self.grid.rebuild()
        self.grid.select_rows([min(rows[0], self.tab.pdf.page_count - 1)])

    def select_parity(self, odd=True):
        self.grid.select_rows([i for i in range(self.grid.count()) if (i % 2 == 0) == odd])

    def reverse(self):
        if self.tab:
            n = self.tab.pdf.page_count
            self._apply_order(list(range(n - 1, -1, -1)), [])

    def open_organizer(self):
        if self.tab:
            OrganizerDialog(self.main, self.tab).exec()

    def menu(self):
        m = QMenu(self)
        for ic, tip, fn in self.BUTTONS:
            if self.organizer and ic == "organize":
                continue
            m.addAction(icon(ic, 16), tip, lambda f=fn: f(self))
            if ic in ("splitone", "bottom", "rotr", "extract"):
                m.addSeparator()
        m.addSeparator()
        m.addAction("Chọn các trang lẻ", lambda: self.select_parity(True))
        m.addAction("Chọn các trang chẵn", lambda: self.select_parity(False))
        m.addAction("Đảo ngược thứ tự toàn bộ", self.reverse)
        m.addAction("Xuất các trang chọn thành ảnh…", self.main.to_images_selected)
        return m


class OrganizerDialog(QDialog):
    """Sắp xếp trang toàn màn hình: hình lớn, kéo thả, chọn nhiều, thao tác hàng loạt."""

    def __init__(self, main, tab):
        super().__init__(main)
        self.main, self.tab = main, tab
        self.setWindowTitle(f"Sắp xếp trang – {tab.pdf.name}")
        self.resize(1300, 820)
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, True)
        lay = QVBoxLayout(self)
        self.panel = PagePanel(main, organizer=True, thumb=config().get("organizer_thumb", 190))
        lay.addWidget(self.panel, 1)
        lay.addWidget(QLabel("<b>Kéo thả</b> trang để đổi vị trí (vạch cam = chỗ thả) · Ctrl/Shift + bấm để chọn "
                             "nhiều trang · Kéo file PDF/ảnh từ ngoài vào để chèn · Ctrl+cuộn chuột: to/nhỏ"))
        row = QHBoxLayout()
        for txt, fn in (("Trang lẻ", lambda: self.panel.select_parity(True)),
                        ("Trang chẵn", lambda: self.panel.select_parity(False)),
                        ("Chọn hết", self.panel.grid.selectAll),
                        ("Đảo ngược thứ tự", self.panel.reverse),
                        ("Hoàn tác (Ctrl+Z)", self.undo)):
            b = QPushButton(txt)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch()
        row.addWidget(QLabel("Cỡ hình:"))
        self.size = QSlider(Qt.Horizontal, minimum=80, maximum=420, value=self.panel.grid.thumb)
        self.size.setFixedWidth(160)
        self.size.valueChanged.connect(self.panel.grid.set_thumb)
        row.addWidget(self.size)
        done = QPushButton("Xong")
        done.setObjectName("primary")
        done.clicked.connect(self.accept)
        row.addWidget(done)
        lay.addLayout(row)
        from PySide6.QtGui import QShortcut
        QShortcut(QKeySequence.Undo, self, activated=self.undo)
        QShortcut(QKeySequence.Redo, self, activated=self.redo)
        self.panel.grid.set_tab(tab)

    def undo(self):
        if self.tab.pdf.undo():
            self.panel.grid.rebuild()

    def redo(self):
        if self.tab.pdf.redo():
            self.panel.grid.rebuild()

    def done(self, r):
        config()["organizer_thumb"] = self.panel.grid.thumb
        config().save()
        super().done(r)
