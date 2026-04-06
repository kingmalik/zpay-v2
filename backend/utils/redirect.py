"""
Safe redirect utility — prevents open redirect attacks.
Only allows relative URLs starting with /. Rejects any URL with a scheme or netloc.
"""

from urllib.parse import urlparse


def safe_redirect(url: str, fallback: str = "/") -> str:
    """Return url if it's a safe relative path, else return fallback."""
    if not url:
        return fallback
    parsed = urlparse(url)
    # Reject any URL with a scheme (http://, https://) or network location
    if parsed.scheme or parsed.netloc:
        return fallback
    # Must start with /
    if not url.startswith("/"):
        return fallback
    # Block protocol-relative URLs (//evil.com)
    if url.startswith("//"):
        return fallback
    return url
