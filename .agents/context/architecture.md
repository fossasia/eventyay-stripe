# Stripe plugin architecture and repository map

This repository implements attendee payments within
[Eventyay core](https://github.com/fossasia/eventyay). It is a Django plugin, not a
standalone web service. [Business](https://github.com/fossasia/eventyay-business)
is a separate plugin for commercial policy and organizer invoices. Paths below
are local to Stripe unless explicitly marked core.

| Area | Files in `eventyay_stripe/` |
|---|---|
| App metadata and registration | `__init__.py`, `apps.py`, `signals.py` |
| Provider settings and payment methods | `payment.py`, `forms.py` |
| Webhooks, OAuth, SCA and return views | `views.py`, `urls.py` |
| External object references | `models.py`, `migrations/` |
| Response shape validation | `validation_models.py` |
| Domain verification and account keys | `tasks.py` |
| Currency conversion/signatures/shredding helpers | `utils.py` |
| Checkout UI and translations | `templates/`, `static/`, `locale/` |

`pyproject.toml` defines package metadata, dependencies, Ruff, and pytest settings.
It uses the compatibility entry-point group `pretix.plugin`. Core settings read
entry-point modules and install this Django app; `StripePluginApp.ready()` imports
signals/tasks. Do not rename the group or the existing entry-point value as
unrelated cleanup. Installation, plugin availability, and payment-provider
configuration are distinct layers.

`signals.register_payment_provider` lists provider classes. `StripeSettingsHolder`
holds shared settings; `StripeMethod`, `Redirector`, and individual method classes
implement checkout behavior. Follow the selected method rather than assuming all
methods follow the card flow.

`ReferencedStripeObject` uniquely maps an external object reference to a core
order and optionally its payment. `RegisteredApplePayDomain` records domain/account
verification. Core owns `Order`, `OrderPayment`, `OrderRefund`, and their lifecycle.

## Integration boundaries

Core's `app/eventyay/config/urls.py` and multidomain plugin handler mount plugin
URLs and compatibility aliases. Core also has a separate organizer billing API
in `app/eventyay/api/views/stripe.py` and helpers in
`app/eventyay/helpers/stripe_utils.py`.

Business owns tier entitlements, fee policy, fee ledger, consolidated organizer
invoices, and their collection. Its webhook is
`/control/business/stripe/webhook/`. Do not implement that lifecycle in this
plugin's attendee webhook merely because both receive Stripe events.

Core installs this dependency through `app/pyproject.toml` and `app/uv.lock`.
Editable installation overrides the packaged copy locally. A plugin merge alone
does not update a production core lockfile.
