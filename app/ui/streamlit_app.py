# app/ui/streamlit_app.py

import sys, os, re
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import streamlit as st
import xmltodict
import pandas as pd
from io import BytesIO

from app.parsers.ubl_parser import parse_invoice_minimal
from app.exporters.pdf_nir import generate_pdf  # necesită DejaVuSans.ttf/Bold în app/assets/fonts/

st.set_page_config(page_title="NIR din e-Factura — MVP", layout="centered", page_icon="📄")
st.title("NIR din e-Factura — MVP")
st.caption("Încarci XML (UBL 2.1 / RO_CIUS) → vezi antet, totaluri, linii → exporți CSV/XLSX/PDF.")

uploaded = st.file_uploader("Încarcă fișierul XML e-Factura", type=["xml"])

if uploaded is None:
    st.info("Încarcă un fișier XML pentru a vedea preview.")
else:
    try:
        # 1) Parse XML → dict
        data = xmltodict.parse(uploaded.read())
        inv = parse_invoice_minimal(data)

        # 2) ID factură „safe” (nu depindem de o valoare fixă)
        raw_id = (inv.get("id") or "").strip()
        if not raw_id:
            safe_id = "FARA-ID"
        elif not re.match(r"^[A-Za-z0-9][A-Za-z0-9\-\_\/\.]*$", raw_id):
            safe_id = f"ID_INVALID_{raw_id[:10]}"
        else:
            safe_id = raw_id

        # 3) Header
        st.subheader("Header")
        st.write({
            "ID": safe_id,
            "IssueDate": inv.get("issue_date"),
            "Currency": inv.get("currency"),
            "LineCount": len(inv.get("lines", [])),
        })

        # 4) Totaluri din XML (și comparativ cu ce calculăm noi)
        totals_xml = inv.get("totals", {}) or {}
        st.subheader("Totaluri din XML")
        st.write({
            "TaxExclusiveAmount": totals_xml.get("net"),
            "TaxAmount": totals_xml.get("vat"),
            "TaxInclusiveAmount": totals_xml.get("gross"),
            "PayableAmount": totals_xml.get("payable"),
        })

        # 5) Mini NIR (completăm inteligent lipsurile)
        st.subheader("Mini NIR")

        rows = []
        xml_net = float(totals_xml.get("net") or 0)
        xml_vat = float(totals_xml.get("vat") or 0)
        approx_vat_pct = (xml_vat / xml_net * 100.0) if (xml_net > 0) else 0.0

        for line in inv.get("lines", []):
            qty      = float(line.get("qty") or 0)
            price    = float(line.get("price") or 0)
            line_net = float(line.get("line_net") or 0)
            vat_pct  = float(line.get("vat_pct") or 0)

            # completăm ce lipsește
            if line_net == 0 and qty > 0 and price > 0:
                line_net = round(qty * price, 2)
            if price == 0 and qty > 0 and line_net > 0:
                price = round(line_net / qty, 6)
            if vat_pct == 0 and approx_vat_pct > 0:
                vat_pct = round(approx_vat_pct, 2)

            vat_val = round(line_net * vat_pct / 100.0, 2)
            total   = round(line_net + vat_val, 2)

            rows.append({
                "Denumire": line.get("name"),
                "U.M.": line.get("unit"),
                "Cant.": qty,
                "Preț unitar": price,
                "Valoare netă": line_net,
                "TVA %": vat_pct,
                "TVA (lei)": vat_val,
                "Total (lei)": total,
            })

        df_nir = pd.DataFrame(rows)
        st.dataframe(df_nir, use_container_width=True)

        # 6) Totaluri (recalcul din tabel)
        sum_net   = round(df_nir["Valoare netă"].sum(), 2) if not df_nir.empty else 0.0
        sum_vat   = round(df_nir["TVA (lei)"].sum(), 2)    if not df_nir.empty else 0.0
        sum_total = round(df_nir["Total (lei)"].sum(), 2)  if not df_nir.empty else 0.0

        c1, c2, c3 = st.columns(3)
        c1.metric("Total net",   f"{sum_net:,.2f} RON")
        c2.metric("TVA total",   f"{sum_vat:,.2f} RON")
        c3.metric("Total cu TVA",f"{sum_total:,.2f} RON")

        # 7) nir_data = o singură sursă pentru toate exporturile
        supplier = inv.get("supplier", {}) or {}
        buyer    = inv.get("buyer", {}) or {}

                # --- items_list pentru exporturi (inclusiv PDF) ---
        items_list = []
        for _, row in df_nir.iterrows():
            qty = float(row["Cant."])
            price = float(row["Preț unitar"])
            line_net = float(row["Valoare netă"])
            vat_pct = float(row["TVA %"])
            total = float(row["Total (lei)"])

            # Fallback-uri sigure (în caz că pe viitor unele coloane vin 0)
            if line_net == 0 and qty > 0 and price > 0:
                line_net = round(qty * price, 2)
            if price == 0 and qty > 0 and line_net > 0:
                price = round(line_net / qty, 6)
            if total == 0 and line_net > 0:
                total = round(line_net * (1 + vat_pct / 100.0), 2)

            items_list.append({
                "name":  str(row["Denumire"]),
                "qty":   float(qty),
                "unit":  str(row["U.M."]),
                "price": float(price),
                "vat":   float(vat_pct),
                "line_net": float(line_net),      # <— important pentru PDF
                "total": float(total),
            })

        nir_data = {
            "invoice_id":   safe_id,
            "invoice_date": str(inv.get("issue_date", "")),
            "supplier": {
                "name":    supplier.get("name", "-"),
                "cui":     supplier.get("cui", "-"),
                "address": supplier.get("address", "-"),
            },
            "buyer": {
                "name":    buyer.get("name", "-"),
                "cui":     buyer.get("cui", "-"),
                "address": buyer.get("address", "-"),
            },
            "items":  items_list,
            "totals": {
                "subtotal":    float(sum_net),
                "vat":         float(sum_vat),
                "grand_total": float(sum_total),
            }
        }

        # 8) Export CSV
        st.download_button(
            "Descarcă tabel (CSV)",
            data=df_nir.to_csv(index=False).encode("utf-8-sig"),
            file_name="nir.csv",
            mime="text/csv"
        )

        # 9) Export Excel (formatat, cu antet)
        excel_buffer = BytesIO()
        with pd.ExcelWriter(excel_buffer, engine="xlsxwriter") as writer:
            start_row = 5
            df_nir.to_excel(writer, index=False, sheet_name="NIR", startrow=start_row)

            wb = writer.book
            ws = writer.sheets["NIR"]

            fmt_title = wb.add_format({"bold": True, "font_size": 14})
            fmt_lbl   = wb.add_format({"bold": True})
            fmt_num   = wb.add_format({"num_format": "#,##0.00"})
            fmt_head  = wb.add_format({"bold": True, "bg_color": "#EEEEEE", "border": 1})
            fmt_cell  = wb.add_format({"border": 1})

            ws.write(0, 0, "NIR generat din e-Factura", fmt_title)
            ws.write(2, 0, "Număr factură:", fmt_lbl); ws.write(2, 1, nir_data["invoice_id"])
            ws.write(3, 0, "Dată factură:",  fmt_lbl); ws.write(3, 1, nir_data["invoice_date"])
            ws.write(4, 0, "Monedă:",        fmt_lbl); ws.write(4, 1, inv.get("currency", ""))

            for col_idx, col_name in enumerate(df_nir.columns):
                ws.write(start_row, col_idx, col_name, fmt_head)

            # coloane numerice
            for col in [2, 3, 4, 6, 7]:
                ws.set_column(col, col, 14, fmt_num)
            # text
            ws.set_column(0, 0, 40, fmt_cell)  # Denumire
            ws.set_column(1, 1, 10, fmt_cell)  # U.M.

            nrows, ncols = df_nir.shape
            for r in range(start_row + 1, start_row + 1 + nrows):
                for c in range(0, ncols):
                    ws.write(r, c, df_nir.iloc[r - (start_row + 1), c], fmt_cell)

            ws.freeze_panes(start_row + 1, 0)

        st.download_button(
            "Descarcă NIR (Excel)",
            data=excel_buffer.getvalue(),
            file_name=f"NIR_{nir_data['invoice_id']}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        # 10) Export PDF (fonturi Unicode setate în app/exporters/pdf_nir.py)
        try:
            pdf_bytes = generate_pdf(nir_data)
            st.download_button(
                label="Descarcă NIR (PDF)",
                data=pdf_bytes,
                file_name=f"NIR_{nir_data['invoice_id']}.pdf",
                mime="application/pdf"
            )
        except Exception as e:
            st.warning(f"PDF indisponibil: {e}")

        # 11) Validări parser
        probs = inv.get("validations", [])
        if probs:
            has_err = any(p.get("level") == "error" for p in probs)
            (st.error if has_err else st.warning)("Au fost detectate probleme la verificări:")
            for p in probs:
                msg = p.get("msg", "")
                if p.get("level") == "error":
                    st.error(f"• {msg}")
                else:
                    st.warning(f"• {msg}")
        else:
            st.success("Validări OK (în limitele toleranței).")

    except Exception as e:
        st.error(f"Eroare la parsare sau procesare: {e}")
