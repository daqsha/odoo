"""SQLite access. Each call opens its own connection; every block runs inside a transaction."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import config

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def _resolve(path: str | Path | None) -> Path:
    return Path(path) if path else config.DB_PATH


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    db_file = _resolve(path)
    db_file.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_file, timeout=10, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def transaction(path: str | Path | None = None, *, write: bool = False) -> Iterator[sqlite3.Connection]:
    """Commit when the block finishes, roll back if it raises.

    write=True takes the write lock immediately (BEGIN IMMEDIATE) so two checkouts
    can never both sell the last unit.
    """
    conn = connect(path)
    try:
        conn.execute("BEGIN IMMEDIATE" if write else "BEGIN")
        yield conn
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def init_database(path: str | Path | None = None, *, seed: bool = True) -> None:
    """Create tables if missing and, when empty, load the sample catalogue."""
    db_file = _resolve(path)
    conn = connect(db_file)
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    finally:
        conn.close()
    if seed:
        from database.seed import seed_if_empty

        seed_if_empty(db_file)
