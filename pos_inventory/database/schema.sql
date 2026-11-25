-- SQLite schema for the POS & Inventory app.
-- Every statement is idempotent so init_database() can run on every start.

CREATE TABLE IF NOT EXISTS products (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    sku           TEXT    NOT NULL UNIQUE,
    name          TEXT    NOT NULL,
    brand         TEXT    NOT NULL DEFAULT '',
    category      TEXT    NOT NULL,
    tracking      TEXT    NOT NULL DEFAULT 'none' CHECK (tracking IN ('none', 'serial', 'imei')),
    cost          INTEGER NOT NULL DEFAULT 0 CHECK (cost >= 0),
    price         INTEGER NOT NULL CHECK (price >= 0),
    reorder_level INTEGER NOT NULL DEFAULT 0 CHECK (reorder_level >= 0),
    active        INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_at    TEXT    NOT NULL
);

-- One row per physical unit of a serial/IMEI-tracked product.
CREATE TABLE IF NOT EXISTS serials (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id  INTEGER NOT NULL REFERENCES products(id),
    serial_no   TEXT    NOT NULL UNIQUE,
    status      TEXT    NOT NULL DEFAULT 'in_stock'
                CHECK (status IN ('in_stock', 'sold', 'written_off')),
    received_at TEXT    NOT NULL,
    sale_id     INTEGER REFERENCES sales(id)
);
CREATE INDEX IF NOT EXISTS idx_serials_product_status ON serials(product_id, status);

-- Stock ledger. On-hand quantity is always SUM(qty) for a product.
CREATE TABLE IF NOT EXISTS stock_moves (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id  INTEGER NOT NULL REFERENCES products(id),
    qty         INTEGER NOT NULL CHECK (qty <> 0),
    move_type   TEXT    NOT NULL
                CHECK (move_type IN ('STOCK_IN', 'STOCK_OUT', 'ADJUSTMENT', 'SALE', 'VOID_SALE')),
    serial_no   TEXT,
    reference   TEXT    NOT NULL DEFAULT '',
    note        TEXT    NOT NULL DEFAULT '',
    unit_cost   INTEGER,
    created_at  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_moves_product ON stock_moves(product_id);

CREATE TABLE IF NOT EXISTS payment_options (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    code          TEXT    NOT NULL UNIQUE,
    label         TEXT    NOT NULL,
    method        TEXT    NOT NULL
                  CHECK (method IN ('CASH', 'DEBIT_CARD', 'CREDIT_CARD', 'EWALLET', 'TRANSFER')),
    issuer        TEXT    NOT NULL DEFAULT '',
    tenor_months  INTEGER NOT NULL DEFAULT 0 CHECK (tenor_months >= 0),
    surcharge_pct REAL    NOT NULL DEFAULT 0 CHECK (surcharge_pct >= 0),
    active        INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))
);

CREATE TABLE IF NOT EXISTS promotions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    code         TEXT    NOT NULL UNIQUE,
    name         TEXT    NOT NULL,
    description  TEXT    NOT NULL DEFAULT '',
    reward_type  TEXT    NOT NULL CHECK (reward_type IN ('PERCENT_OFF', 'FIXED_OFF', 'CASHBACK')),
    reward_value REAL    NOT NULL CHECK (reward_value > 0),
    max_reward   INTEGER CHECK (max_reward IS NULL OR max_reward >= 0),
    min_spend    INTEGER NOT NULL DEFAULT 0 CHECK (min_spend >= 0),
    min_qty      INTEGER NOT NULL DEFAULT 1 CHECK (min_qty >= 1),
    stackable    INTEGER NOT NULL DEFAULT 0 CHECK (stackable IN (0, 1)),
    start_date   TEXT,
    end_date     TEXT,
    active       INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))
);

-- Eligible SKUs. A promotion with no rows here applies to every product.
CREATE TABLE IF NOT EXISTS promotion_products (
    promotion_id INTEGER NOT NULL REFERENCES promotions(id) ON DELETE CASCADE,
    product_id   INTEGER NOT NULL REFERENCES products(id),
    PRIMARY KEY (promotion_id, product_id)
);

-- Payment methods that unlock a promotion. No rows here means any payment method qualifies.
CREATE TABLE IF NOT EXISTS promotion_payments (
    promotion_id      INTEGER NOT NULL REFERENCES promotions(id) ON DELETE CASCADE,
    payment_option_id INTEGER NOT NULL REFERENCES payment_options(id),
    PRIMARY KEY (promotion_id, payment_option_id)
);

CREATE TABLE IF NOT EXISTS sales (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    receipt_no      TEXT UNIQUE,
    created_at      TEXT    NOT NULL,
    customer_name   TEXT    NOT NULL DEFAULT '',
    payment_code    TEXT    NOT NULL,
    payment_label   TEXT    NOT NULL,
    surcharge_pct   REAL    NOT NULL DEFAULT 0,
    subtotal        INTEGER NOT NULL,
    promo_discount  INTEGER NOT NULL,
    surcharge       INTEGER NOT NULL,
    total_due       INTEGER NOT NULL,
    cashback        INTEGER NOT NULL,
    effective_total INTEGER NOT NULL,
    tax_included    INTEGER NOT NULL,
    status          TEXT    NOT NULL DEFAULT 'COMPLETED' CHECK (status IN ('COMPLETED', 'VOIDED')),
    void_reason     TEXT    NOT NULL DEFAULT '',
    voided_at       TEXT
);

CREATE TABLE IF NOT EXISTS sale_lines (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    sale_id     INTEGER NOT NULL REFERENCES sales(id) ON DELETE CASCADE,
    product_id  INTEGER NOT NULL REFERENCES products(id),
    sku         TEXT    NOT NULL,
    name        TEXT    NOT NULL,
    serial_no   TEXT,
    qty         INTEGER NOT NULL,
    unit_price  INTEGER NOT NULL,
    list_total  INTEGER NOT NULL,
    discount    INTEGER NOT NULL,
    net_total   INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS sale_promotions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    sale_id      INTEGER NOT NULL REFERENCES sales(id) ON DELETE CASCADE,
    promotion_id INTEGER REFERENCES promotions(id),
    code         TEXT    NOT NULL,
    name         TEXT    NOT NULL,
    reward_type  TEXT    NOT NULL,
    discount     INTEGER NOT NULL DEFAULT 0,
    cashback     INTEGER NOT NULL DEFAULT 0
);
