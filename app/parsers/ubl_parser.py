from __future__ import annotations
from typing import Any, Dict, List

# ---------- utilitare ----------
def _get(d: Any, path: str, default=None):
    """
    Navighează într-un dict/list folosind o cale cu puncte.
    Suportă chei UBL cu namespace (cbc:, cac:).
    Dacă întâlnește listă, ia primul element.
    Suportă și .#text / .@attr (cum vine uneori din xmltodict).
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

def _compose_address(party: dict) -> str:
    addr = _get(party, "cac:PostalAddress") or _get(party, "PostalAddress") or {}
    parts = [
        _get(addr, "cbc:StreetName") or _get(addr, "StreetName"),
        _get(addr, "cbc:CityName") or _get(addr, "CityName"),
        _get(addr, "cbc:PostalZone") or _get(addr, "PostalZone"),
        _get(addr, "cac:Country.cbc:IdentificationCode") or _get(addr, "Country.IdentificationCode"),
    ]
    return ", ".join([p for p in parts if p])

# ---------- parser principal ----------
def parse_invoice_minimal(doc: dict) -> Dict[str, Any]:
    """
    Primește dict din xmltodict.parse pentru UBL 2.1/RO_CIUS.
    Fără fallback-uri „inventate”. Doar ce e în XML.
    Returnează:
    {
      id, issue_date, currency,
      supplier: {name, cui, address},
      buyer:    {name, cui, address},
      totals:   {net, vat, gross, payable, calc_net_from_lines, calc_vat_from_lines, tax_subtotals:[...]},
      lines:    [{name, qty, unit, price, line_net, vat_pct}],
      validations: [ {level,msg}, ... ]
    }
    """
    inv = doc.get("Invoice") or doc  # în multe fișiere rădăcina e "Invoice"

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
        # denumire
        name = (
            _get(ln, "cac:Item.cbc:Name") or
            _get(ln, "Item.cbc:Name") or
            _get(ln, "Item.Name") or
            "-"
        )

        # cantitate + UM
        qty = _as_float(
            _get(ln, "cbc:InvoicedQuantity.#text") or
            _get(ln, "cbc:InvoicedQuantity") or
            _get(ln, "InvoicedQuantity.#text") or
            _get(ln, "InvoicedQuantity")
        )
        unit = (
            _get(ln, "cbc:InvoicedQuantity.@unitCode") or
            _get(ln, "InvoicedQuantity.@unitCode") or
            ""
        )

        # preț unitar (ajustat cu BaseQuantity, dacă există și ≠ 1)
        price_amt = _as_float(
            _get(ln, "cac:Price.cbc:PriceAmount.#text") or
            _get(ln, "cac:Price.cbc:PriceAmount") or
            _get(ln, "Price.cbc:PriceAmount") or
            _get(ln, "Price.PriceAmount")
        )
        base_qty = _as_float(
            _get(ln, "cac:Price.cbc:BaseQuantity.#text") or
            _get(ln, "cac:Price.cbc:BaseQuantity") or
            _get(ln, "Price.cbc:BaseQuantity") or
            _get(ln, "Price.BaseQuantity")
        ) or 1.0
        price = round(price_amt / base_qty, 6) if base_qty not in (0, 1) else price_amt

        # valoare linie (din XML; dacă lipsește, doar atunci qty*price)
        line_net = _as_float(
            _get(ln, "cbc:LineExtensionAmount.#text") or
            _get(ln, "cbc:LineExtensionAmount") or
            _get(ln, "LineExtensionAmount")
        )
        if not line_net and qty and price:
            line_net = round(qty * price, 2)

        # TVA% STRICT din XML:
        # 1) Item → ClassifiedTaxCategory → Percent (prioritar, cum e în fișierul Ame)
        # 2) Dacă nu există acolo, încercăm Percent din TaxTotal/TaxSubtotal pe linie (unele UBL-uri pun acolo)
        vat_pct = _as_float(
            _get(ln, "cac:Item.cac:ClassifiedTaxCategory.cbc:Percent") or
            _get(ln, "Item.cac:ClassifiedTaxCategory.cbc:Percent") or
            _get(ln, "Item.ClassifiedTaxCategory.Percent") or
            _get(ln, "cac:TaxTotal.cac:TaxSubtotal.cbc:Percent") or
            _get(ln, "TaxTotal.TaxSubtotal.Percent") or
            None
        ) or 0.0  # rămâne 0.0 dacă nu e prezent în XML

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

    # defalcare TaxSubtotal la nivel de antet (ne ajută la validări / raportare)
    ts = _get(tax_total, "cac:TaxSubtotal") or _get(tax_total, "TaxSubtotal") or []
    if isinstance(ts, dict):
        ts = [ts]
    tax_subtotals: List[Dict[str, Any]] = []
    for t in ts:
        tax_subtotals.append({
            "rate":    _as_float(
                _get(t, "cac:TaxCategory.cbc:Percent") or
                _get(t, "cbc:Percent") or
                _get(t, "Percent")
            ),
            "taxable": _as_float(_get(t, "cbc:TaxableAmount") or _get(t, "TaxableAmount")),
            "tax":     _as_float(_get(t, "cbc:TaxAmount") or _get(t, "TaxAmount")),
        })

    # --- recalcul din linii (strict pe ce avem în linii) ---
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
            "net": net,
            "vat": vat,
            "gross": gross,
            "payable": payable,
            "calc_net_from_lines": calc_net,
            "calc_vat_from_lines": calc_vat,
            "tax_subtotals": tax_subtotals,
        },
        "lines": lines,
        "validations": validations,
    }
