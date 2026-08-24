"""Interactive Playwright Chromium session for local debugging.

    python -m test.manual_test
    python -m test.manual_test --headed
"""

from os.path import dirname, join, realpath

import click
import IPython
from playwright.sync_api import sync_playwright

from openwpm.browser_bin import chromium_executable, ensure_browsers_path

from .utilities import BASE_TEST_URL, start_server

BASE_DIR = dirname(dirname(realpath(__file__)))


@click.command()
@click.option("--headed", is_flag=True, help="Show the browser window")
def main(headed: bool) -> None:
    ensure_browsers_path()
    chromium_executable()
    server, server_thread = start_server()
    playwright = sync_playwright().start()
    browser = playwright.chromium.launch(headless=not headed)
    context = browser.new_context()
    page = context.new_page()
    page.goto(BASE_TEST_URL + "/simple_a.html")
    print(f"Test server: {BASE_TEST_URL}")
    print("Objects: page, context, browser, playwright")
    try:
        IPython.embed()
    finally:
        context.close()
        browser.close()
        playwright.stop()
        server.shutdown()
        server_thread.join()


if __name__ == "__main__":
    main()
