"""Visit the dashboard link list once and write crawl-data.sqlite.

Reads datadir/crawl-links.json and datadir/crawl-settings.json.
Callstack instrumentation stays off. It cannot start in this tree.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from openwpm.command_sequence import CommandSequence
from openwpm.commands.browser_commands import GetCommand
from openwpm.config import BrowserParams, ManagerParams
from openwpm.header_bidding import HeaderBiddingCommand, apply_profile
from openwpm.storage.sql_provider import SQLiteStorageProvider
from openwpm.task_manager import TaskManager

ROOT = Path(os.environ.get("OPENWPM_ROOT", "/opt/OpenWPM"))
DATA = Path(os.environ.get("OPENWPM_DATADIR", str(ROOT / "datadir")))
LINKS = Path(os.environ.get("OPENWPM_LINKS", str(DATA / "crawl-links.json")))
SETTINGS = Path(os.environ.get("OPENWPM_SETTINGS", str(DATA / "crawl-settings.json")))
STATUS = DATA / "crawl-status.json"


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_json(path: Path, fallback: dict) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback
    return data if isinstance(data, dict) else fallback


def write_status(payload: dict) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    tmp = STATUS.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o666)
    tmp.replace(STATUS)


def urls_from(doc: dict) -> list[str]:
    found: list[str] = []
    for item in doc.get("links") or []:
        if isinstance(item, str):
            url = item.strip()
        elif isinstance(item, dict):
            url = str(item.get("url") or "").strip()
        else:
            continue
        if url.startswith("https://") or url.startswith("http://"):
            found.append(url)
    return found


def main() -> int:
    DATA.mkdir(parents=True, exist_ok=True)
    os.chmod(DATA, 0o777)
    settings = load_json(
        SETTINGS,
        {"dwell": 3, "timeout": 60, "headless": True, "http": True, "cookie": True, "navigation": True, "js": True, "dns": True},
    )
    links = urls_from(load_json(LINKS, {"links": []}))
    dwell = max(0, min(120, int(settings.get("dwell") or 3)))
    timeout = max(5, min(180, int(settings.get("timeout") or 60)))
    headless = bool(settings.get("headless", True))
    rows = [{"url": url, "ok": None, "detail": "queued"} for url in links]
    status = {"state": "running", "started": now(), "finished": "", "sites": rows, "error": ""}
    write_status(status)
    if not links:
        status["state"] = "error"
        status["finished"] = now()
        status["error"] = "The crawl list is empty."
        write_status(status)
        return 1

    manager_params = ManagerParams(num_browsers=1)
    manager_params.data_directory = DATA
    manager_params.log_path = DATA / "openwpm.log"
    browser = BrowserParams(display_mode="headless" if headless else "xvfb")
    browser.http_instrument = bool(settings.get("http", True))
    browser.cookie_instrument = bool(settings.get("cookie", True))
    browser.navigation_instrument = bool(settings.get("navigation", True))
    browser.js_instrument = bool(settings.get("js", True))
    browser.dns_instrument = bool(settings.get("dns", True))
    browser.callstack_instrument = False
    profile = apply_profile(browser, settings)
    hb_log = DATA / "hb-events.jsonl"
    try:
        with TaskManager(
            manager_params,
            [browser],
            SQLiteStorageProvider(DATA / "crawl-data.sqlite"),
            None,
        ) as manager:
            for index, site in enumerate(links):
                outcome = {"ok": False, "detail": "not run"}

                def callback(success: bool, val: str = site, box: dict = outcome) -> None:
                    box["ok"] = bool(success)
                    box["detail"] = "visited" if success else "visit failed"

                sequence = CommandSequence(site, site_rank=index, callback=callback)
                sequence.append_command(GetCommand(url=site, sleep=dwell), timeout=timeout)
                sequence.append_command(
                    HeaderBiddingCommand(profile, str(hb_log)),
                    timeout=timeout,
                )
                manager.execute_command_sequence(sequence)
                rows[index]["ok"] = outcome["ok"]
                rows[index]["detail"] = outcome["detail"]
                write_status(status)
    except Exception as exc:  # noqa: BLE001 — record the crawl failure for the dashboard
        status["state"] = "error"
        status["finished"] = now()
        status["error"] = str(exc)
        write_status(status)
        raise
    status["state"] = "finished"
    status["finished"] = now()
    write_status(status)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
