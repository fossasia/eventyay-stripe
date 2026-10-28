# Stripe review prompts

Select the relevant cases for the changed provider or handler:

- Correct event, organizer, order secret, and stored payment identity.
- Direct-key versus Connect mode/account selection; currency minor units.
- Stable idempotency and reference mapping, signature rejection, duplicate and
  out-of-order delivery, no mutation for unrelated objects.
- SCA/redirect return and asynchronous completion, already-completed payments.
- Partial/external refunds, destination transfer reversal, historical application
  fee refunds, and specific error propagation.
- Null or missing nested response objects and privacy-safe payment shredding.

Existing helper tests do not establish all these behaviors. Add focused mocked
regressions when behavior changes. Keep organizer billing and Business commercial
policy in their owning repositories; do not revive checkout fee charging here.
