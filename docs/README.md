# Documentation

Start with the [project overview](../README.md). Choose the guide for your task;
installed agents load the [skill entry point](../skills/session-harness/SKILL.md)
and only the reference needed for their next action.

| Task | Guide |
| --- | --- |
| Give an agent the installation task | [Start prompt](ONBOARDING-PROMPT.md) |
| Install and reconcile existing instructions | [Onboarding](ONBOARDING.md) |
| Configure, update or recover an installation | [Releases and updates](RELEASES.md) |
| Understand optional background updates | [Automatic maintenance](AUTO-UPDATE.md) |
| Inspect dependencies before contributing | [Code graph](CODE-GRAPH.md) |
| Validate a provider adapter | [Provider validation](PROVIDER-VALIDATION.md) |
| Prepare a contribution or sensitive report | [Contributing](../CONTRIBUTING.md), [security](../SECURITY.md) |
| Check what changed | [Changelog](../CHANGELOG.md) |

| Runtime reference | Scope |
| --- | --- |
| [Clients](../skills/session-harness/references/clients.md) | Discovery, model selection and execution boundaries |
| [Instructions](../skills/session-harness/references/instructions.md) | Client filenames, aliases and skill discovery |
| [Usage and context](../skills/session-harness/references/usage-and-context.md) | Admission, observations, supervision and checkpoints |
| [Budgets](../skills/session-harness/references/budgets.md) | Calendars, daily allocation, reserves and grants |
| [Coordination](../skills/session-harness/references/coordination.md) | Shared authorities, capacity and stopped-owner recovery |
| [API and spend](../skills/session-harness/references/api-and-spend.md) | Paid-route authorization, pricing and liability |
| [Reviews](../skills/session-harness/references/review-protocol.md) | Independent verdicts, packets and deadlines |
| [Platforms](../skills/session-harness/references/platforms.md) | Operating-system support and limitations |
| [Design sources](../skills/session-harness/references/sources.md) | Rationale and provider contracts |

This documentation describes v0.2.1. Check `ai-session version` before following
version-specific instructions. Existing installations retain their selected release
unless the owner requests an update or has already enabled automatic maintenance.
