# Session harness

Shared instructions, current-model discovery, independent plan review and usage
accounting for coding assistants. The strongest available model of the hosting
provider manages substantive work; bounded workers normally use medium effort.
Manager policy defaults to Extra High (`xhigh`), or the highest advertised level
below `max` if unavailable. Reserve `max` for explicitly selected, extremely
difficult tasks. The development launcher applies this default; published v0.2.0
requires checking and adjusting the native effort control before work.
Two other provider families review the same plan independently. Models are resolved
at runtime rather than pinned in policy.

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
