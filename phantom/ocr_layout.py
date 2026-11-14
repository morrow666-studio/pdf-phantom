"""Dựng Word GIỐNG BẢN GỐC từ trang scan / ảnh chụp đã OCR.

Nguyên tắc:
- Cỡ chữ đo theo BỀ RỘNG chữ thật (so với số đo phông Times New Roman), không theo chiều cao – chính xác ±0,5pt.
- Đậm / nghiêng nhận theo nét chữ trên ảnh (độ dày nét, độ nghiêng nét).
- Mỗi dòng đặt đúng chân chữ (baseline) như bản gốc: khoảng cách dòng "Chính xác" (Exactly) + khoảng trước đoạn
  tính từ vị trí tuyệt đối -> không bị dồn lệch dần xuống cuối trang.
- Lề trang, thụt dòng, căn giữa/phải/đều, khối 2 cột (quốc hiệu, nơi nhận/ký tên), bảng kẻ khung: đặt đúng toạ độ.
- keep_lines=True: giữ nguyên chỗ xuống dòng như bản gốc (giống nhất khi in ra);
  False: văn bản liền mạch (dễ sửa thêm nội dung).
"""
import re
import statistics

import numpy as np
import pymupdf as fitz

from .util import config, font_file

F_BASE = 0.8          # baseline nằm ở 80% chiều cao dòng (chế độ Exactly)
DESC_CH = set("gjpqyQ,;()[]{}|/@_ạặậẹệịọộợụựỵẠẶẬẸỆỊỌỘỢỤỰỴ")
SIZES = [6, 7, 7.5, 8, 8.5, 9, 9.5, 10, 10.5, 11, 11.5, 12, 12.5, 13, 13.5, 14, 14.5, 15, 16, 17, 18, 20,
         22, 24, 26, 28, 32, 36, 40, 48, 54, 60, 72]


# ============================================================ số đo phông chữ
class FontMetrics:
    _cache = {}

    def __init__(self, path):
        from fontTools.ttLib import TTFont
        self.f = TTFont(path, lazy=True, fontNumber=0)
        self.upm = self.f["head"].unitsPerEm
        self.cmap = self.f.getBestCmap() or {}
        self.hmtx = self.f["hmtx"]
        self.glyf = self.f["glyf"] if "glyf" in self.f else None
        self._ch = {}

    @classmethod
    def get(cls, family="times", bold=False, italic=False):
        key = (family, bold, italic)
        if key not in cls._cache:
            p = font_file(family, bold, italic)
            cls._cache[key] = cls(p) if p else None
        return cls._cache[key]

    def ch(self, c):
        """(advance, xMin, xMax) theo em."""
        if c in self._ch:
            return self._ch[c]
        g = self.cmap.get(ord(c))
        if g is None:
            r = (0.5, 0.05, 0.45)
        else:
            adv = self.hmtx[g][0] / self.upm
            x0, x1 = 0.0, adv
            if self.glyf is not None:
                try:
                    gl = self.glyf[g]
                    if not hasattr(gl, "xMin"):
                        gl.recalcBounds(self.glyf)
                    if hasattr(gl, "xMin") and gl.numberOfContours != 0:
                        x0, x1 = gl.xMin / self.upm, gl.xMax / self.upm
                except Exception:
                    pass
            r = (adv, x0, x1)
        self._ch[c] = r
        return r

    def advance(self, text):
        return sum(self.ch(c)[0] for c in text)

    def ink(self, word):
        """Bề rộng mực của 1 từ (em) và phần lề trái/phải của mực so với khung chữ."""
        if not word:
            return 0, 0, 0
        adv = [self.ch(c)[0] for c in word]
        first, last = self.ch(word[0]), self.ch(word[-1])
        w = sum(adv[:-1]) + last[2] - first[1]
        return max(w, 0.01), first[1], adv[-1] - last[2]


# ============================================================ phân tích ảnh
class InkImage:
    def __init__(self, page, dpi=300):
        import cv2
        pix = page.get_pixmap(dpi=dpi, colorspace=fitz.csGRAY, annots=False)
        g = np.frombuffer(pix.samples, np.uint8).reshape(pix.h, pix.w)
        _, th = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        self.mask = th > 0
        self.k = dpi / 72.0

    def crop(self, r):
        k = self.k
        y0, y1 = max(0, int(r.y0 * k)), min(self.mask.shape[0], int(r.y1 * k) + 1)
        x0, x1 = max(0, int(r.x0 * k)), min(self.mask.shape[1], int(r.x1 * k) + 1)
        return self.mask[y0:y1, x0:x1]

    def baseline(self, rect):
        """Chân chữ: hàng cuối cùng còn mật độ mực cao (bỏ qua phần chân g, p, y, dấu nặng)."""
        k = self.k
        m = self.crop(fitz.Rect(rect.x0, rect.y0, rect.x1, rect.y1 + 1))
        if m.size == 0 or m.shape[0] < 4:
            return None
        prof = m.sum(axis=1).astype(np.float64)
        if prof.max() <= 0:
            return None
        # làm mượt nhẹ rồi tìm hàng cuối có mật độ >= 35% đỉnh
        sm = np.convolve(prof, [0.25, 0.5, 0.25], mode="same")
        thr = sm.max() * 0.35
        p = int(np.argmax(sm))
        last = p
        while last + 1 < len(sm) and sm[last + 1] >= thr:     # dò xuống từ hàng đậm nhất
            last += 1
        y0 = max(0, int(rect.y0 * k))
        return (y0 + last + 1) / k

    def stroke(self, rects):
        """Độ dày nét trung bình (px) = 2*diện tích mực / chu vi."""
        import cv2
        A = P = 0
        for r in rects:
            m = self.crop(r)
            if m.size == 0:
                continue
            mu = m.astype(np.uint8)
            er = cv2.erode(mu, np.ones((3, 3), np.uint8))
            A += int(mu.sum())
            P += int((mu - er).sum())
        return 2.0 * A / P if P else 0.0

    def slant(self, rects):
        """Độ nghiêng nét chữ (tan góc). Chữ nghiêng (italic) ~ 0.2-0.3."""
        best_k, best_s = 0.0, -1
        crops = [self.crop(r) for r in rects if r.width > 4]
        crops = [c for c in crops if c.size and c.shape[0] > 6]
        if not crops:
            return 0.0
        for kk in np.arange(-0.10, 0.41, 0.05):
            s = 0.0
            for m in crops:
                h, w = m.shape
                ys, xs = np.nonzero(m)
                if len(xs) == 0:
                    continue
                xn = np.round(xs - kk * (h - ys)).astype(int) + int(0.42 * h) + 2
                cols = np.bincount(xn, minlength=w + h)
                s += float((cols.astype(np.float64) ** 2).sum()) / max(len(xs), 1)
            if s > best_s:
                best_s, best_k = s, kk
        return float(best_k)


# ============================================================ dòng & đoạn
def _baseline(words):
    clean = [r.y1 for r, t in words if not (set(t) & DESC_CH)]
    if clean:
        return statistics.median(clean)
    hs = statistics.median(r.height for r, _ in words)
    return statistics.median(r.y1 for r, _ in words) - hs * 0.18


def build_segments(lines, gap_factor=1.3):
    """Gom các từ cùng hàng -> hàng; khoảng trống lớn -> tách thành đoạn cột (segment)."""
    words = []
    for l in lines:
        words += l["words"]
    words.sort(key=lambda w: (w[0].y0 + w[0].y1) / 2)
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
    out = []
    for wl in rows:
        wl.sort(key=lambda w: w[0].x0)
        h = statistics.median(w[0].height for w in wl)
        segs, cur = [], [wl[0]]
        for w in wl[1:]:
            if w[0].x0 - cur[-1][0].x1 > h * gap_factor:
                segs.append(cur)
                cur = [w]
            else:
                cur.append(w)
        segs.append(cur)
        out.append([_seg(s) for s in segs])
    return out


def _seg(words):
    bb = fitz.Rect(words[0][0])
    for r, _ in words[1:]:
        bb |= r
    return {"words": words, "bbox": bb, "text": " ".join(t for _, t in words), "base": _baseline(words)}


def snap_size(s):
    s = min(SIZES, key=lambda v: abs(v - s))
    return s


class Styler:
    """Đo cỡ chữ (theo bề rộng), đậm, nghiêng cho từng đoạn chữ."""

    def __init__(self, ink, family="times"):
        self.ink = ink
        self.family = family

    def measure(self, seg):
        words = [(r, t) for r, t in seg["words"] if len(t) >= 2] or seg["words"]
        rects = [r for r, _ in words]
        seg["stroke"] = self.ink.stroke(rects) if self.ink else 0
        if self.ink:
            bl = self.ink.baseline(seg["bbox"])
            if bl is not None and abs(bl - seg["base"]) < seg["bbox"].height * 0.6:
                seg["base"] = bl
        seg["slant"] = self.ink.slant(rects[:6]) if self.ink else 0
        # cỡ chữ theo bề rộng cho 4 kiểu phông -> chọn sau khi biết đậm/nghiêng
        sizes = {}
        for b in (False, True):
            for i in (False, True):
                fm = FontMetrics.get(self.family, b, i)
                if fm is None:
                    continue
                ink_px = sum(r.width for r, _ in words)
                em = sum(fm.ink(t)[0] for _, t in words)
                sizes[(b, i)] = ink_px / em if em else seg["bbox"].height
        seg["sizes"] = sizes

    def finalize(self, segs):
        """Đậm khi nét dày hơn rõ rệt so với nét chữ phổ biến của trang (tính theo cỡ chữ)."""
        rel = []
        for s in segs:
            base = s["sizes"].get((False, False)) or s["bbox"].height
            s["rel_stroke"] = s["stroke"] / max(base * (self.ink.k if self.ink else 1), 1e-3)
            if len(s["text"]) >= 12:
                rel.append(s["rel_stroke"])
        med = statistics.median(rel) if rel else (statistics.median([s["rel_stroke"] for s in segs]) if segs else 0.08)
        for s in segs:
            s["bold"] = s["rel_stroke"] > med * 1.22 and s["rel_stroke"] > 0.07
            s["italic"] = s["slant"] >= 0.15
            key = (s["bold"], s["italic"])
            raw = s["sizes"].get(key) or s["sizes"].get((False, False)) or s["bbox"].height
            s["size_raw"] = raw
            s["size"] = snap_size(raw)
            fm = FontMetrics.get(self.family, s["bold"], s["italic"])
            first, last = s["words"][0][1], s["words"][-1][1]
            _, lsb, _ = fm.ink(first) if fm else (0, 0, 0)
            _, _, rsb = fm.ink(last) if fm else (0, 0, 0)
            s["x0"] = s["bbox"].x0 - lsb * s["size"]           # gốc chữ (không phải mép mực)
            s["x1"] = s["bbox"].x1 + rsb * s["size"]


# ============================================================ ghi Word
class LayoutWriter:
    def __init__(self, font_name="Times New Roman", family="times", keep_lines=True):
        from docx import Document
        self.doc = Document()
        self.font_name = font_name
        self.family = family
        self.keep_lines = keep_lines
        self.first_page = True
        st = self.doc.styles["Normal"]
        st.font.name = font_name
        st.paragraph_format.space_after = 0
        st.paragraph_format.space_before = 0
        self._fonts(st.element)
        body = self.doc.element.body
        for p in list(body.iterchildren()):
            if p.tag.endswith("}p"):
                body.remove(p)

    # ---------------------------------------------------------- tiện ích docx
    def _fonts(self, el):
        from docx.oxml.ns import qn
        rpr = el.get_or_add_rPr()
        rf = rpr.find(qn("w:rFonts"))
        if rf is None:
            rf = rpr.makeelement(qn("w:rFonts"), {})
            rpr.insert(0, rf)
        for a in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
            rf.set(qn(a), self.font_name)

    def _run(self, p, text, size, bold, italic, spacing=0.0):
        from docx.shared import Pt
        from docx.oxml.ns import qn
        r = p.add_run(text)
        r.font.size = Pt(size)
        r.bold = bool(bold) or None
        r.italic = bool(italic) or None
        self._fonts(r._element)
        if abs(spacing) >= 0.05:
            rpr = r._element.get_or_add_rPr()
            sp = rpr.makeelement(qn("w:spacing"), {qn("w:val"): str(int(round(spacing * 20)))})
            rpr.append(sp)
        return r

    def _para(self, container, L, before, align=None, left=0.0, first=0.0):
        from docx.shared import Pt
        from docx.enum.text import WD_LINE_SPACING
        p = container.add_paragraph()
        pf = p.paragraph_format
        pf.line_spacing_rule = WD_LINE_SPACING.EXACTLY
        pf.line_spacing = Pt(max(L, 1.0))
        pf.space_before = Pt(max(0.0, round(before, 1)))
        pf.space_after = Pt(0)
        pf.widow_control = False
        if align is not None:
            pf.alignment = align
        if abs(left) >= 0.5:
            pf.left_indent = Pt(left)
        if abs(first) >= 0.5:
            pf.first_line_indent = Pt(first)
        return p

    def _fit_spacing(self, text, seg, avail=None, stretch=True):
        """Giãn/co ký tự để dòng rộng đúng như bản gốc; luôn co lại nếu vượt khung (tránh nhảy dòng)."""
        fm = FontMetrics.get(self.family, seg["bold"], seg["italic"])
        if fm is None or len(text) < 2:
            return 0.0
        nat = fm.advance(text) * seg["size"]
        n = len(text) - 1
        sp = 0.0
        if stretch:
            target = seg["x1"] - seg["x0"]
            if abs(target - nat) / max(target, 1) > 0.008:
                sp = max(-1.0, min(1.0, (target - nat) / n))
        if avail is not None and nat + sp * n > avail - 0.8:
            sp = min(sp, (avail - 0.8 - nat) / n)
            sp = max(sp, -1.5)
        return sp

    # ---------------------------------------------------------------- trang
    def page(self, segrows, tables, W, H, ink_words=0):
        from docx.shared import Pt
        from docx.enum.section import WD_ORIENT, WD_SECTION
        allsegs = [s for row in segrows for s in row]
        # lề trái/phải theo các dòng dài (căn trái / căn đều)
        long_ = [s for s in allsegs if (s["x1"] - s["x0"]) > W * 0.45]
        if long_:
            left = statistics.median(sorted(s["x0"] for s in long_)[:max(3, len(long_) // 3)])
            right_edge = statistics.median(sorted((s["x1"] for s in long_), reverse=True)[:max(2, len(long_) // 2)])
        else:
            xs = [s["x0"] for s in allsegs] or [85]
            left = max(28, min(xs))
            right_edge = W - left * 0.7
        left = max(10.0, min(left, 200.0))
        right_edge = max(left + 100, min(right_edge, W - 10))
        self.left, self.right_edge = left, right_edge
        self.cw = right_edge - left
        # các khối theo chiều dọc
        items = []
        for row in segrows:
            items.append(("row", min(s["base"] - s["size"] * 0.9 for s in row), row))
        for t in tables:
            items.append(("table", t["rect"].y0, t))
        items.sort(key=lambda x: x[1])
        first_top = items[0][1] if items else 57
        top_margin = max(8.0, first_top - 4)
        last_bottom = max([t["rect"].y1 for t in tables] + [s["base"] + s["size"] * 0.3 for s in allsegs] + [H - 60])
        bottom_margin = max(6.0, min(H - last_bottom - 6, 57.0))
        if self.first_page:
            sec = self.doc.sections[0]
            self.first_page = False
        else:
            sec = self.doc.add_section(WD_SECTION.NEW_PAGE)
        sec.orientation = WD_ORIENT.LANDSCAPE if W > H else WD_ORIENT.PORTRAIT
        sec.page_width, sec.page_height = Pt(W), Pt(H)
        sec.left_margin = Pt(left)
        sec.right_margin = Pt(W - right_edge)
        sec.top_margin = Pt(top_margin)
        sec.bottom_margin = Pt(bottom_margin)
        sec.header_distance = sec.footer_distance = Pt(max(4, min(top_margin, bottom_margin) / 2))
        self.cursor = top_margin
        self.last_was_table = False
        # gom khối
        i = 0
        para_rows = []
        while i < len(items):
            kind, y, obj = items[i]
            if kind == "table":
                self._flush(para_rows)
                para_rows = []
                self._data_table(obj)
                i += 1
                continue
            row = obj
            if len(row) >= 2 or self._is_offset_single(row):
                # khối nhiều cột: lấy thêm các hàng kế tiếp thuộc cùng các cột
                self._flush(para_rows)
                para_rows = []
                block = [row]
                cols = self._columns(row)
                j = i + 1
                while j < len(items) and items[j][0] == "row":
                    nxt = items[j][2]
                    gap = min(s["base"] for s in nxt) - max(s["base"] for s in block[-1])
                    size = max(s["size"] for s in nxt)
                    if gap > size * 4.5:
                        break
                    if len(nxt) >= 2 or self._fits_cols(nxt[0], cols):
                        block.append(nxt)
                        j += 1
                    else:
                        break
                if len(block) == 1 and len(row) == 1:
                    para_rows.append(row[0])
                else:
                    self._column_block(block)
                i = j if not (len(block) == 1 and len(row) == 1) else i + 1
                continue
            para_rows.append(row[0])
            i += 1
        self._flush(para_rows)

    # ---------------------------------------------------------- phân loại hàng
    def _is_offset_single(self, row):
        return False

    def _columns(self, row):
        return [(s["x0"], s["x1"]) for s in row]

    def _fits_cols(self, seg, cols):
        if len(cols) < 2:
            return False
        for a, b in cols:
            if seg["x0"] >= a - 30 and seg["x1"] <= b + 30:
                return True
        c = (seg["x0"] + seg["x1"]) / 2
        return any(abs(c - (a + b) / 2) < (b - a) * 0.5 for a, b in cols) and \
            (seg["x1"] - seg["x0"]) < self.cw * 0.6

    # ------------------------------------------------------------- đoạn văn
    def _flush(self, segs):
        if not segs:
            return
        for g in self._group(segs):
            self._paragraph(self.doc, g, self.left, self.right_edge)

    def _group(self, segs):
        groups, cur = [], []
        for s in segs:
            if not cur:
                cur = [s]
                continue
            p = cur[-1]
            pitch = s["base"] - p["base"]
            same_style = abs(s["size"] - p["size"]) <= 0.6 and s["bold"] == p["bold"] and s["italic"] == p["italic"]
            prev_pitch = cur[-1]["base"] - cur[-2]["base"] if len(cur) >= 2 else None
            new = (not same_style or pitch > p["size"] * 1.9 or pitch <= 0
                   or (prev_pitch and abs(pitch - prev_pitch) > p["size"] * 0.35)
                   or self.right_edge - p["x1"] > self.cw * 0.12            # dòng trước kết thúc sớm
                   or s["x0"] - cur[0]["x0"] > p["size"] * 1.2 and len(cur) > 1   # thụt đầu dòng mới
                   or self._is_center(p) != self._is_center(s))
            if new:
                groups.append(cur)
                cur = [s]
            else:
                cur.append(s)
        if cur:
            groups.append(cur)
        return groups

    def _is_center(self, s, a=None, b=None):
        a = self.left if a is None else a
        b = self.right_edge if b is None else b
        mid = (a + b) / 2
        c = (s["x0"] + s["x1"]) / 2
        return abs(c - mid) < (b - a) * 0.03 and s["x0"] - a > (b - a) * 0.04

    def _paragraph(self, container, g, a, b, cursor_attr="cursor", owner=None):
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        owner = owner or self
        cw = b - a
        size = statistics.median(s["size"] for s in g)
        x0s = [s["x0"] for s in g]
        x1s = [s["x1"] for s in g]
        if len(g) > 1:
            L = statistics.median(g[k + 1]["base"] - g[k]["base"] for k in range(len(g) - 1))
        else:
            L = size * 1.15
        L = max(L, size * 0.9)
        centered = all(self._is_center(s, a, b) for s in g)
        right = all(b - s["x1"] < cw * 0.02 for s in g) and min(x0s) - a > cw * 0.25
        justified = len(g) > 1 and sum(1 for x in x1s[:-1] if b - x < cw * 0.015) >= (len(g) - 1) * 0.6
        align, left_ind, first = None, 0.0, 0.0
        if centered:
            align = WD_ALIGN_PARAGRAPH.CENTER
        elif right:
            align = WD_ALIGN_PARAGRAPH.RIGHT
        else:
            left_ind = (min(x0s[1:]) if len(g) > 1 else x0s[0]) - a
            left_ind = 0.0 if abs(left_ind) < 1.2 else left_ind
            first = (x0s[0] - a - left_ind) if len(g) > 1 else 0.0
            if justified:
                align = WD_ALIGN_PARAGRAPH.JUSTIFY
        top_target = g[0]["base"] - F_BASE * L
        before = top_target - getattr(owner, cursor_attr)
        p = self._para(container, L, before, align, left_ind, first)
        if not self.keep_lines and len(g) > 1:
            text = " ".join(s["text"] for s in g)
            sp = 0.0
            self._run(p, text, size, g[0]["bold"], g[0]["italic"], sp)
        else:
            for k, s in enumerate(g):
                avail = cw - left_ind - (first if k == 0 else 0)
                last = k == len(g) - 1
                stretch = not (justified and not last) and not centered
                sp = self._fit_spacing(s["text"], s, avail, stretch=stretch)
                s2 = dict(s, size=size)
                self._run(p, s["text"], size, s2["bold"], s2["italic"], sp)
                if not last:
                    p.add_run().add_break()
        setattr(owner, cursor_attr, g[-1]["base"] + (1 - F_BASE) * L)
        self.last_was_table = False
        return p

    # ------------------------------------------------------ khối nhiều cột
    def _spacer(self, gap, force=False):
        """Đoạn trống cao đúng 'gap' pt để đẩy bảng xuống đúng vị trí."""
        if gap < 0.8 and not (force or self.last_was_table):
            return
        p = self._para(self.doc, max(gap, 1.0), 0)
        self.cursor += max(gap, 1.0)
        return p

    def _column_block(self, block):
        from docx.shared import Pt
        segs = [s for row in block for s in row]
        # các cột theo cụm toạ độ x
        cols = []
        for s in sorted(segs, key=lambda s: s["x0"]):
            c = (s["x0"] + s["x1"]) / 2
            for col in cols:
                if s["x0"] < col["x1"] - 2 and s["x1"] > col["x0"] + 2 or abs(c - col["c"]) < 40:
                    col["segs"].append(s)
                    col["x0"] = min(col["x0"], s["x0"])
                    col["x1"] = max(col["x1"], s["x1"])
                    col["c"] = statistics.median((q["x0"] + q["x1"]) / 2 for q in col["segs"])
                    break
            else:
                cols.append({"segs": [s], "x0": s["x0"], "x1": s["x1"], "c": c})
        cols.sort(key=lambda c: c["x0"])
        # biên mỗi cột: cột căn giữa -> đối xứng quanh tâm; cột căn trái -> từ mép trái chữ
        page_l, page_r = 6.0, self.page_w - 6.0
        bounds = []
        for k, col in enumerate(cols):
            lo = cols[k - 1]["x1"] + 2 if k else page_l
            hi = cols[k + 1]["x0"] - 2 if k + 1 < len(cols) else page_r
            xs0 = [s["x0"] for s in col["segs"]]
            centered = len(col["segs"]) > 1 and (max(xs0) - min(xs0)) > 6 and \
                statistics.pstdev([(s["x0"] + s["x1"]) / 2 for s in col["segs"]]) < 6
            if len(col["segs"]) == 1:
                centered = False
            if centered:
                c = col["c"]
                hw = min(c - lo, hi - c)
                hw = max(hw, (col["x1"] - col["x0"]) / 2 + 3)
                bounds.append([c - hw, c + hw, True])
            else:
                bounds.append([col["x0"], min(hi, max(col["x1"] + 8, col["x0"] + 40)), False])
        # khử chồng lấn: chọn ranh giới giữa 2 cột, thu hẹp ĐỐI XỨNG cột căn giữa (giữ đúng tâm chữ)
        for k in range(1, len(bounds)):
            if bounds[k][0] < bounds[k - 1][1]:
                B = (cols[k - 1]["x1"] + cols[k]["x0"]) / 2
                for j, side in ((k - 1, "right"), (k, "left")):
                    a_, b_, cen = bounds[j]
                    if cen:
                        c = (a_ + b_) / 2
                        hw = (b_ - a_) / 2
                        hw = min(hw, (B - c) if side == "right" else (c - B))
                        hw = max(hw, (cols[j]["x1"] - cols[j]["x0"]) / 2 + 0.5)
                        bounds[j] = [c - hw, c + hw, True]
                    else:
                        if side == "right":
                            bounds[j][1] = max(min(b_, B), cols[j]["x1"] + 0.5)
                        else:
                            bounds[j][0] = min(max(a_, B), cols[j]["x0"])
                if bounds[k][0] < bounds[k - 1][1]:          # vẫn chồng (cột quá sát) -> chia đôi
                    mid = (bounds[k][0] + bounds[k - 1][1]) / 2
                    bounds[k - 1][1] = mid
                    bounds[k][0] = mid
        widths, cells = [], []
        x = bounds[0][0]
        for k, (a, b, cen) in enumerate(bounds):
            if a - x > 0.5:
                widths.append(a - x)
                cells.append(None)
            widths.append(b - a)
            cells.append(k)
            x = b
        top = min(s["base"] - F_BASE * max(s["size"] * 1.15, 1) for s in segs)
        # đẩy bảng xuống đúng vị trí
        self._spacer(top - self.cursor, force=True)
        t = self.doc.add_table(rows=1, cols=len(widths))
        _table_setup(t, widths, indent=bounds[0][0] - self.left, borders=False)
        bottom = top
        for ci, k in enumerate(cells):
            if k is None:
                continue
            cell = t.cell(0, ci)
            cell._element.remove(cell.paragraphs[0]._element)
            a, b, cen = bounds[k]
            holder = _Cursor(top)
            cs = sorted(cols[k]["segs"], key=lambda s: s["base"])
            for g in self._group_cell(cs, a, b):
                self._paragraph(cell, g, a, b, "cursor", holder)
            if not cell.paragraphs:
                cell.add_paragraph()
            bottom = max(bottom, holder.cursor)
        for ci, k in enumerate(cells):
            if k is None:
                c = t.cell(0, ci)
                if not c.paragraphs:
                    c.add_paragraph()
                _exact_para(c.paragraphs[0], 1.0)
        _row_height(t.rows[0], bottom - top)
        self.cursor = bottom
        self.last_was_table = True

    def _group_cell(self, segs, a, b):
        groups, cur = [], []
        for s in segs:
            if cur:
                p = cur[-1]
                pitch = s["base"] - p["base"]
                prev = cur[-1]["base"] - cur[-2]["base"] if len(cur) >= 2 else None
                same = abs(s["size"] - p["size"]) <= 0.6 and s["bold"] == p["bold"] and s["italic"] == p["italic"]
                if same and 0 < pitch < p["size"] * 1.9 and (prev is None or abs(pitch - prev) < p["size"] * 0.35) \
                        and self._is_center(s, a, b) == self._is_center(p, a, b):
                    cur.append(s)
                    continue
                groups.append(cur)
            cur = [s]
        if cur:
            groups.append(cur)
        return groups

    # ------------------------------------------------------------ bảng kẻ khung
    def _data_table(self, tb):
        from docx.shared import Pt
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        xs, ys = tb["xs"], tb["ys"]
        self._spacer(ys[0] - self.cursor, force=True)
        widths = [xs[k + 1] - xs[k] for k in range(len(xs) - 1)]
        t = self.doc.add_table(rows=len(ys) - 1, cols=len(widths))
        _table_setup(t, widths, indent=xs[0] - self.left, borders=True)
        for r in range(len(ys) - 1):
            _row_height(t.rows[r], ys[r + 1] - ys[r])
            for c in range(len(widths)):
                cell = t.cell(r, c)
                segs = tb["cells"].get((r, c), [])
                cell._element.remove(cell.paragraphs[0]._element)
                if not segs:
                    _exact_para(cell.add_paragraph(), 1.0)
                    continue
                holder = _Cursor(ys[r])
                a, b = xs[c], xs[c + 1]
                for g in self._group_cell(sorted(segs, key=lambda s: s["base"]), a + 2, b - 2):
                    self._paragraph(cell, g, a, b, "cursor", holder)
        self.cursor = ys[-1]
        self.last_was_table = True

    def save(self, path):
        # tài liệu kết thúc bằng bảng -> Word yêu cầu 1 đoạn sau bảng
        body = self.doc.element.body
        last = [e for e in body.iterchildren() if not e.tag.endswith("}sectPr")]
        if last and last[-1].tag.endswith("}tbl"):
            _exact_para(self.doc.add_paragraph(), 1.0)
        self.doc.save(path)


class _Cursor:
    def __init__(self, y):
        self.cursor = y


def _exact_para(p, L):
    from docx.shared import Pt
    from docx.enum.text import WD_LINE_SPACING
    pf = p.paragraph_format
    pf.line_spacing_rule = WD_LINE_SPACING.EXACTLY
    pf.line_spacing = Pt(L)
    pf.space_before = Pt(0)
    pf.space_after = Pt(0)


def _row_height(row, h):
    from docx.shared import Pt
    from docx.enum.table import WD_ROW_HEIGHT_RULE
    row.height = Pt(max(h, 2))
    row.height_rule = WD_ROW_HEIGHT_RULE.EXACTLY


def _table_setup(t, widths, indent=0.0, borders=True):
    from docx.shared import Pt
    from docx.oxml.ns import qn
    t.autofit = False
    tbl = t._tbl
    tblPr = tbl.tblPr
    def el(tag, **attrs):
        e = tblPr.makeelement(qn(tag), {qn(k): str(v) for k, v in attrs.items()})
        return e
    for tag in ("w:tblW", "w:tblInd", "w:tblLayout", "w:tblCellMar", "w:tblBorders"):
        for old in tblPr.findall(qn(tag)):
            tblPr.remove(old)
    tblPr.append(el("w:tblW", **{"w:w": int(sum(widths) * 20), "w:type": "dxa"}))
    tblPr.append(el("w:tblInd", **{"w:w": int(indent * 20), "w:type": "dxa"}))
    tblPr.append(el("w:tblLayout", **{"w:type": "fixed"}))
    mar = el("w:tblCellMar")
    for side in ("top", "left", "bottom", "right"):
        mar.append(mar.makeelement(qn(f"w:{side}"), {qn("w:w"): "0", qn("w:type"): "dxa"}))
    tblPr.append(mar)
    bd = el("w:tblBorders")
    for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
        attrs = {qn("w:val"): "single", qn("w:sz"): "4", qn("w:space"): "0", qn("w:color"): "000000"} if borders \
            else {qn("w:val"): "nil"}
        bd.append(bd.makeelement(qn(f"w:{side}"), attrs))
    tblPr.append(bd)
    # lưới cột
    grid = tbl.tblGrid
    cols = grid.findall(qn("w:gridCol"))
    for gc, w in zip(cols, widths):
        gc.set(qn("w:w"), str(int(w * 20)))
    for row in t.rows:
        for c, w in zip(row.cells, widths):
            c.width = Pt(w)


# ============================================================ điều phối
def page_to_layout(writer, page, tpage, tables_raw, lines, scale_xy=(1.0, 1.0), ocr_cell=None):
    """lines: từ ocr_lines/native_lines (toạ độ trang); tables_raw: [(rect, xs, ys)] toạ độ trang.
    scale_xy: hệ số quy khổ giấy (ảnh chụp -> A4 chuẩn)."""
    sx, sy = scale_xy
    M = fitz.Matrix(sx, 0, 0, sy, 0, 0)
    W, H = page.rect.width * sx, page.rect.height * sy
    ink = InkImage(tpage)
    styler = Styler(ink, writer.family)
    # từ thuộc bảng kẻ khung
    tables = []
    for rect, xs, ys in tables_raw:
        tables.append({"rect": fitz.Rect(rect), "xs": list(xs), "ys": list(ys), "words": []})
    body_lines = []
    for ln in lines:
        keep = []
        for r, t in ln["words"]:
            c = fitz.Point((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2)
            for tb in tables:
                if tb["rect"].contains(c):
                    tb["words"].append((r, t))
                    break
            else:
                keep.append((r, t))
        if keep:
            body_lines.append({"words": keep})
    segrows = build_segments(body_lines)
    allsegs = [s for row in segrows for s in row]
    # ô bảng: OCR riêng từng ô nếu có, ngược lại dùng từ đã có
    for tb in tables:
        xs, ys = tb["xs"], tb["ys"]
        tb["cells"] = {}
        grid = {}
        for r, t in tb["words"]:
            cx, cy = (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2
            c = max(0, min(len(xs) - 2, sum(1 for x in xs[1:-1] if cx > x)))
            rr = max(0, min(len(ys) - 2, sum(1 for y in ys[1:-1] if cy > y)))
            grid.setdefault((rr, c), []).append((r, t))
        for rr in range(len(ys) - 1):
            for c in range(len(xs) - 1):
                words = None
                if ocr_cell is not None:
                    words = ocr_cell(fitz.Rect(xs[c] + 1.5, ys[rr] + 1.5, xs[c + 1] - 1.5, ys[rr + 1] - 1.5))
                if not words:
                    words = grid.get((rr, c))
                if words:
                    rows = build_segments([{"words": words}], gap_factor=99)
                    tb["cells"][(rr, c)] = [s for row in rows for s in row]
                    allsegs += tb["cells"][(rr, c)]
    for s in allsegs:
        styler.measure(s)
    styler.finalize(allsegs)
    # bỏ "chữ rác" do nhiễu ảnh (dấu chấm bẩn, vệt mờ): không có chữ/số hoặc nét quá mảnh
    def junk(s):
        alnum = sum(ch.isalnum() for ch in s["text"])
        return alnum == 0 or (s["rel_stroke"] < 0.03 and alnum <= 3)
    bad = {id(s) for s in allsegs if junk(s)}
    if bad:
        segrows = [[s for s in row if id(s) not in bad] for row in segrows]
        segrows = [r for r in segrows if r]
        for tb in tables:
            tb["cells"] = {k: [s for s in v if id(s) not in bad] for k, v in tb["cells"].items()}
        allsegs = [s for s in allsegs if id(s) not in bad]
    # cỡ chữ ô bảng ngắn ("m", "2") -> theo cỡ phổ biến của bảng
    for tb in tables:
        cs = [s for v in tb["cells"].values() for s in v]
        sz = [s["size"] for s in cs if len(s["text"]) >= 4]
        common = statistics.median(sz) if sz else None
        for s in cs:
            if common and (len(s["text"]) < 4 or abs(s["size"] - common) <= 1.0):
                s["size"] = snap_size(common)
    # quy đổi toạ độ sang khổ giấy đích
    if (sx, sy) != (1.0, 1.0):
        for s in allsegs:
            s["x0"] *= sx
            s["x1"] *= sx
            s["base"] *= sy
            s["bbox"] = s["bbox"] * M
        for tb in tables:
            tb["rect"] = tb["rect"] * M
            tb["xs"] = [x * sx for x in tb["xs"]]
            tb["ys"] = [y * sy for y in tb["ys"]]
    writer.page_w = W
    writer.page(segrows, tables, W, H)
    return len(allsegs)


def paper_scale(w, h):
    """Khổ gần A4/A3/Letter (±4%) -> trả về (khổ đích, hệ số x, y)."""
    for pw, ph in ((595.28, 841.89), (841.89, 1190.55), (612, 792)):
        for a, b in ((pw, ph), (ph, pw)):
            if abs(w / a - 1) < 0.04 and abs(h / b - 1) < 0.04:
                return (a, b), (a / w, b / h)
    return (w, h), (1.0, 1.0)
