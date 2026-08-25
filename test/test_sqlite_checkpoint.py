"""WAL checkpoint for Chromium History. No browser required."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from openwpm.commands.utils.firefox_profile import (
    checkpoint_chromium_sqlite,
    materialize_chromium_history,
)

pytestmark = pytest.mark.pyonly


def test_checkpoint_merges_history_wal(tmp_path: Path) -> None:
    default = tmp_path / "Default"
    default.mkdir()
    history = default / "History"
    con = sqlite3.connect(history)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE urls (id INTEGER PRIMARY KEY, url TEXT)")
    con.execute("INSERT INTO urls (url) VALUES ('http://example.com/')")
    con.commit()
    con.close()

    checkpoint_chromium_sqlite(tmp_path)

    con = sqlite3.connect(history)
    rows = list(con.execute("SELECT url FROM urls"))
    con.close()
    assert rows == [("http://example.com/",)]
    wal = Path(str(history) + "-wal")
    assert (not wal.exists()) or wal.stat().st_size == 0


def test_materialize_history_copies_urls_table(tmp_path: Path) -> None:
    default = tmp_path / "Default"
    default.mkdir()
    history = default / "History"
    con = sqlite3.connect(history)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE urls (id INTEGER PRIMARY KEY, url TEXT)")
    con.execute("INSERT INTO urls (url) VALUES ('http://example.com/')")
    con.commit()
    con.close()

    materialize_chromium_history(tmp_path)

    dest = tmp_path / "Default" / "History"
    con = sqlite3.connect(dest)
    rows = list(con.execute("SELECT url FROM urls"))
    con.close()
    assert rows == [("http://example.com/",)]
