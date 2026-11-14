"""OCR (nhận dạng chữ) và chuyển PDF/ảnh -> Word giữ bố cục.

- PDF có sẵn chữ (xuất từ Word/Excel...): dùng pdf2docx -> giữ bảng, ảnh, font, lề rất sát.
- PDF scan / ảnh chụp: OCR bằng lõi Tesseract tích hợp trong PyMuPDF (tiếng Việt),
  sau đó dựng lại văn bản Word: khổ giấy, lề, thụt đầu dòng, căn giữa/phải/đều,
  cỡ chữ, khoảng cách dòng/đoạn, bảng có kẻ khung.
"""
import os
import statistics

import numpy as np
import pymupdf as fitz

from .util import config, tessdata_dir, font_file

OCR_DPI = 300


def visible_chars(page):
    """Số ký tự chữ THẬT nhìn thấy được (bỏ lớp chữ ẩn do máy scan/OCR tạo ra)."""
    try:
        return sum(len(sp["chars"]) for sp in page.get_texttrace()
                   if sp.get("type") != 3 and sp.get("opacity", 1) > 0.05)
    except Exception:
        return len(page.get_text("text").strip())


def image_cover(page):
    try:
        r = page.rect
        return sum((fitz.Rect(i["bbox"]) & r).get_area() for i in page.get_image_info()) / max(r.get_area(), 1)
    except Exception:
        return 0.0


def is_scanned(page, min_chars=20):
    """Trang là ảnh scan (kể cả bản scan đã có lớp chữ ẩn) -> True."""
    vis = visible_chars(page)
    if vis < min_chars:
        return True
    # ảnh phủ gần kín trang và rất ít chữ thật -> vẫn coi là scan
    return image_cover(page) > 0.85 and vis < 200


def _tess():
    td = tessdata_dir()
    if not td:
        raise RuntimeError(
            "Chưa có dữ liệu nhận dạng tiếng Việt (vie.traineddata).\n"
            "Hãy chạy lại CAI_DAT.bat hoặc chép file vie.traineddata vào thư mục 'tessdata' cạnh phần mềm.")
    return td


def ocr_textpage(page, lang=None, dpi=OCR_DPI, full=True):
    lang = lang or config().get("ocr_lang", "vie+eng")
    return page.get_textpage_ocr(language=lang, dpi=dpi, full=full, tessdata=_tess())


def ocr_lines(page, lang=None, dpi=OCR_DPI, textpage=None):
    """Trả về danh sách dòng: {'bbox': Rect, 'text': str, 'words': [(Rect, str)]} theo toạ độ trang."""
    tp = textpage or ocr_textpage(page, lang, dpi)
    d = page.get_text("rawdict", textpage=tp, flags=0)
    lines = []
    for b in d["blocks"]:
        for ln in b.get("lines", []):
            words = _line_words(ln)
            if not words:
                continue
            bb = fitz.Rect(words[0][0])
            for r, _ in words[1:]:
                bb |= r
            lines.append({"bbox": bb, "text": " ".join(t for _, t in words), "words": words})
    return lines


def native_lines(page):
    """Dòng chữ gốc của trang (theo toạ độ trang hiển thị) - cùng dạng với ocr_lines."""
    rm = page.rotation_matrix
    groups = {}
    for w in page.get_text("words", sort=True):
        r = (fitz.Rect(w[:4]) * rm).normalize()
        groups.setdefault((w[5], w[6]), []).append((r, w[4]))
    out = []
    for ws in groups.values():
        bb = fitz.Rect(ws[0][0])
        for r, _ in ws[1:]:
            bb |= r
        out.append({"bbox": bb, "text": " ".join(t for _, t in ws), "words": ws})
    return out


def _line_words(ln):
    """Tách từ theo khoảng cách ký tự (Tesseract đôi khi dính từ có dấu: 'CỔPHẦN')."""
    chars = [c for s in ln["spans"] for c in s["chars"]]
    if not chars:
        return []
    h = max(1.0, ln["bbox"][3] - ln["bbox"][1])
    words, cur, cur_r = [], "", None
    prev = None
    for c in chars:
        ch = c["c"]
        r = fitz.Rect(c["bbox"])
        if ch.isspace():
            if cur:
                words.append((cur_r, cur))
            cur, cur_r, prev = "", None, None
            continue
        if prev is not None and r.x0 - prev.x1 > h * 0.22 and cur:
            words.append((cur_r, cur))
            cur, cur_r = "", None
        cur += ch
        cur_r = fitz.Rect(r) if cur_r is None else cur_r | r
        prev = r
    if cur:
        words.append((cur_r, cur))
    return words


def clean_page_for_ocr(page, dpi=OCR_DPI):
    """Tạo trang tạm từ ảnh đã xoá đường kẻ bảng -> OCR chính xác hơn trong bảng.
    Trả về (doc_tạm, trang_tạm, bảng) - toạ độ theo trang đang hiển thị."""
    import cv2
    pix = page.get_pixmap(dpi=dpi, colorspace=fitz.csGRAY)
    img = np.frombuffer(pix.samples, np.uint8).reshape(pix.h, pix.w).copy()
    hor, ver = _grid_masks(img)
    tables = _tables_from_masks(hor, ver, pix.w, pix.h, 72.0 / dpi)
    # chỉ xoá đúng nét kẻ (không giãn) để không ăn mất dấu tiếng Việt sát đường kẻ
    img[(hor | ver) > 0] = 255
    tmp = fitz.open()
    W, H = page.rect.width, page.rect.height
    tp_page = tmp.new_page(width=W, height=H)
    out = fitz.Pixmap(fitz.csGRAY, pix.w, pix.h, img.tobytes(), False)
    out.set_dpi(dpi, dpi)
    tp_page.insert_image(tp_page.rect, pixmap=out)
    return tmp, tp_page, tables


# ----------------------------------------------- lớp chữ ẩn (PDF tìm kiếm được)
def add_ocr_layer(doc, pages=None, lang=None, dpi=OCR_DPI, progress=None):
    """Thêm lớp chữ vô hình lên trang scan để tìm kiếm / bôi đen / copy được."""
    ff = font_file("arial")
    font = fitz.Font(fontfile=ff) if ff else fitz.Font("helv")
    pages = pages if pages is not None else list(range(doc.page_count))
    done = 0
    for k, pno in enumerate(pages):
        if progress and not progress(k, len(pages), f"OCR trang {pno + 1}"):
            break
        page = doc[pno]
        if not is_scanned(page):
            continue
        lines = ocr_lines(page, lang, dpi)
        page.wrap_contents()
        tw = fitz.TextWriter(page.rect)
        for ln in lines:
            r = ln["bbox"]
            size = max(4.0, r.height * 0.85)
            w = font.text_length(ln["text"], fontsize=size)
            if w <= 0:
                continue
            sx = r.width / w
            # dựng theo toạ độ gốc của trang (trang có thể bị xoay)
            tw.append((r.x0, r.y1 - r.height * 0.2), ln["text"], font=font, fontsize=size)
            tw.write_text(page, render_mode=3, morph=(fitz.Point(r.x0, r.y1), fitz.Matrix(sx, 1)))
            tw = fitz.TextWriter(page.rect)
        done += 1
    return done


# ------------------------------------------------------------ PDF -> WORD
def pdf_to_word(src_path, out_path, pages=None, mode="auto", password=None, progress=None, preprocess=True,
                layout="exact"):
    """mode: 'auto' | 'text' (PDF có chữ, dùng pdf2docx) | 'ocr' (đọc chữ từ ảnh, dựng lại văn bản).
    Trả về chế độ đã dùng."""
    doc = fitz.open(src_path)
    if doc.needs_pass:
        if not doc.authenticate(password or ""):
            raise RuntimeError("Sai mật khẩu PDF.")
    pages = pages if pages is not None else list(range(doc.page_count))
    kinds = {p: is_scanned(doc[p]) for p in pages}
    force_ocr = mode == "ocr"
    if mode == "auto":
        mode = "text" if not any(kinds.values()) else "ocr"
    if mode == "text":
        doc.close()
        _pdf2docx(src_path, out_path, pages, password, progress)
        return "text"
    builder = make_builder(layout)
    for k, p in enumerate(pages):
        if progress and not progress(k, len(pages), f"Đọc chữ trang {p + 1}/{doc.page_count}"):
            break
        page = doc[p]
        if kinds[p] or force_ocr:
            if preprocess:
                tmp = _cleaned_scan_page(page)
                builder.add_page(tmp[0])
                tmp.close()
            else:
                builder.add_page(page)
        else:
            builder.add_page(page, native=True)          # trang có chữ thật: lấy chữ gốc, không OCR
    doc.close()
    builder.save(out_path)
    if progress:
        progress(len(pages), len(pages), "Xong")
    return "ocr"


def _cleaned_scan_page(page, dpi=300):
    """Trang scan -> trang tạm đã khử bóng nền, chỉnh nghiêng (đọc chữ chính xác hơn)."""
    import cv2
    from . import ops_scan
    pix = page.get_pixmap(dpi=dpi, colorspace=fitz.csRGB, annots=False)
    img = np.frombuffer(pix.samples, np.uint8).reshape(pix.h, pix.w, 3)[:, :, ::-1].copy()
    img = ops_scan.enhance(img, "gray", sharpen=False)
    img = ops_scan.deskew(img)
    return _image_page(img, page.rect.width, page.rect.height)


def _image_page(img, w_pt, h_pt):
    import cv2
    ok, buf = cv2.imencode(".png", img)
    d = fitz.open()
    pg = d.new_page(width=w_pt, height=h_pt)
    pg.insert_image(pg.rect, stream=buf.tobytes())
    return d


def prepare_photo(path, preprocess=True):
    """Ảnh chụp/scan -> trang PDF tạm khổ A4 sẵn sàng đọc chữ: tìm 4 góc giấy, nắn phẳng,
    khử bóng, chỉnh nghiêng, phóng đủ độ phân giải (~300 DPI)."""
    import cv2
    from . import ops_scan
    img = ops_scan.imread(path)
    if preprocess:
        h, w = img.shape[:2]
        quad = ops_scan.detect_document(img)
        if cv2.contourArea(quad) < 0.9 * w * h:            # ảnh chụp có nền bàn -> cắt & nắn giấy
            img = ops_scan.warp(img, quad)
            hh, ww = img.shape[:2]
            r = max(hh, ww) / min(hh, ww)
            if 1.25 < r < 1.6:                                  # gần khổ A -> ép đúng tỉ lệ √2 (A4)
                if hh >= ww:
                    img = cv2.resize(img, (ww, int(ww * 1.41421)), interpolation=cv2.INTER_CUBIC)
                else:
                    img = cv2.resize(img, (int(hh * 1.41421), hh), interpolation=cv2.INTER_CUBIC)
            hh, ww = img.shape[:2]
            m = int(min(hh, ww) * 0.012)                    # bỏ viền mép giấy còn sót
            img = img[m:hh - m, m:ww - m]
        img = ops_scan.enhance(img, "gray", sharpen=False)
        img = ops_scan.deskew(img)
    h, w = img.shape[:2]
    target = 2480 if h >= w else 3508                      # A4 @300 DPI theo chiều rộng
    if w < target * 0.9:
        f = target / w
        img = cv2.resize(img, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC)
        h, w = img.shape[:2]
    pw = 595.0 if h >= w else 842.0
    return _image_page(img, pw, pw * h / w)


def images_to_word(image_paths, out_path, progress=None, preprocess=True, layout="exact"):
    """Đọc chữ từ ảnh (chụp / scan) và viết lại thành Word sửa được. Nhiều ảnh -> nhiều trang."""
    builder = make_builder(layout)
    empty = []
    for k, ip in enumerate(image_paths):
        if progress and not progress(k, len(image_paths), f"Đọc chữ: {os.path.basename(ip)}"):
            break
        tmp = prepare_photo(ip, preprocess)
        n = builder.add_page(tmp[0])
        if not n:
            empty.append(os.path.basename(ip))
        tmp.close()
    builder.save(out_path)
    if progress:
        progress(len(image_paths), len(image_paths), "Xong")
    if empty and len(empty) == len(image_paths):
        raise RuntimeError("Không đọc được chữ nào trong ảnh. Ảnh quá mờ / quá nhỏ, hoặc thiếu dữ liệu "
                           "nhận dạng tiếng Việt (tessdata).")
    return out_path


def files_to_word(paths, out_path, mode="auto", page_range="", preprocess=True, progress=None, layout="exact"):
    """Nhiều PDF / ảnh -> 1 file Word. mode 'text' chỉ dùng được khi chỉ có 1 file PDF."""
    from .util import parse_pages
    if len(paths) == 1 and paths[0].lower().endswith(".pdf"):
        n = fitz.open(paths[0]).page_count
        pages = parse_pages(page_range, n) if page_range.strip() else None
        pdf_to_word(paths[0], out_path, pages=pages, mode=mode, preprocess=preprocess, progress=progress,
                    layout=layout)
        return out_path
    # danh sách công việc: (file, trang | None)
    jobs = []
    for p in paths:
        if p.lower().endswith(".pdf"):
            d = fitz.open(p)
            pages = parse_pages(page_range, d.page_count) if page_range.strip() else range(d.page_count)
            jobs += [(p, i) for i in pages]
            d.close()
        else:
            jobs.append((p, None))
    builder = make_builder(layout)
    read = 0
    for k, (p, pno) in enumerate(jobs):
        label = os.path.basename(p) + (f" – trang {pno + 1}" if pno is not None else "")
        if progress and not progress(k, len(jobs), f"Đọc chữ: {label}"):
            break
        if pno is None:
            tmp = prepare_photo(p, preprocess)
            read += builder.add_page(tmp[0])
            tmp.close()
        else:
            d = fitz.open(p)
            page = d[pno]
            if mode == "ocr" or is_scanned(page):
                tmp = _cleaned_scan_page(page) if preprocess else None
                read += builder.add_page(tmp[0] if tmp else page)
                if tmp:
                    tmp.close()
            else:
                read += builder.add_page(page, native=True)
            d.close()
    builder.save(out_path)
    if progress:
        progress(len(jobs), len(jobs), "Xong")
    if not read:
        raise RuntimeError("Không đọc được chữ nào. Ảnh quá mờ / quá nhỏ, hoặc thiếu dữ liệu nhận dạng "
                           "tiếng Việt (thư mục tessdata).")
    return out_path


def _pdf2docx(src, out, pages, password, progress):
    from pdf2docx import Converter
    cv = Converter(src, password=password)
    try:
        cv.convert(out, pages=pages, multi_processing=False)
    finally:
        cv.close()
    if progress:
        progress(1, 1, "Xong")
    return out


# ================================================== DỰNG WORD GIỐNG BẢN GỐC (bản mới)
class LayoutBuilder:
    """Bộ dựng Word giữ đúng vị trí dòng, cỡ chữ, đậm/nghiêng, khổ trang (xem ocr_layout.py)."""

    def __init__(self, keep_lines=True):
        from .ocr_layout import LayoutWriter
        fam = config().get("default_font", "times")
        name = {"times": "Times New Roman", "arial": "Arial"}.get(fam, "Times New Roman")
        self.w = LayoutWriter(name, fam if fam in ("times", "arial") else "times", keep_lines)

    def add_page(self, page, assume_a4=False, native=False):
        from .ocr_layout import page_to_layout, paper_scale
        tmp, tpage, tables = clean_page_for_ocr(page)
        try:
            lines = native_lines(page) if native else ocr_lines(tpage)
            _, scl = paper_scale(page.rect.width, page.rect.height)
            cell = None if native else (lambda clip: _ocr_cell_words(tpage, clip))
            return page_to_layout(self.w, page, tpage, tables, lines, scl, cell)
        finally:
            tmp.close()

    def save(self, path):
        self.w.save(path)


def _ocr_cell_words(tpage, clip):
    """OCR riêng 1 ô bảng (thêm viền trắng) -> [(Rect toạ độ trang, chữ)]."""
    try:
        pix = tpage.get_pixmap(dpi=OCR_DPI, clip=clip, colorspace=fitz.csGRAY)
        if pix.width < 8 or pix.height < 8:
            return []
        pad = 24
        f = 72.0 / OCR_DPI
        d = fitz.open()
        pg = d.new_page(width=(pix.width + 2 * pad) * f, height=(pix.height + 2 * pad) * f)
        pg.insert_image(fitz.Rect(pad * f, pad * f, (pad + pix.width) * f, (pad + pix.height) * f), pixmap=pix)
        ls = ocr_lines(pg, dpi=OCR_DPI)
        d.close()
        dx, dy = clip.x0 - pad * f, clip.y0 - pad * f
        return [(r + (dx, dy, dx, dy), t) for l in ls for r, t in l["words"]]
    except Exception:
        return []


def make_builder(layout="exact"):
    if layout == "old":
        return WordBuilder()
    return LayoutBuilder(keep_lines=(layout != "flow"))


# ================================================== DỰNG LẠI VĂN BẢN WORD
class WordBuilder:
    """Dựng tài liệu Word từ kết quả OCR, cố gắng giữ bố cục gốc."""

    def __init__(self, font_name=None):
        from docx import Document
        self.doc = Document()
        self.first = True
        fam = config().get("default_font", "times")
        self.font_name = font_name or {"times": "Times New Roman", "arial": "Arial",
                                       "tahoma": "Tahoma", "calibri": "Calibri"}.get(fam, "Times New Roman")
        st = self.doc.styles["Normal"]
        st.font.name = self.font_name
        st.paragraph_format.space_after = 0
        self._fonts(st.element)

    def _fonts(self, el):
        from docx.oxml.ns import qn
        rpr = el.get_or_add_rPr()
        rfonts = rpr.find(qn("w:rFonts"))
        if rfonts is None:
            rfonts = rpr.makeelement(qn("w:rFonts"), {})
            rpr.insert(0, rfonts)
        for a in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
            rfonts.set(qn(a), self.font_name)

    def _run(self, para, text, size, bold=None):
        from docx.shared import Pt
        run = para.add_run(text)
        run.font.size = Pt(size)
        if bold:
            run.bold = True
        self._fonts(run._element)
        return run

    # ---------------------------------------------------------------- page
    def add_page(self, page, assume_a4=False, native=False):
        from docx.shared import Pt
        from docx.enum.section import WD_ORIENT, WD_SECTION
        prect = page.rect
        scale = 1.0
        if assume_a4:
            scale = (595.0 if prect.width < prect.height else 842.0) / prect.width
        W, H = prect.width * scale, prect.height * scale
        sm = fitz.Matrix(scale, scale)

        tmp, tpage, tables = clean_page_for_ocr(page)
        if native:
            lines = native_lines(page)
            self.tpage = None                   # ô bảng lấy chữ gốc, không OCR
        else:
            lines = ocr_lines(tpage)
            self.tpage = tpage
        self.scale = scale
        for ln in lines:
            ln["bbox"] = ln["bbox"] * sm
            ln["words"] = [(r * sm, t) for r, t in ln["words"]]
        raw_tables = tables
        tables = [(fitz.Rect(t[0]) * sm, [x * scale for x in t[1]], [y * scale for y in t[2]]) for t in tables]
        tables_src = {t[0].y0: raw for t, raw in zip(tables, raw_tables)}

        # tách từ thuộc bảng / thân văn bản
        table_words = [[] for _ in tables]
        body = []
        for ln in lines:
            keep = []
            for r, t in ln["words"]:
                c = fitz.Point((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2)
                for k, tb in enumerate(tables):
                    if tb[0].contains(c):
                        table_words[k].append((r, t))
                        break
                else:
                    keep.append((r, t))
            if keep:
                bb = fitz.Rect(keep[0][0])
                for r, _ in keep[1:]:
                    bb |= r
                body.append({"bbox": bb, "text": " ".join(t for _, t in keep), "words": keep})

        # lề trang theo vùng chữ thực tế
        allb = [l["bbox"] for l in body] + [t[0] for t in tables]
        if allb:
            left = max(28.0, min(_percentile([b.x0 for b in allb], 3), 140.0))
            right = max(28.0, min(W - _percentile([b.x1 for b in allb], 98), 120.0))
            top = max(20.0, min(min(b.y0 for b in allb) - 4, 120.0))
            bottom = max(20.0, min(H - max(b.y1 for b in allb) - 6, 100.0))
        else:
            left, right, top, bottom = 85, 57, 57, 57

        if self.first:
            sec = self.doc.sections[0]
            self.first = False
        else:
            sec = self.doc.add_section(WD_SECTION.NEW_PAGE)
        sec.orientation = WD_ORIENT.LANDSCAPE if W > H else WD_ORIENT.PORTRAIT
        sec.page_width, sec.page_height = Pt(W), Pt(H)
        sec.left_margin, sec.right_margin = Pt(left), Pt(right)
        sec.top_margin, sec.bottom_margin = Pt(top), Pt(bottom)
        sec.header_distance = sec.footer_distance = Pt(min(top, bottom) / 2)
        self.left, self.cw = left, W - left - right

        rows = _merge_same_row(body)
        items = [("r", r["bbox"].y0, r) for r in rows] + [("t", t[0].y0, (t, table_words[k]))
                                                         for k, t in enumerate(tables)]
        items.sort(key=lambda x: x[1])
        heights = [r["bbox"].height for r in rows] or [12]
        self.med_h = statistics.median(heights)
        bs = [_font_size([r]) for r in rows if len(r["text"]) > 15]
        self.body_size = statistics.median(bs) if bs else None
        self.prev_bottom = None

        buf = []
        i = 0
        while i < len(items):
            kind, _, obj = items[i]
            if kind == "t":
                self._flush(buf)
                buf = []
                self._add_table(*obj, tables_src=tables_src[obj[0][0].y0])
                self.prev_bottom = obj[0][0].y1
                i += 1
            elif len(obj["segs"]) >= 2:
                self._flush(buf)
                buf = []
                block = [obj]
                bounds = _col_bounds(obj, left, self.cw)
                j = i + 1
                while j < len(items) and items[j][0] == "r":
                    nxt = items[j][2]
                    gap = nxt["bbox"].y0 - block[-1]["bbox"].y1
                    if gap > self.med_h * 1.6:
                        break
                    if len(nxt["segs"]) >= 2 or (gap < self.med_h * 0.6 and _fits_column(nxt, bounds)):
                        block.append(nxt)
                        j += 1
                    else:
                        break
                self._add_columns(block, bounds)
                i = j
            else:
                buf.append(obj)
                i += 1
        self._flush(buf)
        tmp.close()
        return len(lines)

    # ------------------------------------------------- khối nhiều cột (quốc hiệu)
    def _add_columns(self, rows, bounds):
        from docx.shared import Pt
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        ncol = len(bounds) - 1
        t = self.doc.add_table(rows=1, cols=ncol)
        t.autofit = False
        _no_borders(t)
        cells = [[] for _ in range(ncol)]
        for r in rows:
            for sg in r["segs"]:
                cx = (sg["bbox"].x0 + sg["bbox"].x1) / 2
                k = max(0, min(ncol - 1, sum(1 for b in bounds[1:-1] if cx > b)))
                cells[k].append(sg)
        for k in range(ncol):
            cell = t.cell(0, k)
            cell.width = Pt(bounds[k + 1] - bounds[k])
            first = True
            for sg in cells[k]:
                para = cell.paragraphs[0] if first else cell.add_paragraph()
                first = False
                size = _font_size([sg])
                cx = (sg["bbox"].x0 + sg["bbox"].x1) / 2
                colmid = (bounds[k] + bounds[k + 1]) / 2
                if abs(cx - colmid) < (bounds[k + 1] - bounds[k]) * 0.12:
                    para.alignment = WD_ALIGN_PARAGRAPH.CENTER
                elif sg["bbox"].x0 - bounds[k] > 3:
                    para.paragraph_format.left_indent = Pt(sg["bbox"].x0 - bounds[k])
                para.paragraph_format.space_after = Pt(0)
                self._run(para, sg["text"], size, bold=_is_upper(sg["text"]))
        self.prev_bottom = rows[-1]["bbox"].y1

    # ----------------------------------------------------------- đoạn văn
    def _flush(self, rows):
        if not rows:
            return
        for g in _group_paragraphs(rows, self.med_h, self.left, self.cw):
            self._write_paragraph(g)
            self.prev_bottom = g[-1]["bbox"].y1

    def _write_paragraph(self, rows):
        from docx.shared import Pt
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        left, content_w = self.left, self.cw
        p = self.doc.add_paragraph()
        pf = p.paragraph_format
        x0s = [r["bbox"].x0 for r in rows]
        x1s = [r["bbox"].x1 for r in rows]
        right_edge = left + content_w
        size = _font_size(rows)
        cx = [(r["bbox"].x0 + r["bbox"].x1) / 2 for r in rows]
        mid = left + content_w / 2
        centered = all(abs(c - mid) < content_w * 0.05 for c in cx) and min(x0s) - left > content_w * 0.06
        right_al = all(right_edge - x1 < content_w * 0.03 for x1 in x1s) and min(x0s) - left > content_w * 0.3
        if centered:
            pf.alignment = WD_ALIGN_PARAGRAPH.CENTER
        elif right_al:
            pf.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        else:
            body_x0 = min(x0s[1:]) if len(rows) > 1 else x0s[0]
            if len(rows) > 1:
                ind = max(0.0, body_x0 - left)
                first = x0s[0] - body_x0
                if ind > 3:
                    pf.left_indent = Pt(ind)
                if abs(first) > 3:
                    pf.first_line_indent = Pt(first)
            else:
                # 1 dòng: thụt vào so với lề -> coi là thụt đầu dòng
                ind = x0s[0] - left
                if ind > 3:
                    pf.first_line_indent = Pt(ind)
            full = sum(1 for x1 in x1s[:-1] if right_edge - x1 < content_w * 0.05)
            if len(rows) > 1 and full >= (len(rows) - 1) * 0.6:
                pf.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        if len(rows) > 1:
            pitch = statistics.median(rows[i + 1]["bbox"].y0 - rows[i]["bbox"].y0 for i in range(len(rows) - 1))
            pf.line_spacing = Pt(max(size * 1.05, min(pitch, size * 2.5)))
        gap = 0 if self.prev_bottom is None else rows[0]["bbox"].y0 - self.prev_bottom - size * 0.45
        pf.space_before = Pt(max(0.0, min(round(gap), 60)))
        pf.space_after = Pt(0)
        parts = []
        for k, r in enumerate(rows):
            t = r["text"]
            if k < len(rows) - 1:
                short = right_edge - r["bbox"].x1 > content_w * 0.25 and not centered
                t += "\n" if short else " "
            parts.append(t)
        text = "".join(parts)
        bold = _is_upper(text)
        for k, seg in enumerate(text.split("\n")):
            if k:
                p.add_run().add_break()
            self._run(p, seg, size, bold)

    # ------------------------------------------------------------- bảng
    def _ocr_cell(self, clip):
        """OCR riêng 1 ô (có viền trắng) - chính xác hơn OCR cả trang khi chữ sát đường kẻ."""
        try:
            pix = self.tpage.get_pixmap(dpi=OCR_DPI, clip=clip, colorspace=fitz.csGRAY)
            if pix.width < 8 or pix.height < 8:
                return []
            pad = 24
            f = 72.0 / OCR_DPI
            d = fitz.open()
            pg = d.new_page(width=(pix.width + 2 * pad) * f, height=(pix.height + 2 * pad) * f)
            pg.insert_image(fitz.Rect(pad * f, pad * f, (pad + pix.width) * f, (pad + pix.height) * f), pixmap=pix)
            ls = ocr_lines(pg, dpi=OCR_DPI)
            d.close()
            off = fitz.Point(clip.x0 - pad * f, clip.y0 - pad * f)
            out = []
            for l in ls:
                bb = (l["bbox"] + (off.x, off.y, off.x, off.y)) * fitz.Matrix(self.scale, self.scale)
                out.append({"bbox": bb, "text": l["text"]})
            return out
        except Exception:
            return []

    def _add_table(self, table, words, tables_src=None):
        from docx.shared import Pt
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        rect, xs, ys = table
        nrows, ncols = len(ys) - 1, len(xs) - 1
        t = self.doc.add_table(rows=nrows, cols=ncols)
        t.style = "Table Grid"
        t.autofit = False
        grid = [[[] for _ in range(ncols)] for _ in range(nrows)]
        for r, txt in words:
            cx, cy = (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2
            c = max(0, min(ncols - 1, sum(1 for x in xs[1:-1] if cx > x)))
            rr = max(0, min(nrows - 1, sum(1 for y in ys[1:-1] if cy > y)))
            grid[rr][c].append((r, txt))
        # lượt 1: đọc chữ từng ô
        cells = {}
        for rr in range(nrows):
            for c in range(ncols):
                ws = grid[rr][c]
                lines_ = []
                if tables_src is not None and self.tpage is not None:
                    sx, sy = tables_src[1], tables_src[2]
                    lines_ = self._ocr_cell(fitz.Rect(sx[c] + 1.5, sy[rr] + 1.5, sx[c + 1] - 1.5, sy[rr + 1] - 1.5))
                if not lines_ and ws:
                    lines_ = _words_to_lines(ws)
                if lines_:
                    cells[(rr, c)] = lines_
        # cỡ chữ chung của bảng = cỡ phổ biến nhất (ô chỉ có "m", "2" đo chiều cao không chuẩn)
        sizes = [_font_size(v) for v in cells.values() if sum(len(l["text"]) for l in v) >= 4]
        common = max(set(sizes), key=sizes.count) if sizes else None
        body = getattr(self, "body_size", None)
        if body and (common is None or body * 0.7 <= common <= body * 1.05):
            common = body                       # chữ trong bảng thường cùng cỡ thân văn bản
        # lượt 2: ghi vào Word
        for rr in range(nrows):
            t.rows[rr].height = Pt(ys[rr + 1] - ys[rr])
            for c in range(ncols):
                cell = t.cell(rr, c)
                cell.width = Pt(xs[c + 1] - xs[c])
                para = cell.paragraphs[0]
                para.paragraph_format.space_after = Pt(0)
                lines_ = cells.get((rr, c))
                if not lines_:
                    continue
                size = _font_size(lines_)
                short = sum(len(l["text"]) for l in lines_) < 4
                if common and (short or abs(size - common) <= common * 0.35):
                    size = common
                cell_rect = fitz.Rect(xs[c], ys[rr], xs[c + 1], ys[rr + 1])
                cxm = (cell_rect.x0 + cell_rect.x1) / 2
                if all(abs((l["bbox"].x0 + l["bbox"].x1) / 2 - cxm) < cell_rect.width * 0.12 for l in lines_) \
                        and min(l["bbox"].x0 for l in lines_) - cell_rect.x0 > 8:
                    para.alignment = WD_ALIGN_PARAGRAPH.CENTER
                elif all(cell_rect.x1 - l["bbox"].x1 < 8 for l in lines_) and \
                        min(l["bbox"].x0 for l in lines_) - cell_rect.x0 > cell_rect.width * 0.3:
                    para.alignment = WD_ALIGN_PARAGRAPH.RIGHT
                txt = " ".join(l["text"] for l in lines_)
                self._run(para, txt, size, bold=(rr == 0 and _is_upper(txt)) or None)

    def save(self, path):
        self.doc.save(path)


# ------------------------------------------------------------- hỗ trợ
def _no_borders(table):
    from docx.oxml.ns import qn
    tbl = table._tbl
    tblPr = tbl.tblPr
    borders = tblPr.makeelement(qn("w:tblBorders"), {})
    for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
        e = borders.makeelement(qn(f"w:{side}"), {qn("w:val"): "nil"})
        borders.append(e)
    tblPr.append(borders)


def _is_upper(text):
    letters = [c for c in text if c.isalpha()]
    chars = [c for c in text if not c.isspace()]
    if len(letters) < 6 or len(letters) < 0.7 * len(chars):
        return False
    return sum(c.isupper() for c in letters) / len(letters) > 0.85


def _percentile(vals, q):
    return float(np.percentile(np.array(vals), q)) if vals else 0.0


def _font_size(rows):
    hs = []
    for r in rows:
        h = r["bbox"].height
        hs.append(h * 0.94 if _is_upper(r["text"]) else h / 0.93)
    hs.sort()
    size = hs[len(hs) // 2]
    common = [7, 8, 9, 10, 10.5, 11, 12, 13, 14, 15, 16, 18, 20, 22, 24, 26, 28, 32, 36, 40, 48]
    return min(common, key=lambda c: abs(c - size))


def _words_to_lines(words):
    words = sorted(words, key=lambda w: ((w[0].y0 + w[0].y1) / 2, w[0].x0))
    lines = []
    for r, t in words:
        cy = (r.y0 + r.y1) / 2
        for l in lines:
            if abs(l["cy"] - cy) < max(4, r.height * 0.5):
                l["w"].append((r, t))
                l["bbox"] |= r
                break
        else:
            lines.append({"cy": cy, "w": [(r, t)], "bbox": fitz.Rect(r)})
    out = []
    for l in sorted(lines, key=lambda l: l["cy"]):
        ws = sorted(l["w"], key=lambda w: w[0].x0)
        out.append({"bbox": l["bbox"], "text": " ".join(t for _, t in ws)})
    return out


def _merge_same_row(lines):
    """Gộp các mảnh dòng cùng hàng; khoảng trống lớn -> tách thành cột (segs)."""
    words = []
    for l in lines:
        words += l["words"]
    rows = []
    for wl in _cluster_rows(words):
        wl.sort(key=lambda w: w[0].x0)
        h = statistics.median(w[0].height for w in wl)
        segs, cur = [], [wl[0]]
        for w in wl[1:]:
            if w[0].x0 - cur[-1][0].x1 > h * 1.3:
                segs.append(cur)
                cur = [w]
            else:
                cur.append(w)
        segs.append(cur)
        seg_objs = []
        for sg in segs:
            bb = fitz.Rect(sg[0][0])
            for r, _ in sg[1:]:
                bb |= r
            seg_objs.append({"bbox": bb, "text": " ".join(t for _, t in sg)})
        bb = fitz.Rect(seg_objs[0]["bbox"])
        for s in seg_objs[1:]:
            bb |= s["bbox"]
        rows.append({"bbox": bb, "text": "\t".join(s["text"] for s in seg_objs), "segs": seg_objs})
    return rows


def _cluster_rows(words):
    words = sorted(words, key=lambda w: (w[0].y0 + w[0].y1) / 2)
    rows = []
    for r, t in words:
        cy = (r.y0 + r.y1) / 2
        if rows:
            last = rows[-1]
            lcy = statistics.median((w[0].y0 + w[0].y1) / 2 for w in last)
            lh = statistics.median(w[0].height for w in last)
            if abs(cy - lcy) < lh * 0.45:
                last.append((r, t))
                continue
        rows.append([(r, t)])
    return rows


def _col_bounds(row, left, cw):
    segs = row["segs"]
    b = [left]
    for a, c in zip(segs, segs[1:]):
        b.append((a["bbox"].x1 + c["bbox"].x0) / 2)
    b.append(left + cw)
    return b


def _fits_column(row, bounds):
    """Dòng 1 đoạn nằm gọn trong 1 cột (vd 'VIỆT NAM' dưới 'CỘNG HÒA...')."""
    s = row["segs"][0]["bbox"]
    for a, b in zip(bounds, bounds[1:]):
        if s.x0 >= a - 5 and s.x1 <= b + 5:
            return len(bounds) > 2
    return False


def _group_paragraphs(rows, med_h, left, content_w):
    groups = []
    cur = []
    for r in rows:
        if not cur:
            cur = [r]
            continue
        prev = cur[-1]
        gap = r["bbox"].y0 - prev["bbox"].y1
        new_para = False
        if gap > med_h * 0.8:
            new_para = True
        elif abs(r["bbox"].height - prev["bbox"].height) > med_h * 0.4:
            new_para = True
        elif r["bbox"].x0 - cur[0]["bbox"].x0 > med_h * 1.2 and len(cur) > 1:
            new_para = True
        elif left + content_w - prev["bbox"].x1 > content_w * 0.2:
            new_para = True
        if new_para:
            groups.append(cur)
            cur = [r]
        else:
            cur.append(r)
    if cur:
        groups.append(cur)
    return groups


def _grid_masks(img):
    import cv2
    h, w = img.shape
    th = cv2.adaptiveThreshold(255 - img, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 15, -2)
    hk = cv2.getStructuringElement(cv2.MORPH_RECT, (max(20, w // 30), 1))
    vk = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(20, h // 50)))
    hor = cv2.morphologyEx(th, cv2.MORPH_OPEN, hk)
    ver = cv2.morphologyEx(th, cv2.MORPH_OPEN, vk)
    return hor, ver


def _tables_from_masks(hor, ver, W, H, f):
    import cv2
    grid = cv2.dilate(hor | ver, np.ones((3, 3), np.uint8))
    cnts, _ = cv2.findContours(grid, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    out = []
    for c in cnts:
        x, y, w, h = cv2.boundingRect(c)
        if w < W * 0.2 or h < 20:
            continue
        # viền mép giấy / mép ảnh chụp không phải bảng
        edge = max(4, int(min(W, H) * 0.006))
        if x <= edge or y <= edge or x + w >= W - edge or y + h >= H - edge:
            continue
        sub_h = hor[y:y + h, x:x + w]
        sub_v = ver[y:y + h, x:x + w]
        ys = _line_positions(sub_h.sum(axis=1), w * 255 * 0.5)
        xs = _line_positions(sub_v.sum(axis=0), h * 255 * 0.5)
        if len(xs) < 2 or len(ys) < 2 or (len(xs) - 1) * (len(ys) - 1) < 2:
            continue
        xs = [(x + v) * f for v in xs]
        ys = [(y + v) * f for v in ys]
        out.append((fitz.Rect(xs[0], ys[0], xs[-1], ys[-1]), xs, ys))
    return out


def detect_tables(page, dpi=150):
    """Phát hiện bảng có kẻ khung. Trả về [(rect, xs, ys)] theo toạ độ trang hiển thị."""
    pix = page.get_pixmap(dpi=dpi, colorspace=fitz.csGRAY)
    img = np.frombuffer(pix.samples, np.uint8).reshape(pix.h, pix.w)
    hor, ver = _grid_masks(img)
    return _tables_from_masks(hor, ver, pix.w, pix.h, 72.0 / dpi)


def _line_positions(profile, thresh):
    idx = np.where(profile > thresh)[0]
    if len(idx) == 0:
        return []
    pos, start, prev = [], idx[0], idx[0]
    for v in idx[1:]:
        if v - prev > 3:
            pos.append((start + prev) / 2)
            start = v
        prev = v
    pos.append((start + prev) / 2)
    return pos
