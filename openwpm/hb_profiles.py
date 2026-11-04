"""Training, testing, and baseline profiles for the crawl dashboard.

This module stays on the standard library. The dashboard container is
python:3.12-alpine and cannot import OpenWPM's browser stack.
"""

from __future__ import annotations

import csv
import io
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

PROFILES = {
    "training": {
        "label": "Training",
        "purpose": "Diverse labeled visits for model development.",
        "user_agent": "Mozilla/5.0 (training-profile; OpenWPM-1776) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
        "viewport": "1366x768",
        "geolocation": "America/Detroit",
        "cookie_state": "empty",
        "inject_script": "",
        "consent": "reject",
        "fingerprint_resistance": False,
    },
    "testing": {
        "label": "Testing",
        "purpose": "Edge cases, adversarial inputs, and regressions.",
        "user_agent": "Mozilla/5.0 (testing-profile; adversarial) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
        "viewport": "320x480",
        "geolocation": "UTC",
        "cookie_state": "blocked",
        "inject_script": "window.__hbAdversarial = true;",
        "consent": "absent",
        "fingerprint_resistance": True,
    },
    "baseline": {
        "label": "Baseline",
        "purpose": "Ordinary desktop browsing.",
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "viewport": "1920x1080",
        "geolocation": "America/New_York",
        "cookie_state": "preserved",
        "inject_script": "",
        "consent": "accept",
        "fingerprint_resistance": False,
    },
}


@dataclass
class Bid:
    bidder: str
    ad_id: str
    cpm: float
    time_to_respond_ms: int
    status: str
    message: str = ""


def profile_config(name: str, overrides: Optional[dict] = None) -> dict:
    if name not in PROFILES:
        raise ValueError("profile must be training, testing, or baseline")
    config = dict(PROFILES[name])
    config["name"] = name
    for key in (
        "user_agent",
        "viewport",
        "geolocation",
        "cookie_state",
        "inject_script",
        "consent",
    ):
        if overrides and overrides.get(key) not in (None, ""):
            config[key] = overrides[key]
    if overrides and "fingerprint_resistance" in overrides:
        config["fingerprint_resistance"] = bool(overrides["fingerprint_resistance"])
    width, height = _viewport(config["viewport"])
    config["viewport_width"] = width
    config["viewport_height"] = height
    return config


def _viewport(value: str) -> tuple[int, int]:
    parts = str(value).lower().split("x")
    if len(parts) != 2:
        raise ValueError("viewport must look like 1366x768")
    width, height = int(parts[0]), int(parts[1])
    if not (200 <= width <= 3840 and 200 <= height <= 2160):
        raise ValueError("viewport is out of range")
    return width, height


def apply_profile(browser: Any, settings: dict) -> dict:
    """Copy a dashboard profile onto an OpenWPM BrowserParams object."""
    overrides = {
        "user_agent": settings.get("user_agent"),
        "viewport": settings.get("viewport"),
        "geolocation": settings.get("geolocation"),
        "cookie_state": settings.get("cookie_state"),
        "inject_script": settings.get("inject_script"),
        "consent": settings.get("consent"),
    }
    if settings.get("fingerprint_resistance") is not None:
        overrides["fingerprint_resistance"] = settings.get("fingerprint_resistance")
    config = profile_config(str(settings.get("profile") or "baseline"), overrides)
    cookies = config["cookie_state"]
    if cookies not in {"empty", "blocked", "preserved"}:
        raise ValueError("cookie_state must be empty, blocked, or preserved")
    browser.tp_cookies = "always" if cookies == "preserved" else "never"
    browser.timezone_id = (
        config["geolocation"] if config["geolocation"] != "UTC" else "UTC"
    )
    browser.locale = "en-US"
    prefs = dict(getattr(browser, "prefs", {}) or {})
    prefs["general.useragent.override"] = config["user_agent"]
    prefs["openwpm.fingerprint_resistance"] = bool(config["fingerprint_resistance"])
    prefs["openwpm.cookie_state"] = cookies
    browser.prefs = prefs
    size = "--window-size={0},{1}".format(
        config["viewport_width"], config["viewport_height"]
    )
    args = list(getattr(browser, "launch_args", []) or [])
    if size not in args:
        args.append(size)
    browser.launch_args = args
    return config


def _adapters(profile_name: str) -> list[tuple[str, Callable[[], Bid]]]:
    if profile_name == "testing":
        return [
            ("slow", lambda: (_ for _ in ()).throw(TimeoutError("bidder timeout"))),
            ("broken", lambda: (_ for _ in ()).throw(RuntimeError("adapter error"))),
            ("floor", lambda: Bid("floor", "floor-1", 0.05, 12, "bid")),
        ]
    if profile_name == "training":
        return [
            ("appnexus", lambda: Bid("appnexus", "apn", 0.90, 30, "bid")),
            ("rubicon", lambda: Bid("rubicon", "rub", 1.40, 48, "bid")),
            ("ix", lambda: Bid("ix", "ix", 1.10, 70, "bid")),
            ("pubmatic", lambda: Bid("pubmatic", "pub", 0.0, 20, "no-bid")),
        ]
    return [
        ("appnexus", lambda: Bid("appnexus", "apn", 1.25, 35, "bid")),
        ("rubicon", lambda: Bid("rubicon", "rub", 1.05, 42, "bid")),
    ]


def run_profile_auction(
    profile_name: str, timeout_ms: int = 100, floor_cpm: float = 0.10
) -> dict:
    """Labeled auction for one profile. Does not contact a publisher."""
    started = time.perf_counter()
    responses = []
    for name, factory in _adapters(profile_name):
        try:
            bid = factory()
        except TimeoutError as exc:
            bid = Bid(name, "", 0.0, timeout_ms, "timeout", str(exc))
        except Exception as exc:
            bid = Bid(name, "", 0.0, 0, "error", str(exc))
        if bid.time_to_respond_ms > timeout_ms and bid.status == "bid":
            bid = Bid(
                bid.bidder,
                bid.ad_id,
                0.0,
                bid.time_to_respond_ms,
                "timeout",
                "exceeded bidder timeout",
            )
        responses.append(bid)
    eligible = [
        bid for bid in responses if bid.status == "bid" and bid.cpm >= floor_cpm
    ]
    eligible.sort(key=lambda bid: (-bid.cpm, bid.time_to_respond_ms, bid.bidder))
    winner = eligible[0] if eligible else None
    elapsed = (time.perf_counter() - started) * 1000.0
    bad = sum(1 for bid in responses if bid.status in {"timeout", "error"})
    events = [
        {"kind": "bid_request", "bidder": "*", "detail": {"profile": profile_name}}
    ]
    for bid in responses:
        events.append(
            {
                "kind": "adapter_response",
                "bidder": bid.bidder,
                "detail": {
                    "status": bid.status,
                    "cpm": bid.cpm,
                    "time_to_respond_ms": bid.time_to_respond_ms,
                },
            }
        )
    events.append(
        {
            "kind": "auction_cleared",
            "bidder": winner.bidder if winner else "",
            "detail": {"clearing_cpm": winner.cpm if winner else None},
        }
    )
    if winner:
        events.append(
            {
                "kind": "win_notice",
                "bidder": winner.bidder,
                "detail": {"ad_id": winner.ad_id},
            }
        )
        events.append(
            {
                "kind": "impression",
                "bidder": winner.bidder,
                "detail": {"rendered": True},
            }
        )
    return {
        "profile": profile_name,
        "label": profile_name,
        "winner": winner.bidder if winner else None,
        "clearing_cpm": winner.cpm if winner else None,
        "elapsed_ms": round(elapsed, 3),
        "error_rate": (bad / float(len(responses))) if responses else 0.0,
        "bid_count": len(eligible),
        "responses": [bid.__dict__ for bid in responses],
        "events": events,
    }


def compare_profiles() -> list[dict]:
    rows = []
    for name in ("training", "testing", "baseline"):
        result = run_profile_auction(name)
        rows.append(
            {
                "profile": name,
                "purpose": PROFILES[name]["purpose"],
                "winner": result["winner"],
                "clearing_cpm": result["clearing_cpm"],
                "error_rate": result["error_rate"],
                "elapsed_ms": result["elapsed_ms"],
                "bid_count": result["bid_count"],
                "consent": PROFILES[name]["consent"],
                "cookie_state": PROFILES[name]["cookie_state"],
                "fingerprint_resistance": PROFILES[name]["fingerprint_resistance"],
            }
        )
    return rows


def dataset_document() -> dict:
    return {
        "rows": [
            run_profile_auction(name) for name in ("training", "testing", "baseline")
        ]
    }


def dataset_csv(document: dict) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer,
        fieldnames=[
            "profile",
            "label",
            "winner",
            "clearing_cpm",
            "elapsed_ms",
            "error_rate",
            "bid_count",
        ],
    )
    writer.writeheader()
    for row in document["rows"]:
        writer.writerow({key: row.get(key) for key in writer.fieldnames})
    return buffer.getvalue()
