"""Map Chromium net::ERR_* strings onto the historical OpenWPM error codes."""

from __future__ import annotations

import re
from typing import Optional

# Keep dnsNotFound so is_dns_error() and crawl_history stay stable.
CHROME_NETERROR = {
    "ERR_NAME_NOT_RESOLVED": "dnsNotFound",
    "ERR_INTERNET_DISCONNECTED": "netOffline",
    "ERR_CONNECTION_REFUSED": "connectionFailure",
    "ERR_CONNECTION_TIMED_OUT": "netTimeout",
    "ERR_TIMED_OUT": "netTimeout",
    "ERR_CONNECTION_RESET": "netReset",
    "ERR_CONNECTION_ABORTED": "netReset",
    "ERR_ADDRESS_UNREACHABLE": "connectionFailure",
    "ERR_EMPTY_RESPONSE": "netReset",
    "ERR_SSL_PROTOCOL_ERROR": "nssFailure2",
    "ERR_CERT_AUTHORITY_INVALID": "nssFailure2",
    "ERR_CERT_COMMON_NAME_INVALID": "nssFailure2",
    "ERR_CERT_DATE_INVALID": "nssFailure2",
    "ERR_ABORTED": "NS_BINDING_ABORTED",
    "ERR_BLOCKED_BY_CLIENT": "NS_ERROR_ABORT",
    "ERR_BLOCKED_BY_RESPONSE": "NS_ERROR_ABORT",
    "ERR_NETWORK_ACCESS_DENIED": "denied",
    "ERR_TOO_MANY_REDIRECTS": "redirectLoop",
}

_NET_RE = re.compile(r"net::(ERR_[A-Z0-9_]+)")
# Legacy Firefox about:neterror query (kept so old log lines still parse).
_FF_RE = re.compile(
    r"(?:WebDriverException|Error):?\s*"
    r"(?:Message:\s*)?Reached error page: "
    r"about:neterror\?(.*)\."
)


def neterror_code(error_message: str) -> Optional[str]:
    match = _NET_RE.search(error_message or "")
    if match:
        key = match.group(1)
        return CHROME_NETERROR.get(key, key)
    return None


def parse_neterror(error_message: str) -> str:
    """Return a short error token, or the original message if unknown."""
    code = neterror_code(error_message)
    if code:
        return code
    try:
        from urllib.parse import parse_qs

        qs = _FF_RE.search(error_message)
        if qs:
            params = parse_qs(qs.group(1))
            return "&".join(params["e"])
    except Exception:
        pass
    return error_message


def is_dns_failure_message(error_message: Optional[str]) -> bool:
    if not error_message:
        return False
    return neterror_code(error_message) == "dnsNotFound" or "ERR_NAME_NOT_RESOLVED" in (
        error_message or ""
    )
