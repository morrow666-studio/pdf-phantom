"""Thông tin chữ ký số: đọc từ file gốc, gắn vào trang khi gộp / ghép / sao chép trang,
và lập trang tổng hợp. (Chữ ký số chỉ xác thực được trên file gốc – PDF không cho phép giữ
hiệu lực khi đổi trang, nên phần mềm giữ HÌNH chữ ký + THÔNG TIN ký + đính kèm bản gốc.)"""
import datetime
import hashlib
import html
import logging

import pymupdf as fitz

for _n in ("pyhanko", "pyhanko_certvalidator"):
    logging.getLogger(_n).setLevel(logging.CRITICAL)

SUBJECT = "Chữ ký số"


def _name_attr(name, key):
    try:
        return name.native.get(key, "")
    except Exception:
        return ""


def collect(data, source_name=""):
    """Đọc mọi chữ ký số trong file (bytes) -> list dict (page, rect, signer, time, ...)."""
    import io
    from pyhanko.pdf_utils.reader import PdfFileReader
    from pyhanko.sign.validation import validate_pdf_signature
    from pyhanko_certvalidator import ValidationContext
    doc = fitz.open("pdf", data)
    widgets = {}
    for pg in doc:
        for w in pg.widgets() or []:
            if w.field_type == fitz.PDF_WIDGET_TYPE_SIGNATURE:
                widgets[w.field_name] = (pg.number, fitz.Rect(w.rect) * pg.rotation_matrix)
    doc.close()
    if not widgets:
        return []
    out = []
    r = PdfFileReader(io.BytesIO(data), strict=False)
    sha = hashlib.sha256(data).hexdigest()
    for s in r.embedded_signatures:
        info = {"field": s.field_name, "page": -1, "rect": None, "signer": "", "org": "", "issuer": "",
                "serial": "", "time": None, "reason": "", "location": "", "status": "", "ok": False,
                "source": source_name, "sha256": sha}
        if s.field_name in widgets:
            info["page"], info["rect"] = widgets[s.field_name]
        try:
            cert = s.signer_cert
            info["signer"] = _name_attr(cert.subject, "common_name")
            info["org"] = _name_attr(cert.subject, "organization_name")
            info["issuer"] = _name_attr(cert.issuer, "common_name")
            info["serial"] = format(cert.serial_number, "X")
            info["valid_to"] = cert["tbs_certificate"]["validity"]["not_after"].native
        except Exception:
            pass
        try:
            t = s.self_reported_timestamp
            info["time"] = t.astimezone() if t else None
        except Exception:
            pass
        try:
            sd = s.sig_object
            info["reason"] = str(sd.get("/Reason", "") or "")
            info["location"] = str(sd.get("/Location", "") or "")
        except Exception:
            pass
        try:
            st = validate_pdf_signature(s, ValidationContext(allow_fetching=False))
            intact = st.intact and st.valid
            info["ok"] = bool(intact)
            info["status"] = "Nội dung nguyên vẹn, chữ ký hợp lệ" if intact else "Nội dung đã bị thay đổi sau khi ký"
            if intact and st.trusted:
                info["status"] += " (chứng thư tin cậy)"
        except Exception as e:
            info["status"] = f"Không kiểm tra được ({e.__class__.__name__})"
        out.append(info)
    return out


def describe(i, merged=True):
    t = i["time"].strftime("%d/%m/%Y %H:%M:%S") if i.get("time") else "(không rõ)"
    lines = [f"CHỮ KÝ SỐ – {i['signer'] or '(không rõ người ký)'}"]
    if i.get("org"):
        lines.append(f"Đơn vị: {i['org']}")
    lines.append(f"Thời gian ký: {t}")
    if i.get("reason"):
        lines.append(f"Lý do: {i['reason']}")
    if i.get("location"):
        lines.append(f"Nơi ký: {i['location']}")
    if i.get("issuer"):
        lines.append(f"Cấp bởi: {i['issuer']}")
    if i.get("serial"):
        lines.append(f"Số serial CTS: {i['serial']}")
    if i.get("valid_to"):
        try:
            lines.append(f"CTS hiệu lực đến: {i['valid_to']:%d/%m/%Y}")
        except Exception:
            pass
    if merged:
        lines.append(f"Kiểm tra khi gộp ({datetime.datetime.now():%d/%m/%Y %H:%M}): {i['status']}")
        if i.get("source"):
            lines.append(f"File gốc: {i['source']}")
        lines.append(f"Mã SHA-256 file gốc: {i['sha256'][:32]}…")
        lines.append("Lưu ý: sau khi gộp/ghép trang, chữ ký số chỉ xác thực được trên FILE GỐC "
                     "(được đính kèm trong file này nếu chọn 'đính kèm bản gốc').")
    else:
        lines.append(f"Trạng thái: {i['status']}")
    return "\n".join(lines)


def mark_pages(out_doc, infos, page_map, source_name=""):
    """Gắn ghi chú thông tin chữ ký vào trang mới. page_map: trang gốc -> trang trong out_doc."""
    n = 0
    for i in infos:
        if i["page"] not in page_map or i["rect"] is None:
            continue
        if source_name and not i.get("source"):
            i["source"] = source_name
        page = out_doc[page_map[i["page"]]]
        r = i["rect"]
        # biểu tượng chìa khoá ở góc trên phải khung chữ ký
        pt = fitz.Point(min(r.x1, page.rect.width - 22), max(r.y0 - 18, 2))
        a = page.add_text_annot(pt * page.derotation_matrix, describe(i), icon="Key")
        a.set_colors(stroke=(0.1, 0.55, 0.2) if i["ok"] else (0.85, 0.2, 0.1))
        a.set_info(title=i["signer"] or "Chữ ký số", subject=SUBJECT)
        a.update()
        # khung mảnh quanh vùng chữ ký để dễ nhận biết
        b = page.add_rect_annot((r * page.derotation_matrix).normalize())
        b.set_colors(stroke=(0.1, 0.55, 0.2) if i["ok"] else (0.85, 0.2, 0.1))
        b.set_border(width=0.6, dashes=[2, 2])
        b.set_info(title=i["signer"] or "Chữ ký số", subject=SUBJECT, content=describe(i))
        b.set_opacity(0.7)
        b.update()
        i["out_page"] = page_map[i["page"]]
        n += 1
    return n


def summary_page(out_doc, infos, title="BẢNG THÔNG TIN CHỮ KÝ SỐ CỦA CÁC TÀI LIỆU GỘP"):
    """Thêm 1 trang tổng hợp chữ ký ở cuối file."""
    if not infos:
        return None
    rows = []
    for k, i in enumerate(infos, 1):
        t = i["time"].strftime("%d/%m/%Y<br>%H:%M:%S") if i.get("time") else ""
        pg = i.get("out_page")
        rows.append(
            f"<tr><td style='text-align:center'>{k}</td><td>{html.escape(i.get('source', ''))}</td>"
            f"<td style='text-align:center'>{'' if pg is None else pg + 1}</td>"
            f"<td><b>{html.escape(i['signer'])}</b><br>{html.escape(i.get('org', ''))}</td>"
            f"<td>{t}</td><td>{html.escape(i.get('reason', ''))}</td>"
            f"<td style='color:{'#1B7F3A' if i['ok'] else '#C62828'}'>{html.escape(i['status'])}</td></tr>")
    body = (f"<p style='text-align:center;font-size:13pt;font-weight:bold;color:#C62828'>{title}</p>"
            f"<p style='font-size:8.5pt'>Lập tự động bởi PDF Phantom lúc {datetime.datetime.now():%d/%m/%Y %H:%M}. "
            "Thông tin được đọc và kiểm tra từ file gốc trước khi gộp. Chữ ký số chỉ có giá trị xác thực trên "
            "file gốc; hình chữ ký trong file gộp là bản sao trình bày.</p>"
            "<table><tr><th>STT</th><th>File gốc</th><th>Trang</th><th>Người ký / Đơn vị</th><th>Thời gian ký</th>"
            "<th>Lý do</th><th>Kết quả kiểm tra</th></tr>" + "".join(rows) + "</table>")
    css = ("* {font-family: sans-serif; font-size: 8.5pt;} table {border-collapse: collapse; width: 100%;}"
           "td, th {border: 0.6pt solid #666; padding: 2pt 3pt; vertical-align: top;} th {background: #FFE0B2;}")
    w, h = fitz.paper_size("a4")
    page = out_doc.new_page(width=w, height=h)
    page.insert_htmlbox(fitz.Rect(40, 40, w - 40, h - 40), body, css=css)
    return page.number


def file_signatures(data):
    """Chữ ký trong file + trong các bản gốc đính kèm: [(nguồn, info)]"""
    res = []
    try:
        for i in collect(data):
            res.append(("Trong file này", i))
    except Exception:
        pass
    try:
        d = fitz.open("pdf", data)
        for k in range(d.embfile_count()):
            nm = d.embfile_info(k).get("filename") or d.embfile_info(k).get("name")
            if not str(nm).lower().endswith(".pdf"):
                continue
            try:
                for i in collect(d.embfile_get(k), nm):
                    i["embedded_index"] = k
                    res.append((f"Bản gốc đính kèm: {nm}", i))
            except Exception:
                pass
        d.close()
    except Exception:
        pass
    return res
