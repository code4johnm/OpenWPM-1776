"""Header bidding inside an OpenWPM command, without launching Chromium."""

from __future__ import annotations

import json
from typing import Any, Optional

from openwpm.config import BrowserParams
from openwpm.header_bidding import (
    HeaderBiddingCommand,
    apply_profile,
    compare_profiles,
    dataset_csv,
    dataset_document,
)


class FakeDriver:
    def __init__(self, bids: Optional[list] = None, fail: bool = False) -> None:
        self.bids = bids or []
        self.fail = fail
        self.scripts: list = []

    def execute_script(self, script: str, *args: Any) -> Any:
        self.scripts.append(script)
        if self.fail:
            raise RuntimeError("page closed")
        if "pbjs" in script:
            return self.bids
        if "wanted" in script or "arguments" in script:
            return {"seen": True, "clicked": True, "mode": args[0] if args else ""}
        return None


def test_profiles_change_browser_cookie_and_fingerprint_state() -> None:
    training = BrowserParams()
    apply_profile(training, {"profile": "training"})
    assert training.tp_cookies == "never"
    assert training.timezone_id == "America/Detroit"

    testing = BrowserParams()
    apply_profile(testing, {"profile": "testing", "viewport": "320x480"})
    assert testing.prefs["openwpm.fingerprint_resistance"] is True
    assert testing.tp_cookies == "never"
    assert "--window-size=320,480" in testing.launch_args

    baseline = BrowserParams()
    apply_profile(baseline, {"profile": "baseline"})
    assert baseline.tp_cookies == "always"
    assert baseline.prefs["openwpm.cookie_state"] == "preserved"


def test_command_records_page_bids_consent_and_errors(tmp_path: Any) -> None:
    path = tmp_path / "hb-events.jsonl"
    profile = apply_profile(BrowserParams(), {"profile": "baseline"})
    command = HeaderBiddingCommand(profile, str(path))
    command.visit_id = 7
    bids = [
        {
            "adId": "1",
            "bidder": "rubicon",
            "cpm": 1.2,
            "rendered": True,
            "time": 40,
            "msg": "Bid available",
            "adunit": "/a",
        }
    ]
    command.execute(FakeDriver(bids), None, None, None)
    row = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert row["source"] == "page"
    assert row["records"][0]["bidder"] == "rubicon"
    assert row["consent"]["clicked"] is True
    assert row["error_rate"] == 0.0
    assert row["elapsed_ms"] >= 0

    command.execute(FakeDriver(fail=True), None, None, None)
    failed = json.loads(path.read_text(encoding="utf-8").splitlines()[1])
    assert failed["error_rate"] == 1.0
    assert failed["source"] == "absent"
    assert "page closed" in failed["error"]


def test_labeled_dataset_differs_by_profile_and_exports_csv() -> None:
    summary = compare_profiles()
    by_name = {row["profile"]: row for row in summary}
    assert by_name["training"]["winner"] == "rubicon"
    assert by_name["testing"]["winner"] is None
    assert by_name["testing"]["error_rate"] > 0
    assert by_name["baseline"]["winner"] == "appnexus"
    document = dataset_document()
    kinds = {event["kind"] for event in document["rows"][0]["events"]}
    assert {
        "bid_request",
        "adapter_response",
        "auction_cleared",
        "win_notice",
        "impression",
    } <= kinds
    csv_text = dataset_csv(document)
    assert "profile,label,winner" in csv_text
    assert "testing" in csv_text
