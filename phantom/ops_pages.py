"""Các thao tác PDF không cần giao diện: gộp, tách, chuyển ảnh, đánh số trang,
in nhiều trang/tờ, bảo mật, đóng dấu chìm, nén."""
import io
import os
import datetime

import pymupdf as fitz

from .util import font_file, format_number, parse_ranges, parse_pages, safe_name

IMAGE_EXT = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".gif", ".webp", ".jfif")
PAPER = {"A4": fitz.paper_size("a4"), "A3": fitz.paper_size("a3"), "A5": fitz.paper_size("a5"),
         "Letter": fitz.paper_size("letter")}


def mm(v):
    return v * 72.0 / 25.4


def hex2rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def _progress(cb, i, n, msg=""):
    if cb:
        return cb(i, n, msg)
    return True


# ===================================================================== GỘP
def image_to_pdf_page(out, path, fit="image", margin_mm=0, paper="A4"):
    """Chèn 1 ảnh thành 1 trang. fit: 'image' = khổ theo ảnh, 'paper' = đặt vừa khổ giấy."""
    # ảnh chụp điện thoại có cờ xoay EXIF -> dựng thẳng đúng như khi xem ảnh, không tự quay ngang/dọc
    try:
        from PIL import Image, ImageOps
        with Image.open(path) as im:
            if im.getexif().get(0x0112, 1) not in (1, None):
                im2 = ImageOps.exif_transpose(im)
                b = io.BytesIO()
                im2.save(b, "PNG" if im2.mode in ("RGBA", "LA", "P") else "JPEG", quality=95)
                path = None
                data = b.getvalue()
    except Exception:
        pass
    img = fitz.open(path) if path else fitz.open(stream=data)
    try:
        rect = img[0].rect
        pdfbytes = img.convert_to_pdf()
    finally:
        img.close()
    src = fitz.open("pdf", pdfbytes)
    if fit == "image":
        page = out.new_page(width=rect.width, height=rect.height)
        page.show_pdf_page(page.rect, src, 0)
    else:
        w, h = PAPER.get(paper, PAPER["A4"])
        if rect.width > rect.height:          # ảnh ngang -> giấy ngang
            w, h = h, w
        page = out.new_page(width=w, height=h)
        m = mm(margin_mm)
        page.show_pdf_page(fitz.Rect(m, m, w - m, h - m), src, 0, keep_proportion=True)
    src.close()


def merge_files(files, out_path, image_fit="image", margin_mm=0, paper="A4",
                bookmarks=True, keep_sig_look=True, attach_originals=False, progress=None,
                sig_info=True, sig_summary=True):
    """Gộp PDF + ảnh. attach_originals=True: đính kèm bản gốc (giữ chữ ký số hợp lệ).
    sig_info: gắn thông tin chữ ký số tại vị trí chữ ký; sig_summary: thêm trang tổng hợp chữ ký."""
    from . import siginfo
    out = fitz.open()
    toc = []
    all_sigs = []
    n = len(files)
    for i, f in enumerate(files):
        if not _progress(progress, i, n, os.path.basename(f)):
            return None
        start = out.page_count
        ext = os.path.splitext(f)[1].lower()
        if ext in IMAGE_EXT:
            image_to_pdf_page(out, f, image_fit, margin_mm, paper)
        else:
            src = fitz.open(f)
            if src.needs_pass:
                raise RuntimeError(f"File có mật khẩu, hãy gỡ mật khẩu trước: {os.path.basename(f)}")
            sigs = []
            if sig_info and src.is_pdf:
                try:
                    with open(f, "rb") as fh:
                        sigs = siginfo.collect(fh.read(), os.path.basename(f))
                except Exception:
                    sigs = []
            if keep_sig_look and src.is_pdf:
                # 'Nướng' chữ ký/ghi chú/form vào nội dung để không mất hình chữ ký khi gộp
                tmp = fitz.open("pdf", src.tobytes())
                try:
                    tmp.bake(annots=True, widgets=True)
                    src.close()
                    src = tmp
                except Exception:
                    tmp.close()
            src_toc = src.get_toc(simple=True)
            npg = src.page_count
            out.insert_pdf(src, links=True, annots=True)
            if sigs:
                siginfo.mark_pages(out, sigs, {p: start + p for p in range(npg)}, os.path.basename(f))
                all_sigs += sigs
            if bookmarks:
                toc.append([1, os.path.splitext(os.path.basename(f))[0], start + 1])
                for lvl, title, pno in src_toc:
                    if pno > 0:
                        toc.append([lvl + 1, title, start + pno])
            src.close()
        if attach_originals and ext == ".pdf":
            ename = f"{i + 1:02d}_" + safe_name(os.path.basename(f))
            with open(f, "rb") as fh:
                out.embfile_add(ename, fh.read(),
                                filename=os.path.basename(f),
                                desc="Bản gốc (giữ nguyên chữ ký số) - " + os.path.basename(f))
    if sig_summary and all_sigs:
        pno = siginfo.summary_page(out, all_sigs)
        if pno is not None:
            toc.append([1, "Bảng thông tin chữ ký số", pno + 1])
    if bookmarks and toc:
        try:
            out.set_toc(_fix_toc(toc))
        except Exception:
            pass
    if attach_originals:
        out.set_pagemode("UseAttachments")
    out.save(out_path, garbage=3, deflate=True)
    out.close()
    _progress(progress, n, n, "Xong")
    return out_path


def _fix_toc(toc):
    fixed, last = [], 0
    for lvl, t, p in toc:
        lvl = min(lvl, last + 1) if last else 1
        fixed.append([lvl, t, p])
        last = lvl
    return fixed


def append_signed(base_signed, others, out_path):
    """Gộp kiểu 'cập nhật gia tăng': giữ nguyên chữ ký của file đầu (chữ ký đã có vẫn
    xác thực được cho phiên bản đã ký), các trang mới được nối thêm phía sau."""
    with open(base_signed, "rb") as fh:
        data = fh.read()
    with open(out_path, "wb") as fh:
        fh.write(data)
    doc = fitz.open(out_path)
    for f in others:
        ext = os.path.splitext(f)[1].lower()
        if ext in IMAGE_EXT:
            image_to_pdf_page(doc, f, "paper")
        else:
            s = fitz.open(f)
            doc.insert_pdf(s)
            s.close()
    doc.save(out_path, incremental=True, encryption=fitz.PDF_ENCRYPT_KEEP)
    doc.close()
    return out_path


# ===================================================================== TÁCH
SPLIT_MODES = ["free", "ranges", "cuts", "every", "single", "oddeven", "bookmarks", "size"]


def parse_free_groups(text, n):
    """Chế độ TỰ CHỌN: mỗi dòng = 1 file. Dòng dạng  'Tên file: 1, 3, 5-7'  hoặc chỉ '1, 3, 5-7'.
    Trang giữ ĐÚNG THỨ TỰ gõ (gõ '5, 1-2' -> file có trang 5, 1, 2). Dòng trống / bắt đầu bằng # bỏ qua.
    -> [(tên, [trang 0-based]), ...] ; lỗi -> ValueError('Dòng k: ...')"""
    out = []
    for k, line in enumerate((text or "").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        title = ""
        if ":" in line:
            title, line = line.rsplit(":", 1)
            title = title.strip()
        if not line.strip():
            raise ValueError(f"Dòng {k}: chưa ghi số trang")
        try:
            pages = parse_pages(line, n)
        except ValueError as e:
            raise ValueError(f"Dòng {k}: {e}")
        if not pages:
            raise ValueError(f"Dòng {k}: số trang ngoài phạm vi 1–{n}")
        out.append((title, pages))
    return out


def plan_split(src, mode="ranges", value="", rest=False):
    """Tính trước các nhóm trang (để XEM TRƯỚC và để tách). -> [(tên, [trang 0-based]), ...]
    free     : mỗi dòng 1 file, tự chọn trang bất kỳ, có thể đặt tên ('Hồ sơ A: 1,3,5-7')
    ranges   : '1-3, 4-10, 11-'  mỗi dải 1 file
    cuts     : cắt TẠI các trang '5, 12' -> 1-4 | 5-11 | 12-hết
    every    : mỗi file N trang      single : từng trang      oddeven : 2 file trang lẻ / chẵn
    bookmarks: theo dấu trang cấp 1  size   : theo dung lượng tối đa (MB)
    rest=True: gom các trang CHƯA được chọn thành 1 file 'Con lai'."""
    n = src.page_count
    groups = []
    if mode == "free":
        groups = parse_free_groups(value, n)
    elif mode == "ranges":
        groups = [("", g) for g in parse_ranges(value, n)]
    elif mode == "cuts":
        pts = sorted({p for p in parse_pages(str(value), n) if p > 0})
        edges = [0] + pts + [n]
        groups = [("", list(range(edges[i], edges[i + 1]))) for i in range(len(edges) - 1) if edges[i + 1] > edges[i]]
    elif mode == "every":
        k = max(1, int(value or 1))
        groups = [("", list(range(i, min(i + k, n)))) for i in range(0, n, k)]
    elif mode == "single":
        groups = [("", [i]) for i in range(n)]
    elif mode == "oddeven":
        groups = [("Trang le", list(range(0, n, 2))), ("Trang chan", list(range(1, n, 2)))]
        groups = [g for g in groups if g[1]]
    elif mode == "bookmarks":
        tops = [(t, p - 1) for lvl, t, p in src.get_toc() if lvl == 1 and p > 0]
        if not tops:
            raise ValueError("File không có dấu trang (bookmark) cấp 1.")
        if tops[0][1] > 0:
            tops.insert(0, ("Phan dau", 0))
        for j, (t, p) in enumerate(tops):
            end = tops[j + 1][1] if j + 1 < len(tops) else n
            if end > p:
                groups.append((t, list(range(p, end))))
    elif mode == "size":
        limit = float(value or 5) * 1024 * 1024
        cur = []
        for i in range(n):
            cur.append(i)
            tmp = fitz.open()
            tmp.insert_pdf(src, from_page=cur[0], to_page=cur[-1])
            size = len(tmp.tobytes(garbage=3, deflate=True))
            tmp.close()
            if size > limit and len(cur) > 1:
                groups.append(("", cur[:-1]))
                cur = [i]
        if cur:
            groups.append(("", cur))
    if rest and mode in ("free", "ranges"):
        used = {p for _, g in groups for p in g}
        left = [p for p in range(n) if p not in used]
        if left:
            groups.append(("Con lai", left))
    return groups


def describe_pages(g):
    """[0,1,2,4,7,8] -> '1-3, 5, 8-9'"""
    out, i = [], 0
    while i < len(g):
        j = i
        while j + 1 < len(g) and g[j + 1] == g[j] + 1:
            j += 1
        out.append(f"{g[i] + 1}" if i == j else f"{g[i] + 1}-{g[j] + 1}")
        i = j + 1
    return ", ".join(out)


def split_pdf(path, out_dir, mode="ranges", value="", name_tpl="{name}_{i}", progress=None, password=None,
              rest=False, data=None, name=None, groups=None):
    """Tách PDF. path: file trên đĩa, hoặc data=bytes (bản đang mở, gồm thay đổi chưa lưu).
    groups: danh sách đã tính sẵn [(tên, trang)] (bỏ qua mode/value)."""
    src = fitz.open("pdf", data) if data is not None else fitz.open(path)
    if src.needs_pass:
        src.authenticate(password or "")
    name = name or os.path.splitext(os.path.basename(path or "tai_lieu"))[0]
    if groups is None:
        groups = plan_split(src, mode, value, rest)
    toc = src.get_toc(simple=False)
    outs, used = [], set()
    for i, (title, g) in enumerate(groups, 1):
        if not _progress(progress, i - 1, len(groups), f"Phần {i}"):
            break
        out = fitz.open()
        for p in g:
            out.insert_pdf(src, from_page=p, to_page=p)
        # giữ dấu trang trỏ vào các trang thuộc file này
        try:
            pos = {p: k for k, p in enumerate(g)}
            sub = [[e[0], e[1], pos[e[2] - 1] + 1] for e in toc if e[2] - 1 in pos]
            sub.sort(key=lambda e: e[2])
            if sub:
                lv = min(e[0] for e in sub)
                for e in sub:
                    e[0] = max(1, e[0] - lv + 1)
                fixed, prev = [], 0
                for e in sub:
                    e[0] = min(e[0], prev + 1)
                    prev = e[0]
                    fixed.append(e)
                out.set_toc(fixed)
        except Exception:
            pass
        fname = name_tpl.format(name=name, i=f"{i:02d}", start=g[0] + 1, end=g[-1] + 1, title=title)
        if title and "{title}" not in name_tpl:
            fname = f"{name}_{title}"
        base = safe_name(fname) or f"{name}_{i:02d}"
        fp = os.path.join(out_dir, base + ".pdf")
        k = 2
        while fp in used:
            fp = os.path.join(out_dir, f"{base}_{k}.pdf")
            k += 1
        used.add(fp)
        out.save(fp, garbage=3, deflate=True)
        out.close()
        outs.append(fp)
    src.close()
    _progress(progress, len(groups), len(groups), "Xong")
    return outs


# ============================================================ PDF -> ẢNH
def pdf_to_images(doc_or_path, out_dir, pages=None, dpi=200, fmt="png", jpg_quality=90,
                  gray=False, transparent=False, name_tpl="{name}_trang_{p}", progress=None):
    doc = fitz.open(doc_or_path) if isinstance(doc_or_path, str) else doc_or_path
    name = os.path.splitext(os.path.basename(doc.name or "tai_lieu"))[0] or "tai_lieu"
    pages = pages if pages is not None else list(range(doc.page_count))
    cs = fitz.csGRAY if gray else fitz.csRGB
    outs = []
    for k, p in enumerate(pages):
        if not _progress(progress, k, len(pages), f"Trang {p + 1}"):
            break
        pix = doc[p].get_pixmap(dpi=dpi, colorspace=cs, alpha=(transparent and fmt == "png"))
        fp = os.path.join(out_dir, safe_name(name_tpl.format(name=name, p=f"{p + 1:03d}")) + "." + fmt)
        if fmt in ("jpg", "jpeg"):
            pix.save(fp, jpg_quality=jpg_quality)
        elif fmt in ("tif", "tiff", "bmp", "webp"):
            from PIL import Image
            mode = "L" if gray else "RGB"
            img = Image.frombytes(mode, (pix.width, pix.height), pix.samples)
            img.save(fp, dpi=(dpi, dpi), **({"compression": "tiff_lzw"} if fmt.startswith("tif") else {}))
        else:
            pix.save(fp)
        outs.append(fp)
    if isinstance(doc_or_path, str):
        doc.close()
    _progress(progress, len(pages), len(pages), "Xong")
    return outs


# ========================================================= ĐÁNH SỐ TRANG
PN_DEFAULTS = {
    "template": "Trang {n}/{total}",   # {n} số trang, {total} tổng số, {date} ngày
    "style": "1",                      # 1, 01, 001, i, I, a, A
    "position": "bottom-center",       # top/bottom - left/center/right
    "start": 1,                        # bắt đầu đếm từ số
    "range": "",                       # dải trang áp dụng, rỗng = tất cả
    "skip_first": False,               # không đánh số trang bìa
    "count_skipped": True,             # trang bị bỏ qua vẫn được tính số
    "mirror": False,                   # trang chẵn/lẻ đối xứng (in 2 mặt)
    "font": "times", "size": 12, "bold": False, "italic": False,
    "color": "#000000",
    "margin_x": 15.0, "margin_y": 10.0,  # mm tính từ mép giấy
    "total_mode": "applied",           # 'applied' = số trang được đánh, 'doc' = tổng số trang file
    "box": False,                      # khung viền quanh số
    "opacity": 1.0,
}


def page_number_label(cfg, index_in_seq, total):
    n = cfg["start"] + index_in_seq
    tot = cfg["start"] + total - 1 if cfg.get("total_mode", "applied") == "applied" else total
    return cfg["template"].format(
        n=format_number(n, cfg["style"]),
        total=format_number(tot, cfg["style"]),
        date=datetime.date.today().strftime("%d/%m/%Y"))


def add_page_numbers(doc, cfg):
    """Đánh số trang trực tiếp lên doc (pymupdf.Document). Trả về số trang đã đánh."""
    c = dict(PN_DEFAULTS)
    c.update(cfg or {})
    n = doc.page_count
    pages = []
    for g in parse_ranges(c["range"], n):
        pages += g
    if c["skip_first"] and pages:
        first = pages[0]
        pages_num = pages[1:]
    else:
        first = None
        pages_num = pages
    # tính chỉ số đếm: trang bìa bị bỏ qua vẫn có thể được tính số (như Word)
    if first is not None and c.get("count_skipped"):
        seq = [(p, i + 1) for i, p in enumerate(pages_num)]
        total = len(pages)
    else:
        seq = [(p, i) for i, p in enumerate(pages_num)]
        total = len(pages_num)
    if c.get("total_mode") == "doc":
        total = n
    ff = font_file(c["font"], c["bold"], c["italic"])
    font = fitz.Font(fontfile=ff) if ff else fitz.Font("helv")
    color = hex2rgb(c["color"])
    mx, my = mm(float(c["margin_x"])), mm(float(c["margin_y"]))
    vpos, hpos = c["position"].split("-")
    for p, idx in seq:
        page = doc[p]
        text = page_number_label(c, idx, total)
        size = float(c["size"])
        tw = font.text_length(text, fontsize=size)
        r = page.rect                       # kích thước hiển thị (đã xoay)
        h_eff = hpos
        if c["mirror"] and hpos in ("left", "right"):
            # số trang thực (1-based) lẻ -> bên phải, chẵn -> bên trái (mép ngoài)
            real = p + 1
            h_eff = "right" if real % 2 == 1 else "left"
            if hpos == "left":
                h_eff = "left" if real % 2 == 1 else "right"
        if h_eff == "left":
            x = mx
        elif h_eff == "right":
            x = r.width - mx - tw
        else:
            x = (r.width - tw) / 2
        if vpos == "top":
            y = my + size * 0.8
        else:
            y = r.height - my
        _insert_text_visible(page, (x, y), text, size, ff, color, c.get("opacity", 1.0))
        if c.get("box"):
            box = fitz.Rect(x - 4, y - size * 0.9, x + tw + 4, y + size * 0.3)
            _draw_rect_visible(page, box, color)
    return len(seq)


def _insert_text_visible(page, pt, text, size, fontfile, color, opacity=1.0, fontname="PNFont"):
    """Chèn chữ theo toạ độ trang đang hiển thị (tự xử lý trang bị xoay)."""
    page.wrap_contents()
    p = fitz.Point(pt) * page.derotation_matrix
    kw = dict(fontsize=size, color=color, rotate=page.rotation, fill_opacity=opacity, stroke_opacity=opacity)
    if fontfile:
        page.insert_text(p, text, fontname=fontname, fontfile=fontfile, **kw)
    else:
        page.insert_text(p, text, fontname="helv", **kw)


def _draw_rect_visible(page, rect, color, width=0.6):
    r = fitz.Rect(rect) * page.derotation_matrix
    page.draw_rect(r, color=color, width=width)


# ===================================================== ĐẦU TRANG / CHÂN TRANG
def add_header_footer(doc, items, font="times", size=10, color="#000000", margin_mm=10, rng="", line=False):
    """items: dict vị trí -> văn bản, ví dụ {'top-left': 'Dự án TBA 220kV An Lão', 'bottom-right': '{date}'}"""
    ff = font_file(font)
    f = fitz.Font(fontfile=ff) if ff else fitz.Font("helv")
    col = hex2rgb(color)
    m = mm(margin_mm)
    pages = []
    for g in parse_ranges(rng, doc.page_count):
        pages += g
    for k, p in enumerate(pages):
        page = doc[p]
        r = page.rect
        for pos, tpl in items.items():
            if not tpl:
                continue
            txt = tpl.format(n=k + 1, total=len(pages), date=datetime.date.today().strftime("%d/%m/%Y"),
                             file=os.path.basename(doc.name or ""))
            tw = f.text_length(txt, fontsize=size)
            v, h = pos.split("-")
            x = m if h == "left" else (r.width - m - tw if h == "right" else (r.width - tw) / 2)
            y = m + size if v == "top" else r.height - m
            _insert_text_visible(page, (x, y), txt, size, ff, col, fontname="HFFont")
        if line:
            for v in {pos.split("-")[0] for pos, t in items.items() if t}:
                y = m + size + 3 if v == "top" else r.height - m - size - 2
                _draw_line_visible(page, (m, y), (r.width - m, y), col)
    return len(pages)


def _draw_line_visible(page, a, b, color):
    dm = page.derotation_matrix
    page.draw_line(fitz.Point(a) * dm, fitz.Point(b) * dm, color=color, width=0.5)


# =========================================================== DẤU CHÌM
def add_watermark(doc, text, size=60, color="#C00000", opacity=0.15, angle=45, rng="", font="arial", bold=True):
    ff = font_file(font, bold)
    pages = []
    for g in parse_ranges(rng, doc.page_count):
        pages += g
    col = hex2rgb(color)
    for p in pages:
        page = doc[p]
        r = page.rect
        tw = (fitz.Font(fontfile=ff) if ff else fitz.Font("helv")).text_length(text, fontsize=size)
        center = fitz.Point(r.width / 2, r.height / 2)
        start = fitz.Point(center.x - tw / 2, center.y + size / 3)
        mat = fitz.Matrix(-angle)
        morph = (center * page.derotation_matrix, mat)
        page.wrap_contents()
        page.insert_text(start * page.derotation_matrix, text, fontsize=size, fontname="WMFont",
                         fontfile=ff, color=col, fill_opacity=opacity, stroke_opacity=opacity,
                         rotate=page.rotation, morph=morph, overlay=True)
    return len(pages)


# ================================================ IN NHIỀU TRANG / 1 TỜ (N-UP)
def nup(doc, per_sheet=4, paper="A4", landscape=None, margin_mm=5, gap_mm=3, border=False,
        order="row", pages=None):
    """Tạo tài liệu mới gồm nhiều trang thu nhỏ trên 1 tờ."""
    layouts = {2: (2, 1), 4: (2, 2), 6: (3, 2), 8: (4, 2), 9: (3, 3), 12: (4, 3), 16: (4, 4)}
    a, b = layouts.get(per_sheet, (2, 2))
    W, H = PAPER.get(paper, PAPER["A4"])
    if landscape is None:
        landscape = per_sheet in (2, 6, 8, 12)
    if landscape:
        W, H = max(W, H), min(W, H)
        cols, rows = a, b
    else:
        W, H = min(W, H), max(W, H)
        cols, rows = b, a
    m, gap = mm(margin_mm), mm(gap_mm)
    cw = (W - 2 * m - (cols - 1) * gap) / cols
    ch = (H - 2 * m - (rows - 1) * gap) / rows
    pages = pages if pages is not None else list(range(doc.page_count))
    out = fitz.open()
    for k, p in enumerate(pages):
        slot = k % per_sheet
        if slot == 0:
            sheet = out.new_page(width=W, height=H)
        if order == "row":
            r_, c_ = divmod(slot, cols)
        else:
            c_, r_ = divmod(slot, rows)
        cell = fitz.Rect(m + c_ * (cw + gap), m + r_ * (ch + gap), m + c_ * (cw + gap) + cw, m + r_ * (ch + gap) + ch)
        sheet.show_pdf_page(cell, doc, p, keep_proportion=True, rotate=-doc[p].rotation)
        if border:
            sheet.draw_rect(cell, color=(0.6, 0.6, 0.6), width=0.5)
    return out


def region_to_pdf(doc, pno, clip, paper="A4", fit=True, margin_mm=10):
    """Tạo PDF chỉ chứa 1 vùng chọn của trang (để in/xuất vùng)."""
    out = fitz.open()
    page = doc[pno]
    vis = fitz.Rect(clip)                                   # vùng theo trang hiển thị
    src_clip = (vis * page.derotation_matrix).normalize()   # đổi về toạ độ gốc
    rot = -page.rotation
    if fit:
        W, H = PAPER.get(paper, PAPER["A4"])
        if vis.width > vis.height:
            W, H = H, W
        pg = out.new_page(width=W, height=H)
        m = mm(margin_mm)
        pg.show_pdf_page(fitz.Rect(m, m, W - m, H - m), doc, pno, clip=src_clip, keep_proportion=True, rotate=rot)
    else:
        pg = out.new_page(width=vis.width, height=vis.height)
        pg.show_pdf_page(pg.rect, doc, pno, clip=src_clip, rotate=rot)
    return out


# ============================================================ BẢO MẬT
PERM_FLAGS = {
    "print": fitz.PDF_PERM_PRINT, "print_hq": fitz.PDF_PERM_PRINT_HQ,
    "modify": fitz.PDF_PERM_MODIFY, "copy": fitz.PDF_PERM_COPY,
    "annotate": fitz.PDF_PERM_ANNOTATE, "form": fitz.PDF_PERM_FORM,
    "assemble": fitz.PDF_PERM_ASSEMBLE, "accessibility": fitz.PDF_PERM_ACCESSIBILITY,
}


def save_encrypted(doc, out_path, user_pw="", owner_pw="", perms=None, method="aes256",
                   strip_meta=False):
    perms = perms if perms is not None else list(PERM_FLAGS)
    p = 0
    for k in perms:
        p |= PERM_FLAGS[k]
    enc = {"aes256": fitz.PDF_ENCRYPT_AES_256, "aes128": fitz.PDF_ENCRYPT_AES_128,
           "rc4": fitz.PDF_ENCRYPT_RC4_128}[method]
    if not owner_pw:
        owner_pw = user_pw or os.urandom(8).hex()
    if strip_meta:
        doc.set_metadata({})
        doc.del_xml_metadata()
    doc.save(out_path, encryption=enc, owner_pw=owner_pw, user_pw=user_pw, permissions=p,
             garbage=3, deflate=True)


def save_decrypted(doc, out_path):
    doc.save(out_path, encryption=fitz.PDF_ENCRYPT_NONE, garbage=3, deflate=True)


def redact_text(doc, needle, fill=(0, 0, 0)):
    """Xoá vĩnh viễn (bôi đen) mọi chỗ xuất hiện của chuỗi."""
    count = 0
    for page in doc:
        for r in page.search_for(needle):
            page.add_redact_annot(r, fill=fill)
            count += 1
        if count:
            page.apply_redactions()
    return count


# =============================================================== NÉN
def compress(doc, out_path, image_dpi=150, jpg_quality=70, gray=False):
    try:
        doc.rewrite_images(dpi_threshold=image_dpi + 10, dpi_target=image_dpi, quality=jpg_quality,
                           set_to_gray=gray)
    except Exception:
        pass
    doc.subset_fonts()
    doc.save(out_path, garbage=4, deflate=True, deflate_images=True, deflate_fonts=True, clean=True)


# ===================================================== CHUYỂN TRANG THÀNH ẢNH (giữ đúng vị trí)
def _text_layer(page, spans, fontfile):
    """Lớp chữ ẨN (render_mode 3) đặt đúng chỗ chữ gốc -> vẫn tìm kiếm / bôi đen / copy được."""
    font = fitz.Font(fontfile=fontfile) if fontfile else fitz.Font("helv")
    kw = dict(fontname="PhRasterTxt", fontfile=fontfile) if fontfile else dict(fontname="helv")
    n = 0
    for sp in spans:
        txt = sp["text"]
        if not txt.strip() or sp["size"] < 1:
            continue
        dx, dy = sp["dir"]
        rot = 0
        if abs(dx) < 0.5:
            rot = 90 if dy < 0 else 270
        elif dx < 0:
            rot = 180
        o = fitz.Point(sp["origin"])
        morph = None
        if rot == 0:
            want = sp["bbox"][2] - sp["bbox"][0]
            have = font.text_length(txt, fontsize=sp["size"])
            if have > 0 and 0.3 < want / have < 3:
                morph = (o, fitz.Matrix(want / have, 1))
        try:
            page.insert_text(o, txt, fontsize=sp["size"], render_mode=3, rotate=rot, morph=morph, **kw)
            n += 1
        except Exception:
            pass
    return n


def rasterize_pages(doc, pages, dpi=200, color="color", fmt="jpg", jpg_quality=85, keep_text=True,
                    merge_annots=True, progress=None):
    """Chuyển các trang thành ẢNH ngay trong file, giữ nguyên vị trí trang, khổ giấy, chiều xoay, dấu trang.
    color: color | gray | bw ;  fmt: jpg | png ;  merge_annots: True = ghi chú/chữ ký gộp vào ảnh,
    False = vẫn giữ ghi chú sửa được nằm trên ảnh.  -> số trang đã chuyển"""
    from PIL import Image
    fontfile = font_file("arial") if keep_text else None
    pages = sorted(set(p for p in pages if 0 <= p < doc.page_count))
    for k, pno in enumerate(pages):
        if not _progress(progress, k, len(pages), f"Trang {pno + 1}"):
            break
        page = doc[pno]
        spans = []
        if keep_text:
            for b in page.get_text("dict", flags=fitz.TEXTFLAGS_TEXT)["blocks"]:
                for ln in b.get("lines", []):
                    for sp in ln["spans"]:
                        spans.append(dict(text=sp["text"], size=sp["size"], origin=sp["origin"], bbox=sp["bbox"],
                                          dir=ln["dir"]))
        cs = fitz.csGRAY if color in ("gray", "bw") else fitz.csRGB
        pix = page.get_pixmap(dpi=dpi, colorspace=cs, alpha=False, annots=merge_annots)
        if color == "bw":
            im = Image.frombytes("L", (pix.width, pix.height), pix.samples).point(lambda v: 255 if v > 160 else 0)
            b = io.BytesIO()
            im.convert("1").save(b, "PNG", optimize=True)
            data = b.getvalue()
        elif fmt == "png":
            data = pix.tobytes("png")
        else:
            data = pix.tobytes("jpeg", jpg_quality=jpg_quality)
        # xoá nội dung cũ của trang (giữ nguyên trang -> dấu trang, liên kết, nhãn trang không đổi)
        for x in page.get_contents():
            doc.update_stream(x, b"")
        doc.xref_set_key(page.xref, "Contents", "null")
        doc.xref_set_key(page.xref, "Resources", "<<>>")
        if merge_annots:
            for a in list(page.annots()):
                page.delete_annot(a)
            for wdg in list(page.widgets() or []):
                try:
                    page.delete_widget(wdg)
                except Exception:
                    pass
        # ĐẶT ẢNH THEO HỆ TOẠ ĐỘ GỐC (không xoay) rồi trả lại góc xoay cũ -> trang hiển thị y hệt lúc xuất,
        # không phụ thuộc trang xoay 90/180/270°, xoay kế thừa, MediaBox/CropBox lệch gốc.
        page = doc[pno]
        rot = page.rotation
        if rot:
            im = Image.open(io.BytesIO(data))
            im = im.rotate(rot, expand=True)          # ảnh đang theo chiều HIỂN THỊ -> quay về chiều GỐC
            b = io.BytesIO()
            if color == "bw":
                im.convert("1").save(b, "PNG", optimize=True)
            elif fmt == "png":
                im.save(b, "PNG")
            else:
                im.convert("RGB" if color == "color" else "L").save(b, "JPEG", quality=jpg_quality)
            data = b.getvalue()
            page.set_rotation(0)
            page = doc[pno]
        page.insert_image(page.rect, stream=data, keep_proportion=False)
        if rot:
            page.set_rotation(rot)
            page = doc[pno]
        if spans:
            _text_layer(page, spans, fontfile)
    _progress(progress, len(pages), len(pages), "Xong")
    return len(pages)
