from decimal import Decimal

import stripe

from eventyay_stripe.utils import (
    stripe_charge_source_type,
    stripe_decimal_to_int,
    stripe_key_is_valid,
    stripe_object_to_dict,
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


def test_stripe_webhook_signature_header_is_stable_for_a_timestamp():
    header = stripe_webhook_signature_header("{}", "whsec_123", timestamp=1)
    assert header.startswith("t=1,v1=")
    assert stripe_webhook_signature_header("{}", "whsec_123", timestamp=1) == header
    assert stripe_webhook_signature_header("{}", "whsec_other", timestamp=1) != header


def _stripe_object(data):
    return stripe.StripeObject.construct_from(data, "sk_test_dummy")


def test_stripe_object_to_dict_supports_dict_methods_on_api_objects():
    account = stripe_object_to_dict(
        _stripe_object({"country": "DE", "settings": {"dashboard": {"display_name": "Mega Conf"}}})
    )

    assert account.get("country") == "DE"
    assert account.get("email") is None
    assert account.get("settings", {}).get("dashboard", {}).get("display_name") == "Mega Conf"


def test_stripe_object_to_dict_keeps_plain_dicts_and_handles_none():
    data = {"country": "DE"}

    assert stripe_object_to_dict(data) is data
    assert stripe_object_to_dict(None) == {}


class _ObjectWithoutDictMethods:
    """Stand-in for a stripe-python 15 StripeObject: supports ``in``, ``[]`` and ``to_dict()`` but not ``.get()``."""

    def __init__(self, data):
        self._data = data

    def __contains__(self, key):
        return key in self._data

    def __getitem__(self, key):
        value = self._data[key]
        return _ObjectWithoutDictMethods(value) if isinstance(value, dict) else value

    def to_dict(self):
        return self._data


def test_stripe_object_to_dict_converts_objects_without_dict_methods():
    account = stripe_object_to_dict(_ObjectWithoutDictMethods({"country": "DE", "settings": {"dashboard": {}}}))

    assert account.get("country") == "DE"
    assert account.get("settings", {}).get("dashboard") == {}


def test_stripe_charge_source_type():
    assert stripe_charge_source_type(_stripe_object({"source": {"type": "sofort"}})) == "sofort"
    assert stripe_charge_source_type(_stripe_object({"source": {"object": "card"}})) == "card"
    assert stripe_charge_source_type(_stripe_object({"source": None})) == "card"
    assert stripe_charge_source_type(_stripe_object({})) == "card"


def test_stripe_charge_source_type_uses_payment_method_details_without_source():
    charge = {"source": None, "payment_method_details": {"type": "ideal", "ideal": {"bank": "ing"}}}

    assert stripe_charge_source_type(_stripe_object(charge)) == "ideal"
    assert stripe_charge_source_type(_ObjectWithoutDictMethods(charge)) == "ideal"
    assert stripe_charge_source_type(_ObjectWithoutDictMethods({"source": {"type": "sofort"}})) == "sofort"
