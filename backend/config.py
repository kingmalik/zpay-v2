from __future__ import annotations

import os
import tempfile
from pathlib import Path

# Prefer $DATA_DIR; fallback to /tmp (always writable in containers)
DATA_DIR = Path(os.getenv("DATA_DIR") or (Path(tempfile.gettempdir()) / "zpay-data"))
DATA_IN = DATA_DIR / "in"
DATA_OUT = DATA_DIR / "out"

for d in (DATA_IN, DATA_OUT):
    d.mkdir(parents=True, exist_ok=True)

