import re
import xmltodict
from app.parsers.ubl_parser import parse_invoice_minimal

def test_parse_invoice_minimal_sample():
    with open("fixtures/sample_invoice.xml", "rb") as f:
        data = xmltodict.parse(f.read())

    inv = parse_invoice_minimal(data)

    assert isinstance(inv.get("id"), str)
    assert inv["id"] is not None

    # dacă există ID, să fie format "safe" (litere/cifre și - _ / .)
    if inv["id"].strip():
        assert re.match(r"^[A-Za-z0-9][A-Za-z0-9\-\_\/\.]*$", inv["id"])
