"""Bộ nhớ tạm cho TRANG PDF: Ctrl+C / Ctrl+X / Ctrl+V giữa các file (thẻ) và với Windows Explorer.

- Sao chép: các trang chọn -> 1 PDF nhỏ trong bộ nhớ + file tạm (dán vào thư mục Windows thành file PDF).
- Giữ hình chữ ký/con dấu (làm phẳng) và gắn ghi chú thông tin chữ ký số của file gốc.
"""
import os
import tempfile

import pymupdf as fitz
from PySide6.QtCore import QMimeData, QUrl, QByteArray
from PySide6.QtGui import QGuiApplication

from .util import safe_name

MIME = "application/x-pdfphantom-pages"
STAMP_MIME = "application/x-pdfphantom-stamp"
IMG_EXT = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tif", ".tiff")
_last = {"data": None, "count": 0, "source": ""}


def _tmpdir():
    d = os.path.join(tempfile.gettempdir(), "PDFPhantom_clip")
    os.makedirs(d, exist_ok=True)
    return d


def pages_to_pdf(doc, rows, source_name="", original_bytes=None):
    """Tạo PDF chỉ gồm các trang rows (giữ hình chữ ký + gắn thông tin chữ ký số)."""
    from . import siginfo
    src = fitz.open("pdf", doc.tobytes())
    infos = []
    try:
        infos = siginfo.collect(original_bytes or doc.tobytes())
    except Exception:
        infos = []
    try:
        src.bake(annots=False, widgets=True)        # chữ ký số -> hình cố định, không mất khi chép
    except Exception:
        pass
    out = fitz.open()
    for r in rows:
        out.insert_pdf(src, from_page=r, to_page=r, annots=True, links=True)
    pmap = {r: k for k, r in enumerate(rows)}
    siginfo.mark_pages(out, [i for i in infos if i["page"] in pmap], pmap, source_name)
    data = out.tobytes(garbage=3, deflate=True)
    out.close()
    src.close()
    return data


def copy_pages(tab, rows):
    name = os.path.splitext(tab.pdf.name)[0]
    data = pages_to_pdf(tab.pdf.doc, rows, tab.pdf.name,
                        None if tab.pdf.modified else tab.pdf.original_bytes)
    _last.update(data=data, count=len(rows), source=tab.pdf.name)
    label = f"{rows[0] + 1}" if len(rows) == 1 else f"{rows[0] + 1}-{rows[-1] + 1}" \
        if rows == list(range(rows[0], rows[-1] + 1)) else f"{len(rows)}trang"
    path = os.path.join(_tmpdir(), safe_name(f"{name}_trang_{label}") + ".pdf")
    with open(path, "wb") as f:
        f.write(data)
    md = QMimeData()
    md.setData(MIME, QByteArray(data))
    md.setUrls([QUrl.fromLocalFile(path)])
    QGuiApplication.clipboard().setMimeData(md)
    return len(rows)


def copy_stamp(payload):
    """Ảnh/con dấu -> bộ nhớ tạm: dán được vào trang khác, file PDF khác (giữ vị trí, cỡ, độ mờ)
    và cả Word / Zalo / Paint (dạng ảnh PNG)."""
    import base64
    import json
    from PySide6.QtGui import QImage
    d = dict(payload)
    d["png"] = base64.b64encode(payload["png"]).decode("ascii")
    md = QMimeData()
    md.setData(STAMP_MIME, QByteArray(json.dumps(d).encode("utf-8")))
    md.setImageData(QImage.fromData(payload["png"]))
    QGuiApplication.clipboard().setMimeData(md)


def clipboard_content():
    """Trả về ('pages', bytes) | ('stamp', dict) | ('files', [paths]) | ('image', QImage) | (None, None)."""
    md = QGuiApplication.clipboard().mimeData()
    if md is None:
        return None, None
    if md.hasFormat(MIME):
        return "pages", bytes(md.data(MIME))
    if md.hasFormat(STAMP_MIME):
        import json
        try:
            d = json.loads(bytes(md.data(STAMP_MIME)).decode("utf-8"))
            import base64
            d["png"] = base64.b64decode(d["png"])
            return "stamp", d
        except Exception:
            pass
    if md.hasUrls():
        files = [u.toLocalFile() for u in md.urls() if u.isLocalFile() and os.path.isfile(u.toLocalFile())]
        files = [f for f in files if f.lower().endswith((".pdf",) + IMG_EXT)]
        if files:
            return "files", files
    if md.hasImage():
        img = QGuiApplication.clipboard().image()
        if not img.isNull():
            return "image", img
    if _last["data"]:
        return "pages", _last["data"]
    return None, None


def single_page_files(doc, rows, folder, base, original_bytes=None, source_name=""):
    """Tách từng trang thành file riêng: base_trang_001.pdf ..."""
    outs = []
    for r in rows:
        data = pages_to_pdf(doc, [r], source_name, original_bytes)
        p = os.path.join(folder, safe_name(f"{base}_trang_{r + 1:03d}") + ".pdf")
        with open(p, "wb") as f:
            f.write(data)
        outs.append(p)
    return outs
