from app.parsers.ubl_parser import parse_invoice_minimal
import xmltodict

def test_parse_invoice_minimal_sample():
    with open("fixtures/sample_invoice.xml", "rb") as f:
        data = xmltodict.parse(f.read())
    inv = parse_invoice_minimal(data)
    assert inv.get("id") == "INV-12345"
    assert inv.get("currency") == "RON"
    assert len(inv.get("lines", [])) == 2