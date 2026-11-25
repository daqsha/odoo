"""Receipts and price estimates, as plain text (for printing or copy-paste) and as HTML."""

from __future__ import annotations

import html
from datetime import datetime

import config
from logic.models import Quote
from logic.money import money

WIDTH = 42


def _pair(left: str, right: str, width: int = WIDTH) -> str:
    space = max(1, width - len(left) - len(right))
    return f"{left}{' ' * space}{right}"


def _center(text: str, width: int = WIDTH) -> str:
    return text.center(width).rstrip()


def _when(stamp: str) -> str:
    try:
        return datetime.fromisoformat(stamp).strftime("%d %b %Y %H:%M")
    except (TypeError, ValueError):
        return stamp or ""


def receipt_text(sale: dict, width: int = WIDTH) -> str:
    rule, thin = "=" * width, "-" * width
    out = [
        rule,
        _center(config.STORE_NAME, width),
        _center(f"Receipt {sale.get('receipt_no') or '-'}", width),
        _center(_when(sale["created_at"]), width),
    ]
    if sale.get("customer_name"):
        out.append(f"Customer: {sale['customer_name']}")
    out.append(thin)

    for line in sale["lines"]:
        out.append(line["name"])
        ident = f"  {line['sku']}"
        if line["serial_no"]:
            ident += f"  S/N {line['serial_no']}"
        out.append(ident)
        out.append(_pair(f"  {line['qty']} x {money(line['unit_price'])}", money(line["list_total"]), width))
        if line["discount"]:
            out.append(_pair("  Discount", f"-{money(line['discount'])}", width))

    out.append(thin)
    out.append(_pair("Subtotal", money(sale["subtotal"]), width))
    for promo in sale["promotions"]:
        if promo["discount"]:
            out.append(_pair(f"Promo {promo['code']}", f"-{money(promo['discount'])}", width))
    if sale["surcharge"]:
        out.append(_pair(f"Payment fee ({sale['surcharge_pct']:g}%)", money(sale["surcharge"]), width))
    out.append(_pair("TOTAL", money(sale["total_due"]), width))
    out.append(_pair(f"  included {config.TAX_LABEL}", money(sale["tax_included"]), width))
    if sale["cashback"]:
        out.append(thin)
        out.append(_pair("Cashback reward (credited later)", money(sale["cashback"]), width))
        out.append(_pair("Effective price after rewards", money(sale["effective_total"]), width))
    out.append(thin)
    out.append(f"Paid by: {sale['payment_label']}")
    if sale["status"] == "VOIDED":
        out.append(_center("*** VOIDED ***", width))
        out.append(f"Void reason: {sale['void_reason']}")
    out.append(rule)
    out.append(_center("Thank you for shopping with us!", width))
    return "\n".join(out)


def estimate_text(quote: Quote, lines_title: str = "PRICE ESTIMATE") -> str:
    """Customer-friendly quote for the Demo Price tab. Safe to copy into a chat message."""
    out = [f"{lines_title} · {config.STORE_NAME}"]
    for line in quote.lines:
        out.append(f"{line.qty} x {line.name}  {money(line.list_total)}")
    out.append(f"Subtotal: {money(quote.subtotal)}")
    for app in quote.applications:
        if app.discount:
            out.append(f"Promo {app.promotion.name}: -{money(app.discount)}")
    if quote.surcharge:
        out.append(f"Payment fee ({quote.payment.surcharge_pct:g}%): {money(quote.surcharge)}")
    out.append(f"Total to pay: {money(quote.total_due)}")
    if quote.cashback:
        out.append(f"Cashback reward: {money(quote.cashback)}")
        out.append(f"Effective price after rewards: {money(quote.effective_total)}")
    payment = quote.payment.label if quote.payment else "not chosen"
    out.append(f"Payment: {payment}")
    out.append(
        f"Prices include {config.TAX_LABEL} ({money(quote.tax_included)}). "
        "Estimate only. Final price is confirmed at checkout."
    )
    return "\n".join(out)


def receipt_html(sale: dict) -> str:
    e = html.escape
    item_rows = []
    for line in sale["lines"]:
        ident = e(line["sku"]) + (f" · S/N {e(line['serial_no'])}" if line["serial_no"] else "")
        item_rows.append(
            f"<tr><td>{e(line['name'])}<div class='muted'>{ident}</div></td>"
            f"<td class='num'>{line['qty']} × {e(money(line['unit_price']))}</td>"
            f"<td class='num'>{e(money(line['net_total']))}</td></tr>"
        )

    summary: list[tuple[str, str, bool]] = [("Subtotal", money(sale["subtotal"]), False)]
    for promo in sale["promotions"]:
        if promo["discount"]:
            summary.append((f"Promo: {promo['name']}", f"-{money(promo['discount'])}", False))
    if sale["surcharge"]:
        summary.append((f"Payment fee ({sale['surcharge_pct']:g}%)", money(sale["surcharge"]), False))
    summary.append(("Total", money(sale["total_due"]), True))
    summary.append((f"Included {config.TAX_LABEL}", money(sale["tax_included"]), False))
    if sale["cashback"]:
        summary.append(("Cashback reward (credited later)", money(sale["cashback"]), False))
        summary.append(("Effective price after rewards", money(sale["effective_total"]), False))
    summary_rows = "".join(
        f"<tr class='{'grand' if bold else ''}'><td colspan='2'>{e(label)}</td><td class='num'>{e(amount)}</td></tr>"
        for label, amount, bold in summary
    )
    void_banner = ""
    if sale["status"] == "VOIDED":
        void_banner = f"<p class='void'>VOIDED · {e(sale['void_reason'])}</p>"

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Receipt {e(sale.get('receipt_no') or '')}</title>
<style>
  body {{ font-family: -apple-system, Segoe UI, Roboto, sans-serif; background: #f4f5f7; margin: 0; padding: 24px; color: #1d2333; }}
  .receipt {{ max-width: 420px; margin: 0 auto; background: #fff; padding: 24px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,.08); }}
  h1 {{ font-size: 20px; margin: 0; text-align: center; }}
  .meta {{ text-align: center; color: #6b7280; font-size: 13px; margin: 4px 0 16px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
  td {{ padding: 6px 0; vertical-align: top; }}
  .num {{ text-align: right; white-space: nowrap; }}
  .muted {{ color: #6b7280; font-size: 12px; }}
  tr.grand td {{ font-weight: 700; font-size: 16px; border-top: 1px solid #d1d5db; padding-top: 10px; }}
  .void {{ color: #b91c1c; font-weight: 700; text-align: center; }}
  .foot {{ text-align: center; color: #6b7280; font-size: 12px; margin-top: 16px; }}
  @media print {{ body {{ background: #fff; padding: 0; }} .receipt {{ box-shadow: none; }} }}
</style></head>
<body><div class="receipt">
  <h1>{e(config.STORE_NAME)}</h1>
  <div class="meta">Receipt {e(sale.get('receipt_no') or '-')}<br>{e(_when(sale['created_at']))}
    {('<br>Customer: ' + e(sale['customer_name'])) if sale.get('customer_name') else ''}</div>
  {void_banner}
  <table>{''.join(item_rows)}</table>
  <table style="margin-top:12px">{summary_rows}</table>
  <p class="meta">Paid by {e(sale['payment_label'])}</p>
  <p class="foot">Thank you for shopping with us!</p>
</div></body></html>"""
