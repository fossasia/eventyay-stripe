# Attendee payment flow and review boundaries

## Configuration and checkout

1. `signals.py` registers providers and global settings; `forms.py` and
   `StripeSettingsHolder` validate settings. `views.py` handles Connect OAuth
   and organizer settings.
2. `payment.py` selects publishable keys and mode through `_uses_stripe_connect`,
   `_requested_stripe_testmode`, and related helpers. `StripeMethod.api_config`
   selects the API key/account context. Inspect both paths when debugging mode
   mismatches: direct-key behavior and Connect behavior are not identical.
3. `PaymentIntentFactory.create_payment_intent` converts to currency minor units,
   supplies order/event metadata and an idempotency key, and creates the intent.
   Individual provider methods supply payment-method-specific options.
4. Payment data and `ReferencedStripeObject` connect subsequent Stripe objects
   to the core order/payment. SCA and return views use order secrets and payment
   identity; do not reduce these checks to a user-controlled order code.

The repository currently pins `stripe==11.3.*` and `_init_api` sets
`2024-11-20.acacia`. These describe current code, not a recommendation to use that
version in a new integration. API/SDK upgrades need their own compatibility work.

## Webhook processing

`urls.py` defines event-scoped `stripe/webhook/` and global `/_stripe/webhook/`,
plus OAuth and SCA/return routes. Core provides compatibility aliases too.

`views.webhook` verifies the raw payload with the shared core secret helper,
dispatches by object type (`charge`, `dispute`, `source`, `payment_intent`), and
looks up `ReferencedStripeObject`. Charge delivery can precede the corresponding
PaymentIntent update, so the lookup has a PaymentIntent-reference fallback.
Unknown/unrelated objects can be acknowledged without changing an order.

Follow `charge_webhook`, `source_webhook`, or `paymentintent_webhook` and the
provider's execution logic to the core payment state transition. A successful
HTTP response alone does not prove that an order was paid. Preserve replay,
out-of-order delivery, scope, and already-completed payment behavior.

The signing secret currently comes from core's global
`stripe_webhook_secret_key`, read by `get_stripe_webhook_secret_key()` in
`app/eventyay/helpers/stripe_utils.py` (core `dev`, inspected 2026-10-28).
The helper in that revision does not read `payment_stripe_webhook_secret`. Do not invent per-event/per-endpoint secret settings
in setup instructions. Core billing and Business billing have separate handlers;
verify the target route before diagnosing a missing update.

## Connect fees, refunds, and privacy

`StripeMethod._prepare_api_connect_args` currently adds `transfer_data` for a
configured destination. It does not add a new checkout application fee. Business
records and collects platform fees through its own ledger/invoices. Historical
payment info can still contain `application_fee_amount`; refunds inspect it to
request `refund_application_fee`, and destination refunds may reverse transfers.
Do not remove historical refund support or restore fee creation from old README
language about Connect fees.

Refund behavior in `payment.py` uses core refund records and specific payment
exceptions. Check partial amounts, external refund notifications, account
context, and currency precision when changing it.

`utils.shredded_stripe_payment_info` and provider shredding preserve selected
operational fields while dropping sensitive fields. `validation_models.py`
handles optional/nested response data. Preserve these privacy and missing-data
behaviors when changing stored responses or logging.

## Test map and gaps

The repository has **two test roots**. `tests/test_utils.py`,
`tests/test_validation_models.py`, and `tests/test_shred_payment_info.py` cover
helpers. `eventyay_stripe/tests/` contains database-backed `test_provider.py`,
`test_checkout.py`, `test_settings.py`, and `test_webhook.py`.

Current CI invokes `pytest tests --reruns 3`, and `pyproject.toml` sets
`testpaths = ["tests"]`; that selection does not include the nested suite. For
provider changes, explicitly run `pytest -p no:env tests eventyay_stripe/tests` with core
Django settings and test services from [development](development.md). The nested
tests also skip at module level if the settings environment variable is absent.
Even with settings supplied, `test_webhook.py` unconditionally skips the entire
module, and the checkout test in `test_checkout.py` is also unconditionally
skipped because their multidomain/session setup is incomplete. Use `-rs` to
inspect skip reasons. Selecting the suite does not establish webhook or checkout
coverage; these flows need working fixtures and separate regression validation.
Core integration tests include
`app/tests/tickets/api/test_stripe_webhook_routes.py` and
`test_payment_plugin_compat.py`. Do not infer complete coverage from green helper CI.

For payment changes, add targeted mocked regressions for the changed provider or
handler, including failed/duplicate delivery where applicable. Only describe a
sandbox checkout, SCA, webhook, or refund exercise as tested if actually performed
with test configuration. Never infer payment coverage from helper tests alone.

## Design history

The parent [Eventyay epic #5890](https://github.com/fossasia/eventyay/issues/5890)
tracks the architecture and rollout. Its directly linked implementation PRs were
merged when reviewed on 2026-10-28; the epic remains open for deployment validation
and controlled organizer activation. Early checkout-splitting proposals were
superseded by [Stripe #55](https://github.com/fossasia/eventyay-stripe/pull/55).
Historical fee refund support remains intentional. Current activation additionally
requires the reconciliation gate from
[Business #130](https://github.com/fossasia/eventyay-business/pull/130).
Do not infer live deployment readiness from merged PRs or historical test counts.
