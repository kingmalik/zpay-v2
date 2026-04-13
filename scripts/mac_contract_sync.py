#!/usr/bin/env python3
"""
MAZ Services — Contract Sync Agent
Runs silently on mom's Mac. Polls Z-Pay every 15 minutes for newly signed
contracts and downloads them to ~/Documents/MAZ Contracts/.

Setup:
  1. python3 mac_contract_sync.py --install   (installs launchd, starts agent)
  2. python3 mac_contract_sync.py --uninstall (removes launchd agent)
  3. python3 mac_contract_sync.py --run-once  (manual one-time sync)

Requires:
  ZPAY_URL     — Z-Pay backend URL (e.g. https://zpay-backend.railway.app)
  ZPAY_SESSION — Session cookie value from a logged-in Z-Pay session
"""

import json
import os
import sys
import subprocess
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

# ── Config ─────────────────────────────────────────────────────────────────────

ZPAY_URL = os.environ.get("ZPAY_URL", "").rstrip("/")
ZPAY_SESSION = os.environ.get("ZPAY_SESSION", "")
SAVE_DIR = Path.home() / "Documents" / "MAZ Contracts"
STATE_FILE = Path.home() / ".zpay_sync_state.json"
LOG_FILE = Path.home() / "Library" / "Logs" / "zpay_sync.log"
LAUNCHD_LABEL = "com.maz.zpay-contract-sync"
LAUNCHD_PLIST = Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"
INTERVAL_SECONDS = 900  # 15 minutes

# ── Logging ────────────────────────────────────────────────────────────────────

def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass

# ── State (tracks which file IDs we've already downloaded) ────────────────────

def load_state() -> set:
    if STATE_FILE.exists():
        try:
            data = json.loads(STATE_FILE.read_text())
            return set(data.get("downloaded_ids", []))
        except Exception:
            pass
    return set()

def save_state(downloaded_ids: set):
    STATE_FILE.write_text(json.dumps({"downloaded_ids": list(downloaded_ids)}))

# ── Sync ───────────────────────────────────────────────────────────────────────

def sync():
    if not ZPAY_URL:
        log("ERROR: ZPAY_URL not set. Edit the launchd plist and add your Z-Pay backend URL.")
        return
    if not ZPAY_SESSION:
        log("ERROR: ZPAY_SESSION not set. Get your session cookie from Z-Pay and update the plist.")
        return

    SAVE_DIR.mkdir(parents=True, exist_ok=True)
    downloaded_ids = load_state()

    # Fetch list of signed contracts from Z-Pay
    list_url = f"{ZPAY_URL}/api/v1/onboarding/contracts/list"
    req = urllib.request.Request(list_url, headers={"Cookie": f"session={ZPAY_SESSION}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            contracts = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        log(f"ERROR: Failed to fetch contract list — HTTP {e.code}")
        return
    except Exception as e:
        log(f"ERROR: Failed to fetch contract list — {e}")
        return

    new_count = 0
    for contract in contracts:
        file_id = contract.get("id")
        download_url = contract.get("download_url")
        filename = contract.get("filename") or f"contract_{file_id}.pdf"
        driver_name = contract.get("driver_name") or "Unknown Driver"
        uploaded_at = contract.get("uploaded_at", "")[:10]  # YYYY-MM-DD

        if file_id in downloaded_ids:
            continue
        if not download_url:
            log(f"SKIP: No download URL for file_id={file_id} ({driver_name})")
            continue

        # Build safe filename: YYYY-MM-DD_DriverName_filename.pdf
        safe_driver = driver_name.replace(" ", "_").replace("/", "-")
        dest_filename = f"{uploaded_at}_{safe_driver}_{filename}"
        dest = SAVE_DIR / dest_filename

        try:
            dl_req = urllib.request.Request(download_url)
            with urllib.request.urlopen(dl_req, timeout=60) as resp:
                pdf_bytes = resp.read()
            dest.write_bytes(pdf_bytes)
            downloaded_ids.add(file_id)
            save_state(downloaded_ids)
            log(f"SAVED: {dest_filename} ({len(pdf_bytes):,} bytes)")
            new_count += 1
        except Exception as e:
            log(f"ERROR: Failed to download file_id={file_id} ({driver_name}) — {e}")

    if new_count == 0:
        log(f"OK: No new contracts (checked {len(contracts)} total)")
    else:
        log(f"DONE: Downloaded {new_count} new contract(s) to {SAVE_DIR}")

# ── Install / Uninstall ────────────────────────────────────────────────────────

def install():
    script_path = Path(__file__).resolve()
    python_path = sys.executable

    plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{LAUNCHD_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{python_path}</string>
        <string>{script_path}</string>
        <string>--run-once</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>ZPAY_URL</key>
        <string>REPLACE_WITH_ZPAY_BACKEND_URL</string>
        <key>ZPAY_SESSION</key>
        <string>REPLACE_WITH_SESSION_COOKIE</string>
    </dict>
    <key>StartInterval</key>
    <integer>{INTERVAL_SECONDS}</integer>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{LOG_FILE}</string>
    <key>StandardErrorPath</key>
    <string>{LOG_FILE}</string>
</dict>
</plist>"""

    LAUNCHD_PLIST.parent.mkdir(parents=True, exist_ok=True)
    LAUNCHD_PLIST.write_text(plist_content)
    print(f"Plist written to: {LAUNCHD_PLIST}")
    print()
    print("NEXT STEP: Edit the plist and fill in:")
    print("  ZPAY_URL    — your Railway backend URL")
    print("  ZPAY_SESSION — your session cookie from Z-Pay")
    print()
    print("Then run:")
    print(f"  launchctl load {LAUNCHD_PLIST}")
    print()
    print(f"Contracts will auto-download to: {SAVE_DIR}")
    print(f"Logs at: {LOG_FILE}")

def uninstall():
    try:
        subprocess.run(["launchctl", "unload", str(LAUNCHD_PLIST)], check=False)
        LAUNCHD_PLIST.unlink(missing_ok=True)
        print("Agent uninstalled.")
    except Exception as e:
        print(f"Error during uninstall: {e}")

# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "--run-once"
    if arg == "--install":
        install()
    elif arg == "--uninstall":
        uninstall()
    elif arg == "--run-once":
        sync()
    else:
        print("Usage: python3 mac_contract_sync.py [--install | --uninstall | --run-once]")
