"""Hệ thống tiện ích mở rộng (plugin) + kiểm tra cập nhật.

Cách viết plugin: tạo file .py trong thư mục plugins (cạnh phần mềm hoặc %APPDATA%/PDFPhantom/plugins)
có hàm register(api). Ví dụ xem plugins/vi_du_dong_dau.py.
"""
import importlib.util
import json
import os
import traceback
import urllib.request

from PySide6.QtWidgets import QMessageBox, QDialog, QVBoxLayout, QListWidget, QPushButton, QHBoxLayout, QLabel

from . import VERSION
from .util import app_dir, user_dir, resource_dir, config


class PluginAPI:
    """Giao diện để plugin thao tác với phần mềm."""

    def __init__(self, win, plugin_name):
        self.win = win
        self.plugin_name = plugin_name

    # --- giao diện
    def add_action(self, text, callback, icon="plugin", tooltip="", tab="Tiện ích"):
        return self.win.add_plugin_action(tab, text, callback, icon, tooltip or text)

    def message(self, text, title=None):
        QMessageBox.information(self.win, title or self.plugin_name, text)

    # --- tài liệu
    def current_tab(self):
        return self.win.current_tab()

    def current_document(self):
        t = self.win.current_tab()
        return t.pdf.doc if t else None

    def current_page_index(self):
        t = self.win.current_tab()
        return t.view.current_page if t else 0

    def begin_edit(self):
        """Gọi trước khi sửa tài liệu (để hoàn tác được)."""
        t = self.win.current_tab()
        if t:
            t.pdf.snapshot()

    def end_edit(self):
        """Gọi sau khi sửa xong để cập nhật hiển thị."""
        t = self.win.current_tab()
        if t:
            t.pdf.commit("reload")

    def open_file(self, path):
        self.win.open_file(path)


def plugin_dirs():
    out = []
    for d in (os.path.join(app_dir(), "plugins"), os.path.join(resource_dir(), "plugins"),
              os.path.join(user_dir(), "plugins")):
        if os.path.isdir(d) and d not in out:
            out.append(d)
    return out


def load_plugins(win):
    loaded, errors = [], []
    seen = set()
    # Bản Microsoft Store: không nạp mã bên ngoài (Store Policy 10.2.2)
    return loaded, errors
    for d in plugin_dirs():
        for f in sorted(os.listdir(d)):
            if not f.endswith(".py") or f.startswith("_") or f in seen:
                continue
            seen.add(f)
            path = os.path.join(d, f)
            name = os.path.splitext(f)[0]
            try:
                spec = importlib.util.spec_from_file_location(f"phantom_plugin_{name}", path)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                title = getattr(mod, "PLUGIN_NAME", name)
                if hasattr(mod, "register"):
                    mod.register(PluginAPI(win, title))
                loaded.append((title, getattr(mod, "PLUGIN_VERSION", ""), path))
            except Exception:
                errors.append((name, traceback.format_exc(limit=3)))
    return loaded, errors


class PluginDialog(QDialog):
    def __init__(self, win, loaded, errors):
        super().__init__(win)
        self.setWindowTitle("Tiện ích mở rộng (Plugin)")
        self.resize(600, 400)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Plugin đã nạp:"))
        lst = QListWidget()
        for t, v, p in loaded:
            lst.addItem(f"✔ {t} {v}   —   {p}")
        for n, e in errors:
            lst.addItem(f"✘ {n}: {e.splitlines()[-1]}")
        lay.addWidget(lst, 1)
        lay.addWidget(QLabel("Thêm plugin: chép file .py vào thư mục plugin rồi khởi động lại phần mềm.\n"
                             f"Thư mục plugin của anh: {os.path.join(user_dir(), 'plugins')}"))
        row = QHBoxLayout()
        b = QPushButton("Mở thư mục plugin")
        from .widgets import open_path
        b.clicked.connect(lambda: open_path(os.path.join(user_dir(), "plugins")))
        row.addWidget(b)
        row.addStretch()
        c = QPushButton("Đóng")
        c.clicked.connect(self.accept)
        row.addWidget(c)
        lay.addLayout(row)


def _vtuple(v):
    try:
        return tuple(int(x) for x in v.split("."))
    except Exception:
        return (0,)


def check_update(win, silent=False):
    url = config().get("update_url")
    if not url:
        if not silent:
            QMessageBox.information(win, "Cập nhật",
                                    f"Phiên bản hiện tại: {VERSION}\n\n"
                                    "Cách cập nhật: tải bộ cài phiên bản mới và chạy CAI_DAT.bat – cài đặt, "
                                    "chữ ký, plugin, lịch sử file của anh được giữ nguyên.\n\n"
                                    "Có thể khai báo địa chỉ kiểm tra cập nhật tự động trong Cài đặt → Cập nhật.")
        return
    try:
        with urllib.request.urlopen(url, timeout=8) as r:
            info = json.loads(r.read().decode("utf-8"))
        latest = info.get("version", "0")
        if _vtuple(latest) > _vtuple(VERSION):
            r = QMessageBox.question(win, "Có bản cập nhật",
                                     f"Phiên bản mới: {latest} (hiện tại {VERSION})\n\n{info.get('notes', '')}\n\n"
                                     "Mở trang tải về?")
            if r == QMessageBox.Yes and info.get("url"):
                import webbrowser
                webbrowser.open(info["url"])
        elif not silent:
            QMessageBox.information(win, "Cập nhật", f"Anh đang dùng phiên bản mới nhất ({VERSION}).")
    except Exception as e:
        if not silent:
            QMessageBox.warning(win, "Cập nhật", f"Không kiểm tra được cập nhật: {e}")
