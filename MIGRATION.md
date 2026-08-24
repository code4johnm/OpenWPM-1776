# Migrating custom commands to Playwright Chromium

OpenWPM now drives **Playwright's bundled Chromium** (Playwright 1.62.0,
Chromium 151.0.7922.34). Selenium, geckodriver, and the Firefox WebExtension
are gone.

## Command `execute()` signature

The four arguments are the same names as before:

```python
def execute(self, webdriver, browser_params, manager_params, extension_socket):
    ...
```

Types changed:

| Argument | Was | Now |
|---|---|---|
| `webdriver` | `selenium.webdriver.Firefox` | `openwpm.browser.BrowserSession` |
| `extension_socket` | socket to the Firefox extension | `openwpm.instrumentation.controller.MeasurementController` |

`BrowserSession` still provides `current_url`, `get()`, `find_elements()`,
`execute_script()`, `page_source`, `save_screenshot()`, `back()`, and
`quit()`. Raw Playwright objects are on `webdriver.page` and
`webdriver.context`.

Locator helper:

```python
from openwpm.browser import By  # not selenium.webdriver.common.by
```

`Initialize` / `Finalize` still call `extension_socket.send({...})`.

## Config

- `BrowserParams.browser` default is `"chromium"` (`"firefox"` is rejected).
- `BrowserParams.prefs` is ignored. Extra Chromium flags go in
  `BrowserParams.launch_args`.
- `FIREFOX_BINARY` is gone. Override the binary with
  `OPENWPM_CHROMIUM_EXECUTABLE` only for tests or a local Chrome for Testing
  build. Production crawls should use Playwright's pinned Chromium.
- Profiles are Chromium `user-data-dir` trees (`Default/Preferences`,
  `Default/Cookies`, `Default/History`), not Firefox `cookies.sqlite` /
  `places.sqlite`.

## Instruments

HTTP, cookies, navigation, DNS, and JS still write the same tables. Capture
is Playwright request events + CDP, plus a page-world JS inject script
(`openwpm/instrumentation/js_inject.js`). Firefox-only fields
(`oscpu`, `buildID`, TRR DNS, `about:config` prefs) are not populated.

`callstack_instrument` remains disabled.

## Headless

CI and servers: `display_mode="headless"` (default for tests). Headed:
`native` or `xvfb`. `--no-sandbox` is added only in CI, as root, or in
containers (`OPENWPM_NO_SANDBOX=1`).

## Smoke

```bash
python -m openwpm.smoke
```
