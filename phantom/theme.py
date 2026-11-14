"""Giao diện: bảng màu sáng/tối và bộ biểu tượng vẽ bằng mã (không cần file ảnh)."""
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor, QFont, QPainterPath, QPen

ACCENT = "#EF6C00"      # tím Phantom

LIGHT = f"""
* {{ font-family: 'Segoe UI', Arial; font-size: 10pt; }}
QMainWindow, QDialog {{ background: #F4F5F8; }}
QTabWidget#ribbon::pane {{ border: none; background: #FFFFFF; border-bottom: 1px solid #D9DCE3; }}
QTabWidget#ribbon > QTabBar::tab {{ padding: 6px 16px; background: transparent; color: #333; border: none; }}
QTabWidget#ribbon > QTabBar::tab:selected {{ background: #FFFFFF; color: {ACCENT}; border-bottom: 3px solid {ACCENT}; font-weight: 600; }}
QTabWidget#ribbon > QTabBar::tab:hover {{ color: {ACCENT}; }}
QToolBar {{ background: #FFFFFF; border: none; spacing: 2px; padding: 2px; }}
QToolButton {{ border: 1px solid transparent; border-radius: 6px; padding: 3px 5px; color: #222; }}
QToolButton:hover {{ background: #FFF3E0; border-color: #FFCC80; }}
QToolButton:checked {{ background: #FFE0B2; border-color: {ACCENT}; }}
QTabWidget#docs::pane {{ border: none; }}
QTabWidget#docs > QTabBar::tab {{ padding: 5px 12px; background: #E6E8EE; border: 1px solid #D0D4DC; border-bottom: none; margin-right: 2px; border-top-left-radius: 6px; border-top-right-radius: 6px; }}
QTabWidget#docs > QTabBar::tab:selected {{ background: #FFFFFF; color: {ACCENT}; }}
QGraphicsView {{ background: #8A8F99; border: none; }}
QDockWidget::title {{ background: #ECEEF3; padding: 5px; font-weight: 600; }}
QListWidget {{ background: #FAFBFC; border: none; }}
QListWidget::item:selected {{ background: #FFE0B2; color: #000; border-radius: 4px; }}
QPushButton {{ background: #FFFFFF; border: 1px solid #C8CCD5; border-radius: 6px; padding: 5px 14px; min-width: 16px; }}
QPushButton[small="true"] {{ padding: 3px 2px; }}
QPushButton:hover {{ border-color: {ACCENT}; color: {ACCENT}; }}
QPushButton#primary {{ background: {ACCENT}; color: white; border: none; font-weight: 600; }}
QPushButton#primary:hover {{ background: #D35400; color: white; }}
QGroupBox {{ border: 1px solid #D5D9E0; border-radius: 6px; margin-top: 10px; padding-top: 8px; background: #FFFFFF; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {ACCENT}; font-weight: 600; }}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit {{ background: #FFFFFF; border: 1px solid #C8CCD5; border-radius: 4px; padding: 3px; }}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus {{ border-color: {ACCENT}; }}
QStatusBar {{ background: #FFFFFF; border-top: 1px solid #D9DCE3; }}
QProgressBar {{ border: 1px solid #C8CCD5; border-radius: 4px; text-align: center; background: #FFF; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 3px; }}
"""

DARK = f"""
* {{ font-family: 'Segoe UI', Arial; font-size: 10pt; color: #E6E6EB; }}
QMainWindow, QDialog, QWidget {{ background: #1F2026; }}
QTabWidget#ribbon::pane {{ border: none; background: #2A2B33; }}
QTabWidget#ribbon > QTabBar::tab {{ padding: 6px 16px; background: transparent; border: none; }}
QTabWidget#ribbon > QTabBar::tab:selected {{ background: #2A2B33; color: #FFB74D; border-bottom: 3px solid #FF9800; font-weight: 600; }}
QToolBar {{ background: #2A2B33; border: none; }}
QToolButton {{ border: 1px solid transparent; border-radius: 6px; padding: 3px 5px; }}
QToolButton:hover {{ background: #4A3A2A; }}
QToolButton:checked {{ background: #7A4A1A; border-color: #FF9800; }}
QTabWidget#docs > QTabBar::tab {{ padding: 5px 12px; background: #2A2B33; margin-right: 2px; }}
QTabWidget#docs > QTabBar::tab:selected {{ background: #3A3B45; color: #FFB74D; }}
QGraphicsView {{ background: #15161A; border: none; }}
QDockWidget::title {{ background: #2A2B33; padding: 5px; }}
QListWidget {{ background: #24252C; border: none; }}
QListWidget::item:selected {{ background: #7A4A1A; }}
QPushButton {{ background: #2E2F38; border: 1px solid #474956; border-radius: 6px; padding: 5px 14px; }}
QPushButton[small="true"] {{ padding: 3px 2px; }}
QPushButton#primary {{ background: #F57C00; border: none; color: white; font-weight: 600; }}
QGroupBox {{ border: 1px solid #3A3B45; border-radius: 6px; margin-top: 10px; padding-top: 8px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; color: #FFB74D; }}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit {{ background: #2A2B33; border: 1px solid #474956; border-radius: 4px; padding: 3px; }}
QMenu {{ background: #2A2B33; }} QMenu::item:selected {{ background: #7A4A1A; }}
QProgressBar::chunk {{ background: #F57C00; }}
"""

# (ký tự, màu nền)
ICONS = {
    "open": ("📂", "#F5A623"), "save": ("💾", "#4A90E2"), "saveas": ("🖫", "#4A90E2"),
    "print": ("🖨", "#555B66"), "undo": ("↶", "#555B66"), "redo": ("↷", "#555B66"),
    "zoomin": ("＋", "#2D9CDB"), "zoomout": ("－", "#2D9CDB"), "fitw": ("⇔", "#2D9CDB"), "fitp": ("⛶", "#2D9CDB"),
    "hand": ("✋", "#EF6C00"), "select": ("➤", "#EF6C00"),
    "rotl": ("⟲", "#27AE60"), "rotr": ("⟳", "#27AE60"), "delete": ("🗑", "#EB5757"),
    "extract": ("⇪", "#27AE60"), "insert": ("⊕", "#27AE60"), "blank": ("▭", "#27AE60"), "crop": ("✂", "#27AE60"),
    "text": ("T", "#E2574C"), "note": ("🗨", "#F2C94C"), "highlight": ("🖍", "#F2C94C"),
    "underline": ("U̲", "#2F80ED"), "strike": ("S̶", "#EB5757"), "rect": ("▢", "#E2574C"),
    "ellipse": ("◯", "#E2574C"), "line": ("╱", "#E2574C"), "arrow": ("➝", "#E2574C"),
    "ink": ("✎", "#9B51E0"), "image": ("🖼", "#27AE60"), "stamp": ("✔", "#EB5757"),
    "symbol": ("★", "#F2994A"), "whiteout": ("⬜", "#828282"), "cloud": ("☁", "#2F80ED"),
    "polygon": ("⬠", "#E2574C"), "measure": ("📏", "#F2994A"),
    "edittext": ("✍", "#E2574C"), "addtext": ("Ａ", "#E2574C"),
    "merge": ("⧉", "#2D9CDB"), "split": ("⫽", "#2D9CDB"), "toimg": ("🖼", "#2D9CDB"),
    "toword": ("W", "#2B579A"), "scan": ("📷", "#2D9CDB"), "ocr": ("🔍", "#2D9CDB"),
    "imgpdf": ("⧉", "#27AE60"), "pagenum": ("#", "#F2994A"), "header": ("☰", "#F2994A"),
    "watermark": ("💧", "#2F80ED"), "lock": ("🔒", "#EB5757"), "unlock": ("🔓", "#27AE60"),
    "sign": ("✒", "#EF6C00"), "verify": ("🛡", "#27AE60"), "nup": ("▦", "#555B66"),
    "region": ("⬚", "#555B66"), "ai": ("✦", "#D97757"), "apps": ("⧉", "#555B66"),
    "plugin": ("🧩", "#9B51E0"), "settings": ("⚙", "#555B66"), "update": ("⟳", "#27AE60"),
    "info": ("ℹ", "#2D9CDB"), "compress": ("🗜", "#2D9CDB"), "theme": ("◐", "#555B66"),
    "search": ("🔎", "#555B66"), "cad": ("⌖", "#C62828"),
    "up": ("▲", "#F57C00"), "down": ("▼", "#F57C00"), "top": ("⤒", "#F57C00"), "bottom": ("⤓", "#F57C00"),
    "dup": ("⧉", "#27AE60"), "copy": ("⎘", "#1E88E5"), "cut": ("✂", "#E53935"), "paste": ("📋", "#1E88E5"),
    "splitone": ("⇶", "#8E24AA"), "raster": ("▣", "#0288D1"), "zoom": ("🔍", "#2D9CDB"), "imgedit": ("✨", "#8E24AA"), "sig": ("🔑", "#2E7D32"), "organize": ("▦", "#F57C00"), "bookmark": ("🔖", "#F2994A"), "redact": ("█", "#000000"),
}

_icon_cache = {}


def icon(name, size=32):
    key = (name, size)
    if key in _icon_cache:
        return _icon_cache[key]
    ch, color = ICONS.get(name, ("•", "#777"))
    pm = QPixmap(size * 2, size * 2)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    r = QRectF(2, 2, size * 2 - 4, size * 2 - 4)
    path.addRoundedRect(r, size * 0.45, size * 0.45)
    base = QColor(color)
    p.fillPath(path, base)
    p.setPen(QPen(base.darker(125), 2))
    p.drawPath(path)
    f = QFont("Segoe UI Symbol")
    f.setPixelSize(int(size * 1.15))
    f.setBold(True)
    p.setFont(f)
    p.setPen(QColor("white"))
    p.drawText(r, Qt.AlignCenter, ch)
    p.end()
    ic = QIcon(pm)
    _icon_cache[key] = ic
    return ic


def app_icon():
    from .util import asset
    import os
    p = asset("icon.ico")
    if os.path.exists(p):
        return QIcon(p)
    return icon("ai")
