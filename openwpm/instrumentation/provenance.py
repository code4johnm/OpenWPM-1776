"""Crawl-run provenance and main-document blocking-status helpers.

These records measure the browser stack and observed 403/429/503 on the
main document. They are off by default and do not enable HTTP/cookie
instruments, collect bodies, or change the User-Agent.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Union

OUTCOME_BY_STATUS = {
    403: "forbidden",
    429: "rate_limited",
    503: "unavailable",
}

ALLOWED_CRAWL_OUTCOME = (False, "status_codes_only")


def playwright_version() -> str:
    """Return the installed Playwright package version.

    ``playwright.__version__`` is not set on current packages; read
    ``importlib.metadata`` instead.
    """
    try:
        from importlib.metadata import version

        return version("playwright")
    except Exception:
        pass
    try:
        from importlib.metadata import version

        return version("playwright-core")
    except Exception:
        pass
    try:
        import playwright

        ver = getattr(playwright, "__version__", None)
        if ver:
            return str(ver)
    except Exception:
        pass
    return "unknown"


def headed_from_display_mode(display_mode: str) -> bool:
    return display_mode != "headless"


def build_provenance_record(
    *,
    browser_id: int,
    display_mode: str,
    user_agent: str,
    playwright_ver: Optional[str] = None,
    browser_engine: str = "chromium",
) -> Dict[str, Any]:
    return {
        "browser_id": int(browser_id),
        "browser_engine": browser_engine,
        "display_mode": display_mode,
        "headed": 1 if headed_from_display_mode(display_mode) else 0,
        "playwright_version": (
            playwright_ver if playwright_ver is not None else playwright_version()
        ),
        "user_agent": user_agent,
    }


def outcome_for_status(http_status: Union[int, None]) -> Optional[str]:
    if http_status is None:
        return None
    return OUTCOME_BY_STATUS.get(int(http_status))


def build_crawl_outcome_record(
    *,
    visit_id: int,
    browser_id: int,
    http_status: int,
) -> Optional[Dict[str, Any]]:
    outcome = outcome_for_status(http_status)
    if outcome is None:
        return None
    return {
        "visit_id": int(visit_id),
        "browser_id": int(browser_id),
        "http_status": int(http_status),
        "outcome": outcome,
        "resource_scope": "document",
    }
