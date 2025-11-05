import sys, os
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import streamlit as st
import xmltodict
import pandas as pd
from io import BytesIO
from app.parsers.ubl_parser import parse_invoice_minimal

# -------------------------------------------------------
st.set_page_config(page_title="NIR din e-Factura — MVP", layout="centered", page_icon="📄")
st.title("NIR din e-Factura — MVP")
st.caption("Upload XML e-Factura (UBL 2.1 / RO_CIUS) → header, totaluri, linii și mini NIR")

uploaded = st.file_uploader("Încarcă fișierul XML e-Factura", type=["xml"])

if uploaded is not None:
    try:
        # === 1. Parse XML ===
        data = xmltodict.parse(uploaded.read())
        inv = parse_invoice_minimal(data)

        # === 2. Header ===
        st.subheader("Header")
        st.write({
            "ID": inv.get("id"),
            "IssueDate": inv.get("issue_date"),
            "Currency": inv.get("currency"),
            "LineCount": len(inv.get("lines", [])),
        })

        # === 3. Totaluri ===
        totals = inv.get("totals", {}) or {}
        st.subheader("Totaluri")
        st.write({
            "TaxExclusiveAmount (din XML)": totals.get("net"),
            "TaxAmount (din XML)": totals.get("vat"),
            "TaxInclusiveAmount (din XML)": totals.get("gross"),
            "PayableAmount (din XML)": totals.get("payable"),
            "Net calculat din linii": totals.get("calc_net_from_lines"),
            "TVA calculat din linii": totals.get("calc_vat_from_lines"),
        })

        # === 4. Primele 5 linii (preview) ===
        if inv.get("lines"):
            st.subheader("Primele 5 linii")
            for i, line in enumerate(inv["lines"][:5], start=1):
                st.write({
                    "index": i,
                    "name": line.get("name"),
                    "qty": line.get("qty"),
                    "unit": line.get("unit"),
                    "price": line.get("price"),
                    "line_net": line.get("line_net"),
                    "vat_pct": line.get("vat_pct"),
                })

        # === 5. MINI NIR (tabel) ===
        st.subheader("Mini NIR")

        rows = []
        for line in inv.get("lines", []):
            qty = float(line.get("qty") or 0)
            price = float(line.get("price") or 0)
            line_net = float(line.get("line_net") or (qty * price))
            vat_pct = float(line.get("vat_pct") or 0)
            vat_val = round(line_net * vat_pct / 100.0, 2)
            total = round(line_net + vat_val, 2)
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

        # totaluri tabel
        sum_net = round(df_nir["Valoare netă"].sum(), 2) if not df_nir.empty else 0.0
        sum_vat = round(df_nir["TVA (lei)"].sum(), 2) if not df_nir.empty else 0.0
        sum_total = round(df_nir["Total (lei)"].sum(), 2) if not df_nir.empty else 0.0

        c1, c2, c3 = st.columns(3)
        c1.metric("Total net", f"{sum_net:,.2f} RON")
        c2.metric("TVA total", f"{sum_vat:,.2f} RON")
        c3.metric("Total cu TVA", f"{sum_total:,.2f} RON")

        # === 6. Export CSV ===
        csv_bytes = df_nir.to_csv(index=False).encode("utf-8-sig")
        st.download_button("Descarcă tabel (CSV)", data=csv_bytes, file_name="nir.csv", mime="text/csv")

        # === 7. Export Excel (XLSX) cu antet NIR și freeze panes ===
        excel_buffer = BytesIO()
        with pd.ExcelWriter(excel_buffer, engine="xlsxwriter") as writer:
            start_row = 5  # lăsăm loc pentru antet
            # scriem tabelul (pandas scrie header pe start_row)
            df_nir.to_excel(writer, index=False, sheet_name="NIR", startrow=start_row)

            wb  = writer.book
            ws  = writer.sheets["NIR"]

            # formate
            fmt_title = wb.add_format({"bold": True, "font_size": 14})
            fmt_lbl   = wb.add_format({"bold": True})
            fmt_num   = wb.add_format({"num_format": "#,##0.00"})
            fmt_head  = wb.add_format({"bold": True, "bg_color": "#EEEEEE", "border": 1})
            fmt_cell  = wb.add_format({"border": 1})

            # antet sus
            ws.write(0, 0, "NIR generat din e-Factura", fmt_title)
            ws.write(2, 0, "Număr factură:", fmt_lbl); ws.write(2, 1, inv.get("id", ""))
            ws.write(3, 0, "Dată factură:",  fmt_lbl); ws.write(3, 1, inv.get("issue_date", ""))
            ws.write(4, 0, "Monedă:",        fmt_lbl); ws.write(4, 1, inv.get("currency", ""))

            # refacem headerul tabelului cu format
            for col_idx, col_name in enumerate(df_nir.columns):
                ws.write(start_row, col_idx, col_name, fmt_head)

            # formatare coloane
            for col in [2, 3, 4, 6, 7]:  # Cant., Preț, Valoare, TVA (lei), Total (lei)
                ws.set_column(col, col, 14, fmt_num)
            ws.set_column(0, 0, 40, fmt_cell)  # Denumire
            ws.set_column(1, 1, 10, fmt_cell)  # U.M.

            # borduri pentru toate celulele din body
            nrows, ncols = df_nir.shape
            for r in range(start_row + 1, start_row + 1 + nrows):
                for c in range(0, ncols):
                    ws.write(r, c, df_nir.iloc[r - (start_row + 1), c], fmt_cell)

            # îngheață sub header
            ws.freeze_panes(start_row + 1, 0)

        excel_bytes = excel_buffer.getvalue()
        st.download_button(
            "Descarcă NIR (Excel)",
            data=excel_bytes,
            file_name="nir.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        # === 8. Validări ===
        probs = inv.get("validations", [])
        if probs:
            has_err = any(p["level"] == "error" for p in probs)
            (st.error if has_err else st.warning)("Au fost detectate probleme la verificări.")
            for p in probs:
                if p["level"] == "error":
                    st.error(f"• {p['msg']}")
                else:
                    st.warning(f"• {p['msg']}")
        else:
            st.success("Validări OK (în limitele toleranței).")

    except Exception as e:
        st.error(f"Eroare la parsare XML: {e}")

else:
    st.info("Încarcă un fișier XML pentru a vedea preview.")
