"""WAL checkpoint for Chromium History. No browser required."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from openwpm.commands.utils.firefox_profile import (
    OPENWPM_HISTORY_SNAPSHOT,
    checkpoint_chromium_sqlite,
    materialize_chromium_history,
    snapshot_chromium_history,
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


def _write_history_with_url(path: Path, url: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE urls (id INTEGER PRIMARY KEY, url TEXT)")
    con.execute("INSERT INTO urls (url) VALUES (?)", (url,))
    con.commit()
    con.close()


def test_snapshot_writes_side_file(tmp_path: Path) -> None:
    _write_history_with_url(tmp_path / "Default" / "History", "http://example.com/")
    snapshot_chromium_history(tmp_path)
    snap = tmp_path / OPENWPM_HISTORY_SNAPSHOT
    con = sqlite3.connect(snap)
    rows = list(con.execute("SELECT url FROM urls"))
    con.close()
    assert rows == [("http://example.com/",)]


def test_materialize_restores_snapshot_when_live_history_empty(tmp_path: Path) -> None:
    _write_history_with_url(
        tmp_path / OPENWPM_HISTORY_SNAPSHOT, "http://example.com/from-snapshot"
    )
    default = tmp_path / "Default"
    default.mkdir()
    empty = default / "History"
    empty.write_bytes(b"")
    materialize_chromium_history(tmp_path)
    con = sqlite3.connect(empty)
    rows = list(con.execute("SELECT url FROM urls"))
    con.close()
    assert rows == [("http://example.com/from-snapshot",)]


def test_materialize_prefers_snapshot_over_empty_urls_table(tmp_path: Path) -> None:
    _write_history_with_url(
        tmp_path / OPENWPM_HISTORY_SNAPSHOT, "http://example.com/kept"
    )
    dest = tmp_path / "Default" / "History"
    dest.parent.mkdir()
    con = sqlite3.connect(dest)
    con.execute("CREATE TABLE urls (id INTEGER PRIMARY KEY, url TEXT)")
    con.commit()
    con.close()
    materialize_chromium_history(tmp_path)
    con = sqlite3.connect(dest)
    rows = list(con.execute("SELECT url FROM urls"))
    con.close()
    assert rows == [("http://example.com/kept",)]
