"""Tiện ích dùng chung: đường dẫn, cấu hình, font, biểu tượng, phân tích dải trang."""
import json
import os
import re
import sys
import shutil
import logging

log = logging.getLogger("phantom")


# ----------------------------------------------------------------- đường dẫn
def app_dir():
    """Thư mục chứa chương trình (khi đóng gói exe là thư mục exe)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resource_dir():
    """Thư mục tài nguyên (PyInstaller giải nén vào _MEIPASS)."""
    return getattr(sys, "_MEIPASS", app_dir())


def user_dir():
    """Thư mục dữ liệu người dùng: %APPDATA%/PDFPhantom (giữ nguyên khi cập nhật)."""
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
    d = os.path.join(base, "PDFPhantom")
    os.makedirs(d, exist_ok=True)
    os.makedirs(os.path.join(d, "plugins"), exist_ok=True)
    os.makedirs(os.path.join(d, "stamps"), exist_ok=True)
    return d


def asset(name):
    for base in (resource_dir(), app_dir()):
        p = os.path.join(base, "assets", name)
        if os.path.exists(p):
            return p
    return os.path.join(app_dir(), "assets", name)


# ------------------------------------------------------------------ cấu hình
DEFAULTS = {
    "theme": "light",
    "recent": [],
    "last_dir": "",
    "render_quality": 1.0,
    "claude_api_key": "",
    "claude_model": "claude-sonnet-5-5",
    "tesseract_path": "",
    "ocr_lang": "vie+eng",
    "pkcs11_dll": "",
    "tsa_url": "",
    "signer_name": "",
    "signer_location": "",
    "update_url": "",
    "external_apps": [],          # [{"name":..., "path":...}]
    "default_font": "times",
    "annot_styles": {},
    "page_number": {},
}


class Config(dict):
    def __init__(self):
        super().__init__(DEFAULTS)
        self.path = os.path.join(user_dir(), "config.json")
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                self.update(json.load(f))
        except Exception:
            pass

    def save(self):
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(dict(self), f, ensure_ascii=False, indent=2)
        except Exception as e:
            log.warning("Không lưu được cấu hình: %s", e)

    def add_recent(self, path):
        rec = [p for p in self.get("recent", []) if p != path]
        rec.insert(0, path)
        self["recent"] = rec[:15]
        self["last_dir"] = os.path.dirname(path)
        self.save()


CONFIG = None


def config():
    global CONFIG
    if CONFIG is None:
        CONFIG = Config()
    return CONFIG


# --------------------------------------------------------------------- font
_FONT_CANDIDATES = {
    "times": ["times.ttf", "Times New Roman.ttf", "LiberationSerif-Regular.ttf", "DejaVuSerif.ttf"],
    "times-bold": ["timesbd.ttf", "Times New Roman Bold.ttf", "LiberationSerif-Bold.ttf", "DejaVuSerif-Bold.ttf"],
    "times-italic": ["timesi.ttf", "Times New Roman Italic.ttf", "LiberationSerif-Italic.ttf", "DejaVuSerif-Italic.ttf"],
    "times-bolditalic": ["timesbi.ttf", "LiberationSerif-BoldItalic.ttf", "DejaVuSerif-BoldItalic.ttf"],
    "arial": ["arial.ttf", "Arial.ttf", "LiberationSans-Regular.ttf", "DejaVuSans.ttf"],
    "arial-bold": ["arialbd.ttf", "Arial Bold.ttf", "LiberationSans-Bold.ttf", "DejaVuSans-Bold.ttf"],
    "arial-italic": ["ariali.ttf", "LiberationSans-Italic.ttf", "DejaVuSans-Oblique.ttf"],
    "arial-bolditalic": ["arialbi.ttf", "LiberationSans-BoldItalic.ttf", "DejaVuSans-BoldOblique.ttf"],
    "tahoma": ["tahoma.ttf", "DejaVuSans.ttf"],
    "calibri": ["calibri.ttf", "Carlito-Regular.ttf", "DejaVuSans.ttf"],
}

FONT_LABELS = {"times": "Times New Roman", "arial": "Arial", "tahoma": "Tahoma", "calibri": "Calibri"}


def _font_dirs():
    dirs = []
    win = os.environ.get("WINDIR", r"C:\Windows")
    dirs.append(os.path.join(win, "Fonts"))
    la = os.environ.get("LOCALAPPDATA")
    if la:
        dirs.append(os.path.join(la, "Microsoft", "Windows", "Fonts"))
    dirs += ["/usr/share/fonts/truetype/liberation", "/usr/share/fonts/truetype/dejavu",
             "/usr/share/fonts/truetype/crosextra", "/Library/Fonts", "/System/Library/Fonts"]
    dirs.append(os.path.join(resource_dir(), "assets", "fonts"))
    return dirs


_font_cache = {}


def font_file(family="times", bold=False, italic=False):
    """Trả về đường dẫn file TTF hỗ trợ tiếng Việt, hoặc None."""
    key = family
    if bold and italic:
        key += "-bolditalic"
    elif bold:
        key += "-bold"
    elif italic:
        key += "-italic"
    if key in _font_cache:
        return _font_cache[key]
    names = _FONT_CANDIDATES.get(key) or _FONT_CANDIDATES.get(family) or _FONT_CANDIDATES["arial"]
    found = None
    for d in _font_dirs():
        for n in names:
            p = os.path.join(d, n)
            if os.path.exists(p):
                found = p
                break
        if found:
            break
    if not found and key != family:
        found = font_file(family)
    if not found and family != "arial":
        found = font_file("arial", bold, italic)
    _font_cache[key] = found
    return found


def guess_family(fontname):
    """Đoán họ font gần nhất từ tên font trong PDF."""
    n = (fontname or "").lower()
    bold = "bold" in n or "black" in n or ",b" in n or "-b" == n[-2:]
    italic = "italic" in n or "oblique" in n
    if "times" in n or "serif" in n and "sans" not in n or "roman" in n:
        fam = "times"
    elif "tahoma" in n:
        fam = "tahoma"
    elif "calibri" in n:
        fam = "calibri"
    else:
        fam = "arial" if ("arial" in n or "helv" in n or "sans" in n) else config().get("default_font", "times")
    return fam, bold, italic


# ----------------------------------------------------------------- dải trang
def parse_ranges(text, page_count):
    """'1-3, 5, 8-' -> danh sách nhóm [[0,1,2],[4],[7..n-1]] (0-based)."""
    groups = []
    text = (text or "").replace(";", ",").strip()
    if not text:
        return [list(range(page_count))]
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        m = re.fullmatch(r"(\d*)\s*-\s*(\d*)", part)
        if m:
            a = int(m.group(1)) if m.group(1) else 1
            b = int(m.group(2)) if m.group(2) else page_count
            if a > b:
                rng = list(range(min(a, page_count), max(b, 1) - 1, -1))
            else:
                rng = list(range(max(a, 1), min(b, page_count) + 1))
            g = [p - 1 for p in rng if 1 <= p <= page_count]
        elif part.isdigit():
            p = int(part)
            g = [p - 1] if 1 <= p <= page_count else []
        else:
            raise ValueError(f"Dải trang không hợp lệ: '{part}'")
        if g:
            groups.append(g)
    return groups


def parse_pages(text, page_count):
    out = []
    for g in parse_ranges(text, page_count):
        out += g
    return out


def to_roman(n):
    vals = [(1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"),
            (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]
    if n <= 0:
        return str(n)
    s = ""
    for v, r in vals:
        while n >= v:
            s += r
            n -= v
    return s


def to_letters(n):
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s or "0"


def format_number(n, style):
    if style == "i":
        return to_roman(n).lower()
    if style == "I":
        return to_roman(n)
    if style == "a":
        return to_letters(n).lower()
    if style == "A":
        return to_letters(n)
    if style == "01":
        return f"{n:02d}"
    if style == "001":
        return f"{n:03d}"
    return str(n)


def safe_name(s):
    return re.sub(r'[\\/:*?"<>|]+', "_", s).strip() or "file"


def find_tesseract():
    p = config().get("tesseract_path")
    if p and os.path.exists(p):
        return p
    for c in [os.path.join(app_dir(), "tesseract", "tesseract.exe"),
              r"C:\Program Files\Tesseract-OCR\tesseract.exe",
              r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
              os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Tesseract-OCR", "tesseract.exe")]:
        if c and os.path.exists(c):
            return c
    return shutil.which("tesseract")


def tessdata_dir():
    """Ưu tiên thư mục tessdata đi kèm phần mềm (có vie.traineddata)."""
    for d in [os.path.join(app_dir(), "tessdata"), os.path.join(user_dir(), "tessdata")]:
        if os.path.exists(os.path.join(d, "vie.traineddata")):
            return d
    t = find_tesseract()
    if t:
        d = os.path.join(os.path.dirname(t), "tessdata")
        if os.path.isdir(d):
            return d
    return None


def human_size(n):
    for u in ["B", "KB", "MB", "GB"]:
        if n < 1024:
            return f"{n:.0f} {u}" if u == "B" else f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} TB"
