"""Tạo/sửa ghi chú (annotation) chuẩn PDF + bảng tuỳ chỉnh chi tiết từng mục."""
import datetime
import os

import pymupdf as fitz
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QDialog, QFormLayout, QDialogButtonBox, QPushButton, QColorDialog,
                               QDoubleSpinBox, QSpinBox, QComboBox, QPlainTextEdit, QCheckBox,
                               QLineEdit, QHBoxLayout, QWidget, QVBoxLayout, QLabel, QSlider)

from .util import config, font_file

DEFAULT_STYLE = {
    "color": "#E53935", "fill": "", "width": 1.5, "opacity": 1.0, "dash": "solid",
    "font": "Helv", "fontsize": 12, "text_color": "#C62828", "align": 0,
    "highlight": "#FFEB3B", "underline": "#1E88E5", "strike": "#E53935", "squiggly": "#43A047",
    "note_icon": "Comment", "measure_scale": 1.0, "measure_unit": "mm", "arrow_end": "ClosedArrow",
}

FONTS = {"Helv": "Arial / Helvetica", "TiRo": "Times New Roman", "Cour": "Courier"}
DASHES = {"solid": None, "dash": [6, 3], "dot": [1, 2], "dashdot": [6, 3, 1, 3]}
LINE_ENDS = {"None": fitz.PDF_ANNOT_LE_NONE, "OpenArrow": fitz.PDF_ANNOT_LE_OPEN_ARROW,
             "ClosedArrow": fitz.PDF_ANNOT_LE_CLOSED_ARROW, "Circle": fitz.PDF_ANNOT_LE_CIRCLE,
             "Square": fitz.PDF_ANNOT_LE_SQUARE, "Diamond": fitz.PDF_ANNOT_LE_DIAMOND,
             "Butt": fitz.PDF_ANNOT_LE_BUTT, "Slash": fitz.PDF_ANNOT_LE_SLASH}
NOTE_ICONS = ["Comment", "Note", "Key", "Help", "Insert", "Paragraph", "NewParagraph"]

STAMPS = [
    ("ĐÃ DUYỆT", "#C62828"), ("ĐÃ KIỂM TRA", "#1565C0"), ("ĐỒNG Ý", "#2E7D32"),
    ("KHÔNG ĐỒNG Ý", "#C62828"), ("BẢN SAO", "#6A1B9A"), ("SAO Y BẢN CHÍNH", "#C62828"),
    ("HOÀN CÔNG", "#2E7D32"), ("BẢN VẼ THI CÔNG", "#1565C0"), ("ĐÃ THI CÔNG", "#2E7D32"),
    ("CHỜ XỬ LÝ", "#EF6C00"), ("KHẨN", "#C62828"), ("MẬT", "#C62828"), ("NHÁP", "#757575"),
    ("HẾT HIỆU LỰC", "#424242"), ("ĐÃ THANH TOÁN", "#2E7D32"),
]

SYMBOLS = ["✔", "✘", "★", "●", "■", "▲", "◆", "⚠", "→", "←", "↑", "↓", "↔", "⊕", "⊗",
           "Ø", "±", "≈", "≤", "≥", "Δ", "Σ", "°", "①", "②", "③", "④", "⑤", "?", "!"]


def style():
    s = dict(DEFAULT_STYLE)
    s.update(config().get("annot_styles", {}))
    return s


def save_style(key, value):
    cfg = config()
    st = dict(cfg.get("annot_styles", {}))
    st[key] = value
    cfg["annot_styles"] = st
    cfg.save()


def rgb(h):
    if not h:
        return None
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def hexcol(c):
    if not c:
        return ""
    return "#%02X%02X%02X" % tuple(int(max(0, min(1, v)) * 255) for v in c[:3])


def _author():
    return config().get("signer_name") or os.environ.get("USERNAME") or "PDF Phantom"


def _finish(a, st, stroke=True, fill=False):
    if stroke:
        a.set_colors(stroke=rgb(st["color"]), fill=rgb(st["fill"]) if fill and st.get("fill") else None)
    a.set_border(width=st["width"], dashes=DASHES.get(st.get("dash"), None))
    a.set_opacity(st["opacity"])
    info = a.info
    info["title"] = _author()
    a.set_info(info)
    a.update()
    return a


# ----------------------------------------------------------- toạ độ
def U(page, obj):
    """Đổi toạ độ hiển thị -> toạ độ gốc (trang có xoay)."""
    if isinstance(obj, (tuple, list)) and len(obj) == 2:
        return fitz.Point(obj) * page.derotation_matrix
    if isinstance(obj, fitz.Point):
        return obj * page.derotation_matrix
    return (fitz.Rect(obj) * page.derotation_matrix).normalize()


# ----------------------------------------------------------- tạo ghi chú
def add_textbox(page, rect, text, st=None):
    st = st or style()
    r = U(page, rect)
    a = page.add_freetext_annot(
        r, text, fontsize=st["fontsize"], fontname=st["font"], text_color=rgb(st["text_color"]),
        fill_color=rgb(st["fill"]) if st.get("fill") else None, border_width=st.get("tb_border", 0),
        align=st["align"], rotate=page.rotation, opacity=st["opacity"])
    info = a.info
    info["title"] = _author()
    a.set_info(info)
    a.update()
    return a


def add_callout(page, rect, text, anchor, st=None):
    st = st or style()
    r = U(page, rect)
    pa = U(page, anchor)
    knee = fitz.Point((pa.x + r.x0) / 2, (r.y0 + r.y1) / 2)
    end = fitz.Point(r.x0, (r.y0 + r.y1) / 2)
    return page.add_freetext_annot(r, text, fontsize=st["fontsize"], fontname=st["font"],
                                   text_color=rgb(st["text_color"]), callout=(pa, knee, end),
                                   line_end=fitz.PDF_ANNOT_LE_OPEN_ARROW, rotate=page.rotation,
                                   fill_color=rgb(st["fill"]) if st.get("fill") else None)


def add_note(page, point, text, st=None):
    st = st or style()
    a = page.add_text_annot(U(page, point), text, icon=st.get("note_icon", "Comment"))
    a.set_colors(stroke=rgb(st.get("note_color", "#FFC107")))
    info = a.info
    info["title"] = _author()
    a.set_info(info)
    a.update()
    return a


def add_shape(page, kind, rect, st=None):
    st = st or style()
    r = U(page, rect)
    a = page.add_rect_annot(r) if kind == "rect" else page.add_circle_annot(r)
    return _finish(a, st, fill=True)


def add_line(page, p1, p2, st=None, arrow=False, label=None):
    st = st or style()
    a = page.add_line_annot(U(page, p1), U(page, p2))
    if arrow:
        a.set_line_ends(fitz.PDF_ANNOT_LE_NONE, LINE_ENDS.get(st.get("arrow_end"), fitz.PDF_ANNOT_LE_CLOSED_ARROW))
    _finish(a, st, fill=arrow)
    if label:
        a.set_info(content=label)
        a.update()
    return a


def add_measure(page, p1, p2, st=None):
    """Đo khoảng cách: vẽ đường kích thước có mũi tên 2 đầu + nhãn chữ."""
    st = st or style()
    dist_pt = fitz.Point(p1).distance_to(fitz.Point(p2))
    label = format_measure(dist_pt, st)
    a = page.add_line_annot(U(page, p1), U(page, p2))
    a.set_line_ends(fitz.PDF_ANNOT_LE_CLOSED_ARROW, fitz.PDF_ANNOT_LE_CLOSED_ARROW)
    _finish(a, st, fill=True)
    a.set_info(content=label, subject="Đo kích thước")
    a.update()
    mid = fitz.Point((p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2)
    fs = max(7, st["fontsize"] * 0.9)
    w = fitz.get_text_length(label, fontsize=fs) + 6
    tr = fitz.Rect(mid.x - w / 2, mid.y - fs * 1.6, mid.x + w / 2, mid.y - 1)
    t = page.add_freetext_annot(U(page, tr), label, fontsize=fs, fontname="Helv",
                                text_color=rgb(st["color"]), rotate=page.rotation, align=1)
    t.set_info(subject="Đo kích thước")
    t.update()
    return a


def format_measure(dist_pt, st):
    mm = dist_pt * 25.4 / 72.0 * float(st.get("measure_scale", 1.0))
    unit = st.get("measure_unit", "mm")
    if unit == "m":
        return f"{mm / 1000:,.2f} m".replace(",", "X").replace(".", ",").replace("X", ".")
    if unit == "cm":
        return f"{mm / 10:,.1f} cm".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{mm:,.0f} mm".replace(",", ".")


def add_poly(page, kind, pts, st=None):
    st = st or style()
    pts = [U(page, p) for p in pts]
    if kind == "polyline":
        a = page.add_polyline_annot(pts)
        _finish(a, st)
        return a
    pts = pts + [pts[0]]
    a = page.add_polygon_annot(pts)
    a.set_colors(stroke=rgb(st["color"]), fill=rgb(st["fill"]) if st.get("fill") else None)
    if kind == "cloud":
        a.set_border(width=st["width"], clouds=2)
    else:
        a.set_border(width=st["width"], dashes=DASHES.get(st.get("dash")))
    a.set_opacity(st["opacity"])
    a.set_info(title=_author())
    a.update()
    return a


def add_ink(page, strokes, st=None):
    st = st or style()
    s2 = [[tuple(U(page, p)) for p in s] for s in strokes]
    a = page.add_ink_annot(s2)
    return _finish(a, st)


def add_markup(page, kind, rects_visible, st=None):
    st = st or style()
    quads = [U(page, r).quad for r in rects_visible]
    if not quads:
        return None
    fn = {"highlight": page.add_highlight_annot, "underline": page.add_underline_annot,
          "strike": page.add_strikeout_annot, "squiggly": page.add_squiggly_annot}[kind]
    a = fn(quads)
    a.set_colors(stroke=rgb(st.get(kind, "#FFEB3B")))
    a.set_opacity(st["opacity"] if kind != "highlight" else min(st["opacity"], 1.0))
    a.set_info(title=_author())
    a.update()
    return a


def words_in(page, rect_visible):
    rm = page.rotation_matrix
    out = []
    for w in page.get_text("words", sort=True):
        r = (fitz.Rect(w[:4]) * rm).normalize()
        if r.intersects(rect_visible):
            out.append((r, w[4], w[5], w[6]))
    return out


def line_rects(words):
    """Gộp các từ cùng dòng thành 1 khung (để tô sáng liền mạch)."""
    lines = {}
    for r, t, b, l in words:
        key = (b, l)
        lines[key] = lines[key] | r if key in lines else fitz.Rect(r)
    return list(lines.values())


def add_whiteout(page, rect):
    a = page.add_rect_annot(U(page, rect))
    a.set_colors(stroke=(1, 1, 1), fill=(1, 1, 1))
    a.set_border(width=0)
    a.set_info(title=_author(), subject="Tẩy trắng")
    a.update()
    return a


def add_redact(page, rect):
    a = page.add_redact_annot(U(page, rect), fill=(0, 0, 0))
    return a


# ---------------------------------------------------------- con dấu / ảnh
def stamp_pixmap(text, color="#C62828", date=True, sub="", w=260, h=None, double=True, zoom=4):
    """Dựng ảnh con dấu chữ nhật bo góc (PNG trong suốt)."""
    lines = [text]
    if sub:
        lines.append(sub)
    if date:
        lines.append(datetime.date.today().strftime("Ngày %d/%m/%Y"))
    ff = font_file("times", bold=True) or font_file("arial", bold=True)
    ff2 = font_file("times") or font_file("arial")
    font = fitz.Font(fontfile=ff) if ff else fitz.Font("hebo")
    big = min(30, (w - 24) / max(font.text_length(text, fontsize=1), 0.01))
    small = big * 0.42
    h = h or (big * 1.35 + (len(lines) - 1) * small * 1.5 + 18)
    doc = fitz.open()
    pg = doc.new_page(width=w, height=h)
    col = rgb(color)
    r = fitz.Rect(3, 3, w - 3, h - 3)
    pg.draw_rect(r, color=col, width=3, radius=0.12)
    if double:
        pg.draw_rect(fitz.Rect(7, 7, w - 7, h - 7), color=col, width=1, radius=0.1)
    y = 9 + big
    tw = font.text_length(text, fontsize=big)
    pg.insert_text(((w - tw) / 2, y), text, fontsize=big, fontname="SB", fontfile=ff, color=col)
    f2 = fitz.Font(fontfile=ff2) if ff2 else fitz.Font("helv")
    for extra in lines[1:]:
        y += small * 1.5
        tw = f2.text_length(extra, fontsize=small)
        pg.insert_text(((w - tw) / 2, y), extra, fontsize=small, fontname="SN", fontfile=ff2, color=col)
    pix = pg.get_pixmap(dpi=72 * zoom, alpha=True)
    doc.close()
    return pix, (w, h)


def add_image_stamp(page, rect_visible, pix_or_path, keep_ratio=True, title="", opacity=1.0):
    pix = fitz.Pixmap(pix_or_path) if isinstance(pix_or_path, str) else pix_or_path
    r = fitz.Rect(rect_visible)
    if keep_ratio and pix.width and pix.height:
        ar = pix.width / pix.height
        if r.width / max(r.height, 1) > ar:
            nw = r.height * ar
            r = fitz.Rect(r.x0, r.y0, r.x0 + nw, r.y1)
        else:
            nh = r.width / ar
            r = fitz.Rect(r.x0, r.y0, r.x1, r.y0 + nh)
    # trang có xoay: xoay ảnh theo đúng chiều trang để hiển thị thẳng (đã kiểm 90/180/270°)
    if page.rotation:
        pix = _rotate_pix(pix, page.rotation)
    a = page.add_stamp_annot(U(page, r), stamp=pix)
    a.set_info(title=_author(), content=title, subject="Con dấu")
    a.set_opacity(opacity)
    a.update()
    return a


GROUP_KEY = "PhantomGroup"


def stamp_group(doc, xref):
    try:
        t, v = doc.xref_get_key(xref, GROUP_KEY)
        return v.strip("()") if t != "null" else None
    except Exception:
        return None


def set_stamp_group(doc, xref, gid):
    doc.xref_set_key(xref, GROUP_KEY, fitz.get_pdf_str(gid))


def stamp_image(doc, pno, xref, zoom=4.0):
    """Lấy lại ẢNH GỐC của ảnh/con dấu đã chèn, đúng chiều hiển thị, nền trong suốt, chưa áp độ mờ.
    -> dict(png, rect (toạ độ hiển thị), page_w, page_h, opacity, name)"""
    t = fitz.open()
    t.insert_pdf(doc, from_page=pno, to_page=pno, annots=True)
    tp = t[0]
    for c in tp.get_contents():
        t.update_stream(c, b"")                      # bỏ nội dung trang, chỉ giữ ảnh
    target = None
    page = doc[pno]                                  # giữ trang sống (tránh lỗi bộ nhớ của PyMuPDF)
    src = page.load_annot(xref)
    src_rect = fitz.Rect(src.rect)
    for an in list(tp.annots()):
        if an.type[0] == fitz.PDF_ANNOT_STAMP and target is None and \
                abs(an.rect.x0 - src_rect.x0) < 0.01 and abs(an.rect.y0 - src_rect.y0) < 0.01 and \
                abs(an.rect.x1 - src_rect.x1) < 0.01:
            target = an.xref
    for an in list(tp.annots()):
        if an.xref != target:
            tp.delete_annot(an)
    an = tp.load_annot(target)
    op = src.opacity if src.opacity >= 0 else 1.0
    an.set_opacity(1.0)
    an.update()
    vis = (an.rect * tp.rotation_matrix).normalize()
    pm = tp.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=vis, alpha=True, annots=True)
    out = dict(png=pm.tobytes("png"), rect=tuple(vis), page_w=page.rect.width, page_h=page.rect.height,
               opacity=op, name=src.info.get("content") or "Ảnh")
    t.close()
    return out


def map_rect(rect, src_w, src_h, dst_w, dst_h, mode="edge"):
    """Đặt khung ảnh sang trang khác khổ.
    edge  : giữ khoảng cách tới MÉP GẦN NHẤT, giữ nguyên cỡ ảnh (dấu góc phải dưới vẫn ở góc phải dưới).
    same  : giữ nguyên toạ độ.   scale: co giãn theo tỉ lệ khổ trang."""
    r = fitz.Rect(rect)
    if mode == "same" or (abs(src_w - dst_w) < 1 and abs(src_h - dst_h) < 1):
        out = r
    elif mode == "scale":
        sx, sy = dst_w / src_w, dst_h / src_h
        s = min(sx, sy)
        cx, cy = (r.x0 + r.x1) / 2 * sx, (r.y0 + r.y1) / 2 * sy
        out = fitz.Rect(cx - r.width * s / 2, cy - r.height * s / 2, cx + r.width * s / 2, cy + r.height * s / 2)
    else:
        x0 = r.x0 if (r.x0 + r.x1) / 2 <= src_w / 2 else dst_w - (src_w - r.x0)
        y0 = r.y0 if (r.y0 + r.y1) / 2 <= src_h / 2 else dst_h - (src_h - r.y0)
        out = fitz.Rect(x0, y0, x0 + r.width, y0 + r.height)
    # không cho lọt ra ngoài trang
    dx = max(0, -out.x0) - max(0, out.x1 - dst_w)
    dy = max(0, -out.y0) - max(0, out.y1 - dst_h)
    return out + (dx, dy, dx, dy)


def _rotate_pix(pix, angle):
    from PIL import Image
    mode = "RGBA" if pix.alpha else "RGB"
    im = Image.frombytes(mode, (pix.width, pix.height), pix.samples)
    im = im.rotate(angle, expand=True)
    import io
    b = io.BytesIO()
    im.save(b, "PNG")
    return fitz.Pixmap(b.getvalue())


def add_symbol(page, rect, sym, color="#2E7D32"):
    r = U(page, rect)
    size = max(8, min(rect.height, rect.width) * 0.85)
    a = page.add_freetext_annot(r, sym, fontsize=size, fontname="Helv", text_color=rgb(color),
                                align=1, rotate=page.rotation)
    a.set_info(title=_author(), subject="Ký hiệu")
    a.update()
    return a


# --------------------------------------------------------------- chèn ảnh/chữ vào nội dung
def insert_text_content(page, point, text, family="times", size=12, color="#000000", bold=False, italic=False):
    ff = font_file(family, bold, italic)
    page.wrap_contents()
    p = fitz.Point(point) * page.derotation_matrix
    page.insert_text(p, text, fontsize=size, fontname="ETF" + ("B" if bold else "") + ("I" if italic else ""),
                     fontfile=ff, color=rgb(color), rotate=page.rotation)


# ---------------------------------------------------------------- sửa chữ
def span_at(page, pt_visible):
    """Tìm đoạn chữ (span) dưới điểm. Trả về dict span + line bbox (toạ độ gốc)."""
    p = fitz.Point(pt_visible) * page.derotation_matrix
    d = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
    best = None
    for b in d["blocks"]:
        for ln in b.get("lines", []):
            for sp in ln["spans"]:
                r = fitz.Rect(sp["bbox"])
                if fitz.Rect(r.x0 - 1, r.y0 - 1, r.x1 + 1, r.y1 + 1).contains(p) and sp["text"].strip():
                    best = {"span": sp, "line": ln, "dir": ln.get("dir", (1, 0))}
    return best


def replace_span(page, span, new_text, family=None, size=None, color=None, bold=None, italic=None):
    """Xoá chữ cũ (redact, giữ nền/hình) và viết chữ mới đúng vị trí, cỡ, màu."""
    from .util import guess_family
    fam, b0, i0 = guess_family(span["font"])
    flags = span.get("flags", 0)
    b0 = b0 or bool(flags & 16)
    i0 = i0 or bool(flags & 2)
    family = family or fam
    bold = b0 if bold is None else bold
    italic = i0 if italic is None else italic
    size = size or span["size"]
    c = span["color"]
    color = color or "#%06X" % c
    # vùng xoá ôm sát thân chữ (tránh ăn sang dòng trên/dưới khi giãn dòng hẹp)
    r = fitz.Rect(span["bbox"])
    oy = span["origin"][1]
    asc = span.get("ascender", 0.8) or 0.8
    r = fitz.Rect(r.x0 + 0.3, max(r.y0, oy - size * min(asc, 0.8) * 0.85), r.x1 - 0.3,
                  min(r.y1, oy + size * 0.12))
    page.add_redact_annot(r)
    page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE, graphics=fitz.PDF_REDACT_LINE_ART_NONE,
                          text=fitz.PDF_REDACT_TEXT_REMOVE)
    ff = font_file(family, bold, italic)
    origin = fitz.Point(span["origin"])
    page.wrap_contents()
    page.insert_text(origin, new_text, fontsize=size, fontname="ED" + ("B" if bold else "") + ("I" if italic else ""),
                     fontfile=ff, color=rgb(color))
    return True


# ============================================================== HỘP THOẠI
class ColorButton(QPushButton):
    def __init__(self, color="", allow_none=False, parent=None):
        super().__init__(parent)
        self.allow_none = allow_none
        self.setFixedWidth(70)
        self.set_color(color)
        self.clicked.connect(self.pick)

    def set_color(self, c):
        self.color = c or ""
        if self.color:
            self.setStyleSheet(f"background:{self.color}; border:1px solid #888; border-radius:4px;")
            self.setText("")
        else:
            self.setStyleSheet("")
            self.setText("Không")

    def pick(self):
        dlg = QColorDialog(QColor(self.color or "#FFFFFF"), self)
        dlg.setOption(QColorDialog.ShowAlphaChannel, False)
        if self.allow_none:
            btn = QPushButton("Không màu")
            btn.clicked.connect(lambda: (self.set_color(""), dlg.reject()))
            dlg.layout().addWidget(btn)
        if dlg.exec():
            self.set_color(dlg.selectedColor().name().upper())


class AnnotPropsDialog(QDialog):
    """Tuỳ chỉnh chi tiết 1 ghi chú đã có."""

    def __init__(self, annot, parent=None):
        super().__init__(parent)
        self.annot = annot
        t = annot.type[0]
        self.setWindowTitle(f"Thuộc tính ghi chú - {annot.type[1]}")
        self.setMinimumWidth(420)
        lay = QVBoxLayout(self)
        f = QFormLayout()
        lay.addLayout(f)
        info = annot.info
        cols = annot.colors or {}
        self.content = QPlainTextEdit(info.get("content", ""))
        self.content.setFixedHeight(90)
        f.addRow("Nội dung:", self.content)
        self.author = QLineEdit(info.get("title", ""))
        f.addRow("Người ghi:", self.author)
        self.is_free = t == fitz.PDF_ANNOT_FREE_TEXT
        self.stroke = ColorButton(hexcol(cols.get("stroke")), allow_none=True)
        self.fill = ColorButton(hexcol(cols.get("fill")), allow_none=True)
        if not self.is_free:
            f.addRow("Màu viền / nét:", self.stroke)
        if t in (fitz.PDF_ANNOT_SQUARE, fitz.PDF_ANNOT_CIRCLE, fitz.PDF_ANNOT_POLYGON, fitz.PDF_ANNOT_FREE_TEXT,
                 fitz.PDF_ANNOT_LINE):
            f.addRow("Màu nền / tô:", self.fill)
        self.width = QDoubleSpinBox(decimals=1, minimum=0, maximum=30, singleStep=0.5)
        self.width.setValue(annot.border.get("width", 1) if annot.border else 1)
        if t not in (fitz.PDF_ANNOT_TEXT, fitz.PDF_ANNOT_HIGHLIGHT, fitz.PDF_ANNOT_STAMP):
            f.addRow("Độ dày nét (pt):", self.width)
        self.dash = QComboBox()
        self.dash.addItems(["Liền", "Gạch", "Chấm", "Gạch chấm"])
        dd = annot.border.get("dashes") if annot.border else None
        self.dash.setCurrentIndex(0 if not dd else 1)
        if t in (fitz.PDF_ANNOT_SQUARE, fitz.PDF_ANNOT_CIRCLE, fitz.PDF_ANNOT_LINE, fitz.PDF_ANNOT_POLYGON,
                 fitz.PDF_ANNOT_POLY_LINE):
            f.addRow("Kiểu nét:", self.dash)
        self.opacity = QSlider(Qt.Horizontal, minimum=5, maximum=100)
        self.opacity.setValue(int((annot.opacity if annot.opacity >= 0 else 1) * 100))
        self.op_lbl = QLabel(f"{self.opacity.value()}%")
        self.opacity.valueChanged.connect(lambda v: self.op_lbl.setText(f"{v}%"))
        row = QHBoxLayout()
        row.addWidget(self.opacity)
        row.addWidget(self.op_lbl)
        w = QWidget()
        w.setLayout(row)
        f.addRow("Độ trong suốt:", w)
        if self.is_free:
            st = style()
            self.font = QComboBox()
            for k, v in FONTS.items():
                self.font.addItem(v, k)
            self.fsize = QDoubleSpinBox(decimals=1, minimum=4, maximum=200)
            self.fsize.setValue(_freetext_size(annot) or st["fontsize"])
            self.tcolor = ColorButton(_freetext_color(annot) or st["text_color"])
            self.align = QComboBox()
            self.align.addItems(["Trái", "Giữa", "Phải"])
            self.border_on = QDoubleSpinBox(decimals=1, minimum=0, maximum=10)
            self.border_on.setValue(annot.border.get("width", 0) if annot.border else 0)
            f.addRow("Phông chữ:", self.font)
            f.addRow("Cỡ chữ:", self.fsize)
            f.addRow("Màu chữ:", self.tcolor)
            f.addRow("Căn lề:", self.align)
            f.addRow("Khung viền (pt):", self.border_on)
        if t == fitz.PDF_ANNOT_TEXT:
            self.icon = QComboBox()
            self.icon.addItems(NOTE_ICONS)
            f.addRow("Biểu tượng:", self.icon)
        if t == fitz.PDF_ANNOT_LINE:
            self.le_start = QComboBox()
            self.le_end = QComboBox()
            for k in LINE_ENDS:
                self.le_start.addItem(k)
                self.le_end.addItem(k)
            le = annot.line_ends or (0, 0)
            inv = {v: k for k, v in LINE_ENDS.items()}
            self.le_start.setCurrentText(inv.get(le[0], "None"))
            self.le_end.setCurrentText(inv.get(le[1], "None"))
            f.addRow("Đầu đường:", self.le_start)
            f.addRow("Cuối đường:", self.le_end)
        self.save_default = QCheckBox("Dùng làm kiểu mặc định cho ghi chú mới")
        lay.addWidget(self.save_default)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Áp dụng")
        bb.button(QDialogButtonBox.Ok).setObjectName("primary")
        bb.button(QDialogButtonBox.Cancel).setText("Huỷ")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def apply(self):
        a = self.annot
        t = a.type[0]
        a.set_info(content=self.content.toPlainText(), title=self.author.text())
        op = self.opacity.value() / 100.0
        a.set_opacity(op)
        dash = [None, [6, 3], [1, 2], [6, 3, 1, 3]][self.dash.currentIndex()]
        if self.is_free:
            a.set_border(width=self.border_on.value())
            a.update(fontsize=self.fsize.value(), fontname=self.font.currentData(),
                     text_color=rgb(self.tcolor.color), fill_color=rgb(self.fill.color),
                     border_color=None)
            if self.save_default.isChecked():
                for k, v in (("fontsize", self.fsize.value()), ("font", self.font.currentData()),
                             ("text_color", self.tcolor.color), ("fill", self.fill.color)):
                    save_style(k, v)
            return
        if t not in (fitz.PDF_ANNOT_STAMP,):
            try:
                a.set_colors(stroke=rgb(self.stroke.color), fill=rgb(self.fill.color))
            except Exception:
                a.set_colors(stroke=rgb(self.stroke.color))
        if t not in (fitz.PDF_ANNOT_TEXT, fitz.PDF_ANNOT_HIGHLIGHT, fitz.PDF_ANNOT_STAMP):
            a.set_border(width=self.width.value(), dashes=dash)
        if t == fitz.PDF_ANNOT_TEXT:
            a.set_name(self.icon.currentText())
        if t == fitz.PDF_ANNOT_LINE:
            a.set_line_ends(LINE_ENDS[self.le_start.currentText()], LINE_ENDS[self.le_end.currentText()])
        a.update()
        if self.save_default.isChecked():
            save_style("color", self.stroke.color or "#E53935")
            save_style("fill", self.fill.color)
            save_style("width", self.width.value())
            save_style("opacity", op)


def _freetext_da(annot):
    try:
        return annot.parent.parent.xref_get_key(annot.xref, "DA")[1] or ""
    except Exception:
        return ""


def _freetext_size(annot):
    import re
    m = re.search(r"([\d.]+)\s+Tf", _freetext_da(annot))
    return float(m.group(1)) if m else None


def _freetext_font(annot):
    import re
    m = re.search(r"/(\w+)\s+[\d.]+\s+Tf", _freetext_da(annot))
    return m.group(1) if m else None


def _freetext_color(annot):
    import re
    m = re.search(r"([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+rg", _freetext_da(annot))
    if m:
        return hexcol([float(m.group(i)) for i in (1, 2, 3)])
    m = re.search(r"([\d.]+)\s+g\b", _freetext_da(annot))
    if m:
        return hexcol([float(m.group(1))] * 3)
    return None


class StyleDialog(QDialog):
    """Kiểu mặc định cho công cụ vẽ (hiện khi bấm mũi tên cạnh công cụ / thanh thuộc tính)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Kiểu ghi chú mặc định")
        st = style()
        f = QFormLayout(self)
        self.color = ColorButton(st["color"])
        self.fill = ColorButton(st["fill"], allow_none=True)
        self.width = QDoubleSpinBox(decimals=1, minimum=0.2, maximum=30, value=st["width"])
        self.opacity = QSpinBox(minimum=5, maximum=100, value=int(st["opacity"] * 100), suffix=" %")
        self.dash = QComboBox()
        self.dash.addItems(list(DASHES))
        self.dash.setCurrentText(st["dash"])
        self.font = QComboBox()
        for k, v in FONTS.items():
            self.font.addItem(v, k)
        self.font.setCurrentIndex(list(FONTS).index(st["font"]) if st["font"] in FONTS else 0)
        self.fsize = QDoubleSpinBox(decimals=1, minimum=4, maximum=200, value=st["fontsize"])
        self.tcolor = ColorButton(st["text_color"])
        self.hl = ColorButton(st["highlight"])
        self.scale = QDoubleSpinBox(decimals=2, minimum=0.01, maximum=100000, value=float(st["measure_scale"]))
        self.unit = QComboBox()
        self.unit.addItems(["mm", "cm", "m"])
        self.unit.setCurrentText(st["measure_unit"])
        for lbl, w in (("Màu nét:", self.color), ("Màu tô nền:", self.fill), ("Độ dày nét:", self.width),
                       ("Kiểu nét:", self.dash), ("Độ đậm (opacity):", self.opacity), ("Phông chữ:", self.font),
                       ("Cỡ chữ:", self.fsize), ("Màu chữ:", self.tcolor), ("Màu tô sáng:", self.hl),
                       ("Tỉ lệ bản vẽ 1 :", self.scale), ("Đơn vị đo:", self.unit)):
            f.addRow(lbl, w)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        f.addRow(bb)

    def save(self):
        for k, v in (("color", self.color.color), ("fill", self.fill.color), ("width", self.width.value()),
                     ("opacity", self.opacity.value() / 100), ("dash", self.dash.currentText()),
                     ("font", self.font.currentData()), ("fontsize", self.fsize.value()),
                     ("text_color", self.tcolor.color), ("highlight", self.hl.color),
                     ("measure_scale", self.scale.value()), ("measure_unit", self.unit.currentText())):
            save_style(k, v)
