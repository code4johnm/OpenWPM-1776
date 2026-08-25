"""Page helpers used by built-in commands (Playwright BrowserSession)."""

from __future__ import annotations

import random
import time
from typing import Any, Callable, Dict, List, Optional
from urllib import parse as urlparse

import domain_utils as du

from ...browser import BrowserError, BrowserSession, By, NetError, SessionElement
from ...instrumentation.neterror import parse_neterror

# Re-export so callers that imported parse_neterror from webdriver_utils still work
# after the rename — those call sites are updated in this pass.

__all__ = [
    "parse_neterror",
    "scroll_down",
    "scroll_to_bottom",
    "is_loaded",
    "wait_until_loaded",
    "get_intra_links",
    "execute_script_with_retry",
    "is_displayed",
    "execute_in_all_frames",
]


def scroll_down(session: BrowserSession) -> None:
    at_bottom = False
    while random.random() > 0.20 and not at_bottom:
        session.execute_script(
            "window.scrollBy(0,%d); return true;" % (10 + int(200 * random.random()))
        )
        at_bottom = session.execute_script(
            "return (((window.scrollY + window.innerHeight ) + 100 "
            "> document.body.clientHeight ))"
        )
        time.sleep(0.5 + random.random())


def scroll_to_bottom(session: BrowserSession) -> None:
    try:
        session.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    except BrowserError:
        pass


def is_loaded(session: BrowserSession) -> bool:
    try:
        return session.execute_script("return document.readyState") == "complete"
    except BrowserError:
        return False


def wait_until_loaded(
    session: BrowserSession, timeout: float, period: float = 0.25, min_time: float = 0
) -> bool:
    start_time = time.time()
    mustend = time.time() + timeout
    while time.time() < mustend:
        if is_loaded(session):
            if time.time() - start_time < min_time:
                time.sleep(min_time + start_time - time.time())
            return True
        time.sleep(period)
    return False


def get_intra_links(session: BrowserSession, url: str) -> List[SessionElement]:
    ps1 = du.get_ps_plus_1(url)
    links = []
    for elem in session.find_elements(By.TAG_NAME, "a"):
        href = elem.get_attribute("href")
        if href is None:
            continue
        full_href = urlparse.urljoin(url, href)
        if not full_href.startswith("http"):
            continue
        try:
            if du.get_ps_plus_1(full_href) == ps1:
                links.append(elem)
        except Exception:
            continue
    return links


def execute_script_with_retry(session: BrowserSession, script: str) -> Any:
    try:
        return session.execute_script(script)
    except BrowserError:
        return session.execute_script(script)


def is_displayed(element: SessionElement) -> bool:
    try:
        return element.is_displayed()
    except Exception:
        return False


def execute_in_all_frames(
    session: BrowserSession,
    func: Callable[..., Any],
    kwargs: Optional[Dict[str, Any]] = None,
    **_unused: Any,
) -> None:
    """Apply ``func(session, frame_stack, **kwargs)`` to every frame.

    ``frame_stack`` is a list whose first item is ``"default"`` and whose
    remaining items are Playwright Frame objects (or SessionElement stand-ins
    with an ``id``). RecursiveDumpPageSourceCommand is the only in-tree caller
    and has been rewritten to walk ``page.frames`` directly; this helper
    remains for custom commands.
    """
    kwargs = kwargs or {}
    page = session.page

    def walk(frame, stack):
        func(session, stack, **kwargs)
        for child in frame.child_frames:
            walk(child, stack + [child])

    walk(page.main_frame, ["default", page.main_frame])
