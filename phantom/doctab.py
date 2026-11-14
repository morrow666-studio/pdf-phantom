"""Một thẻ tài liệu: khung xem + xử lý kết quả công cụ (tạo ghi chú, sửa chữ...)."""
import os

import pymupdf as fitz
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication, QImage
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QInputDialog, QMessageBox, QDialog, QFormLayout,
                               QPlainTextEdit, QComboBox, QDoubleSpinBox, QCheckBox, QDialogButtonBox,
                               QMenu, QFileDialog, QHBoxLayout, QLineEdit, QLabel)

from . import annots as A
from .annots import ColorButton
from .document import PdfDocument
from .util import config, FONT_LABELS
from .viewer import DocView, pix_to_qimage


class TextInputDialog(QDialog):
    def __init__(self, title, label, text="", parent=None, with_font=False, span=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(460)
        f = QFormLayout(self)
        self.edit = QPlainTextEdit(text)
        self.edit.setFixedHeight(110 if not span else 70)
        f.addRow(label, self.edit)
        self.with_font = with_font
        if with_font:
            from .util import guess_family
            fam, b, i = guess_family(span["font"]) if span else (config().get("default_font", "times"), False, False)
            if span:
                b = b or bool(span.get("flags", 0) & 16)
                i = i or bool(span.get("flags", 0) & 2)
            self.family = QComboBox()
            for k, v in FONT_LABELS.items():
                self.family.addItem(v, k)
            self.family.setCurrentIndex(list(FONT_LABELS).index(fam) if fam in FONT_LABELS else 0)
            self.size = QDoubleSpinBox(minimum=3, maximum=200, decimals=1,
                                       value=round(span["size"], 1) if span else 12)
            self.bold = QCheckBox("Đậm")
            self.bold.setChecked(b)
            self.italic = QCheckBox("Nghiêng")
            self.italic.setChecked(i)
            self.color = ColorButton("#%06X" % span["color"] if span else "#000000")
            row = QHBoxLayout()
            for w in (self.size, self.bold, self.italic, self.color):
                row.addWidget(w)
            f.addRow("Phông chữ:", self.family)
            f.addRow("Cỡ / kiểu / màu:", row)
            if span:
                f.addRow(QLabel(f"<i>Phông gốc trong file: {span['font']}</i>"))
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Đồng ý")
        bb.button(QDialogButtonBox.Cancel).setText("Huỷ")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        f.addRow(bb)

    def text(self):
        return self.edit.toPlainText()


class DocTab(QWidget):
    status = Signal(str)

    def __init__(self, main, path=None, data=None, password=None):
        super().__init__()
        self.main = main
        self.pdf = PdfDocument(path, data, password, self)
        self.view = DocView(self.pdf, self)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.view)
        self.pdf.changed.connect(self.on_changed)
        self.view.toolFinished.connect(self.on_tool)
        self.view.annotEditRequest.connect(self.edit_annot)
        self.view.stampEditRequest.connect(self.edit_stamp)
        self.view.stampCopyRequest.connect(self.copy_stamp)
        self.view.stampDupRequest.connect(self.duplicate_stamp)
        self.view.stampGroupDeleteRequest.connect(self.delete_stamp_group)
        self.view.annotDeleteRequest.connect(self.delete_annot)
        self.view.annotMoved.connect(self.move_annot)
        self.view.contextAction.connect(self.on_context)
        self.pending_image = None
        self.pending_stamp = None
        self.pending_symbol = "✔"

    # ---------------------------------------------------------------
    def on_changed(self, kind):
        self.view.invalidate_words()
        self.view.refresh(kind)
        self.main.doc_changed(self, kind)

    def page(self, pno):
        return self.pdf.doc[pno]

    def _edit(self, pno, fn):
        """Bọc thao tác sửa: snapshot -> fn -> cập nhật."""
        self.pdf.snapshot()
        try:
            res = fn(self.page(pno))
        except Exception as e:
            self.pdf.undo_stack.pop() if self.pdf.undo_stack else None
            QMessageBox.critical(self, "Lỗi", str(e))
            return None
        self.pdf.set_modified(True)
        self.view.invalidate_words()
        self.view.refresh("annots", [pno])
        self.main.doc_changed(self, "annots")
        return res

    # --------------------------------------------------------- kết quả công cụ
    def on_tool(self, tool, pno, data):
        st = A.style()
        if tool == "text":
            d = TextInputDialog("Hộp chữ ghi chú", "Nội dung:", parent=self)
            if d.exec() and d.text().strip():
                self._edit(pno, lambda p: A.add_textbox(p, data["rect"], d.text(), st))
        elif tool == "note":
            d = TextInputDialog("Ghi chú dán", "Nội dung ghi chú:", parent=self)
            if d.exec():
                self._edit(pno, lambda p: A.add_note(p, data["point"], d.text(), st))
        elif tool in ("rect", "ellipse"):
            self._edit(pno, lambda p: A.add_shape(p, tool, data["rect"], st))
        elif tool in ("line", "arrow"):
            self._edit(pno, lambda p: A.add_line(p, data["p1"], data["p2"], st, arrow=(tool == "arrow")))
        elif tool == "measure":
            self._edit(pno, lambda p: A.add_measure(p, data["p1"], data["p2"], st))
        elif tool in ("polygon", "cloud", "polyline"):
            self._edit(pno, lambda p: A.add_poly(p, tool, data["points"], st))
        elif tool == "ink":
            self._edit(pno, lambda p: A.add_ink(p, data["points"], st))
        elif tool in ("highlight", "underline", "strike", "squiggly"):
            ws = A.words_in(self.page(pno), data["rect"])
            if not ws:
                self.main.flash("Không có chữ trong vùng chọn (trang scan? hãy chạy OCR trước) – "
                                "dùng hình chữ nhật tô màu thay thế.")
                return
            self._edit(pno, lambda p: A.add_markup(p, tool, A.line_rects(ws), st))
        elif tool == "whiteout":
            self._edit(pno, lambda p: A.add_whiteout(p, data["rect"]))
        elif tool == "redact":
            self._edit(pno, lambda p: A.add_redact(p, data["rect"]))
            self.main.flash("Đã đánh dấu vùng che (viền đỏ). Bấm 'Áp dụng che' để xoá vĩnh viễn nội dung.")
        elif tool == "stamp":
            text, color, img = self.pending_stamp or ("ĐÃ DUYỆT", "#C62828", None)
            if img:
                self._edit(pno, lambda p: A.add_image_stamp(p, data["rect"], img, title=os.path.basename(img)))
            else:
                pix, (w, h) = A.stamp_pixmap(text, color)
                self._edit(pno, lambda p: A.add_image_stamp(p, data["rect"], pix, title=text))
        elif tool == "image":
            if not self.pending_image:
                self.pending_image, _ = QFileDialog.getOpenFileName(self, "Chọn ảnh", config().get("last_dir", ""),
                                                                    "Ảnh (*.png *.jpg *.jpeg *.bmp *.gif *.tif *.webp)")
            if self.pending_image:
                r = data["rect"]
                self.insert_image(pno, ((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2), self.pending_image, rect=r)
        elif tool == "symbol":
            self._edit(pno, lambda p: A.add_symbol(p, data["rect"], self.pending_symbol, st["color"]))
        elif tool == "edittext":
            self.edit_text(pno, data["point"])
        elif tool == "addtext":
            d = TextInputDialog("Thêm chữ vào trang", "Nội dung:", parent=self, with_font=True)
            if d.exec() and d.text().strip():
                pt = data["point"]

                def go(p):
                    y = pt[1] + d.size.value() * 0.8
                    for k, line in enumerate(d.text().splitlines()):
                        A.insert_text_content(p, (pt[0], y + k * d.size.value() * 1.25), line, d.family.currentData(),
                                              d.size.value(), d.color.color, d.bold.isChecked(), d.italic.isChecked())
                self._edit(pno, go)
                self.pdf.changed.emit("content")
        elif tool == "region":
            direct = self.view.tool_opts.get("direct")
            if direct == "print":
                self.print_region(pno, data["rect"])
            elif direct == "cad":
                self.cad_region(pno, data["rect"])
            else:
                self.region_menu(pno, data["rect"])
        elif tool == "crop":
            self.crop(pno, data["rect"])
        elif tool == "sign_area":
            self.main.sign(pno, data["rect"])

    # ------------------------------------------------------------- chèn ảnh có xoá nền
    def insert_image(self, pno, point, src, rect=None):
        """Trình chỉnh ảnh (tự xoá phông nền) -> chế độ ĐẶT ẢNH: kéo, co giãn (Shift giữ tỉ lệ),
        xoay bằng chuột / gõ số, dịch từng chút bằng phím mũi tên -> Enter hoàn tất."""
        import pymupdf as fitz
        from .imgedit import ImageEditDialog
        try:
            dlg = ImageEditDialog(self, src)
        except Exception as e:
            QMessageBox.warning(self, "Chèn ảnh", str(e))
            return False
        if not dlg.exec() or not dlg.result_png:
            return False
        r = dlg.insert_rect(point[0], point[1], fitz.Rect(rect) if rect is not None else None)
        name = os.path.basename(src) if isinstance(src, str) else "Ảnh dán"
        self.place_image(pno, dlg.result_png, r, name)
        return True

    def place_image(self, pno, png, rect, name="Ảnh", opacity=1.0, on_cancel=None, on_commit=None):
        import pymupdf as fitz

        def done(ok, pno_, png_, rect_, opacity_):
            if not ok:
                if on_cancel:
                    on_cancel()
                self.main.flash("Đã huỷ chèn ảnh.")
                return
            pix = fitz.Pixmap(png_)
            self._edit(pno_, lambda p: A.add_image_stamp(p, rect_, pix, keep_ratio=False, title=name,
                                                           opacity=opacity_))
            if on_commit:
                on_commit()
            self.main.flash("Đã chèn ảnh. Bấm đúp vào ảnh để xoay, co giãn, dịch lại.")
        self.view.start_placement(pno, png, rect, done, opacity)
        self.main.flash("ĐẶT ẢNH: kéo để di chuyển · kéo góc để co giãn (giữ Shift = giữ tỉ lệ) · kéo nút tròn để xoay · "
                        "mũi tên dịch 0,5pt (Ctrl 0,1pt · Shift 5pt) · [ ] xoay 1° · Enter xong · Esc huỷ", 15000)

    def edit_stamp(self, pno, xref):
        """Đưa ảnh / con dấu đã chèn về chế độ đặt ảnh để xoay, co giãn, dịch lại."""
        import pymupdf as fitz
        page = self.page(pno)
        a = page.load_annot(xref)
        if a is None or a.type[0] != fitz.PDF_ANNOT_STAMP:
            return False
        pix = a.get_pixmap(matrix=fitz.Matrix(4, 4), alpha=True)
        png = pix.tobytes("png")
        r = (a.rect * page.rotation_matrix).normalize()
        name = a.info.get("content") or "Ảnh"
        op = a.opacity if a.opacity >= 0 else 1.0
        self.pdf.snapshot()
        page.delete_annot(a)
        self.view.select_annot(None)
        self.view.refresh("annots", [pno])

        def cancel():
            self.pdf.undo()                      # trả lại ảnh như cũ
        def commit():
            # bỏ bước trung gian (ảnh đã xoá) để Ctrl+Z quay thẳng về trước khi sửa
            if len(self.pdf.undo_stack) >= 2:
                self.pdf.undo_stack.pop()
        self.place_image(pno, png, r, name, op, on_cancel=cancel, on_commit=commit)
        return True

    # ------------------------------------------------- sao chép / nhân bản ảnh
    def _is_stamp(self, pno, xref):
        try:
            page = self.page(pno)                       # giữ trang sống trong lúc đọc ghi chú
            a = page.load_annot(xref)
            return a is not None and a.type[0] == fitz.PDF_ANNOT_STAMP
        except Exception:
            return False

    def copy_stamp(self, pno, xref):
        """Ctrl+C trên ảnh/con dấu đang chọn -> dán sang trang khác / file khác bằng Ctrl+V."""
        from . import pageclip
        if not self._is_stamp(pno, xref):
            return False
        d = A.stamp_image(self.pdf.doc, pno, xref)
        d["source"] = self.pdf.name
        pageclip.copy_stamp(d)
        self.main.flash("Đã sao chép ảnh. Sang trang / file khác bấm Ctrl+V – ảnh dán đúng vị trí cũ, "
                        "chỉnh lại được trước khi Enter.")
        return True

    def paste_stamp(self, d, pno, at=None):
        """Dán ảnh đã sao chép. at=None: đúng vị trí như trang gốc; at=(x, y): tâm ảnh tại điểm đó."""
        page = self.page(pno)
        pr = page.rect
        r = A.map_rect(d["rect"], d["page_w"], d["page_h"], pr.width, pr.height, "edge")
        if at is not None:
            w, h = r.width, r.height
            r = fitz.Rect(at[0] - w / 2, at[1] - h / 2, at[0] + w / 2, at[1] + h / 2)
        self.place_image(pno, d["png"], r, d.get("name", "Ảnh"), d.get("opacity", 1.0))

    def stamp_on_pages(self, d, pages, mode="edge"):
        """Đóng ảnh đã sao chép lên nhiều trang cùng lúc (Ctrl+V ở bảng Trang khi chọn nhiều trang)."""
        if not pages:
            return 0
        if len(pages) == 1:
            self.paste_stamp(d, pages[0])
            return 1
        pix = fitz.Pixmap(d["png"])
        self.pdf.snapshot()
        for p in pages:
            page = self.pdf.doc[p]
            r = A.map_rect(d["rect"], d["page_w"], d["page_h"], page.rect.width, page.rect.height, mode)
            A.add_image_stamp(page, r, pix, keep_ratio=False, title=d.get("name", "Ảnh"),
                              opacity=d.get("opacity", 1.0))
        self.pdf.set_modified(True)
        self.view.refresh("annots", pages)
        self.main.doc_changed(self, "annots")
        self.main.flash(f"Đã dán ảnh lên {len(pages)} trang đang chọn. Ctrl+Z để hoàn tác.")
        return len(pages)

    def duplicate_stamp(self, pno, xref):
        """Nhân bản ảnh sang nhiều trang của file này và/hoặc các file đang mở khác."""
        import uuid
        from .dialog_dup import DuplicateDialog
        if not self._is_stamp(pno, xref):
            return 0
        dlg = DuplicateDialog(self.main, self, pno)
        if not dlg.exec():
            return 0
        targets = dlg.targets()
        if not targets:
            self.main.flash("Chưa chọn trang / file nào để nhân bản.")
            return 0
        mode = dlg.pos.currentData()
        d = A.stamp_image(self.pdf.doc, pno, xref)
        pix = fitz.Pixmap(d["png"])
        gid = None
        if dlg.group.isChecked():
            gid = A.stamp_group(self.pdf.doc, xref) or uuid.uuid4().hex[:12]
            if not any(t is self for t, _ in targets):
                self.pdf.snapshot()
            A.set_stamp_group(self.pdf.doc, xref, gid)
        from PySide6.QtWidgets import QApplication
        QApplication.setOverrideCursor(Qt.WaitCursor)
        total = 0
        try:
            for t, pages in targets:
                t.pdf.snapshot()                       # 1 lần Ctrl+Z gỡ hết bản nhân trong file đó
                for p in pages:
                    page = t.pdf.doc[p]
                    r = A.map_rect(d["rect"], d["page_w"], d["page_h"], page.rect.width, page.rect.height, mode)
                    a = A.add_image_stamp(page, r, pix, keep_ratio=False, title=d["name"], opacity=d["opacity"])
                    if gid:
                        A.set_stamp_group(t.pdf.doc, a.xref, gid)
                    total += 1
                t.pdf.set_modified(True)
                t.view.invalidate_words()
                t.view.refresh("annots", pages)
                self.main.doc_changed(t, "annots")
            if gid:
                self.view.refresh("annots", [pno])
        finally:
            QApplication.restoreOverrideCursor()
        names = ", ".join(t.pdf.name for t, _ in targets)
        self.main.flash(f"Đã nhân bản ảnh ra {total} trang ({names}). Ctrl+Z để hoàn tác.", 10000)
        return total

    def stamp_group_members(self, pno, xref):
        gid = A.stamp_group(self.pdf.doc, xref)
        if not gid:
            return []
        out = []
        for i in range(self.pdf.page_count):
            page = self.pdf.doc[i]
            for a in page.annots(types=[fitz.PDF_ANNOT_STAMP]):
                if A.stamp_group(self.pdf.doc, a.xref) == gid:
                    out.append((i, a.xref))
        return out

    def delete_stamp_group(self, pno, xref):
        """Xoá ảnh này ở MỌI trang đã nhân bản (cùng nhóm) trong file."""
        mem = self.stamp_group_members(pno, xref)
        if not mem:
            return 0
        self.pdf.snapshot()
        pages = sorted({p for p, _ in mem})
        for p, x in mem:
            page = self.pdf.doc[p]
            a = page.load_annot(x)
            if a:
                page.delete_annot(a)
        self.view.select_annot(None)
        self.pdf.set_modified(True)
        self.view.refresh("annots", pages)
        self.main.doc_changed(self, "annots")
        self.main.flash(f"Đã xoá {len(mem)} ảnh cùng nhóm.")
        return len(mem)

    # ---------------------------------------------------------------- sửa chữ
    def edit_text(self, pno, pt):
        page = self.page(pno)
        hit = A.span_at(page, pt)
        if not hit:
            QMessageBox.information(self, "Sửa chữ", "Không tìm thấy chữ tại vị trí này.\n"
                                    "(Nếu là trang scan thì không có chữ để sửa – dùng 'Tẩy trắng' + 'Thêm chữ'.)")
            return
        sp = hit["span"]
        d = TextInputDialog("Sửa chữ trực tiếp", "Nội dung:", sp["text"], self, with_font=True, span=sp)
        if not d.exec():
            return
        new = d.text().replace("\n", " ")
        if hit["dir"] != (1, 0) and abs(hit["dir"][1]) > 0.01:
            QMessageBox.warning(self, "Sửa chữ", "Chữ nằm nghiêng/xoay – chưa hỗ trợ sửa trực tiếp.")
            return
        self._edit(pno, lambda p: A.replace_span(p, sp, new, d.family.currentData(), d.size.value(),
                                                 d.color.color, d.bold.isChecked(), d.italic.isChecked()))
        self.pdf.changed.emit("content")

    # -------------------------------------------------------------- ghi chú
    def edit_annot(self, pno, xref):
        page = self.page(pno)
        a = page.load_annot(xref)
        if a is None:
            return
        self.pdf.snapshot()
        page = self.page(pno)
        a = page.load_annot(xref)
        d = A.AnnotPropsDialog(a, self)
        if d.exec():
            try:
                d.apply()
            except Exception as e:
                QMessageBox.warning(self, "Thuộc tính", str(e))
            self.pdf.set_modified(True)
            self.view.refresh("annots", [pno])
            self.main.doc_changed(self, "annots")
        else:
            self.pdf.undo_stack.pop()

    def delete_annot(self, pno, xref):
        def go(p):
            a = p.load_annot(xref)
            if a:
                p.delete_annot(a)
        self.view.select_annot(None)
        self._edit(pno, go)

    def move_annot(self, pno, xref, rect_visible):
        page = self.page(pno)
        a = page.load_annot(xref)
        if a is None:
            return
        t = a.type[0]
        if t in (fitz.PDF_ANNOT_LINE, fitz.PDF_ANNOT_INK, fitz.PDF_ANNOT_POLYGON, fitz.PDF_ANNOT_POLY_LINE,
                 fitz.PDF_ANNOT_HIGHLIGHT, fitz.PDF_ANNOT_UNDERLINE, fitz.PDF_ANNOT_STRIKE_OUT,
                 fitz.PDF_ANNOT_SQUIGGLY):
            self._edit(pno, lambda p: _move_vertices(p, xref, rect_visible))
        else:
            def go(p):
                an = p.load_annot(xref)
                an.set_rect(A.U(p, rect_visible))
                an.update()
            self._edit(pno, go)
        self.view.select_annot((pno, xref))

    # ----------------------------------------------------------- vùng chọn
    def region_pixmap(self, pno, rect, dpi=200):
        return self.page(pno).get_pixmap(dpi=dpi, clip=rect, annots=True)

    def region_menu(self, pno, rect):
        m = QMenu(self)
        m.addAction("Sao chép ảnh vùng chọn", lambda: QGuiApplication.clipboard().setImage(
            pix_to_qimage(self.region_pixmap(pno, rect))))
        m.addAction("Lưu ảnh vùng chọn…", lambda: self._save_region(pno, rect))
        m.addAction("In vùng bản vẽ (chọn khổ giấy, vừa khổ / đúng tỉ lệ)…", lambda: self.print_region(pno, rect))
        m.addAction("Xuất vùng sang CAD (DWG / DXF)…", lambda: self.cad_region(pno, rect))
        m.addAction("Xuất vùng chọn thành PDF…", lambda: self._region_pdf(pno, rect))
        m.addSeparator()
        m.addAction("Sao chép chữ trong vùng", lambda: self._copy_region_text(pno, rect))
        m.addAction("Nhận dạng chữ (OCR) vùng chọn → sao chép", lambda: self._ocr_region(pno, rect))
        m.addAction("Hỏi Claude về vùng này", lambda: self.main.ask_ai_image(self.region_pixmap(pno, rect, 150)))
        m.addSeparator()
        m.addAction("Cắt lề trang theo vùng này…", lambda: self.crop(pno, rect))
        from PySide6.QtGui import QCursor
        m.exec(QCursor.pos())

    def _save_region(self, pno, rect):
        from .widgets import ask_save, done_message
        p = ask_save(self, "Lưu ảnh", f"vung_trang_{pno + 1}.png", "PNG (*.png);;JPG (*.jpg)")
        if p:
            self.region_pixmap(pno, rect, 300).save(p)
            done_message(self, "Đã lưu ảnh.", p)

    def _region_pdf(self, pno, rect):
        from .ops_pages import region_to_pdf
        from .widgets import ask_save, done_message
        p = ask_save(self, "Xuất vùng thành PDF", f"vung_trang_{pno + 1}.pdf")
        if p:
            region_to_pdf(self.pdf.doc, pno, rect, fit=False).save(p)
            done_message(self, "Đã xuất.", p)

    def print_region(self, pno, rect):
        from .dialog_cad import PrintRegionDialog
        PrintRegionDialog(self, self.pdf, pno, rect).exec()

    def cad_region(self, pno, rect):
        from .dialog_cad import CadExportDialog
        CadExportDialog(self, self.pdf, pno, rect).exec()

    def _print_region(self, pno, rect, fit):
        from .ops_pages import region_to_pdf
        from .printing import print_document
        print_document(self, region_to_pdf(self.pdf.doc, pno, rect, fit=fit), "Vùng chọn")

    def _copy_region_text(self, pno, rect):
        ws = A.words_in(self.page(pno), rect)
        lines, last = [], None
        for r, t, b, l in ws:
            if (b, l) != last:
                lines.append([])
                last = (b, l)
            lines[-1].append(t)
        txt = "\n".join(" ".join(l) for l in lines)
        QGuiApplication.clipboard().setText(txt)
        self.main.flash(f"Đã sao chép {len(txt)} ký tự." if txt else "Vùng không có chữ – thử OCR vùng chọn.")

    def _ocr_region(self, pno, rect):
        from . import ops_ocr
        try:
            pix = self.region_pixmap(pno, rect, 300)
            d = fitz.open()
            pg = d.new_page(width=pix.width * 72 / 300, height=pix.height * 72 / 300)
            pg.insert_image(pg.rect, pixmap=pix)
            lines = ops_ocr.ocr_lines(pg)
            txt = "\n".join(l["text"] for l in lines)
            QGuiApplication.clipboard().setText(txt)
            self.main.flash("Đã nhận dạng và sao chép: " + txt[:80].replace("\n", " ") + "…")
        except Exception as e:
            QMessageBox.warning(self, "OCR", str(e))

    def crop(self, pno, rect):
        r = QMessageBox.question(self, "Cắt lề trang", "Áp dụng cho TẤT CẢ các trang?\n(Chọn No = chỉ trang hiện tại)",
                                 QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel)
        if r == QMessageBox.Cancel:
            return
        pages = list(range(self.pdf.page_count)) if r == QMessageBox.Yes else [pno]
        self.pdf.crop(pages, fitz.Rect(rect))

    # ----------------------------------------------------------- menu chuột phải
    def on_context(self, action, payload):
        if action == "rotate":
            self.pdf.rotate([payload[0]], payload[1])
        elif action == "delete_page":
            self.main.delete_pages([payload])
        elif action == "page_image":
            from .dialogs import ToImageDialog
            d = ToImageDialog(self, self.pdf.doc, payload)
            d.rng.setText(str(payload + 1))
            if d.exec():
                d.run()
        elif action == "markup":
            if self.view.sel_rects:
                pno = self.view.sel_page
                rects = A.line_rects([(r, "", 0, i) for i, r in enumerate(self.view.sel_rects)])
                # gộp theo dòng dựa vào toạ độ y
                rects = _merge_rows(self.view.sel_rects)
                self._edit(pno, lambda p: A.add_markup(p, payload, rects, A.style()))
        elif action == "ask_ai":
            self.main.ask_ai_text(payload)


def _merge_rows(rects):
    rows = []
    for r in sorted(rects, key=lambda r: (round(r.y0), r.x0)):
        for i, rr in enumerate(rows):
            if abs((rr.y0 + rr.y1) / 2 - (r.y0 + r.y1) / 2) < r.height * 0.5:
                rows[i] = rr | r
                break
        else:
            rows.append(fitz.Rect(r))
    return rows


def _move_vertices(page, xref, rect_visible):
    """Di chuyển ghi chú dạng đỉnh (đường, nét vẽ…): tạo lại ở vị trí mới."""
    a = page.load_annot(xref)
    old = (a.rect * page.rotation_matrix).normalize()
    dx, dy = rect_visible.x0 - old.x0, rect_visible.y0 - old.y0
    sx = rect_visible.width / old.width if old.width > 1 else 1
    sy = rect_visible.height / old.height if old.height > 1 else 1
    rm, dm = page.rotation_matrix, page.derotation_matrix

    def tr(p):
        v = fitz.Point(p) * rm
        v = fitz.Point(old.x0 + (v.x - old.x0) * sx + dx, old.y0 + (v.y - old.y0) * sy + dy)
        return v * dm
    t = a.type[0]
    info, cols, border, op = a.info, a.colors, a.border, a.opacity
    verts = a.vertices
    le = a.line_ends
    page.delete_annot(a)
    if t == fitz.PDF_ANNOT_INK:
        n = page.add_ink_annot([[tuple(tr(p)) for p in s] for s in verts])
    elif t == fitz.PDF_ANNOT_LINE:
        n = page.add_line_annot(tr(verts[0]), tr(verts[1]))
        if le:
            n.set_line_ends(*le)
    elif t == fitz.PDF_ANNOT_POLYGON:
        n = page.add_polygon_annot([tr(p) for p in verts])
    elif t == fitz.PDF_ANNOT_POLY_LINE:
        n = page.add_polyline_annot([tr(p) for p in verts])
    else:
        quads = [fitz.Quad([tr(p) for p in verts[i:i + 4]]) for i in range(0, len(verts), 4)]
        fn = {fitz.PDF_ANNOT_HIGHLIGHT: page.add_highlight_annot, fitz.PDF_ANNOT_UNDERLINE: page.add_underline_annot,
              fitz.PDF_ANNOT_STRIKE_OUT: page.add_strikeout_annot, fitz.PDF_ANNOT_SQUIGGLY: page.add_squiggly_annot}[t]
        n = fn(quads)
    if cols:
        try:
            n.set_colors(stroke=cols.get("stroke"), fill=cols.get("fill"))
        except Exception:
            n.set_colors(stroke=cols.get("stroke"))
    if border:
        kw = {"width": border.get("width", 1)}
        if border.get("clouds", -1) > 0:
            kw["clouds"] = border["clouds"]
        if border.get("dashes"):
            kw["dashes"] = border["dashes"]
        n.set_border(**kw)
    n.set_opacity(op if op >= 0 else 1)
    n.set_info(info)
    n.update()
