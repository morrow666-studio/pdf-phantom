"""Ký số PDF chuẩn PAdES bằng pyHanko.

Hỗ trợ:
 - Chứng thư số dạng file .pfx/.p12 (có mật khẩu)
 - USB Token (Viettel-CA, VNPT-CA, FPT-CA, BKAV-CA, MISA-CA...) qua thư viện PKCS#11 (.dll)
   do nhà cung cấp token cài vào máy.
 - Hiển thị khung chữ ký (tên, thời gian, lý do, ảnh chữ ký/con dấu) đặt đúng vị trí chọn.
 - Dấu thời gian (TSA) tuỳ chọn.
 - Kiểm tra chữ ký số có trong file.
"""
import os
import glob
import logging
import datetime

for _n in ("pyhanko", "pyhanko_certvalidator", "pyhanko.sign", "fontTools"):
    logging.getLogger(_n).setLevel(logging.CRITICAL)

from .util import font_file

# Tên file DLL PKCS#11 thường gặp của các nhà cung cấp chứng thư số tại Việt Nam.
# (Danh sách tham khảo - tên có thể khác tuỳ phiên bản driver; phần mềm sẽ tự dò thêm.)
KNOWN_P11 = [
    "viettel-ca_v*.dll", "viettel*p11*.dll", "vnpt-ca*.dll", "vnptca*.dll", "fptca*.dll",
    "fpt*pkcs11*.dll", "bkavca*.dll", "bkav*p11*.dll", "misa*.dll", "nacencomm*.dll",
    "safenet*.dll", "eTPKCS11.dll", "eps2003csp11*.dll", "ShuttleCsp11*.dll", "gclib.dll",
    "*pkcs11*.dll", "*p11*.dll", "*csp11*.dll",
]


def find_pkcs11_dlls():
    win = os.environ.get("WINDIR", r"C:\Windows")
    dirs = [os.path.join(win, "System32"), os.path.join(win, "SysWOW64"),
            r"C:\Program Files", r"C:\Program Files (x86)"]
    found = []
    for d in dirs[:2]:
        for pat in KNOWN_P11:
            for f in glob.glob(os.path.join(d, pat)):
                if f not in found:
                    found.append(f)
    for d in dirs[2:]:
        for pat in ("*/*pkcs11*.dll", "*/*p11*.dll", "*/*/*pkcs11*.dll", "*/*csp11*.dll"):
            for f in glob.glob(os.path.join(d, pat)):
                if f not in found:
                    found.append(f)
    return found


# ------------------------------------------------------------- tải signer
def load_pfx(path, password):
    from pyhanko.sign import signers
    pw = password.encode("utf-8") if password else None
    signer = signers.SimpleSigner.load_pkcs12(pfx_file=path, passphrase=pw)
    if signer is None:
        raise RuntimeError("Không mở được file chứng thư: sai mật khẩu hoặc file hỏng.")
    return signer


def list_token_certs(dll_path, pin):
    """Liệt kê chứng thư trong USB token: [(label, id_hex, subject)]"""
    import pkcs11
    from pkcs11 import Attribute, ObjectClass
    from asn1crypto import x509
    lib = pkcs11.lib(dll_path)
    out = []
    for slot in lib.get_slots(token_present=True):
        token = slot.get_token()
        with token.open(user_pin=pin) as sess:
            for obj in sess.get_objects({Attribute.CLASS: ObjectClass.CERTIFICATE}):
                try:
                    label = obj[Attribute.LABEL]
                except Exception:
                    label = ""
                try:
                    cid = bytes(obj[Attribute.ID]).hex()
                except Exception:
                    cid = ""
                try:
                    cert = x509.Certificate.load(bytes(obj[Attribute.VALUE]))
                    subj = cert.subject.human_friendly
                    exp = cert["tbs_certificate"]["validity"]["not_after"].native
                    subj += f"  (hết hạn {exp:%d/%m/%Y})"
                except Exception:
                    subj = label
                out.append((token.label, label, cid, subj))
    return out


class TokenSigner:
    """Ngữ cảnh mở phiên token, trả về signer của pyHanko."""

    def __init__(self, dll_path, pin, token_label=None, cert_label=None, cert_id=None):
        self.args = (dll_path, pin, token_label, cert_label, cert_id)
        self.session = None

    def __enter__(self):
        from pyhanko.sign import pkcs11 as p11
        dll, pin, token_label, cert_label, cert_id = self.args
        kw = {}
        if token_label:
            kw["token_label"] = token_label
        self.session = p11.open_pkcs11_session(dll, user_pin=pin, **kw)
        skw = {}
        if cert_id:
            skw["cert_id"] = bytes.fromhex(cert_id)
            skw["key_id"] = bytes.fromhex(cert_id)
        elif cert_label:
            skw["cert_label"] = cert_label
            skw["key_label"] = cert_label
        return p11.PKCS11Signer(self.session, **skw)

    def __exit__(self, *a):
        try:
            self.session.close()
        except Exception:
            pass


def signer_name(signer):
    try:
        cert = signer.signing_cert
        cn = cert.subject.native.get("common_name")
        return cn or cert.subject.human_friendly
    except Exception:
        return ""


# ---------------------------------------------------------------- ký
def sign_pdf(in_path, out_path, signer, page_index=0, box=None, page_height=None,
             reason="", location="", contact="", image_path=None, show_text=True,
             text_lines=None, tsa_url=None, field_name=None, certify=False,
             text_color="#C00000"):
    """box: (x0, y0, x1, y1) theo toạ độ PyMuPDF (gốc trên-trái, đơn vị pt, trang chưa xoay).
    page_height: chiều cao mediabox để đổi sang toạ độ PDF (gốc dưới-trái)."""
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
    from pyhanko.sign import signers, fields, timestamps
    from pyhanko import stamp
    from pyhanko.pdf_utils.layout import SimpleBoxLayoutRule, AxisAlignment, Margins

    name = signer_name(signer)
    field_name = field_name or "ChuKy_" + datetime.datetime.now().strftime("%Y%m%d%H%M%S")

    with open(in_path, "rb") as inf:
        w = IncrementalPdfFileWriter(inf, strict=False)
        if box is not None:
            x0, y0, x1, y1 = box
            ph = page_height
            pdf_box = (int(x0), int(ph - y1), int(x1), int(ph - y0))
            fields.append_signature_field(w, fields.SigFieldSpec(
                sig_field_name=field_name, on_page=page_index, box=pdf_box))
        else:
            fields.append_signature_field(w, fields.SigFieldSpec(sig_field_name=field_name))

        meta = signers.PdfSignatureMetadata(
            field_name=field_name, reason=reason or None, location=location or None,
            contact_info=contact or None, md_algorithm="sha256", subfilter=None,
            certify=certify)

        style = None
        if box is not None:
            from pyhanko.pdf_utils import images
            lines = text_lines if text_lines is not None else default_lines(name, reason, location)
            png = make_appearance(box[2] - box[0], box[3] - box[1], lines if show_text else [],
                                  image_path, color=text_color)
            style = stamp.TextStampStyle(
                stamp_text="", border_width=0, background=images.PdfImage(png),
                background_opacity=1.0,
                background_layout=SimpleBoxLayoutRule(
                    x_align=AxisAlignment.ALIGN_MID, y_align=AxisAlignment.ALIGN_MID,
                    margins=Margins.uniform(0)))
        ts = timestamps.HTTPTimeStamper(tsa_url) if tsa_url else None
        pdf_signer = signers.PdfSigner(meta, signer=signer, stamp_style=style, timestamper=ts)
        with open(out_path, "wb") as outf:
            pdf_signer.sign_pdf(w, output=outf, appearance_text_params={"signer": name})
    return out_path


def default_lines(name, reason="", location="", when=None):
    when = when or datetime.datetime.now()
    out = [f"Ký bởi: {name}", f"Ngày ký: {when:%d/%m/%Y %H:%M:%S}"]
    if reason:
        out.append(f"Lý do: {reason}")
    if location:
        out.append(f"Nơi ký: {location}")
    return out


def make_appearance(w, h, lines, image_path=None, color="#C00000", zoom=4):
    """Dựng hình khung chữ ký (PNG trong suốt): ảnh chữ ký/con dấu bên trái, chữ bên phải."""
    import pymupdf as fitz
    import tempfile
    doc = fitz.open()
    page = doc.new_page(width=w, height=h)
    text_rect = fitz.Rect(2, 2, w - 2, h - 2)
    if image_path:
        if lines:
            img_rect = fitz.Rect(2, 2, min(h * 1.2, w * 0.42), h - 2)
            text_rect = fitz.Rect(img_rect.x1 + 3, 2, w - 2, h - 2)
        else:
            img_rect = fitz.Rect(2, 2, w - 2, h - 2)
        page.insert_image(img_rect, filename=image_path, keep_proportion=True)
    if lines:
        ff = font_file("arial") or font_file("times")
        col = tuple(int(color.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4))
        font = fitz.Font(fontfile=ff) if ff else fitz.Font("helv")
        lh = 1.2
        size_h = text_rect.height / (len(lines) * lh)
        size_w = min(text_rect.width / max(font.text_length(l, fontsize=1), 1e-3) for l in lines)
        size = max(3.0, min(13.0, size_h, size_w * 0.98))
        block_h = len(lines) * size * lh
        y = text_rect.y0 + (text_rect.height - block_h) / 2 + size * 0.95
        for l in lines:
            page.insert_text((text_rect.x0, y), l, fontsize=size, fontname="SigF", fontfile=ff, color=col)
            y += size * lh
    pix = page.get_pixmap(dpi=72 * zoom, alpha=True)
    path = os.path.join(tempfile.gettempdir(), f"phantom_sig_{os.getpid()}.png")
    pix.save(path)
    doc.close()
    return path


# ------------------------------------------------------------ kiểm tra
def verify_pdf(path):
    """Trả về danh sách kết quả từng chữ ký (chuỗi tiếng Việt)."""
    from pyhanko.pdf_utils.reader import PdfFileReader
    from pyhanko.sign.validation import validate_pdf_signature
    from pyhanko_certvalidator import ValidationContext
    out = []
    with open(path, "rb") as f:
        r = PdfFileReader(f, strict=False)
        sigs = r.embedded_signatures
        if not sigs:
            return ["File không có chữ ký số."]
        vc = ValidationContext(allow_fetching=False)
        for s in sigs:
            try:
                st = validate_pdf_signature(s, vc)
                cert = s.signer_cert
                who = cert.subject.native.get("common_name", "") if cert else ""
                when = s.self_reported_timestamp
                if when is not None:
                    when = when.astimezone()
                intact = "Nguyên vẹn" if st.intact and st.valid else "BỊ THAY ĐỔI / KHÔNG HỢP LỆ"
                cover = st.coverage.name if hasattr(st, "coverage") else ""
                mod = ""
                if cover and "ENTIRE_FILE" not in cover:
                    mod = " (file có cập nhật thêm sau khi ký)"
                trust = "tin cậy" if st.trusted else "chưa xác minh chuỗi tin cậy (cần chứng thư gốc CA)"
                out.append(f"• Trường '{s.field_name}': {who}\n   Thời gian: {when:%d/%m/%Y %H:%M:%S}"
                           f"\n   Toàn vẹn nội dung: {intact}{mod}\n   Chứng thư: {trust}" if when else
                           f"• Trường '{s.field_name}': {who} - {intact}{mod} - {trust}")
            except Exception as e:
                out.append(f"• Trường '{s.field_name}': lỗi kiểm tra - {e}")
    return out


def has_signatures(doc):
    try:
        return doc.get_sigflags() > 0
    except Exception:
        return False


def make_test_pfx(path, password, name="Nguyen Van Test"):
    """Tạo chứng thư tự ký để thử nghiệm (KHÔNG có giá trị pháp lý)."""
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import pkcs12
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subj = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name),
                      x509.NameAttribute(NameOID.ORGANIZATION_NAME, "PDF Phantom Test"),
                      x509.NameAttribute(NameOID.COUNTRY_NAME, "VN")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(subj).issuer_name(subj).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now)
            .not_valid_after(now + datetime.timedelta(days=365))
            .add_extension(x509.KeyUsage(True, True, False, False, False, False, False, False, False), True)
            .sign(key, hashes.SHA256()))
    data = pkcs12.serialize_key_and_certificates(name.encode(), key, cert, None,
                                                 serialization.BestAvailableEncryption(password.encode()))
    with open(path, "wb") as f:
        f.write(data)
    return path
