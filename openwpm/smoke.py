"""Smoke crawl: fail if Chromium is missing, open example.com, capture artifacts.

Usage:
    python -m openwpm.smoke
    python -m openwpm.smoke --headed
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from openwpm.browser_bin import (
    chromium_executable,
    chromium_version,
    ensure_browsers_path,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="OpenWPM Chromium smoke crawl")
    parser.add_argument(
        "--headed", action="store_true", help="Run headed (default is headless)"
    )
    parser.add_argument(
        "--url", default="https://example.com", help="URL to open (default example.com)"
    )
    parser.add_argument(
        "--outdir",
        default=Path("datadir"),
        type=Path,
        help="Directory for screenshot + HAR",
    )
    args = parser.parse_args(argv)

    ensure_browsers_path()
    exe = chromium_executable()
    version = chromium_version()
    print(f"Chromium binary: {exe}")
    print(f"Chromium version: {version}")

    args.outdir.mkdir(parents=True, exist_ok=True)
    screenshot = args.outdir / "smoke.png"
    har_path = args.outdir / "smoke.har"

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headed)
        context = browser.new_context(record_har_path=str(har_path))
        page = context.new_page()
        page.goto(args.url, wait_until="domcontentloaded")
        title = page.title()
        print(f"Title: {title}")
        if (
            "example" not in title.lower()
            and args.url.rstrip("/") == "https://example.com"
        ):
            print("ERROR: expected Example Domain title", file=sys.stderr)
            context.close()
            browser.close()
            return 1
        page.screenshot(path=str(screenshot))
        context.close()
        browser.close()

    if not screenshot.is_file():
        print("ERROR: screenshot was not written", file=sys.stderr)
        return 1
    if not har_path.is_file():
        print("ERROR: HAR was not written", file=sys.stderr)
        return 1
    try:
        har = json.loads(har_path.read_text())
        entries = har.get("log", {}).get("entries", [])
        print(f"HAR entries: {len(entries)}")
    except json.JSONDecodeError:
        print("ERROR: HAR is not valid JSON", file=sys.stderr)
        return 1

    print(f"Screenshot: {screenshot}")
    print(f"HAR: {har_path}")
    print("Smoke crawl OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
