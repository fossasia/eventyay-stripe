import stripe
from django.core.management.base import BaseCommand
from django_scopes import scopes_disabled
from eventyay.base.models import Event
from eventyay.base.settings import GlobalSettingsObject

from ...utils import stripe_object_to_dict


class Command(BaseCommand):
    help = "Detect country for Stripe Connect accounts connected with eventyay (required for payment request buttons)"

    @scopes_disabled()
    def handle(self, *args, **options):
        cache = {}
        gs = GlobalSettingsObject()
        api_key = gs.settings.payment_stripe_connect_secret_key or gs.settings.payment_stripe_connect_test_secret_key
        if not api_key:
            self.stderr.write(self.style.ERROR("Stripe Connect is not set up!"))
            return

        for e in Event.objects.filter(plugins__icontains="eventyay_stripe"):
            uid = e.settings.payment_stripe_connect_user_id
            if uid and not e.settings.payment_stripe_merchant_country:
                if uid in cache:
                    e.settings.payment_stripe_merchant_country = cache[uid]
                else:
                    try:
                        account = stripe.Account.retrieve(uid, api_key=api_key)
                    except Exception as e:
                        print(e)
                    else:
                        country = stripe_object_to_dict(account).get("country")
                        e.settings.payment_stripe_merchant_country = cache[uid] = country
