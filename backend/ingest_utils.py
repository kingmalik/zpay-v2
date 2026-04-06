# backend/ingest_utils.py
import re
from pathlib import Path
import yaml

# Base directory of the backend package (where ingest_utils.py lives)
BASE_DIR = Path(__file__).resolve().parent

# Directory that holds your per-source YAML files
SOURCE_CFG_DIR = BASE_DIR / "config" / "source"

DATE_LIKE = re.compile(r"^\s*\d{1,2}/\d{1,2}/\d{2,4}(\b| )", re.I)

def load_source_cfg(source_name: str) -> dict:
    """
    Load YAML configuration for a given source (e.g. 'acumen', 'acl').

    Looks for:
        backend/config/source/<source_name>.yml
    """
    cfg_path = SOURCE_CFG_DIR / f"{source_name}.yml"

    if not cfg_path.exists():
        raise FileNotFoundError(f"Config file not found for source '{source_name}': {cfg_path}")

    with cfg_path.open("r") as f:
        data = yaml.safe_load(f) or {}

    if not isinstance(data, dict):
        raise ValueError(f"Config for source '{source_name}' must be a mapping/dict, got: {type(data)}")

    return data


# (Optional) if you ever had the old name:
def load_source_config(source_name: str) -> dict:
    """Backward-compatible alias."""
    return load_source_cfg(source_name)
    
def is_junk_person_name(name: str | None) -> bool:
    if not name:
        return False  # let DB trigger derive or error
    n = name.strip()
    if not n:
        return True
    up = n.upper()
    if up in {"SUBTOTAL", "UNKNOWN"}:
        return True
    if DATE_LIKE.match(n):
        return True
    return False

