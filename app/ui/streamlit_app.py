# app/ui/streamlit_app.py
from __future__ import annotations

import io
import re
from typing import Any, Dict, List

import pandas as pd
import streamlit as st
import xmltodict

# parser + exportere
from app.parsers.ubl_parser import parse_invoice_minimal
from app.exporters.pdf_nir import generate_pdf


# =============== helpers UI/format ===============
def s(x: Any) -> str:
    """safe string for UI"""
    return str(x or "").strip()

def filename_safe_id(raw_id: str) -> str:
    """ID sigur pentru nume de fișier (nu afectează afișarea)."""
    cleaned = re.sub(r"[^\w\-.]+", "_", s(raw_id))
    cleaned = cleaned.strip("_")
    return cleaned or "invoice"

def to_nir_df(inv: Dict[str, Any]) -> pd.DataFrame:
    """Construiește DataFrame-ul NIR din payload-ul parserului (fără invenții)."""
    rows = []
    for ln in inv.get("lines", []):
        qty      = float(ln.get("qty") or 0)
        price    = float(ln.get("price") or 0)
        line_net = float(ln.get("line_net") or (qty * price))
        vat_pct  = float(ln.get("vat_pct") or 0)

        vat_lei   = round(line_net * vat_pct / 100.0, 2)
        total_lei = round(line_net + vat_lei, 2)

        rows.append({
            "Denumire": s(ln.get("name")),
            "UM":       s(ln.get("unit")),
            "Cant.":    round(qty, 2),
            "Preț unitar": round(price, 2),
            "Valoare netă": round(line_net, 2),
            "TVA %":    round(vat_pct, 2),
            "TVA (lei)": vat_lei,
            "Valoare (cu TVA)": total_lei,
        })
    df = pd.DataFrame(rows, columns=[
        "Denumire", "UM", "Cant.", "Preț unitar", "Valoare netă",
        "TVA %", "TVA (lei)", "Valoare (cu TVA)"
    ])
    return df


def render_totals(inv: Dict[str, Any]):
    t = inv.get("totals", {}) or {}
    col1, col2, col3, col4 = st.columns([1,1,1,1])
    col1.metric("Subtotal (TaxExclusiveAmount)", f"{t.get('net', 0):,.2f}")
    col2.metric("TVA (TaxAmount)", f"{t.get('vat', 0):,.2f}")
    col3.metric("Total (TaxInclusiveAmount)", f"{t.get('gross', 0):,.2f}")
    col4.metric("De plată (PayableAmount)", f"{t.get('payable', 0):,.2f}")

    # diferențe din linii vs antet
    calc_net = float(t.get("calc_net_from_lines") or 0)
    calc_vat = float(t.get("calc_vat_from_lines") or 0)
    if abs(calc_net - float(t.get("net") or 0)) > 0.05 or abs(calc_vat - float(t.get("vat") or 0)) > 0.05:
        st.warning(
            f"Diferențe între linii și antet: Net linii = {calc_net:.2f}, TVA linii = {calc_vat:.2f}"
        )


def export_xlsx(df: pd.DataFrame, nir_data: Dict[str, Any], invoice_id_file: str):
    """Generează și oferă la descărcare Excel-ul (XLSX)."""
    excel_buffer = io.BytesIO()

    with pd.ExcelWriter(excel_buffer, engine="xlsxwriter") as writer:
        ws_name = "NIR"
        start_row = 6

        df.to_excel(writer, index=False, sheet_name=ws_name, startrow=start_row)
        wb = writer.book
        ws = writer.sheets[ws_name]

        # formate
        fmt_title = wb.add_format({"bold": True, "font_size": 14})
        fmt_lbl   = wb.add_format({"bold": True})
        fmt_head  = wb.add_format({"bold": True, "bg_color": "#EEEEEE", "border": 1})
        fmt_cell  = wb.add_format({"border": 1})
        fmt_num   = wb.add_format({"num_format": "#,##0.00", "border": 1})
        fmt_pct   = wb.add_format({"num_format": "0.00", "border": 1})

        # meta sus
        ws.write(0, 0, "NIR generat din e-Factura", fmt_title)
        ws.write(2, 0, "Număr factură:", fmt_lbl); ws.write(2, 1, s(nir_data.get("invoice_id")))
        ws.write(3, 0, "Dată factură:",  fmt_lbl); ws.write(3, 1, s(nir_data.get("invoice_date")))
        ws.write(4, 0, "Monedă:",        fmt_lbl); ws.write(4, 1, s(inv_payload.get("currency")))

        # reformatăm header-ul
        for c, col in enumerate(df.columns):
            ws.write(start_row, c, col, fmt_head)

        # lățimi coloane
        ws.set_column(0, 0, 60, fmt_cell)  # Denumire
        ws.set_column(1, 1, 8,  fmt_cell)  # UM
        ws.set_column(2, 2, 12, fmt_num)   # Cant.
        ws.set_column(3, 3, 14, fmt_num)   # Preț unitar
        ws.set_column(4, 4, 14, fmt_num)   # Valoare netă
        ws.set_column(5, 5, 8,  fmt_pct)   # TVA %
        ws.set_column(6, 7, 14, fmt_num)   # TVA (lei), Valoare (cu TVA)

        # borduri pe corp (opțional)
        nrows, ncols = df.shape
        for r in range(start_row + 1, start_row + nrows + 1):
            for c in range(ncols):
                v = df.iloc[r - (start_row + 1), c]
                ws.write(r, c, v, fmt_num if isinstance(v, (int, float, float)) else fmt_cell)

        ws.freeze_panes(start_row + 1, 0)

    excel_buffer.seek(0)
    st.download_button(
        "Descarcă NIR (Excel)",
        data=excel_buffer.getvalue(),
        file_name=f"NIR_{invoice_id_file}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key="dl_xlsx",
    )


# =============== UI ===============
st.set_page_config(page_title="NIR e-Factura — MVP", layout="wide")
st.title("NIR e-Factura — MVP")

st.caption("Încarcă XML UBL (e-Factura) → parser → NIR → export PDF / Excel")

uploaded = st.file_uploader("Încarcă fișier XML", type=["xml"])

if uploaded is None:
    st.info("Încarcă un fișier e-Factura (UBL XML) pentru a începe.")
    st.stop()

try:
    # 1) parse XML
    xml_bytes = uploaded.read()
    doc = xmltodict.parse(xml_bytes)
    inv_payload = parse_invoice_minimal(doc)

    # 2) ID: Afișare vs. Nume fișier
    invoice_id_display = s(inv_payload.get("id")) or "N/A"
    invoice_id_file    = filename_safe_id(invoice_id_display)

    # 3) layout info
    info_col1, info_col2, info_col3 = st.columns([1,1,1])
    with info_col1:
        st.subheader("Factura")
        st.write(f"**Număr:** {invoice_id_display}")
        st.write(f"**Data:** {s(inv_payload.get('issue_date'))}")
        st.write(f"**Monedă:** {s(inv_payload.get('currency'))}")

    with info_col2:
        sp = inv_payload.get("supplier") or {}
        st.subheader("Furnizor")
        st.write(s(sp.get("name")) or "-")
        st.write(f"CUI: {s(sp.get('cui')) or '-'}")
        st.write(s(sp.get("address")) or "-")

    with info_col3:
        bp = inv_payload.get("buyer") or {}
        st.subheader("Cumpărător")
        st.write(s(bp.get("name")) or "-")
        st.write(f"CUI: {s(bp.get('cui')) or '-'}")
        st.write(s(bp.get("address")) or "-")

    st.divider()

    # 4) totaluri + validări
    render_totals(inv_payload)
    vlist = inv_payload.get("validations") or []
    if vlist:
        with st.expander("Validări"):
            for v in vlist:
                lvl = s(v.get("level")).lower()
                msg = s(v.get("msg"))
                if lvl == "error":
                    st.error(msg)
                elif lvl == "warning":
                    st.warning(msg)
                else:
                    st.info(msg)

    # 5) tabel NIR
    df_nir = to_nir_df(inv_payload)
    st.subheader("Tabel NIR")
    st.dataframe(df_nir, use_container_width=True, hide_index=True)

    # 6) exporturi
    # pregătim payload-ul pentru PDF (nomenclatorul cheilor este cel așteptat de generate_pdf)
    items_for_pdf: List[Dict[str, Any]] = []
    for _, r in df_nir.iterrows():
        items_for_pdf.append({
            "name": r["Denumire"],
            "unit": r["UM"],
            "qty": float(r["Cant."]),
            "price": float(r["Preț unitar"]),
            "line_net": float(r["Valoare netă"]),
            "vat_pct": float(r["TVA %"]),
            "total": float(r["Valoare (cu TVA)"]),
        })

    totals_for_pdf = {
        "subtotal": float(inv_payload.get("totals", {}).get("net") or df_nir["Valoare netă"].sum()),
        "vat": float(inv_payload.get("totals", {}).get("vat") or df_nir["TVA (lei)"].sum()),
        "grand_total": float(inv_payload.get("totals", {}).get("gross") or df_nir["Valoare (cu TVA)"].sum()),
    }

    nir_data = {
        "invoice_id": invoice_id_display,   # Afișare exact cum e în XML
        "invoice_date": s(inv_payload.get("issue_date")),
        "supplier": inv_payload.get("supplier") or {},
        "buyer":    inv_payload.get("buyer") or {},
        "items":    items_for_pdf,
        "totals":   totals_for_pdf,
    }

    col_pdf, col_xlsx = st.columns([1,1])
    with col_pdf:
        try:
            pdf_bytes = generate_pdf(nir_data)
            st.download_button(
                "Descarcă NIR (PDF)",
                data=pdf_bytes,
                file_name=f"NIR_{invoice_id_file}.pdf",
                mime="application/pdf",
                key="dl_pdf",
            )
        except Exception as e:
            st.error(f"Eroare PDF: {e}")

    with col_xlsx:
        try:
            export_xlsx(df_nir, nir_data, invoice_id_file)
        except Exception as e:
            st.error(f"Eroare Excel: {e}")

except Exception as e:
    st.error(f"Eroare la parsare sau procesare: {e}")
