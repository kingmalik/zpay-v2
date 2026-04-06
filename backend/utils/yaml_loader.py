from pathlib import Path
import yaml

CONFIG_DIR = Path(__file__).parent / "config" / "source"

def load_source_cfg(name: str) -> dict:
    # name = "acumen" or "acl"
    cfg_path = CONFIG_DIR / f"{name}.yml"
    with cfg_path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)  # safe

