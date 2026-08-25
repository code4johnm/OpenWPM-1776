import gzip
import json
import logging
import os
import random
import time
from hashlib import md5

from ..browser import BrowserError, BrowserSession, NetError
from ..config import BrowserParams, ManagerParams
from .types import BaseCommand
from .utils.page_utils import (
    execute_script_with_retry,
    get_intra_links,
    is_displayed,
    scroll_down,
    wait_until_loaded,
)

NUM_MOUSE_MOVES = 10
RANDOM_SLEEP_LOW = 1
RANDOM_SLEEP_HIGH = 7
logger = logging.getLogger("openwpm")


def bot_mitigation(session: BrowserSession) -> None:
    """Optional mouse/scroll/sleep to look slightly less like a dead headless client.

    This is not anti-detect. ``navigator.webdriver`` stays true.
    """
    window_size = session.get_window_size()
    try:
        session.page.mouse.move(window_size["width"] / 2, window_size["height"] / 2)
        for _ in range(NUM_MOUSE_MOVES):
            session.page.mouse.move(
                random.randint(0, max(1, window_size["width"] - 1)),
                random.randint(0, max(1, window_size["height"] - 1)),
            )
    except Exception:
        pass
    scroll_down(session)
    time.sleep(random.randrange(RANDOM_SLEEP_LOW, RANDOM_SLEEP_HIGH))


def close_other_windows(session: BrowserSession) -> None:
    session.close_extra_pages()


def tab_restart_browser(session: BrowserSession) -> None:
    """Drop extra pages and park the active page on about:blank to stop traffic."""
    session.reset_to_blank()


class GetCommand(BaseCommand):
    """goes to <url> using the given browser session"""

    def __init__(self, url, sleep):
        self.url = url
        self.sleep = sleep

    def __repr__(self):
        return "GetCommand({},{})".format(self.url, self.sleep)

    def execute(
        self,
        webdriver: BrowserSession,
        browser_params: BrowserParams,
        manager_params: ManagerParams,
        extension_socket,
    ) -> None:
        tab_restart_browser(webdriver)

        if extension_socket is not None:
            extension_socket.send(self.visit_id)

        try:
            webdriver.get(self.url)
        except NetError:
            raise
        except BrowserError:
            pass

        if (
            extension_socket is not None
            and getattr(browser_params, "record_crawl_outcome", False)
            == "status_codes_only"
        ):
            try:
                extension_socket.record_document_outcome(
                    self.visit_id, getattr(webdriver, "last_document_status", None)
                )
            except Exception:
                logger.exception("Failed to record crawl_outcome for %s", self.url)

        if self.sleep:
            time.sleep(self.sleep)

        persist = getattr(extension_socket, "persist_http_responses", None)
        if callable(persist):
            try:
                persist()
            except Exception:
                logger.debug("persist_http_responses failed", exc_info=True)

        close_other_windows(webdriver)

        if browser_params.bot_mitigation:
            bot_mitigation(webdriver)


class BrowseCommand(BaseCommand):
    def __init__(self, url, num_links, sleep):
        self.url = url
        self.num_links = num_links
        self.sleep = sleep

    def __repr__(self):
        return "BrowseCommand({},{},{})".format(self.url, self.num_links, self.sleep)

    def execute(
        self,
        webdriver,
        browser_params,
        manager_params,
        extension_socket,
    ):
        get_command = GetCommand(self.url, self.sleep)
        get_command.set_visit_browser_id(self.visit_id, self.browser_id)
        get_command.execute(
            webdriver,
            browser_params,
            manager_params,
            extension_socket,
        )

        for _ in range(self.num_links):
            links = [
                x
                for x in get_intra_links(webdriver, self.url)
                if is_displayed(x) is True
            ]
            if not links:
                break
            r = int(random.random() * len(links))
            href = links[r].get_attribute("href")
            logger.info(
                "BROWSER %i: visiting internal link %s"
                % (browser_params.browser_id, href)
            )

            try:
                links[r].click()
                wait_until_loaded(webdriver, 300)
                time.sleep(max(1, self.sleep))
                if browser_params.bot_mitigation:
                    bot_mitigation(webdriver)
                webdriver.back()
                wait_until_loaded(webdriver, 300)
            except Exception as e:
                logger.error(
                    "BROWSER %i: Error visiting internal link %s",
                    browser_params.browser_id,
                    href,
                    exc_info=e,
                )
                try:
                    webdriver.get(self.url)
                    wait_until_loaded(webdriver, 300)
                except Exception:
                    break

        persist = getattr(extension_socket, "persist_http_responses", None)
        if callable(persist):
            try:
                persist()
            except Exception:
                logger.debug("persist_http_responses failed", exc_info=True)


class SaveScreenshotCommand(BaseCommand):
    def __init__(self, suffix):
        self.suffix = suffix

    def __repr__(self):
        return "SaveScreenshotCommand({})".format(self.suffix)

    def execute(
        self,
        webdriver,
        browser_params,
        manager_params,
        extension_socket,
    ):
        suffix = "-" + self.suffix if self.suffix else ""
        urlhash = md5(webdriver.current_url.encode("utf-8")).hexdigest()
        outname = os.path.join(
            manager_params.screenshot_path,
            "%i-%s%s.png" % (self.visit_id, urlhash, suffix),
        )
        webdriver.save_screenshot(outname)


class ScreenshotFullPageCommand(BaseCommand):
    def __init__(self, suffix):
        self.suffix = suffix

    def __repr__(self):
        return "ScreenshotFullPageCommand({})".format(self.suffix)

    def execute(
        self,
        webdriver,
        browser_params,
        manager_params,
        extension_socket,
    ):
        suffix = "-" + self.suffix if self.suffix else ""
        urlhash = md5(webdriver.current_url.encode("utf-8")).hexdigest()
        outname = os.path.join(
            manager_params.screenshot_path,
            "%i-%s%s.png" % (self.visit_id, urlhash, suffix),
        )
        webdriver.save_screenshot(outname, full_page=True)


class DumpPageSourceCommand(BaseCommand):
    def __init__(self, suffix):
        self.suffix = suffix

    def __repr__(self):
        return "DumpPageSourceCommand({})".format(self.suffix)

    def execute(
        self,
        webdriver,
        browser_params,
        manager_params,
        extension_socket,
    ):
        suffix = "-" + self.suffix if self.suffix else ""
        outname = md5(webdriver.current_url.encode("utf-8")).hexdigest()
        outfile = os.path.join(
            manager_params.source_dump_path,
            "%i-%s%s.html" % (self.visit_id, outname, suffix),
        )
        with open(outfile, "wb") as f:
            f.write(webdriver.page_source.encode("utf8"))
            f.write(b"\n")


class RecursiveDumpPageSourceCommand(BaseCommand):
    def __init__(self, suffix):
        self.suffix = suffix

    def __repr__(self):
        return "RecursiveDumpPageSourceCommand({})".format(self.suffix)

    def execute(
        self,
        webdriver,
        browser_params,
        manager_params,
        extension_socket,
    ):
        suffix = "-" + self.suffix if self.suffix else ""
        outname = md5(webdriver.current_url.encode("utf-8")).hexdigest()
        outfile = os.path.join(
            manager_params.source_dump_path,
            "%i-%s%s.json.gz" % (self.visit_id, outname, suffix),
        )

        def collect(frame):
            try:
                source = frame.content()
            except Exception:
                source = ""
            return {
                "doc_url": frame.url,
                "source": source,
                "iframes": {
                    str(i): collect(child) for i, child in enumerate(frame.child_frames)
                },
            }

        page_source = collect(webdriver.page.main_frame)
        with gzip.GzipFile(outfile, "wb") as f:
            f.write(json.dumps(page_source).encode("utf-8"))


class FinalizeCommand(BaseCommand):
    """Automatically appended to the end of a CommandSequence."""

    def __init__(self, sleep):
        self.sleep = sleep

    def __repr__(self):
        return f"FinalizeCommand({self.sleep})"

    def execute(
        self,
        webdriver,
        browser_params,
        manager_params,
        extension_socket,
    ):
        tab_restart_browser(webdriver)
        time.sleep(self.sleep)
        msg = {"action": "Finalize", "visit_id": self.visit_id}
        extension_socket.send(msg)


class InitializeCommand(BaseCommand):
    """Automatically prepended to the beginning of a CommandSequence."""

    def __repr__(self):
        return "InitializeCommand()"

    def execute(
        self,
        webdriver,
        browser_params,
        manager_params,
        extension_socket,
    ):
        msg = {"action": "Initialize", "visit_id": self.visit_id}
        extension_socket.send(msg)
