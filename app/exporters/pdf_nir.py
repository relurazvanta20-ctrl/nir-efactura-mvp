from __future__ import annotations
from typing import Dict, Any, List
from fpdf import FPDF
from datetime import datetime
import os

# === Fonturi Unicode (DejaVu) ===
# Asigură-te că ai aceste fișiere în repo:
# app/assets/fonts/DejaVuSans.ttf
# app/assets/fonts/DejaVuSans-Bold.ttf
FONT_DIR   = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "assets", "fonts"))
REGULAR_TTF = os.path.join(FONT_DIR, "DejaVuSans.ttf")
BOLD_TTF    = os.path.join(FONT_DIR, "DejaVuSans-Bold.ttf")
FAMILY      = "DejaVu"

class NirPDF(FPDF):
    def header(self):
        # ATENȚIE: fonturile sunt deja înregistrate în generate_pdf() înainte de add_page()
        self.set_font(FAMILY, "B", 14)
        self.cell(0, 10, "NIR - Nota de intrare recepție", ln=True, align="C")
        self.ln(2)

    def footer(self):
        self.set_y(-15)
        self.set_font(FAMILY, "", 8)
        self.cell(0, 10, f"Generat la {datetime.now().strftime('%Y-%m-%d %H:%M')}", align="R")

def _cell(pdf: FPDF, w: float, txt: str, style: str = "") -> None:
    pdf.set_font(FAMILY, style, 10)
    pdf.cell(w, 8, str(txt), border=1)

def generate_pdf(nir_data: Dict[str, Any]) -> bytes:
    pdf = NirPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)

    # 1) Înregistrăm fonturile Unicode ÎNAINTE de add_page (pt. diacritice și header)
    if os.path.isfile(REGULAR_TTF) and os.path.isfile(BOLD_TTF):
        pdf.add_font(FAMILY, "", REGULAR_TTF, uni=True)
        pdf.add_font(FAMILY, "B", BOLD_TTF,    uni=True)
    else:
        raise RuntimeError(
            "Lipsesc fonturile Unicode (DejaVuSans.ttf / DejaVuSans-Bold.ttf) în app/assets/fonts/."
        )

    # 2) Pagină + antet
    pdf.add_page()

    inv_id   = str(nir_data.get("invoice_id", "N/A"))
    inv_date = str(nir_data.get("invoice_date", "N/A"))

    pdf.set_font(FAMILY, "", 11)
    pdf.cell(0, 7, f"Factura: {inv_id}   |   Data: {inv_date}", ln=True)

    # Nr. poziții (ca în Excel)
    items = nir_data.get("items", []) or []
    pdf.set_font(FAMILY, "", 10)
    pdf.cell(0, 6, f"Nr. poziții: {len(items)}", ln=True)
    pdf.ln(1)

    # 3) Furnizor / Cumpărător
    s = nir_data.get("supplier", {}) or {}
    b = nir_data.get("buyer", {}) or {}
    pdf.set_font(FAMILY, "B", 11)
    pdf.cell(95, 7, "Furnizor", ln=0)
    pdf.cell(95, 7, "Cumpărător", ln=1)

    pdf.set_font(FAMILY, "", 10)
    pdf.multi_cell(95, 6, f"{s.get('name','-')}\nCUI: {s.get('cui','-')}\n{s.get('address','-')}", border=1)
    x = pdf.get_x(); y = pdf.get_y()
    pdf.set_xy(105, y - 18)
    pdf.multi_cell(95, 6, f"{b.get('name','-')}\nCUI: {b.get('cui','-')}\n{b.get('address','-')}", border=1)
    pdf.ln(2)

    # 4) Tabel produse
    col_w   = [70, 20, 20, 25, 20, 35]  # Denumire, Cant., UM, Preț, TVA%, Total cu TVA
    headers = ["Denumire", "Cant.", "UM", "Preț unitar", "TVA%", "Valoare (cu TVA)"]
    pdf.set_font(FAMILY, "B", 10)
    for w, h in zip(col_w, headers):
        _cell(pdf, w, h)
    pdf.ln(8)

    # Linii cu fallback-uri robuste (nu inventăm valori: derivăm din cele existente)
    pdf.set_font(FAMILY, "", 10)
    for it in items:
        name     = it.get("name", "")
        qty      = float(it.get("qty", 0) or 0)
        unit     = it.get("unit", "")
        price    = float(it.get("price", 0) or 0)
        vat      = float(it.get("vat", 0) or 0)
        total    = float(it.get("total", 0) or 0)
        line_net = float(it.get("line_net", 0) or 0)

        # Fallback-uri logice
        if line_net == 0 and qty > 0 and price > 0:
            line_net = round(qty * price, 2)
        if qty == 0 and line_net > 0 and price > 0:
            qty = round(line_net / price, 6)
        if total == 0 and line_net > 0:
            total = round(line_net * (1 + vat / 100.0), 2)

        _cell(pdf, col_w[0], name)
        _cell(pdf, col_w[1], f"{qty:g}")
        _cell(pdf, col_w[2], unit)
        _cell(pdf, col_w[3], f"{price:.2f}")
        _cell(pdf, col_w[4], f"{vat:.0f}")
        _cell(pdf, col_w[5], f"{total:.2f}")
        pdf.ln(8)

    # 5) Totaluri
    totals = nir_data.get("totals", {}) or {}
    pdf.ln(2)
    pdf.set_font(FAMILY, "B", 11)
    pdf.cell(
        0, 8,
        f"Subtotal: {float(totals.get('subtotal', 0)):.2f}   |   "
        f"TVA: {float(totals.get('vat', 0)):.2f}   |   "
        f"Total: {float(totals.get('grand_total', 0)):.2f}",
        ln=True, align="R"
    )

    # 6) Returnăm bytes compatibil cu toate versiunile fpdf2
    out = pdf.output(dest="S")
    pdf_bytes = bytes(out) if isinstance(out, (bytearray, bytes)) else out.encode("latin1")
    return pdf_bytes
