# This is code adapted from KU Leuven crawler code written by
# Gunes Acar and Marc Juarez

import os
import shutil
import sqlite3
import time
from glob import glob
from pathlib import Path
from typing import Iterable, List, Optional, Union

# Chromium overwrites Default/History on quit. Keep a side copy at the
# profile root so dump can restore a queryable ``urls`` table.
OPENWPM_HISTORY_SNAPSHOT = "openwpm-history.sqlite"

_CHROMIUM_SQLITE_NAMES = frozenset(
    {
        "History",
        "Cookies",
        "Web Data",
        "Favicons",
        "Login Data",
        "Shortcuts",
        "Top Sites",
    }
)


def tmp_sqlite_files_exist(path: Union[str, Path]) -> bool:
    """Check if temporary sqlite files(wal, shm) exist in a given path."""
    root = Path(path)
    for base in (root, root / "Default"):
        if glob(os.path.join(str(base), "*-wal")) or glob(
            os.path.join(str(base), "*-shm")
        ):
            return True
    return False


def checkpoint_chromium_sqlite(profile_dir: Union[str, Path]) -> None:
    """Merge History/Cookies WAL into the main DB after Chromium exits.

    Waiting for ``*-wal`` to disappear is not enough: once the browser
    process is gone nothing checkpoints, and a 0-byte History has no
    ``urls`` table. Force ``PRAGMA wal_checkpoint(TRUNCATE)``.
    """
    root = Path(profile_dir)
    db_paths = set()
    for base in (root, root / "Default"):
        if not base.is_dir():
            continue
        for wal in base.glob("*-wal"):
            db_paths.add(wal.with_name(wal.name[: -len("-wal")]))
        for name in _CHROMIUM_SQLITE_NAMES:
            candidate = base / name
            if candidate.is_file():
                db_paths.add(candidate)
    for db_path in db_paths:
        if not db_path.is_file() or db_path.stat().st_size == 0:
            continue
        try:
            uri = f"file:{db_path.as_posix()}?mode=rw"
            con = sqlite3.connect(uri, uri=True, timeout=5)
            try:
                con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                con.commit()
                leftover_wal = Path(str(db_path) + "-wal")
                if leftover_wal.is_file() and leftover_wal.stat().st_size > 0:
                    bak = Path(str(db_path) + ".openwpm-ckpt")
                    dst = sqlite3.connect(bak)
                    try:
                        con.backup(dst)
                    finally:
                        dst.close()
                    bak.replace(db_path)
            finally:
                con.close()
        except sqlite3.Error:
            continue


def _sqlite_has_urls_table(db_path: Path) -> bool:
    if not db_path.is_file() or db_path.stat().st_size == 0:
        return False
    try:
        con = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True, timeout=5)
        try:
            rows = con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='urls'"
            ).fetchall()
            return bool(rows)
        finally:
            con.close()
    except sqlite3.Error:
        return False


def _sqlite_url_count(db_path: Path) -> int:
    """Number of ``urls`` rows, or 0 if the file is missing/unreadable."""
    if not _sqlite_has_urls_table(db_path):
        return 0
    try:
        con = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True, timeout=5)
        try:
            row = con.execute("SELECT COUNT(*) FROM urls").fetchone()
            return int(row[0]) if row else 0
        finally:
            con.close()
    except (sqlite3.Error, TypeError, ValueError):
        return 0


def _backup_sqlite(src: Path, dest: Path) -> bool:
    try:
        src_con = sqlite3.connect(f"file:{src.as_posix()}?mode=ro", uri=True, timeout=5)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".openwpm-tmp")
        if tmp.exists():
            tmp.unlink()
        dst_con = sqlite3.connect(tmp)
        try:
            src_con.backup(dst_con)
        finally:
            dst_con.close()
            src_con.close()
        tmp.replace(dest)
        for suffix in ("-wal", "-shm"):
            leftover = Path(str(dest) + suffix)
            if leftover.exists():
                leftover.unlink()
        return _sqlite_has_urls_table(dest)
    except sqlite3.Error:
        return False


def _copy_sqlite_with_wal(src: Path, dest: Path) -> bool:
    """Copy db + WAL/SHM then checkpoint, for when the backup API is locked."""
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".openwpm-copy")
        if tmp.exists():
            tmp.unlink()
        shutil.copy2(src, tmp)
        for suffix in ("-wal", "-shm"):
            side = Path(str(src) + suffix)
            tmp_side = Path(str(tmp) + suffix)
            if tmp_side.exists():
                tmp_side.unlink()
            if side.is_file() and side.stat().st_size > 0:
                shutil.copy2(side, tmp_side)
        con = sqlite3.connect(f"file:{tmp.as_posix()}?mode=rw", uri=True, timeout=5)
        try:
            con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            con.commit()
        finally:
            con.close()
        tmp.replace(dest)
        for suffix in ("-wal", "-shm"):
            leftover = Path(str(dest) + suffix)
            if leftover.exists():
                leftover.unlink()
        return _sqlite_url_count(dest) > 0 or _sqlite_has_urls_table(dest)
    except (OSError, sqlite3.Error):
        return False


def _history_candidates(root: Path) -> List[Path]:
    candidates: List[Path] = []
    for base in (root / "Default", root):
        if not base.is_dir():
            continue
        for path in base.glob("History*"):
            if path.is_file() and not str(path).endswith(("-wal", "-shm")):
                candidates.append(path)
        named = base / "History"
        if named.is_file() and named not in candidates:
            candidates.append(named)
    snap = root / OPENWPM_HISTORY_SNAPSHOT
    if snap.is_file() and snap not in candidates:
        candidates.append(snap)
    return candidates


def _replace_history(src: Path, dest: Path) -> bool:
    if src.resolve() == dest.resolve():
        return _sqlite_has_urls_table(dest)
    if _backup_sqlite(src, dest):
        return True
    return _copy_sqlite_with_wal(src, dest)


def snapshot_chromium_history(profile_dir: Union[str, Path]) -> None:
    """Copy a History that has ``urls`` rows to ``openwpm-history.sqlite``.

    Chromium rewrites ``Default/History`` on exit. The snapshot lives at
    the profile root so the browser will not overwrite it.
    """
    root = Path(profile_dir)
    dest = root / OPENWPM_HISTORY_SNAPSHOT
    best: Optional[Path] = None
    best_count = 0
    for src in _history_candidates(root):
        count = _sqlite_url_count(src)
        if count > best_count:
            best = src
            best_count = count
    if best is not None and best_count > 0:
        if best.resolve() != dest.resolve():
            _replace_history(best, dest)
        return
    for src in _history_candidates(root):
        if src.name == OPENWPM_HISTORY_SNAPSHOT:
            continue
        if _replace_history(src, dest) and _sqlite_url_count(dest) > 0:
            return


def merge_visit_urls_into_history(
    profile_dir: Union[str, Path], urls: Iterable[str]
) -> None:
    """Ensure ``openwpm-history.sqlite`` contains each visited URL.

    Playwright Chromium often leaves ``Default/History`` with no ``urls``
    table. The crawl still knows which documents it opened; write those
    into the snapshot Chromium will not overwrite.
    """
    incoming: List[str] = []
    seen = set()
    for raw in urls:
        url = (raw or "").strip()
        if not url or url.startswith(
            ("about:", "chrome:", "devtools:", "data:", "blob:")
        ):
            continue
        if url in seen:
            continue
        seen.add(url)
        incoming.append(url)
    if not incoming:
        return
    root = Path(profile_dir)
    dest = root / OPENWPM_HISTORY_SNAPSHOT
    existing: List[str] = []
    if _sqlite_url_count(dest) > 0:
        try:
            con = sqlite3.connect(
                f"file:{dest.as_posix()}?mode=ro", uri=True, timeout=5
            )
            try:
                existing = [str(row[0]) for row in con.execute("SELECT url FROM urls")]
            finally:
                con.close()
        except sqlite3.Error:
            existing = []
    merged: List[str] = []
    seen_merged = set()
    for url in existing + incoming:
        if url in seen_merged:
            continue
        seen_merged.add(url)
        merged.append(url)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".openwpm-visits")
    if tmp.exists():
        tmp.unlink()
    con = sqlite3.connect(tmp)
    try:
        con.execute("CREATE TABLE urls (id INTEGER PRIMARY KEY, url TEXT UNIQUE)")
        con.executemany(
            "INSERT OR IGNORE INTO urls (url) VALUES (?)", [(url,) for url in merged]
        )
        con.commit()
    finally:
        con.close()
    tmp.replace(dest)


def materialize_chromium_history(profile_dir: Union[str, Path]) -> None:
    """Write a standalone Default/History that has a queryable ``urls`` table.

    After Chromium exits, History may be 0 bytes with data only in WAL, or
    Chromium may replace ``Default/History`` with an empty file. Prefer the
    pre-close ``openwpm-history.sqlite`` snapshot when the live file has no
    visit rows.
    """
    root = Path(profile_dir)
    checkpoint_chromium_sqlite(root)
    snapshot_chromium_history(root)
    dest = root / "Default" / "History"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if _sqlite_url_count(dest) > 0:
        return
    snap = root / OPENWPM_HISTORY_SNAPSHOT
    if _sqlite_url_count(snap) > 0:
        _replace_history(snap, dest)
        return
    for src in _history_candidates(root):
        if src.resolve() == dest.resolve():
            if _sqlite_has_urls_table(src) or _backup_sqlite(src, dest):
                return
            continue
        if _replace_history(src, dest) and (
            _sqlite_url_count(dest) > 0 or _sqlite_has_urls_table(dest)
        ):
            return


def sleep_until_sqlite_checkpoint(
    profile_dir: Union[str, Path], timeout: int = 60
) -> None:
    """
    Checkpoint Chromium SQLite (History/Cookies) so dump_profile archives
    a queryable snapshot. https://www.sqlite.org/wal.html#ckpt.
    """
    started = time.time()
    remaining: float = float(timeout)
    while remaining > 0:
        checkpoint_chromium_sqlite(profile_dir)
        if not tmp_sqlite_files_exist(profile_dir):
            break
        time.sleep(0.25)
        remaining = timeout - (time.time() - started)
    print(
        "Waited for %s seconds for sqlite checkpointing"
        % (timeout - max(remaining, 0.0))
    )
