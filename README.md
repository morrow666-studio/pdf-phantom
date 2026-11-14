# PDF Phantom

Phần mềm xem và chỉnh sửa PDF cho Windows, viết bằng Python (PySide6, PyMuPDF). / A PDF viewer and editor for Windows written in Python.

Phiên bản / Version: 1.4.6

## Giấy phép / License
Mã nguồn phát hành theo **GNU Affero General Public License v3.0** (xem [LICENSE](LICENSE)).
This program is free software under the **GNU AGPL v3.0**; see [LICENSE](LICENSE).

Copyright (C) 2026 Nguyen Van Luan

Phần mềm dùng PyMuPDF (giấy phép kép AGPL-3.0 hoặc giấy phép thương mại của Artifex); bản này dùng theo AGPL-3.0, nên toàn bộ chương trình được phát hành theo AGPL-3.0. Người dùng bản phát hành trên Microsoft Store có quyền lấy mã nguồn tương ứng tại kho này.
The program uses PyMuPDF (dual-licensed AGPL-3.0 / Artifex commercial); this build uses it under AGPL-3.0, so the whole program is released under AGPL-3.0. Users of the Microsoft Store release can get the corresponding source here.

## Thư viện bên thứ ba / Third-party components
Giấy phép ghi theo thông tin của từng gói khi build; xem trang của từng dự án để biết chi tiết.

| Thành phần | Giấy phép |
|---|---|
| PyMuPDF / MuPDF | AGPL-3.0 hoặc Artifex Commercial |
| PySide6 / Qt for Python | LGPL-3.0 hoặc GPL-2.0/3.0 |
| pdf2docx, python-docx, pyHanko, python-pkcs11 | MIT |
| OpenCV (opencv-python-headless) | Apache-2.0 |
| cryptography | Apache-2.0 hoặc BSD-3-Clause |
| Pillow | MIT-CMU |
| NumPy | BSD-3-Clause và các giấy phép đi kèm |
| pymupdf-fonts | SIL OFL 1.1 |
| ezdxf | xem dự án (MIT) |
| Dữ liệu OCR Tesseract (`tessdata/eng`, `tessdata/vie`) | Apache-2.0 |

## Chạy từ mã nguồn / Run from source
```
py -3.12 -m venv venv
venv\Scripts\pip install -r requirements.txt python-pkcs11
venv\Scripts\python main.py
```
Đóng gói: `pyinstaller PDFPhantom.spec`. Bản Microsoft Store đóng thành MSIX từ thư mục PyInstaller; bản này tắt nạp plugin `.py` bên ngoài theo chính sách của Store.

## Quyền riêng tư / Privacy
https://morrow666-studio.github.io/pdf-phantom-privacy/
