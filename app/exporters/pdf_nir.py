from __future__ import annotations
from typing import Dict, Any, List
from fpdf import FPDF
from datetime import datetime
from io import BytesIO
import os

# === setări font Unicode ===
# pune în app/assets/fonts/ fișierele: DejaVuSans.ttf și DejaVuSans-Bold.ttf
FONT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "assets", "fonts"))
REGULAR_TTF = os.path.join(FONT_DIR, "DejaVuSans.ttf")
BOLD_TTF    = os.path.join(FONT_DIR, "DejaVuSans-Bold.ttf")
FAMILY = "DejaVu"  # numele familiei înregistrate

class NirPDF(FPDF):
    def header(self):
        self.set_font(FAMILY, "B", 14)
        self.cell(0, 10, "NIR - Nota de intrare recepție", ln=True, align="C")
        self.ln(2)

    def footer(self):
        self.set_y(-15)
        self.set_font(FAMILY, "", 8)
        self.cell(0, 10, f"Generat la {datetime.now().strftime('%Y-%m-%d %H:%M')}", align="R")

def _cell(pdf, w, txt, style=""):
    pdf.set_font(FAMILY, style, 10)  # folosim mereu fontul Unicode
    pdf.cell(w, 8, str(txt), border=1)

def generate_pdf(nir_data: Dict[str, Any]) -> bytes:
    pdf = NirPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)

    # 1) Înregistrează fonturile Unicode ÎNAINTE de primul add_page,
    #    altfel header-ul (care se desenează la add_page) nu are fontul disponibil.
    if os.path.isfile(REGULAR_TTF) and os.path.isfile(BOLD_TTF):
        pdf.add_font(FAMILY, "", REGULAR_TTF, uni=True)
        pdf.add_font(FAMILY, "B", BOLD_TTF, uni=True)
    else:
        raise RuntimeError(
            "Lipsesc fișierele de font în app/assets/fonts/ "
            "(DejaVuSans.ttf și DejaVuSans-Bold.ttf)."
        )

    # 2) Abia acum pagina:
    pdf.add_page()

    inv_id = str(nir_data.get("invoice_id", "N/A"))
    inv_date = str(nir_data.get("invoice_date", "N/A"))

    pdf.set_font(FAMILY, "", 11)
    pdf.cell(0, 7, f"Factura: {inv_id}   |   Data: {inv_date}", ln=True)


    # înregistrăm fonturile Unicode (o singură dată per document)
    if os.path.isfile(REGULAR_TTF) and os.path.isfile(BOLD_TTF):
        pdf.add_font(FAMILY, "", REGULAR_TTF, uni=True)
        pdf.add_font(FAMILY, "B", BOLD_TTF, uni=True)
    else:
        # fallback: dacă lipsesc fonturile, totul va eșua pe diacritice
        raise RuntimeError("Lipsesc fișierele de font Unicode în app/assets/fonts/. Adaugă DejaVuSans.ttf și DejaVuSans-Bold.ttf")

    inv_id = str(nir_data.get("invoice_id", "N/A"))
    inv_date = str(nir_data.get("invoice_date", "N/A"))

    pdf.set_font(FAMILY, "", 11)
    pdf.cell(0, 7, f"Factura: {inv_id}   |   Data: {inv_date}", ln=True)

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

    col_w = [70, 20, 20, 25, 20, 35]
    headers = ["Denumire", "Cant.", "UM", "Preț unitar", "TVA%", "Valoare (cu TVA)"]
    pdf.set_font(FAMILY, "B", 10)
    for w, h in zip(col_w, headers):
        _cell(pdf, w, h)
    pdf.ln(8)

    items: List[dict] = nir_data.get("items", []) or []
    pdf.set_font(FAMILY, "", 10)
    for it in items:
        _cell(pdf, col_w[0], it.get("name", ""))
        _cell(pdf, col_w[1], it.get("qty", ""))
        _cell(pdf, col_w[2], it.get("unit", ""))
        _cell(pdf, col_w[3], f"{float(it.get('price', 0) or 0):.2f}")
        _cell(pdf, col_w[4], f"{float(it.get('vat', 0) or 0):.0f}")
        _cell(pdf, col_w[5], f"{float(it.get('total', 0) or 0):.2f}")
        pdf.ln(8)

    totals = nir_data.get("totals", {}) or {}
    pdf.ln(2)
    pdf.set_font(FAMILY, "B", 11)
    pdf.cell(0, 8,
             f"Subtotal: {float(totals.get('subtotal', 0)):.2f}   |   "
             f"TVA: {float(totals.get('vat', 0)):.2f}   |   "
             f"Total: {float(totals.get('grand_total', 0)):.2f}",
             ln=True, align="R")

    out = BytesIO()
    out.write(pdf.output(dest="S").encode("latin1"))
    return out.getvalue()
