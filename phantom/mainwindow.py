"""Cửa sổ chính PDF Phantom: ribbon kiểu Office, nhiều thẻ tài liệu, thanh trang/dấu trang/ghi chú,
khung Claude AI, tìm kiếm, kéo thả file."""
import os

import pymupdf as fitz
from PySide6.QtCore import Qt, QSize, QTimer, QSettings
from PySide6.QtGui import QColor, QAction, QActionGroup, QKeySequence, QIcon, QPixmap, QGuiApplication
from PySide6.QtWidgets import (QMainWindow, QTabWidget, QToolBar, QToolButton, QWidget, QVBoxLayout,
                               QHBoxLayout, QDockWidget, QListWidget, QListWidgetItem, QTreeWidget,
                               QTreeWidgetItem, QLabel, QSpinBox, QComboBox, QLineEdit, QPushButton,
                               QFileDialog, QMessageBox, QInputDialog, QMenu, QStatusBar, QAbstractItemView,
                               QApplication, QSizePolicy, QCheckBox)

from . import APP_NAME, VERSION, annots as A
from .doctab import DocTab
from .propbar import PropBar
from .theme import icon, LIGHT, DARK, app_icon
from .util import config, parse_pages, human_size
from .viewer import pix_to_qimage

OPEN_FILTER = "PDF và ảnh (*.pdf *.png *.jpg *.jpeg *.bmp *.tif *.tiff *.gif *.webp);;PDF (*.pdf);;Tất cả (*.*)"


def short_title(name, n=24):
    """Rút gọn tên file dài: 'Hồ sơ thanh toán đợt 3 ... (rev2).pdf' -> 'Hồ sơ thanh toá…(rev2).pdf'."""
    if len(name) <= n:
        return name
    base, ext = os.path.splitext(name)
    keep = n - len(ext) - 1
    head = max(6, int(keep * 0.62))
    tail = max(3, keep - head)
    return base[:head].rstrip() + "…" + base[-tail:].lstrip() + ext


class PageBox(QLineEdit):
    """Ô số trang (thay QSpinBox – tránh lỗi chữ bị che): gõ số + Enter để chuyển trang."""
    from PySide6.QtCore import Signal as _Signal
    editingFinished2 = _Signal()

    def __init__(self):
        super().__init__()
        from PySide6.QtGui import QIntValidator
        self._max = 1
        self._val = QIntValidator(1, 1, self)
        self.setValidator(self._val)
        self.setAlignment(Qt.AlignCenter)
        self.setText("1")

    def setMaximum(self, n):
        self._max = max(1, n)
        self._val.setTop(self._max)

    def setValue(self, v):
        if not self.hasFocus():
            self.setText(str(int(v)))

    def value(self):
        try:
            return max(1, min(int(self.text()), self._max))
        except ValueError:
            return 1

    def focusInEvent(self, e):
        super().focusInEvent(e)
        QTimer.singleShot(0, self.selectAll)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {VERSION}")
        self.setWindowIcon(app_icon())
        self.resize(1400, 880)
        self.setAcceptDrops(True)
        self.tool_actions = {}
        self.plugin_toolbar = None
        self.plugins_loaded = ([], [])

        central = QWidget()
        cl = QVBoxLayout(central)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        self.ribbon = QTabWidget()
        self.ribbon.setObjectName("ribbon")
        self.ribbon.setFixedHeight(104)
        rb = QToolBar("Ribbon")
        rb.setObjectName("ribbon_bar")
        rb.setMovable(False)
        rb.setFloatable(False)
        rb.setContextMenuPolicy(Qt.CustomContextMenu)
        rb.customContextMenuRequested.connect(lambda pos: self._panels_menu().exec(rb.mapToGlobal(pos)))
        rb.setStyleSheet("QToolBar#ribbon_bar { padding:0; margin:0; border:none; }")
        rb.addWidget(self.ribbon)
        self.addToolBar(Qt.TopToolBarArea, rb)
        self.addToolBarBreak(Qt.TopToolBarArea)
        self.propbar = PropBar(self)
        self.addToolBar(Qt.TopToolBarArea, self.propbar)
        self.findbar = self._make_findbar()
        cl.addWidget(self.findbar)
        self.tabs = QTabWidget()
        self.tabs.setObjectName("docs")
        self.tabs.setTabsClosable(True)
        self.tabs.setElideMode(Qt.ElideMiddle)
        self.tabs.setUsesScrollButtons(True)
        self.tabs.setMovable(True)
        self.tabs.setDocumentMode(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self.tab_changed)
        cl.addWidget(self.tabs, 1)
        self.welcome = self._make_welcome()
        cl.addWidget(self.welcome, 1)
        self.setCentralWidget(central)

        self._make_docks()
        self._make_actions()
        self._make_ribbon()
        self._make_status()
        self.apply_theme()
        self.update_ui()
        self.restore_layout()

        from .plugins import load_plugins, check_update
        self.plugins_loaded = load_plugins(self)
        if config().get("update_url"):
            QTimer.singleShot(4000, lambda: check_update(self, silent=True))

    # =============================================================== giao diện
    def _make_welcome(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addStretch()
        t = QLabel("<div style='text-align:center'><span style='font-size:30pt;font-weight:700;color:#EF6C00'>"
                   f"PDF Phantom</span><br><span style='color:#666'>Đọc · Ghi chú · Gộp · Tách · Chuyển đổi · "
                   f"Scan · OCR · Ký số · Claude AI</span></div>")
        t.setAlignment(Qt.AlignCenter)
        lay.addWidget(t)
        row = QHBoxLayout()
        row.addStretch()
        for txt, ic, fn in (("Mở file PDF", "open", self.open_dialog), ("Gộp file", "merge", self.merge),
                            ("Scan ảnh chụp", "scan", self.scan), ("PDF → Word", "toword", self.to_word)):
            b = QToolButton()
            b.setText(txt)
            b.setIcon(icon(ic, 48))
            b.setIconSize(QSize(48, 48))
            b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            b.setMinimumSize(130, 100)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch()
        lay.addLayout(row)
        self.recent_list = QListWidget()
        self.recent_list.setMaximumWidth(700)
        self.recent_list.itemDoubleClicked.connect(lambda it: self.open_file(it.data(Qt.UserRole)))
        r2 = QHBoxLayout()
        r2.addStretch()
        v = QVBoxLayout()
        v.addWidget(QLabel("<b>File mở gần đây</b> (bấm đúp để mở) – hoặc kéo thả file PDF vào cửa sổ:"))
        v.addWidget(self.recent_list)
        r2.addLayout(v)
        r2.addStretch()
        lay.addLayout(r2)
        lay.addStretch()
        return w

    def _refresh_recent(self):
        self.recent_list.clear()
        for p in config().get("recent", []):
            if os.path.exists(p):
                it = QListWidgetItem(icon("open", 16), f"{os.path.basename(p)}    —    {os.path.dirname(p)}")
                it.setData(Qt.UserRole, p)
                self.recent_list.addItem(it)

    def _make_findbar(self):
        w = QWidget()
        w.setVisible(False)
        lay = QHBoxLayout(w)
        lay.setContentsMargins(8, 4, 8, 4)
        lay.addWidget(QLabel("Tìm:"))
        self.find_edit = QLineEdit(placeholderText="Nhập từ cần tìm, Enter để tìm tiếp…")
        self.find_edit.returnPressed.connect(lambda: self.find_next(1))
        self.find_case = QCheckBox("Phân biệt hoa/thường")
        self.find_info = QLabel()
        lay.addWidget(self.find_edit, 1)
        lay.addWidget(self.find_case)
        for t, s in (("◀", -1), ("▶", 1)):
            b = QPushButton(t)
            b.setFixedWidth(34)
            b.clicked.connect(lambda _, s=s: self.find_next(s))
            lay.addWidget(b)
        lay.addWidget(self.find_info)
        b = QPushButton("✕")
        b.setFixedWidth(30)
        b.clicked.connect(lambda: (w.setVisible(False), self.current_tab() and self.current_tab().view.show_hits([])))
        lay.addWidget(b)
        self.find_edit.textChanged.connect(lambda *_: setattr(self, "_hits", None))
        self._hits = None
        self._hit_idx = -1
        return w

    def _make_docks(self):
        self.left_dock = QDockWidget("Điều hướng", self)
        self.left_dock.setObjectName("left_dock")
        self.left_tabs = QTabWidget()
        from .pagepanel import PagePanel
        self.page_panel = PagePanel(self)
        self.thumbs = self.page_panel.grid
        self.left_tabs.addTab(self.page_panel, "Trang")
        bw = QWidget()
        bl = QVBoxLayout(bw)
        bl.setContentsMargins(2, 2, 2, 2)
        self.bm_tree = QTreeWidget()
        self.bm_tree.setHeaderHidden(True)
        self.bm_tree.itemClicked.connect(self._bm_goto)
        bl.addWidget(self.bm_tree)
        r = QHBoxLayout()
        for t, fn in (("Thêm", self.bm_add), ("Đổi tên", self.bm_rename), ("Xoá", self.bm_delete)):
            b = QPushButton(t)
            b.clicked.connect(fn)
            r.addWidget(b)
        bl.addLayout(r)
        self.left_tabs.addTab(bw, "Dấu trang")
        self.annot_list = QListWidget()
        self.annot_list.itemClicked.connect(self._annot_goto)
        self.left_tabs.addTab(self.annot_list, "Ghi chú")
        sw = QWidget()
        sl = QVBoxLayout(sw)
        sl.setContentsMargins(2, 2, 2, 2)
        self.sig_list = QListWidget()
        self.sig_list.setWordWrap(True)
        self.sig_list.itemClicked.connect(self._sig_goto)
        self.sig_list.itemDoubleClicked.connect(self._sig_open)
        sl.addWidget(self.sig_list, 1)
        rs = QHBoxLayout()
        b1 = QPushButton("Kiểm tra lại")
        b1.clicked.connect(lambda: self.refresh_signatures(force=True))
        b2 = QPushButton("Mở bản gốc")
        b2.setToolTip("Mở file gốc đính kèm (còn nguyên chữ ký số) của mục đang chọn")
        b2.clicked.connect(lambda: self._sig_open(self.sig_list.currentItem()))
        rs.addWidget(b1)
        rs.addWidget(b2)
        sl.addLayout(rs)
        self.left_tabs.addTab(sw, "Chữ ký")
        self.left_tabs.currentChanged.connect(lambda i: self.refresh_annot_list() if i == 2 else
                                              (self.refresh_signatures() if i == 3 else None))
        self.left_dock.setWidget(self.left_tabs)
        self.left_dock.setMinimumWidth(200)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.left_dock)
        self.resizeDocks([self.left_dock], [230], Qt.Horizontal)

        from .ai import AIPanel
        self.ai_dock = QDockWidget("Claude AI", self)
        self.ai_dock.setObjectName("ai_dock")
        self.ai_panel = AIPanel(self)
        self.ai_dock.setWidget(self.ai_panel)
        self.ai_dock.setMinimumWidth(330)
        self.addDockWidget(Qt.RightDockWidgetArea, self.ai_dock)
        self.ai_dock.hide()

    def _act(self, text, ic, fn, shortcut=None, tip=None, checkable=False):
        a = QAction(icon(ic), text, self)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        a.setToolTip((tip or text) + (f"  ({shortcut})" if shortcut else ""))
        a.setCheckable(checkable)
        if fn:
            a.triggered.connect(fn)
        self.addAction(a)
        return a

    def _make_actions(self):
        self.acts = {}
        a = self.acts
        a["open"] = self._act("Mở", "open", self.open_dialog, "Ctrl+O")
        a["save"] = self._act("Lưu", "save", self.save, "Ctrl+S")
        a["saveas"] = self._act("Lưu thành", "saveas", self.save_as, "Ctrl+Shift+S")
        a["print"] = self._act("In", "print", self.print_doc, "Ctrl+P")
        a["undo"] = self._act("Hoàn tác", "undo", lambda: self._tab_call(lambda t: t.pdf.undo()), "Ctrl+Z")
        a["redo"] = self._act("Làm lại", "redo", lambda: self._tab_call(lambda t: t.pdf.redo()), "Ctrl+Y")
        a["zoomin"] = self._act("Phóng to", "zoomin", lambda: self._zoom(1.2), "Ctrl+=")
        a["zoomout"] = self._act("Thu nhỏ", "zoomout", lambda: self._zoom(1 / 1.2), "Ctrl+-")
        a["fitw"] = self._act("Vừa rộng", "fitw", lambda: self._fit("width"), "Ctrl+0")
        a["fitp"] = self._act("Vừa trang", "fitp", lambda: self._fit("page"), "Ctrl+9")
        a["find"] = self._act("Tìm kiếm", "search", self.show_find, "Ctrl+F")
        a["close"] = self._act("Đóng thẻ", "delete", lambda: self.close_tab(self.tabs.currentIndex()), "Ctrl+W")
        self.tool_group = QActionGroup(self)
        self.tool_group.setExclusive(True)
        tools = [("hand", "Bàn tay", "hand", "H"), ("select", "Chọn", "select", "V"),
                 ("zoom", "Kính lúp", "zoom", "Z"),
                 ("text", "Hộp chữ", "text", "T"), ("note", "Ghi chú dán", "note", "N"),
                 ("highlight", "Tô sáng", "highlight", "Ctrl+H"), ("underline", "Gạch chân", "underline", None),
                 ("strike", "Gạch ngang", "strike", None), ("squiggly", "Lượn sóng", "underline", None),
                 ("rect", "Chữ nhật", "rect", "R"), ("ellipse", "Elip", "ellipse", "E"),
                 ("line", "Đường thẳng", "line", "L"), ("arrow", "Mũi tên", "arrow", "A"),
                 ("polygon", "Đa giác", "polygon", None), ("cloud", "Đám mây", "cloud", "C"),
                 ("polyline", "Gấp khúc", "line", None), ("ink", "Vẽ tay", "ink", "P"),
                 ("stamp", "Con dấu", "stamp", None), ("symbol", "Ký hiệu", "symbol", None),
                 ("image", "Chèn ảnh", "image", None), ("measure", "Đo kích thước", "measure", "M"),
                 ("whiteout", "Tẩy trắng", "whiteout", None), ("redact", "Che thông tin", "redact", None),
                 ("edittext", "Sửa chữ", "edittext", "F2"), ("addtext", "Thêm chữ", "addtext", None),
                 ("region", "Chọn vùng", "region", "Ctrl+Shift+R"), ("crop", "Cắt lề", "crop", None),
                 ("sign_area", "Ký số", "sign", None)]
        for key, txt, ic, sc in tools:
            act = self._act(txt, ic, lambda _=False, k=key: self.set_tool(k), sc, checkable=True)
            self.tool_group.addAction(act)
            self.tool_actions[key] = act
        self.tool_actions["select"].setChecked(True)
        esc = QAction(self)
        esc.setShortcut(QKeySequence(Qt.Key_Escape))
        esc.triggered.connect(lambda: self.set_tool("select"))
        self.addAction(esc)

    def _toolbar(self, title):
        tb = QToolBar(title)
        tb.setIconSize(QSize(28, 28))
        tb.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        tb.setMovable(False)
        self.ribbon.addTab(tb, title)
        return tb

    def _btn(self, tb, text, ic, fn, menu=None, tip=None):
        a = QAction(icon(ic), text, self)
        a.setToolTip(tip or text)
        if fn:
            a.triggered.connect(fn)
        if menu is not None:
            a.setMenu(menu)
        tb.addAction(a)
        if menu is not None:
            w = tb.widgetForAction(a)
            if isinstance(w, QToolButton):
                w.setPopupMode(QToolButton.MenuButtonPopup if fn else QToolButton.InstantPopup)
        return a

    def _make_ribbon(self):
        T = self.tool_actions
        a = self.acts
        # --- Trang chủ
        tb = self._toolbar("Trang chủ")
        for k in ("open", "save", "saveas", "print"):
            tb.addAction(a[k])
        tb.addSeparator()
        tb.addAction(a["undo"])
        tb.addAction(a["redo"])
        tb.addSeparator()
        tb.addAction(T["hand"])
        tb.addAction(T["select"])
        tb.addAction(T["zoom"])
        tb.addAction(T["region"])
        tb.addSeparator()
        for k in ("zoomin", "zoomout", "fitw", "fitp", "find"):
            tb.addAction(a[k])
        tb.addSeparator()
        self._btn(tb, "Xoay trái", "rotl", lambda: self.rotate_pages(-90))
        self._btn(tb, "Xoay phải", "rotr", lambda: self.rotate_pages(90))
        tb.addSeparator()
        nav = self.left_dock.toggleViewAction()
        nav.setText("Điều hướng")
        nav.setIcon(icon("organize"))
        nav.setShortcut(QKeySequence("F4"))
        nav.setToolTip("Ẩn / hiện thanh Điều hướng (trang, dấu trang, ghi chú, chữ ký)  (F4)")
        self.addAction(nav)
        tb.addAction(nav)
        self._btn(tb, "Giao diện", "theme", self.toggle_theme, tip="Chuyển giao diện sáng / tối")
        # --- Trang
        tb = self._toolbar("Trang")
        self._btn(tb, "Xoay trái", "rotl", lambda: self.rotate_pages(-90))
        self._btn(tb, "Xoay phải", "rotr", lambda: self.rotate_pages(90))
        self._btn(tb, "Xoá trang", "delete", lambda: self.delete_pages(None))
        self._btn(tb, "Trích xuất", "extract", self.extract_pages, tip="Lưu các trang chọn thành file mới")
        self._btn(tb, "Trang trắng", "blank", self.insert_blank)
        self._btn(tb, "Chèn file", "insert", self.insert_file, tip="Chèn PDF/ảnh vào sau trang hiện tại")
        self._btn(tb, "Sao chép", "copy", lambda: self.page_panel.copy(), tip="Sao chép trang chọn (Ctrl+C)")
        self._btn(tb, "Cắt", "cut", lambda: self.page_panel.cut(), tip="Cắt trang chọn (Ctrl+X)")
        self._btn(tb, "Dán", "paste", lambda: self.page_panel.paste(), tip="Dán trang (Ctrl+V) – vào vị trí con trỏ chuột")
        self._btn(tb, "Tách trang", "splitone", lambda: self.page_panel.split_single(),
                  tip="Tách từng trang thành file PDF riêng")
        self._btn(tb, "Thành ảnh", "raster", self.rasterize_pages,
                  tip="Chuyển trang PDF thành ảnh và ghép lại đúng vị trí trang đó (khoá nội dung, gộp ghi chú/dấu)")
        self._btn(tb, "Lên", "up", lambda: self.page_panel.move_step(-1), tip="Đưa trang chọn lên 1 vị trí (Ctrl+↑)")
        self._btn(tb, "Xuống", "down", lambda: self.page_panel.move_step(1), tip="Đưa trang chọn xuống 1 vị trí (Ctrl+↓)")
        self._btn(tb, "Chuyển tới", "split", self.move_pages, tip="Chuyển các trang chọn tới vị trí số …")
        self._btn(tb, "Sắp xếp", "organize", lambda: self.page_panel.open_organizer(),
                  tip="Xem toàn bộ trang dạng lưới lớn, kéo thả sắp xếp")
        tb.addAction(T["crop"])
        tb.addSeparator()
        self._btn(tb, "Số trang", "pagenum", self.page_numbers, tip="Đánh số trang")
        self._btn(tb, "Đầu/Chân", "header", self.header_footer, tip="Đầu/Chân trang")
        self._btn(tb, "Dấu chìm", "watermark", self.watermark)
        # --- Ghi chú
        tb = self._toolbar("Ghi chú")
        tb.addAction(T["select"])
        for k in ("text", "note", "highlight", "underline", "strike"):
            tb.addAction(T[k])
        tb.addSeparator()
        for k in ("rect", "ellipse", "line", "arrow", "polygon", "cloud", "polyline", "ink"):
            tb.addAction(T[k])
        tb.addSeparator()
        T["stamp"].setMenu(self._stamp_menu())
        tb.addAction(T["stamp"])
        tb.widgetForAction(T["stamp"]).setPopupMode(QToolButton.MenuButtonPopup)
        T["symbol"].setMenu(self._symbol_menu())
        tb.addAction(T["symbol"])
        tb.widgetForAction(T["symbol"]).setPopupMode(QToolButton.MenuButtonPopup)
        tb.addAction(T["image"])
        tb.addAction(T["measure"])
        tb.addSeparator()
        self._btn(tb, "Kiểu", "settings", self.style_dialog, tip="Màu, nét, phông, tỉ lệ đo…")
        # --- Sửa nội dung
        tb = self._toolbar("Chỉnh sửa")
        tb.addAction(T["edittext"])
        tb.addAction(T["addtext"])
        tb.addAction(T["whiteout"])
        tb.addAction(T["redact"])
        self._btn(tb, "Áp dụng che", "redact", self.apply_redactions, tip="Xoá vĩnh viễn nội dung dưới vùng che")
        tb.addSeparator()
        self._btn(tb, "Làm phẳng", "stamp", self.flatten, tip="Gắn cố định ghi chú vào nội dung trang")
        self._btn(tb, "Thông tin", "info", self.doc_info, tip="Thông tin file")
        # --- Chuyển đổi
        tb = self._toolbar("Chuyển đổi")
        self._btn(tb, "Gộp file", "merge", self.merge, tip="Gộp nhiều PDF / ảnh thành 1 file")
        self._btn(tb, "Tách file", "split", lambda: self.split(), tip="Tách PDF: tự chọn trang (mỗi dòng 1 file), theo dải, cắt tại trang, mỗi N trang, lẻ/chẵn, bookmark, dung lượng")
        self._btn(tb, "PDF → Ảnh", "toimg", self.to_images)
        self._btn(tb, "PDF → Word", "toword", self.to_word, tip="PDF (kể cả bản scan) → Word, đọc chữ sửa được")
        self._btn(tb, "Ảnh → Word", "toword", self.images_to_word, tip="Ảnh chụp / ảnh scan → đọc chữ → Word sửa được")
        self._btn(tb, "Ảnh → PDF", "imgpdf", self.images_to_pdf)
        self._btn(tb, "Scan ảnh", "scan", self.scan, tip="Biến ảnh chụp điện thoại thành bản scan")
        self._btn(tb, "OCR", "ocr", self.ocr_layer, tip="Nhận dạng chữ cho PDF scan (tìm kiếm, copy được)")
        self._btn(tb, "Nén PDF", "compress", self.compress)
        tb.addSeparator()
        mc = QMenu(self)
        mc.addAction("Xuất cả trang hiện tại…", self.to_cad)
        mc.addAction("Kéo chọn 1 vùng trên bản vẽ rồi xuất…", lambda: (self.set_tool("region", direct="cad"),
                                                                      self.flash("Kéo chọn vùng bản vẽ cần xuất sang CAD.")))
        self._btn(tb, "PDF → CAD", "cad", self.to_cad, menu=mc, tip="Xuất bản vẽ PDF sang DWG/DXF đúng kích thước thật")
        # --- Bảo mật & ký
        tb = self._toolbar("Bảo mật && Ký số")
        self._btn(tb, "Mật khẩu", "lock", self.security)
        self._btn(tb, "Gỡ khoá", "unlock", self.security, tip="Gỡ mật khẩu")
        tb.addAction(T["redact"])
        tb.addSeparator()
        m = QMenu(self)
        m.addAction("Chọn vị trí khung chữ ký trên trang rồi ký", lambda: self.set_tool("sign_area"))
        m.addAction("Ký không hiển thị khung", lambda: self.sign(None, None))
        self._btn(tb, "Ký số", "sign", lambda: self.set_tool("sign_area"), menu=m)
        self._btn(tb, "Kiểm tra ký", "verify", self.verify, tip="Kiểm tra chữ ký")
        # --- In
        tb = self._toolbar("In ấn")
        tb.addAction(a["print"])
        self._btn(tb, "Nhiều trang", "nup", self.nup, tip="In 2, 4, 6, 8, 9, 16 trang thu nhỏ trên 1 tờ")
        self._btn(tb, "In vùng", "region", lambda: (self.set_tool("region", direct="print"),
                                                           self.flash("Kéo chọn khu vực bản vẽ cần in.")),
                  tip="Kéo chọn 1 khu vực trên bản vẽ, in vừa khổ hoặc đúng tỉ lệ")
        # --- Kết nối
        tb = self._toolbar("Kết nối")
        self.ai_toggle = self._btn(tb, "Claude AI", "ai", self.toggle_ai, tip="Mở khung trợ lý Claude")
        self.openwith_menu = QMenu(self)
        self.openwith_menu.aboutToShow.connect(self._fill_openwith)
        self._btn(tb, "Mở bằng…", "apps", None, menu=self.openwith_menu)
        self._btn(tb, "Ứng dụng", "apps", self.external_apps, tip="Ứng dụng ngoài")
        tb.addSeparator()
        self._btn(tb, "Plugin", "plugin", self.plugins)
        self._btn(tb, "Cài đặt", "settings", self.settings)
        self._btn(tb, "Cập nhật", "update", self.check_update)
        self._btn(tb, "Giới thiệu", "info", self.about)

    def _stamp_menu(self):
        m = QMenu(self)
        for text, color in A.STAMPS:
            m.addAction(text, lambda t=text, c=color: self._choose_stamp(t, c, None))
        m.addSeparator()
        m.addAction("Con dấu chữ tuỳ chỉnh…", self._custom_stamp)
        m.addAction("Con dấu từ ảnh (PNG)…", self._image_stamp)
        return m

    def _choose_stamp(self, text, color, img):
        for t in self._tabs():
            t.pending_stamp = (text, color, img)
        self.set_tool("stamp", default_size=(200, 60))
        self.flash(f"Kéo khung (hoặc bấm) trên trang để đóng dấu '{text or os.path.basename(img or '')}'")

    def _custom_stamp(self):
        t, ok = QInputDialog.getText(self, "Con dấu tuỳ chỉnh", "Nội dung con dấu:")
        if ok and t:
            from PySide6.QtWidgets import QColorDialog
            c = QColorDialog.getColor(Qt.red, self, "Màu con dấu")
            self._choose_stamp(t.upper(), c.name() if c.isValid() else "#C62828", None)

    def _image_stamp(self):
        from .util import user_dir
        p, _ = QFileDialog.getOpenFileName(self, "Chọn ảnh con dấu / chữ ký", os.path.join(user_dir(), "stamps"),
                                           "Ảnh (*.png *.jpg *.jpeg)")
        if p:
            # con dấu từ ảnh: qua trình xoá nền trước
            t = self.current_tab()
            if t is not None:
                from .imgedit import ImageEditDialog, png_bytes
                dlg = ImageEditDialog(self, p, "Con dấu từ ảnh – tự xoá phông nền")
                if not dlg.exec() or not dlg.result_png:
                    return
                import tempfile
                q = os.path.join(tempfile.gettempdir(), "phantom_stamp_clean.png")
                with open(q, "wb") as f:
                    f.write(dlg.result_png)
                p = q
            self._choose_stamp("", "", p)

    def _symbol_menu(self):
        m = QMenu(self)
        row = None
        for i, s in enumerate(A.SYMBOLS):
            m.addAction(f"{s}", lambda s=s: self._choose_symbol(s))
        return m

    def _choose_symbol(self, s):
        for t in self._tabs():
            t.pending_symbol = s
        self.set_tool("symbol", default_size=(24, 24))

    def _make_status(self):
        sb = QStatusBar()
        self.setStatusBar(sb)
        self.msg = QLabel()
        sb.addWidget(self.msg, 1)
        self.page_spin = PageBox()
        self.page_spin.setMinimumWidth(48)
        self.page_spin.setToolTip("Gõ số trang rồi Enter để chuyển tới")
        self.page_spin.editingFinished.connect(lambda: self._tab_call(lambda t: t.view.goto(self.page_spin.value() - 1)))
        self.page_total = QLabel("/ 0")
        sb.addPermanentWidget(QLabel("Trang"))
        sb.addPermanentWidget(self.page_spin)
        sb.addPermanentWidget(self.page_total)
        for k in ("zoomout",):
            b = QToolButton()
            b.setDefaultAction(self.acts[k])
            sb.addPermanentWidget(b)
        self.zoom_box = QComboBox(editable=True)
        self.zoom_box.addItems(["25%", "50%", "75%", "100%", "125%", "150%", "200%", "300%", "400%", "800%",
                                "Thực tế 1:1", "Vừa rộng", "Vừa trang"])
        self.zoom_box.setFixedWidth(100)
        self.zoom_box.activated.connect(self._zoom_box)
        self.zoom_box.lineEdit().returnPressed.connect(self._zoom_box)
        sb.addPermanentWidget(self.zoom_box)
        for k in ("zoomin", "fitw", "fitp"):
            b = QToolButton()
            b.setDefaultAction(self.acts[k])
            sb.addPermanentWidget(b)

    # =============================================================== tiện ích
    def apply_theme(self):
        QApplication.instance().setStyleSheet(DARK if config().get("theme") == "dark" else LIGHT)

    def toggle_theme(self):
        c = config()
        c["theme"] = "dark" if c.get("theme") != "dark" else "light"
        c.save()
        self.apply_theme()

    def flash(self, text, ms=6000):
        self.msg.setText(text)
        QTimer.singleShot(ms, lambda: self.msg.text() == text and self.msg.setText(""))

    def current_tab(self):
        w = self.tabs.currentWidget()
        return w if isinstance(w, DocTab) else None

    def _tabs(self):
        return [self.tabs.widget(i) for i in range(self.tabs.count())]

    def _tab_call(self, fn):
        t = self.current_tab()
        if t:
            return fn(t)
        return None

    def need_tab(self):
        t = self.current_tab()
        if t is None:
            QMessageBox.information(self, APP_NAME, "Hãy mở một file PDF trước.")
        return t

    def update_ui(self):
        has = self.current_tab() is not None
        self.tabs.setVisible(has)
        self.welcome.setVisible(not has)
        if not has:
            self._refresh_recent()
        for k in ("save", "saveas", "print", "undo", "redo", "zoomin", "zoomout", "fitw", "fitp", "find"):
            self.acts[k].setEnabled(has)
        t = self.current_tab()
        if t:
            self.page_spin.setMaximum(t.pdf.page_count)
            digits = len(str(t.pdf.page_count))
            self.page_spin.setFixedWidth(max(48, self.page_spin.fontMetrics().horizontalAdvance("0" * digits) + 26))
            self.page_total.setText(f"/ {t.pdf.page_count}")
            self.page_total.setMinimumWidth(self.page_total.fontMetrics().horizontalAdvance(f"/ {t.pdf.page_count}") + 8)
            self.page_spin.setValue(t.view.current_page + 1)
            title = t.pdf.name + (" *" if t.pdf.modified else "")
            self.tabs.setTabText(self.tabs.indexOf(t), short_title(t.pdf.name) + (" *" if t.pdf.modified else ""))
            self.tabs.setTabToolTip(self.tabs.indexOf(t), t.pdf.path or t.pdf.name)
            self.setWindowTitle(f"{short_title(t.pdf.name, 48)}{' *' if t.pdf.modified else ''} – {APP_NAME}")
            self.zoom_box.setEditText(f"{t.view.zoom / t.view.unit * 100:.0f}%")
        else:
            self.setWindowTitle(f"{APP_NAME} {VERSION}")
            self.page_total.setText("/ 0")

    def set_tool(self, tool, **opts):
        if tool in self.tool_actions:
            self.tool_actions[tool].setChecked(True)
        st = A.style()
        o = {"color": st["color"], "width": st["width"], "fmt": lambda v, st=st: A.format_measure(v, st)}
        if tool in ("highlight", "underline", "strike", "squiggly"):
            o["color"] = st.get(tool, "#FFEB3B")
        o.update(opts)
        for t in self._tabs():
            if tool == "image":
                t.pending_image = None
            t.view.set_tool(tool, **o)
        hints = {"zoom": "Kính lúp: kéo khung để phóng vùng đó · bấm = phóng to · chuột phải / Alt+bấm = thu nhỏ.",
                 "hand": "Giữ chuột kéo để di chuyển trang (luôn dùng được: giữ chuột GIỮA hoặc giữ phím Space).",
                 "image": "Kéo khung hoặc bấm vị trí cần chèn ảnh – ảnh sẽ được tự xoá phông nền trước khi chèn.",
                 "text": "Kéo khung để tạo hộp chữ.", "note": "Bấm vào vị trí cần ghi chú.",
                 "polygon": "Bấm từng đỉnh, bấm đúp để kết thúc.", "cloud": "Bấm từng đỉnh, bấm đúp để kết thúc.",
                 "polyline": "Bấm từng điểm, bấm đúp để kết thúc.", "edittext": "Bấm vào chữ cần sửa.",
                 "addtext": "Bấm vào vị trí cần thêm chữ.", "region": "Kéo chọn vùng – sau đó chọn thao tác.",
                 "crop": "Kéo chọn vùng giữ lại.", "sign_area": "Kéo khung vị trí hiển thị chữ ký.",
                 "measure": f"Kéo để đo. Tỉ lệ 1:{st['measure_scale']:g}, đơn vị {st['measure_unit']} "
                            "(đổi ở Ghi chú → Kiểu mặc định).",
                 "redact": "Kéo vùng cần che, rồi bấm 'Áp dụng che'.", "ink": "Giữ chuột và vẽ."}
        if tool in hints:
            self.flash(hints[tool])
        if hasattr(self, "propbar"):
            self.propbar.on_tool(tool)

    def _zoom(self, f):
        self._tab_call(lambda t: t.view.set_zoom(t.view.zoom * f))

    def _fit(self, mode):
        def go(t):
            t.view.fit_mode = mode
            t.view.apply_fit()
        self._tab_call(go)

    def _zoom_box(self, *a):
        txt = self.zoom_box.currentText()
        if txt.startswith("Vừa rộng"):
            return self._fit("width")
        if txt.startswith("Vừa trang"):
            return self._fit("page")
        if txt.startswith("Thực tế"):
            return self._tab_call(lambda t: t.view.zoom_actual())
        try:
            z = float(txt.replace("%", "").replace(",", ".").strip()) / 100
            self._tab_call(lambda t: t.view.set_zoom(z * t.view.unit))
        except ValueError:
            pass

    def open_dialog(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Mở file", config().get("last_dir", ""), OPEN_FILTER)
        for f in files:
            self.open_file(f)

    def open_file(self, path):
        path = os.path.abspath(path)
        for t in self._tabs():
            if t.pdf.path and os.path.normcase(t.pdf.path) == os.path.normcase(path):
                self.tabs.setCurrentWidget(t)
                return t
        pw = None
        try:
            probe = fitz.open(path)
            if probe.needs_pass:
                while True:
                    pw, ok = QInputDialog.getText(self, "File có mật khẩu", f"Nhập mật khẩu để mở\n{os.path.basename(path)}:",
                                                  QLineEdit.Password)
                    if not ok:
                        return None
                    if probe.authenticate(pw):
                        break
                    QMessageBox.warning(self, "Mật khẩu", "Sai mật khẩu.")
            probe.close()
            is_img = os.path.splitext(path)[1].lower() in (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".gif", ".webp")
            tab = DocTab(self, path, password=pw)
            tab.pdf.source_image = path if is_img else None
            if is_img:
                tab.pdf.path = None
                tab.pdf.set_modified(True)
        except Exception as e:
            QMessageBox.critical(self, "Mở file", f"Không mở được file:\n{path}\n\n{e}")
            return None
        self._add_tab(tab, os.path.basename(path))
        if not os.path.splitext(path)[1].lower() != ".pdf":
            config().add_recent(path)
        return tab

    def _add_tab(self, tab, title):
        i = self.tabs.addTab(tab, short_title(title))
        self.tabs.setTabToolTip(i, tab.pdf.path or title)
        tab.view.pageChanged.connect(lambda p, t=tab: self._page_changed(t, p))
        tab.view.zoomChanged.connect(lambda z, t=tab: self.current_tab() is t and
                                     self.zoom_box.setEditText(f"{z / t.view.unit * 100:.0f}%"))
        tab.view.pasteRequest.connect(lambda pos, t=tab: self.paste_into_view(t, pos))
        tab.view.signatureClicked.connect(lambda name, t=tab: self.show_signature(t, name))
        tab.view.annotSelected.connect(lambda sel, t=tab: self.propbar.on_selection(t, sel))
        tab.view.placementStarted.connect(lambda pl, t=tab: self.current_tab() is t and self.propbar.on_place_start(pl))
        tab.view.placementFinished.connect(lambda ok, t=tab: self.propbar.on_place_end(ok))
        tab.view.imageDropped.connect(lambda pno, pt, path, t=tab: t.insert_image(pno, pt, path))
        tab.view.filesDropped.connect(lambda files: [self.open_file(f) for f in files if os.path.isfile(f)])
        tab.pdf.modified_changed.connect(lambda *_: self.update_ui())
        cur = next((k for k, a in self.tool_actions.items() if a.isChecked()), "select")
        tab.view.set_tool(cur)
        self.tabs.setCurrentWidget(tab)
        self.update_ui()
        QTimer.singleShot(0, tab.view.setFocus)

    def new_from_bytes(self, data, title):
        tab = DocTab(self, None, data=data)
        self._add_tab(tab, title)
        tab.pdf.set_modified(True)
        return tab

    def _page_changed(self, tab, p):
        if tab is self.current_tab():
            self.page_spin.setValue(p + 1)
            it = self.thumbs.item(p)
            if it and not getattr(self.thumbs, "_hold", False) and len(self.thumbs.selectedItems()) <= 1:
                self.thumbs.blockSignals(True)
                self.thumbs.setCurrentItem(it)
                self.thumbs.scrollToItem(it)
                self.thumbs.blockSignals(False)

    def tab_changed(self, i):
        t = self.current_tab()
        if hasattr(self, "propbar"):
            self.propbar.set_tab(t)
        self.thumbs.set_tab(t)
        QTimer.singleShot(0, self.thumbs.fit_width)
        if self.left_tabs.currentIndex() == 3:
            self.refresh_signatures()
        self.refresh_bookmarks()
        self.refresh_annot_list()
        self._hits = None
        self.update_ui()

    def doc_changed(self, tab, kind):
        if tab is self.current_tab():
            if kind in ("pages", "reload"):
                self.thumbs.rebuild()
                self.refresh_bookmarks()
            else:
                self.thumbs.invalidate()
            if self.left_tabs.currentIndex() == 2:
                self.refresh_annot_list()
        self._hits = None
        self.update_ui()

    # ================================================================ dán vào trang
    def paste_into_view(self, tab, vpos):
        """Ctrl+V khi đang ở trang: trang -> chèn tại vị trí chuột; ảnh -> xoá nền rồi chèn vào trang."""
        from . import pageclip
        kind, data = pageclip.clipboard_content()
        it, pt = tab.view.page_at(vpos)
        if kind == "stamp":
            # ảnh sao chép từ PDF Phantom: dán đúng vị trí như trang gốc (trang dưới chuột / trang đang xem)
            pno = it.pno if it is not None else tab.view.current_page
            tab.paste_stamp(data, pno)
            return
        if kind == "image" or (kind == "files" and len(data) == 1 and data[0].lower().endswith(pageclip.IMG_EXT)):
            if it is None:
                it = tab.view.items[tab.view.current_page]
                from PySide6.QtCore import QPointF
                pt = QPointF(it.w / 2, it.h / 2)
            tab.insert_image(it.pno, (pt.x(), pt.y()), data if kind == "image" else data[0])
            return
        if kind in ("pages", "files"):
            at = (it.pno if pt.y() < it.h / 2 else it.pno + 1) if it is not None else tab.view.current_page + 1
            self.page_panel.paste(at)
            return
        self.flash("Bộ nhớ tạm chưa có trang / ảnh để dán.")

    # ================================================================ chữ ký
    def refresh_signatures(self, force=False):
        self.sig_list.clear()
        t = self.current_tab()
        if not t:
            return
        from . import siginfo
        data = t.pdf.original_bytes if (t.pdf.original_bytes and not t.pdf.modified) else t.pdf.doc.tobytes()
        key = (id(t), len(data), t.pdf.modified)
        if not force and getattr(t, "_sig_cache", (None,))[0] == key:
            res = t._sig_cache[1]
        else:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                res = siginfo.file_signatures(data)
            finally:
                QApplication.restoreOverrideCursor()
            t._sig_cache = (key, res)
        for src, i in res:
            ok = "✔" if i["ok"] else "✘"
            tm = i["time"].strftime("%d/%m/%Y %H:%M") if i.get("time") else ""
            it = QListWidgetItem(f"{ok} {i['signer'] or '(không rõ)'}\n{tm} · trang {i['page'] + 1 if i['page'] >= 0 else '?'}"
                                 f"\n{src}")
            it.setToolTip(siginfo.describe(i, merged=False))
            it.setForeground(QColor("#1B7F3A") if i["ok"] else QColor("#C62828"))
            it.setData(Qt.UserRole, ("sig", src, i))
            self.sig_list.addItem(it)
        # thông tin chữ ký đã gắn khi gộp / ghép trang
        for pno in range(t.pdf.page_count):
            for a in t.pdf.doc[pno].annots():
                if a.info.get("subject") == siginfo.SUBJECT and a.type[0] == fitz.PDF_ANNOT_TEXT:
                    c = a.info.get("content", "")
                    first = c.splitlines()[0].replace("CHỮ KÝ SỐ – ", "") if c else ""
                    tm = next((l.split(": ", 1)[1] for l in c.splitlines() if l.startswith("Thời gian ký")), "")
                    it = QListWidgetItem(f"🔑 {first}\n{tm} · trang {pno + 1}\n(thông tin chữ ký từ file gốc)")
                    it.setToolTip(c)
                    it.setData(Qt.UserRole, ("note", pno, a.xref))
                    self.sig_list.addItem(it)
        if self.sig_list.count() == 0:
            self.sig_list.addItem("File không có chữ ký số.")

    def show_signature(self, tab, field):
        from . import siginfo
        info = tab.view._sig_infos().get(field)
        if not info:
            QMessageBox.information(self, "Chữ ký số", f"Ô chữ ký '{field}' chưa được ký hoặc không đọc được.")
            return
        box = QMessageBox(self)
        box.setWindowTitle("Thông tin chữ ký số")
        box.setIcon(QMessageBox.Information if info["ok"] else QMessageBox.Warning)
        box.setText(("✔ Chữ ký số hợp lệ – nội dung nguyên vẹn từ khi ký" if info["ok"] else
                     "✘ Chữ ký không hợp lệ hoặc nội dung đã bị sửa sau khi ký"))
        box.setInformativeText(siginfo.describe(info, merged=False))
        box.addButton("Đóng", QMessageBox.AcceptRole)
        box.exec()

    def _sig_goto(self, it):
        t = self.current_tab()
        d = it.data(Qt.UserRole) if it else None
        if not t or not d:
            return
        if d[0] == "note":
            t.view.goto(d[1])
            t.view.select_annot((d[1], d[2]))
        else:
            i = d[2]
            if i["page"] >= 0 and d[1] == "Trong file này":
                t.view.goto(i["page"], max(0, i["rect"].y0 - 60) if i["rect"] else None)

    def _sig_open(self, it):
        t = self.current_tab()
        d = it.data(Qt.UserRole) if it else None
        if not t or not d or d[0] != "sig" or "embedded_index" not in d[2]:
            if d and d[0] == "note":
                QMessageBox.information(self, "Thông tin chữ ký số", it.toolTip())
            return
        k = d[2]["embedded_index"]
        doc = t.pdf.doc
        data = doc.embfile_get(k)
        nm = doc.embfile_info(k).get("filename") or "ban_goc.pdf"
        tab = self.new_from_bytes(data, nm)
        tab.pdf.original_bytes = data
        tab.pdf.set_modified(False)
        self.left_tabs.setCurrentIndex(3)

    def save(self):
        t = self.need_tab()
        if not t:
            return False
        if not t.pdf.path:
            return self.save_as()
        from .ops_sign import has_signatures
        if has_signatures(t.pdf.doc) and t.pdf.modified:
            box = QMessageBox(self)
            box.setWindowTitle("File có chữ ký số")
            box.setIcon(QMessageBox.Warning)
            box.setText("File này có CHỮ KÝ SỐ. Lưu đè toàn bộ sẽ làm chữ ký mất hiệu lực xác thực.\n\n"
                        "• 'Lưu bản sao giữ chữ ký': chỉ thêm ghi chú (cập nhật gia tăng) – chữ ký vẫn hợp lệ.\n"
                        "• 'Lưu đè': áp dụng mọi thay đổi (xoay/xoá trang, sửa chữ…).")
            keep = box.addButton("Lưu bản sao giữ chữ ký…", QMessageBox.AcceptRole)
            over = box.addButton("Lưu đè", QMessageBox.DestructiveRole)
            box.addButton("Huỷ", QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() is keep:
                from .widgets import ask_save, done_message
                p = ask_save(self, "Lưu bản sao giữ chữ ký", os.path.splitext(t.pdf.name)[0] + "_ghichu.pdf")
                if p:
                    t.pdf.save_incremental_copy(p)
                    done_message(self, "Đã lưu bản sao (chữ ký số giữ nguyên hiệu lực).", p)
                return False
            if box.clickedButton() is not over:
                return False
        try:
            t.pdf.save()
            self.flash(f"Đã lưu {t.pdf.path}")
            config().add_recent(t.pdf.path)
            self.update_ui()
            return True
        except Exception as e:
            QMessageBox.critical(self, "Lưu", f"Không lưu được:\n{e}\n\n(File có thể đang mở ở phần mềm khác.)")
            return False

    def save_as(self):
        t = self.need_tab()
        if not t:
            return False
        from .widgets import ask_save
        p = ask_save(self, "Lưu thành", t.pdf.name if t.pdf.name.lower().endswith(".pdf") else
                     os.path.splitext(t.pdf.name)[0] + ".pdf")
        if not p:
            return False
        try:
            t.pdf.save(p)
            config().add_recent(p)
            self.tabs.setTabToolTip(self.tabs.indexOf(t), p)
            self.update_ui()
            return True
        except Exception as e:
            QMessageBox.critical(self, "Lưu", str(e))
            return False

    def close_tab(self, i):
        t = self.tabs.widget(i)
        if t is None:
            return True
        if t.pdf.modified:
            self.tabs.setCurrentIndex(i)
            r = QMessageBox.question(self, "Đóng", f"Lưu thay đổi của '{t.pdf.name}'?",
                                     QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
            if r == QMessageBox.Cancel:
                return False
            if r == QMessageBox.Save and not self.save():
                return False
        self.tabs.removeTab(i)
        t.pdf.close()
        t.deleteLater()
        self.update_ui()
        return True

    def closeEvent(self, e):
        while self.tabs.count():
            if not self.close_tab(0):
                e.ignore()
                return
        s = QSettings("PC1", "PDFPhantom")
        s.setValue("geometry", self.saveGeometry())
        s.setValue("state", self.saveState())
        e.accept()

    def restore_layout(self):
        s = QSettings("PC1", "PDFPhantom")
        if s.value("geometry"):
            self.restoreGeometry(s.value("geometry"))
        if s.value("state"):
            self.restoreState(s.value("state"))
        # thanh Thuộc tính luôn nằm dòng riêng ngay dưới ribbon
        if self.toolBarArea(self.propbar) != Qt.TopToolBarArea or not self.toolBarBreak(self.propbar):
            self.addToolBar(Qt.TopToolBarArea, self.propbar)
            self.insertToolBarBreak(self.propbar)
        self.propbar.show()
        # thanh Điều hướng luôn hiện khi mở phần mềm (tránh bị đóng mất không tìm lại được)
        if not self.left_dock.isVisible() or self.left_dock.isFloating() and not self.left_dock.isVisible():
            self.left_dock.setFloating(False)
            self.addDockWidget(Qt.LeftDockWidgetArea, self.left_dock)
            self.left_dock.show()
        self.ensure_on_screen()

    def _panels_menu(self):
        m = QMenu(self)
        m.addAction(self.left_dock.toggleViewAction())
        m.addAction(self.ai_dock.toggleViewAction())
        m.addSeparator()
        m.addAction("Khôi phục bố cục mặc định", self.reset_layout)
        return m

    def reset_layout(self):
        for d, area in ((self.left_dock, Qt.LeftDockWidgetArea), (self.ai_dock, Qt.RightDockWidgetArea)):
            d.setFloating(False)
            self.addDockWidget(area, d)
        self.left_dock.show()
        self.resizeDocks([self.left_dock], [230], Qt.Horizontal)

    def ensure_on_screen(self):
        """Cửa sổ lưu ở màn hình phụ đã rút ra -> đưa về màn hình chính (tránh bị 'ẩn')."""
        from PySide6.QtGui import QGuiApplication
        geo = self.frameGeometry()
        screens = QGuiApplication.screens()
        visible = any(sc.availableGeometry().intersected(geo).width() > 200 and
                      sc.availableGeometry().intersected(geo).height() > 150 for sc in screens)
        if not visible:
            ag = QGuiApplication.primaryScreen().availableGeometry()
            w, h = min(1400, ag.width() - 40), min(880, ag.height() - 40)
            self.setGeometry(ag.x() + (ag.width() - w) // 2, ag.y() + (ag.height() - h) // 2, w, h)

    def bring_to_front(self):
        """Đưa cửa sổ lên trên cùng, nhận focus (Windows chặn 'cướp focus' nên dùng thêm WinAPI)."""
        self.ensure_on_screen()
        if self.isMinimized():
            self.showNormal()
        self.setWindowState((self.windowState() & ~Qt.WindowMinimized) | Qt.WindowActive)
        self.show()
        self.raise_()
        self.activateWindow()
        import sys
        if sys.platform.startswith("win"):
            try:
                import ctypes
                u = ctypes.windll.user32
                k = ctypes.windll.kernel32
                hwnd = int(self.winId())
                if u.IsIconic(hwnd):
                    u.ShowWindow(hwnd, 9)                       # SW_RESTORE
                fg = u.GetForegroundWindow()
                fg_thread = u.GetWindowThreadProcessId(fg, None)
                me = k.GetCurrentThreadId()
                if fg_thread and fg_thread != me:
                    u.AttachThreadInput(fg_thread, me, True)
                u.BringWindowToTop(hwnd)
                u.SetForegroundWindow(hwnd)
                # nhảy lên trên cùng rồi trả lại bình thường
                u.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040)   # HWND_TOPMOST
                u.SetWindowPos(hwnd, -2, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040)   # HWND_NOTOPMOST
                if fg_thread and fg_thread != me:
                    u.AttachThreadInput(fg_thread, me, False)
                u.FlashWindow(hwnd, True)
            except Exception:
                pass

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        for u in e.mimeData().urls():
            p = u.toLocalFile()
            if os.path.isfile(p):
                self.open_file(p)

    def print_doc(self):
        t = self.need_tab()
        if t:
            from .printing import print_document
            print_document(self, t.pdf.doc, t.pdf.name)

    # =============================================================== trang
    def _sel_pages(self):
        t = self.current_tab()
        if not t:
            return []
        return self.thumbs.selected_pages()

    def rasterize_pages(self, pages=None):
        t = self.need_tab()
        if not t:
            return
        from .dialog_raster import RasterDialog, rasterize
        d = RasterDialog(self, t, pages if pages is not None else self._sel_pages())
        if d.exec():
            rasterize(self, t, d.pages(), d.options())

    def rotate_pages(self, angle):
        t = self.need_tab()
        if t:
            t.pdf.rotate(self._sel_pages(), angle)

    def delete_pages(self, pages=None):
        t = self.need_tab()
        if not t:
            return
        pages = pages if pages is not None else self._sel_pages()
        if QMessageBox.question(self, "Xoá trang", f"Xoá {len(pages)} trang: {', '.join(str(p + 1) for p in pages[:15])}"
                                f"{'…' if len(pages) > 15 else ''}?") == QMessageBox.Yes:
            try:
                t.pdf.delete(pages)
            except Exception as e:
                QMessageBox.warning(self, "Xoá trang", str(e))

    def extract_pages(self):
        t = self.need_tab()
        if not t:
            return
        pages = self._sel_pages()
        txt, ok = QInputDialog.getText(self, "Trích xuất trang", "Các trang cần trích (vd 1-3, 5):",
                                       text=",".join(str(p + 1) for p in pages))
        if not ok:
            return
        pages = parse_pages(txt, t.pdf.page_count)
        from .widgets import ask_save, done_message
        p = ask_save(self, "Lưu trang trích xuất", os.path.splitext(t.pdf.name)[0] + "_trich.pdf")
        if p:
            t.pdf.extract(pages, p)
            done_message(self, f"Đã trích {len(pages)} trang.", p)

    def insert_blank(self):
        t = self.need_tab()
        if t:
            p = t.view.current_page
            t.pdf.insert_blank(p + 1, like=p)

    def insert_file(self):
        t = self.need_tab()
        if not t:
            return
        files, _ = QFileDialog.getOpenFileNames(self, "Chèn file", config().get("last_dir", ""), OPEN_FILTER)
        at = t.view.current_page + 1
        for f in files:
            n0 = t.pdf.page_count
            t.pdf.insert_file(f, at)
            at += t.pdf.page_count - n0

    def move_pages(self):
        t = self.need_tab()
        if not t:
            return
        pages = self._sel_pages()
        to, ok = QInputDialog.getInt(self, "Di chuyển trang", f"Chuyển {len(pages)} trang đang chọn tới trước trang số:\n"
                                     f"(nhập {t.pdf.page_count + 1} để đưa xuống cuối; cũng có thể kéo thả "
                                     f"thumbnail bên trái)", 1, 1, t.pdf.page_count + 1)
        if ok:
            before = len([p for p in pages if p < to - 1])
            t.pdf.move(pages, to - 1 - before)

    def page_numbers(self):
        t = self.need_tab()
        if not t:
            return
        from .dialogs import PageNumberDialog
        d = PageNumberDialog(self, t.pdf.doc, t.view.current_page)
        if d.exec():
            n = d.apply(t.pdf)
            self.flash(f"Đã đánh số {n} trang.")

    def header_footer(self):
        t = self.need_tab()
        if t:
            from .dialogs import HeaderFooterDialog
            d = HeaderFooterDialog(self)
            if d.exec():
                d.apply(t.pdf)

    def watermark(self):
        t = self.need_tab()
        if t:
            from .dialogs import WatermarkDialog
            d = WatermarkDialog(self)
            if d.exec():
                d.apply(t.pdf)

    # ============================================================== ghi chú
    def style_dialog(self):
        d = A.StyleDialog(self)
        if d.exec():
            d.save()
            cur = next((k for k, a in self.tool_actions.items() if a.isChecked()), "select")
            self.set_tool(cur)

    def apply_redactions(self):
        t = self.need_tab()
        if not t:
            return
        if QMessageBox.question(self, "Áp dụng che", "Xoá VĨNH VIỄN mọi nội dung nằm dưới các vùng che?") != QMessageBox.Yes:
            return
        t.pdf.snapshot()
        n = 0
        for page in t.pdf.doc:
            if any(a.type[0] == fitz.PDF_ANNOT_REDACT for a in page.annots()):
                page.apply_redactions()
                n += 1
        t.pdf.commit("content")
        self.flash(f"Đã áp dụng che trên {n} trang.")

    def flatten(self):
        t = self.need_tab()
        if t and QMessageBox.question(self, "Làm phẳng", "Gắn cố định toàn bộ ghi chú vào nội dung trang "
                                      "(không sửa/xoá được nữa)?") == QMessageBox.Yes:
            t.pdf.snapshot()
            t.pdf.doc.bake(annots=True, widgets=True)
            t.pdf.commit("reload")

    def refresh_annot_list(self):
        self.annot_list.clear()
        t = self.current_tab()
        if not t:
            return
        for pno in range(t.pdf.page_count):
            for a in t.pdf.doc[pno].annots():
                if a.type[0] in (fitz.PDF_ANNOT_POPUP, fitz.PDF_ANNOT_LINK, fitz.PDF_ANNOT_WIDGET):
                    continue
                info = a.info
                txt = (info.get("content") or "").replace("\n", " ")[:60]
                it = QListWidgetItem(f"Tr.{pno + 1} · {a.type[1]} · {info.get('title', '')}\n{txt}")
                it.setData(Qt.UserRole, (pno, a.xref))
                self.annot_list.addItem(it)

    def _annot_goto(self, it):
        t = self.current_tab()
        pno, xref = it.data(Qt.UserRole)
        page = t.pdf.doc[pno]
        a = page.load_annot(xref)
        if a:
            r = (a.rect * page.rotation_matrix).normalize()
            t.view.goto(pno, max(0, r.y0 - 60))
            t.view.select_annot((pno, xref))

    # ============================================================= dấu trang
    def refresh_bookmarks(self):
        self.bm_tree.clear()
        t = self.current_tab()
        if not t:
            return
        stack = [self.bm_tree.invisibleRootItem()]
        for lvl, title, page in t.pdf.doc.get_toc(simple=True):
            while len(stack) > lvl:
                stack.pop()
            while len(stack) < lvl:
                stack.append(stack[-1].child(stack[-1].childCount() - 1) if stack[-1].childCount() else stack[-1])
            it = QTreeWidgetItem([title])
            it.setData(0, Qt.UserRole, page)
            stack[-1].addChild(it)
            stack.append(it)
        self.bm_tree.expandToDepth(0)

    def _bm_goto(self, it):
        p = it.data(0, Qt.UserRole)
        if p and self.current_tab():
            self.current_tab().view.goto(p - 1)

    def _toc_from_tree(self):
        out = []

        def walk(item, lvl):
            for i in range(item.childCount()):
                c = item.child(i)
                out.append([lvl, c.text(0), c.data(0, Qt.UserRole) or 1])
                walk(c, lvl + 1)
        walk(self.bm_tree.invisibleRootItem(), 1)
        return out

    def _bm_save(self):
        t = self.current_tab()
        t.pdf.snapshot()
        t.pdf.doc.set_toc(self._toc_from_tree())
        t.pdf.set_modified(True)
        self.refresh_bookmarks()

    def bm_add(self):
        t = self.need_tab()
        if not t:
            return
        name, ok = QInputDialog.getText(self, "Thêm dấu trang", f"Tên dấu trang (trang {t.view.current_page + 1}):")
        if ok and name:
            it = QTreeWidgetItem([name])
            it.setData(0, Qt.UserRole, t.view.current_page + 1)
            sel = self.bm_tree.currentItem()
            (sel.parent() or self.bm_tree.invisibleRootItem()).addChild(it) if sel else self.bm_tree.addTopLevelItem(it)
            self._bm_save()

    def bm_rename(self):
        it = self.bm_tree.currentItem()
        if it:
            name, ok = QInputDialog.getText(self, "Đổi tên", "Tên mới:", text=it.text(0))
            if ok and name:
                it.setText(0, name)
                self._bm_save()

    def bm_delete(self):
        it = self.bm_tree.currentItem()
        if it:
            (it.parent() or self.bm_tree.invisibleRootItem()).removeChild(it)
            self._bm_save()

    # ================================================================ tìm kiếm
    def show_find(self):
        if self.need_tab():
            self.findbar.setVisible(True)
            t = self.current_tab()
            if t.view.selected_text:
                self.find_edit.setText(t.view.selected_text.split("\n")[0][:60])
            self.find_edit.setFocus()
            self.find_edit.selectAll()

    def find_next(self, step):
        t = self.current_tab()
        q = self.find_edit.text().strip()
        if not t or not q:
            return
        if self._hits is None:
            hits = []
            flags = 0 if self.find_case.isChecked() else None
            for pno in range(t.pdf.page_count):
                page = t.pdf.doc[pno]
                rm = page.rotation_matrix
                for r in page.search_for(q):
                    if self.find_case.isChecked():
                        txt = page.get_textbox(r)
                        if q not in txt:
                            continue
                    hits.append((pno, (r * rm).normalize()))
            self._hits = hits
            self._hit_idx = -1 if step > 0 else 0
        if not self._hits:
            self.find_info.setText("Không tìm thấy")
            t.view.show_hits([])
            return
        self._hit_idx = (self._hit_idx + step) % len(self._hits)
        self.find_info.setText(f"{self._hit_idx + 1}/{len(self._hits)}")
        t.view.show_hits(self._hits, self._hit_idx)

    # ============================================================= chuyển đổi
    def merge(self):
        from .dialogs import MergeDialog
        t = self.current_tab()
        init = [t.pdf.path] if t and t.pdf.path else None
        d = MergeDialog(self, init)
        while d.exec():
            if d.run():
                break

    def images_to_pdf(self):
        from .dialogs import MergeDialog
        d = MergeDialog(self)
        d.setWindowTitle("Ảnh → PDF")
        d.files.add_dialog()
        while d.exec():
            if d.run():
                break

    def split(self, selected=None):
        from .dialogs import SplitDialog
        t = self.current_tab()
        if selected is None and t:
            sel = self._sel_pages()
            selected = sel if len(sel) > 1 else None
        d = SplitDialog(self, t.pdf.path if t else None, t.pdf.page_count if t else 0, tab=t, selected=selected)
        # không chặn cửa sổ chính: vẫn bấm chọn trang ở bảng Trang rồi '+ Thêm trang đang chọn'
        d.setModal(False)
        d.setAttribute(Qt.WA_DeleteOnClose)
        self._split_dlg = d          # 'Tách file' -> hỏi thư mục lưu -> tách -> báo xong + Mở thư mục
        d.show()

    def to_images(self, pages_text=None):
        t = self.need_tab()
        if t:
            from .dialogs import ToImageDialog
            d = ToImageDialog(self, t.pdf.doc, t.view.current_page)
            if pages_text:
                d.rng.setText(pages_text)
            if d.exec():
                d.run()

    def to_images_selected(self):
        self.to_images(",".join(str(p + 1) for p in self._sel_pages()))

    def to_word(self, files=None):
        from .dialogs import ToWordDialog
        t = self.current_tab()
        path = None
        if t:
            src_img = getattr(t.pdf, "source_image", None)
            if src_img and not t.pdf.modified:
                path = src_img                     # ảnh đang mở: dùng ảnh gốc để nắn + đọc chữ tốt hơn
            elif t.pdf.modified or not t.pdf.path:
                import tempfile
                path = os.path.join(tempfile.gettempdir(), os.path.splitext(t.pdf.name)[0] + ".pdf")
                t.pdf.doc.save(path)
            else:
                path = t.pdf.path
        d = ToWordDialog(self, path, t.pdf.page_count if t else 0, files=files)
        if d.exec():
            d.run()

    def images_to_word(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Chọn ảnh chụp / ảnh scan văn bản", config().get("last_dir", ""),
                                                "Ảnh (*.jpg *.jpeg *.png *.bmp *.tif *.tiff *.webp)")
        if files:
            config()["last_dir"] = os.path.dirname(files[0])
            self.to_word(files)

    def to_cad(self):
        t = self.need_tab()
        if t:
            from .dialog_cad import CadExportDialog
            CadExportDialog(self, t.pdf, t.view.current_page).exec()

    def scan(self):
        from .dialog_scan import ScanDialog
        files, _ = QFileDialog.getOpenFileNames(self, "Chọn ảnh chụp văn bản", config().get("last_dir", ""),
                                                "Ảnh (*.jpg *.jpeg *.png *.bmp *.tif *.tiff *.webp)")
        if files:
            config()["last_dir"] = os.path.dirname(files[0])
            ScanDialog(self, files).exec()

    def ocr_layer(self):
        t = self.need_tab()
        if t:
            from .dialogs import OcrLayerDialog
            d = OcrLayerDialog(self, t.pdf)
            if d.exec():
                d.run()

    def compress(self):
        t = self.need_tab()
        if t:
            from .dialogs import CompressDialog
            d = CompressDialog(self, t.pdf)
            if d.exec():
                d.run()

    def nup(self):
        t = self.need_tab()
        if t:
            from .dialogs import NupDialog
            NupDialog(self, t.pdf).exec()

    # ============================================================== bảo mật
    def security(self):
        t = self.need_tab()
        if t:
            from .dialogs import SecurityDialog
            SecurityDialog(self, t.pdf).exec()

    def sign(self, pno, rect):
        t = self.need_tab()
        if not t:
            return
        from .dialog_sign import SignDialog
        d = SignDialog(self, t.pdf, pno if pno is not None else t.view.current_page, rect)
        d.exec()
        self.set_tool("select")
        if d.out_path:
            pass

    def verify(self):
        t = self.need_tab()
        if not t:
            return
        from .dialog_sign import VerifyDialog
        import tempfile
        path = t.pdf.path
        if not path or t.pdf.modified:
            path = os.path.join(tempfile.gettempdir(), "phantom_verify.pdf")
            with open(path, "wb") as f:
                f.write(t.pdf.original_bytes or t.pdf.doc.tobytes())
        VerifyDialog(self, path).exec()

    def doc_info(self):
        t = self.need_tab()
        if not t:
            return
        d = t.pdf.doc
        m = d.metadata or {}
        p0 = d[0].rect
        from .ops_sign import has_signatures
        info = (f"Tên file: {t.pdf.name}\nĐường dẫn: {t.pdf.path or '(chưa lưu)'}\n"
                f"Dung lượng: {human_size(len(t.pdf.original_bytes or b''))}\nSố trang: {d.page_count}\n"
                f"Khổ trang 1: {p0.width * 25.4 / 72:.0f} × {p0.height * 25.4 / 72:.0f} mm\n"
                f"Phiên bản PDF: {m.get('format', '')}\nMã hoá: {m.get('encryption') or 'Không'}\n"
                f"Chữ ký số: {'Có' if has_signatures(d) else 'Không'}\n"
                f"Tiêu đề: {m.get('title', '')}\nTác giả: {m.get('author', '')}\n"
                f"Phần mềm tạo: {m.get('creator', '')} / {m.get('producer', '')}\n"
                f"Ngày tạo: {m.get('creationDate', '')}")
        QMessageBox.information(self, "Thông tin tài liệu", info)

    # ================================================================== AI
    def toggle_ai(self):
        self.ai_dock.setVisible(not self.ai_dock.isVisible())

    def ask_ai_text(self, text):
        self.ai_dock.show()
        self.ai_panel.scope.setCurrentIndex(3)
        self.ai_panel.input.setPlainText("Giải thích / phân tích đoạn này: ")
        self.ai_panel.input.setFocus()

    def ask_ai_image(self, pix):
        import base64
        self.ai_dock.show()
        if not config().get("claude_api_key"):
            QMessageBox.information(self, "Claude", "Chưa có API key. Vào Kết nối → Cài đặt → Claude AI.")
            return
        q, ok = QInputDialog.getMultiLineText(self, "Hỏi Claude về vùng chọn", "Câu hỏi:",
                                              "Đọc và giải thích nội dung vùng này (bảng, ký hiệu, ghi chú bản vẽ).")
        if not ok:
            return
        p = self.ai_panel
        p.history.append({"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                         "data": base64.b64encode(pix.tobytes("png")).decode()}},
            {"type": "text", "text": q}]})
        p._append("Anh", q + "  [kèm ảnh vùng chọn]")
        from .ai import ClaudeWorker
        p.send_btn.setEnabled(False)
        p.worker = ClaudeWorker(p.history, config().get("claude_model"), config().get("claude_api_key"))
        p.worker.finished_ok.connect(p._done)
        p.worker.failed.connect(p._fail)
        p.worker.start()

    def _fill_openwith(self):
        from .ai import external_apps, open_with
        self.openwith_menu.clear()
        t = self.current_tab()
        for app in external_apps():
            act = self.openwith_menu.addAction(app["name"])
            act.setEnabled(bool(t and t.pdf.path))
            act.triggered.connect(lambda _=False, a=app: open_with(a, self.current_tab().pdf.path))
        self.openwith_menu.addSeparator()
        self.openwith_menu.addAction("Quản lý danh sách…", self.external_apps)

    def external_apps(self):
        from .ai import ExternalAppsDialog
        ExternalAppsDialog(self).exec()

    # ================================================================ plugin
    def add_plugin_action(self, tab, text, callback, ic, tip):
        if self.plugin_toolbar is None:
            self.plugin_toolbar = self._toolbar(tab)
        a = QAction(icon(ic), text, self)
        a.setToolTip(tip)
        a.triggered.connect(lambda: self._safe(callback))
        self.plugin_toolbar.addAction(a)
        return a

    def _safe(self, fn):
        try:
            fn()
        except Exception as e:
            import traceback
            QMessageBox.critical(self, "Plugin", f"Lỗi plugin:\n{e}\n\n{traceback.format_exc(limit=2)}")

    def plugins(self):
        from .plugins import PluginDialog
        PluginDialog(self, *self.plugins_loaded).exec()

    def settings(self):
        from .settings import SettingsDialog
        if SettingsDialog(self).exec():
            self.apply_theme()
            self.ai_panel._intro() if not self.ai_panel.history else None

    def check_update(self):
        from .plugins import check_update
        check_update(self)

    def about(self):
        QMessageBox.about(self, "Giới thiệu", f"<h2>{APP_NAME} {VERSION}</h2>"
                          "<p>Phần mềm xử lý PDF miễn phí, không quảng cáo, chạy hoàn toàn trên máy.</p>"
                          "<p>Xây dựng cho: Nguyễn Văn Luân – Chỉ huy trưởng, Công ty CP PC1 Mỹ Đình.</p>"
                          "<p>Nền tảng: PySide6 (Qt), PyMuPDF (MuPDF), pyHanko, pdf2docx, OpenCV, Tesseract OCR.</p>"
                          "<p>Phím tắt: Ctrl+O mở · Ctrl+S lưu · Ctrl+Z hoàn tác · Ctrl+F tìm · Ctrl+cuộn chuột phóng to · "
                          "V chọn · H bàn tay · T hộp chữ · F2 sửa chữ · Esc bỏ công cụ · Delete xoá ghi chú.</p>")
