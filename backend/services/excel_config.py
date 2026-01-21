from pathlib import Path
import yaml

def load_excel_config(cfg_path: str | Path) -> dict:
    cfg_path = Path(cfg_path)

    if not cfg_path.exists():
        raise FileNotFoundError(f"Config file not found: {cfg_path}")

    with cfg_path.open("r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    if not isinstance(cfg, dict):
        raise ValueError(f"Invalid YAML structure in {cfg_path}")

    return cfg