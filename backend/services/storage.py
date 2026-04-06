from __future__ import annotations

import errno
import tempfile
from datetime import datetime
from pathlib import Path
from fastapi import UploadFile

from backend.config import DATA_IN

def save_upload(file: UploadFile) -> Path:
    """Write the upload to DATA_IN; fallback to /tmp if parent is read-only."""
    suffix = Path(file.filename or "upload.pdf").suffix or ".pdf"
    fname = f"{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}{suffix.upper()}"
    dest = DATA_IN / fname
    data = file.file.read()
    try:
        with dest.open("wb") as f:
            f.write(data)
        return dest
    except OSError as e:
        if e.errno == errno.EROFS:
            tmp_in = Path(tempfile.gettempdir()) / "zpay-data" / "in"
            tmp_in.mkdir(parents=True, exist_ok=True)
            dest = tmp_in / fname
            with dest.open("wb") as f:
                f.write(data)
            return dest
        raise
