# app/exporters/pdf_nir.py
from __future__ import annotations
from typing import Dict, Any, List
from fpdf import FPDF
from datetime import datetime
import os
import math
import re

# ========================== Config & Fonturi ==========================
FONT_DIR    = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "assets", "fonts"))
REGULAR_TTF = os.path.join(FONT_DIR, "DejaVuSans.ttf")
BOLD_TTF    = os.path.join(FONT_DIR, "DejaVuSans-Bold.ttf")
FAMILY      = "DejaVu"

# Margini (mm) pentru A4 landscape
MARGIN_L = 12
MARGIN_R = 12
MARGIN_T = 12
MARGIN_B = 18  # ușor mai mare ca să încapă footerul

# Coloane (mm) pentru A4 landscape (297mm lățime brută)
# [Denumire, UM, Cant., Preț, TVA%, Total (cu TVA)]
COL_WIDTHS = [150, 16, 20, 26, 14, 30]  # total ~256mm în interiorul marginilor
HEADERS    = ["Denumire", "UM", "Cant.", "Preț unitar", "TVA%", "Valoare (cu TVA)"]

# Dimensiuni text
TABLE_FONT_SIZE   = 9
HEADER_FONT_SIZE  = 10
TITLE_FONT_SIZE   = 14
INFO_FONT_SIZE    = 10
LINE_H            = 5.6
HEADER_LINE_H     = 5.6
PAD_X             = 1.6

# ========================== Utilitare ==========================
def coalesce(*vals, default=0.0) -> float:
    for v in vals:
        if v is None:
            continue
        try:
            f = float(v)
            if not math.isnan(f):
                return f
        except Exception:
            continue
    return float(default)

def fmt_float(x: Any, nd=2) -> str:
    try:
        return f"{float(x):.{nd}f}"
    except Exception:
        return f"{0:.{nd}f}"

def tokenize_for_wrap(text: str) -> List[str]:
    if not text:
        return [""]
    # Rupe după spații și delimitatori utili la wrap
    return re.findall(r"[^\s/\-\(\),\.]+|[/\-\(\),\.]", str(text))

def wrap_text_to_width(pdf: FPDF, text: str, width: float) -> List[str]:
    """Împarte textul pe linii care încap în 'width'. Rupe și pe delimitatori; dacă
    un token e prea lung, îl rupe la nivel de caractere."""
    tokens: List[str] = tokenize_for_wrap(text)
    lines: List[str] = []
    cur = ""

    def fits(s: str) -> bool:
        return pdf.get_string_width(s) <= width

    for tok in tokens:
        candidate = tok if not cur else (cur + tok if tok in "/-(),." else cur + " " + tok)
        if fits(candidate):
            cur = candidate
        else:
            if cur:
                lines.append(cur)
                cur = ""
            if not fits(tok.strip()):
                piece = ""
                for ch in tok:
                    if fits(piece + ch):
                        piece += ch
                    else:
                        if piece:
                            lines.append(piece)
                        piece = ch
                cur = piece
            else:
                cur = tok
    if cur or not lines:
        lines.append(cur)
    return [ln.strip() for ln in lines]

# ========================== Clasa PDF ==========================
class NirPDF(FPDF):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.in_table = False
        self.col_w: List[float] = COL_WIDTHS[:]
        self.headers: List[str] = HEADERS[:]

    # ---- Header pagină ----
    def header(self):
        self.set_font(FAMILY, "B", TITLE_FONT_SIZE)
        self.cell(0, 9, "NIR - Nota de intrare recepție", ln=True, align="C")
        self.ln(1)
        if self.in_table:
            self._draw_table_header()

    # ---- Footer pagină ----
    def footer(self):
        # păstrăm doar paginare și moment generare; footer-ul cu comisia îl desenăm din corp
        self.set_y(-10)
        self.set_font(FAMILY, "", 8)
        self.cell(0, 8, f"Pagina {self.page_no()} • Generat la {datetime.now().strftime('%Y-%m-%d %H:%M')}", align="R")

    # ---- Header tabel multi-linie (fără overflow) ----
    def _draw_table_header(self):
        self.set_font(FAMILY, "B", HEADER_FONT_SIZE)
        self.set_fill_color(238, 238, 238)

        wrapped = []
        max_lines = 1
        for w, text in zip(self.col_w, self.headers):
            box_w = max(0.0, w - 2 * PAD_X)
            lines = wrap_text_to_width(self, text, box_w)
            wrapped.append((w, lines, box_w))
            max_lines = max(max_lines, len(lines))

        header_h = max_lines * HEADER_LINE_H
        x_left = self.get_x()
        y_top  = self.get_y()

        # dreptunghiuri (fond + contur)
        x = x_left
        for w, _, _ in wrapped:
            self.set_xy(x, y_top)
            self.cell(w, header_h, "", border=1, fill=True)
            x += w

        # text în interior
        x = x_left
        for col_idx, (w, lines, box_w) in enumerate(wrapped):
            align  = "L" if col_idx == 0 else "C"
            y_text = y_top + (header_h - len(lines) * HEADER_LINE_H) / 2.0
            for i, ln_text in enumerate(lines):
                self.set_xy(x + PAD_X, y_text + i * HEADER_LINE_H)
                self.cell(box_w, HEADER_LINE_H, ln_text, ln=0, align=align)
            x += w

        self.set_xy(x_left, y_top + header_h)

    def ensure_space(self, row_h: float):
        """Dacă rândul nu încape, rupe pagina și redesenează headerul tabelului."""
        # păstrăm o „zonă tampon” de 12 mm ca să nu călcăm peste footerul de o linie
        buffer_zone = 12
        if self.get_y() + row_h > (self.page_break_trigger - buffer_zone):
            self.add_page()  # header() redesenează capul tabelului

# ========================== Desen rând tabel ==========================
def draw_row(pdf: NirPDF, row: Dict[str, Any], line_h: float = LINE_H):
    pdf.set_font(FAMILY, "", TABLE_FONT_SIZE)

    # Extrage câmpuri + derive simple
    name      = str(row.get("name", "") or "")
    unit      = str(row.get("unit", "") or "")
    qty       = coalesce(row.get("qty"))
    price     = coalesce(row.get("price"))
    vat_pct   = coalesce(row.get("vat_pct"), row.get("vat"))
    line_net  = coalesce(row.get("line_net"))
    total     = coalesce(row.get("total"))

    if total == 0.0 and line_net > 0:
        total = round(line_net * (1.0 + vat_pct / 100.0), 2)
    if line_net == 0.0 and qty > 0 and price > 0:
        line_net = round(qty * price, 2)

    unit_txt  = unit
    qty_txt   = fmt_float(qty, 2)
    price_txt = fmt_float(price, 2)
    vat_txt   = fmt_float(vat_pct, 0)
    total_txt = fmt_float(total, 2)

    # Wrap pentru „Denumire”
    name_w   = max(0.0, pdf.col_w[0] - 2 * PAD_X)
    name_ln  = wrap_text_to_width(pdf, name, name_w)
    n_lines  = max(1, len(name_ln))
    row_h    = n_lines * line_h

    # Page-break dacă nu încape rândul (cu buffer pentru footer)
    pdf.ensure_space(row_h)

    # Coordonate
    x0 = pdf.get_x()
    y0 = pdf.get_y()

    # Borduri pentru rând
    x = x0
    for w in pdf.col_w:
        pdf.rect(x, y0, w, row_h)
        x += w

    # Text în celule
    # 1) Denumire multi-linie
    for i, ln in enumerate(name_ln):
        pdf.set_xy(x0 + PAD_X, y0 + i * line_h)
        pdf.cell(name_w, line_h, ln, ln=0, align="L")

    # 2) Restul (o linie, centrat vertical)
    def write_cell(x_left: float, w: float, text: str, align="R"):
        y_text = y0 + (row_h - line_h) / 2.0
        pdf.set_xy(x_left, y_text)
        pdf.cell(w, line_h, text, ln=0, align=align)

    x = x0 + pdf.col_w[0]
    write_cell(x,                pdf.col_w[1], unit_txt,  align="C"); x += pdf.col_w[1]
    write_cell(x,                pdf.col_w[2], qty_txt,   align="R"); x += pdf.col_w[2]
    write_cell(x,                pdf.col_w[3], price_txt, align="R"); x += pdf.col_w[3]
    write_cell(x,                pdf.col_w[4], vat_txt,   align="C"); x += pdf.col_w[4]
    write_cell(x,                pdf.col_w[5], total_txt, align="R")

    pdf.set_xy(x0, y0 + row_h)

# ========================== Footer pe o singură linie ==========================
def draw_footer_single_line(pdf: NirPDF, inv_date: str):
    """
    Footer pe o singură linie — tot textul uniform, fără bold, fără diferențe de font.
    Cu spațiere proporțională pentru a nu se suprapune.
    """
    y = pdf.h - pdf.b_margin - 8
    pdf.set_y(y)

    # poziție inițială ușor spre dreapta pentru aerisire
    x = pdf.l_margin + 12
    fs = 10  # font uniform

    pdf.set_font(FAMILY, "", fs)

    # segmente ordonate și lățimi calibrate pentru A4 landscape
    segments = [
        ("Comisia de recepție", 40),
        ("Nume + prenume",      50),
        ("Semnătura",           35),
        ("Data",                20),
        (inv_date or "",        28),
        ("",                    16),  # spațiu gol între blocuri
        ("Primit în gestiune",  46),
        ("Semnătura",           35),
    ]

    for text, w in segments:
        pdf.set_xy(x, y)
        pdf.cell(w, 6, text, ln=0, align="L")
        x += w

# ========================== Generator principal ==========================
def generate_pdf(nir_data: Dict[str, Any]) -> bytes:
    """
    Așteaptă dict:
    {
      "invoice_id": str,
      "invoice_date": str,
      "supplier": { "name":..., "cui":..., "address":... },
      "buyer":    { "name":..., "cui":..., "address":... },
      "items": [
         { "name":..., "unit":..., "qty":..., "price":..., "vat_pct"/"vat":..., "line_net":..., "total":... },
      ],
      "totals": { "subtotal":..., "vat":..., "grand_total":... }
    }
    """
    # 1) Inițializare PDF în LANDSCAPE A4
    pdf = NirPDF(orientation="L", unit="mm", format="A4")
    pdf.set_margins(MARGIN_L, MARGIN_T, MARGIN_R)
    pdf.set_auto_page_break(auto=True, margin=MARGIN_B)

    # 2) Fonturi Unicode
    if os.path.isfile(REGULAR_TTF) and os.path.isfile(BOLD_TTF):
        pdf.add_font(FAMILY, "", REGULAR_TTF, uni=True)
        pdf.add_font(FAMILY, "B", BOLD_TTF,    uni=True)
    else:
        raise RuntimeError("Lipsesc fonturile DejaVuSans.ttf / DejaVuSans-Bold.ttf în app/assets/fonts/.")

    pdf.add_page()

    # 3) Header informații factură
    inv_id   = str(nir_data.get("invoice_id", "N/A"))
    inv_date = str(nir_data.get("invoice_date", "N/A"))
    supplier = nir_data.get("supplier", {}) or {}
    buyer    = nir_data.get("buyer", {}) or {}
    items    = nir_data.get("items", []) or []

    pdf.set_font(FAMILY, "", INFO_FONT_SIZE)
    pdf.cell(0, 7, f"Factura: {inv_id}   |   Data: {inv_date}", ln=True)

    pdf.ln(1)
    pdf.set_font(FAMILY, "B", INFO_FONT_SIZE + 1)
    pdf.cell(140, 7, "Furnizor", ln=0)
    pdf.cell(140, 7, "Cumpărător", ln=1)

    pdf.set_font(FAMILY, "", INFO_FONT_SIZE)
    s_text = f"{supplier.get('name','-')}\nCUI: {supplier.get('cui','-')}\n{supplier.get('address','-')}"
    b_text = f"{buyer.get('name','-')}\nCUI: {buyer.get('cui','-')}\n{buyer.get('address','-')}"
    y_before = pdf.get_y()
    pdf.multi_cell(140, 6, s_text, border=1)
    pdf.set_xy(MARGIN_L + 140, y_before)
    pdf.multi_cell(0, 6, b_text, border=1)

    pdf.ln(2)
    pdf.set_font(FAMILY, "", INFO_FONT_SIZE)
    pdf.cell(0, 6, f"Nr. poziții: {len(items)}", ln=True)
    pdf.ln(1)

    # 4) Tabel produse
    pdf.in_table = True
    pdf._draw_table_header()

    pdf.set_font(FAMILY, "", TABLE_FONT_SIZE)
    for it in items:
        draw_row(pdf, it, line_h=LINE_H)

    pdf.in_table = False

    # 5) Totaluri (fallback defensiv dacă lipsesc)
    totals   = nir_data.get("totals", {}) or {}
    subtotal = coalesce(totals.get("subtotal"))
    vat_sum  = coalesce(totals.get("vat"))
    grand    = coalesce(totals.get("grand_total"))

    if subtotal == 0.0 or vat_sum == 0.0 or grand == 0.0:
        s_net = s_vat = s_gross = 0.0
        for it in items:
            ln_net = coalesce(it.get("line_net"), it.get("qty", 0) * it.get("price", 0))
            rate   = coalesce(it.get("vat_pct"), it.get("vat"))
            gross  = coalesce(it.get("total"))
            if gross == 0.0:
                gross = ln_net * (1.0 + rate / 100.0) if ln_net > 0 else 0.0
            s_net   += ln_net
            s_vat   += ln_net * (rate / 100.0)
            s_gross += gross
        if subtotal == 0.0: subtotal = round(s_net, 2)
        if vat_sum  == 0.0: vat_sum  = round(s_vat, 2)
        if grand    == 0.0: grand    = round(s_gross, 2)

    pdf.ln(2)
    pdf.set_font(FAMILY, "B", INFO_FONT_SIZE + 1)
    pdf.cell(
        0, 8,
        f"Subtotal: {fmt_float(subtotal)}    |    TVA: {fmt_float(vat_sum)}    |    Total: {fmt_float(grand)}",
        ln=True, align="R"
    )

    # 6) Footer pe o singură linie (fără borduri/linie orizontală)
    draw_footer_single_line(pdf, inv_date)

    # 7) Return bytes
    out = pdf.output(dest="S")
    return bytes(out) if isinstance(out, (bytes, bytearray)) else out.encode("latin1")
