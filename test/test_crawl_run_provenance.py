"""Crawl-run provenance and main-document 403/429/503 outcome.

Both tables are off by default. Enabling either flag must not turn on
http_instrument or cookie_instrument.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional, Tuple

import pytest

from openwpm.config import BrowserParams, ManagerParams
from openwpm.errors import ConfigError
from openwpm.instrumentation.controller import _headers_json
from openwpm.instrumentation.provenance import (
    OUTCOME_BY_STATUS,
    build_crawl_outcome_record,
    build_provenance_record,
    headed_from_display_mode,
    outcome_for_status,
    playwright_version,
)
from openwpm.utilities import db_utils

from . import utilities
from .openwpmtest import OpenWPMTest


def test_headers_json_preserves_wire_case_pairs():
    raw = _headers_json(
        [
            {"name": "Content-Type", "value": "text/plain"},
            {"name": "Content-Length", "value": "4"},
        ]
    )
    assert "Content-Type" in raw
    assert "Content-Length" in raw
    parsed = json.loads(raw)
    names = []
    for header, value in parsed:
        names.append(header)
        assert isinstance(value, str)
    assert names == ["Content-Type", "Content-Length"]
    # Must not rewrite to the Playwright headers-dict lowercase form.
    assert raw != json.dumps([{"name": "content-type", "value": "text/plain"}])


def test_playwright_version_is_live():
    import playwright

    assert playwright_version() == playwright.__version__
    assert playwright.__version__


def test_http_status_constants_and_mapping():
    assert OUTCOME_BY_STATUS[403] == "forbidden"
    assert OUTCOME_BY_STATUS[429] == "rate_limited"
    assert OUTCOME_BY_STATUS[503] == "unavailable"
    assert outcome_for_status(200) is None
    assert outcome_for_status(None) is None
    assert outcome_for_status(301) is None
    assert outcome_for_status(302) is None
    assert build_crawl_outcome_record(visit_id=1, browser_id=2, http_status=200) is None
    assert build_crawl_outcome_record(visit_id=1, browser_id=2, http_status=301) is None
    row = build_crawl_outcome_record(visit_id=1, browser_id=2, http_status=429)
    assert row == {
        "visit_id": 1,
        "browser_id": 2,
        "http_status": 429,
        "outcome": "rate_limited",
        "resource_scope": "document",
    }


def test_headed_matches_display_mode():
    assert headed_from_display_mode("headless") is False
    assert headed_from_display_mode("native") is True
    assert headed_from_display_mode("xvfb") is True


def test_provenance_serializer_uses_live_playwright():
    record = build_provenance_record(
        browser_id=7,
        display_mode="headless",
        user_agent="Mozilla/5.0 TestUA",
    )
    assert record["browser_engine"] == "chromium"
    assert record["headed"] == 0
    import playwright

    assert record["playwright_version"] == playwright.__version__
    assert record["user_agent"] == "Mozilla/5.0 TestUA"


class TestProvenanceAndOutcome(OpenWPMTest):
    def get_config(
        self, data_dir: Optional[Path] = None
    ) -> Tuple[ManagerParams, List[BrowserParams]]:
        manager_params, browser_params = self.get_test_config(data_dir)
        browser_params[0].cookie_instrument = False
        browser_params[0].http_instrument = False
        browser_params[0].js_instrument = False
        return manager_params, browser_params

    def test_default_off_writes_zero_rows(self):
        db = self.visit("/simple_a.html")
        assert (
            db_utils.query_db(db, "SELECT COUNT(*) FROM crawl_run_provenance")[0][0]
            == 0
        )
        assert db_utils.query_db(db, "SELECT COUNT(*) FROM crawl_outcome")[0][0] == 0

    def _visit_with(self, path: str, **flags: object) -> object:
        original = self.get_config

        def patched(
            data_dir: Optional[Path] = None,
        ) -> Tuple[ManagerParams, List[BrowserParams]]:
            manager_params, browser_params = original(data_dir)
            for key, value in flags.items():
                setattr(browser_params[0], key, value)
            return manager_params, browser_params

        self.get_config = patched  # type: ignore[method-assign]
        try:
            return self.visit(path)
        finally:
            self.get_config = original  # type: ignore[method-assign]

    def test_provenance_enabled_matches_live_playwright(self):
        db = self._visit_with(
            "/simple_a.html",
            record_provenance=True,
            cookie_instrument=False,
            http_instrument=False,
        )
        rows = db_utils.query_db(db, "SELECT * FROM crawl_run_provenance")
        assert len(rows) == 1
        row = rows[0]
        assert row["browser_engine"] == "chromium"
        assert row["display_mode"] == "headless"
        assert row["headed"] in (0, False)
        import playwright

        assert row["playwright_version"] == playwright.__version__
        assert "Chrome" in row["user_agent"] or "Chromium" in row["user_agent"]
        assert (
            db_utils.query_db(db, "SELECT COUNT(*) FROM javascript_cookies")[0][0] == 0
        )
        assert db_utils.query_db(db, "SELECT COUNT(*) FROM http_requests")[0][0] == 0

    def test_http_200_writes_zero_outcome_rows(self):
        db = self._visit_with(
            "/simple_a.html",
            record_crawl_outcome="status_codes_only",
            cookie_instrument=False,
            http_instrument=False,
        )
        assert db_utils.query_db(db, "SELECT COUNT(*) FROM crawl_outcome")[0][0] == 0
        assert db_utils.query_db(db, "SELECT COUNT(*) FROM http_requests")[0][0] == 0
        assert (
            db_utils.query_db(db, "SELECT COUNT(*) FROM javascript_cookies")[0][0] == 0
        )

    @pytest.mark.parametrize(
        "status,outcome",
        [(403, "forbidden"), (429, "rate_limited"), (503, "unavailable")],
    )
    def test_blocking_status_writes_outcome(self, status, outcome):
        db = self._visit_with(
            f"{utilities.BASE_TEST_URL_NOPATH}/MAGIC_STATUS/{status}",
            record_crawl_outcome="status_codes_only",
            cookie_instrument=False,
            http_instrument=False,
        )
        rows = db_utils.query_db(db, "SELECT * FROM crawl_outcome")
        assert len(rows) == 1
        assert rows[0]["http_status"] == status
        assert rows[0]["outcome"] == outcome
        assert rows[0]["resource_scope"] == "document"
        assert db_utils.query_db(db, "SELECT COUNT(*) FROM http_requests")[0][0] == 0

    def test_redirect_stores_final_document_status(self):
        db = self._visit_with(
            f"{utilities.BASE_TEST_URL_NOPATH}/MAGIC_REDIRECT/bounce"
            "?dst=/MAGIC_STATUS/403",
            record_crawl_outcome="status_codes_only",
            cookie_instrument=False,
            http_instrument=False,
        )
        rows = db_utils.query_db(db, "SELECT http_status, outcome FROM crawl_outcome")
        assert len(rows) == 1
        assert rows[0]["http_status"] == 403
        assert rows[0]["outcome"] == "forbidden"


def test_record_crawl_outcome_true_is_config_error():
    params = BrowserParams()
    params.record_crawl_outcome = True
    from openwpm.config import validate_browser_params

    with pytest.raises(ConfigError):
        validate_browser_params(params)
