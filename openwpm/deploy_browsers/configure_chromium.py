"""Chromium launch flags for measurement.

Playwright already applies a modern default set. This module only adds
flags that change measurement behaviour, plus container/CI workarounds
that are documented inline.

No stealth / automation-hiding patches. ``navigator.webdriver`` remains
true. If a site gates on that bit, document the limitation rather than
shipping CDP cloaking.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List

from ..config import BrowserParamsInternal

# Viewport used for both the window and Playwright context.
DEFAULT_SCREEN_RES = (1366, 768)


def running_in_container() -> bool:
    if Path("/.dockerenv").exists():
        return True
    return os.environ.get("OPENWPM_DISABLE_DEV_SHM", "") == "1"


def needs_no_sandbox() -> bool:
    """--no-sandbox is required in many CI images and when running as root.

    Chromium's SUID sandbox cannot be created in unprivileged containers
    or as uid 0. We only add the flag in those environments.
    """
    if os.environ.get("CI"):
        return True
    if os.environ.get("OPENWPM_NO_SANDBOX") == "1":
        return True
    try:
        if os.geteuid() == 0:
            return True
    except AttributeError:
        pass
    return running_in_container()


def launch_args(browser_params: BrowserParamsInternal) -> List[str]:
    args: List[str] = [
        f"--window-size={DEFAULT_SCREEN_RES[0]},{DEFAULT_SCREEN_RES[1]}",
        # Reduce background chatter that is not part of the page under test.
        "--disable-background-networking",
        "--disable-component-update",
        "--disable-sync",
        "--disable-default-apps",
        "--disable-hang-monitor",
        "--disable-popup-blocking",
        "--disable-prompt-on-repost",
        "--metrics-recording-only",
        "--no-first-run",
        "--password-store=basic",
        "--use-mock-keychain",
    ]

    # Chrome's third-party cookie phaseout would silently change cookie
    # measurement versus a "cookies always allowed" crawl. Disable it
    # unless the operator asked to block third-party cookies.
    tp = (browser_params.tp_cookies or "always").lower()
    if tp == "never":
        args.append("--block-third-party-cookies")
    else:
        args.append("--disable-features=TrackingProtection3pcd")
        if tp == "from_visited":
            # Chromium has no Firefox-style "visited" cookieBehaviour.
            # Documented fallback: treat as always-allow.
            pass

    if running_in_container():
        # Avoid /dev/shm exhaustion that crashes Chromium in Docker.
        args.append("--disable-dev-shm-usage")

    args.extend(browser_params.launch_args)
    return args
