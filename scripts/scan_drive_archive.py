"""
scan_drive_archive.py — Z-Pay Google Drive Payroll Archive Scanner.

Reads ~/Library/CloudStorage/GoogleDrive-*/My Drive/Wheels of Unity/Payroll/
and reports per-week coverage:
  - FA (Acumen) Excel file present?
  - Maz (EverDriven) PDF present?

Output: JSON report saved to ~/Library/Application Support/zpay-backups/drive-coverage/
and posted to Discord.

Run manually:
  python scripts/scan_drive_archive.py

Run via launchd (installed separately via com.malik.zpay-drive-scan.plist):
  Fires Sunday at 21:00 PT — after mom's W15 run, before Monday morning.

Environment:
  NOTIFY_DISCORD=1   Send result to Discord (default: 1 if Discord env available)
"""
from __future__ import annotations

import glob
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Drive root resolution
# ---------------------------------------------------------------------------

_GOOGLE_DRIVE_BASE = Path.home() / "Library" / "CloudStorage"
_SHORTCUT_SUBPATH = ".shortcut-targets-by-id"
_PAYROLL_SUFFIX = "Wheels of Unity/Payroll"


def _find_payroll_root() -> Optional[Path]:
    """
    Find the Wheels of Unity/Payroll directory under Google Drive CloudStorage.
    Handles both direct mount and shortcut-targets-by-id structure.
    """
    if not _GOOGLE_DRIVE_BASE.exists():
        return None

    for account_dir in _GOOGLE_DRIVE_BASE.iterdir():
        if not account_dir.is_dir() or not account_dir.name.startswith("GoogleDrive-"):
            continue

        # Direct path: My Drive/Wheels of Unity/Payroll
        direct = account_dir / "My Drive" / _PAYROLL_SUFFIX
        if direct.is_dir():
            return direct

        # Shortcut path: .shortcut-targets-by-id/<id>/Wheels of Unity/Payroll
        shortcut_base = account_dir / _SHORTCUT_SUBPATH
        if shortcut_base.is_dir():
            for target_dir in shortcut_base.iterdir():
                candidate = target_dir / _PAYROLL_SUFFIX
                if candidate.is_dir():
                    return candidate

    return None


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------

def _week_num(week_dir_name: str) -> int:
    """'Week 14' → 14"""
    parts = week_dir_name.strip().split()
    if len(parts) == 2 and parts[0].lower() == "week":
        try:
            return int(parts[1])
        except ValueError:
            pass
    return -1


def _has_xlsx(week_dir: Path) -> tuple[bool, Optional[str]]:
    files = list(week_dir.glob("*.xlsx"))
    if files:
        return True, files[0].name
    return False, None


def _has_pdf(week_dir: Path) -> tuple[bool, Optional[str]]:
    files = list(week_dir.glob("*.pdf"))
    if files:
        return True, files[0].name
    return False, None


def scan_payroll_archive(payroll_root: Path) -> dict:
    """
    Scan the Payroll directory tree and return a coverage report.

    Expected structure:
      Payroll/
        Acumen/
          2026/
            Week 1/   ← FA Excel file here
            Week 2/
            ...
        Maz/
          2026/
            Week 1/   ← ED PDF here
            Week 2/
            ...

    Returns dict:
      {
        "scanned_at": "2026-05-03T23:00:00Z",
        "payroll_root": "/path/...",
        "weeks": {
          "1": {"fa_present": true, "fa_file": "Prod_SP_...", "maz_present": true, "maz_file": "Cashiering..."},
          ...
        },
        "missing_fa": [2, 5, ...],
        "missing_maz": [3, ...],
        "summary": "W1-W17: 15/17 FA, 16/17 Maz — 2 gaps"
      }
    """
    acumen_base = payroll_root / "Acumen" / "2026"
    maz_base = payroll_root / "Maz" / "2026"

    # Collect all week numbers from both directories
    all_weeks: set[int] = set()
    for base in [acumen_base, maz_base]:
        if base.is_dir():
            for week_dir in base.iterdir():
                n = _week_num(week_dir.name)
                if n > 0:
                    all_weeks.add(n)

    weeks_data: dict[str, dict] = {}
    missing_fa: list[int] = []
    missing_maz: list[int] = []

    for week_num in sorted(all_weeks):
        week_dir_name = f"Week {week_num}"
        fa_dir = acumen_base / week_dir_name
        maz_dir = maz_base / week_dir_name

        fa_present, fa_file = _has_xlsx(fa_dir) if fa_dir.is_dir() else (False, None)
        maz_present, maz_file = _has_pdf(maz_dir) if maz_dir.is_dir() else (False, None)

        if not fa_present:
            missing_fa.append(week_num)
        if not maz_present:
            missing_maz.append(week_num)

        weeks_data[str(week_num)] = {
            "fa_present": fa_present,
            "fa_file": fa_file,
            "maz_present": maz_present,
            "maz_file": maz_file,
        }

    total_weeks = len(all_weeks)
    fa_count = total_weeks - len(missing_fa)
    maz_count = total_weeks - len(missing_maz)
    gap_count = len(missing_fa) + len(missing_maz)
    week_range = f"W{min(all_weeks)}-W{max(all_weeks)}" if all_weeks else "none"

    summary_parts = [f"{week_range}: {fa_count}/{total_weeks} FA, {maz_count}/{total_weeks} Maz"]
    if gap_count == 0:
        summary_parts.append("— all complete")
    else:
        if missing_fa:
            summary_parts.append(f"— FA missing: W{','.join(str(w) for w in missing_fa)}")
        if missing_maz:
            summary_parts.append(f"— Maz missing: W{','.join(str(w) for w in missing_maz)}")

    return {
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "payroll_root": str(payroll_root),
        "weeks": weeks_data,
        "missing_fa": missing_fa,
        "missing_maz": missing_maz,
        "summary": " ".join(summary_parts),
        "total_weeks": total_weeks,
        "fa_present_count": fa_count,
        "maz_present_count": maz_count,
    }


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def _save_report(report: dict) -> Path:
    """Save JSON report to ~/Library/Application Support/zpay-backups/drive-coverage/"""
    out_dir = (
        Path.home() / "Library" / "Application Support"
        / "zpay-backups" / "drive-coverage"
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = out_dir / f"{ts}_drive_coverage.json"
    out_path.write_text(json.dumps(report, indent=2))
    return out_path


def _discord_alert(message: str) -> None:
    try:
        script = Path.home() / ".claude" / "scripts" / "notify_discord.sh"
        if script.exists():
            subprocess.run([str(script), message], timeout=10, capture_output=True)
    except Exception as exc:
        print(f"[scan] Discord alert failed: {exc}", file=sys.stderr)


def _human_report(report: dict) -> str:
    lines = [
        "=== Z-Pay Drive Archive Scan ===",
        f"Scanned: {report['scanned_at']}",
        f"Summary: {report['summary']}",
        "",
    ]
    for week_num_str, data in sorted(report["weeks"].items(), key=lambda x: int(x[0])):
        fa_icon = "OK" if data["fa_present"] else "MISSING"
        maz_icon = "OK" if data["maz_present"] else "MISSING"
        lines.append(
            f"  W{week_num_str:>2}: FA={fa_icon:<7}  Maz={maz_icon}"
        )

    if report["missing_fa"] or report["missing_maz"]:
        lines.append("")
        lines.append("GAPS:")
        if report["missing_fa"]:
            lines.append(f"  FA (Excel) missing: W{', W'.join(str(w) for w in report['missing_fa'])}")
        if report["missing_maz"]:
            lines.append(f"  Maz (PDF) missing: W{', W'.join(str(w) for w in report['missing_maz'])}")
    else:
        lines.append("\nAll weeks have both FA and Maz files.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    print("[scan] Starting Z-Pay Drive Archive scan...")

    payroll_root = _find_payroll_root()
    if payroll_root is None:
        msg = "[scan] ERROR: Could not find Wheels of Unity/Payroll under Google Drive CloudStorage. Is Google Drive app running?"
        print(msg, file=sys.stderr)
        _discord_alert(f"ZPay Drive Scan FAILED: {msg}")
        return 1

    print(f"[scan] Payroll root: {payroll_root}")
    report = scan_payroll_archive(payroll_root)

    # Print human-readable
    human = _human_report(report)
    print(human)

    # Save JSON
    saved_path = _save_report(report)
    print(f"\n[scan] Report saved: {saved_path}")

    # Discord
    notify = os.environ.get("NOTIFY_DISCORD", "1")
    if notify == "1":
        discord_msg = f"ZPay Drive Scan: {report['summary']}"
        if report["missing_fa"] or report["missing_maz"]:
            discord_msg += " — ACTION NEEDED: gaps found"
        _discord_alert(discord_msg)
        print("[scan] Discord notification sent")

    # Exit non-zero if gaps
    if report["missing_fa"] or report["missing_maz"]:
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
