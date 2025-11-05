from pydantic import BaseModel
from typing import List, Optional

class InvoiceLine(BaseModel):
    name: Optional[str] = None
    qty: Optional[float] = None
    unit: Optional[str] = None
    price: Optional[float] = None

class InvoiceHeader(BaseModel):
    id: Optional[str] = None
    issue_date: Optional[str] = None
    currency: Optional[str] = None
    lines: List[InvoiceLine] = []