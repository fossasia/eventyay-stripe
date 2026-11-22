"""Privacy, correlation, and fail-open behavior of plugin operational logs."""

import json
import logging
import sys
import types
import unittest.mock as mock
from http import HTTPStatus

import django
import pytest
import stripe
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.test import RequestFactory

from eventyay_stripe import operational_log
from eventyay_stripe.operational_log import (
    OUTCOME_FAILURE,
    OUTCOME_SUCCESS,
    bind_request_id,
    log_operation,
    log_plugin_loaded,
    reset_request_id,
    stripe_error_code,
    traced_job,
)


def _import_views():
    if "eventyay_stripe.views" in sys.modules:
        return sys.modules["eventyay_stripe.views"]

    django.setup()
    from django.core.cache import cache

    try:
        import eventyay_stripe.views as views_mod

        return views_mod
    except Exception:
        with (
            mock.patch.object(cache, "get", return_value=None),
            mock.patch.object(cache, "set", return_value=None),
        ):
            import eventyay_stripe.views as views_mod

            return views_mod


def _import_payment():
    if "eventyay_stripe.payment" in sys.modules:
        return sys.modules["eventyay_stripe.payment"]

    _import_views()
    return sys.modules["eventyay_stripe.payment"]


def _import_tasks():
    if "eventyay_stripe.tasks" in sys.modules:
        return sys.modules["eventyay_stripe.tasks"]

    _import_views()
    return sys.modules["eventyay_stripe.tasks"]


@pytest.fixture
def captured(monkeypatch):
    records = []

    def fake_log(level, action, extra=None):
        records.append((level, action, extra or {}))

    monkeypatch.setattr(operational_log, "_HOST_LOG_EVENT", None)
    monkeypatch.setattr(logging.getLogger("eventyay.plugins"), "log", fake_log)
    return records


def test_drops_email_token_and_unknown_fields(captured):
    log_operation(
        "plugin.loaded",
        OUTCOME_SUCCESS,
        backend="stripe",
        email="person@example.com",
        token="secret-token",
        body="{raw}",
        webhook_id=99,
        recipient_count=5,
        model="Order",
        order_code="ABC12",
        event_id=12,
    )
    assert len(captured) == 1
    extra = captured[0][2]
    assert extra["backend"] == "stripe"
    assert extra["model"] == "Order"
    assert extra["event_id"] == 12
    assert extra["outcome"] == "success"
    for forbidden in ("email", "token", "body", "webhook_id", "recipient_count", "order_code"):
        assert forbidden not in extra
    blob = str(extra)
    assert "person@example.com" not in blob
    assert "secret-token" not in blob


def test_rejects_unsafe_action_and_backend(captured):
    log_operation("has space", OUTCOME_SUCCESS, backend="stripe")
    assert captured == []

    log_operation("connection.request", OUTCOME_FAILURE, backend="pay pal", error_code="not safe")
    assert len(captured) == 1
    extra = captured[0][2]
    assert "backend" not in extra
    assert "error_code" not in extra
    assert "pay pal" not in str(captured)


def test_logging_failure_is_swallowed(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("log sink down")

    monkeypatch.setattr(operational_log, "_HOST_LOG_EVENT", None)
    monkeypatch.setattr(logging.getLogger("eventyay.plugins"), "log", boom)
    log_operation("plugin.loaded", OUTCOME_SUCCESS, backend="stripe")

    monkeypatch.setattr(operational_log, "_HOST_LOG_EVENT", boom)
    log_operation("plugin.loaded", OUTCOME_SUCCESS, backend="stripe")


def test_host_emitter_delegation_and_fallback(monkeypatch):
    host_calls = []
    fallback_calls = []

    def fake_host(component, action, outcome, **kwargs):
        host_calls.append((component, action, outcome, kwargs))

    def fake_log(level, action, extra=None):
        fallback_calls.append((level, action, extra or {}))

    monkeypatch.setattr(operational_log, "_HOST_LOG_EVENT", fake_host)
    monkeypatch.setattr(logging.getLogger("eventyay.plugins"), "log", fake_log)

    log_plugin_loaded("stripe")
    assert len(host_calls) == 1
    assert host_calls[0][:3] == ("plugins", "plugin.loaded", OUTCOME_SUCCESS)
    assert host_calls[0][3]["backend"] == "stripe"
    assert fallback_calls == []

    def failing_host(*args, **kwargs):
        raise RuntimeError("host emitter failed")

    monkeypatch.setattr(operational_log, "_HOST_LOG_EVENT", failing_host)
    log_operation("connection.request", OUTCOME_FAILURE, backend="stripe", error_code="timeout")
    assert len(fallback_calls) == 1
    assert fallback_calls[0][1] == "connection.request"
    assert fallback_calls[0][2]["error_code"] == "timeout"


def test_traced_job_correlates_job_id_across_outcomes(captured):
    class Retry(Exception):
        pass

    class FakeTask:
        request = types.SimpleNamespace(id="celery-task-42", retries=0)

        @traced_job("stripe_verify_domain")
        def run_ok(self):
            return "ok"

        @traced_job("stripe_verify_domain")
        def run_retry(self):
            raise Retry("later")

        @traced_job("stripe_verify_domain")
        def run_fail(self):
            raise RuntimeError("boom")

    task = FakeTask()
    assert task.run_ok() == "ok"
    assert [item[1] for item in captured] == ["job.start", "job.finish"]
    assert all(item[2]["job_id"] == "celery-task-42" for item in captured)

    captured.clear()
    with pytest.raises(Retry):
        task.run_retry()
    assert [item[1] for item in captured] == ["job.start", "job.retry"]
    assert captured[1][2]["error_code"] == "retry"
    assert all(item[2]["job_id"] == "celery-task-42" for item in captured)

    captured.clear()
    with pytest.raises(RuntimeError):
        task.run_fail()
    assert [item[1] for item in captured] == ["job.start", "job.fail"]
    assert captured[1][2]["error_code"] == "RuntimeError"
    assert all(item[2]["job_id"] == "celery-task-42" for item in captured)


def test_traced_job_handles_autoretry_for(captured):
    class AutoretryTask:
        autoretry_for = (ConnectionError,)
        max_retries = 3

        def __init__(self, retries):
            self.request = types.SimpleNamespace(id="celery-auto-7", retries=retries)

        @traced_job("stripe_verify_domain")
        def run(self):
            raise ConnectionError("network")

    with pytest.raises(ConnectionError):
        AutoretryTask(retries=1).run()
    assert [item[1] for item in captured] == ["job.start", "job.retry"]
    assert captured[1][2]["job_id"] == "celery-auto-7"
    assert captured[1][2]["error_code"] == "retry"
    assert captured[1][2]["retry_count"] == 1

    captured.clear()
    with pytest.raises(ConnectionError):
        AutoretryTask(retries=3).run()
    assert [item[1] for item in captured] == ["job.start", "job.fail"]
    assert captured[1][2]["job_id"] == "celery-auto-7"
    assert captured[1][2]["error_code"] == "ConnectionError"
    assert captured[1][2]["retry_count"] == 3

    captured.clear()

    @traced_job("plain_job")
    def plain():
        raise ConnectionError("network")

    with pytest.raises(ConnectionError):
        plain()
    assert [item[1] for item in captured] == ["job.start", "job.fail"]
    assert "job_id" not in captured[0][2]


def test_stripe_error_code_sanitizes_values():
    exc_with_code = stripe.StripeError("bad message", code="card_declined")
    assert stripe_error_code(exc_with_code) == "card_declined"

    exc_with_body = types.SimpleNamespace(code=None, json_body={"error": {"code": "rate_limit"}})
    assert stripe_error_code(exc_with_body) == "rate_limit"

    exc_unsafe = types.SimpleNamespace(code="unsafe code with spaces", json_body=None)
    assert stripe_error_code(exc_unsafe, "fallback_code") == "fallback_code"


def test_webhook_logs_final_outcome_after_dispatch(captured, monkeypatch):
    views = _import_views()
    factory = RequestFactory()
    payload = json.dumps(
        {
            "id": "evt_ok_1",
            "object": "event",
            "type": "charge.succeeded",
            "data": {"object": {"id": "ch_1", "object": "charge"}},
        }
    )

    monkeypatch.setattr(views, "get_stripe_secret_key", lambda: "sk_test_123")
    monkeypatch.setattr(views, "get_stripe_webhook_secret_key", lambda: "whsec_123")
    monkeypatch.setattr(views.stripe.Webhook, "construct_event", lambda *a, **kw: None)

    fake_rso = types.SimpleNamespace(order=types.SimpleNamespace(event=types.SimpleNamespace(pk=77), event_id=77))

    class FakeQuerySet:
        def filter(self, **kwargs):
            return self

        def first(self):
            return fake_rso

    monkeypatch.setattr(views.ReferencedStripeObject.objects, "select_related", lambda *a: FakeQuerySet())

    logs_during_dispatch = []

    def ok_handler(event, event_json, objid, rso):
        logs_during_dispatch.extend(captured)
        return HttpResponse(status=HTTPStatus.OK)

    monkeypatch.setattr(views, "charge_webhook", ok_handler)
    req = factory.post("/_stripe/webhook/", data=payload, content_type="application/json")
    req.META["HTTP_STRIPE_SIGNATURE"] = "sig"
    resp = views.webhook(req)

    assert resp.status_code == 200
    assert logs_during_dispatch == []
    assert len(captured) == 1
    assert captured[0][1] == "webhook.inbound"
    assert captured[0][2]["outcome"] == OUTCOME_SUCCESS
    assert captured[0][2]["status"] == 200
    assert captured[0][2]["event_id"] == 77
    assert captured[0][2]["object_id"] == "evt_ok_1"

    captured.clear()
    monkeypatch.setattr(
        views,
        "charge_webhook",
        lambda *a: HttpResponse("Lock timeout", status=HTTPStatus.SERVICE_UNAVAILABLE),
    )
    resp_503 = views.webhook(req)
    assert resp_503.status_code == 503
    assert len(captured) == 1
    assert captured[0][1] == "webhook.inbound"
    assert captured[0][2]["outcome"] == OUTCOME_FAILURE
    assert captured[0][2]["status"] == 503
    assert captured[0][2]["error_code"] == "lock_timeout"

    captured.clear()
    monkeypatch.setattr(
        views,
        "charge_webhook",
        lambda *a: HttpResponse("Charge not found", status=HTTPStatus.INTERNAL_SERVER_ERROR),
    )
    resp_500 = views.webhook(req)
    assert resp_500.status_code == 500
    assert len(captured) == 1
    assert captured[0][1] == "webhook.inbound"
    assert captured[0][2]["outcome"] == OUTCOME_FAILURE
    assert captured[0][2]["status"] == 500
    assert captured[0][2]["error_code"] == "webhook_processing_error"


def test_webhook_stripe_retrieval_failure_redacts_event_json_and_pii(captured, monkeypatch, caplog):
    views = _import_views()
    event = types.SimpleNamespace(pk=88)

    class DummyProvider:
        api_config = {"api_key": "sk_test_secret"}

        def __init__(self, ev):
            self.event = ev

        def _init_api(self):
            pass

    monkeypatch.setattr(views, "StripeCreditCard", DummyProvider)

    def raise_stripe_error(*args, **kwargs):
        raise stripe.StripeError("Secret error details", code="resource_missing")

    monkeypatch.setattr(views.stripe.Charge, "retrieve", raise_stripe_error)
    monkeypatch.setattr(views.stripe.Source, "retrieve", raise_stripe_error)
    monkeypatch.setattr(views.stripe.PaymentIntent, "retrieve", raise_stripe_error)

    sensitive_event = {
        "id": "evt_redact_1",
        "data": {
            "object": {
                "id": "ch_secret_1",
                "billing_details": {"email": "alice@example.com", "name": "Alice Secret"},
                "client_secret": "pi_secret_xyz",
            }
        },
    }

    with caplog.at_level(logging.ERROR):
        r1 = views.charge_webhook(event, sensitive_event, "ch_secret_1", None)
        r2 = views.source_webhook(event, sensitive_event, "src_secret_1", None)
        r3 = views.paymentintent_webhook(event, sensitive_event, "pi_secret_1", None)

    assert r1.status_code == 500
    assert r2.status_code == 500
    assert r3.status_code == 500

    for forbidden in ("alice@example.com", "Alice Secret", "pi_secret_xyz", "Secret error details", "sk_test_secret"):
        assert forbidden not in caplog.text
        assert forbidden not in str(captured)

    assert len(captured) == 3
    for _, action, extra in captured:
        assert action == "connection.request"
        assert extra["outcome"] == OUTCOME_FAILURE
        assert extra["error_code"] == "resource_missing"
        assert extra["event_id"] == 88
        assert extra["object_id"] == "evt_redact_1"


def test_request_id_correlation_in_fallback_logger(captured):
    token = bind_request_id("req-corr-99")
    try:
        log_operation("plugin.loaded", OUTCOME_SUCCESS, backend="stripe")
    finally:
        reset_request_id(token)

    assert len(captured) == 1
    assert captured[0][2]["request_id"] == "req-corr-99"

    captured.clear()
    log_operation("plugin.loaded", OUTCOME_SUCCESS, backend="stripe")
    assert "request_id" not in captured[0][2]


def test_stripe_verify_domain_propagates_job_id_duration_and_redacts_errors(captured, monkeypatch, caplog):
    tasks = _import_tasks()
    fake_event = types.SimpleNamespace(pk=55)
    fake_provider = types.SimpleNamespace(
        settings=types.SimpleNamespace(
            connect_user_id=None,
            publishable_key="pk_test_123",
            connect_client_id=None,
            secret_key="sk_test_secret",
            connect_secret_key=None,
            connect_test_secret_key=None,
        )
    )
    payment_mod = _import_payment()
    monkeypatch.setattr(payment_mod, "StripeCreditCard", lambda ev: fake_provider)

    class FakeQS:
        def exists(self):
            return False

    monkeypatch.setattr(tasks.RegisteredApplePayDomain.objects, "filter", lambda **kw: FakeQS())
    monkeypatch.setattr(tasks.RegisteredApplePayDomain.objects, "create", lambda **kw: None)
    monkeypatch.setattr(
        tasks.stripe.ApplePayDomain,
        "create",
        lambda **kw: types.SimpleNamespace(livemode=False, last_response=types.SimpleNamespace(code=200)),
    )

    fake_celery_task = types.SimpleNamespace(request=types.SimpleNamespace(id="celery-domain-1", retries=0))
    monkeypatch.setattr(operational_log, "_CELERY_CURRENT_TASK", fake_celery_task)
    tasks.stripe_verify_domain.run(fake_event, "tickets.example.com")

    assert [item[1] for item in captured] == ["job.start", "connection.request", "job.finish"]
    for _, _, extra in captured:
        assert extra["job_id"] == "celery-domain-1"
    conn_extra = captured[1][2]
    assert conn_extra["outcome"] == OUTCOME_SUCCESS
    assert conn_extra["status"] == 200
    assert isinstance(conn_extra["duration_ms"], int)
    assert conn_extra["duration_ms"] >= 0
    assert conn_extra["event_id"] == 55
    assert "tickets.example.com" not in str(captured)

    captured.clear()

    def raise_domain_error(**kw):
        exc = stripe.StripeError("Secret token sk_test_secret failed", code="domain_invalid")
        exc.http_status = 400
        raise exc

    monkeypatch.setattr(tasks.stripe.ApplePayDomain, "create", raise_domain_error)
    with caplog.at_level(logging.ERROR):
        tasks.stripe_verify_domain.run(fake_event, "tickets.example.com")

    assert "sk_test_secret" not in caplog.text
    assert [item[1] for item in captured] == ["job.start", "connection.request", "job.finish"]
    fail_extra = captured[1][2]
    assert fail_extra["outcome"] == OUTCOME_FAILURE
    assert fail_extra["error_code"] == "domain_invalid"
    assert fail_extra["status"] == 400
    assert fail_extra["job_id"] == "celery-domain-1"
    assert isinstance(fail_extra["duration_ms"], int)


def test_error_handler_mixin_does_not_leak_exception_text(captured, caplog):
    payment_mod = _import_payment()
    mixin = payment_mod.StripeErrorHandlerMixin()
    fake_payment = types.SimpleNamespace(
        provider="stripe",
        order_id=321,
        order=types.SimpleNamespace(event_id=654),
        fail=lambda **kw: None,
    )

    card_err = stripe.CardError(
        "Cardholder Alice Secret 4242 declined",
        param="number",
        code="card_declined",
    )
    with caplog.at_level(logging.ERROR):
        with pytest.raises(payment_mod.PaymentException):
            mixin.handle_card_error(card_err, fake_payment)

    assert "Alice Secret" not in caplog.text
    assert "4242" not in caplog.text
    assert "Alice Secret" not in str(captured)
    assert captured[-1][1] == "payment.charge"
    assert captured[-1][2]["outcome"] == OUTCOME_FAILURE
    assert captured[-1][2]["error_code"] == "card_declined"
    assert captured[-1][2]["event_id"] == 654
    assert captured[-1][2]["order_id"] == 321


def test_permission_denied_logs_only_for_authenticated_users(captured):
    views = _import_views()
    factory = RequestFactory()
    fake_event = types.SimpleNamespace(pk=77)
    fake_organizer = types.SimpleNamespace(pk=11)

    req_anon = factory.post("/control/event/org/evt/stripe/disconnect/")
    req_anon.user = types.SimpleNamespace(is_authenticated=False)
    req_anon.event = fake_event
    req_anon.organizer = fake_organizer
    with pytest.raises(PermissionDenied):
        views.oauth_disconnect(req_anon)
    assert captured == []

    req_authed = factory.post("/control/event/org/evt/stripe/disconnect/")
    req_authed.user = types.SimpleNamespace(
        pk=42,
        is_authenticated=True,
        has_event_permission=lambda *a, **kw: False,
    )
    req_authed.event = fake_event
    req_authed.organizer = fake_organizer
    with pytest.raises(PermissionDenied):
        views.oauth_disconnect(req_authed)
    assert len(captured) == 1
    assert captured[0][1] == "permission.denied"
    assert captured[0][2]["outcome"] == OUTCOME_FAILURE
    assert captured[0][2]["error_code"] == "forbidden"
    assert captured[0][2]["status"] == 403
    assert captured[0][2]["user_id"] == 42
    assert captured[0][2]["event_id"] == 77
    assert captured[0][2]["model"] == "event"
    assert captured[0][2]["object_id"] == 77

    captured.clear()
    settings_view = views.OrganizerSettingsFormView.as_view()
    req_org = factory.get("/control/organizer/org/stripeconnect/")
    req_org.user = types.SimpleNamespace(
        pk=99,
        is_authenticated=True,
        is_staff=False,
        is_superuser=False,
        has_active_staff_session=lambda *a: False,
    )
    req_org.session = types.SimpleNamespace(session_key="k")
    req_org.organizer = fake_organizer
    with pytest.raises(PermissionDenied):
        settings_view(req_org)
    assert len(captured) == 1
    assert captured[0][1] == "permission.denied"
    assert captured[0][2]["user_id"] == 99
    assert captured[0][2]["model"] == "organizer"
    assert captured[0][2]["object_id"] == 11


def test_sca_return_view_checks_payment_state_after_handler(captured, monkeypatch):
    views = _import_views()
    factory = RequestFactory()
    monkeypatch.setattr(views, "render", lambda req, tpl, ctx: HttpResponse(status=200))
    monkeypatch.setattr(views, "eventreverse", lambda *a, **kw: "/order/")

    def run_sca(final_state):
        fake_order = types.SimpleNamespace(
            pk=10,
            event_id=20,
            code="ORD1",
            secret="sec",
            refresh_from_db=lambda: None,
        )
        fake_payment = types.SimpleNamespace(
            pk=30,
            provider="stripe",
            state=final_state,
        )
        fake_prov = types.SimpleNamespace(
            redirect_action_handling="redirect",
            _handle_intent_response=lambda req, p: None,
        )
        view = views.ScaReturnView()
        view.order = fake_order
        view.payment = fake_payment
        view.pprov = fake_prov
        req = factory.get("/stripe/sca/ORD1/h/30/return/")
        req.event = types.SimpleNamespace(pk=20)
        view.request = req
        return view.get(req)

    captured.clear()
    resp_fail = run_sca(views.OrderPayment.PAYMENT_STATE_FAILED)
    assert resp_fail.status_code == 200
    assert captured[-1][1] == "payment.sca"
    assert captured[-1][2]["outcome"] == OUTCOME_FAILURE
    assert captured[-1][2]["error_code"] == "requires_payment_method"

    captured.clear()
    resp_ok = run_sca(views.OrderPayment.PAYMENT_STATE_CONFIRMED)
    assert resp_ok.status_code == 200
    assert captured[-1][1] == "payment.sca"
    assert captured[-1][2]["outcome"] == OUTCOME_SUCCESS
