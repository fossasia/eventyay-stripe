from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from django.db import DatabaseError
from eventyay.base.payment import PaymentException

from eventyay_stripe.payment import MultiplePlatformFeePoliciesError, StripeMethod


@pytest.mark.parametrize("error", [ImportError("missing service"), ValueError("invalid fee")])
def test_platform_fee_resolution_failure_is_payment_error(error):
    method = StripeMethod.__new__(StripeMethod)
    method.event = SimpleNamespace(organizer=object())
    payment = SimpleNamespace(amount=Decimal("10.00"), order=object())
    with patch("eventyay_stripe.payment.resolve_platform_fee_policy", side_effect=error):
        with pytest.raises(PaymentException) as exc_info:
            method._platform_fee(payment)

    assert exc_info.value.__cause__ is error


def test_conflicting_platform_fee_policies_are_payment_error():
    method = StripeMethod.__new__(StripeMethod)
    method.event = SimpleNamespace(organizer=object())
    payment = SimpleNamespace(amount=Decimal("10.00"), order=object())
    error = MultiplePlatformFeePoliciesError("multiple platform fee policies")

    with patch("eventyay_stripe.payment.resolve_platform_fee_policy", side_effect=error):
        with pytest.raises(PaymentException) as exc_info:
            method._platform_fee(payment)

    assert exc_info.value.__cause__ is error


def test_platform_fee_position_lookup_failure_is_payment_error():
    method = StripeMethod.__new__(StripeMethod)
    method.event = SimpleNamespace(organizer=object())
    error = DatabaseError("position lookup failed")
    payment = MagicMock(amount=Decimal("10.00"))
    payment.order.positions.all.side_effect = error
    policy = SimpleNamespace(percentage=Decimal("10.00"), maximum_fee=Decimal("1.00"))
    with patch("eventyay_stripe.payment.resolve_platform_fee_policy", return_value=policy):
        with pytest.raises(PaymentException) as exc_info:
            method._platform_fee(payment)

    assert exc_info.value.__cause__ is error
