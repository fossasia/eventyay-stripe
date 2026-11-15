---
name: stripe-change
description: Change or review Eventyay Stripe attendee payment providers, Connect, webhooks, refunds, and payment data handling with repository-specific setup and tests.
---

# Stripe repository changes

Read root [AGENTS.md](../../../AGENTS.md). Use
[architecture](../../context/architecture.md) to locate the owner and
[flows](../../context/flows.md) to trace the affected lifecycle.

1. Confirm branch, Git root, and imported plugin path. Use
   [development](../../context/development.md) for installation and CI commands.
2. Read the relevant model/service/provider, caller, and test together. Identify
   core contracts before adding a dependency or changing a shared signal.
3. Preserve the invariants in [review prompts](references/review.md) relevant to
   the change. Add focused regressions for changed behavior, using mocked external
   APIs. Documentation-only work needs path/link/frontmatter checks instead.
4. Run the affected tests and repository style checks. State unmet service or
   dependency prerequisites rather than reporting an unexecuted command as passed.
5. Update context if behavior/setup changed. Use
   [the PR template](assets/pr-description.md) for a focused PR against `dev`.
   Related repositories require their own commits and reviewable PRs.
