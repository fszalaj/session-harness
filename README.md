# Session harness

Coordinate coding assistants across clients and computers with shared instructions,
model discovery, usage budgets and independent reviews. Work directly on routine
tasks, delegate when it helps, and choose review depth according to risk.

Session harness provides the `ai-session` CLI and installable agent profiles. It
uses your configured clients and accounts; it does not provide a model subscription
or require a particular combination of providers.

## Features

- **Shared agent instructions.** Install common workflows across supported clients
  while preserving project rules, private preferences and unrelated settings.
- **Model and client discovery.** Inspect installed clients, account-visible models,
  supported roles and reasoning controls. Distinguish available metadata from
  verified execution capability.
- **Usage controls.** Coordinate native subscription budgets, reserves, calendars,
  temporary grants and concurrent sessions through one account authority.
- **Selective delegation.** Route bounded tasks using fresh allowance fractions,
  explicit model choices and role restrictions. Inspect worker output before use.
- **Risk-based review.** Routine reversible work uses relevant tests. Material
  production changes require one independent other-family review; exceptionally
  risky or irreversible changes require two other-family plan reviews.
- **Explicit API work.** Run text tasks and typed decisions with separate monetary
  authorization, accounting and model identity checks. No automatic paid fallback.
- **Sign-in and recovery tools.** Inspect native authentication, start supported
  login flows, diagnose admission stops and retain resumable task evidence.
- **Reproducible installation.** Use checksum-verified releases, reversible profile
  updates and optional automatic maintenance. Keep private policy outside the repo.

## Get started

You need Python 3.11+, Git and at least one supported client or configured API route.
For platform-specific steps, see [computer setup](docs/COMPUTER-SETUP.md).

1. Download the archive and checksum from the
   [latest stable release](https://github.com/fszalaj/session-harness/releases/latest).
2. Follow the [verification and extraction instructions](docs/ONBOARDING.md#1-select-and-verify-the-release).
3. From the extracted directory, preview and install:

   ```sh
   python3 scripts/install-agent-profile.py --launcher
   python3 scripts/install-agent-profile.py --launcher --apply
   ```

4. Open a new terminal and configure the services you authorize:

   ```sh
   ai-session configure
   ai-session configure --status
   ai-session inventory
   ```

Configuration is interactive. An assistant must not answer authorization prompts
on your behalf. Installation does not enable billing or authorize inference.
If `ai-session` is unavailable, add the reported launcher directory to `PATH`
(`~/.local/bin` on macOS and Linux).

To retain personal instructions, pass
`--personal-policy /absolute/path/to/personal.md` to both installer commands.
On Windows, use `python`, install `requirements-windows.txt`, and add
`--link-mode copy` when symlinks are unavailable. The PowerShell launcher requires
PowerShell 7.3+. See [onboarding](docs/ONBOARDING.md) for complete steps, or use the
[assistant onboarding prompt](docs/ONBOARDING-PROMPT.md).

## Supported clients and routes

| Client or route | Support |
| --- | --- |
| Codex, Claude Code, Antigravity CLI | Native discovery, quota checks, launch and review adapters, subject to client and platform capabilities |
| Copilot CLI | Native launch, bounded text work and explicit catalog-selected reviews with model-family and returned-identity checks |
| Cursor CLI | Personal Free account quota checks, launch and supervised text through Auto; independent review is unavailable |
| Ollama local | Bounded text tasks from installed local models with explicit task IDs and local receipts |
| Explicit APIs | Authorized text requests with separate credentials and monetary accounting, including Meta and Ollama Cloud routes |
| Configured free routes | Verified allowances, conservative reservations and explicit opt-in to mixed routing |

An installed client or a listed model does not prove that an account can execute a
task. Authentication, current quota, model identity, role permission and adapter
support must all pass. Opaque Auto output is supervised work, not an independent
review. See [client execution](docs/CLIENT-EXECUTION.md),
[adapter boundaries](skills/session-harness/references/clients.md) and
[provider validation](docs/PROVIDER-VALIDATION.md).

## Everyday workflow

Inspect your environment and start an authorized client from your project:

```sh
ai-session auth status
ai-session discover --session auto
ai-session budget
ai-session codex
```

Use another supported launcher, such as `ai-session claude`, when appropriate.
Automatic session detection can report `unknown` or `ambiguous`; an explicit
`--session` value declares the hosting client rather than proving its identity.

The manager handles planning, integration and verification. It executes routine
work directly and delegates only when the expected benefit outweighs preparation
and integration. Required reviews use distinct verified upstream model families,
not merely different gateways. Re-review material changes or unresolved defects;
do not repeat full panels for optional suggestions.

Models are resolved from current account-visible catalogs. Roles default to
advertised `high`, or the highest supported lower level. A local
[effort preference](docs/ONBOARDING.md#default-reasoning-effort) can select `low`,
`medium` or `high`; explicit supported task settings take precedence. Instructions
cannot change the model or reasoning effort of an already-running conversation.

Keep application conventions in the project's `AGENTS.md`. Existing project wiki,
code graph and knowledge tools remain authoritative; no knowledge backend is
required. See the [task startup procedure](skills/session-harness/references/session-start.md)
and [review protocol](skills/session-harness/references/review-protocol.md).

## Budgets and delegation

New configurations default to a local authority, strict quota mode, four concurrent
sessions per service, UTC, all seven workdays, an 08:30 reset cutoff, adaptive
allocation and zero reserve. Existing settings are preserved.

Strict mode blocks inference when bounds cannot be enforced. Explicit observed
mode accepts delayed counters and possible in-flight overshoot. Both require
fresh admission evidence. Missing telemetry is not proof of an exhausted account
or permission to bypass a stop.

When an account is shared across computers, configure one trusted authority.
Native sessions, workers and reviews share its accounting. API spending has a
separate monetary budget. Direct client calls outside the harness are not
universally intercepted or controlled.

Enable optional balancing on the account authority, then submit useful bounded work:

```sh
ai-session balance enable
ai-session balance status
ai-session work --id unique-task-id < task.txt
```

Selection ranks fresh allowance fractions; it does not promise equal token totals
or costs. Task-fit subsets can use `--basis weekly`, with explicit model and effort
controls. Enabling balancing does not move an interactive conversation to another
model. Workers return supervised output that the manager checks and tests.

Use `ai-session usage check SERVICE` for fresh admission through the configured
authority. `usage status` reads local evidence, which can be stale on another host.
`ai-session audit --since YYYY-MM-DD` separates authority accounting from local
session telemetry. See [budgets](skills/session-harness/references/budgets.md),
[balancing](skills/session-harness/references/balancing.md) and
[coordination](skills/session-harness/references/coordination.md).

## API tasks and typed decisions

Use the [provider wizard](skills/session-harness/references/provider-onboarding.md)
to select and authorize an access route:

```sh
ai-session onboard --list
ai-session onboard claude
```

Explicit API work requires configured credentials and monetary authorization.
The [coding-model workflow](skills/session-harness/references/coding-models.md)
selects eligible candidates against fresh metadata and a reviewed policy.
`ai-session api coding-run` returns supervised text for inspection, not autonomous
deployment or independent review approval.

For narrow classification, filtering, candidate selection and scoring,
[Jev typed decisions](skills/session-harness/references/decisions.md) use
`api decision-models` and `api decide openrouter` through existing money controls.
Deterministic rules do not need a model call.

[Free routes](skills/session-harness/references/free-access.md) require verified
allowances and explicit configuration. Expired evidence or unresolved requests
require inspection; they do not trigger paid fallback.

## Updates and recovery

```sh
ai-session version
ai-session update --check
ai-session update
```

Updates use published releases and preserve registered private policy and
accounting. Restart clients to load changed profiles. Automatic maintenance is
optional; see [updates and rollback](docs/RELEASES.md) and
[automatic maintenance](docs/AUTO-UPDATE.md).

For authentication problems, run `ai-session auth status` and use the returned
`ai-session auth login PROVIDER` action. Unknown metadata is not a confirmed logout;
opening a login page does not renew quota evidence or authorize spending.

For admission or interrupted-task problems, follow
[session recovery](skills/session-harness/references/usage-and-context.md#when-a-protected-session-stops).
Do not delete a ledger, erase consumption or grant quota to repair telemetry.

## Documentation and contribution

Browse the [documentation index](docs/README.md), or start with:

- [Onboarding](docs/ONBOARDING.md): installation, configuration and profile loading.
- [Client instructions](skills/session-harness/references/instructions.md): supported instruction paths and discovery limits.
- [API and money](skills/session-harness/references/api-and-spend.md): spending authorization and accounting.
- [Code graph](docs/CODE-GRAPH.md): dependency queries and rebuilding.
- [Contributing](CONTRIBUTING.md): development and testing.

Run `ai-session --help` for command options. Report problems through
[issues](https://github.com/fszalaj/session-harness/issues) with redacted reproduction
details; use [security reporting](SECURITY.md) for vulnerabilities. Keep credentials,
account evidence and personal setup private.

Licensed under [Apache 2.0](LICENSE). Retain [NOTICE](NOTICE) when redistributing.
