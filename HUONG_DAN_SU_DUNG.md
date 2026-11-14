# PDF Phantom 1.4.6 – Hướng dẫn cài đặt & sử dụng

Phần mềm PDF miễn phí, không quảng cáo, chạy hoàn toàn trên máy (trừ tính năng Claude AI cần Internet).

## 1. Cài đặt (1 lần, ~5–15 phút, cần Internet)

1. Giải nén file `PDFPhantom_1.3.zip` ra một thư mục, ví dụ `D:\PDFPhantom`.
2. Bấm đúp **`CAI_DAT.bat`** → bấm phím bất kỳ → chờ chạy xong.
   - Tự cài Python 3.12 nếu máy chưa có, tự tải thư viện, tự đóng gói ra `PDF Phantom.exe`.
   - Không cần quyền Administrator. Cài vào `%LOCALAPPDATA%\Programs\PDF Phantom`.
3. Xong: có biểu tượng **PDF Phantom** ngoài Desktop và trong menu Start.
4. Đặt làm phần mềm mặc định mở PDF: chuột phải 1 file PDF → *Open with* → *Choose another app* → **PDF Phantom** → tích *Always*.

> Nếu mạng công ty dùng proxy và bước tải thư viện lỗi: cài đặt ở mạng ngoài (4G) hoặc gửi file `%LOCALAPPDATA%\PDFPhantom\install.log` để được hỗ trợ.

**Cập nhật phiên bản mới:** giải nén bản mới → chạy lại `CAI_DAT.bat`. Cài đặt cá nhân, plugin, lịch sử file được giữ nguyên (lưu ở `%APPDATA%\PDFPhantom`).
**Gỡ cài đặt:** Settings → Apps → PDF Phantom → Uninstall.
**Chia sẻ cho đồng nghiệp (1 file Setup.exe):** sau khi cài xong, cài Inno Setup (miễn phí), mở `installer.iss` → Build.

## 2. Bố cục màn hình

- **Ribbon trên cùng** (như Office): Trang chủ · Trang · Ghi chú · Chỉnh sửa · Chuyển đổi · Bảo mật & Ký số · In ấn · Kết nối · Tiện ích.
- **Thanh Thuộc tính** (dưới ribbon): chọn 1 ghi chú → đổi ngay màu nét, **màu nền**, độ dày, kiểu nét (liền / gạch / chấm / **đám mây**), **độ mờ**, đầu mũi tên, phông/cỡ/màu chữ. Không chọn gì = chỉnh **kiểu mặc định** cho ghi chú vẽ mới.
- **Trái:** Trang (thumbnail kéo thả đổi thứ tự) · Dấu trang · Danh sách ghi chú.
- **Phải:** khung Claude AI (bật ở tab Kết nối).
- **Dưới:** số trang, mức phóng to.
- Mở nhiều file cùng lúc theo thẻ; kéo thả file PDF vào cửa sổ để mở.

## 3. Chức năng

| Nhu cầu | Thao tác |
|---|---|
| Xoay / xoá / trích / chèn / nhân bản trang | Chọn trang ở thumbnail (Ctrl/Shift để chọn nhiều) → tab **Trang** hoặc chuột phải |
| **Sắp xếp trang** | Ngay trên bảng **Trang** bên trái: nút ▲ ▼ (lên/xuống 1 vị trí), ⤒ ⤓ (lên đầu/xuống cuối), xoay, nhân bản, chèn, trích, xoá. **Giữ chuột kéo thả** từng trang (vạch cam báo chỗ thả), chọn nhiều trang bằng Ctrl/Shift rồi kéo cả nhóm. Phím tắt Ctrl+↑/↓, Ctrl+Home/End, Delete. Kéo file PDF/ảnh từ Windows thả vào bảng để chèn đúng vị trí. Ctrl+cuộn chuột: to/nhỏ hình trang |
| **Sao chép / cắt / dán trang giữa các file** | Ở bảng **Trang**: chọn trang → **Ctrl+C** (chép) hoặc **Ctrl+X** (cắt) → chuyển sang thẻ file khác → **di chuột tới vị trí cần dán** (trên bảng trang hoặc trên trang đang xem) → **Ctrl+V**. Dán vào thư mục Windows sẽ ra file PDF. Hình chữ ký + thông tin chữ ký số được giữ |
| **Tách từng trang ra file riêng** | Nút ⇶ trên bảng Trang / **Trang → Tách từng trang**; hoặc **kéo trang thả ra Desktop / thư mục** là thành file PDF |
| Sắp xếp toàn màn hình | Nút ▦ trên bảng Trang hoặc **Trang → Sắp xếp trang**: lưới hình lớn, kéo thả, chọn trang lẻ/chẵn, đảo ngược thứ tự, hoàn tác |
| Cắt lề trang | **Trang → Cắt lề** → kéo vùng giữ lại |
| **Đánh số trang** | **Trang → Đánh số trang**: mẫu (Trang 1/10, - 1 -…), kiểu số (1, 01, i, I, a, A), 6 vị trí, bắt đầu từ số bất kỳ, phạm vi trang, bỏ trang bìa, đối xứng chẵn/lẻ in 2 mặt, phông/cỡ/màu/khung, xem trước trực tiếp |
| Đầu trang / chân trang / dấu chìm | tab **Trang** |
| Ghi chú chữ, ghi chú dán, tô sáng, gạch chân/ngang | tab **Ghi chú** |
| Hình vẽ: chữ nhật, elip, đường, mũi tên, đa giác, **đám mây**, gấp khúc, vẽ tay | tab **Ghi chú** (đa giác/đám mây: bấm từng đỉnh, bấm đúp kết thúc) |
| **Con dấu** (ĐÃ DUYỆT, HOÀN CÔNG, SAO Y BẢN CHÍNH… hoặc ảnh dấu riêng), **ký hiệu** ✔ ✘ ★ ⚠… | **Ghi chú → Con dấu / Ký hiệu** (mũi tên ▼ để chọn mẫu) |
| **Đo kích thước bản vẽ** | **Ghi chú → Đo kích thước**; đặt tỉ lệ 1:100, đơn vị mm/m ở **Kiểu mặc định** |
| Tuỳ chỉnh chi tiết từng ghi chú | Công cụ **Chọn** (phím V) → bấm đúp ghi chú: màu viền/nền, độ dày, kiểu nét, độ trong suốt, phông, cỡ chữ, đầu mũi tên… Kéo để di chuyển, kéo góc phải dưới để đổi cỡ, phím Delete để xoá |
| **Sửa chữ trực tiếp** | **Chỉnh sửa → Sửa chữ** (F2) → bấm vào chữ → sửa nội dung/phông/cỡ/màu |
| Thêm chữ / tẩy trắng / che thông tin vĩnh viễn | tab **Chỉnh sửa** |
| **Gộp PDF + ảnh** | **Chuyển đổi → Gộp file** (kéo thả, sắp xếp, tự tạo bookmark) |
| **Gộp giữ chữ ký số** | Trong hộp gộp chọn: *Gộp + đính kèm bản gốc* (chữ ký từng file hợp lệ 100%) hoặc *Nối vào file đã ký* |
| Tách file | theo dải trang · mỗi N trang · từng trang · theo bookmark · theo dung lượng |
| **PDF → Ảnh** | chọn DPI (72–600), PNG/JPG/TIFF/WebP, chất lượng JPG, thang xám, nền trong |
| **PDF / ảnh scan → Word** | **Chuyển đổi → PDF → Word** hoặc **Ảnh → Word**: phần mềm **đọc chữ trên hình (OCR tiếng Việt) và gõ lại thành văn bản Word sửa được** – giữ khổ giấy, lề, căn giữa/phải/đều, thụt đầu dòng, cỡ chữ, quốc hiệu 2 cột, bảng kẻ khung. Tự nhận cả bản scan đã có lớp chữ ẩn của máy photo. Ảnh chụp điện thoại được tự nắn phẳng, khử bóng trước khi đọc. Nhiều ảnh/file → gộp 1 file Word |
| **Scan ảnh chụp điện thoại** | **Chuyển đổi → Scan ảnh chụp**: tự tìm 4 góc giấy (kéo chỉnh được), nắn phẳng, khử bóng, chế độ trắng đen / xám / màu, kèm OCR |
| OCR cho PDF scan (tìm kiếm, copy được) | **Chuyển đổi → OCR** |
| Nén PDF | **Chuyển đổi → Nén PDF** |
| **Mật khẩu & phân quyền** | **Bảo mật → Mật khẩu**: AES-256, cấm in/copy/sửa… |
| **Ký số** | **Bảo mật → Ký số** → kéo khung vị trí chữ ký → chọn USB Token (nhập PIN) hoặc file .pfx → chọn ảnh chữ ký/con dấu → Ký và lưu. Ký nhiều người lần lượt được |
| Kiểm tra chữ ký số | **Bảo mật → Kiểm tra chữ ký** |
| **In nhiều trang trên 1 tờ** | **In ấn → Nhiều trang/tờ** (2, 4, 6, 8, 9, 12, 16), xem trước, in hoặc lưu PDF |
| **In 1 khu vực của bản vẽ** | **In ấn → In vùng bản vẽ** → kéo chọn khu vực → chọn khổ A4/A3/A2/A1/A0, hướng giấy, tỉ lệ: *vừa khổ*, *đúng tỉ lệ bản vẽ gốc (100%)* hoặc % tuỳ chọn. Phần mềm tính sẵn tỉ lệ in thực tế (vd bản vẽ 1:100 phóng vừa A4 → 1:30), có xem trước, in hoặc lưu PDF |
| **PDF bản vẽ → CAD (DWG/DXF)** | **Chuyển đổi → PDF → CAD** (cả trang, nhiều trang, hoặc ▼ chọn 1 vùng). Quy đổi đúng kích thước thật: tự đọc tỉ lệ "TỈ LỆ 1:100" trên khung tên, nhập tay, hoặc hiệu chỉnh theo 1 đường đo (vẽ bằng *Đo kích thước* lên 1 kích thước đã biết rồi nhập số thật). Ra nét, polyline, đường tròn, nét đứt, hatch, chữ tiếng Việt, layer theo màu, đơn vị mm/cm/m |
| **Chọn vùng → in / chụp / copy** | **Trang chủ → Chọn vùng** → kéo vùng → menu: sao chép ảnh, lưu ảnh, in vùng (vừa khổ hoặc đúng tỉ lệ), xuất PDF, copy chữ, OCR vùng, hỏi Claude |
| **Claude AI** | **Kết nối → Claude AI**: Tóm tắt, Trích khối lượng, Soạn công văn trả lời, Kiểm tra lỗi… Cần API key (console.anthropic.com) nhập ở **Kết nối → Cài đặt** |
| Mở bằng ứng dụng khác | **Kết nối → Mở bằng…** (Word, Excel, AutoCAD… tự thêm ở *Ứng dụng ngoài*) |

## 3b. Di chuyển & thu phóng trong trang

- **Kéo trang**: giữ **chuột giữa** (con lăn) rồi kéo, hoặc giữ **Space** + kéo chuột trái, hoặc công cụ Bàn tay (H).
- **Thu phóng**: **Ctrl + cuộn chuột** (phóng tại vị trí con trỏ, mượt theo từng nấc) · **Shift + cuộn** cuộn ngang.
- **Kính lúp (Z)**: kéo khung → phóng đúng vùng đó; bấm = phóng to; chuột phải / Alt+bấm = thu nhỏ.
- **← / →**: trang trước / trang sau · **giữ ↑ hoặc ↓ (nửa giây)**: trang hiện tại về **tỉ lệ 1:1** (đúng kích thước thật), giữ lần nữa = vừa trang · bấm nhanh ↑/↓ = cuộn · **Ctrl+1** = 1:1.

## 3c. Chèn ảnh tự xoá phông nền

Kéo thả ảnh vào trang, **Ctrl+V** ảnh vừa chụp màn hình / copy, hoặc công cụ **Chèn ảnh (I)** → cửa sổ chỉnh ảnh tự xoá nền (chữ ký, con dấu chụp trên giấy). Phím tắt: **B** bật/tắt xoá nền · **[ ]** chỉnh ngưỡng · **E** chỉ xoá nền nối từ mép (giữ lòng trắng con dấu) · **C** cắt sát · **R / Shift+R** xoay · **1-4** màu mực (giữ nguyên / xanh / đỏ / đen) · **S** lưu vào thư viện con dấu · **Ctrl+Z** hoàn tác · **Enter** chèn · **Esc** huỷ.

## 3c2. Đặt ảnh: co giãn, xoay, dịch từng chút (mới 1.4)

Sau khi chỉnh ảnh (hoặc dán Ctrl+V), ảnh **chưa dính vào trang** mà ở chế độ ĐẶT ẢNH (khung cam):
- Kéo ảnh = di chuyển · kéo **góc** = co giãn (**giữ Shift** hoặc tích *Giữ tỉ lệ* = đúng tỉ lệ) · kéo **nút tròn** phía trên = xoay (giữ Shift = bước 15°).
- Thanh Thuộc tính đổi thành ô **gõ số**: X, Y, Rộng, Cao (mm), **Góc (°)**, Độ mờ, nút ⟲ 90° / ⟳ 90°.
- **← ↑ → ↓** dịch 0,5 pt · **Ctrl+mũi tên 0,1 pt (nhỏ nhất)** · Shift+mũi tên 5 pt · **[ ]** xoay 1° (Shift 15°) · **+ / −** phóng/thu 1%.
- **Enter** / bấm đúp / bấm ra ngoài = hoàn tất · **Esc** = huỷ.
- Ảnh/con dấu đã chèn: **bấm đúp** vào ảnh (hoặc chuột phải → *Xoay / co giãn / dịch chuyển ảnh*) để chỉnh lại.

## 3c3. Sao chép & nhân bản ảnh / con dấu / chữ ký (mới 1.4.6)

Bấm chọn ảnh đã chèn trên trang → thanh Thuộc tính hiện 2 nút:
- **Nhân bản sang trang / file…**: chọn *Tất cả trang · Trang lẻ · Trang chẵn · Các trang (vd 2-5, 8)*, tích thêm **các file PDF đang mở khác**; vị trí *giữ khoảng cách tới mép gần nhất* (dấu ở góc phải dưới trang A4 vẫn ở góc phải dưới trang A3). Ctrl+Z một lần là gỡ hết bản nhân trong file.
- **Sao chép (Ctrl+C)** → sang trang khác hoặc file khác bấm **Ctrl+V**: ảnh dán **đúng vị trí cũ**, chỉnh lại bằng chuột / mũi tên rồi Enter. Ở bảng Trang chọn nhiều trang rồi Ctrl+V = đóng ảnh lên tất cả trang đó. Ảnh sao chép cũng dán được sang Word, Zalo, Paint.
- Chuột phải ảnh → **Xoá ảnh này ở MỌI trang** (các bản cùng nhóm nhân bản).

## 3c5. Tách file theo trang tự chọn (mới 1.4.6)

Tab **Trang → Tách file** (hoặc chuột phải bảng Trang → *Tách file theo trang tự chọn*). Chế độ **Tự chọn trang – mỗi dòng là 1 file**:
```
Hồ sơ nghiệm thu: 1-5, 8
Bản vẽ: 10-14
20, 3, 4
```
- Dòng có `Tên:` → file mang tên đó; thứ tự trang giữ đúng như gõ; dòng bắt đầu `#` là ghi chú.
- Bấm chọn trang ở bảng Trang (Ctrl/Shift) rồi **+ Thêm trang đang chọn** → tự thêm 1 dòng (cửa sổ tách không chặn bảng Trang).
- Tích **Gom các trang chưa chọn** → thêm file "Con lai".
- Khung **Xem trước** hiện ngay tên file, trang, số trang; gõ sai trang báo lỗi đỏ.
- Chế độ khác: theo dải, **cắt tại trang** (vd 5, 12 → 1-4 | 5-11 | 12-hết), mỗi N trang, từng trang, lẻ/chẵn, bookmark, dung lượng.
- Bấm **Tách file** → hỏi ngay **lưu vào thư mục nào** (ô "Lưu vào" nhớ thư mục lần trước), trùng tên thì hỏi ghi đè; xong có nút **Mở thư mục**.
- Mặc định dùng **bản đang mở** (gồm thay đổi chưa lưu); dấu trang được giữ trong từng file.

## 3c4. Chuyển trang thành ảnh, ghép lại đúng trang (mới 1.4.6)

Tab **Trang → Thành ảnh** (hoặc chuột phải ở bảng Trang → *Chuyển trang chọn thành ảnh*): chọn trang đang xem / các trang đang chọn / toàn bộ / dải trang (vd 1-3, 7); độ phân giải 150–600 dpi; Màu / Xám / Đen trắng; JPEG hoặc PNG.
- Trang được thay bằng ảnh **ngay tại chỗ**: giữ nguyên vị trí, khổ giấy, chiều xoay, dấu trang.
- **Giữ lớp chữ ẩn**: vẫn Ctrl+F tìm, bôi đen, copy chữ được.
- **Gộp ghi chú / con dấu / chữ ký vào ảnh**: khoá cứng, không ai sửa / xoá được.
- Dùng khi: khoá nội dung trước khi gửi, sửa lỗi phông khi in, bản vẽ nặng mở chậm, hồ sơ yêu cầu dạng scan. Ctrl+Z để hoàn tác.

## 3e. Scan ảnh giữ màu (mới 1.4)

Chế độ mặc định **"Văn bản màu"**: nền trắng nhưng **giữ màu dấu đỏ, chữ ký xanh, chữ màu**. Chọn chế độ *Đen trắng / Xám* nếu muốn file nhẹ hơn.

## 3d. Ẩn / hiện thanh Điều hướng

Bấm **F4**, hoặc nút **Điều hướng** ở tab Trang chủ, hoặc chuột phải lên thanh ribbon → chọn *Điều hướng* / *Khôi phục bố cục mặc định*. Mở lại phần mềm thì thanh Điều hướng luôn hiện.

## 4. Phím tắt

Ctrl+O mở · Ctrl+S lưu · Ctrl+P in · Ctrl+Z / Ctrl+Y hoàn tác / làm lại · Ctrl+F tìm · Ctrl+cuộn chuột phóng to · Ctrl+0 vừa rộng · V chọn · H bàn tay · T hộp chữ · N ghi chú dán · R chữ nhật · C đám mây · M đo · P vẽ tay · F2 sửa chữ · Esc bỏ công cụ · Delete xoá ghi chú/trang.

Rê chuột lên **ô chữ ký số** trên trang → hiện khung xanh (hợp lệ) / đỏ (lỗi) và thông tin người ký, thời gian, tình trạng; bấm vào để xem chi tiết.

## 5. Lưu ý quan trọng

- **Chữ ký số khi gộp / ghép trang:** theo chuẩn PDF, chữ ký số chỉ còn hiệu lực xác thực trên file gốc. Phần mềm giữ **hình chữ ký**, gắn **thẻ thông tin ký** 🔑 (người ký, đơn vị, thời gian, đơn vị cấp CTS, số serial, kết quả kiểm tra) ngay tại chữ ký – di chuột lên để xem, thêm **trang tổng hợp chữ ký** cuối file gộp, và **đính kèm file gốc**. Tab **Chữ ký** ở bảng điều hướng liệt kê tất cả; nút *Mở bản gốc* mở file gốc còn nguyên chữ ký để kiểm tra.
- **File có chữ ký số:** khi lưu sau khi sửa, phần mềm hỏi: *Lưu bản sao giữ chữ ký* (chỉ thêm ghi chú, chữ ký còn hiệu lực) hoặc *Lưu đè* (chữ ký mất hiệu lực).
- **Ký số bằng USB Token:** cần cài driver token của nhà cung cấp (Viettel-CA, VNPT-CA, FPT-CA, BKAV-CA…). Phần mềm tự dò file thư viện `.dll`; nếu không thấy, chọn thủ công trong `C:\Windows\System32`.
- **PDF → CAD:** chỉ áp dụng cho PDF xuất từ phần mềm CAD (dạng nét). Bản vẽ scan là ảnh nên không chuyển thành nét được. Kích thước (DIM), block, layer gốc không còn trong PDF nên ra nét thường. Lưu thẳng DWG cần cài thêm **ODA File Converter** (miễn phí, opendesign.com); nếu không cài thì lưu DXF – AutoCAD mở trực tiếp, sau đó Save As DWG.
- **OCR → Word:** chính xác cao với bản scan rõ (≥ 200 DPI). Chữ viết tay, con dấu đè chữ, bảng không kẻ khung có thể sai – nên soát lại.
- **Lỗi phát sinh:** chi tiết ghi tại `%APPDATA%\PDFPhantom\loi.log`.

## 6. Mở rộng bằng plugin

Chép file `.py` vào `%APPDATA%\PDFPhantom\plugins` rồi mở lại phần mềm – nút mới xuất hiện ở tab **Tiện ích**. Xem mẫu `plugins\vi_du_dong_dau.py` (đóng dấu "Đã kiểm tra", đếm số trang cả thư mục hồ sơ).
