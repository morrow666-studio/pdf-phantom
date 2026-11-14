"""PDF Phantom - điểm khởi động.
Mở 1 cửa sổ duy nhất: bấm đúp file PDF khác sẽ mở thêm thẻ trong cửa sổ đang chạy."""
import logging
import os
import sys
import traceback

# Chạy từ mã nguồn: thêm thư mục chứa file này vào sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMessageBox

from phantom import APP_NAME, VERSION
from phantom.util import user_dir

SERVER_NAME = "PDFPhantom_SingleInstance_v1"

# Bản exe dạng cửa sổ không có console: tránh lỗi khi thư viện in ra stdout/stderr
class _Null:
    def write(self, *a):
        return 0

    def flush(self):
        pass


if sys.stdout is None:
    sys.stdout = _Null()
if sys.stderr is None:
    sys.stderr = _Null()


def setup_logging():
    log_path = os.path.join(user_dir(), "loi.log")
    logging.basicConfig(filename=log_path, level=logging.WARNING, encoding="utf-8",
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return log_path


def excepthook(etype, value, tb):
    msg = "".join(traceback.format_exception(etype, value, tb))
    logging.error(msg)
    try:
        box = QMessageBox()
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("PDF Phantom – lỗi")
        box.setText(f"Có lỗi xảy ra: {value}\n\nPhần mềm vẫn tiếp tục chạy. Chi tiết đã ghi vào:\n"
                    f"{os.path.join(user_dir(), 'loi.log')}")
        box.setDetailedText(msg)
        box.exec()
    except Exception:
        pass


def send_to_running(files):
    # cho phép cửa sổ đang chạy được nhảy lên trên cùng (Windows chặn mặc định)
    if sys.platform.startswith("win"):
        try:
            import ctypes
            ctypes.windll.user32.AllowSetForegroundWindow(-1)      # ASFW_ANY
        except Exception:
            pass
    sock = QLocalSocket()
    sock.connectToServer(SERVER_NAME)
    if not sock.waitForConnected(400):
        return False
    sock.write(("\n".join(files) or "__show__").encode("utf-8"))
    sock.flush()
    sock.waitForBytesWritten(1000)
    sock.disconnectFromServer()
    return True


def selftest():
    """Kiểm tra nhanh các thành phần (dùng: "PDF Phantom.exe" --selftest)."""
    import tempfile
    import pymupdf
    out = []
    try:
        from phantom import ops_pages, ops_scan, ops_ocr, ops_sign, annots, dialogs, dialog_scan, dialog_sign, ai
        from phantom.util import tessdata_dir, font_file
        d = pymupdf.open()
        p = d.new_page()
        p.insert_text((72, 100), "Kiểm tra tiếng Việt", fontname="F", fontfile=font_file("times"))
        ops_pages.add_page_numbers(d, {})
        annots.add_textbox(p, (72, 200, 300, 240), "Ghi chú")
        out.append("PDF + ghi chú: OK")
        out.append("Font tiếng Việt: " + str(font_file("times")))
        out.append("Dữ liệu OCR: " + str(tessdata_dir()))
        if tessdata_dir():
            tp = p.get_textpage_ocr(language="vie", dpi=150, full=True, tessdata=tessdata_dir())
            out.append("OCR: " + p.get_text(textpage=tp).strip().splitlines()[0])
        import pdf2docx, docx, cv2, pyhanko  # noqa
        from phantom import ops_cad
        dx = os.path.join(tempfile.gettempdir(), "phantom_selftest.dxf")
        st = ops_cad.pdf_to_dxf(d, 0, dx, scale=100)
        out.append(f"PDF -> CAD (DXF): OK ({st['text']} chữ)")
        out.append("ODA File Converter (DWG): " + str(ops_cad.find_oda() or "chưa cài – dùng DXF"))
        if tessdata_dir():
            sp = os.path.join(tempfile.gettempdir(), "phantom_selftest_scan.pdf")
            sd = pymupdf.open()
            sp_page = sd.new_page()
            sp_page.insert_image(sp_page.rect, pixmap=p.get_pixmap(dpi=200))
            sd.save(sp)
            wd = os.path.join(tempfile.gettempdir(), "phantom_selftest.docx")
            ops_ocr.pdf_to_word(sp, wd, mode="ocr")
            from docx import Document
            txt = " ".join(x.text for x in Document(wd).paragraphs)
            out.append("Scan -> Word giống bản gốc: " + ("OK" if "Việt" in txt else "LỖI: " + txt[:60]))
        from pyhanko.pdf_utils.font.opentype import GlyphAccumulatorFactory  # noqa
        tmp = os.path.join(tempfile.gettempdir(), "phantom_selftest.pfx")
        ops_sign.make_test_pfx(tmp, "1")
        ops_sign.load_pfx(tmp, "1")
        out.append("Ký số (pyHanko): OK")
        try:
            import pkcs11  # noqa
            out.append("USB Token (PKCS#11): OK")
        except Exception:
            out.append("USB Token (PKCS#11): chưa cài python-pkcs11")
        out.append("TẤT CẢ OK")
    except Exception as e:
        out.append("LỖI: " + repr(e))
        out.append(traceback.format_exc())
    res = "\n".join(out)
    with open(os.path.join(user_dir(), "selftest.txt"), "w", encoding="utf-8") as f:
        f.write(res)
    print(res)
    return 0 if "TẤT CẢ OK" in res else 1


def main():
    if "--selftest" in sys.argv:
        return selftest()
    setup_logging()
    sys.excepthook = excepthook
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(VERSION)
    app.setOrganizationName("PC1")
    app.setFont(QFont("Segoe UI", 10))
    files = [os.path.abspath(a) for a in sys.argv[1:] if os.path.isfile(a)]

    if "--new-window" not in sys.argv and send_to_running(files):
        return 0

    from phantom.mainwindow import MainWindow
    win = MainWindow()
    server = QLocalServer()
    QLocalServer.removeServer(SERVER_NAME)
    server.listen(SERVER_NAME)

    def on_conn():
        s = server.nextPendingConnection()
        if not s:
            return

        def read():
            data = bytes(s.readAll()).decode("utf-8", "ignore")
            for p in data.splitlines():
                if os.path.isfile(p):
                    win.open_file(p)
            win.bring_to_front()
        s.readyRead.connect(read)
    server.newConnection.connect(on_conn)

    win.show()
    for f in files:
        QTimer.singleShot(0, lambda f=f: win.open_file(f))
    # lần đầu mở: luôn đưa cửa sổ lên màn hình chính, trên cùng
    QTimer.singleShot(50, win.bring_to_front)
    QTimer.singleShot(700, win.bring_to_front)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
