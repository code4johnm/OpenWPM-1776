"""Playwright-backed browser session used by commands.

Custom commands receive a BrowserSession. It exposes the Playwright
``page`` / ``context`` objects plus a small Selenium-shaped surface
(``current_url``, ``find_elements``, ``execute_script``) so existing
commands keep working with minimal changes. See MIGRATION.md.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, List, Optional, Sequence, Union

if TYPE_CHECKING:
    from playwright.sync_api import (
        BrowserContext,
        Dialog,
        ElementHandle,
        Frame,
        Page,
        Playwright,
    )

logger = logging.getLogger("openwpm")


def _playwright_errors():
    from playwright.sync_api import Error
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

    return Error, PlaywrightTimeoutError


DEFAULT_VIEWPORT = {"width": 1366, "height": 768}


class By:
    """Locator strategies accepted by ``BrowserSession.find_element(s)``."""

    TAG_NAME = "tag name"
    ID = "id"
    CSS_SELECTOR = "css selector"
    XPATH = "xpath"
    CLASS_NAME = "class name"
    NAME = "name"
    LINK_TEXT = "link text"
    PARTIAL_LINK_TEXT = "partial link text"


class BrowserError(Exception):
    """Raised for recoverable automation failures (replaces WebDriverException)."""


class NetError(BrowserError):
    """Navigation failed with a Chromium network error (DNS, TLS, reset, ...)."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class SessionElement:
    """Thin wrapper around a Playwright ElementHandle for command code."""

    def __init__(self, handle: ElementHandle) -> None:
        self._el = handle
        self.id = str(id(handle))

    def get_attribute(self, name: str) -> Optional[str]:
        try:
            return self._el.get_attribute(name)
        except Exception:
            return None

    def click(self) -> None:
        self._el.click()

    def is_displayed(self) -> bool:
        try:
            return self._el.is_visible()
        except Exception:
            return False

    def is_enabled(self) -> bool:
        try:
            return self._el.is_enabled()
        except Exception:
            return False

    @property
    def text(self) -> str:
        try:
            return self._el.inner_text()
        except Exception:
            return ""

    @property
    def location(self) -> dict:
        try:
            box = self._el.bounding_box()
        except Exception:
            box = None
        if not box:
            return {"x": 0, "y": 0}
        return {"x": box["x"], "y": box["y"]}


class BrowserSession:
    """One Chromium persistent context + the page commands operate on."""

    def __init__(
        self,
        playwright: Playwright,
        context: BrowserContext,
        page: Page,
        profile_path: Any,
        browser_pid: Optional[int] = None,
    ) -> None:
        self.playwright = playwright
        self.context = context
        self.page = page
        self.profile_path = profile_path
        self.browser_pid = browser_pid
        self.last_document_status: Optional[int] = None
        self._dismiss_dialogs()

    def _dismiss_dialogs(self) -> None:
        def _on_dialog(dialog: Dialog) -> None:
            try:
                dialog.dismiss()
            except Exception:
                pass

        self.page.on("dialog", _on_dialog)
        self.context.on("page", lambda p: p.on("dialog", _on_dialog))

    @property
    def current_url(self) -> str:
        try:
            return self.page.url
        except Exception:
            return "about:blank"

    @property
    def page_source(self) -> str:
        return self.page.content()

    @property
    def title(self) -> str:
        return self.page.title()

    @property
    def current_window_handle(self) -> Page:
        return self.page

    @property
    def window_handles(self) -> List[Page]:
        return [p for p in self.context.pages if not p.is_closed()]

    def get_window_size(self) -> dict:
        vp = self.page.viewport_size or DEFAULT_VIEWPORT
        return {"width": vp["width"], "height": vp["height"]}

    def set_window_size(self, width: int, height: int) -> None:
        self.page.set_viewport_size({"width": width, "height": height})

    def get(self, url: str, timeout: float = 30000) -> None:
        """Navigate. Timeout is milliseconds (Playwright convention)."""
        Error, PWTimeout = _playwright_errors()
        self.last_document_status = None
        try:
            response = self.page.goto(
                url, wait_until="domcontentloaded", timeout=timeout
            )
            # Final document after redirects. None → no crawl_outcome row.
            if response is not None:
                self.last_document_status = response.status
            try:
                self.page.wait_for_load_state("load", timeout=min(timeout, 15000))
            except PWTimeout:
                pass
        except PWTimeout:
            pass
        except Error as exc:
            raise _as_browser_error(exc) from exc

    def goto(self, url: str, **kwargs: Any) -> Any:
        Error, _ = _playwright_errors()
        try:
            return self.page.goto(url, **kwargs)
        except Error as exc:
            raise _as_browser_error(exc) from exc

    def back(self) -> None:
        Error, _ = _playwright_errors()
        try:
            self.page.go_back(wait_until="domcontentloaded")
        except Error as exc:
            raise _as_browser_error(exc) from exc

    def execute_script(self, script: str, *args: Any) -> Any:
        body = script.strip()
        Error, _ = _playwright_errors()
        try:
            if args:
                return self.page.evaluate(f"(args) => {{ {body} }}", list(args))
            return self.page.evaluate(f"() => {{ {body} }}")
        except Error as exc:
            raise BrowserError(str(exc)) from exc

    def evaluate(self, expression: str, arg: Any = None) -> Any:
        if arg is None:
            return self.page.evaluate(expression)
        return self.page.evaluate(expression, arg)

    def find_elements(
        self, by: str, value: Optional[str] = None
    ) -> List[SessionElement]:
        selector = _to_selector(by, value)
        try:
            handles = self.page.query_selector_all(selector)
        except Exception:
            return []
        return [SessionElement(h) for h in handles]

    def find_element(self, by: str, value: Optional[str] = None) -> SessionElement:
        els = self.find_elements(by, value)
        if not els:
            raise BrowserError(f"No element found: {by}={value}")
        return els[0]

    def save_screenshot(self, path: str, full_page: bool = False) -> None:
        self.page.screenshot(path=path, full_page=full_page)

    def close_extra_pages(self) -> None:
        for page in list(self.context.pages):
            if page is self.page or page.is_closed():
                continue
            try:
                page.close()
            except Exception:
                pass

    def reset_to_blank(self) -> None:
        """Stop in-flight traffic by navigating the active page to about:blank."""
        self.close_extra_pages()
        url = (self.current_url or "").lower()
        if url in ("about:blank", "about:blank/", "chrome://newtab/", ""):
            return
        Error, _ = _playwright_errors()
        try:
            self.page.goto("about:blank", wait_until="commit", timeout=10000)
        except Error:
            pass

    def close(self) -> None:
        """Close the current page (profile dump may still need the context)."""
        Error, _ = _playwright_errors()
        try:
            if not self.page.is_closed():
                self.page.close()
        except Error:
            pass

    def close_context(self) -> None:
        Error, _ = _playwright_errors()
        try:
            self.context.close()
        except Error:
            pass

    def quit(self) -> None:
        self.close_context()
        playwright = getattr(self, "playwright", None)
        if playwright is None:
            return
        try:
            playwright.stop()
        except Exception:
            pass
        self.playwright = None  # type: ignore[assignment]

    def cookies(self, urls: Optional[Sequence[str]] = None) -> list:
        if urls:
            return self.context.cookies(list(urls))
        return self.context.cookies()

    def frames(self) -> List[Frame]:
        return list(self.page.frames)


def _to_selector(by: str, value: Optional[str]) -> str:
    if value is None:
        return by
    if by in (By.TAG_NAME, "tag name", "tag_name"):
        return value
    if by in (By.ID, "id"):
        return f"#{value}"
    if by in (By.CSS_SELECTOR, "css selector"):
        return value
    if by in (By.XPATH, "xpath"):
        return f"xpath={value}"
    if by in (By.CLASS_NAME, "class name"):
        return f".{value}"
    if by in (By.NAME, "name"):
        return f'[name="{value}"]'
    if by in (By.LINK_TEXT, "link text"):
        return f"text={value}"
    if by in (By.PARTIAL_LINK_TEXT, "partial link text"):
        return f"text={value}"
    return value


def _as_browser_error(exc: BaseException) -> Union[NetError, BrowserError]:
    from openwpm.instrumentation.neterror import neterror_code

    message = str(exc)
    code = neterror_code(message)
    if code:
        return NetError(code, message)
    return BrowserError(message)
