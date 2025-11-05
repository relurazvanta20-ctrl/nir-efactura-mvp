# NIR din e-Factura — MVP

MVP care încarcă un XML de e-Factura (UBL 2.1 / RO_CIUS), afișează header-ul și numărul de linii și pregătește terenul pentru maparea către NIR 14-3-1A.

## Rulare locală
```bash
python -m venv venv
venv\Scripts\activate   # Windows
pip install -r requirements.txt
streamlit run app/ui/streamlit_app.py
```

## Teste
```bash
pytest -q
```

## Structură
- `app/ui/streamlit_app.py` — UI minimal (upload XML, preview).
- `app/parsers/ubl_parser.py` — funcții pentru parsarea facturilor UBL RO_CIUS.
- `app/models/schemas.py` — modele Pydantic pentru InvoiceHeader/InvoiceLine.
- `fixtures/sample_invoice.xml` — exemplu de factură (dummy) pentru test.