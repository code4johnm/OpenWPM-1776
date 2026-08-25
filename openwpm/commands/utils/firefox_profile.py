# This is code adapted from KU Leuven crawler code written by
# Gunes Acar and Marc Juarez

import os
import sqlite3
import time
from glob import glob
from pathlib import Path
from typing import Union

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


def materialize_chromium_history(profile_dir: Union[str, Path]) -> None:
    """Write a standalone Default/History that has a queryable ``urls`` table.

    After Chromium exits, History may be 0 bytes with data only in WAL.
    Open read-only (applies WAL) and backup to a clean file so extract +
    ``SELECT url FROM urls`` works without the WAL sidecar.
    """
    root = Path(profile_dir)
    checkpoint_chromium_sqlite(root)
    dest = root / "Default" / "History"
    dest.parent.mkdir(parents=True, exist_ok=True)
    candidates = []
    for base in (root / "Default", root):
        if not base.is_dir():
            continue
        for path in base.glob("History*"):
            if path.is_file() and not str(path).endswith(("-wal", "-shm")):
                candidates.append(path)
        named = base / "History"
        if named.is_file() and named not in candidates:
            candidates.append(named)
    if dest.is_file() and dest not in candidates:
        candidates.insert(0, dest)
    for src in candidates:
        if _sqlite_has_urls_table(src) or _backup_sqlite(src, dest):
            if src != dest and _sqlite_has_urls_table(src):
                _backup_sqlite(src, dest)
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
