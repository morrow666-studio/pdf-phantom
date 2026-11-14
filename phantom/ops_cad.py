"""PDF bản vẽ -> CAD (DXF, và DWG qua ODA File Converter miễn phí) đúng kích thước thật.

Quy đổi: 1 pt PDF = 25.4/72 mm trên giấy. Bản vẽ tỉ lệ 1:N -> kích thước thật = mm giấy × N.
Hoặc hiệu chỉnh theo 1 kích thước đã biết (đường đo vẽ bằng công cụ 'Đo kích thước').
"""
import glob
import logging
import math
import os
import re
import shutil
import subprocess
import tempfile

import pymupdf as fitz

logging.getLogger("ezdxf").setLevel(logging.WARNING)

PT2MM = 25.4 / 72.0
LINEWEIGHTS = [0, 5, 9, 13, 15, 18, 20, 25, 30, 35, 40, 50, 53, 60, 70, 80, 90, 100, 106, 120, 140, 158, 200, 211]
UNITS = {"mm": (1.0, 4), "cm": (0.1, 5), "m": (0.001, 6)}       # hệ số từ mm, mã $INSUNITS


# ------------------------------------------------------------- nhận tỉ lệ
def detect_scale(page):
    """Tìm chữ 'TỈ LỆ 1:100', 'TL 1/50', 'SCALE 1:200' trên trang -> N hoặc None."""
    txt = page.get_text("text")
    pats = [r"(?:T[ỈỶI]\s*L[ỆE]|TL|SCALE|Scale|Tỉ lệ|Tỷ lệ)\s*[:\-]?\s*1\s*[:/]\s*(\d{1,5})"]
    found = []
    for p in pats:
        for m in re.finditer(p, txt, flags=re.IGNORECASE):
            found.append(int(m.group(1)))
    if not found:
        return None
    return max(set(found), key=found.count)


def measure_lines(page):
    """Các đường đo (công cụ Đo kích thước) trên trang: [(độ dài mm trên giấy, nhãn)]."""
    out = []
    for a in page.annots():
        if a.type[0] == fitz.PDF_ANNOT_LINE:
            v = a.vertices
            if len(v) >= 2:
                d = fitz.Point(v[0]).distance_to(fitz.Point(v[1])) * PT2MM
                out.append((d, a.info.get("content", "")))
    return out


# ------------------------------------------------------------- ODA -> DWG
def find_oda():
    from .util import config
    p = config().get("oda_path")
    if p and os.path.exists(p):
        return p
    cands = []
    for base in (r"C:\Program Files\ODA", r"C:\Program Files (x86)\ODA",
                 os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "ODA")):
        cands += glob.glob(os.path.join(base, "*", "ODAFileConverter.exe"))
        cands += glob.glob(os.path.join(base, "ODAFileConverter.exe"))
    cands.sort(reverse=True)
    return cands[0] if cands else shutil.which("ODAFileConverter")


def dxf_to_dwg(dxf_path, dwg_path, version="ACAD2018"):
    oda = find_oda()
    if not oda:
        raise RuntimeError("NO_ODA")
    tin = tempfile.mkdtemp(prefix="oda_in_")
    tout = tempfile.mkdtemp(prefix="oda_out_")
    try:
        name = "drawing.dxf"
        shutil.copy(dxf_path, os.path.join(tin, name))
        flags = 0x08000000 if os.name == "nt" else 0       # CREATE_NO_WINDOW
        subprocess.run([oda, tin, tout, version, "DWG", "0", "1", "*.DXF"], check=False, timeout=600,
                       creationflags=flags)
        res = os.path.join(tout, "drawing.dwg")
        if not os.path.exists(res):
            raise RuntimeError("ODA File Converter không tạo được file DWG.")
        shutil.move(res, dwg_path)
        return dwg_path
    finally:
        shutil.rmtree(tin, ignore_errors=True)
        shutil.rmtree(tout, ignore_errors=True)


# --------------------------------------------------------------- chuyển đổi
def _lw(width_pt):
    if not width_pt:
        return -3                       # ByDefault
    mm100 = width_pt * PT2MM * 100
    return min(LINEWEIGHTS, key=lambda v: abs(v - mm100))


def _rgb(c):
    if not c:
        return None
    return tuple(int(round(max(0, min(1, v)) * 255)) for v in c[:3])


def _layer_name(rgb, kind="NET"):
    if rgb is None:
        return "0"
    return f"{kind}_{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"


def _bezier(p0, p1, p2, p3, n):
    pts = []
    for i in range(1, n + 1):
        t = i / n
        u = 1 - t
        x = u ** 3 * p0.x + 3 * u * u * t * p1.x + 3 * u * t * t * p2.x + t ** 3 * p3.x
        y = u ** 3 * p0.y + 3 * u * u * t * p1.y + 3 * u * t * t * p2.y + t ** 3 * p3.y
        pts.append(fitz.Point(x, y))
    return pts


def _merge_dashes(items, ang_tol=0.01, off_tol=0.3):
    """Các đoạn thẳng rời, cùng phương, cùng 1 đường và có khe hở -> (đầu, cuối) hoặc None."""
    a0, b0 = items[0][1], items[0][2]
    L = a0.distance_to(b0)
    if L <= 0:
        return None
    ux, uy = (b0.x - a0.x) / L, (b0.y - a0.y) / L
    ts = []
    gaps = 0
    prev_end = None
    for it in items:
        a, b = it[1], it[2]
        for q in (a, b):
            # khoảng cách tới đường thẳng gốc
            if abs((q.x - a0.x) * uy - (q.y - a0.y) * ux) > off_tol:
                return None
        ta = (a.x - a0.x) * ux + (a.y - a0.y) * uy
        tb = (b.x - a0.x) * ux + (b.y - a0.y) * uy
        ts += [ta, tb]
        if prev_end is not None and a.distance_to(prev_end) > 0.002:
            gaps += 1
        prev_end = b
    if gaps < 2:
        return None
    tmin, tmax = min(ts), max(ts)
    return (fitz.Point(a0.x + ux * tmin, a0.y + uy * tmin), fitz.Point(a0.x + ux * tmax, a0.y + uy * tmax))


def _circle_of(items, tol=0.06):
    """Nhận dạng đường tròn vẽ bằng 4 cung Bezier -> (tâm, bán kính) hoặc None."""
    cs = [it for it in items if it[0] == "c"]
    if len(cs) != 4 or any(it[0] not in ("c", "l") for it in items):
        return None
    pts = []
    for it in cs:
        pts += _bezier(it[1], it[2], it[3], it[4], 6)
    xs = [p.x for p in pts]
    ys = [p.y for p in pts]
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    rx, ry = (max(xs) - min(xs)) / 2, (max(ys) - min(ys)) / 2
    if rx <= 0 or abs(rx - ry) / rx > tol:
        return None
    r = (rx + ry) / 2
    if any(abs(math.hypot(p.x - cx, p.y - cy) - r) / r > tol for p in pts):
        return None
    return fitz.Point(cx, cy), r


def pdf_to_dxf(doc, pno, out_path, scale=100.0, unit="mm", clip=None, include_text=True,
               include_fill=True, layer_by_color=True, detect_circles=True, curve_segments=10,
               text_font="arial.ttf", frame=True, progress=None):
    """Xuất 1 trang PDF (hoặc vùng clip - toạ độ hiển thị) ra DXF R2018 đúng kích thước thật.

    scale: N của tỉ lệ 1:N (1 = kích thước trên giấy).
    Trả về dict thống kê."""
    import ezdxf
    from ezdxf import colors as ezcolors

    page = doc[pno]
    rm = page.rotation_matrix
    vis = page.rect
    region = fitz.Rect(clip) if clip is not None else fitz.Rect(vis)
    f_unit, insunits = UNITS[unit]
    k = PT2MM * float(scale) * f_unit                  # pt (giấy) -> đơn vị CAD

    def P(p):                                          # điểm gốc -> toạ độ CAD
        v = fitz.Point(p) * rm
        return ((v.x - region.x0) * k, (region.y1 - v.y) * k)

    def inside(p):
        v = fitz.Point(p) * rm
        return region.x0 - 0.5 <= v.x <= region.x1 + 0.5 and region.y0 - 0.5 <= v.y <= region.y1 + 0.5

    dxf = ezdxf.new("R2018", setup=True)
    dxf.units = insunits
    dxf.header["$INSUNITS"] = insunits
    dxf.header["$MEASUREMENT"] = 1
    dxf.header["$LTSCALE"] = max(1.0, float(scale) * f_unit)
    msp = dxf.modelspace()
    if "PDF_TEXT" not in dxf.styles:
        dxf.styles.new("PDF_TEXT", dxfattribs={"font": text_font})
    layers = {}

    def layer(name, rgb=None):
        if name not in layers:
            if name not in dxf.layers:
                lay = dxf.layers.add(name)
                if rgb is not None:
                    if rgb in ((0, 0, 0), (255, 255, 255)):
                        lay.color = 7
                    else:
                        lay.rgb = rgb
            layers[name] = True
        return name

    stats = {"line": 0, "polyline": 0, "circle": 0, "hatch": 0, "text": 0}
    paths = page.get_drawings()
    n = len(paths)
    for idx, path in enumerate(paths):
        if progress and idx % 500 == 0 and not progress(idx, n + 1, f"Nét vẽ {idx}/{n}"):
            return None
        items = path.get("items", [])
        if not items:
            continue
        stroke = _rgb(path.get("color"))
        fill = _rgb(path.get("fill"))
        ptype = path.get("type", "s")
        r = (fitz.Rect(path.get("rect", (0, 0, 0, 0))) * rm).normalize()
        r = fitz.Rect(r.x0 - 1, r.y0 - 1, r.x1 + 1, r.y1 + 1)       # đường ngang/dọc có bề dày 0
        if clip is not None and not r.intersects(region):
            continue
        has_stroke = ptype in ("s", "fs") and stroke is not None
        lname = layer(_layer_name(stroke or fill, "NET" if has_stroke else "TO")
                      if layer_by_color else "PDF", stroke or fill)
        attribs = {"layer": lname, "lineweight": _lw(path.get("width"))}
        if stroke and stroke not in ((0, 0, 0),) and not layer_by_color:
            attribs["true_color"] = ezcolors.rgb2int(stroke)
        dashes = path.get("dashes") or ""
        if dashes and re.search(r"\[\s*[\d.]+", dashes) and not dashes.startswith("[] "):
            attribs["linetype"] = "DASHED"
        closed = bool(path.get("closePath"))

        # đường tròn
        if detect_circles:
            circ = _circle_of(items)
            if circ is not None:
                c, rad = circ
                if clip is None or inside(c):
                    if has_stroke or not include_fill:
                        msp.add_circle(P(c), rad * k, dxfattribs=attribs)
                        stats["circle"] += 1
                    if include_fill and ptype in ("f", "fs") and fill and fill != (255, 255, 255):
                        h = msp.add_hatch(dxfattribs={"layer": layer(_layer_name(fill, "TO"), fill)})
                        h.set_solid_fill(rgb=fill)
                        ep = h.paths.add_edge_path()
                        ep.add_arc(P(c), rad * k, 0, 360)
                        stats["hatch"] += 1
                continue

        # nét đứt bị "rải" thành nhiều đoạn thẳng hàng -> 1 đường DASHED
        if has_stroke and len(items) >= 3 and all(it[0] == "l" for it in items):
            merged = _merge_dashes(items)
            if merged is not None:
                a, b = merged
                if clip is None or inside(a) or inside(b):
                    at = dict(attribs)
                    at["linetype"] = "DASHED"
                    msp.add_line(P(a), P(b), dxfattribs=at)
                    stats["line"] += 1
                continue

        # dựng các polyline liền nét
        chains = []
        cur = []
        last = None
        for it in items:
            kind = it[0]
            if kind == "l":
                a, b = it[1], it[2]
                if last is None or abs(a.x - last.x) > 1e-3 or abs(a.y - last.y) > 1e-3:
                    if len(cur) > 1:
                        chains.append((cur, False))
                    cur = [a]
                cur.append(b)
                last = b
            elif kind == "c":
                a = it[1]
                if last is None or abs(a.x - last.x) > 1e-3 or abs(a.y - last.y) > 1e-3:
                    if len(cur) > 1:
                        chains.append((cur, False))
                    cur = [a]
                seglen = a.distance_to(it[4]) * k
                nseg = max(2, min(curve_segments * 3, int(curve_segments * max(1, seglen ** 0.25 / 2))))
                cur += _bezier(it[1], it[2], it[3], it[4], nseg)
                last = it[4]
            elif kind == "re":
                rr = it[1]
                chains.append(([rr.tl, rr.tr, rr.br, rr.bl], True))
                last = None
            elif kind == "qu":
                q = it[1]
                chains.append(([q.ul, q.ur, q.lr, q.ll], True))
                last = None
        if len(cur) > 1:
            chains.append((cur, closed))
        if include_fill and ptype in ("f", "fs") and fill and fill != (255, 255, 255):
            rings = [[P(p) for p in pts] for pts, cl in chains
                     if len(pts) >= 3 and (clip is None or any(inside(p) for p in pts))]
            if rings and not (len(rings) == 1 and r.width * r.height > vis.width * vis.height * 0.8):
                h = msp.add_hatch(dxfattribs={"layer": layer(_layer_name(fill, "TO"), fill)})
                h.set_solid_fill(rgb=fill)
                h.dxf.hatch_style = 0                 # chẵn-lẻ: giữ lỗ bên trong chữ
                for ring in rings:
                    h.paths.add_polyline_path(ring, is_closed=True)
                stats["hatch"] += 1
        for pts, cl in chains:
            if clip is not None and not any(inside(p) for p in pts):
                continue
            cad = [P(p) for p in pts]
            if not has_stroke:
                continue
            if len(cad) == 2 and not cl:
                msp.add_line(cad[0], cad[1], dxfattribs=attribs)
                stats["line"] += 1
            else:
                msp.add_lwpolyline(cad, close=cl, dxfattribs=attribs)
                stats["polyline"] += 1

    # chữ
    if include_text:
        font = fitz.Font("helv")
        layer("CHU", (0, 0, 0))
        d = page.get_text("dict")
        for b in d["blocks"]:
            for ln in b.get("lines", []):
                dx, dy = ln.get("dir", (1, 0))
                vdir = fitz.Point(dx, dy) * rm - fitz.Point(0, 0) * rm
                ang = math.degrees(math.atan2(-vdir.y, vdir.x))
                for sp in ln["spans"]:
                    t = sp["text"]
                    if not t.strip():
                        continue
                    org = fitz.Point(sp["origin"])
                    if clip is not None and not inside(org):
                        continue
                    size = sp["size"]
                    bw = fitz.Rect(sp["bbox"])
                    span_len = math.hypot(bw.width, bw.height) if abs(dy) > 0.01 else bw.width
                    exp = font.text_length(t, fontsize=size)
                    wf = max(0.4, min(1.6, span_len / exp)) if exp > 0 else 1.0
                    col = sp.get("color", 0)
                    rgb = ((col >> 16) & 255, (col >> 8) & 255, col & 255)
                    e = msp.add_text(t, height=size * 0.716 * k, rotation=ang, dxfattribs={
                        "layer": "CHU", "style": "PDF_TEXT", "width": round(wf, 3)})
                    if rgb != (0, 0, 0):
                        e.dxf.true_color = ezcolors.rgb2int(rgb)
                    e.set_placement(P(org))
                    stats["text"] += 1

    if frame:
        layer("KHUNG_GIAY", (128, 128, 128))
        w, h = region.width * k, region.height * k
        msp.add_lwpolyline([(0, 0), (w, 0), (w, h), (0, h)], close=True, dxfattribs={"layer": "KHUNG_GIAY"})
    dxf.saveas(out_path)
    stats["size"] = (region.width * k, region.height * k)
    if progress:
        progress(n + 1, n + 1, "Xong")
    return stats


# ------------------------------------------------- in vùng bản vẽ lên khổ giấy
PAPERS = {"A4": (210, 297), "A3": (297, 420), "A2": (420, 594), "A1": (594, 841), "A0": (841, 1189),
          "Letter": (215.9, 279.4)}


def region_on_paper(doc, pno, clip_vis, paper="A4", orient="auto", mode="fit", percent=100.0,
                    margin_mm=8, frame=False, note=""):
    """Đặt vùng chọn của trang lên 1 tờ giấy.
    mode: 'fit' vừa khổ | 'actual' đúng tỉ lệ bản gốc (100%) | 'percent' tỉ lệ % tuỳ chọn.
    Trả về (doc mới, tỉ lệ thu phóng thực tế, cảnh báo tràn giấy)."""
    page = doc[pno]
    vis = fitz.Rect(clip_vis)
    src = (vis * page.derotation_matrix).normalize()
    pw, ph = PAPERS.get(paper, PAPERS["A4"])
    W, H = pw / PT2MM, ph / PT2MM
    if orient == "landscape" or (orient == "auto" and vis.width > vis.height):
        W, H = max(W, H), min(W, H)
    else:
        W, H = min(W, H), max(W, H)
    m = margin_mm / PT2MM
    note_h = 12 if note else 0
    aw, ah = W - 2 * m, H - 2 * m - note_h
    if mode == "fit":
        s = min(aw / vis.width, ah / vis.height)
    elif mode == "actual":
        s = 1.0
    else:
        s = float(percent) / 100.0
    tw, th = vis.width * s, vis.height * s
    overflow = tw > aw + 0.5 or th > ah + 0.5
    x0 = m + max(0, (aw - tw) / 2) if not overflow else m
    y0 = m + max(0, (ah - th) / 2) if not overflow else m
    out = fitz.open()
    pg = out.new_page(width=W, height=H)
    target = fitz.Rect(x0, y0, x0 + tw, y0 + th)
    pg.show_pdf_page(target, doc, pno, clip=src, rotate=-page.rotation)
    if frame:
        pg.draw_rect(target & pg.rect, color=(0, 0, 0), width=0.6)
    if note:
        from .util import font_file
        ff = font_file("arial")
        pg.insert_text((m, H - m), note, fontsize=8, fontname="NT", fontfile=ff, color=(0.3, 0.3, 0.3))
    return out, s, overflow
