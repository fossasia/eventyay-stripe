import hashlib
import hmac
import re
import time


def stripe_key_is_valid(value: str, prefixes: list[str]) -> bool:
    """Return True when a Stripe key starts with one of the expected prefixes."""
    return any(value.startswith(prefix) for prefix in prefixes)


def stripe_statement_descriptor(event_slug: str, order_code: str, event_name: object, length: int = 22) -> str:
    """Build a Stripe statement descriptor from event and order identifiers."""
    eventname = re.sub("[^a-zA-Z0-9 ]", "", str(event_name))
    return f"{event_slug.upper()}-{order_code} {eventname}"[:length]


def stripe_decimal_to_int(amount, places: int) -> int:
    """Convert a decimal amount to Stripe's integer minor units."""
    return int(amount * 10**places)


def stripe_webhook_signature_header(payload: str, secret: str, timestamp: int | None = None) -> str:
    """Build a Stripe-Signature header value for webhook tests."""
    timestamp = timestamp if timestamp is not None else int(time.time())
    signed_payload = f"{timestamp}.{payload}"
    signature = hmac.new(secret.encode("utf-8"), signed_payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={signature}"


def stripe_object_to_dict(obj) -> dict:
    """Return a Stripe API object as a dict that supports dict methods such as ``.get()``.

    Before stripe-python 15, ``StripeObject`` subclassed ``dict`` and is returned as is.
    From 15 on it no longer does, and ``to_dict()`` converts it recursively.
    """
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    return obj.to_dict()


def stripe_charge_source_type(charge) -> str:
    """Return the payment method type of a charge.

    Read the legacy source when the charge has one, then the payment method details, and fall back to ``card``.
    """
    source = stripe_object_to_dict(charge["source"] if "source" in charge else None)
    source_type = source.get("type") or source.get("object")
    if source_type:
        return source_type
    details = stripe_object_to_dict(charge["payment_method_details"] if "payment_method_details" in charge else None)
    return details.get("type") or "card"


def shredded_stripe_source(source) -> dict | None:
    """Keep only operational Stripe source fields. Ignore missing or null sources."""
    if not isinstance(source, dict):
        return None

    card = source.get("card")
    card_data = card if isinstance(card, dict) else {}
    return {
        "id": source.get("id"),
        "type": source.get("type"),
        "brand": source.get("brand"),
        "last4": source.get("last4"),
        "bank_name": source.get("bank_name"),
        "bank": source.get("bank"),
        "bic": source.get("bic"),
        "card": {
            "brand": card_data.get("brand"),
            "country": card_data.get("country"),
            "last4": card_data.get("last4"),
        },
    }


def shredded_stripe_payment_info(payload: dict) -> dict:
    """Build a privacy-safe copy of stored Stripe payment info."""
    new = {}
    source = shredded_stripe_source(payload.get("source"))
    if source is not None:
        new["source"] = source
    for key in ("amount", "currency", "status", "id"):
        if key in payload:
            new[key] = payload[key]
    new["_shredded"] = True
    return new
