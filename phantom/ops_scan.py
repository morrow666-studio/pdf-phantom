"""Scan ảnh chụp văn bản như máy scan chuyên dụng: tìm 4 góc giấy, nắn phẳng,
khử bóng, làm nét, chuyển trắng đen / xám / màu."""
import numpy as np
import cv2

MODES = {
    "doc_color": "Văn bản màu – nền trắng, GIỮ MÀU chữ, dấu đỏ, chữ ký xanh",
    "auto": "Văn bản xám – nền trắng, chữ đen (nhẹ file)",
    "bw": "Đen trắng (như máy photo)",
    "gray": "Thang xám",
    "color": "Màu tăng cường",
    "original": "Giữ nguyên ảnh gốc",
}


def imread(path):
    data = np.fromfile(path, dtype=np.uint8)          # hỗ trợ đường dẫn tiếng Việt
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        raise RuntimeError(f"Không đọc được ảnh: {path}")
    return img


def imwrite(path, img, quality=92):
    ext = "." + path.rsplit(".", 1)[-1].lower()
    params = [cv2.IMWRITE_JPEG_QUALITY, quality] if ext in (".jpg", ".jpeg") else []
    ok, buf = cv2.imencode(ext, img, params)
    if ok:
        buf.tofile(path)


def order_points(pts):
    pts = np.array(pts, dtype="float32").reshape(4, 2)
    s = pts.sum(axis=1)
    d = np.diff(pts, axis=1).ravel()
    return np.array([pts[np.argmin(s)], pts[np.argmin(d)], pts[np.argmax(s)], pts[np.argmax(d)]], dtype="float32")


def detect_document(img):
    """Trả về 4 góc (tl, tr, br, bl) theo toạ độ ảnh gốc. Không tìm thấy -> cả khung ảnh."""
    h, w = img.shape[:2]
    scale = 1000.0 / max(h, w)
    small = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1 else img.copy()
    if scale >= 1:
        scale = 1.0
    sh, sw = small.shape[:2]
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    candidates = []
    # Cách 1: cạnh Canny
    for lo, hi in ((30, 100), (50, 150), (75, 200)):
        edges = cv2.Canny(gray, lo, hi)
        edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=2)
        candidates += _quads(edges, sw, sh)
    # Cách 2: phân ngưỡng giấy sáng trên nền tối
    _, th = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    th = cv2.morphologyEx(th, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    candidates += _quads(th, sw, sh)
    if candidates:
        best = max(candidates, key=lambda q: cv2.contourArea(q))
        return order_points(best / scale)
    return np.array([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]], dtype="float32")


def _quads(binary, w, h):
    cnts, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    out = []
    for c in sorted(cnts, key=cv2.contourArea, reverse=True)[:5]:
        area = cv2.contourArea(c)
        if area < 0.15 * w * h:
            continue
        peri = cv2.arcLength(c, True)
        for eps in (0.02, 0.03, 0.05):
            approx = cv2.approxPolyDP(c, eps * peri, True)
            if len(approx) == 4 and cv2.isContourConvex(approx):
                out.append(approx.reshape(4, 2).astype("float32"))
                break
        else:
            if area > 0.3 * w * h:          # dùng hình chữ nhật xoay bao quanh
                out.append(cv2.boxPoints(cv2.minAreaRect(c)).astype("float32"))
    return out


def warp(img, quad, paper_ratio=None):
    """Nắn phẳng phối cảnh. paper_ratio = cao/rộng (A4 = 1.414) để ép đúng tỉ lệ giấy."""
    tl, tr, br, bl = order_points(quad)
    wa = np.linalg.norm(br - bl)
    wb = np.linalg.norm(tr - tl)
    ha = np.linalg.norm(tr - br)
    hb = np.linalg.norm(tl - bl)
    W = int(max(wa, wb))
    H = int(max(ha, hb))
    if paper_ratio:
        if H >= W:
            H = int(W * paper_ratio)
        else:
            W = int(H * paper_ratio)
    W, H = max(W, 10), max(H, 10)
    dst = np.array([[0, 0], [W - 1, 0], [W - 1, H - 1], [0, H - 1]], dtype="float32")
    M = cv2.getPerspectiveTransform(np.array([tl, tr, br, bl], dtype="float32"), dst)
    return cv2.warpPerspective(img, M, (W, H), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def remove_shadow(gray):
    """Chia cho nền (ước lượng bằng giãn nở + làm mờ) để khử bóng, ánh sáng không đều."""
    k = max(15, (min(gray.shape[:2]) // 25) | 1)
    bg = cv2.dilate(gray, np.ones((7, 7), np.uint8))
    bg = cv2.medianBlur(bg, k if k % 2 else k + 1)
    norm = cv2.divide(gray, bg, scale=255)
    return norm


def clean_color(img, ink_lo=18, ink_hi=135, sat=1.35):
    """Nền trắng sạch (khử bóng, cân trắng từng kênh) nhưng GIỮ ĐÚNG MÀU mực: đỏ, xanh, đen."""
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    h, w = img.shape[:2]
    k = max(15, (min(h, w) // 25) | 1)
    k = k if k % 2 else k + 1
    planes = []
    for c in cv2.split(img):
        bg = cv2.medianBlur(cv2.dilate(c, np.ones((7, 7), np.uint8)), k)
        planes.append(cv2.divide(c, np.maximum(bg, 1), scale=255))
    norm = cv2.merge(planes).astype(np.float32)          # nền ~255, mực giữ màu
    dn = 255.0 - norm                                     # "lượng mực" từng kênh
    m = dn.max(axis=2)
    # đường cong mức: bỏ vệt nền mờ, làm đậm nét mực
    t = np.clip((m - ink_lo) / float(ink_hi - ink_lo), 0, 1)
    t = t * t * (3 - 2 * t)                               # mềm mép (smoothstep)
    target = t * 235.0
    scale = np.where(m > 1, target / np.maximum(m, 1), 0)
    out = 255.0 - dn * scale[:, :, None]
    out = np.clip(out, 0, 255).astype(np.uint8)
    # tăng độ tươi màu cho nét có màu (dấu đỏ, mực xanh)
    hsv = cv2.cvtColor(out, cv2.COLOR_BGR2HSV).astype(np.float32)
    colored = hsv[:, :, 1] > 40
    hsv[:, :, 1] = np.where(colored, np.clip(hsv[:, :, 1] * sat, 0, 255), hsv[:, :, 1])
    return cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)


def enhance(img, mode="auto", sharpen=True, brightness=0, contrast=1.0):
    if mode == "original":
        out = img
    elif mode == "doc_color":
        out = clean_color(img)
    elif mode == "color":
        planes = [remove_shadow(p) for p in cv2.split(img)]
        out = cv2.merge(planes)
        lab = cv2.cvtColor(out, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        l = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(l)
        out = cv2.cvtColor(cv2.merge([l, a, b]), cv2.COLOR_LAB2BGR)
    else:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
        norm = remove_shadow(gray)
        if mode == "gray":
            out = cv2.normalize(norm, None, 0, 255, cv2.NORM_MINMAX)
        elif mode == "bw":
            blk = max(15, (min(norm.shape[:2]) // 40) | 1)
            out = cv2.adaptiveThreshold(norm, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, blk, 15)
            out = cv2.medianBlur(out, 3)
        else:  # auto: nền trắng tinh, chữ đậm nhưng giữ khử răng cưa
            n2 = cv2.normalize(norm, None, 0, 255, cv2.NORM_MINMAX)
            lut = np.clip((np.arange(256) - 60) * 255.0 / (230 - 60), 0, 255).astype(np.uint8)
            out = cv2.LUT(n2, lut)
    if sharpen and mode not in ("bw",):
        blur = cv2.GaussianBlur(out, (0, 0), 1.2)
        out = cv2.addWeighted(out, 1.5, blur, -0.5, 0)
    if brightness or contrast != 1.0:
        out = cv2.convertScaleAbs(out, alpha=contrast, beta=brightness)
    return out


def deskew(img):
    """Chỉnh nghiêng nhẹ (±10°) dựa trên các dòng chữ."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    th = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    lines = cv2.HoughLinesP(th, 1, np.pi / 720, threshold=200, minLineLength=gray.shape[1] // 4, maxLineGap=20)
    if lines is None:
        return img
    angles = []
    for x1, y1, x2, y2 in np.asarray(lines).reshape(-1, 4):
        a = np.degrees(np.arctan2(y2 - y1, x2 - x1))
        if abs(a) < 10:
            angles.append(a)
    if not angles:
        return img
    ang = float(np.median(angles))
    if abs(ang) < 0.15:
        return img
    h, w = gray.shape
    M = cv2.getRotationMatrix2D((w / 2, h / 2), ang, 1.0)
    return cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def process(img, quad=None, mode="doc_color", paper_ratio=None, do_deskew=True, rotate=0):
    quad = detect_document(img) if quad is None else quad
    out = warp(img, quad, paper_ratio)
    if rotate:
        out = np.ascontiguousarray(np.rot90(out, k=-(rotate // 90) % 4))
    out = enhance(out, mode)
    if mode != "original":
        # xoá vệt viền mép giấy còn sót sau khi nắn
        m = max(2, int(min(out.shape[:2]) * 0.006))
        out[:m] = 255
        out[-m:] = 255
        out[:, :m] = 255
        out[:, -m:] = 255
    if do_deskew and mode != "original":
        out = deskew(out)
    return out


def images_to_pdf(images, out_path, dpi=200, paper="A4", jpg_quality=85, ocr=False, lang="vie+eng",
                  tessdata=None, progress=None):
    """images: list ảnh numpy đã xử lý. Mỗi ảnh 1 trang, đặt vừa khổ giấy.
    ocr=True -> tạo lớp chữ ẩn để tìm kiếm/copy (cần Tesseract)."""
    import pymupdf as fitz
    from .ops_pages import PAPER
    out = fitz.open()
    for i, im in enumerate(images):
        if progress and not progress(i, len(images), f"Trang {i + 1}"):
            break
        h, w = im.shape[:2]
        ok, buf = cv2.imencode(".jpg" if im.ndim == 3 or not _is_binary(im) else ".png", im,
                               [cv2.IMWRITE_JPEG_QUALITY, jpg_quality])
        data = buf.tobytes()
        if paper == "auto":
            pw, ph = w * 72.0 / dpi, h * 72.0 / dpi
        else:
            pw, ph = PAPER.get(paper, PAPER["A4"])
            if w > h:
                pw, ph = ph, pw
        if ocr:
            pix = fitz.Pixmap(data)
            if pix.alpha:
                pix = fitz.Pixmap(pix, 0)
            pdfbytes = pix.pdfocr_tobytes(language=lang, tessdata=tessdata)
            src = fitz.open("pdf", pdfbytes)
            page = out.new_page(width=pw, height=ph)
            page.show_pdf_page(page.rect, src, 0, keep_proportion=True)
            src.close()
        else:
            page = out.new_page(width=pw, height=ph)
            page.insert_image(page.rect, stream=data, keep_proportion=True)
    out.save(out_path, garbage=3, deflate=True)
    out.close()
    return out_path


def _is_binary(im):
    if im.ndim != 2:
        return False
    vals = np.unique(im[::7, ::7])
    return len(vals) <= 4
