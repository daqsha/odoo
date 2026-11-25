"""Runs the real Streamlit app headlessly (AppTest) and drives the main cashier and stock flows."""

import sqlite3

import pytest
from streamlit.testing.v1 import AppTest

import config
from database.db import transaction
from logic import catalog, inventory
from logic.identifiers import imei_check_digit

APP = str(config.BASE_DIR / "app.py")


@pytest.fixture()
def app(app_db):
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def _go(at, page):
    at.sidebar.radio[0].set_value(page).run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def _product_id(sku):
    with transaction() as conn:
        return catalog.get_product_by_sku(conn, sku)["id"]


def _sql(query, *args):
    conn = sqlite3.connect(config.DB_PATH)
    try:
        return conn.execute(query, args).fetchall()
    finally:
        conn.close()


def _button(at, label):
    return next(b for b in at.button if b.label == label)


@pytest.mark.parametrize(
    "page",
    [
        "🏠 Dashboard",
        "🛒 Point of Sale",
        "🏷️ Demo Price",
        "📦 Inventory",
        "🧾 Sales & Receipts",
        "🎯 Promotions & Payments",
        "⚙️ Settings",
    ],
)
def test_every_page_renders_without_errors(app, page):
    _go(app, page)


def test_pos_cashier_flow_scan_pay_promote_checkout(app):
    _go(app, "🛒 Point of Sale")
    with transaction() as conn:
        serial = inventory.in_stock_serials(conn, _product_id("NX-X1-128-BLK"))[0]
    charger = _product_id("CH-GAN-65W")
    bca = _sql("SELECT id FROM promotions WHERE code = 'BCA10-PHONE'")[0][0]
    welcome = _sql("SELECT id FROM promotions WHERE code = 'WELCOME5'")[0][0]

    # Scan the IMEI into the search box, then add a charger from its tile
    app.text_input(key="pos_scan").set_value(serial).run()
    assert not app.exception
    app.button(key=f"pos_add_{charger}").click().run()
    assert not app.exception

    # Nothing unlocks until a payment method is chosen
    assert app.button(key="pos_checkout").disabled
    assert all(b.disabled for b in app.button if b.key and b.key.startswith("pos_promo_apply_"))

    app.selectbox(key="pos_payment").set_value("BCA-CC-12M").run()
    assert not app.button(key=f"pos_promo_apply_{bca}").disabled
    app.button(key=f"pos_promo_apply_{bca}").click().run()
    assert not app.exception

    # The 10% card promotion is not stackable, so the stackable welcome promo stays locked
    assert app.button(key=f"pos_promo_apply_{welcome}").disabled

    app.button(key="pos_checkout").click().run()
    assert not app.exception
    assert _sql("SELECT COUNT(*) FROM sales WHERE status = 'COMPLETED'")[0][0] == 1
    assert _sql("SELECT status FROM serials WHERE serial_no = ?", serial)[0][0] == "sold"
    # Cart: phone 4.599.000 + charger 299.000 = 4.898.000. BCA 10% applies to the phone only: 459.900.
    # Then the 1.5% installment fee on 4.438.100 = 66.572, so the customer pays 4.504.672.
    assert _sql("SELECT total_due FROM sales")[0][0] == 4_504_672


def test_demo_price_quotes_quantities_beyond_stock_without_touching_it(app):
    _go(app, "🏷️ Demo Price")
    charger = _product_id("CH-GAN-65W")
    on_hand_before = _sql("SELECT COALESCE(SUM(qty), 0) FROM stock_moves WHERE product_id = ?", charger)[0][0]

    app.selectbox(key="demo_pick").set_value(charger).run()
    app.number_input(key="demo_qty").set_value(30).run()  # more than the 24 in stock
    _button(app, "Add to quote").click().run()
    assert not app.exception
    assert app.session_state["demo_cart"] == [{"product_id": charger, "qty": 30, "serial_no": None}]

    app.selectbox(key="demo_payment").set_value("CASH").run()
    assert not app.exception
    assert len(app.dataframe) >= 1  # the payment-method comparison table

    assert _sql("SELECT COALESCE(SUM(qty), 0) FROM stock_moves WHERE product_id = ?", charger)[0][0] == on_hand_before
    assert _sql("SELECT COUNT(*) FROM sales")[0][0] == 0


def test_inventory_stock_in_form_receives_valid_imeis(app):
    _go(app, "📦 Inventory")
    phone = _product_id("PX-P7-128-GRY")
    body = "49015420323752"
    second_imei = body + str(imei_check_digit(body))
    before = _sql("SELECT COUNT(*) FROM serials WHERE product_id = ?", phone)[0][0]

    app.selectbox(key="si_product_0").set_value(phone).run()
    # Form values commit together with the submit click, so stage them in the same run
    app.text_area(key="si_serials_0").set_value(f"490154203237518\n{second_imei}")
    _button(app, "Receive stock").click().run()

    assert not app.exception
    assert _sql("SELECT COUNT(*) FROM serials WHERE product_id = ?", phone)[0][0] == before + 2
    assert any("Received 2 unit(s)" in m.value for m in app.success)


def test_inventory_stock_in_refuses_a_bad_imei_checksum(app):
    _go(app, "📦 Inventory")
    phone = _product_id("PX-P7-128-GRY")
    before = _sql("SELECT COUNT(*) FROM serials WHERE product_id = ?", phone)[0][0]

    app.selectbox(key="si_product_0").set_value(phone).run()
    app.text_area(key="si_serials_0").set_value("490154203237519")
    _button(app, "Receive stock").click().run()

    assert not app.exception
    assert any("checksum" in m.value for m in app.error)
    assert _sql("SELECT COUNT(*) FROM serials WHERE product_id = ?", phone)[0][0] == before


def test_inventory_write_off_and_count_adjustment_forms(app):
    _go(app, "📦 Inventory")
    drone = _product_id("DR-MINI-2")
    with transaction() as conn:
        serial = inventory.in_stock_serials(conn, drone)[0]

    version = app.session_state["inv_form_version"]
    app.selectbox(key=f"so_product_{version}").set_value(drone).run()
    app.multiselect(key=f"so_serials_{version}").set_value([serial])
    _button(app, "Write off selected units").click().run()
    assert not app.exception
    assert _sql("SELECT status FROM serials WHERE serial_no = ?", serial)[0][0] == "written_off"

    charger = _product_id("CH-GAN-65W")
    version = app.session_state["inv_form_version"]
    app.selectbox(key=f"so_product_{version}").set_value(charger).run()
    app.radio(key=f"so_mode_{version}").set_value("Count adjustment (set the counted quantity)").run()
    app.number_input(key=f"ct_qty_{version}").set_value(20)
    _button(app, "Apply count adjustment").click().run()
    assert not app.exception
    assert _sql("SELECT COALESCE(SUM(qty), 0) FROM stock_moves WHERE product_id = ?", charger)[0][0] == 20


def test_new_product_and_new_promotion_forms_validate_and_save(app):
    _go(app, "📦 Inventory")
    version = app.session_state["inv_form_version"]
    app.text_input(key=f"np_sku_{version}").set_value("TEST-SKU-1")
    app.text_input(key=f"np_name_{version}").set_value("Test gadget")
    app.number_input(key=f"np_cost_{version}").set_value(10_000)
    app.number_input(key=f"np_price_{version}").set_value(25_000)
    _button(app, "Create product").click().run()
    assert _sql("SELECT price FROM products WHERE sku = 'TEST-SKU-1'") == [(25_000,)]

    _go(app, "🎯 Promotions & Payments")
    version = app.session_state["promo_form_version"]
    app.text_input(key=f"np_code_{version}").set_value("RAYA 25")
    app.text_input(key=f"np_name_{version}").set_value("Raya 25 percent")
    app.number_input(key=f"np_value_{version}").set_value(150.0)  # invalid: over 100 percent
    _button(app, "Create promotion").click().run()
    assert any("cannot exceed 100" in e.value for e in app.error)
    assert _sql("SELECT COUNT(*) FROM promotions WHERE code = 'RAYA-25'") == [(0,)]

    version = app.session_state["promo_form_version"]
    app.number_input(key=f"np_value_{version}").set_value(25.0)
    _button(app, "Create promotion").click().run()
    assert _sql("SELECT reward_type, reward_value FROM promotions WHERE code = 'RAYA-25'") == [("PERCENT_OFF", 25.0)]


def test_void_from_sales_page_restores_stock(app):
    from datetime import date

    from logic import pos

    with transaction(write=True) as conn:
        phone = catalog.get_product_by_sku(conn, "NX-X1-128-BLK")
        serial = inventory.in_stock_serials(conn, phone["id"])[0]
        cart: list[dict] = []
        pos.cart_add(cart, product=phone, on_hand=4, in_stock_serials=[serial], serial_no=serial)
        sale_id = pos.checkout(conn, items=cart, payment_code="CASH", today=date.today())

    _go(app, "🧾 Sales & Receipts")
    void_button = _button(app, "Void sale and restore stock")
    assert void_button.disabled  # needs the explicit confirmation first
    app.text_input(key=f"void_reason_{sale_id}").set_value("Customer returned phone")
    app.checkbox(key=f"void_confirm_{sale_id}").check().run()
    _button(app, "Void sale and restore stock").click().run()

    assert not app.exception
    assert _sql("SELECT status FROM sales WHERE id = ?", sale_id) == [("VOIDED",)]
    assert _sql("SELECT status FROM serials WHERE serial_no = ?", serial) == [("in_stock",)]


def test_settings_reset_requires_confirmation_and_reloads_seed(app):
    _go(app, "⚙️ Settings")
    assert _button(app, "Reset to demo data").disabled
    app.checkbox(key="reset_confirm").check().run()
    _button(app, "Reset to demo data").click().run()
    assert not app.exception
    assert _sql("SELECT COUNT(*) FROM products") == [(24,)]
