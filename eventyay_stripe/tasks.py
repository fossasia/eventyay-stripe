import logging
import time
from urllib.parse import urlsplit

import stripe
from django.conf import settings
from eventyay.base.services.tasks import EventTask
from eventyay.celery_app import app
from eventyay.multidomain.urlreverse import get_event_domain

from .models import RegisteredApplePayDomain
from .operational_log import (
    OUTCOME_FAILURE,
    OUTCOME_SUCCESS,
    log_operation,
    stripe_error_code,
    traced_job,
)

logger = logging.getLogger(__name__)


def get_domain_for_event(event):
    domain = get_event_domain(event, fallback=True)
    if not domain:
        siteurlsplit = urlsplit(settings.SITE_URL)
        return siteurlsplit.hostname
    return domain


def get_stripe_account_key(prov):
    if prov.settings.connect_user_id:
        return prov.settings.connect_user_id
    else:
        return prov.settings.publishable_key


@app.task(base=EventTask, max_retries=5, default_retry_delay=1)
@traced_job("stripe_verify_domain")
def stripe_verify_domain(event, domain):
    from .payment import StripeCreditCard

    prov = StripeCreditCard(event)
    account = get_stripe_account_key(prov)

    api_config = {
        "api_key": prov.settings.connect_secret_key or prov.settings.connect_test_secret_key
        if prov.settings.connect_client_id and prov.settings.connect_user_id
        else prov.settings.secret_key
    }

    if prov.settings.connect_client_id and prov.settings.connect_user_id:
        api_config["stripe_account"] = prov.settings.connect_user_id

    if RegisteredApplePayDomain.objects.filter(account=account, domain=domain).exists():
        return

    started = time.monotonic()
    try:
        resp = stripe.ApplePayDomain.create(domain_name=domain, **api_config)
    except stripe.StripeError as e:
        duration_ms = int((time.monotonic() - started) * 1000)
        err_code = stripe_error_code(e, "stripe_error")
        http_status = getattr(e, "http_status", None)
        logger.error("Could not verify domain with Stripe (event_id=%s, error_code=%s)", event.pk, err_code)
        log_operation(
            "connection.request",
            OUTCOME_FAILURE,
            backend="stripe",
            payment_provider="stripe",
            error_code=err_code,
            status=http_status if isinstance(http_status, int) and not isinstance(http_status, bool) else None,
            duration_ms=duration_ms,
            event_id=event.pk,
        )
    else:
        duration_ms = int((time.monotonic() - started) * 1000)
        last_resp = getattr(resp, "last_response", None)
        resp_status = getattr(last_resp, "code", None)
        log_operation(
            "connection.request",
            OUTCOME_SUCCESS,
            backend="stripe",
            payment_provider="stripe",
            status=resp_status if isinstance(resp_status, int) and not isinstance(resp_status, bool) else None,
            duration_ms=duration_ms,
            event_id=event.pk,
        )
        if resp.livemode:
            RegisteredApplePayDomain.objects.create(domain=domain, account=account)
