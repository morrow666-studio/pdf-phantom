"""Tích hợp Claude (Anthropic API) ngay trong phần mềm: hỏi đáp, tóm tắt, trích xuất khối lượng,
soạn công văn trả lời từ nội dung PDF. Cần API key (console.anthropic.com).
Kết nối ứng dụng ngoài: mở file đang xem bằng Word, Excel, AutoCAD, Zalo… theo danh sách tự cấu hình."""
import base64
import json
import os
import ssl
import subprocess
import urllib.request

import pymupdf as fitz
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QTextCursor, QGuiApplication
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QTextBrowser, QPlainTextEdit, QPushButton,
                               QComboBox, QLabel, QMessageBox, QFileDialog, QDialog, QFormLayout, QLineEdit,
                               QListWidget, QListWidgetItem, QDialogButtonBox, QMenu)

from .util import config, parse_pages

API_URL = "https://api.anthropic.com/v1/messages"
SYSTEM = ("Bạn là trợ lý kỹ thuật cho chỉ huy trưởng công trường xây lắp điện (trạm biến áp, đường dây). "
          "Luôn trả lời bằng tiếng Việt, rõ ràng, có cấu trúc, đi thẳng vào vấn đề. Khi trích số liệu phải "
          "ghi rõ trang nguồn. Nếu tài liệu không có thông tin, nói rõ là không có, không tự suy đoán.")

QUICK = [
    ("Tóm tắt", "Tóm tắt nội dung chính của tài liệu thành các ý ngắn gọn, nêu rõ: loại văn bản, đơn vị ban hành, "
                "số/ngày, nội dung yêu cầu, thời hạn (nếu có)."),
    ("Trích khối lượng", "Trích toàn bộ bảng khối lượng / số liệu trong tài liệu thành bảng Markdown "
                         "(STT | Hạng mục | Đơn vị | Khối lượng | Ghi chú | Trang)."),
    ("Soạn công văn trả lời", "Dựa trên văn bản này, soạn dự thảo công văn trả lời của Công ty Cổ phần PC1 Mỹ Đình "
                              "(Ban chỉ huy công trường) theo thể thức văn bản hành chính Việt Nam (Nghị định 30/2020/NĐ-CP)."),
    ("Kiểm tra lỗi", "Rà soát tài liệu: lỗi chính tả, số liệu không khớp, thiếu chữ ký/ngày tháng, mâu thuẫn nội dung. "
                     "Liệt kê theo trang."),
    ("Việc cần làm", "Liệt kê các đầu việc/yêu cầu phải thực hiện từ tài liệu này: nội dung, đơn vị thực hiện, thời hạn."),
    ("Dịch sang Anh", "Dịch nội dung sang tiếng Anh chuyên ngành, giữ nguyên số liệu."),
]


class ClaudeWorker(QThread):
    finished_ok = Signal(str)
    failed = Signal(str)

    def __init__(self, messages, model, key, max_tokens=4096):
        super().__init__()
        self.messages, self.model, self.key, self.max_tokens = messages, model, key, max_tokens

    def run(self):
        body = json.dumps({"model": self.model, "max_tokens": self.max_tokens, "system": SYSTEM,
                           "messages": self.messages}).encode("utf-8")
        req = urllib.request.Request(API_URL, data=body, method="POST", headers={
            "x-api-key": self.key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=300, context=ssl.create_default_context()) as r:
                data = json.loads(r.read().decode("utf-8"))
            text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
            self.finished_ok.emit(text or "(không có nội dung trả về)")
        except urllib.error.HTTPError as e:
            try:
                msg = json.loads(e.read().decode("utf-8")).get("error", {}).get("message", "")
            except Exception:
                msg = ""
            hint = {401: "API key không đúng.", 403: "Key không có quyền dùng model này.",
                    404: "Tên model không đúng – vào Cài đặt để sửa.", 429: "Vượt giới hạn tần suất, thử lại sau.",
                    529: "Máy chủ Claude đang quá tải, thử lại sau."}.get(e.code, "")
            self.failed.emit(f"Lỗi {e.code}: {msg}\n{hint}")
        except Exception as e:
            self.failed.emit(f"Không kết nối được Claude: {e}\nKiểm tra mạng Internet / proxy công ty.")


class AIPanel(QWidget):
    """Khung chat Claude bên phải cửa sổ."""

    def __init__(self, main):
        super().__init__()
        self.main = main
        self.history = []
        self.worker = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        top = QHBoxLayout()
        self.scope = QComboBox()
        self.scope.addItems(["Trang hiện tại", "Toàn bộ tài liệu", "Dải trang…", "Đoạn chữ đang chọn",
                             "Không gửi tài liệu"])
        top.addWidget(QLabel("Gửi kèm:"))
        top.addWidget(self.scope, 1)
        self.rng = QLineEdit(placeholderText="vd 1-5")
        self.rng.setMaximumWidth(80)
        self.rng.setVisible(False)
        self.scope.currentIndexChanged.connect(lambda i: self.rng.setVisible(i == 2))
        top.addWidget(self.rng)
        lay.addLayout(top)
        qrow = QHBoxLayout()
        qrow.setSpacing(3)
        for lbl, prompt in QUICK[:3]:
            b = QPushButton(lbl)
            b.setToolTip(prompt)
            b.clicked.connect(lambda _, p=prompt: self.ask(p))
            qrow.addWidget(b)
        more = QPushButton("…")
        more.setProperty("small", True)
        more.setFixedWidth(28)
        m = QMenu(more)
        for lbl, prompt in QUICK[3:]:
            m.addAction(lbl, lambda p=prompt: self.ask(p))
        more.setMenu(m)
        qrow.addWidget(more)
        lay.addLayout(qrow)
        self.view = QTextBrowser()
        self.view.setOpenExternalLinks(True)
        lay.addWidget(self.view, 1)
        self.input = QPlainTextEdit(placeholderText="Hỏi Claude về tài liệu… (Ctrl+Enter để gửi)")
        self.input.setFixedHeight(80)
        self.input.installEventFilter(self)
        lay.addWidget(self.input)
        row = QHBoxLayout()
        self.send_btn = QPushButton("Gửi")
        self.send_btn.setObjectName("primary")
        self.send_btn.clicked.connect(lambda: self.ask(self.input.toPlainText()))
        for txt, fn in (("Xoá hội thoại", self.clear), ("Chép", self.copy_last), ("Lưu Word", self.save_word),
                        ("Thành ghi chú", self.to_note)):
            b = QPushButton(txt)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch()
        row.addWidget(self.send_btn)
        lay.addLayout(row)
        self.last_answer = ""
        self._intro()

    def _intro(self):
        if not config().get("claude_api_key"):
            self.view.setHtml("<p><b>Kết nối Claude</b></p><p>Để dùng trợ lý AI ngay trong phần mềm, vào "
                              "<b>Cài đặt → Claude AI</b> và dán <b>API key</b> (tạo tại "
                              "<a href='https://console.anthropic.com'>console.anthropic.com</a>, trả phí theo lượng dùng).</p>"
                              "<p>Không có API key? Dùng nút <b>Chép</b> trong menu chuột phải để sao chép chữ "
                              "rồi dán vào ứng dụng Claude.</p>")
        else:
            self.view.setHtml("<p>Xin chào anh! Chọn phạm vi gửi kèm rồi bấm nút nhanh hoặc gõ câu hỏi.</p>")

    def eventFilter(self, obj, e):
        from PySide6.QtCore import QEvent
        if obj is self.input and e.type() == QEvent.KeyPress and e.key() in (Qt.Key_Return, Qt.Key_Enter) \
                and e.modifiers() & Qt.ControlModifier:
            self.ask(self.input.toPlainText())
            return True
        return super().eventFilter(obj, e)

    def context_blocks(self):
        tab = self.main.current_tab()
        if tab is None or self.scope.currentIndex() == 4:
            return []
        doc = tab.pdf.doc
        idx = self.scope.currentIndex()
        if idx == 3:
            t = tab.view.selected_text
            return [{"type": "text", "text": f"Đoạn trích từ tài liệu '{tab.pdf.name}':\n{t}"}] if t else []
        if idx == 0:
            pages = [tab.view.current_page]
        elif idx == 2:
            pages = parse_pages(self.rng.text(), doc.page_count)
        else:
            pages = list(range(doc.page_count))
        blocks = []
        text_parts = []
        images = 0
        for p in pages:
            page = doc[p]
            t = page.get_text("text").strip()
            if len(t) > 30:
                text_parts.append(f"--- Trang {p + 1} ---\n{t}")
            elif images < 20:
                # trang scan: gửi ảnh để Claude đọc
                pix = page.get_pixmap(dpi=110)
                blocks.append({"type": "text", "text": f"Ảnh trang {p + 1}:"})
                blocks.append({"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                                           "data": base64.b64encode(pix.tobytes("png")).decode()}})
                images += 1
        full = "\n\n".join(text_parts)
        if len(full) > 400000:
            full = full[:400000] + "\n…(đã cắt bớt do quá dài)"
        if full:
            blocks.insert(0, {"type": "text", "text": f"Nội dung tài liệu '{tab.pdf.name}':\n{full}"})
        return blocks

    def ask(self, prompt):
        prompt = (prompt or "").strip()
        if not prompt:
            return
        key = config().get("claude_api_key")
        if not key:
            QMessageBox.information(self, "Claude", "Chưa có API key. Vào Cài đặt → Claude AI để nhập.")
            return
        if self.worker and self.worker.isRunning():
            return
        content = []
        if not self.history:
            content = self.context_blocks()
        content.append({"type": "text", "text": prompt})
        self.history.append({"role": "user", "content": content})
        self._append("Anh", prompt)
        self.input.clear()
        self.send_btn.setEnabled(False)
        self.send_btn.setText("Đang trả lời…")
        self.worker = ClaudeWorker(self.history, config().get("claude_model", "claude-sonnet-5-5"), key)
        self.worker.finished_ok.connect(self._done)
        self.worker.failed.connect(self._fail)
        self.worker.start()

    def _append(self, who, text, md=False):
        self.view.moveCursor(QTextCursor.End)
        color = "#EF6C00" if who == "Claude" else "#333"
        self.view.insertHtml(f"<p style='margin-top:10px'><b style='color:{color}'>{who}:</b></p>")
        if md:
            cur = self.view.textCursor()
            cur.movePosition(QTextCursor.End)
            cur.insertMarkdown(text + "\n")
        else:
            self.view.insertPlainText(text + "\n")
        self.view.moveCursor(QTextCursor.End)

    def _done(self, text):
        self.history.append({"role": "assistant", "content": text})
        self.last_answer = text
        self._append("Claude", text, md=True)
        self._reset_btn()

    def _fail(self, msg):
        self.history.pop()
        self._append("Lỗi", msg)
        self._reset_btn()

    def _reset_btn(self):
        self.send_btn.setEnabled(True)
        self.send_btn.setText("Gửi")

    def clear(self):
        self.history = []
        self.last_answer = ""
        self._intro()

    def copy_last(self):
        if self.last_answer:
            QGuiApplication.clipboard().setText(self.last_answer)

    def save_word(self):
        if not self.last_answer:
            return
        from .widgets import ask_save, done_message
        p = ask_save(self, "Lưu câu trả lời ra Word", "Claude_tra_loi.docx", "Word (*.docx)")
        if not p:
            return
        from docx import Document
        from docx.shared import Pt
        d = Document()
        st = d.styles["Normal"]
        st.font.name = "Times New Roman"
        st.font.size = Pt(13)
        for line in self.last_answer.splitlines():
            s = line.strip()
            if s.startswith("#"):
                d.add_heading(s.lstrip("# "), level=min(3, len(s) - len(s.lstrip("#"))))
            elif s.startswith(("- ", "* ")):
                d.add_paragraph(s[2:], style="List Bullet")
            else:
                d.add_paragraph(line.replace("**", ""))
        d.save(p)
        done_message(self, "Đã lưu file Word.", p)

    def to_note(self):
        tab = self.main.current_tab()
        if not tab or not self.last_answer:
            return
        from . import annots
        page = tab.pdf.doc[tab.view.current_page]
        tab.pdf.snapshot()
        annots.add_note(page, (20, 20), self.last_answer)
        tab.pdf.commit("annots")
        tab.view.refresh("annots", [tab.view.current_page])


# ----------------------------------------------------------- ứng dụng ngoài
DEFAULT_APPS = [
    {"name": "Microsoft Word", "path": "winword.exe"},
    {"name": "Microsoft Excel", "path": "excel.exe"},
    {"name": "Trình duyệt web mặc định", "path": "__browser__"},
    {"name": "Thư mục chứa file", "path": "__folder__"},
]


def external_apps():
    return config().get("external_apps") or DEFAULT_APPS


def open_with(app, path):
    p = app.get("path", "")
    if p == "__folder__":
        if os.name == "nt":
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        else:
            subprocess.Popen(["xdg-open", os.path.dirname(path)])
        return
    if p == "__browser__":
        import webbrowser
        webbrowser.open("file:///" + path.replace("\\", "/"))
        return
    if os.name == "nt" and not os.path.isabs(p):
        subprocess.Popen(f'start "" "{p}" "{path}"', shell=True)
    else:
        subprocess.Popen([p, path])


class ExternalAppsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Kết nối ứng dụng ngoài")
        self.resize(560, 380)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Các ứng dụng hiện trong menu 'Mở bằng…' (file đang xem sẽ được mở bằng ứng dụng đó):"))
        self.list = QListWidget()
        for a in external_apps():
            self._add(a["name"], a["path"])
        lay.addWidget(self.list, 1)
        f = QFormLayout()
        self.name = QLineEdit(placeholderText="vd: AutoCAD 2020")
        self.path = QLineEdit(placeholderText=r"vd: C:\Program Files\Autodesk\AutoCAD 2020\acad.exe")
        b = QPushButton("…")
        b.setProperty("small", True)
        b.clicked.connect(self.pick)
        r = QHBoxLayout()
        r.addWidget(self.path, 1)
        r.addWidget(b)
        f.addRow("Tên:", self.name)
        f.addRow("Đường dẫn .exe:", r)
        lay.addLayout(f)
        row = QHBoxLayout()
        ba = QPushButton("Thêm")
        ba.clicked.connect(lambda: self._add(self.name.text(), self.path.text()) if self.name.text() else None)
        bd = QPushButton("Xoá mục chọn")
        bd.clicked.connect(lambda: self.list.takeItem(self.list.currentRow()))
        row.addWidget(ba)
        row.addWidget(bd)
        row.addStretch()
        lay.addLayout(row)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.save)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _add(self, name, path):
        it = QListWidgetItem(f"{name}   —   {path}")
        it.setData(Qt.UserRole, {"name": name, "path": path})
        self.list.addItem(it)

    def pick(self):
        p, _ = QFileDialog.getOpenFileName(self, "Chọn chương trình", r"C:\Program Files", "Chương trình (*.exe)")
        if p:
            self.path.setText(p)
            if not self.name.text():
                self.name.setText(os.path.splitext(os.path.basename(p))[0])

    def save(self):
        config()["external_apps"] = [self.list.item(i).data(Qt.UserRole) for i in range(self.list.count())]
        config().save()
        self.accept()
