"""In tài liệu bằng máy in Windows (hộp thoại in chuẩn) - tự xoay giấy theo trang,
co vừa khổ, in vùng chọn."""
import pymupdf as fitz
from PySide6.QtCore import Qt, QRectF, QSizeF, QMarginsF
from PySide6.QtGui import QPainter, QPageLayout, QPageSize
from PySide6.QtPrintSupport import QPrinter, QPrintDialog
from PySide6.QtWidgets import QMessageBox, QProgressDialog, QApplication

from .viewer import pix_to_qimage


def _page_size_for(page):
    """Khổ giấy đúng bằng kích thước trang PDF (khớp A4/A3/A2... nếu gần đúng)."""
    w, h = page.rect.width, page.rect.height
    ps = QPageSize(QSizeF(min(w, h), max(w, h)), QPageSize.Point, "", QPageSize.FuzzyMatch)
    return ps, (QPageLayout.Landscape if w > h else QPageLayout.Portrait)


def print_document(parent, doc, title="PDF Phantom", pages=None, fit=True, max_dpi=300, exact=False):
    """exact=True: in ĐÚNG KÍCH THƯỚC trang PDF lên giấy cùng khổ (không co giãn) -
    dùng cho in bản vẽ theo tỉ lệ."""
    printer = QPrinter(QPrinter.HighResolution)
    printer.setDocName(title)
    if exact:
        ps, orient = _page_size_for(doc[0])
        printer.setPageSize(ps)
        printer.setPageOrientation(orient)
        printer.setFullPage(True)
        printer.setPageMargins(QMarginsF(0, 0, 0, 0), QPageLayout.Millimeter)
    else:
        printer.setPageSize(QPageSize(QPageSize.A4))
    printer.setFromTo(1, doc.page_count)
    dlg = QPrintDialog(printer, parent)
    dlg.setWindowTitle("In tài liệu")
    dlg.setOption(QPrintDialog.PrintPageRange, True)
    dlg.setOption(QPrintDialog.PrintCurrentPage, False)
    dlg.setMinMax(1, doc.page_count)
    if dlg.exec() != QPrintDialog.Accepted:
        return False
    if pages is None:
        if printer.printRange() == QPrinter.PageRange:
            pages = list(range(printer.fromPage() - 1, printer.toPage()))
        else:
            pages = list(range(doc.page_count))
    copies = 1
    dpi = min(printer.resolution(), max_dpi)
    prog = QProgressDialog("Đang gửi lệnh in…", "Huỷ", 0, len(pages), parent)
    prog.setWindowModality(Qt.WindowModal)
    painter = None
    try:
        for k, pno in enumerate(pages):
            if prog.wasCanceled():
                break
            prog.setValue(k)
            QApplication.processEvents()
            page = doc[pno]
            land = page.rect.width > page.rect.height
            if exact:
                ps, orient = _page_size_for(page)
                printer.setPageSize(ps)
                printer.setPageOrientation(orient)
            else:
                printer.setPageOrientation(QPageLayout.Landscape if land else QPageLayout.Portrait)
            if painter is None:
                painter = QPainter()
                if not painter.begin(printer):
                    raise RuntimeError("Không mở được máy in.")
            elif k:
                printer.newPage()
            target = QRectF(painter.viewport())
            # giới hạn ~80 triệu điểm ảnh cho khổ lớn (A1, A0)
            area_in2 = page.rect.width * page.rect.height / 5184.0
            d = min(dpi, int((80e6 / max(area_in2, 1)) ** 0.5))
            pix = page.get_pixmap(dpi=d, annots=True)
            img = pix_to_qimage(pix)
            if exact:
                # đúng 1:1 theo kích thước vật lý (1 pt = 1/72 inch), gốc tại mép giấy
                k = printer.resolution() / 72.0
                painter.drawImage(QRectF(0, 0, page.rect.width * k, page.rect.height * k), img)
                continue
            if fit:
                s = min(target.width() / img.width(), target.height() / img.height())
            else:
                s = printer.resolution() / dpi
            w, h = img.width() * s, img.height() * s
            r = QRectF(target.x() + (target.width() - w) / 2, target.y() + (target.height() - h) / 2, w, h)
            painter.drawImage(r, img)
        prog.setValue(len(pages))
    except Exception as e:
        QMessageBox.critical(parent, "In", f"Lỗi khi in: {e}")
        return False
    finally:
        if painter is not None:
            painter.end()
    return True
