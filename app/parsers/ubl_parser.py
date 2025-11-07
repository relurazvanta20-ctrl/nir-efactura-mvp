from __future__ import annotations
from typing import Any, Dict, List

# --- utilitare simple ---
def _get(d: Any, path: str, default=None):
    """
    Navighează în dict/list după o cale cu puncte.
    Suportă chei cu namespace UBL (cbc:, cac:).
    Dacă întâlnește listă, ia primul element.
    """
    cur = d
    for p in path.split("."):
        if cur is None:
            return default
        if isinstance(cur, list):
            cur = cur[0] if cur else None
        if isinstance(cur, dict):
            cur = cur.get(p)
        else:
            return default
    return default if cur is None else cur

def _as_float(x) -> float:
    try:
        return float(str(x).replace(",", "."))
    except Exception:
        return 0.0

# --- parser principal ---
def parse_invoice_minimal(doc: dict) -> Dict[str, Any]:
    """
    Primește dict din xmltodict.parse pentru un UBL 2.1/RO_CIUS.
    Returnează:
      {
        id, issue_date, currency,
        supplier: {name, cui, address},
        buyer:    {name, cui, address},
        totals:   {net, vat, gross, payable, calc_net_from_lines, calc_vat_from_lines},
        lines:    [{name, qty, unit, price, line_net, vat_pct}],
        validations: [ {level,msg}, ... ]
      }
    """
    inv = doc.get("Invoice") or doc  # în XML-ul tău rădăcina este "Invoice"

    # --- header ---
    inv_id     = _get(inv, "cbc:ID") or _get(inv, "ID") or ""
    issue_date = _get(inv, "cbc:IssueDate") or _get(inv, "IssueDate") or ""
    currency   = _get(inv, "cbc:DocumentCurrencyCode") or _get(inv, "DocumentCurrencyCode") or "RON"

    # --- supplier ---
    sp = _get(inv, "cac:AccountingSupplierParty") or _get(inv, "AccountingSupplierParty") or {}
    sp_party = _get(sp, "cac:Party") or _get(sp, "Party") or {}
    sp_name  = (
        _get(sp_party, "cac:PartyName.cbc:Name") or
        _get(sp_party, "PartyName.cbc:Name") or
        _get(sp_party, "PartyName.Name") or
        "-"
    )
    sp_cui   = (
        _get(sp_party, "cac:PartyTaxScheme.cbc:CompanyID") or
        _get(sp_party, "PartyTaxScheme.cbc:CompanyID") or
        _get(sp_party, "PartyTaxScheme.CompanyID") or
        "-"
    )
    sp_addr  = _compose_address(sp_party)

    # --- buyer ---
    bp = _get(inv, "cac:AccountingCustomerParty") or _get(inv, "AccountingCustomerParty") or {}
    bp_party = _get(bp, "cac:Party") or _get(bp, "Party") or {}
    bp_name  = (
        _get(bp_party, "cac:PartyName.cbc:Name") or
        _get(bp_party, "PartyName.cbc:Name") or
        _get(bp_party, "PartyName.Name") or
        "-"
    )
    bp_cui   = (
        _get(bp_party, "cac:PartyTaxScheme.cbc:CompanyID") or
        _get(bp_party, "PartyTaxScheme.cbc:CompanyID") or
        _get(bp_party, "PartyTaxScheme.CompanyID") or
        "-"
    )
    bp_addr  = _compose_address(bp_party)

    # --- linii ---
    raw_lines = _get(inv, "cac:InvoiceLine") or _get(inv, "InvoiceLine") or []
    if isinstance(raw_lines, dict):
        raw_lines = [raw_lines]

    lines: List[Dict[str, Any]] = []
    for ln in raw_lines:
        # name
        name = (
            _get(ln, "cac:Item.cbc:Name") or
            _get(ln, "Item.cbc:Name") or
            _get(ln, "Item.Name") or
            "-"
        )
        # qty + unit
        qty  = _as_float(_get(ln, "cbc:InvoicedQuantity") or _get(ln, "cbc:InvoicedQuantity.#text") or _get(ln, "InvoicedQuantity.#text") or _get(ln, "InvoicedQuantity"))
        unit = (
            _get(ln, "cbc:InvoicedQuantity.@unitCode") or
            _get(ln, "InvoicedQuantity.@unitCode") or
            ""
        )
        # price
        price = _as_float(
            _get(ln, "cac:Price.cbc:PriceAmount") or
            _get(ln, "cac:Price.cbc:PriceAmount.#text") or
            _get(ln, "Price.cbc:PriceAmount") or
            _get(ln, "Price.PriceAmount")
        )
        # line net (dacă lipsește, qty*price)
        line_net = _as_float(
            _get(ln, "cbc:LineExtensionAmount") or
            _get(ln, "cbc:LineExtensionAmount.#text") or
            _get(ln, "LineExtensionAmount")
        )
        if not line_net and qty and price:
            line_net = round(qty * price, 2)

        # VAT %
        vat_pct = _as_float(
            _get(ln, "cac:TaxTotal.cac:TaxSubtotal.cbc:Percent") or
            _get(ln, "TaxTotal.TaxSubtotal.Percent") or
            0
        )

        lines.append({
            "name": name,
            "qty": qty,
            "unit": unit,
            "price": price,
            "line_net": line_net,
            "vat_pct": vat_pct,
        })

    # --- totaluri din XML ---
    tax_total = _get(inv, "cac:TaxTotal") or _get(inv, "TaxTotal") or {}
    legal_tot = _get(inv, "cac:LegalMonetaryTotal") or _get(inv, "LegalMonetaryTotal") or {}

    net     = _as_float(_get(legal_tot, "cbc:TaxExclusiveAmount") or _get(legal_tot, "TaxExclusiveAmount"))
    gross   = _as_float(_get(legal_tot, "cbc:TaxInclusiveAmount") or _get(legal_tot, "TaxInclusiveAmount"))
    payable = _as_float(_get(legal_tot, "cbc:PayableAmount") or _get(legal_tot, "PayableAmount"))
    vat     = _as_float(_get(tax_total, "cbc:TaxAmount") or _get(tax_total, "TaxAmount"))

    # --- recalcul din linii ---
    calc_net = round(sum(_as_float(l["line_net"]) for l in lines), 2)
    calc_vat = round(sum(_as_float(l["line_net"]) * (_as_float(l["vat_pct"]) / 100.0) for l in lines), 2)

    # --- validări simple ---
    validations = []
    if not inv_id:
        validations.append({"level": "warning", "msg": "Lipsește ID factură."})
    if net and abs(calc_net - net) > 0.05:
        validations.append({"level": "warning", "msg": f"Net din linii ({calc_net}) diferă de Net din XML ({net})."})
    if vat and abs(calc_vat - vat) > 0.05:
        validations.append({"level": "warning", "msg": f"TVA din linii ({calc_vat}) diferă de TVA din XML ({vat})."})

    return {
        "id": inv_id,
        "issue_date": issue_date,
        "currency": currency,
        "supplier": {"name": sp_name, "cui": sp_cui, "address": sp_addr},
        "buyer":    {"name": bp_name, "cui": bp_cui, "address": bp_addr},
        "totals":   {
            "net": net, "vat": vat, "gross": gross, "payable": payable,
            "calc_net_from_lines": calc_net, "calc_vat_from_lines": calc_vat
        },
        "lines": lines,
        "validations": validations,
    }

def _compose_address(party: dict) -> str:
    addr = _get(party, "cac:PostalAddress") or _get(party, "PostalAddress") or {}
    parts = [
        _get(addr, "cbc:StreetName") or _get(addr, "StreetName"),
        _get(addr, "cbc:CityName") or _get(addr, "CityName"),
        _get(addr, "cbc:PostalZone") or _get(addr, "PostalZone"),
        _get(addr, "cac:Country.cbc:IdentificationCode") or _get(addr, "Country.IdentificationCode"),
    ]
    return ", ".join([p for p in parts if p])
