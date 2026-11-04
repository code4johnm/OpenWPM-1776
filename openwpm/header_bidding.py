"""Header-bidding measurement for an OpenWPM-1776 visit.

Pages that expose Prebid.js are read through pbjs.getBidResponses(). Pages
that do not are recorded as absent. Profile definitions live in hb_profiles
so the Alpine dashboard can load them without OpenWPM's browser dependencies.
"""

from __future__ import annotations

import json
import time
from typing import Any

from openwpm.commands.types import BaseCommand
from openwpm.hb_profiles import (  # noqa: F401
    PROFILES,
    apply_profile,
    compare_profiles,
    dataset_csv,
    dataset_document,
    profile_config,
    run_profile_auction,
)

PBJS_SCRIPT = """
var output = [];
if (typeof pbjs === 'undefined' || !pbjs.getBidResponses) {
  return output;
}
var responses = pbjs.getBidResponses();
var winners = (pbjs.getAllWinningBids && pbjs.getAllWinningBids()) || [];
Object.keys(responses).forEach(function (adUnitCode) {
  var response = responses[adUnitCode] || {};
  (response.bids || []).forEach(function (bid) {
    output.push({
      adunit: adUnitCode,
      adId: bid.adId,
      bidder: bid.bidder,
      time: bid.timeToRespond,
      cpm: bid.cpm,
      msg: bid.statusMessage,
      rendered: !!winners.find(function (winner) { return winner.adId == bid.adId; })
    });
  });
});
return output;
"""

CONSENT_SCRIPT = """
var wanted = args[0];
var nodes = document.querySelectorAll('button, [role="button"]');
var seen = nodes.length > 0 && /consent|cookie|privacy/i.test(document.body ? document.body.innerText.slice(0, 2000) : '');
var clicked = false;
for (var i = 0; i < nodes.length; i++) {
  var text = (nodes[i].innerText || '').toLowerCase();
  if (wanted === 'reject' && /reject|decline|deny/.test(text)) { nodes[i].click(); clicked = true; break; }
  if (wanted === 'accept' && /accept|agree|allow/.test(text)) { nodes[i].click(); clicked = true; break; }
}
return {seen: seen, clicked: clicked, mode: wanted};
"""


class HeaderBiddingCommand(BaseCommand):
    """Read Prebid results after a visit. Does not invent bids when Prebid is absent."""

    def __init__(self, profile: dict, output_path: str) -> None:
        self.profile = profile
        self.output_path = output_path

    def execute(
        self,
        webdriver: Any,
        browser_params: Any,
        manager_params: Any,
        extension_socket: Any,
    ) -> None:
        started = time.perf_counter()
        consent = {"seen": False, "clicked": False, "mode": self.profile.get("consent")}
        injected = False
        error = ""
        records: list = []
        try:
            script = self.profile.get("inject_script") or ""
            if script:
                webdriver.execute_script(script)
                injected = True
            if self.profile.get("consent") in {"accept", "reject"}:
                consent = (
                    webdriver.execute_script(CONSENT_SCRIPT, self.profile["consent"])
                    or consent
                )
            raw = webdriver.execute_script(PBJS_SCRIPT)
            if isinstance(raw, list):
                records = raw
        except Exception as exc:  # noqa: BLE001 — one visit must not stop the crawl
            error = str(exc)
        elapsed = (time.perf_counter() - started) * 1000.0
        row = {
            "visit_id": getattr(self, "visit_id", None),
            "profile": self.profile.get("name"),
            "source": "page" if records else "absent",
            "consent": consent,
            "injected": injected,
            "fingerprint_resistance": bool(self.profile.get("fingerprint_resistance")),
            "cookie_state": self.profile.get("cookie_state"),
            "elapsed_ms": round(elapsed, 3),
            "error": error,
            "error_rate": 1.0 if error else 0.0,
            "records": records,
        }
        with open(self.output_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(row) + "\n")
