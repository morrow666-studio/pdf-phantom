"""Thành phần giao diện dùng chung: luồng chạy nền + tiến trình, danh sách file kéo thả."""
import os
import traceback

from PySide6.QtCore import Qt, QThread, Signal, QSize
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QLabel, QProgressBar, QPushButton, QListWidget,
                               QListWidgetItem, QHBoxLayout, QFileDialog, QMessageBox, QAbstractItemView,
                               QWidget, QApplication)

from .util import config, human_size


class Worker(QThread):
    progress = Signal(int, int, str)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn, *a, **kw):
        super().__init__()
        self.fn, self.a, self.kw = fn, a, kw
        self.cancelled = False

    def cb(self, i, n, msg=""):
        self.progress.emit(i, n, msg)
        return not self.cancelled

    def run(self):
        try:
            res = self.fn(*self.a, progress=self.cb, **self.kw)
            self.done.emit(res)
        except Exception as e:
            traceback.print_exc()
            self.failed.emit(str(e) or e.__class__.__name__)


class ProgressDialog(QDialog):
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(420)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        lay = QVBoxLayout(self)
        self.lbl = QLabel("Đang xử lý…")
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        self.btn = QPushButton("Huỷ")
        lay.addWidget(self.lbl)
        lay.addWidget(self.bar)
        lay.addWidget(self.btn, alignment=Qt.AlignRight)
        self.result = None
        self.error = None

    def update_progress(self, i, n, msg):
        if n:
            self.bar.setRange(0, n)
            self.bar.setValue(i)
        self.lbl.setText(msg or "Đang xử lý…")


def run_task(parent, title, fn, *a, **kw):
    """Chạy fn(progress=...) trong luồng nền, hiện hộp tiến trình. Trả về (ok, kết_quả|lỗi)."""
    dlg = ProgressDialog(title, parent)
    w = Worker(fn, *a, **kw)
    w.progress.connect(dlg.update_progress)

    def ok(res):
        dlg.result = res
        dlg.accept()

    def bad(msg):
        dlg.error = msg
        dlg.reject()

    def cancel():
        w.cancelled = True
        dlg.lbl.setText("Đang dừng…")

    w.done.connect(ok)
    w.failed.connect(bad)
    dlg.btn.clicked.connect(cancel)
    w.start()
    dlg.exec()
    w.wait()
    if dlg.error:
        QMessageBox.critical(parent, title, f"Có lỗi xảy ra:\n{dlg.error}")
        return False, dlg.error
    if w.cancelled:
        return False, "Đã huỷ"
    return True, dlg.result


class FileList(QWidget):
    """Danh sách file có kéo-thả sắp xếp, thêm/xoá/lên/xuống."""

    def __init__(self, filters="Tất cả (*.*)", parent=None):
        super().__init__(parent)
        self.filters = filters
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.list = QListWidget()
        self.list.setDragDropMode(QAbstractItemView.InternalMove)
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list.setAcceptDrops(True)
        self.list.setMinimumHeight(220)
        self.list.setIconSize(QSize(20, 20))
        lay.addWidget(self.list, 1)
        col = QVBoxLayout()
        for txt, fn in (("Thêm file…", self.add_dialog), ("Thêm thư mục…", self.add_folder),
                        ("Lên ▲", lambda: self.move(-1)), ("Xuống ▼", lambda: self.move(1)),
                        ("Sắp xếp A→Z", self.sort), ("Xoá", self.remove), ("Xoá hết", self.list.clear)):
            b = QPushButton(txt)
            b.clicked.connect(fn)
            col.addWidget(b)
        col.addStretch()
        lay.addLayout(col)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        self.add([u.toLocalFile() for u in e.mimeData().urls()])

    def add(self, paths):
        for p in paths:
            if os.path.isdir(p):
                self.add(sorted(os.path.join(p, f) for f in os.listdir(p)))
                continue
            if not os.path.isfile(p):
                continue
            it = QListWidgetItem(f"{os.path.basename(p)}    ({human_size(os.path.getsize(p))})")
            it.setData(Qt.UserRole, p)
            it.setToolTip(p)
            self.list.addItem(it)

    def add_dialog(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Chọn file", config().get("last_dir", ""), self.filters)
        if files:
            config()["last_dir"] = os.path.dirname(files[0])
            self.add(files)

    def add_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Chọn thư mục", config().get("last_dir", ""))
        if d:
            exts = [x.strip("*") for x in self.filters.split("(")[-1].rstrip(")").split()]
            self.add([os.path.join(d, f) for f in sorted(os.listdir(d))
                      if any(f.lower().endswith(x.lower()) for x in exts) or "*.*" in self.filters])

    def move(self, step):
        rows = sorted({self.list.row(i) for i in self.list.selectedItems()}, reverse=step > 0)
        for r in rows:
            nr = r + step
            if 0 <= nr < self.list.count():
                it = self.list.takeItem(r)
                self.list.insertItem(nr, it)
                it.setSelected(True)

    def sort(self):
        items = sorted(self.paths(), key=lambda p: os.path.basename(p).lower())
        self.list.clear()
        self.add(items)

    def remove(self):
        for it in self.list.selectedItems():
            self.list.takeItem(self.list.row(it))

    def paths(self):
        return [self.list.item(i).data(Qt.UserRole) for i in range(self.list.count())]


def ask_save(parent, title, default_name, filters="PDF (*.pdf)"):
    d = config().get("last_dir", "")
    p, _ = QFileDialog.getSaveFileName(parent, title, os.path.join(d, default_name), filters)
    if p:
        config()["last_dir"] = os.path.dirname(p)
        config().save()
    return p


def ask_dir(parent, title):
    d = QFileDialog.getExistingDirectory(parent, title, config().get("last_dir", ""))
    if d:
        config()["last_dir"] = d
    return d


def open_path(path):
    """Mở file/thư mục bằng ứng dụng mặc định của Windows."""
    import subprocess
    import sys
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception:
        pass


def done_message(parent, text, path=None, folder=None):
    box = QMessageBox(parent)
    box.setWindowTitle("Hoàn thành")
    box.setIcon(QMessageBox.Information)
    box.setText(text)
    ob = of = None
    if path:
        ob = box.addButton("Mở file", QMessageBox.AcceptRole)
    if folder or path:
        of = box.addButton("Mở thư mục", QMessageBox.ActionRole)
    box.addButton("Đóng", QMessageBox.RejectRole)
    box.exec()
    c = box.clickedButton()
    if c is ob and path:
        win = parent.window() if parent else None
        if path.lower().endswith(".pdf") and hasattr(win, "open_file"):
            win.open_file(path)
        else:
            open_path(path)
    elif c is of:
        open_path(folder or os.path.dirname(path))
    return c is ob
