"""Resend-backed purchase-receipt email.

Matches the visual style of the existing Spark AI verification email
(``app/emails/verification_email.py``) so the user gets a coherent
brand experience. The Resend API key is reused from that module —
hardcoded there today; when the project moves it to an env var,
this module picks it up for free.

This module exposes a single public function: ``send_receipt_email``.
The HTML template is rendered inline so we don't add another file just
to hold a string — receipts have a stable schema and one template
covers them.

Failure policy: we never raise from ``send_receipt_email``. The
caller (the post-payment watcher) needs to finish persisting the
receipt to disk even if Resend is down — so we return a dict with
``sent: bool`` and an ``error`` field, and let the caller decide.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)

# The Spark AI Resend integration. We reuse the same API key that the
# verification-email module set, so a single source of truth controls
# email auth. If that module hasn't been imported yet (e.g. running a
# bare unit test), fall back to the env var.
try:
    from app.emails import verification_email as _existing  # noqa: F401
    # The existing module sets ``resend.api_key`` at import time. Nothing else to do.
except Exception:
    logger.debug("commerce.email: app.emails.verification_email not importable; using RESEND_API_KEY env if set")

import resend  # type: ignore

_API_KEY_FROM_ENV = os.getenv("RESEND_API_KEY")
if _API_KEY_FROM_ENV and not getattr(resend, "api_key", None):
    resend.api_key = _API_KEY_FROM_ENV

# Brand defaults — sender domain and recipient. Override via env if needed.
DEFAULT_SENDER = os.getenv("SPARK_RECEIPT_FROM", "Spark AI <no-reply@siddhantyadav.com.np>")
DEFAULT_RECIPIENT = os.getenv("SPARK_USER_EMAIL", "siddthecoder@gmail.com")


# ── Public API ─────────────────────────────────────────────────────────────

def send_receipt_email(
    receipt: dict,
    *,
    to_email: Optional[str] = None,
    user_name: str = "there",
    icon_url: Optional[str] = None,
) -> dict[str, Any]:
    """Send a purchase confirmation email via Resend.

    Returns ``{"sent": bool, "id": str | None, "error": str | None}``.
    Never raises. The caller (watcher) writes whatever we return into the
    saved receipt so the user can debug delivery issues later.
    """
    to = to_email or DEFAULT_RECIPIENT
    try:
        html = _render_receipt_html(receipt, user_name=user_name, icon_url=icon_url)
        subject = _subject_for(receipt)
        params = {
            "from": DEFAULT_SENDER,
            "to": [to],
            "subject": subject,
            "html": html,
        }
        resp = resend.Emails.send(params)  # type: ignore[attr-defined]
        # Resend returns an object with .id (or a dict, depending on SDK version).
        email_id = getattr(resp, "id", None) or (resp.get("id") if isinstance(resp, dict) else None)
        logger.info("commerce.email: receipt sent to %s (id=%s)", to, email_id)
        return {"sent": True, "id": email_id, "error": None, "to": to}
    except Exception as e:
        logger.exception("commerce.email: receipt send failed")
        return {"sent": False, "id": None, "error": str(e), "to": to}


# ── Template ───────────────────────────────────────────────────────────────

def _subject_for(receipt: dict) -> str:
    src = (receipt.get("source") or "").capitalize() or "Order"
    order_id = receipt.get("order_id")
    if order_id:
        return f"Your {src} order #{order_id} is confirmed"
    return f"Your {src} order is confirmed"


def _money(receipt: dict) -> str:
    total = receipt.get("total")
    currency = receipt.get("currency") or ""
    if total is None:
        return ""
    if isinstance(total, (int, float)):
        total = f"{total:,.2f}"
    return f"{currency} {total}".strip()


def _format_item_price(item: dict) -> str:
    price = item.get("price") or item.get("line_total") or item.get("total") or ""
    if price == "":
        return ""
    currency = str(item.get("currency") or "").strip()
    if isinstance(price, (int, float)):
        price_text = f"{price:,.2f}"
    else:
        price_text = str(price).strip()
    if currency and currency.lower() not in price_text.lower():
        return f"{currency} {price_text}".strip()
    return price_text


def _item_meta(item: dict) -> str:
    parts: list[str] = []
    seller = str(item.get("seller") or item.get("seller_name") or "").strip()
    brand = str(item.get("brand") or item.get("brand_name") or "").strip()
    sku = str(item.get("sku") or item.get("simple_sku") or "").strip()
    item_id = str(item.get("item_id") or "").strip()
    if seller:
        parts.append(f"Seller: {seller}")
    if brand and brand.lower() != "no brand":
        parts.append(f"Brand: {brand}")
    if sku:
        parts.append(f"SKU: {sku}")
    if item_id:
        parts.append(f"Item ID: {item_id}")
    return " · ".join(parts)


def _items_block(receipt: dict) -> str:
    items = receipt.get("items") or []
    if not items:
        return ""
    rows = []
    for it in items:
        name = str(it.get("name") or "").strip()
        qty = it.get("qty") or it.get("quantity") or ""
        price = _format_item_price(it)
        meta = _item_meta(it)
        meta_html = (
            f'<div style="margin-top:4px;color:#94a3b8;font-size:12px;line-height:1.4;">{_escape(meta)}</div>'
            if meta else ""
        )
        rows.append(
            f"""
            <tr>
                <td style="padding:12px 0;border-bottom:1px solid #f1f5f9;color:#1e293b;font-size:14px;line-height:1.45;">
                    <div style="font-weight:600;">{_escape(name)}</div>
                    {meta_html}
                </td>
                <td style="padding:12px 0;border-bottom:1px solid #f1f5f9;color:#64748b;font-size:13px;text-align:center;vertical-align:top;">{_escape(qty)}</td>
                <td style="padding:12px 0;border-bottom:1px solid #f1f5f9;color:#1e293b;font-size:14px;text-align:right;vertical-align:top;font-weight:600;">{_escape(price)}</td>
            </tr>
            """
        )
    return f"""
    <div style="margin-top:18px;">
        <div style="font-size:12px;color:#1e40af;text-transform:uppercase;letter-spacing:1px;font-weight:700;margin-bottom:8px;">Products in this order</div>
        <table style="width:100%;border-collapse:collapse;">
            <thead>
                <tr>
                    <th style="text-align:left;font-size:11px;color:#94a3b8;text-transform:uppercase;letter-spacing:1px;padding-bottom:8px;">Product</th>
                    <th style="text-align:center;font-size:11px;color:#94a3b8;text-transform:uppercase;letter-spacing:1px;padding-bottom:8px;">Qty</th>
                    <th style="text-align:right;font-size:11px;color:#94a3b8;text-transform:uppercase;letter-spacing:1px;padding-bottom:8px;">Line total</th>
                </tr>
            </thead>
            <tbody>
                {"".join(rows)}
            </tbody>
        </table>
    </div>
    """


def _escape(s: Any) -> str:
    if s is None:
        return ""
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _render_receipt_html(receipt: dict, *, user_name: str, icon_url: Optional[str]) -> str:
    year = datetime.now().year
    source = (receipt.get("source") or "your order").capitalize()
    order_id = receipt.get("order_id") or "—"
    total = _money(receipt) or "—"
    source_url = receipt.get("source_url") or ""
    eta = receipt.get("eta") or receipt.get("delivery_eta") or ""
    address = receipt.get("shipping_address") or ""
    items_html = _items_block(receipt)
    logo_html = (
        f'<img src="{icon_url}" alt="Spark AI" style="width:32px;height:32px;">'
        if icon_url else "✦"
    )

    # Stylistically aligned with verification_email.py — same wave header,
    # color palette, footer treatment.
    return f"""\
<!DOCTYPE html>
<html>
<head>
<style>
body {{ margin:0; padding:0; background:linear-gradient(135deg,#f0f9ff 0%,#e0f2fe 100%); font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','Helvetica Neue',Arial,sans-serif; }}
.wrapper {{ width:100%; padding:30px 20px; background:linear-gradient(135deg,#f0f9ff 0%,#e0f2fe 100%); }}
.card {{ max-width:580px; margin:0 auto; background:#ffffff; border-radius:16px; overflow:hidden; box-shadow:0 20px 60px rgba(59,130,246,0.08); border:1px solid rgba(147,197,253,0.15); }}
.wave-header {{ position:relative; height:110px; background:linear-gradient(135deg,#dbeafe 0%,#bfdbfe 50%,#93c5fd 100%); overflow:hidden; }}
.wave-header::before {{ content:''; position:absolute; bottom:0; left:0; width:100%; height:100%; background:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1200 120'%3E%3Cpath fill='%23ffffff' d='M0,64 C240,96 480,32 720,64 C960,96 1200,32 1200,32 L1200,120 L0,120 Z'/%3E%3C/svg%3E") no-repeat bottom; background-size:cover; }}
.logo {{ padding:24px 0 0 32px; font-size:24px; font-weight:700; color:#1e3a8a; letter-spacing:-0.5px; position:relative; z-index:1; display:flex; align-items:center; gap:10px; }}
.content {{ padding:24px 32px 28px; color:#1e293b; }}
.greeting {{ font-size:16px; color:#475569; margin-bottom:14px; line-height:1.5; }}
.greeting strong {{ color:#1e3a8a; font-weight:600; }}
.message {{ font-size:14px; color:#64748b; line-height:1.6; margin-bottom:20px; }}
.order-box {{ margin:18px 0; padding:18px; background:linear-gradient(135deg,#eff6ff 0%,#dbeafe 100%); border:1px solid #93c5fd; border-radius:12px; }}
.order-row {{ display:flex; justify-content:space-between; padding:6px 0; font-size:14px; }}
.order-label {{ color:#60a5fa; font-size:11px; text-transform:uppercase; letter-spacing:1px; font-weight:600; }}
.order-value {{ color:#1e40af; font-weight:600; }}
.total-row {{ margin-top:10px; padding-top:12px; border-top:1px dashed #93c5fd; font-size:18px; }}
.button {{ display:inline-block; background:linear-gradient(135deg,#3b82f6 0%,#2563eb 100%); color:#ffffff; text-align:center; padding:13px 32px; border-radius:10px; text-decoration:none; font-weight:600; font-size:14px; box-shadow:0 4px 12px rgba(59,130,246,0.2); }}
.footer {{ text-align:center; padding:20px 32px; background:#f8fafc; font-size:12px; color:#94a3b8; border-top:1px solid #e0f2fe; }}
</style>
</head>
<body>
<div class="wrapper">
  <div class="card">
    <div class="wave-header">
      <div class="logo">{logo_html} Spark AI</div>
    </div>
    <div class="content">
      <div class="greeting">Hello <strong>{_escape(user_name)}</strong>,</div>
      <div class="message">
        Your purchase on <strong>{_escape(source)}</strong> just went through.
        Here's the confirmation — Spark AI saved a full copy locally too.
      </div>
      <div class="order-box">
        <div class="order-row">
          <span class="order-label">Order</span>
          <span class="order-value">#{_escape(order_id)}</span>
        </div>
        <div class="order-row total-row">
          <span class="order-label">Total</span>
          <span class="order-value">{_escape(total)}</span>
        </div>
        { f'<div class="order-row"><span class="order-label">Delivery ETA</span><span class="order-value">{_escape(eta)}</span></div>' if eta else "" }
        { f'<div class="order-row"><span class="order-label">Ship to</span><span class="order-value">{_escape(address)}</span></div>' if address else "" }
      </div>
      {items_html}
      { f'<div style="text-align:center;margin:24px 0 8px;"><a href="{_escape(source_url)}" class="button">View on {_escape(source)}</a></div>' if source_url else "" }
      <div style="margin-top:18px;font-size:12px;color:#94a3b8;">
        Spark saved the receipt, screenshot, and page HTML locally for your records.
      </div>
    </div>
    <div class="footer">
      <div>© {year} Spark AI · Purchase confirmation</div>
    </div>
  </div>
</div>
</body>
</html>
"""


__all__ = ["send_receipt_email", "DEFAULT_SENDER", "DEFAULT_RECIPIENT"]
