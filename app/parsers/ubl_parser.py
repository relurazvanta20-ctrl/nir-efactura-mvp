from typing import Any, Dict, List, Optional

def _get(d: Dict, *keys):
    for k in keys:
        if k in d:
            return d[k]
    return None

def _norm_list(x):
    if x is None:
        return []
    if isinstance(x, list):
        return x
    return [x]

def try_float(x) -> Optional[float]:
    if x is None:
        return None
    try:
        return float(x)
    except Exception:
        try:
            return float(str(x))
        except Exception:
            return None

def _line_vat_percent(line: Dict) -> Optional[float]:
    """
    Caută procentul TVA pe linie:
    cac:InvoiceLine -> cac:TaxTotal -> cac:TaxSubtotal -> cbc:Percent
    (în unele fișiere poate lipsi sau fi la nivel agregat)
    """
    tax_total = _get(line, "cac:TaxTotal", "TaxTotal") or {}
    subs = _norm_list(_get(tax_total, "cac:TaxSubtotal", "TaxSubtotal"))
    for s in subs:
        pct = _get(s, "cbc:Percent", "Percent")
        if pct is not None:
            return try_float(pct)
    return None

def parse_invoice_minimal(data: Dict[str, Any]) -> Dict[str, Any]:
    invoice = data.get("Invoice", {})
    # Header
    inv_id = _get(invoice, "cbc:ID", "ID")
    issue_date = _get(invoice, "cbc:IssueDate", "IssueDate")
    currency = _get(invoice, "cbc:DocumentCurrencyCode", "DocumentCurrencyCode")

    # Linii
    lines_raw = _get(invoice, "cac:InvoiceLine", "InvoiceLine")
    lines_raw = _norm_list(lines_raw)

    parsed_lines: List[Dict[str, Any]] = []
    sum_lines_net = 0.0
    sum_vat_calc = 0.0

    for ln in lines_raw:
        item = _get(ln, "cac:Item", "Item") or {}
        name = _get(item, "cbc:Name", "Name")

        qty = _get(ln, "cbc:InvoicedQuantity", "InvoicedQuantity")
        unit = None
        if isinstance(qty, dict):
            unit = qty.get("@unitCode") or qty.get("unitCode")
            qty = qty.get("#text") or qty.get("value") or qty
        qty = try_float(qty)

        price = _get(_get(ln, "cac:Price", "Price") or {}, "cbc:PriceAmount", "PriceAmount")
        price = try_float(price)

        # valoarea liniei fără TVA (LineExtensionAmount) – dacă există
        line_ext = _get(ln, "cbc:LineExtensionAmount", "LineExtensionAmount")
        line_ext = try_float(line_ext)

        # TVA %
        vat_pct = _line_vat_percent(ln)

        # calcule rapide (dacă lipsesc unele câmpuri, aproximăm din qty * price)
        if line_ext is None and (qty is not None and price is not None):
            line_ext = round(qty * price, 2)

        if line_ext is not None:
            sum_lines_net += line_ext

        if vat_pct is not None and line_ext is not None:
            sum_vat_calc += round(line_ext * vat_pct / 100.0, 2)

        parsed_lines.append({
            "name": name,
            "qty": qty,
            "unit": unit,
            "price": price,
            "line_net": line_ext,
            "vat_pct": vat_pct,
        })

    # Totaluri din header (dacă există)
    tax_total = _get(invoice, "cac:TaxTotal", "TaxTotal") or {}
    tax_amount = _get(tax_total, "cbc:TaxAmount", "TaxAmount")
    tax_amount = try_float(tax_amount)

    legal_total = _get(invoice, "cac:LegalMonetaryTotal", "LegalMonetaryTotal") or {}
    total_net = try_float(_get(legal_total, "cbc:TaxExclusiveAmount", "TaxExclusiveAmount"))
    total_gross = try_float(_get(legal_total, "cbc:TaxInclusiveAmount", "TaxInclusiveAmount"))
    payable = try_float(_get(legal_total, "cbc:PayableAmount", "PayableAmount"))

    # Validări simple
    validations = []
    def add_warn(msg): validations.append({"level": "warn", "msg": msg})
    def add_err(msg): validations.append({"level": "error", "msg": msg})

    # 1) suma liniilor ≈ total fără TVA (dacă ambele prezente)
    if total_net is not None and sum_lines_net is not None:
        if abs(sum_lines_net - total_net) > 0.02:  # toleranță 2 bani
            add_err(f"Suma liniilor (calc: {sum_lines_net}) diferă de TaxExclusiveAmount ({total_net}).")

    # 2) TVA calculat din linii ≈ TVA raportat (dacă există ambele)
    if tax_amount is not None and sum_vat_calc is not None and sum_vat_calc > 0:
        if abs(sum_vat_calc - tax_amount) > 0.02:
            add_err(f"TVA calculat din linii (calc: {sum_vat_calc}) diferă de TaxAmount ({tax_amount}).")

    # 3) total brut ≈ net + TVA
    if total_net is not None and tax_amount is not None and total_gross is not None:
        if abs(total_net + tax_amount - total_gross) > 0.02:
            add_err(f"TaxInclusiveAmount ({total_gross}) diferă de net+TVA ({total_net + tax_amount}).")

    return {
        "id": inv_id,
        "issue_date": issue_date,
        "currency": currency,
        "lines": parsed_lines,
        "totals": {
            "net": total_net,
            "vat": tax_amount,
            "gross": total_gross,
            "payable": payable,
            "calc_net_from_lines": round(sum_lines_net, 2),
            "calc_vat_from_lines": round(sum_vat_calc, 2),
        },
        "validations": validations,
    }
