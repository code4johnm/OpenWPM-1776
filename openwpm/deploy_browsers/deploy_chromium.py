"""Launch a Playwright Chromium persistent context for one BrowserManager."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from easyprocess import EasyProcessError
from multiprocess import Queue
from pyvirtualdisplay import Display

from ..browser import DEFAULT_VIEWPORT, BrowserSession
from ..browser_bin import chromium_executable, ensure_browsers_path
from ..commands.profile_commands import load_profile
from ..config import BrowserParamsInternal, ConfigEncoder, ManagerParamsInternal
from .configure_chromium import DEFAULT_SCREEN_RES, launch_args, needs_no_sandbox

logger = logging.getLogger("openwpm")


def deploy_chromium(
    status_queue: Queue,
    browser_params: BrowserParamsInternal,
    manager_params: ManagerParamsInternal,
    crash_recovery: bool,
) -> Tuple[BrowserSession, Path, Optional[Display]]:
    ensure_browsers_path()
    chromium_executable()  # fail closed if the binary is missing

    browser_profile_path = Path(
        tempfile.mkdtemp(prefix="chromium_profile_", dir=browser_params.tmp_profile_dir)
    )
    status_queue.put(("STATUS", "Profile Created", browser_profile_path))

    assert browser_params.browser_id is not None
    if browser_params.seed_tar and not crash_recovery:
        logger.info(
            "BROWSER %i: Loading initial browser profile from: %s"
            % (browser_params.browser_id, browser_params.seed_tar)
        )
        load_profile(browser_profile_path, browser_params, browser_params.seed_tar)
    elif browser_params.recovery_tar:
        logger.debug(
            "BROWSER %i: Loading recovered browser profile from: %s"
            % (browser_params.browser_id, browser_params.recovery_tar)
        )
        load_profile(browser_profile_path, browser_params, browser_params.recovery_tar)
    status_queue.put(("STATUS", "Profile Tar", None))

    display_mode = browser_params.display_mode
    display_pid = None
    display_port = None
    display = None
    if display_mode == "xvfb":
        try:
            display = Display(visible=False, size=DEFAULT_SCREEN_RES)
            display.start()
            display_pid, display_port = display.pid, display.display
        except EasyProcessError as exc:
            raise RuntimeError(
                "Xvfb could not be started. Please ensure it's on your path. "
                "See www.X.org for full details. Commonly solved on ubuntu "
                "with `sudo apt install xvfb`"
            ) from exc
    status_queue.put(("STATUS", "Display", (display_pid, display_port)))

    extension_config: Dict[str, Any] = dict()
    extension_config.update(browser_params.to_dict())
    extension_config["logger_address"] = manager_params.logger_address
    extension_config["storage_controller_address"] = (
        manager_params.storage_controller_address
    )
    extension_config["testing"] = manager_params.testing
    ext_config_file = browser_profile_path / "browser_params.json"
    with open(ext_config_file, "w") as f:
        json.dump(extension_config, f, cls=ConfigEncoder)

    if browser_params.prefs:
        logger.warning(
            "BROWSER %i: BrowserParams.prefs is a Firefox leftover and is "
            "ignored on Chromium. Pass extra Chromium flags via "
            "BrowserParams.launch_args." % browser_params.browser_id
        )

    status_queue.put(("STATUS", "Launch Attempted", None))

    args = launch_args(browser_params)
    extra_headers = None
    if browser_params.donottrack:
        extra_headers = {"DNT": "1"}

    launch_kwargs: Dict[str, Any] = {
        "user_data_dir": str(browser_profile_path),
        "headless": display_mode == "headless",
        "args": args,
        "viewport": {
            "width": DEFAULT_VIEWPORT["width"],
            "height": DEFAULT_VIEWPORT["height"],
        },
        "chromium_sandbox": not needs_no_sandbox(),
        "accept_downloads": False,
        "ignore_https_errors": False,
    }
    if extra_headers:
        launch_kwargs["extra_http_headers"] = extra_headers
    if browser_params.locale:
        launch_kwargs["locale"] = browser_params.locale
    if browser_params.timezone_id:
        launch_kwargs["timezone_id"] = browser_params.timezone_id
    override = os.environ.get("OPENWPM_CHROMIUM_EXECUTABLE")
    if override:
        launch_kwargs["executable_path"] = override

    from playwright.sync_api import sync_playwright

    playwright = sync_playwright().start()
    try:
        context = playwright.chromium.launch_persistent_context(**launch_kwargs)
    except Exception:
        try:
            playwright.stop()
        except Exception:
            pass
        raise

    page = context.pages[0] if context.pages else context.new_page()
    page.set_viewport_size(
        {"width": DEFAULT_VIEWPORT["width"], "height": DEFAULT_VIEWPORT["height"]}
    )

    browser_pid = None
    try:
        import psutil

        proc = psutil.Process()
        for child in proc.children(recursive=True):
            name = (child.name() or "").lower()
            if "chrom" in name or "headless_shell" in name:
                browser_pid = child.pid
                break
    except Exception:
        logger.debug(
            "BROWSER %i: Could not resolve Chromium pid" % browser_params.browser_id
        )

    session = BrowserSession(
        playwright=playwright,
        context=context,
        page=page,
        profile_path=browser_profile_path,
        browser_pid=browser_pid,
    )
    status_queue.put(("STATUS", "Browser Launched", int(browser_pid or 0)))
    logger.debug(
        "BROWSER %i: Playwright Chromium launched (pid=%s)"
        % (browser_params.browser_id, browser_pid)
    )
    return session, browser_profile_path, display
