# blibli POS & Inventory

A localhost point-of-sale and inventory app built with **Python, Streamlit and SQLite**, inspired by the
integrated POS and Inventory flows in Odoo. It targets two gaps in standard POS setups:

1. **Rule-checked promotions.** A promotion unlocks only when its terms and conditions (T&C) are met for the
   *chosen payment method* and the *current cart*. Locked promotions say exactly what is missing and cannot be applied.
2. **Demo Price.** Sales staff can quote any product, with or without stock or an IMEI scanned, test every payment
   method and the promotions it unlocks, and hand the customer an accurate price estimate. Nothing is sold.

Everything persists in a local SQLite file, so stock, sales and promotions survive restarts.

---

## Contents

- [Set up in VS Code](#set-up-in-vs-code)
- [Using the app](#using-the-app)
- [Look and feel](#look-and-feel)
- [How the promotion rule engine works](#how-the-promotion-rule-engine-works)
- [Inventory rules (stock-in, stock-out, IMEI and serials)](#inventory-rules)
- [Project layout](#project-layout)
- [Running the tests](#running-the-tests)
- [Resetting or moving the data](#resetting-or-moving-the-data)
- [Design notes and limits](#design-notes-and-limits)

---

## Set up in VS Code

**You need:** Python 3.10 or newer (developed and tested on 3.13), and VS Code with the
**Python** extension (`ms-python.python`).

1. **Unzip** the project, then in VS Code choose **File → Open Folder…** and open the `pos_inventory` folder.

2. **Open a terminal** with **Terminal → New Terminal** (`` Ctrl+` `` / `` Cmd+` ``).

3. **Create a virtual environment** (one time only).

   macOS / Linux:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

   Windows PowerShell:
   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

   If PowerShell blocks the activation script, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, then try again.

4. **Pick the interpreter.** Press `Ctrl+Shift+P` (`Cmd+Shift+P` on macOS), run **Python: Select Interpreter**, and choose
   the one inside `.venv`. The terminal should now show `(.venv)`.

5. **Install the dependencies:**
   ```bash
   pip install -r requirements.txt
   ```
   For the test suite as well, use `pip install -r requirements-dev.txt`.

6. **Start the app:**
   ```bash
   streamlit run app.py
   ```
   Your browser opens at **http://localhost:8501**. On the first start the app creates `data/pos.sqlite3` and loads the
   sample catalogue (24 electronics and gadget products, 11 payment options, 9 promotions and opening stock).

   You can also press **F5** and choose **Run POS app (Streamlit)** from the Run and Debug panel. The launch
   configuration lives in `.vscode/launch.json`.

To stop the server, press `Ctrl+C` in the terminal.

---

## Using the app

The sidebar has seven pages.

| Page | What it is for |
| --- | --- |
| **🏠 Dashboard** | Today's sales, promotions given, cashback owed, stock value, low-stock alerts, top sellers and recent sales. |
| **🛒 Point of Sale** | Scan or pick products, check promotions, choose payment, complete the sale and print or download the receipt. |
| **🏷️ Demo Price** | Quote any product, with any quantity, including items not in stock. Compare every payment method side by side. |
| **📦 Inventory** | Stock overview, stock-in, stock-out and count adjustments, product catalogue, and full movement history. |
| **🧾 Sales & Receipts** | Browse sales, reopen or download any receipt, and void a sale (which returns the units to stock). |
| **🎯 Promotions & Payments** | Create and switch promotions and payment options (cards, tenors, e-wallets), with their T&C shown in plain language. |
| **⚙️ Settings** | Store details, how the rules are enforced, and a guarded reset to the demo data. |

### Point of Sale, step by step

1. **Add items.** Type an SKU or name in *Filter catalogue*, or click **Add**. Serial-tracked items (phones, laptops,
   wearables and so on) show a picker of units in stock.
   *Scanning:* click the scan box and scan a barcode, or type an SKU or IMEI and press **Enter**. A scanned IMEI or serial
   goes straight into the cart.
2. **Choose the payment method first.** Until a method is chosen, every promotion shows **🔒 Locked, Select a payment method
   first**, and checkout stays disabled.
3. **Promotions.** Each promotion is either **🔓 Unlocked** (with the estimated saving and an **Apply** button) or
   **🔒 Locked** with every condition that is not met. Open *Terms & conditions* to read the full T&C.
4. **Totals.** Shows subtotal, promotions, installment fee if any, the total to pay, the tax included in the price,
   and any cashback reward and effective price.
5. **Complete sale.** The sale is written atomically. Stock and IMEI statuses are updated and a receipt appears, ready to
   download as `.txt` (thermal-style) or `.html` (printable).

### Demo Price, step by step

1. Pick any product and quantity and click **Add to quote**. Stock and IMEIs are *not* checked, and the page says so.
2. Choose the payment method and apply the promotions that unlock.
3. Read the price estimate, or open **Copy-ready estimate for the customer** to paste it into a chat or message.
4. **Compare payment methods** shows every payment option for the same cart, using the best combination of promotions
   that each one qualifies for, sorted by lowest effective price.

Nothing on this page creates a sale or changes stock.

---

## Look and feel

The interface follows a purple and coral dashboard layout. The main parts are:

- a purple navigation rail with a white pill for the current page
- a greeting with search, and category pills that wrap
- product cards with one primary action (*Order* or *Add unit*)
- Best Seller and Statistics blocks, with a small revenue chart
- a sticky right-hand panel. On **Point of Sale** it holds *My Order*, the customer, payment, promotions and checkout. On **Demo Price** it holds the price estimate, and on **Overview** it holds recent orders and stock alerts.

To rebrand:

- **Store and cashier names:** `STORE_NAME` and `CASHIER_NAME` in `config.py`.
- **Colours:** the `PRIMARY` and `ACCENT` constants and the CSS variables at the top of `views/theme.py`. Streamlit's own widgets (buttons, pills, tabs, focus rings) use the purple from the `[theme]` block in `.streamlit/config.toml`.
- **Product icons:** the sample products have no photos. Each card shows an emoji for its category. Change `CATEGORY_ICONS` in `views/theme.py`, or extend the cards to show images.

The heading font (Poppins) loads from Google Fonts. Without internet access the page falls back to the system font, and nothing else changes.

## How the promotion rule engine works

Source: `logic/rules.py`, `logic/pricing.py`, `logic/models.py`. The engine is pure Python with no UI or database calls,
and it is unit-tested directly.

A promotion is **unlocked only when all of these hold**:

| # | Condition | Example reason shown when locked |
| --- | --- | --- |
| 1 | A payment method has been chosen | *Select a payment method first* |
| 2 | The promotion is switched on | *Promotion is switched off* |
| 3 | Today is inside its validity window | *Starts 01 Dec 2026* / *Expired on 31 Dec 2025* |
| 4 | The payment method is one it names (if it names any) | *Requires payment: BCA Credit Card 12-month installment* |
| 5 | The cart has an eligible SKU (if it names any) | *Needs an eligible item: ZB-14-I5-512, ZB-15-I7-1TB* |
| 6 | At least the minimum number of eligible units | *Needs 2 eligible item(s), cart has 1* |
| 7 | Eligible subtotal at least the minimum spend | *Add Rp 401.000 more eligible items (minimum Rp 5.000.000)* |
| 8 | No clash with a discount already applied | *Cannot be combined with BCA Credit Card 10 percent off smartphones* |

**Other rules that keep prices correct**

- **Conditions use list prices**, so the result does not depend on the order the cashier clicks in.
- **Discounts apply in sequence** on the amount still left on eligible lines, so a price can never go negative.
- **Clashes:** two price reductions (percent or amount off) cannot be combined unless *both* are marked *combinable*.
  Cashback never clashes.
- **Strict re-check.** Whenever the cart or payment method changes, every applied promotion is re-checked. Any that no
  longer qualify are removed, and the cashier sees a warning naming the condition that failed. Checkout re-checks them a
  final time, and the sale is refused if any no longer qualify.
- **Cashback** is calculated last, on what the customer actually pays for the eligible items. It is a reward credit, so
  it is shown separately and does not change the amount collected today.
- **Rounding** is half-up and exact (no floating-point drift). Discount shares are split with the largest-remainder method,
  so line discounts always add up to the promotion total.
- **Installment fees** (surcharge %) are applied after promotions, on the net amount.

**Promotion types**

| Type | Meaning |
| --- | --- |
| `PERCENT_OFF` | Percent off eligible items, optionally capped by a maximum reward. |
| `FIXED_OFF` | An amount off the eligible items, never more than their value. |
| `CASHBACK` | Percent back on eligible items, credited after payment, optionally capped. |

The sample data includes examples of each: a BCA card 10% deal capped at Rp 500.000, a Mandiri 12-month 0% laptop
deal, a GoPay 15% cashback, a cash-only accessory bundle, a BNI debit wearables deal, a non-combinable spend-5-million
deal, an OVO accessory cashback, a stackable welcome discount, and an expired launch promotion that shows the expired
state.

---

## Inventory rules

- **Ledger first.** Every quantity change is a row in `stock_moves`. On-hand is always the sum of that ledger.
- **Quantity items** (cables, chargers, cases) are received and written off by count. Stock can never go negative.
- **Serial and IMEI items** (phones, tablets, laptops, wearables, cameras, drones) are received one number per unit.
  - **IMEI:** exactly 15 digits, and the check digit must pass the Luhn checksum. Spaces and dashes are removed.
  - **Serial:** 4 to 40 letters, digits or dashes. It is stored in upper case.
  - Duplicates inside one receipt are refused, and so is any number already in the system.
  - A unit can only be sold if it is `in_stock`. A sold unit returns to `in_stock` only through a void.
- **Stock-out** records a reason (damaged, lost, internal use or demo unit, returned to supplier, other) and writes units
  off one by one.
- **Count adjustment** sets the physically counted quantity for a quantity item and records the difference.
- **Concurrency.** Checkout, void and stock changes run inside `BEGIN IMMEDIATE` transactions, so two registers cannot
  sell the same last unit.

---

## Project layout

```
pos_inventory/
├── app.py                    Streamlit entry point (sidebar navigation)
├── config.py                 Settings: database path, currency, tax
├── requirements.txt          Runtime dependencies (streamlit)
├── requirements-dev.txt      Adds pytest for the test suite
├── pytest.ini
├── README.md
├── .streamlit/config.toml    Streamlit server and browser options
├── .vscode/                  Launch configurations and test settings
├── database/
│   ├── schema.sql            Tables (idempotent, runs on every start)
│   ├── db.py                 Connections and transactions
│   └── seed.py               Loads data/seed/*.csv through the same validated logic
├── data/
│   ├── seed/                 Sample products, stock, payment options, promotions (CSV)
│   └── pos.sqlite3           Created on first run (git-ignored)
├── logic/                    Business rules, no Streamlit imports
│   ├── models.py             Dataclasses: CartLine, Promotion, PaymentOption, Quote...
│   ├── rules.py              Promotion rule engine (eligibility, clashes, prune, auto-select)
│   ├── pricing.py            Quote builder: discounts, cashback, fees, tax
│   ├── pos.py                Cart operations, checkout, void, sale history
│   ├── inventory.py          Stock ledger, stock-in, stock-out, counts, serial registry
│   ├── catalog.py            Products
│   ├── promotions.py         Promotion repository
│   ├── payments.py           Payment options
│   ├── identifiers.py        IMEI Luhn check and serial validation
│   ├── receipts.py           Receipt text, HTML and price estimates
│   ├── reports.py            Dashboard numbers
│   ├── money.py              Exact rounding and currency formatting
│   ├── errors.py             BusinessError, StockError, PromotionError
│   └── utils.py
├── views/                    Streamlit pages (one module per page) and theme.py for styling
└── tests/                    83 tests: rules, pricing, identifiers, stock and sales, theme helpers and headless app flows
```

Data flows one way: pages call `logic/`, and `logic/` talks to SQLite through an open connection passed in by the page.
That keeps the rules testable without starting Streamlit.

---

## Running the tests

```bash
python -m pytest
```

The suite runs in a few seconds. It uses its own temporary databases, so your `data/pos.sqlite3` is never touched.
It covers:

- rule-engine gating, clashes, validity windows, pruning, and the greedy best-combination logic
- price maths: caps, sequencing, exact allocation, surcharges, cashback and tax
- IMEI checksums and serial validation
- stock invariants: the ledger always equals the count of in-stock serials, and nothing goes negative
- checkout atomicity (a stale serial or a failed promotion writes nothing), voids and reset
- the real Streamlit app driven headlessly with `streamlit.testing`: the full cashier flow, Demo Price,
  inventory forms, promotion creation and validation, void, and reset

In VS Code, the **Testing** panel also discovers them (the settings are in `.vscode/settings.json`).

---

## Resetting or moving the data

- **Reset to demo data:** *Settings* page, tick the confirmation box, then press the button. This wipes every table and
  reloads `data/seed/`.
- **From the terminal:** `python -m database.seed --reset`
- **Keep the database elsewhere:** set `POS_DB_PATH` before starting, for example
  `POS_DB_PATH=/path/to/shop.sqlite3 streamlit run app.py` (on Windows PowerShell:
  `$env:POS_DB_PATH="C:\data\shop.sqlite3"; streamlit run app.py`).
- **Back up:** stop the app (`Ctrl+C`), then copy `data/pos.sqlite3`. If a `pos.sqlite3-wal` file is present, copy it too.

To add your own products, use the *Inventory → Catalogue* tab, or edit the CSV files in `data/seed/` and reset. Seed
rows are validated exactly like typed-in data.

---

## Design notes and limits

- **Currency and tax.** Amounts are whole rupiah (`Rp`) and shelf prices include 11% PPN, which is shown as "included"
  on totals and receipts. Change `CURRENCY_SYMBOL`, `TAX_RATE` and `TAX_LABEL` in `config.py` for another market.
- **Sample data is fictional.** Brands such as Nimbus, Pixo, Vexa, Orbit, Zentra, Pulse and Beatwave are made up.
  The IMEIs are generated with valid check digits but use a non-allocated prefix (`990…`), so they do not identify
  real devices. Bank and e-wallet names appear only as payment labels in the sample promotions.
- **Single register, localhost.** There is no login and no user accounts. SQLite runs in WAL mode, which handles
  several browser tabs on one machine well, but this is not built for multi-branch or internet deployment.
- **Not included (good next steps):** partial returns (a void reverses a whole sale), hardware printer or barcode
  label output, per-product tax rates, multi-currency, and customer loyalty accounts.
- **Extending promotions.** To add a reward type: add the constant in `logic/models.py`, handle it in
  `logic/pricing.py` (`build_quote`) and `logic/rules.py` (`reward_summary`, `terms`), add its label to
  `REWARD_LABELS` in `logic/promotions.py`, and extend the `CHECK` constraint in `database/schema.sql`. Because SQLite
  cannot alter a `CHECK` constraint in place, reset the demo database or run a manual migration for existing data.
- **Streamlit version.** Developed and tested on Streamlit 1.67. The layout uses keyed containers, pills and column alignment, so `requirements.txt` asks for 1.50 or newer. Older versions are untested.

---

_Built as a self-contained example project. Use it as a starting point for your own shop._
