"""Shared test setup. Every test run uses its own temporary database, never the real one."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_TMP_DIR = Path(tempfile.mkdtemp(prefix="pos-tests-"))
os.environ["POS_DB_PATH"] = str(_TMP_DIR / "app.sqlite3")

import pytest  # noqa: E402

from database.db import init_database  # noqa: E402
from database.seed import reset_demo_data  # noqa: E402


@pytest.fixture()
def db(tmp_path: Path) -> Path:
    """A fresh, seeded database file for a single test."""
    path = tmp_path / "test.sqlite3"
    init_database(path, seed=True)
    return path


@pytest.fixture()
def app_db() -> None:
    """Reset the database the Streamlit app uses (AppTest runs the real app against it)."""
    reset_demo_data()
