"""Central settings for the POS & Inventory app.

Set the POS_DB_PATH environment variable to keep the SQLite file somewhere else.
"""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
SEED_DIR = DATA_DIR / "seed"
DB_PATH = Path(os.environ.get("POS_DB_PATH", DATA_DIR / "pos.sqlite3"))

APP_TITLE = "Gadget Hub POS & Inventory"
STORE_NAME = "Gadget Hub (Demo)"

# Amounts are stored as whole numbers in this currency (no decimals).
CURRENCY_SYMBOL = "Rp"

# Shelf prices are tax-inclusive (PPN 11%). The tax portion is shown on totals and receipts.
TAX_RATE = 0.11
TAX_LABEL = "PPN 11%"
