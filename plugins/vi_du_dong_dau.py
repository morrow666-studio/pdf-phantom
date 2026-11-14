"""Plugin ví dụ cho PDF Phantom.

Cách viết plugin mới:
  1. Tạo file .py trong thư mục plugins (cạnh phần mềm) hoặc %APPDATA%\\PDFPhantom\\plugins
  2. Khai báo PLUGIN_NAME và hàm register(api)
  3. Trong register: api.add_action("Tên nút", ham_xu_ly, icon="plugin")
  4. Khởi động lại PDF Phantom -> nút xuất hiện ở tab "Tiện ích"

API có sẵn:
  api.current_document()   -> pymupdf.Document đang mở (hoặc None)
  api.current_page_index() -> số trang đang xem (bắt đầu từ 0)
  api.begin_edit() / api.end_edit()  -> bọc thao tác sửa (để Ctrl+Z hoàn tác được)
  api.message("...")        -> hiện thông báo
  api.open_file(path)       -> mở file trong phần mềm
"""
import datetime
import os

PLUGIN_NAME = "Tiện ích công trường"
PLUGIN_VERSION = "1.0"


def register(api):

    def dong_dau_trang_hien_tai():
        """Đóng dòng 'Đã kiểm tra – ngày' ở góc phải trên trang hiện tại."""
        doc = api.current_document()
        if doc is None:
            return api.message("Chưa mở file.")
        from phantom.util import font_file
        api.begin_edit()
        page = doc[api.current_page_index()]
        r = page.rect
        txt = f"Đã kiểm tra – {datetime.date.today():%d/%m/%Y}"
        page.insert_text((r.width - 200, 30), txt, fontsize=11, fontname="KT",
                         fontfile=font_file("times", bold=True), color=(0.8, 0, 0))
        api.end_edit()

    def thong_ke_thu_muc():
        """Đếm số trang tất cả file PDF trong 1 thư mục (lập danh mục hồ sơ)."""
        from PySide6.QtWidgets import QFileDialog
        import pymupdf
        d = QFileDialog.getExistingDirectory(None, "Chọn thư mục hồ sơ")
        if not d:
            return
        rows, total = [], 0
        for f in sorted(os.listdir(d)):
            if f.lower().endswith(".pdf"):
                try:
                    n = pymupdf.open(os.path.join(d, f)).page_count
                except Exception:
                    n = 0
                rows.append(f"{f}: {n} trang")
                total += n
        out = os.path.join(d, "_DanhMuc_SoTrang.txt")
        with open(out, "w", encoding="utf-8") as fh:
            fh.write("\n".join(rows) + f"\n\nTỔNG: {len(rows)} file, {total} trang\n")
        api.message(f"{len(rows)} file, tổng {total} trang.\nĐã lưu danh mục: {out}")

    api.add_action("Đóng dấu đã KT", dong_dau_trang_hien_tai, icon="stamp",
                   tooltip="Ghi 'Đã kiểm tra – ngày' lên trang hiện tại")
    api.add_action("Đếm trang thư mục", thong_ke_thu_muc, icon="info",
                   tooltip="Thống kê số trang các file PDF trong 1 thư mục")
