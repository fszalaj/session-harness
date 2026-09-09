# Session harness

Shared instructions, current-model discovery, independent plan review and usage
accounting for coding assistants. The strongest available model of the hosting
provider manages substantive work; bounded workers normally use medium effort.
Manager policy defaults to Extra High (`xhigh`), or the highest advertised level
below `max` if unavailable. Reserve `max` for explicitly selected, extremely
difficult tasks. The development launcher applies this default; published v0.2.0
requires checking and adjusting the native effort control before work.
Two other provider families review the same plan independently. Native role models
are resolved at runtime from current client capabilities.

## Start here

For a laptop or desktop, start with [use your own computer](docs/COMPUTER-SETUP.md).
It distinguishes personal accounts, shared account coordination and remote execution.

New installation: open the [latest stable release](https://github.com/fszalaj/session-harness/releases/latest)
and follow the [installation workflow](docs/ONBOARDING.md#1-select-and-verify-the-release).
Download its release archive and checksum together, verify them, then work from the
extracted directory. Resolve the release once; maintained installations never track
`main`. To delegate the whole workflow, use the [short onboarding prompt](docs/ONBOARDING-PROMPT.md).

Already installed? Run `ai-session version` and retain that selected release.
`ai-session update --check` checks availability; updates need your instruction or
your existing opt-in to [automatic maintenance](docs/AUTO-UPDATE.md).
See [updates and rollback](docs/RELEASES.md).

Python 3.11+, Git and your chosen clients are required. From the verified extracted
release directory, the essential installation commands are:

```sh
python3 scripts/test.py
python3 scripts/install-agent-profile.py --launcher
python3 scripts/install-agent-profile.py --launcher --apply
ai-session configure
```

The first installer command previews changes. Preserve unique personal rules in a
private Markdown addendum and pass the same `--personal-policy /absolute/path/to/personal.md`
to both invocations. Backups alone do not keep those rules active. Installation
preserves unrelated settings and skills; updates retain private policy and accounting.
Restart affected clients and rerun the preview to verify idempotence.

On Windows, use `python`, first run `python -m pip install -r requirements-windows.txt`,
and add `--link-mode copy` to both installer commands when symlinks are unavailable.
Checked copies protect subsequent user edits. Use PowerShell 7.3+ with the installed
`ai-session.ps1`, or invoke `ai-session.py` with Python; add the reported launcher
directory to PATH. See [platform support](skills/session-harness/references/platforms.md).

## Configure and run

The owner completes `ai-session configure` interactively to authorize native/API
services and choose usage policy. An assistant must not complete it with `--yes`.
Existing choices remain defaults; installation enables no billing. Before setup,
inference returns `environment_setup_required`; inspection remains available.

```sh
ai-session version
ai-session configure --status
ai-session inventory
ai-session budget
ai-session coordination status
ai-session claude
```

Use one trusted quota authority when sharing an account across computers. Native
sessions and workers share its budget. Direct clients outside these controls remain
unprotected. See [coordination](skills/session-harness/references/coordination.md).

**Strict mode is the default and blocks inference without enforceable bounds.**
Explicit observed mode accepts delayed counters and possible in-flight overshoot.
Fresh quota and paid-usage eligibility are still required. Metadata discovery does
not prove protected execution or a successful independent review.

Version 0.2.0 adds account-bound owner confirmation of disabled Codex Auto top-up
plus fresh zero-credit evidence; quota and admission controls still apply. It also
adds optional automatic stable updates, disabled by default. Existing opt-ins are
preserved. Version 0.1.2 blocked protected Codex execution because its native
credit metadata could not establish paid-use disablement.
Check the [capability guide](docs/PROVIDER-VALIDATION.md) and [release guide](docs/RELEASES.md)
for your selected version before relying on either feature.

## Balance subscriptions (development)

The development source adds opt-in routing across configured native subscriptions.
A short manager session can distribute bounded text work independently of its model
family while respecting every provider's daily quota and paid-use guards. These
commands are not included in the published v0.2.0 release:

```sh
ai-session balance enable
ai-session balance status
ai-session work --id unique-task-id < task.txt
ai-session audit --since 2026-01-01
```

Enable on the account authority after the owner requests balancing. Selection targets
equal fractions of daily allowances, using atomic task reservations and fresh native
observations. It does not promise equal token totals or dollar costs. APIs remain
separately authorized; inventory-only clients are reported as unsupported for routing.
The manager must submit useful tasks to `work`; enabling a profile does not transfer
its interactive conversation to another model. A newer concurrent quota observation
gets one read-only re-evaluation; failed refreshes and quota denials still stop work.
See [balancing, supported clients and recovery](skills/session-harness/references/balancing.md).
Owners can also [configure model supervision](skills/session-harness/references/balancing.md#configure-which-models-need-supervision)
by model pattern and role. These settings can allow implementation while preventing
the same model from acting as an independent reviewer; no vendor ranking is built in.

Development installations also explain protected session stops in the terminal,
including the reason and recovery commands. Cleanup errors retain the original quota
reason and report uncertain process termination separately. Worker pacing denials
report `balance_blocked` and the real reason, such as `max_lead_exceeded`, instead
of a CLI schema error. An unconfirmed work receipt reports
`balance_receipt_unavailable`; inspect the task before recovery or another dispatch. See
[session stop recovery](skills/session-harness/references/usage-and-context.md#when-a-protected-session-stops).

Use `ai-session usage check SERVICE` for a fresh native admission check through the
configured authority, with or without a Claude `--model`. `usage status` reads local
evidence and may stay stale on another computer; `usage refresh` updates only that
computer's ledger. An unavailable quota read does not establish an exhausted plan.
Claude discovery reports a verified signed-out response as `auth_required`; native
sign-in in that execution context is separate from shared quota admission.

Claude alias resolution also uses fresh native `resolvedModel` metadata, allowing
current Sonnet workers alongside a newer minor revision of the planning tier.
Development builds keep model-specific and common Claude allowances separate. A
Fable-only stop can select current Opus and resume the exact protected conversation
after confirmed cleanup. Common quota and configured role restrictions still apply.
See [model allowances and recovery](skills/session-harness/references/model-allowances.md).

## Add reviewed coding models (development)

The optional [coding profile](skills/session-harness/references/coding-models.md)
adds Kimi, GLM, DeepSeek, MiniMax and Qwen candidates through OpenRouter. This is
one access route within the broader native/API harness: five model families can
share one gateway account, while direct accounts have separate authentication and
allowances. Choose an [access route](skills/session-harness/references/coding-models.md#choose-the-access-route)
before creating accounts. Run
`ai-session api coding-models` to intersect the reviewed allowlist with fresh public
metadata. Review expiry, missing capabilities and unapproved variants block selection.

Execution with `ai-session api coding-run` requires an OpenRouter key, explicit API
setup and a monthly money budget. It returns supervised text work for manager
inspection. API billing stays separate from native subscription balancing, and
installation does not enable paid inference. The guide explains what to configure;
keep passwords, keys and deployment records private.

For recurring free allowances, development builds also provide
[`ai-session free`](skills/session-harness/references/free-access.md). OpenRouter
uses an exact-zero route; direct free accounts use separately verified account
limits and conservative reservations. One executor serves both computers, keeps
credentials local, and records actual model identities without paid fallback.
Explicit `mixed_work` opt-in includes admitted free pools in `ai-session work`.
Evidence expiry or an unresolved request requires inspection before more work.

## Find the relevant guide

Browse the [documentation index](docs/README.md) or choose a task below.

- [Onboarding](docs/ONBOARDING.md): preserve rules, install, configure and verify loading.
- [Client instructions](skills/session-harness/references/instructions.md): native paths and discovery limits.
- [Budgets](skills/session-harness/references/budgets.md): calendars, reserves and dated grants.
- [API and money](skills/session-harness/references/api-and-spend.md): explicit paid authorization and accounting.
- [Usage and context](skills/session-harness/references/usage-and-context.md): admission and session continuity.
- [Releases](docs/RELEASES.md) and [automatic maintenance](docs/AUTO-UPDATE.md): supported updates and recovery.
- [Code graph](docs/CODE-GRAPH.md): dependency queries and rebuilding for contributors.

Prefer the shared installed skill plus a short project `AGENTS.md` reference.
Keep application conventions in the project and explicitly vendored harness copies
on their own reviewed release. Existing knowledge and graph tools remain authoritative;
no knowledge backend is required by installation.

## Help and license

Run `ai-session --help`, consult [provider validation](docs/PROVIDER-VALIDATION.md),
or [open an issue](https://github.com/fszalaj/session-harness/issues) with redacted
reproduction details. Keep credentials, account evidence and personal setup private.
See [contributing](CONTRIBUTING.md) and [security reporting](SECURITY.md).

Licensed under [Apache 2.0](LICENSE), copyright 2026 Filip Szalaj.
Retain [NOTICE](NOTICE) when redistributing; installation includes both legal files.
