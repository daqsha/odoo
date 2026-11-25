"""Integration tests against a real SQLite file: stock ledger, serial registry, checkout and voids."""

from datetime import date

import pytest

from database.db import transaction
from database.seed import reset_demo_data
from logic import catalog, inventory, payments, pos
from logic import promotions as promo_store
from logic import reports
from logic.errors import BusinessError, PromotionError, StockError

TODAY = date(2026, 11, 25)


def pid(conn, sku):
    return catalog.get_product_by_sku(conn, sku)["id"]


def assert_ledger_matches_serials(conn):
    """For every product: on-hand equals the ledger sum, and serial-tracked stock equals in-stock units."""
    for product in catalog.list_products(conn, active_only=False):
        on_hand = inventory.on_hand(conn, product["id"])
        assert on_hand >= 0, product["sku"]
        if product["tracking"] != "none":
            count = conn.execute(
                "SELECT COUNT(*) FROM serials WHERE product_id = ? AND status = 'in_stock'", (product["id"],)
            ).fetchone()[0]
            assert on_hand == count, product["sku"]


def sell_one_phone(db, payment_code="CASH", promotion_ids=(), customer=""):
    with transaction(db, write=True) as conn:
        phone = catalog.get_product_by_sku(conn, "NX-X1-128-BLK")
        serial = inventory.in_stock_serials(conn, phone["id"])[0]
        cart: list[dict] = []
        pos.cart_add(
            cart,
            product=phone,
            on_hand=inventory.on_hand(conn, phone["id"]),
            in_stock_serials=inventory.in_stock_serials(conn, phone["id"]),
            serial_no=serial,
        )
        return pos.checkout(
            conn,
            items=cart,
            payment_code=payment_code,
            promotion_ids=list(promotion_ids),
            customer_name=customer,
            today=TODAY,
        ), serial


# ----- seed and ledger -----

def test_seed_loads_the_expected_sample_catalogue(db):
    with transaction(db) as conn:
        assert len(catalog.list_products(conn)) == 24
        assert len(payments.load_payment_options(conn)) == 11
        assert len(promo_store.load_promotions(conn, active_only=False)) == 9
        nx = pid(conn, "NX-X1-128-BLK")
        assert inventory.on_hand(conn, nx) == 4
        assert_ledger_matches_serials(conn)


def test_reseeding_an_existing_database_does_not_duplicate_data(db):
    from database.seed import seed_if_empty

    assert seed_if_empty(db) is False


# ----- stock-in -----

def test_receiving_an_imei_adds_one_unit_and_rejects_duplicates(db):
    with transaction(db, write=True) as conn:
        nx = pid(conn, "NX-X1-128-BLK")
        inventory.receive_stock(conn, product_id=nx, serials=["490154203237518"], unit_cost=3_900_000)
        assert inventory.on_hand(conn, nx) == 5
    with pytest.raises(BusinessError, match="Already in the system"):
        with transaction(db, write=True) as conn:
            inventory.receive_stock(conn, product_id=nx, serials=["490154203237518"])
    with transaction(db) as conn:
        assert inventory.on_hand(conn, pid(conn, "NX-X1-128-BLK")) == 5
        assert_ledger_matches_serials(conn)


def test_receiving_rejects_a_bad_imei_checksum_and_duplicates_inside_one_receipt(db):
    with pytest.raises(BusinessError, match="checksum"):
        with transaction(db, write=True) as conn:
            inventory.receive_stock(conn, product_id=pid(conn, "NX-X1-128-BLK"), serials=["490154203237519"])
    with pytest.raises(BusinessError, match="Duplicate"):
        with transaction(db, write=True) as conn:
            inventory.receive_stock(
                conn, product_id=pid(conn, "NX-X1-128-BLK"), serials=["490154203237518", "490154203237518"]
            )


def test_quantity_products_take_a_count_not_serials(db):
    with transaction(db, write=True) as conn:
        charger = pid(conn, "CH-GAN-65W")
        assert inventory.receive_stock(conn, product_id=charger, qty=5, reference="PO-1") == 5
        assert inventory.on_hand(conn, charger) == 30
        with pytest.raises(BusinessError):
            inventory.receive_stock(conn, product_id=charger, qty=0)


# ----- stock-out and adjustments -----

def test_stock_out_of_quantity_item_cannot_go_negative(db):
    with pytest.raises(StockError):
        with transaction(db, write=True) as conn:
            inventory.stock_out(conn, product_id=pid(conn, "CH-GAN-65W"), reason="Damaged", qty=99)
    with transaction(db, write=True) as conn:
        drone = pid(conn, "DR-MINI-2")
        inventory.stock_out(conn, product_id=drone, reason="Damaged", serials=[inventory.in_stock_serials(conn, drone)[0]])
        assert inventory.on_hand(conn, drone) == 1
        assert_ledger_matches_serials(conn)


def test_writing_off_a_serial_marks_it_unavailable(db):
    with transaction(db, write=True) as conn:
        tablet = pid(conn, "OT-10-WIFI-64")
        serial = inventory.in_stock_serials(conn, tablet)[0]
        inventory.stock_out(conn, product_id=tablet, reason="Lost / missing", serials=[serial])
        status = conn.execute("SELECT status FROM serials WHERE serial_no = ?", (serial,)).fetchone()[0]
        assert status == "written_off"
        assert inventory.on_hand(conn, tablet) == 2
        with pytest.raises(StockError):
            inventory.stock_out(conn, product_id=tablet, reason="Damaged", serials=[serial])


def test_count_adjustment_sets_the_counted_quantity(db):
    with transaction(db, write=True) as conn:
        charger = pid(conn, "CH-GAN-65W")
        assert inventory.adjust_count(conn, product_id=charger, counted_qty=20, reason="Monthly count") == -5
        assert inventory.on_hand(conn, charger) == 20
        with pytest.raises(BusinessError, match="Nothing to adjust"):
            inventory.adjust_count(conn, product_id=charger, counted_qty=20)
        with pytest.raises(BusinessError, match="cannot be count-adjusted"):
            inventory.adjust_count(conn, product_id=pid(conn, "NX-X1-128-BLK"), counted_qty=1)


# ----- cart rules -----

def test_cart_refuses_more_units_than_are_on_hand(db):
    with transaction(db) as conn:
        charger = catalog.get_product_by_sku(conn, "CH-GAN-65W")
        cart: list[dict] = []
        pos.cart_add(cart, product=charger, on_hand=2, qty=2)
        with pytest.raises(StockError):
            pos.cart_add(cart, product=charger, on_hand=2, qty=1)
        assert cart == [{"product_id": charger["id"], "qty": 2, "serial_no": None}]


def test_cart_refuses_a_serial_that_is_not_in_stock_or_already_added(db):
    with transaction(db) as conn:
        phone = catalog.get_product_by_sku(conn, "NX-X1-128-BLK")
        serials = inventory.in_stock_serials(conn, phone["id"])
        cart: list[dict] = []
        with pytest.raises(StockError):
            pos.cart_add(cart, product=phone, on_hand=4, in_stock_serials=serials, serial_no="NOPE1234")
        pos.cart_add(cart, product=phone, on_hand=4, in_stock_serials=serials, serial_no=serials[0])
        with pytest.raises(BusinessError, match="already in the cart"):
            pos.cart_add(cart, product=phone, on_hand=4, in_stock_serials=serials, serial_no=serials[0])


def test_sanitize_cart_caps_quantities_after_stock_changes(db):
    with transaction(db) as conn:
        charger = catalog.get_product_by_sku(conn, "CH-GAN-65W")
        products = {p["id"]: p for p in catalog.list_products(conn)}
        cart = [{"product_id": charger["id"], "qty": 5, "serial_no": None}]
        cleaned, messages = pos.sanitize_cart(cart, products, {charger["id"]: 2}, {})
        assert cleaned[0]["qty"] == 2
        assert any("Quantity reduced" in m for m in messages)


# ----- checkout and voids -----

def test_checkout_writes_sale_moves_serial_and_receipt(db):
    sale_id, serial = sell_one_phone(db, payment_code="CASH", customer="Dewi")
    with transaction(db) as conn:
        sale = pos.get_sale(conn, sale_id)
        assert sale["total_due"] == 4_599_000
        assert sale["customer_name"] == "Dewi"
        assert sale["receipt_no"].startswith("R")
        assert inventory.on_hand(conn, pid(conn, "NX-X1-128-BLK")) == 3
        status = conn.execute("SELECT status, sale_id FROM serials WHERE serial_no = ?", (serial,)).fetchone()
        assert status["status"] == "sold" and status["sale_id"] == sale_id
        assert_ledger_matches_serials(conn)


def test_checkout_with_a_stale_serial_fails_and_writes_nothing(db):
    sale_id, serial = sell_one_phone(db)
    with transaction(db) as conn:
        phone = pid(conn, "NX-X1-128-BLK")
        before = conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0]
    with pytest.raises(StockError):
        with transaction(db, write=True) as conn:
            pos.checkout(
                conn,
                items=[{"product_id": phone, "qty": 1, "serial_no": serial}],
                payment_code="CASH",
                today=TODAY,
            )
    with transaction(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0] == before


def test_checkout_rechecks_promotion_terms_and_refuses_a_mismatched_payment(db):
    with transaction(db) as conn:
        bca = conn.execute("SELECT id FROM promotions WHERE code = 'BCA10-PHONE'").fetchone()[0]
        phone = pid(conn, "NX-X1-128-BLK")
        serial = inventory.in_stock_serials(conn, phone)[0]
    with pytest.raises(PromotionError, match="Requires payment"):
        with transaction(db, write=True) as conn:
            pos.checkout(
                conn,
                items=[{"product_id": phone, "qty": 1, "serial_no": serial}],
                payment_code="CASH",
                promotion_ids=[bca],
                today=TODAY,
            )
    with transaction(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0] == 0
        assert conn.execute("SELECT status FROM serials WHERE serial_no = ?", (serial,)).fetchone()[0] == "in_stock"


def test_checkout_applies_promotion_discount_and_records_it(db):
    with transaction(db) as conn:
        bca = conn.execute("SELECT id FROM promotions WHERE code = 'BCA10-PHONE'").fetchone()[0]
    sale_id, _ = sell_one_phone(db, payment_code="BCA-CC-FULL", promotion_ids=[bca])
    with transaction(db) as conn:
        sale = pos.get_sale(conn, sale_id)
        assert sale["promo_discount"] == 459_900
        assert sale["promotions"][0]["code"] == "BCA10-PHONE"
        assert sale["total_due"] == 4_599_000 - 459_900


def test_void_restores_units_to_stock_and_cannot_be_repeated(db):
    sale_id, serial = sell_one_phone(db)
    with transaction(db, write=True) as conn:
        pos.void_sale(conn, sale_id=sale_id, reason="Customer returned phone")
    with transaction(db) as conn:
        assert pos.get_sale(conn, sale_id)["status"] == "VOIDED"
        assert conn.execute("SELECT status FROM serials WHERE serial_no = ?", (serial,)).fetchone()[0] == "in_stock"
        assert inventory.on_hand(conn, pid(conn, "NX-X1-128-BLK")) == 4
        assert_ledger_matches_serials(conn)
    with pytest.raises(BusinessError, match="already been voided"):
        with transaction(db, write=True) as conn:
            pos.void_sale(conn, sale_id=sale_id, reason="again")


def test_void_needs_a_reason(db):
    sale_id, _ = sell_one_phone(db)
    with pytest.raises(BusinessError, match="reason"):
        with transaction(db, write=True) as conn:
            pos.void_sale(conn, sale_id=sale_id, reason="   ")


def test_best_sellers_and_seven_day_revenue_series(db):
    sell_one_phone(db)
    with transaction(db) as conn:
        rows = reports.product_sales(conn)
        assert rows[0]["sku"] == "NX-X1-128-BLK"  # best sellers first
        assert next(r for r in rows if r["sku"] == "NX-X1-128-BLK")["units"] == 1
        series = reports.daily_revenue(conn, date.today(), days=7)
        assert len(series) == 7
        assert series[-1][1] == 4_599_000
        assert all(value == 0 for _, value in series[:-1])


def test_dashboard_summary_reflects_todays_sales(db):
    sell_one_phone(db)
    with transaction(db) as conn:
        summary = reports.dashboard_summary(conn, date.today())
        assert summary["sales_count"] == 1
        assert summary["sales_total"] == 4_599_000
        assert summary["units_on_hand"] > 0


def test_reset_demo_data_restores_the_seed_after_changes(db):
    sell_one_phone(db)
    reset_demo_data(db)
    with transaction(db) as conn:
        assert inventory.on_hand(conn, pid(conn, "NX-X1-128-BLK")) == 4
        assert conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0] == 0
        assert_ledger_matches_serials(conn)


# ----- stock lookup -----

def test_lookup_finds_units_by_partial_imei_and_by_product_name(db):
    with transaction(db) as conn:
        phone = pid(conn, "NX-X1-128-BLK")
        serial = inventory.in_stock_serials(conn, phone)[0]
        partial = inventory.lookup(conn, serial[3:11])
        assert any(u["serial_no"] == serial for u in partial["units"])
        assert partial["exact_unit"] is None
        by_name = inventory.lookup(conn, "nimbus x1")
        assert {p["sku"] for p in by_name["products"]} >= {"NX-X1-128-BLK", "NX-X1-256-BLU"}
        assert all(u["status"] == "in_stock" for u in by_name["units"])


def test_lookup_exact_match_reports_sale_details_and_history(db):
    sale_id, serial = sell_one_phone(db, customer="Rina")
    with transaction(db) as conn:
        result = inventory.lookup(conn, serial)
        unit = result["exact_unit"]
        assert unit["serial_no"] == serial and result["units"][0]["serial_no"] == serial
        assert unit["status"] == "sold"
        assert unit["receipt_no"] == pos.get_sale(conn, sale_id)["receipt_no"]
        assert unit["customer_name"] == "Rina"
    with transaction(db, write=True) as conn:
        pos.void_sale(conn, sale_id=sale_id, reason="Returned")
    with transaction(db) as conn:
        assert inventory.lookup(conn, serial)["exact_unit"]["status"] == "in_stock"
        moves = [m["move_type"] for m in inventory.serial_history(conn, serial)]
        assert moves == ["STOCK_IN", "SALE", "VOID_SALE"]


def test_lookup_shows_write_off_reason(db):
    with transaction(db, write=True) as conn:
        drone = pid(conn, "DR-MINI-2")
        serial = inventory.in_stock_serials(conn, drone)[0]
        inventory.stock_out(conn, product_id=drone, reason="Damaged", serials=[serial], note="dropped")
        unit = inventory.lookup(conn, serial)["exact_unit"]
        assert unit["status"] == "written_off"
        assert unit["writeoff_note"] == "Damaged - dropped"


def test_lookup_treats_sql_wildcards_literally_and_handles_blank_input(db):
    with transaction(db) as conn:
        assert inventory.lookup(conn, "%") == {"units": [], "products": [], "exact_unit": None}
        assert inventory.lookup(conn, "_") == {"units": [], "products": [], "exact_unit": None}
        assert inventory.lookup(conn, "   ") == {"units": [], "products": [], "exact_unit": None}


def test_lookup_product_stock_state_and_counts(db):
    sell_one_phone(db)
    with transaction(db) as conn:
        product = next(p for p in inventory.lookup(conn, "NX-X1-128-BLK")["products"] if p["sku"] == "NX-X1-128-BLK")
        assert product["units_available"] == 3 and product["units_sold"] == 1
        assert product["stock_state"] == "ok"
        keyboard = next(p for p in inventory.lookup(conn, "KB-BT-SLIM")["products"])
        assert keyboard["stock_state"] == "low"
