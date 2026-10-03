import json
import os
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

if not os.environ.get("DJANGO_SETTINGS_MODULE"):
    pytest.skip("Django settings are not configured", allow_module_level=True)

import stripe
from django.test import RequestFactory
from django.utils.timezone import now
from django_scopes import scope
from eventyay.base.models import Event, Order, OrderRefund, Organizer
from eventyay.base.payment import PaymentException
from stripe.error import APIConnectionError, CardError

from eventyay_stripe.payment import StripeCreditCard


@pytest.fixture
def env():
    o = Organizer.objects.create(name="Dummy", slug="dummy")
    with scope(organizer=o):
        event = Event.objects.create(
            organizer=o,
            name="Mega Conf",
            slug="dummy",
            date_from=now(),
            live=True,
            currency="EUR",
        )
        event.settings.set("payment_stripe_secret_key", "sk_test_123")
        event.settings.set("payment_stripe_publishable_key", "pk_test_123")
        o1 = Order.objects.create(
            code="FOOBAR",
            event=event,
            email="dummy@dummy.test",
            status=Order.STATUS_PENDING,
            datetime=now(),
            expires=now() + timedelta(days=10),
            total=Decimal("13.37"),
        )
        yield event, o1


@pytest.fixture(autouse=True)
def no_messages(monkeypatch):
    monkeypatch.setattr("django.contrib.messages.api.add_message", lambda *args, **kwargs: None)


@pytest.fixture
def factory():
    return RequestFactory()


class MockedRefunds:
    pass


class MockedCharge:
    status = ""
    paid = False
    id = "ch_123345345"
    refunds = MockedRefunds()

    def refresh(self):
        pass


class Object:
    pass


class MockedPaymentintent:
    status = ""
    id = "pi_1EUon12Tb35ankTnZyvC3SdE"
    charges = Object()
    charges.data = [MockedCharge()]
    last_payment_error = None

    @property
    def latest_charge(self):
        return self.charges.data[0]


@pytest.mark.django_db
def test_perform_success(env, factory, monkeypatch):
    event, order = env

    def paymentintent_create(**kwargs):
        assert kwargs["amount"] == 1337
        assert kwargs["currency"] == "eur"
        assert kwargs["payment_method"] == "pm_189fTT2eZvKYlo2CvJKzEzeu"
        assert kwargs["description"] == "DUMMY-FOOBAR"
        assert kwargs["statement_descriptor_suffix"] == "DUMMY-FOOBAR Mega Conf"
        c = MockedPaymentintent()
        c.status = "succeeded"
        c.charges.data[0].paid = True
        return c

    monkeypatch.setattr("stripe.PaymentIntent.create", paymentintent_create)
    monkeypatch.setattr(
        "eventyay_stripe.payment.build_absolute_uri",
        lambda *args, **kwargs: "https://example.test/stripe/return",
    )
    prov = StripeCreditCard(event)
    prov._init_api()

    assert stripe.api_version == "2024-11-20.acacia"
    app_name = getattr(stripe.app_info, "name", None)
    if app_name is None and isinstance(stripe.app_info, dict):
        app_name = stripe.app_info.get("name")
    assert app_name == "eventyay-stripe"

    req = factory.post(
        "/", {"stripe_payment_method_id": "pm_189fTT2eZvKYlo2CvJKzEzeu", "stripe_last4": "4242", "stripe_brand": "Visa"}
    )
    req.session = {}
    prov.checkout_prepare(req, {})
    assert "payment_stripe_card_payment_method_id" in req.session
    payment = order.payments.create(provider="stripe_cc", amount=order.total)
    prov.execute_payment(req, payment)
    order.refresh_from_db()
    assert order.status == Order.STATUS_PAID


@pytest.mark.django_db
def test_statement_descriptor_uses_sanitized_event_name(env):
    event, order = env
    payment = order.payments.create(provider="stripe_cc", amount=order.total)
    prov = StripeCreditCard(event)

    assert prov.statement_descriptor(payment) == "DUMMY-FOOBAR Mega Conf"


@pytest.mark.django_db
def test_connect_fee_is_zero_without_business_plugin(env):
    event, order = env
    event.settings.set("payment_stripe_connect_client_id", "ca_test")
    event.settings.set("payment_stripe_connect_user_id", "acct_test")
    event.settings.set("payment_stripe_connect_app_fee_percent", "5.00")
    provider = StripeCreditCard(event)
    payment = order.payments.create(provider="stripe_cc", amount=order.total)

    with patch("eventyay_stripe.payment.apps.is_installed", return_value=False):
        assert "application_fee_amount" not in provider._prepare_api_connect_args(payment)


@pytest.mark.django_db
def test_connect_fee_uses_business_rate_and_cap(env):
    event, order = env
    event.settings.set("payment_stripe_connect_client_id", "ca_test")
    event.settings.set("payment_stripe_connect_user_id", "acct_test")
    provider = StripeCreditCard(event)
    payment = MagicMock(amount=Decimal("10.00"))
    payment.order.total = Decimal("20.00")
    payment.order.positions.all.return_value = [
        SimpleNamespace(price=Decimal("18.00"), tax_value=Decimal("2.00")),
        SimpleNamespace(price=Decimal("2.00"), tax_value=None),
    ]
    subscription_model = MagicMock()
    subscription_model.objects.filter.return_value.exclude.return_value.select_related.return_value.first.return_value = SimpleNamespace(
        tier_version=object()
    )
    resolve_fee_settings = MagicMock(return_value=(Decimal("10.00"), Decimal("1.00"), True))

    with (
        patch("eventyay_stripe.payment.apps.is_installed", return_value=True),
        patch("eventyay_stripe.payment.apps.get_model", return_value=subscription_model),
        patch(
            "eventyay_stripe.payment.import_module",
            return_value=SimpleNamespace(resolve_fee_settings=resolve_fee_settings),
        ),
    ):
        assert provider._prepare_api_connect_args(payment)["application_fee_amount"] == 50

    resolve_fee_settings.assert_called_once()


@pytest.mark.django_db
def test_payment_intent_description_uses_raw_event_name(env, monkeypatch):
    event, order = env
    payment = order.payments.create(provider="stripe_cc", amount=order.total)
    prov = StripeCreditCard(event)
    captured = {}

    def paymentintent_create(**kwargs):
        captured.update(kwargs)
        return MockedPaymentintent()

    monkeypatch.setattr("stripe.PaymentIntent.create", paymentintent_create)
    monkeypatch.setattr(
        "eventyay_stripe.payment.build_absolute_uri",
        lambda *args, **kwargs: "https://example.test/stripe/return",
    )

    prov.intent_factory.create_payment_intent(
        payment=payment,
        event=event,
        payment_method_id="pm_test",
        method="card",
        confirmation_method="manual",
        idempotency_key_seed="seed",
        kwargs={
            "statement_descriptor_suffix": prov.statement_descriptor(payment),
            **prov.api_config,
        },
    )

    assert captured["description"] == "DUMMY-FOOBAR"
    assert captured["statement_descriptor_suffix"] == "DUMMY-FOOBAR Mega Conf"


@pytest.mark.django_db
def test_perform_success_zero_decimal_currency(env, factory, monkeypatch):
    event, order = env
    event.currency = "JPY"
    event.save()

    def paymentintent_create(**kwargs):
        assert kwargs["amount"] == 13
        assert kwargs["currency"] == "jpy"
        assert kwargs["payment_method"] == "pm_189fTT2eZvKYlo2CvJKzEzeu"
        c = MockedPaymentintent()
        c.status = "succeeded"
        c.charges.data[0].paid = True
        return c

    monkeypatch.setattr("stripe.PaymentIntent.create", paymentintent_create)
    monkeypatch.setattr(
        "eventyay_stripe.payment.build_absolute_uri",
        lambda *args, **kwargs: "https://example.test/stripe/return",
    )
    prov = StripeCreditCard(event)
    req = factory.post(
        "/", {"stripe_payment_method_id": "pm_189fTT2eZvKYlo2CvJKzEzeu", "stripe_last4": "4242", "stripe_brand": "Visa"}
    )
    req.session = {}
    prov.checkout_prepare(req, {})
    assert "payment_stripe_card_payment_method_id" in req.session
    payment = order.payments.create(provider="stripe_cc", amount=order.total)
    prov.execute_payment(req, payment)
    order.refresh_from_db()
    assert order.status == Order.STATUS_PAID


@pytest.mark.django_db
def test_perform_card_error(env, factory, monkeypatch):
    event, order = env

    def paymentintent_create(**kwargs):
        raise CardError(message="Foo", param="foo", code=100)

    monkeypatch.setattr("stripe.PaymentIntent.create", paymentintent_create)
    monkeypatch.setattr(
        "eventyay_stripe.payment.build_absolute_uri",
        lambda *args, **kwargs: "https://example.test/stripe/return",
    )
    prov = StripeCreditCard(event)
    req = factory.post(
        "/", {"stripe_payment_method_id": "pm_189fTT2eZvKYlo2CvJKzEzeu", "stripe_last4": "4242", "stripe_brand": "Visa"}
    )
    req.session = {}
    prov.checkout_prepare(req, {})
    assert "payment_stripe_card_payment_method_id" in req.session
    with pytest.raises(PaymentException):
        payment = order.payments.create(provider="stripe_cc", amount=order.total)
        prov.execute_payment(req, payment)
    order.refresh_from_db()
    assert order.status == Order.STATUS_PENDING


@pytest.mark.django_db
def test_perform_stripe_error(env, factory, monkeypatch):
    event, order = env

    def paymentintent_create(**kwargs):
        raise CardError(message="Foo", param="foo", code=100)

    monkeypatch.setattr("stripe.PaymentIntent.create", paymentintent_create)
    monkeypatch.setattr(
        "eventyay_stripe.payment.build_absolute_uri",
        lambda *args, **kwargs: "https://example.test/stripe/return",
    )
    prov = StripeCreditCard(event)
    req = factory.post(
        "/", {"stripe_payment_method_id": "pm_189fTT2eZvKYlo2CvJKzEzeu", "stripe_last4": "4242", "stripe_brand": "Visa"}
    )
    req.session = {}
    prov.checkout_prepare(req, {})
    assert "payment_stripe_card_payment_method_id" in req.session
    with pytest.raises(PaymentException):
        payment = order.payments.create(provider="stripe_cc", amount=order.total)
        prov.execute_payment(req, payment)
    order.refresh_from_db()
    assert order.status == Order.STATUS_PENDING


@pytest.mark.django_db
def test_perform_failed(env, factory, monkeypatch):
    event, order = env

    def paymentintent_create(**kwargs):
        assert kwargs["amount"] == 1337
        assert kwargs["currency"] == "eur"
        assert kwargs["payment_method"] == "pm_189fTT2eZvKYlo2CvJKzEzeu"
        c = MockedPaymentintent()
        c.status = "failed"
        c.failure_message = "Foo"
        c.charges.data[0].paid = False
        c.last_payment_error = Object()
        c.last_payment_error.message = "Foo"
        return c

    monkeypatch.setattr("stripe.PaymentIntent.create", paymentintent_create)
    monkeypatch.setattr(
        "eventyay_stripe.payment.build_absolute_uri",
        lambda *args, **kwargs: "https://example.test/stripe/return",
    )
    prov = StripeCreditCard(event)
    req = factory.post(
        "/", {"stripe_payment_method_id": "pm_189fTT2eZvKYlo2CvJKzEzeu", "stripe_last4": "4242", "stripe_brand": "Visa"}
    )
    req.session = {}
    prov.checkout_prepare(req, {})
    assert "payment_stripe_card_payment_method_id" in req.session
    with pytest.raises(PaymentException):
        payment = order.payments.create(provider="stripe_cc", amount=order.total)
        prov.execute_payment(req, payment)
    order.refresh_from_db()
    assert order.status == Order.STATUS_PENDING


@pytest.mark.django_db
def test_refund_success(env, factory, monkeypatch):
    event, order = env

    def refund_create(**kwargs):
        assert kwargs["charge"] == "ch_123345345"
        assert kwargs["amount"] == 1337
        r = Object()
        r.id = "re_foo"
        r.status = "succeeded"
        return r

    monkeypatch.setattr("stripe.Refund.create", refund_create)
    order.status = Order.STATUS_PAID
    p = order.payments.create(provider="stripe_cc", amount=order.total, info=json.dumps({"id": "ch_123345345"}))
    order.save()
    prov = StripeCreditCard(event)
    refund = order.refunds.create(
        provider="stripe_cc",
        amount=order.total,
        payment=p,
    )
    prov.execute_refund(refund)
    refund.refresh_from_db()
    assert refund.state == OrderRefund.REFUND_STATE_DONE


@pytest.mark.django_db
def test_refund_unavailable(env, factory, monkeypatch):
    event, order = env

    def refund_create(**kwargs):
        raise APIConnectionError(message="Foo")

    monkeypatch.setattr("stripe.Refund.create", refund_create)
    order.status = Order.STATUS_PAID
    p = order.payments.create(provider="stripe_cc", amount=order.total, info=json.dumps({"id": "ch_123345345"}))
    order.save()
    prov = StripeCreditCard(event)
    refund = order.refunds.create(provider="stripe_cc", amount=order.total, payment=p)
    with pytest.raises(PaymentException):
        prov.execute_refund(refund)
    refund.refresh_from_db()
    assert refund.state != OrderRefund.REFUND_STATE_DONE
