#!/usr/bin/env python3
"""
backfill_emails_from_sent.py
----------------------------
One-off script: reads the Sent folder of noreply.acumenpay@gmail.com,
extracts recipient addresses from paystub emails, and backfills person.email
for the 16 active drivers that currently have NULL email.

PREREQUISITES
-------------
1. Run /admin/gmail-reauth?account=acumen with the wider scope
   (gmail.send + gmail.readonly) so the stored refresh token covers reads.
   The new token lands in Railway env var GMAIL_REFRESH_TOKEN_ACUMEN
   automatically via the callback.

2. Export it to your local env before running this script:
     export DATABASE_URL="postgresql://app:zpay_secret_2026@junction.proxy.rlwy.net:38477/appdb"
     export GMAIL_CLIENT_ID="<from Railway>"
     export GMAIL_CLIENT_SECRET="<from Railway>"
     export GMAIL_REFRESH_TOKEN_ACUMEN="<new token after reauth>"

RUN COMMAND (after reauth)
--------------------------
    cd ~/Desktop/zpay-v2-fresh
    python scripts/backfill_emails_from_sent.py

IDEMPOTENT: re-running is safe — only fills NULL/empty email cells,
never overwrites an existing address.
"""

import os
import re
import sys
import base64
import logging
from typing import Optional

import psycopg2
from psycopg2.extras import RealDictCursor
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("backfill_emails")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
]

GMAIL_QUERY = 'in:sent subject:"Pay Stub"'
# Also try subject:"paystub" if the template changed at some point
GMAIL_QUERY_ALT = 'in:sent subject:"paystub"'

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
# Matches "Dear Firstname," or "Dear Firstname " at start of body
DEAR_RE = re.compile(r"Dear\s+([A-Za-z]+)[,\s]")


def _get_gmail_service():
    client_id     = os.environ.get("GMAIL_CLIENT_ID", "").strip()
    client_secret = os.environ.get("GMAIL_CLIENT_SECRET", "").strip()
    refresh_token = os.environ.get("GMAIL_REFRESH_TOKEN_ACUMEN", "").strip()

    missing = [k for k, v in {
        "GMAIL_CLIENT_ID": client_id,
        "GMAIL_CLIENT_SECRET": client_secret,
        "GMAIL_REFRESH_TOKEN_ACUMEN": refresh_token,
    }.items() if not v]

    if missing:
        log.error("Missing env vars: %s", ", ".join(missing))
        log.error("Export them before running. See script header for instructions.")
        sys.exit(1)

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=SCOPES,
    )
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _list_message_ids(service, query: str) -> list[str]:
    """Return all message IDs matching query (handles pagination)."""
    ids = []
    page_token = None
    while True:
        kwargs = {"userId": "me", "q": query, "maxResults": 500}
        if page_token:
            kwargs["pageToken"] = page_token
        resp = service.users().messages().list(**kwargs).execute()
        ids.extend(m["id"] for m in resp.get("messages", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return ids


def _get_header(headers: list[dict], name: str) -> str:
    for h in headers:
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""


def _extract_first_name_from_body(service, msg_id: str) -> Optional[str]:
    """Fetch message body and parse 'Dear Firstname,' salutation."""
    try:
        msg = service.users().messages().get(
            userId="me", id=msg_id, format="full"
        ).execute()
        payload = msg.get("payload", {})

        def _decode_part(part) -> str:
            data = part.get("body", {}).get("data", "")
            if not data:
                return ""
            return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="ignore")

        body_text = ""
        if payload.get("mimeType", "").startswith("text/plain"):
            body_text = _decode_part(payload)
        else:
            for part in payload.get("parts", []):
                if part.get("mimeType") == "text/plain":
                    body_text = _decode_part(part)
                    break
                if part.get("mimeType") == "text/html" and not body_text:
                    body_text = _decode_part(part)

        m = DEAR_RE.search(body_text)
        if m:
            return m.group(1).strip().lower()
    except Exception as exc:
        log.debug("Could not fetch body for %s: %s", msg_id, exc)
    return None


def _load_target_drivers(conn) -> dict[int, dict]:
    """Return {person_id: {full_name, first_name_lower}} for active NULL-email drivers."""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT person_id, full_name
            FROM person
            WHERE active = true
              AND (email IS NULL OR email = '')
            ORDER BY full_name
        """)
        rows = cur.fetchall()

    result = {}
    for row in rows:
        pid = row["person_id"]
        fname = row["full_name"].strip().split()[0].lower()
        result[pid] = {"full_name": row["full_name"], "first_name": fname}
    return result


def _apply_update(conn, person_id: int, email: str, dry_run: bool = False) -> None:
    if dry_run:
        log.info("DRY RUN  would set person_id=%s → %s", person_id, email)
        return
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE person SET email = %s WHERE person_id = %s AND (email IS NULL OR email = '')",
            (email, person_id),
        )
    conn.commit()


def main() -> None:
    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        log.error("DATABASE_URL not set.")
        sys.exit(1)

    dry_run = "--dry-run" in sys.argv
    if dry_run:
        log.info("DRY RUN mode — no DB writes will happen")

    # -----------------------------------------------------------------------
    # 1. Load target drivers
    # -----------------------------------------------------------------------
    conn = psycopg2.connect(db_url)
    targets = _load_target_drivers(conn)

    if not targets:
        log.info("No active drivers with NULL email — nothing to do.")
        conn.close()
        return

    log.info("Targeting %d active drivers with NULL email:", len(targets))
    for pid, d in targets.items():
        log.info("  pid=%-5s  %s  (first_name=%s)", pid, d["full_name"], d["first_name"])

    # -----------------------------------------------------------------------
    # 2. Build Gmail service
    # -----------------------------------------------------------------------
    service = _get_gmail_service()
    log.info("Gmail service authenticated OK")

    # -----------------------------------------------------------------------
    # 3. Fetch Sent messages
    # -----------------------------------------------------------------------
    log.info("Fetching sent paystub messages (query: %s)...", GMAIL_QUERY)
    msg_ids = _list_message_ids(service, GMAIL_QUERY)
    if not msg_ids:
        log.info("No results for primary query. Trying alt query: %s", GMAIL_QUERY_ALT)
        msg_ids = _list_message_ids(service, GMAIL_QUERY_ALT)

    log.info("Found %d sent paystub message(s) to scan", len(msg_ids))

    if not msg_ids:
        log.warning("No paystub emails found in Sent folder. Check that the account is noreply.acumenpay@gmail.com and subject matches.")
        conn.close()
        return

    # -----------------------------------------------------------------------
    # 4. Parse: recipient → first-name mapping
    # -----------------------------------------------------------------------
    # recipient_email → set of first_names seen (to detect ambiguity)
    # first_name_lower → set of recipient emails (to detect multiple addresses per name)
    fname_to_emails: dict[str, set[str]] = {}   # first_name → {emails}
    email_to_fnames: dict[str, set[str]] = {}   # email → {first_names}

    for i, mid in enumerate(msg_ids):
        if i % 50 == 0:
            log.info("  scanning message %d / %d ...", i + 1, len(msg_ids))
        try:
            meta = service.users().messages().get(
                userId="me", id=mid, format="metadata",
                metadataHeaders=["To", "Subject"]
            ).execute()
        except Exception as exc:
            log.debug("Could not fetch metadata for %s: %s", mid, exc)
            continue

        headers = meta.get("payload", {}).get("headers", [])
        to_header = _get_header(headers, "To")
        if not to_header:
            continue

        # Extract all email addresses from the To: header
        recipient_emails = EMAIL_RE.findall(to_header)
        if not recipient_emails:
            continue

        # Try to get first name from body salutation
        first_name = _extract_first_name_from_body(service, mid)

        for email_addr in recipient_emails:
            email_addr = email_addr.lower().strip()
            if first_name:
                fname_to_emails.setdefault(first_name, set()).add(email_addr)
                email_to_fnames.setdefault(email_addr, set()).add(first_name)

    log.info("Parsed %d unique first-name→email mappings", len(fname_to_emails))

    # -----------------------------------------------------------------------
    # 5. Match drivers → emails
    # -----------------------------------------------------------------------
    matched = []
    ambiguous = []
    not_found = []

    for pid, driver in targets.items():
        fname = driver["first_name"]
        emails_for_name = fname_to_emails.get(fname, set())

        if not emails_for_name:
            not_found.append((pid, driver["full_name"], fname))
            continue

        if len(emails_for_name) > 1:
            # Multiple distinct addresses sent to this first name — flag for manual review
            ambiguous.append((pid, driver["full_name"], fname, sorted(emails_for_name)))
            continue

        email_addr = next(iter(emails_for_name))

        # Extra safety: if this email was seen under multiple first names, skip
        fnames_for_email = email_to_fnames.get(email_addr, set())
        if len(fnames_for_email) > 1:
            ambiguous.append((pid, driver["full_name"], fname, [email_addr + " (shared name)"]))
            continue

        matched.append((pid, driver["full_name"], email_addr))

    # -----------------------------------------------------------------------
    # 6. Apply updates
    # -----------------------------------------------------------------------
    log.info("")
    log.info("=== RESULTS ===")
    log.info("Matched:   %d drivers", len(matched))
    log.info("Ambiguous: %d drivers (skipped — manual review needed)", len(ambiguous))
    log.info("Not found: %d drivers", len(not_found))
    log.info("")

    if matched:
        log.info("--- MATCHED (will update) ---")
        for pid, name, email_addr in matched:
            log.info("  pid=%-5s  %-30s  ->  %s", pid, name, email_addr)
            _apply_update(conn, pid, email_addr, dry_run=dry_run)

    if ambiguous:
        log.info("")
        log.info("--- AMBIGUOUS (manual review needed) ---")
        for pid, name, fname, candidates in ambiguous:
            log.info("  pid=%-5s  %-30s  first_name=%s  candidates=%s", pid, name, fname, candidates)
        log.info("Run: UPDATE person SET email='...' WHERE person_id=... AND email IS NULL;")

    if not_found:
        log.info("")
        log.info("--- NOT FOUND in Sent folder ---")
        for pid, name, fname in not_found:
            log.info("  pid=%-5s  %-30s  (searching for first_name=%s)", pid, name, fname)
        log.info("These drivers may not have received a paystub yet, or the salutation format differs.")

    conn.close()
    log.info("")
    if dry_run:
        log.info("DRY RUN complete — rerun without --dry-run to apply.")
    else:
        log.info("Done. Re-run is safe (idempotent — only fills NULLs).")


if __name__ == "__main__":
    main()
