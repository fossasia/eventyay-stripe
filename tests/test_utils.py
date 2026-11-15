from decimal import Decimal

from eventyay_stripe.utils import (
    stripe_decimal_to_int,
    stripe_int_to_decimal,
    stripe_key_is_valid,
    stripe_statement_descriptor,
    stripe_webhook_signature_header,
)


def test_stripe_key_is_valid_accepts_known_prefixes():
    assert stripe_key_is_valid("sk_live_abc", ["sk_", "rk_"])
    assert stripe_key_is_valid("rk_test_abc", ["sk_", "rk_"])
    assert stripe_key_is_valid("pk_test_abc", ["pk_"])
    assert not stripe_key_is_valid("skihaspartialprefix", ["sk_"])
    assert not stripe_key_is_valid("ihasnoprefix", ["pk_"])
    assert not stripe_key_is_valid("ihaspostfixsk_", ["sk_"])


def test_stripe_statement_descriptor_sanitizes_and_truncates():
    assert stripe_statement_descriptor("dummy", "FOOBAR", "Mega Conf") == "DUMMY-FOOBAR Mega Conf"
    assert stripe_statement_descriptor("dummy", "FOOBAR", "Mega-Conf!") == "DUMMY-FOOBAR MegaConf"
    assert len(stripe_statement_descriptor("dummy", "FOOBAR", "A very long event name here", length=22)) <= 22


def test_stripe_decimal_to_int_uses_currency_places():
    assert stripe_decimal_to_int(Decimal("13.37"), 2) == 1337
    assert stripe_decimal_to_int(Decimal("13"), 0) == 13


def test_stripe_int_to_decimal_uses_currency_places():
    assert stripe_int_to_decimal(1337, 2) == Decimal("13.37")
    assert stripe_int_to_decimal(500, 2) == Decimal("5.00")
    assert stripe_int_to_decimal(13, 0) == Decimal("13")
    assert stripe_int_to_decimal(1337, 3) == Decimal("1.337")


def test_stripe_webhook_signature_header_is_stable_for_a_timestamp():
    header = stripe_webhook_signature_header("{}", "whsec_123", timestamp=1)
    assert header.startswith("t=1,v1=")
    assert stripe_webhook_signature_header("{}", "whsec_123", timestamp=1) == header
    assert stripe_webhook_signature_header("{}", "whsec_other", timestamp=1) != header
