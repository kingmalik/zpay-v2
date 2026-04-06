import re

def clean_bytes(raw: bytes) -> bytes:
    """
    Pre-clean raw file bytes for more reliable CSV parsing.
    - Remove BOM/NULLs
    - Normalize newlines to LF
    - Replace NBSP with space
    - Normalize fancy quotes
    - Trim trailing spaces before newline
    """
    if not raw:
        return raw
    text = raw.decode("utf-8", errors="replace")
    text = text.replace("\ufeff", "")              # BOM
    text = text.replace("\x00", "")                # NULLs
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u00A0", " ")             # NBSP
    text = text.replace("“", '"').replace("”", '"').replace("’", "'")
    text = re.sub(r"[ \t]+(?=\n)", "", text)       # trailing spaces at EOL
    return text.encode("utf-8", errors="ignore")
