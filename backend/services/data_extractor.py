import re
from datetime import date, datetime

MAZ_RECEIPT_RE = re.compile(
    r"Cashiering\s+Receipt\s*#\s*(?P<receipt>\d+)",
    re.IGNORECASE,
)
MAZ_PERIOD_RE = re.compile(
    r"Cashiering Dates:\s*"
    r"(?P<start>\d{1,2}/\d{1,2}/\d{4})\s*-\s*"
    r"(?P<end>\d{1,2}/\d{1,2}/\d{4})",
    re.IGNORECASE,
)
def parse_maz_period(pdf_text: str) -> tuple[date, date]:
    m = MAZ_PERIOD_RE.search(pdf_text)
    if not m:
        raise ValueError("Could not find 'Cashiering Dates' period in MAZ PDF text")

    start = datetime.strptime(m.group("start"), "%m/%d/%Y").date()
    end   = datetime.strptime(m.group("end"), "%m/%d/%Y").date()
    return start, end

def parse_maz_receipt_number(text: str) -> str:
    m = MAZ_RECEIPT_RE.search(text)
    if not m:
        raise ValueError("Could not find Cashiering Receipt number in MAZ PDF")
    return m.group("receipt")
