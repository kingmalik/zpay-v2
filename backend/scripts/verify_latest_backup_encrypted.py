#!/usr/bin/env python3
"""
Verify the latest B2 backup: GPG-encrypted, decrypts cleanly, real pg_dump data.

Usage (Railway):
    railway run python3 scripts/verify_latest_backup_encrypted.py

Exit 0 = all pass, 1 = any fail.
"""
import gzip, io, os, subprocess, sys, tempfile

REQUIRED = ["BACKBLAZE_KEY_ID", "BACKBLAZE_APP_KEY", "BACKBLAZE_BUCKET", "BACKUP_PASSPHRASE"]


def die(msg):
    print(f"ERROR: {msg}")
    sys.exit(1)


def require_env():
    missing = [k for k in REQUIRED if not os.environ.get(k)]
    if missing:
        die(f"missing required env vars: {', '.join(missing)}\n"
            "Set them in Railway and re-run via `railway run`.")
    return {k: os.environ[k] for k in REQUIRED}


def human_size(n):
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} TB"


def list_newest_gpg(env):
    try:
        from b2sdk.v2 import InMemoryAccountInfo, B2Api
    except ImportError:
        die("b2sdk not installed — add b2sdk to requirements.txt")
    api = B2Api(InMemoryAccountInfo())
    api.authorize_account("production", env["BACKBLAZE_KEY_ID"], env["BACKBLAZE_APP_KEY"])
    bucket = api.get_bucket_by_name(env["BACKBLAZE_BUCKET"])
    files = [
        (fv.file_name, fv.size, fv.upload_timestamp)
        for fv, _ in bucket.ls(latest_only=True, recursive=True)
        if fv.file_name.endswith(".gpg")
    ]
    if not files:
        die("no .gpg objects found in bucket")
    files.sort(key=lambda x: x[2], reverse=True)
    newest = files[0]
    bucket.download_file_by_name(newest[0]).save_to(newest[0].split("/")[-1])
    return newest, bucket


def gpg_decrypt(path, passphrase):
    """Decrypt path with gpg. Returns (ok, stdout_bytes, stderr_str)."""
    r = subprocess.run(
        ["gpg", "--batch", "--yes", "--quiet", "--passphrase-fd", "0", "--decrypt", path],
        input=passphrase.encode(), capture_output=True, timeout=120,
    )
    err = r.stderr.decode(errors="replace").replace(passphrase, "***").strip()
    return r.returncode == 0, r.stdout, err


def maybe_ungzip(data):
    if data[:2] == b"\x1f\x8b":
        try:
            return gzip.open(io.BytesIO(data)).read(131072)
        except Exception:
            pass
    return data[:131072]


def main():
    env = require_env()
    print("Connecting to Backblaze B2 ...")

    try:
        from b2sdk.v2 import InMemoryAccountInfo, B2Api
    except ImportError:
        die("b2sdk not installed")

    api = B2Api(InMemoryAccountInfo())
    api.authorize_account("production", env["BACKBLAZE_KEY_ID"], env["BACKBLAZE_APP_KEY"])
    bucket = api.get_bucket_by_name(env["BACKBLAZE_BUCKET"])

    files = [
        (fv.file_name, fv.size, fv.upload_timestamp)
        for fv, _ in bucket.ls(latest_only=True, recursive=True)
        if fv.file_name.endswith(".gpg")
    ]
    if not files:
        die("no .gpg objects found in bucket")
    files.sort(key=lambda x: x[2], reverse=True)
    name, size, _ = files[0]

    print(f"\nLatest object : {name}")
    print(f"Size          : {human_size(size)}")

    results = {}

    with tempfile.NamedTemporaryFile(suffix=".gpg", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        print("Downloading ...")
        bucket.download_file_by_name(name).save_to(tmp_path)

        # 1. Encrypted?
        with open(tmp_path, "rb") as f:
            hdr = f.read(4)
        enc_ok = bool(hdr and hdr[0] & 0x80)
        results["encryption"] = enc_ok
        print(f"Encryption    : {'PASS' if enc_ok else 'FAIL'}")

        # 2. Decrypts cleanly?
        dec_ok, raw, err = gpg_decrypt(tmp_path, env["BACKUP_PASSPHRASE"])
        results["decrypt"] = dec_ok
        print(f"Decrypt       : {'PASS' if dec_ok else f'FAIL — {err[:200]}'}")

        # 3. Real pg_dump content?
        if dec_ok:
            plain = maybe_ungzip(raw)
            text = plain.decode(errors="replace")
            has_header = "PostgreSQL database dump" in text
            has_copy = b"COPY " in plain and b"FROM stdin" in plain
            content_ok = has_header and has_copy
            detail = (
                "OK" if content_ok
                else ("no pg_dump header" if not has_header else "no COPY...FROM stdin block")
            )
            results["content"] = content_ok
            print(f"Content sanity: {'PASS' if content_ok else f'FAIL — {detail}'}")
        else:
            results["content"] = False
            print("Content sanity: SKIP (decrypt failed)")

    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    all_pass = all(results.values())
    print(f"\nOverall: {'ALL CHECKS PASSED' if all_pass else 'ONE OR MORE CHECKS FAILED'}")
    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
