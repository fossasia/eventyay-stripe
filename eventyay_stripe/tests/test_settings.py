import datetime
import os

import pytest

if not os.environ.get("DJANGO_SETTINGS_MODULE"):
    pytest.skip("Django settings are not configured", allow_module_level=True)

from eventyay.base.models import Event, Organizer, Team, User

from eventyay_stripe.signals import register_global_settings

valid_secret_key_values = [
    "sk_",
    "sk_foo",
    "rk_bla",
]

valid_publishable_key_values = [
    "pk_",
    "pk_foo",
]

invalid_secret_key_values = [
    "skihaspartialprefix",
    "ihasnoprefix",
    "ihaspostfixsk_",
]

invalid_publishable_key_values = [
    "pkihaspartialprefix",
    "ihasnoprefix",
    "ihaspostfixpk_",
]


def test_global_ticketing_fields_are_owned_by_stripe_plugin():
    fields = register_global_settings(sender=None)
    assert {
        "payment_stripe_connect_client_id",
        "payment_stripe_connect_publishable_key",
        "payment_stripe_connect_secret_key",
        "payment_stripe_connect_test_publishable_key",
        "payment_stripe_connect_test_secret_key",
    } <= set(fields)
    assert "payment_stripe_connect_app_fee_percent" not in fields


@pytest.fixture
def env(client):
    orga = Organizer.objects.create(name="CCC", slug="ccc")
    event = Event.objects.create(
        organizer=orga,
        name="30C3",
        slug="30c3",
        date_from=datetime.datetime(2013, 12, 26, tzinfo=datetime.UTC),
        plugins="eventyay_stripe",
        live=True,
    )
    event.settings.set("attendee_names_asked", False)
    event.settings.set("payment_stripe__enabled", True)
    user = User.objects.create_user("dummy@dummy.dummy", "dummy")
    t = Team.objects.create(organizer=event.organizer, can_change_event_settings=True)
    t.members.add(user)
    t.limit_events.add(event)
    client.force_login(user)
    url = "/control/event/%s/%s/settings/payment/stripe_settings" % (event.organizer.slug, event.slug)
    return client, event, url


@pytest.mark.django_db
@pytest.mark.skip(reason="Stripe Connect settings UI no longer exposes the legacy stripe__enabled field markup")
def test_settings(env):
    client, event, url = env
    response = client.get(url, follow=True)
    assert response.status_code == 200
    assert "stripe__enabled" in response.rendered_content


def _stripe_key_test(env, field, value, is_valid):
    client, event, url = env
    data = {"payment_stripe_" + field: value, "payment_stripe__enabled": "on"}
    response = client.post(url, data, follow=True)

    if not is_valid:
        assert "does not look valid" in response.rendered_content
    else:
        assert "does not look valid" not in response.rendered_content


@pytest.mark.django_db
@pytest.mark.skip(
    reason="Control payment settings POST needs Eventyay multidomain/session setup beyond this plugin suite"
)
@pytest.mark.parametrize("value", invalid_secret_key_values)
def test_settings_secret_key_invalid(env, value):
    _stripe_key_test(env, "secret_key", value, False)


@pytest.mark.django_db
@pytest.mark.skip(
    reason="Control payment settings POST needs Eventyay multidomain/session setup beyond this plugin suite"
)
@pytest.mark.parametrize("value", invalid_publishable_key_values)
def test_settings_publishable_key_invalid(env, value):
    _stripe_key_test(env, "publishable_key", value, False)


@pytest.mark.django_db
@pytest.mark.skip(
    reason="Control payment settings POST needs Eventyay multidomain/session setup beyond this plugin suite"
)
@pytest.mark.parametrize("value", valid_secret_key_values)
def test_settings_secret_key_valid(env, value):
    _stripe_key_test(env, "secret_key", value, True)


@pytest.mark.django_db
@pytest.mark.skip(
    reason="Control payment settings POST needs Eventyay multidomain/session setup beyond this plugin suite"
)
@pytest.mark.parametrize("value", valid_publishable_key_values)
def test_settings_publishable_key_valid(env, value):
    _stripe_key_test(env, "publishable_key", value, True)
