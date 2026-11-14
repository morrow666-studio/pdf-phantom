"""Mô hình tài liệu: bọc pymupdf.Document + hoàn tác/làm lại + lưu an toàn."""
import os
import shutil
import tempfile

import pymupdf as fitz
from PySide6.QtCore import QObject, Signal


class PdfDocument(QObject):
    changed = Signal(str)          # loại thay đổi: 'pages', 'content', 'annots', 'reload'
    modified_changed = Signal(bool)

    MAX_UNDO = 30

    def __init__(self, path=None, data=None, password=None, parent=None):
        super().__init__(parent)
        self.path = path
        self.password = password
        if data is None and path:
            with open(path, "rb") as f:
                data = f.read()
        if data is None:
            self.doc = fitz.open()
            self.doc.new_page()
        else:
            # mở từ bộ nhớ -> không khoá file trên Windows, lưu đè được
            self.doc = fitz.open("pdf", data) if self._is_pdf(path, data) else self._image_doc(path, data)
        if self.doc.needs_pass and password:
            if not self.doc.authenticate(password):
                raise PermissionError("Sai mật khẩu")
        self.original_bytes = data
        self.undo_stack = []
        self.redo_stack = []
        self._modified = False

    @staticmethod
    def _is_pdf(path, data):
        return (data[:5] == b"%PDF-") or (path or "").lower().endswith(".pdf")

    @staticmethod
    def _image_doc(path, data):
        ext = os.path.splitext(path or "x.png")[1].lstrip(".") or "png"
        img = fitz.open(stream=data, filetype=ext)
        pdf = fitz.open("pdf", img.convert_to_pdf())
        img.close()
        return pdf

    # ------------------------------------------------------------ thuộc tính
    @property
    def name(self):
        if self.path:
            return os.path.basename(self.path)
        src = getattr(self, "source_image", None)
        return os.path.splitext(os.path.basename(src))[0] + ".pdf" if src else "Tài liệu mới.pdf"

    @property
    def page_count(self):
        return self.doc.page_count

    def __getitem__(self, i):
        return self.doc[i]

    @property
    def modified(self):
        return self._modified

    def set_modified(self, v=True):
        if v != self._modified:
            self._modified = v
            self.modified_changed.emit(v)

    # ------------------------------------------------------- hoàn tác
    def snapshot(self):
        """Gọi TRƯỚC mỗi thao tác sửa."""
        try:
            self.undo_stack.append(self.doc.tobytes(garbage=0, deflate=False))
        except Exception:
            return
        if len(self.undo_stack) > self.MAX_UNDO:
            self.undo_stack.pop(0)
        self.redo_stack.clear()

    def _restore(self, data):
        self.doc.close()
        self.doc = fitz.open("pdf", data)
        if self.doc.needs_pass and self.password:
            self.doc.authenticate(self.password)

    def undo(self):
        if not self.undo_stack:
            return False
        self.redo_stack.append(self.doc.tobytes())
        self._restore(self.undo_stack.pop())
        self.version = getattr(self, "version", 0) + 1
        self.set_modified(True)
        self.changed.emit("reload")
        return True

    def redo(self):
        if not self.redo_stack:
            return False
        self.undo_stack.append(self.doc.tobytes())
        self._restore(self.redo_stack.pop())
        self.version = getattr(self, "version", 0) + 1
        self.set_modified(True)
        self.changed.emit("reload")
        return True

    def commit(self, kind="content"):
        self.version = getattr(self, "version", 0) + 1
        self.set_modified(True)
        self.changed.emit(kind)

    # ------------------------------------------------------- thao tác trang
    def rotate(self, pages, angle):
        self.snapshot()
        for p in pages:
            pg = self.doc[p]
            pg.set_rotation((pg.rotation + angle) % 360)
        self.commit("pages")

    def delete(self, pages):
        if len(pages) >= self.doc.page_count:
            raise RuntimeError("Không thể xoá toàn bộ trang.")
        self.snapshot()
        self.doc.delete_pages(sorted(set(pages)))
        self.commit("pages")

    def reorder(self, order):
        self.snapshot()
        self.doc.select(order)
        self.commit("pages")

    def move(self, pages, to):
        order = list(range(self.doc.page_count))
        moving = [order[p] for p in sorted(pages)]
        rest = [p for p in order if p not in moving]
        to = max(0, min(to, len(rest)))
        new = rest[:to] + moving + rest[to:]
        self.reorder(new)

    def duplicate(self, pages):
        self.snapshot()
        for k, p in enumerate(sorted(pages)):
            self.doc.fullcopy_page(p + k, p + k + 1)
        self.commit("pages")

    def insert_blank(self, at, like=None):
        self.snapshot()
        ref = self.doc[like if like is not None else max(0, min(at, self.doc.page_count - 1))]
        self.doc.new_page(at, width=ref.rect.width, height=ref.rect.height)
        self.commit("pages")

    def insert_file(self, path, at):
        self.snapshot()
        ext = os.path.splitext(path)[1].lower()
        src = fitz.open(path)
        if not src.is_pdf:
            pdf = fitz.open("pdf", src.convert_to_pdf())
            src.close()
            src = pdf
        self.doc.insert_pdf(src, start_at=at)
        src.close()
        self.commit("pages")

    def insert_bytes(self, data, at):
        """Chèn các trang từ PDF trong bộ nhớ (dán trang). Trả về số trang đã chèn."""
        self.snapshot()
        src = fitz.open("pdf", data)
        n = src.page_count
        at = max(0, min(at, self.doc.page_count))
        self.doc.insert_pdf(src, start_at=at, annots=True, links=True)
        src.close()
        self.commit("pages")
        return n

    def extract(self, pages, out_path):
        out = fitz.open()
        for p in pages:
            out.insert_pdf(self.doc, from_page=p, to_page=p)
        out.save(out_path, garbage=3, deflate=True)
        out.close()

    def crop(self, pages, rect_visible):
        """Cắt lề trang theo vùng (toạ độ hiển thị)."""
        self.snapshot()
        for p in pages:
            pg = self.doc[p]
            r = (rect_visible * pg.derotation_matrix).normalize()
            r = r & pg.mediabox
            if not r.is_empty:
                pg.set_cropbox(r)
        self.commit("pages")

    # --------------------------------------------------------------- lưu
    def save(self, path=None, **kw):
        path = path or self.path
        if not path:
            raise RuntimeError("Chưa có tên file")
        fd, tmp = tempfile.mkstemp(suffix=".pdf", dir=os.path.dirname(os.path.abspath(path)))
        os.close(fd)
        try:
            opts = dict(garbage=3, deflate=True)
            opts.update(kw)
            if self.doc.is_encrypted or self.doc.needs_pass:
                opts.setdefault("encryption", fitz.PDF_ENCRYPT_KEEP)
            self.doc.save(tmp, **opts)
            shutil.move(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
        self.path = path
        with open(path, "rb") as f:
            self.original_bytes = f.read()
        self.set_modified(False)

    def save_incremental_copy(self, path):
        """Lưu kiểu gia tăng (giữ hiệu lực chữ ký số đã có) - ghi các thay đổi nối sau bản gốc."""
        with open(path, "wb") as f:
            f.write(self.original_bytes)
        tmpdoc = fitz.open(path)
        # chép lại các chú thích mới sang bản gốc
        for i in range(min(tmpdoc.page_count, self.doc.page_count)):
            src = self.doc[i]
            dst = tmpdoc[i]
            existing = {a.xref for a in dst.annots()}
            for a in src.annots():
                if a.xref in existing:
                    continue
                try:
                    _copy_annot(a, dst)
                except Exception:
                    pass
        tmpdoc.save(path, incremental=True, encryption=fitz.PDF_ENCRYPT_KEEP)
        tmpdoc.close()

    def close(self):
        try:
            self.doc.close()
        except Exception:
            pass


def _copy_annot(a, page):
    t = a.type[0]
    info = a.info
    col = a.colors
    if t == fitz.PDF_ANNOT_FREE_TEXT:
        n = page.add_freetext_annot(a.rect, info.get("content", ""), fontsize=11)
    elif t == fitz.PDF_ANNOT_TEXT:
        n = page.add_text_annot(a.rect.tl, info.get("content", ""))
    elif t in (fitz.PDF_ANNOT_HIGHLIGHT, fitz.PDF_ANNOT_UNDERLINE, fitz.PDF_ANNOT_STRIKE_OUT):
        quads = a.vertices
        q = [fitz.Quad(quads[i:i + 4]) for i in range(0, len(quads), 4)]
        n = {fitz.PDF_ANNOT_HIGHLIGHT: page.add_highlight_annot,
             fitz.PDF_ANNOT_UNDERLINE: page.add_underline_annot,
             fitz.PDF_ANNOT_STRIKE_OUT: page.add_strikeout_annot}[t](q)
    elif t == fitz.PDF_ANNOT_SQUARE:
        n = page.add_rect_annot(a.rect)
    elif t == fitz.PDF_ANNOT_CIRCLE:
        n = page.add_circle_annot(a.rect)
    elif t == fitz.PDF_ANNOT_INK:
        n = page.add_ink_annot(a.vertices)
    elif t == fitz.PDF_ANNOT_LINE:
        v = a.vertices
        n = page.add_line_annot(v[0], v[1])
    else:
        return
    if col:
        n.set_colors(stroke=col.get("stroke"), fill=col.get("fill"))
    n.set_border(width=a.border.get("width", 1))
    n.set_opacity(a.opacity if a.opacity >= 0 else 1)
    n.set_info(info)
    n.update()
