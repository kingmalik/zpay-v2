"""
Google Drive archive service for Maz payroll exports.

On every Maz batch approval, Z-Pay uploads the payroll xlsx to:
    Master/Maz/Z-Pay Outputs/<filename>

The parent folder `Master/Maz/` is looked up by name (not hardcoded ID).
If the `Z-Pay Outputs` subfolder doesn't exist it is created automatically.

Auth:
  Reuses the existing GMAIL_CLIENT_ID + GMAIL_CLIENT_SECRET OAuth client.
  Requires a refresh token that was issued with BOTH Gmail AND Drive scopes:
    - https://www.googleapis.com/auth/gmail.send
    - https://www.googleapis.com/auth/drive.file

  The new refresh token is stored in GOOGLE_DRIVE_REFRESH_TOKEN_MAZ.
  The existing GMAIL_REFRESH_TOKEN_MAZ (Gmail-only) is NOT replaced.

Usage:
    from backend.services.drive_archive import upload_maz_payroll_xlsx
    url = upload_maz_payroll_xlsx(week_no=15, period_start=date(2026,4,13), xlsx_bytes=b"...")

Environment variables (required):
    GMAIL_CLIENT_ID
    GMAIL_CLIENT_SECRET
    GOOGLE_DRIVE_REFRESH_TOKEN_MAZ   # new token with Drive+Gmail scopes

Optional override:
    MAZ_PAYROLL_DRIVE_FOLDER_ID      # skip folder-lookup; use this folder ID directly
"""
from __future__ import annotations

import io
import json
import logging
import os
from datetime import date
from typing import Optional

import requests

log = logging.getLogger(__name__)

# ── OAuth constants ───────────────────────────────────────────────────────────

_TOKEN_URL = "https://oauth2.googleapis.com/token"
_DRIVE_FILES_URL = "https://www.googleapis.com/drive/v3/files"
_DRIVE_UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3/files"

# Folder search uses "drive" scope; upload uses "drive.file" (narrower, preferred).
# Both are granted by the combined refresh token.
_SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/drive.file",
]

# Name of the subfolder created under Master/Maz/
_OUTPUT_SUBFOLDER = "Z-Pay Outputs"
# Name of the intermediate parent (used for lookup only — never created by us)
_MAZ_PARENT_FOLDER = "Maz"


def _get_access_token() -> str:
    """Exchange refresh token for a short-lived access token."""
    client_id = os.environ.get("GMAIL_CLIENT_ID", "")
    client_secret = os.environ.get("GMAIL_CLIENT_SECRET", "")
    refresh_token = os.environ.get("GOOGLE_DRIVE_REFRESH_TOKEN_MAZ", "")

    if not all([client_id, client_secret, refresh_token]):
        missing = [
            k for k, v in {
                "GMAIL_CLIENT_ID": client_id,
                "GMAIL_CLIENT_SECRET": client_secret,
                "GOOGLE_DRIVE_REFRESH_TOKEN_MAZ": refresh_token,
            }.items() if not v
        ]
        raise EnvironmentError(
            f"Drive archive: missing env vars: {', '.join(missing)}"
        )

    resp = requests.post(
        _TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def _find_folder(name: str, parent_id: Optional[str], token: str) -> Optional[str]:
    """Return the Drive folder ID matching *name* under *parent_id*, or None."""
    q_parts = [
        f"name = '{name}'",
        "mimeType = 'application/vnd.google-apps.folder'",
        "trashed = false",
    ]
    if parent_id:
        q_parts.append(f"'{parent_id}' in parents")

    resp = requests.get(
        _DRIVE_FILES_URL,
        headers={"Authorization": f"Bearer {token}"},
        params={"q": " and ".join(q_parts), "fields": "files(id, name)", "spaces": "drive"},
        timeout=15,
    )
    resp.raise_for_status()
    files = resp.json().get("files", [])
    return files[0]["id"] if files else None


def _create_folder(name: str, parent_id: Optional[str], token: str) -> str:
    """Create a Drive folder named *name* under *parent_id* and return its ID."""
    metadata: dict = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
    }
    if parent_id:
        metadata["parents"] = [parent_id]

    resp = requests.post(
        _DRIVE_FILES_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        data=json.dumps(metadata),
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["id"]


def _get_or_create_output_folder(token: str) -> str:
    """
    Locate or create the `Z-Pay Outputs` folder under `Master/Maz/`.

    Walk order:
      1. If MAZ_PAYROLL_DRIVE_FOLDER_ID env var is set, use it directly.
      2. Search Drive for a folder named "Maz" (top-level).
      3. Under that, find or create "Z-Pay Outputs".

    Returns the folder ID for `Z-Pay Outputs`.
    """
    override = os.environ.get("MAZ_PAYROLL_DRIVE_FOLDER_ID", "").strip()
    if override:
        log.debug("drive_archive: using MAZ_PAYROLL_DRIVE_FOLDER_ID override=%s", override)
        return override

    # Find the Maz parent folder (created by Drive user, not by us)
    maz_id = _find_folder(_MAZ_PARENT_FOLDER, parent_id=None, token=token)
    if not maz_id:
        raise RuntimeError(
            f"Drive archive: could not find a folder named '{_MAZ_PARENT_FOLDER}' "
            f"in Google Drive. Create it manually or set MAZ_PAYROLL_DRIVE_FOLDER_ID."
        )
    log.debug("drive_archive: found Maz folder id=%s", maz_id)

    # Find or create Z-Pay Outputs under Maz
    output_id = _find_folder(_OUTPUT_SUBFOLDER, parent_id=maz_id, token=token)
    if output_id:
        log.debug("drive_archive: found Z-Pay Outputs id=%s", output_id)
        return output_id

    log.info("drive_archive: creating '%s' under Maz (%s)", _OUTPUT_SUBFOLDER, maz_id)
    output_id = _create_folder(_OUTPUT_SUBFOLDER, parent_id=maz_id, token=token)
    log.info("drive_archive: created Z-Pay Outputs id=%s", output_id)
    return output_id


def _search_file_in_folder(filename: str, folder_id: str, token: str) -> Optional[str]:
    """Return the file ID if a file with *filename* already exists in *folder_id*."""
    q = (
        f"name = '{filename}' "
        f"and '{folder_id}' in parents "
        f"and trashed = false"
    )
    resp = requests.get(
        _DRIVE_FILES_URL,
        headers={"Authorization": f"Bearer {token}"},
        params={"q": q, "fields": "files(id, name)"},
        timeout=15,
    )
    resp.raise_for_status()
    files = resp.json().get("files", [])
    return files[0]["id"] if files else None


def _upload_file(
    filename: str,
    xlsx_bytes: bytes,
    folder_id: str,
    token: str,
    existing_file_id: Optional[str] = None,
) -> str:
    """
    Upload xlsx_bytes to Drive as *filename* inside *folder_id*.

    If *existing_file_id* is set, the file is overwritten (PUT to update).
    Returns the shareable web view link.
    """
    mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    if existing_file_id:
        # Update existing file content
        resp = requests.patch(
            f"{_DRIVE_UPLOAD_URL}/{existing_file_id}",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": mime,
            },
            params={"uploadType": "media"},
            data=xlsx_bytes,
            timeout=60,
        )
        resp.raise_for_status()
        file_id = existing_file_id
    else:
        # Multipart upload: metadata + bytes in one request
        metadata = json.dumps({"name": filename, "parents": [folder_id]})
        boundary = "zpay_drive_boundary"
        body = (
            f"--{boundary}\r\n"
            f"Content-Type: application/json; charset=UTF-8\r\n\r\n"
            f"{metadata}\r\n"
            f"--{boundary}\r\n"
            f"Content-Type: {mime}\r\n\r\n"
        ).encode() + xlsx_bytes + f"\r\n--{boundary}--".encode()

        resp = requests.post(
            _DRIVE_UPLOAD_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": f"multipart/related; boundary={boundary}",
            },
            params={"uploadType": "multipart", "fields": "id"},
            data=body,
            timeout=60,
        )
        resp.raise_for_status()
        file_id = resp.json()["id"]

    # Make the file readable by anyone with the link
    requests.post(
        f"{_DRIVE_FILES_URL}/{file_id}/permissions",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        data=json.dumps({"role": "reader", "type": "anyone"}),
        timeout=15,
    )

    # Fetch the web view link
    meta_resp = requests.get(
        f"{_DRIVE_FILES_URL}/{file_id}",
        headers={"Authorization": f"Bearer {token}"},
        params={"fields": "webViewLink"},
        timeout=15,
    )
    meta_resp.raise_for_status()
    return meta_resp.json().get("webViewLink", f"https://drive.google.com/file/d/{file_id}/view")


def _build_filename(week_no: int, approved_date: date) -> str:
    """Return the canonical archive filename for a Maz payroll week."""
    week_str = f"W{week_no:02d}"
    date_str = approved_date.strftime("%Y-%m-%d")
    return f"{week_str}_Maz_Payroll_Approved_{date_str}.xlsx"


def upload_maz_payroll_xlsx(
    week_no: int,
    period_start: date,
    xlsx_bytes: bytes,
    approved_date: Optional[date] = None,
) -> str:
    """
    Upload a Maz payroll xlsx to Google Drive and return the shareable URL.

    Idempotent: if a file with the same name already exists in the folder,
    it is overwritten (not duplicated).

    Args:
        week_no:       ISO week number (e.g. 15 for W15).
        period_start:  Batch period_start date — used only to derive week_no
                       if caller passes 0. Pass the correct week_no directly.
        xlsx_bytes:    Raw xlsx file bytes to upload.
        approved_date: Date to embed in the filename (defaults to today).

    Returns:
        Google Drive webViewLink (shareable URL).
    """
    from datetime import date as _date_cls
    effective_date = approved_date or _date_cls.today()
    filename = _build_filename(week_no, effective_date)

    log.info("drive_archive: uploading %s (%d bytes)", filename, len(xlsx_bytes))

    token = _get_access_token()
    folder_id = _get_or_create_output_folder(token)

    existing_id = _search_file_in_folder(filename, folder_id, token)
    if existing_id:
        log.info("drive_archive: overwriting existing file id=%s", existing_id)

    url = _upload_file(filename, xlsx_bytes, folder_id, token, existing_file_id=existing_id)
    log.info("drive_archive: uploaded successfully -> %s", url)
    return url
