# Eventyay Stripe agent instructions

This is the canonical agent policy for this repository. Read only the context
needed for the task; verify details against the checked-out source and CI.
Adapters must link here instead of maintaining copies of these rules.

## Start here

- [Repository architecture](.agents/context/architecture.md): ownership, modules,
  models, and integration boundaries.
- [Development and testing](.agents/context/development.md): installation, service
  prerequisites, commands, and source-of-truth caveats.
- [End-to-end flows](.agents/context/flows.md): lifecycle, failure paths, and tests.
- [Repository change skill](.agents/skills/stripe-change/SKILL.md):
  workflow and PR handoff.

## Working rules

- Product code belongs in `eventyay_stripe/`; tests belong in `tests/` and `eventyay_stripe/tests/`. This is a
  separate Git repository from core Eventyay and other plugins. Confirm the Git
  root before staging; do not accidentally commit a parent checkout's changes.
- Use `eventyay.*` for new core imports and `eventyay_stripe.*` or relative imports for
  this plugin. Existing `pretix.plugin` entry-point names and stored identifiers
  are compatibility contracts; do not rename them as incidental cleanup.
- Event-owned ORM access must use `django_scopes.scope(event=event)`. Filter
  organizer-owned data by the authorized organizer and preserve view permission
  checks. Use `select_related`/`prefetch_related` where related data is consumed.
- Keep imports at module top, except where needed to resolve circular imports.
  Preserve specific exception types and transactional/idempotency behavior.
- Use external JavaScript modules for new behavior, no inline scripts or jQuery.
  Mark user-facing strings for translation; preserve namespaced template paths.
- Use the repository's formatter and test configuration, not another plugin's.
  Do not upgrade Stripe APIs/SDKs or rewrite legacy flows as part of documentation
  or unrelated changes.
- Keep credentials and customer/payment payloads out of commits and PRs. Mock
  external payment calls in automated tests; use explicitly configured test
  environments for requested payment exercises.

## Changes and PRs

Use a feature branch from upstream `dev` and target `dev`. Inspect remotes before
pushing; contributors may use forks. Keep commits focused. Record checks and
limitations honestly, and link related core/plugin changes with any required
ordering. A plugin PR does not update core's dependency lock automatically.

When code changes invalidate a documented path, command, contract, or flow,
update the relevant context file in the same PR. Keep detailed knowledge in
`.agents/context/` and `.agents/skills/stripe-change/references/`;
keep this entry point short.
