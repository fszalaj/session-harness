# Session harness

Portable instructions, model discovery, independent review and conservative usage
accounting for subscribed coding clients. The active session's strongest current
model plans and manages; native workers from the same model family normally do the
implementation at medium/high effort. The other two model families review the plan.

**Strict mode is the public default and blocks inference when an exact bound cannot
be enforced.** Subscription counters can lag and a response can cross a threshold
before it is reported. An explicit local opt-in to observed-threshold mode accepts
that in-flight overshoot; it does not create a hard cap. New ledgers default to
**20 percentage points/day per pool** and **0% reserve**, with a UTC calendar,
all seven workdays and an 08:30 reset cutoff. Existing settings are preserved. Explicit adaptive budgets
can target **100% utilization** by distributing the balance until each real reset;
daily grants let the owner add headroom without erasing usage.
Missing or unreliable quota evidence still blocks admission. Processes started
outside the harness, including an already-running manager, are outside its control.

Start with the [copy-paste onboarding prompt](docs/ONBOARDING-PROMPT.md) and
[practical onboarding guide](docs/ONBOARDING.md). They cover existing instructions,
owned skills, backups, project integration and verification before installation.

See [provider validation and its limits](docs/PROVIDER-VALIDATION.md) for real
native protocol requirements and the distinction between deterministic tests and
actual provider execution.

## Relationship to knowledge-gateway

Session harness coordinates models, independent reviews, execution and usage
admission. A knowledge-gateway deployment can provide durable project knowledge
and a code graph. These are complementary responsibilities; knowledge-gateway is
not a required dependency. Existing local documentation, a vault or another graph
backend can serve the same project integration points.

## Install

Requires macOS or Linux, Python 3.11+, Git and the clients you already use.
The clone example also uses GitHub CLI; Git can clone the same repository URL. Install
and authenticate vendor clients separately through their normal subscription flows.
Do not put API keys, OAuth tokens or usage records in this repository.

```sh
gh repo clone fszalaj/session-harness
cd session-harness
python3 scripts/test.py
python3 scripts/install-agent-profile.py --launcher
python3 scripts/install-agent-profile.py --launcher --apply
```

Audit and merge existing personal rules first: backups alone do not keep replaced
rules active. See the onboarding guide. The first install command is a preview. The second installs verified immutable
snapshots under `~/.local/share/session-harness/releases/`, links client instructions
and skills to shared personal targets, and installs `~/.local/bin/ai-session`.
Existing replacements have private backups; unrelated settings and skills remain.
Restart clients to load the new definitions. Add `~/.local/bin` to PATH if needed.

```sh
python3 skills/session-harness/scripts/harness.py inventory
python3 skills/session-harness/scripts/harness.py usage refresh codex --initialize
python3 skills/session-harness/scripts/harness.py usage status codex
python3 skills/session-harness/scripts/harness.py usage check codex
```

After explicitly accepting observed-mode limitations, persist that local choice:

```sh
python3 skills/session-harness/scripts/quota.py configure --mode observed
```

The setting lives in the private ledger, applies across local projects, and survives
reinstallation. `--mode strict` restores strict admission without resetting usage.

`--initialize` explicitly starts prospective observation for a previously unseen
pool. It does not reconstruct earlier daily usage, erase history, or bypass strict
admission. A failed `check` exits 2. `status` and `refresh` can succeed while their
JSON reports `allowed: false`; a successful metadata command is not permission.

`ai-session codex`, `ai-session claude` and `ai-session antigravity` dynamically
select model/effort, then enforce admission before launching. Strict mode reports unsupported quota
bounds. Observed mode requires explicit local configuration and fresh admissible
evidence; it can still block a client whose quota report is incomplete. Dry-run launch
is available with `harness.py launch <client>` and does not invoke a model.

Owned launch/review processes are checked before, every 15 seconds during execution,
and after completion. Denial terminates their process group and restores the terminal.
Polling and refresh latency can delay a stop; detached sessions and other computers
remain outside that boundary. Codex, Claude and Antigravity have native quota
readers; unsupported or changed native protocols still block admission.

## Easy budget controls

```sh
ai-session budget
ai-session budget calendar --workdays weekdays --reset-cutoff 08:30
ai-session budget defaults --reserve 0
ai-session budget set codex --strategy adaptive --reserve 0
ai-session budget add codex 5
ai-session budget use-rest codex
```

Use the appropriate service name. Each pool keeps its own balance, daily allocation
and reset forecast. Adaptive pacing uses scheduled workdays; a fresh reset due by
tomorrow's local cutoff releases current native headroom on a scheduled workday.
It does not predict a refill. Existing service/pool overrides outrank global defaults;
set their reserves explicitly when migrating. Grants expire at local midnight; reuse the printed `--id` for
idempotent retries. They change local permission, not the provider allowance or
admission mode. See [adaptive budgets and reset research](skills/session-harness/references/budgets.md)
for weekly/monthly pacing, unknown schedules, early renewals and JSON output.

## What each client supports

| Client/service | Model evidence | Quota evidence | Protected inference |
| --- | --- | --- | --- |
| Codex | Account-visible `model/list` | `account/rateLimits/read`, all returned windows | Observed-mode launch/review supervision; strict blocked |
| Claude Code | Native initialize selectable options/efforts; rolling `best`, actual ID on execution | Native control read, global/scoped/additional pools, successful backend-read evidence | Observed-mode launch/review supervision; strict blocked |
| Antigravity | Account-visible `agy models` | Owned native localhost endpoint with forced backend refresh, all grouped pools | Observed-mode launch/review supervision; strict blocked |
| Copilot | Metadata-only `models.list` | Metadata-only `account.getQuota` | Inventory adapter; execution unverified and blocked |
| Cursor | `agent models` selectable catalog; account access unverified | No verified personal CLI quota endpoint | Inventory adapter; execution unverified and blocked |
| Kimi, OpenCode, Aider, Continue, Gemini CLI | Installed-client registry; unsupported metadata stays explicit | No verified quota adapter | Execution blocked |
| Ollama | Local installed models, forced loopback | Local inventory is not a subscription allowance | Execution adapter unverified |

Installed, authenticated, account-visible and successfully invoked are separate
states. Grok/xAI, DeepSeek, Kimi/Moonshot and GLM/Z.ai are recognized model
families, often accessed through another client. An advertised catalog never proves
subscription entitlement; no API authentication or paid fallback is enabled.
Copilot's bundled help list is not account access. Model IDs are not pinned;
ambiguous generation or capability relationships require current provider evidence.
Copilot and Cursor can host several vendors. A Claude model in Copilot consumes
Copilot quota; it does not debit a separately subscribed Claude account. It still
counts as Anthropic for independent-review family selection.

Native same-family workers are explicitly supported: OpenAI for an OpenAI manager,
Anthropic for an Anthropic manager, Google for a Google manager. A configured native
role can override spawn effort or inherit a configured subagent default, so verify
effective model/effort instead of assuming inheritance. Keep one writer per scope.

## Instructions and skill discovery

Repository `CLAUDE.md` and `GEMINI.md` link to `AGENTS.md`. Gemini CLI still defaults
to `GEMINI.md`; Antigravity CLI, Cursor and Copilot CLI support project `AGENTS.md`.
Copilot IDE/GitHub support varies by feature. See the [client instruction map](skills/session-harness/references/instructions.md)
for official sources, scoped rules, settings and global-path differences. Instruction
compatibility does not imply a working execution adapter. Installed personal links:

| Consumer | Path |
| --- | --- |
| Shared policy | `~/.agents/AGENTS.md` |
| Codex | `~/.codex/AGENTS.md` |
| Claude | `~/.claude/CLAUDE.md` |
| Antigravity / default Gemini CLI | `~/.gemini/GEMINI.md` |
| Copilot | `~/.copilot/copilot-instructions.md` |
| Shared skill | `~/.agents/skills/session-harness` |

Client skill directories also link to the shared skill, including Copilot and
Cursor. Cursor global User Rules live in its UI; this installer does not invent
a globally loaded `~/.cursor/AGENTS.md`. Remote/cloud workers need their own setup.
Custom `CODEX_HOME`, `CLAUDE_CONFIG_DIR` and `COPILOT_HOME` values are rejected
before installation when they differ from the selected home's default directories.
Configure those instruction paths explicitly; the installer never silently writes
a different profile. Runtime inventory preserves the native authentication paths.

For any project, follow [AI onboarding](docs/ONBOARDING.md). Preserve its existing
`AGENTS.md` and conventions. A repository-linked copy wins over a personal copy;
otherwise use the installed skill. Same-name entries can coexist. Compare runtime
path/hash and reinstall after changing maintained sources.

## Usage history, resets and context

The private SQLite ledger lives under
`$XDG_STATE_HOME/session-harness/quota/ledger.sqlite3`, normally
`~/.local/state/session-harness/quota/ledger.sqlite3`. It is shared across local
projects and sessions, with a persisted timezone, daily pool counters and reset
history. It is not a distributed account lock across computers. Provider counters
can include use from other devices; never claim complete multi-device admission.

Check the configured ledger timezone before initializing observation; the current
default for a new ledger is `UTC`. Existing timezone settings are preserved;
`budget calendar --timezone IANA` initializes or validates the timezone and cannot
rewrite established history. Known reset instants are stored as UTC timestamps.
A provider may omit a reset schedule; that pool remains tracked with an explicit
unknown date, without inventing renewal or disabling its budget.
Provider resets never refund daily consumption. A usage drop or changed reset is
recorded, not assumed to mean unused daily budget. The clock reaching a reset is
not proof of renewal. Missing or stale pools block admission. In observed mode,
fresh complete reports can resume after gaps while preserving the daily lower bound
and marking historical coverage partial. Earlier unobserved use is not reconstructed.
Strict mode keeps the uncertainty block.

Native statusline capture stores allowlisted reports only. Receipt time is not a
verified backend refresh, so cached redraws cannot authorize inference. See
[usage and context policy](skills/session-harness/references/usage-and-context.md)
for capture commands and the limits of native hooks.

At 60% context usage, prepare a checkpoint. At 75%, reduce unnecessary context and
avoid large new work. At 85%, use native compaction to continue the same task when
supported. These are advisory thresholds; Markdown cannot trigger compaction or
switch the running model. Start a new session for an unrelated task, a required
model change or unrecoverable context. Neither approach guarantees quota savings.
Use actual context metadata, not cumulative token or billing totals. Checkpoints
carry the plan digest, owned files, tests, pending decisions and quota stop reason.
Refresh persisted quota policy before stopping; report the actual reserve instead
of a threshold remembered from instructions loaded earlier in the session.

## Verify and maintain

`python3 scripts/test.py` runs deterministic tests without inference. Report the
platform and checks actually run; local results do not establish cross-platform
or live provider support.
Read [official sources](skills/session-harness/references/sources.md)
and installed CLI help when adapting an integration. Record actual observed models
and capabilities; simulations and completed processes are not review approval.

Deterministic tests do not prove live provider execution, independent model review,
or exact quota guarantees. Report actual capabilities and checks separately
from deterministic coverage. Installation does not change paid-usage settings.

Licensed under the [Apache License, Version 2.0](LICENSE). Copyright 2026 Filip
Szalaj. See [NOTICE](NOTICE) for retained notices. Referenced third-party material
retains its stated license. The installer includes LICENSE and NOTICE in the
profile snapshot and installed skill. See also
[contributing](CONTRIBUTING.md) and [security](SECURITY.md).

For rollback, use the install manifest and restore only its listed paths. Preserve
symlink text when restoring links; do not dereference relative backup links. Keep
old snapshots until no managed link references them. Never delete whole vendor
configuration directories to uninstall this skill.
