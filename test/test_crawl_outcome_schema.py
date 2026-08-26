"""SQLite constraints for crawl_outcome. No browser required."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

pytestmark = pytest.mark.pyonly

SCHEMA = Path(__file__).resolve().parents[1] / "openwpm" / "storage" / "schema.sql"


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.executescript(SCHEMA.read_text())
    return conn


def test_schema_binds_status_outcome_pairs():
    conn = _db()
    conn.execute(
        "INSERT INTO crawl_outcome VALUES (1, 2, 403, 'forbidden', 'document')"
    )
    conn.execute(
        "INSERT INTO crawl_outcome VALUES (2, 2, 429, 'rate_limited', 'document')"
    )
    conn.execute(
        "INSERT INTO crawl_outcome VALUES (3, 2, 503, 'unavailable', 'document')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO crawl_outcome VALUES (4, 2, 403, 'rate_limited', 'document')"
        )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO crawl_outcome VALUES (5, 2, 200, 'forbidden', 'document')"
        )
    conn.close()


def test_schema_replaces_last_document_status_on_retry():
    conn = _db()
    conn.execute(
        "INSERT INTO crawl_outcome VALUES (9, 1, 403, 'forbidden', 'document')"
    )
    conn.execute(
        "INSERT OR REPLACE INTO crawl_outcome VALUES (9, 1, 429, 'rate_limited', 'document')"
    )
    row = conn.execute(
        "SELECT http_status, outcome FROM crawl_outcome WHERE visit_id = 9"
    ).fetchone()
    assert row == (429, "rate_limited")
    assert conn.execute("SELECT COUNT(*) FROM crawl_outcome").fetchone()[0] == 1
    conn.close()
