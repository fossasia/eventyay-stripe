from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from eventyay.base.payment import PaymentException

from eventyay_stripe.payment import StripeMethod


@pytest.mark.parametrize("error", [ImportError("missing service"), ValueError("invalid fee")])
def test_business_fee_resolution_failure_is_payment_error(error):
    method = StripeMethod.__new__(StripeMethod)
    method.event = SimpleNamespace(organizer=object())
    payment = SimpleNamespace(amount=Decimal("10.00"), order=object())
    subscription_model = MagicMock()
    subscription_model.objects.filter.return_value.exclude.return_value.select_related.return_value.first.return_value = None

    with (
        patch("eventyay_stripe.payment.apps.is_installed", return_value=True),
        patch("eventyay_stripe.payment.apps.get_model", return_value=subscription_model),
        patch("eventyay_stripe.payment.import_module") as import_module,
    ):
        if isinstance(error, ImportError):
            import_module.side_effect = error
        else:
            import_module.return_value.resolve_fee_settings.side_effect = error
        with pytest.raises(PaymentException) as exc_info:
            method._business_platform_fee(payment)

    assert exc_info.value.__cause__ is error


def test_missing_business_subscription_model_is_payment_error():
    method = StripeMethod.__new__(StripeMethod)
    method.event = SimpleNamespace(organizer=object())
    payment = SimpleNamespace(amount=Decimal("10.00"), order=object())
    error = LookupError("missing Subscription model")

    with (
        patch("eventyay_stripe.payment.apps.is_installed", return_value=True),
        patch("eventyay_stripe.payment.apps.get_model", side_effect=error),
    ):
        with pytest.raises(PaymentException) as exc_info:
            method._business_platform_fee(payment)

    assert exc_info.value.__cause__ is error
