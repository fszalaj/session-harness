# Session harness

Shared instructions, current-model discovery, independent plan review and usage
accounting for coding assistants. The strongest available model of the active
session's provider manages; bounded workers normally use medium effort. Two other
provider families review the same plan independently. Model versions are resolved
at runtime, never pinned in policy.

Start with the [onboarding prompt](docs/ONBOARDING-PROMPT.md) or
[installation guide](docs/ONBOARDING.md). These include consolidation of existing
`AGENTS.md`, client aliases and user-owned skills without discarding unique rules.

## Install

Python 3.11+, Git, and the clients you choose to use are required. Core accounting,
API requests and profile installation support Linux, macOS and Windows. Native
client execution has the narrower capabilities listed below.

```sh
git clone --branch v0.1.2 --depth 1 https://github.com/fszalaj/session-harness.git
cd session-harness
python3 scripts/test.py
python3 scripts/install-agent-profile.py --launcher
python3 scripts/install-agent-profile.py --launcher --apply
ai-session configure
```

`ai-session setup` records the private environment authorization: which native
services (Codex, Claude Code, Antigravity) and which direct API services may run
inference, the ledger timezone, working days, reset cutoff and quota mode, plus a
positive total monthly API budget and money mode when API services are selected.
Native launches, external reviews and API dispatch are denied until that record
exists; a missing, corrupt or unselected entry fails closed with
`environment_setup_required` or `service_not_configured`. Status, inventory,
discovery, quota refresh and accounting commands stay available. `ai-session setup
--status` reads the record, `--reset` clears only the authorization, and repeated
setup, budget changes or profile reinstallation never erase budgets, grants or
history. Noninteractive use needs explicit options, `--mode` and `--yes`; an agent
must not complete setup on the owner's behalf.

The first installer invocation previews changes. Put unique personal rules in a
private Markdown file and pass `--personal-policy /absolute/path/to/personal.md`
to preview and apply. The installer appends those rules to the generic policy and
remembers that path for updates. Keep it outside this public checkout. Backups
alone do not keep replaced rules active. Unrelated settings and skills are preserved.
Restart clients after installation.

## Configure and update

```sh
ai-session configure             # Guided configuration; Enter keeps current choices
ai-session configure --status    # Inspect authorized services without changing them
ai-session version
ai-session update --check        # Check the latest published release
ai-session update                # Show the version and ask before installing
ai-session update --version 0.1.2 --apply  # Pin or return to an exact release
ai-session claude                # Start a protected session after configuration
ai-session codex
```

`configure` is the interactive `setup` command under an easier name. It asks about
services, APIs, working days, reset cutoff, quota mode, shared authority and session capacity;
existing choices remain the defaults. API selection requires a monthly money budget.
Use `ai-session budget add SERVICE 5` for an extra allowance today, or
`ai-session budget use-rest SERVICE` for the remaining available balance.

Updates select published immutable releases, verify SHA-256 checksums and install
local snapshots. They preserve private policy, environment authorization, budgets,
grants, usage history and unrelated client settings. Background updates require
explicit opt-in and never follow `main`. Restart clients after updating; already-running
sessions retain their selected runtime. Rollback uses the same exact-version
command and does not rewind accounting. See [releases and updates](docs/RELEASES.md).

The development build adds `ai-session auto-update` (not included in v0.1.2):

```sh
ai-session auto-update register  # Verify the installed files against their published baseline
ai-session auto-update enable --interval-hours 24
ai-session auto-update status
ai-session auto-update disable
```

The flag defaults to off. macOS uses a user LaunchAgent; Linux uses a user systemd
timer. Checks run hourly and obey the selected interval. Installation waits until
the shared authority has no protected sessions, then holds a maintenance lock
against new admissions. Local overlays are carried only when their original files
are unchanged, or retired when the release includes identical fixes; conflicts
defer installation. Windows and checked-copy profiles keep explicit updates.
See [automatic maintenance and recovery](docs/AUTO-UPDATE.md), including login,
network and crash-recovery limits. Downloads use HTTPS and same-origin checksums,
not an independent publisher signature. Updating makes no model calls and never
changes provider billing or automatic credit top-up.

Most projects need only a short `AGENTS.md` reference to the installed skill. A
single explicit update then serves those projects. A project with a maintained
vendored copy keeps its own reviewed version and update procedure; a global update
does not replace it. Keep application conventions in the project's `AGENTS.md`.

On Windows, use `python` in place of `python3`, install timezone data with
`python -m pip install -r requirements-windows.txt`, and add `--link-mode copy`
to both installer invocations if symlinks are unavailable. Copy mode maintains
checked views of the same canonical source and refuses to overwrite subsequent
user edits. It is explicit, never a silent symlink fallback. PowerShell 7.3+ users
can run the installed `ai-session.ps1`; other shells can call `ai-session.py` with
Python. Add the reported launcher directory to PATH. See
[Windows boundaries](skills/session-harness/references/platforms.md).

## Keep sessions within one account budget

```sh
ai-session setup
ai-session hooks --install
ai-session hooks --install --apply
ai-session coordination status
ai-session codex
ai-session claude
ai-session antigravity
```

Setup asks which clients and APIs you authorize, your workdays, timezone and quota
mode. It also asks for the quota authority: `local` for one machine, or an existing
trusted SSH `user@host` for multiple machines. Run setup on the authority first;
it needs subscription authentication for the same accounts. On other machines:

```sh
ai-session coordination set --authority user@host
```

Install the harness on every participating machine. SSH must already work with
host-key verification and noninteractive authentication. All native admission and
session ownership then go through that authority; failure blocks, without local
fallback. Edit quota budgets and session capacity on the authority. New configurations
allow **four sessions per billing service**; existing choices, including one, remain
unchanged. All sessions and native workers share the same daily allowance. For example,
four sessions spending 3 points each consume 12 points from their common pool.

```sh
ai-session coordination status
ai-session coordination set --max-sessions 8
```

Capacity accepts 1..32 and can increase while sessions are running; omitting
`--authority` keeps the current authority. The configuration wizard also asks for
this value. `account_session_busy` means those places are occupied, not that quota
is exhausted. Close an unused session or deliberately increase capacity on the
authority. A crashed session requires confirmation that it stopped before release.
See [multiple sessions and teams](skills/session-harness/references/coordination.md).

Different provider accounts need separate authorities and ledgers. Sharing a project
does not make its contributors share quota. People deliberately using one account
must route admission to that account's authority. Backend refreshes serialize per
ledger/service so concurrent sessions cannot record responses out of order; model
execution can still overlap. More concurrent work increases possible observed-mode
overshoot and never multiplies the quota budget.

Claude's optional command hooks merge with existing settings, make private backups,
and stop supported prompt/tool events on denial without asking another model to
retry. Restart Claude after installation. A supervisor owns launched process groups;
hooks alone cannot bound streaming text or control clients that ignore them.
For a hook reporting an unknown reset, follow the
[recovery steps](docs/RELEASES.md#claude-stops-because-a-reset-is-unknown).
Direct sessions on machines without the shared authority remain outside protection.
Cross-machine API dispatch is deliberately blocked: execute paid requests on the
monetary authority machine, whose reservations and charges stay in one ledger.

Only the manager plans at maximum effort. Ordinary reviewers now use medium effort
and a 16 KiB packet bound; high effort is an explicit escalation for a difficult
review. The default review deadline is three minutes. Workers receive bounded tasks
and fresh context, normally medium effort, low for gathering. Claude role files
limit worker turns; partial results are checkpoints, not permission to restart.
Dynamic tier aliases must resolve to the current version of their own tier; never
compare version numbers across unrelated model tiers to force every task onto the
flagship. No fixed generation IDs are embedded in policy.

## Subscription budgets

```sh
ai-session inventory
ai-session budget
ai-session budget calendar --workdays weekdays --reset-cutoff 08:30
ai-session budget defaults --strategy adaptive --reserve 0
ai-session budget set claude --strategy adaptive --reserve 0
ai-session budget add claude 5
ai-session budget use-rest claude
```

New ledgers use **adaptive allocation, zero reserve, UTC, all seven workdays and
an inclusive 08:30 reset cutoff**. Existing settings survive upgrades, including
legacy fixed limits. Service/pool overrides outrank global defaults. Fixed pacing
is available with `--strategy fixed --daily-limit 20`. Calendar, defaults and grants
are private and shared across local projects; project instructions refer to them
instead of duplicating personal settings.

Adaptive allocation divides each pool's balance over scheduled workdays until its
actual reset. On a working day, a fresh reset due by tomorrow's local cutoff makes
all current headroom available, subject to the configured reserve. It never invents
a refill. When the reset is absent but the native long-window duration is verified,
adaptive pacing conservatively divides the balance over a full window. The reset
stays unknown, and the cutoff cannot release that balance. Without either form of
evidence, an explicit fixed/window policy is required. Grants expire at local
midnight; reuse their printed `--id` when retrying. See
[budget controls and reset sources](skills/session-harness/references/budgets.md).

**Strict admission is the default and blocks inference without enforceable cost
bounds.** Explicit observed mode accepts delayed counters and possible in-flight
overshoot; it does not create an exact provider cap. Configure it privately with
`ai-session setup` or `python3 skills/session-harness/scripts/quota.py configure
--mode observed` only when that tradeoff is authorized. Setup authorization and
admission are separate: setup names the services that may run, and admission still
needs fresh quota plus enforceable or explicitly observed bounds. No mandatory 10%
floor exists. A quota stop cannot be bypassed by switching services or accounts.

Use `ai-session usage refresh SERVICE --initialize` to explicitly begin prospective
observation, then `ai-session usage check SERVICE`. Initialization cannot reconstruct
previous use. Metadata commands may succeed while reporting `allowed: false`.
Missing, stale or incomplete evidence blocks admission. Owned native processes are
checked before, during and after execution; existing parent sessions, other devices
and processes launched outside the harness remain outside its control.

## API money and extra credits

Direct, text-only routes exist for **OpenAI, Anthropic, Gemini, xAI/Grok, DeepSeek,
Moonshot/Kimi, Z.ai/GLM and OpenRouter**. API usage is separate from subscription
quota. Installation enables no billing and sets no API allowance.

```sh
ai-session spend set total --monthly 50 --currency USD --mode observed
ai-session spend set api:xai --monthly 10 --currency USD --mode observed
ai-session spend status
ai-session spend add total 5 --id extra-this-month
ai-session api models xai
ai-session api run xai --model ACCOUNT_MODEL --max-output-tokens 1000 --reserve-cost 0.25 < plan.txt
```

These are examples of explicit paid authorization, not installation defaults. API
services must also be selected in `ai-session setup`, which requires the positive
monthly total and an explicit money mode. Use an existing key through the selected
provider's environment variable. Catalogs do
not prove entitlement or rank model strength. Z.ai has no verified catalog route;
its general API requires an explicitly selected model. Model-specific API effort
controls remain unsupported until their capability can be verified.

A total monthly cap is mandatory; optional service caps apply simultaneously.
Money defaults to strict mode, independently of subscription mode. Current API
routes require explicit monetary observed mode because a reservation is an
estimate, not a provider-enforced maximum charge. The ledger reserves before
sending, retains unresolved liabilities across months, never automatically retries
a paid request, and records an actual overrun even when it exceeds the cap.
Topups do not clear an overrun requiring reconciliation. Exact receipts and
estimated token costs are reported separately. The monthly balance is paced over
the scheduled working days left in the local month: a day's allowance is the
remaining balance divided by the remaining workdays, frozen at that day's first
reservation so concurrent requests cannot overspend it. Settling below a
reservation releases the unused part the same day, days off deny dispatch even
after a topup, and cap or calendar changes redistribute the remainder without
refunding today's debit. Direct transport accepts only a single-use admission
from the budgeted coordinator; there is no unbudgeted generate entrypoint. Other routes need fresh explicit
model prices before dispatch. See [API and money setup](skills/session-harness/references/api-and-spend.md).

Native extra-credit balances retain their reported units. Unknown credits are
never converted to dollars or quota percentages. Antigravity's documented
`useG1Credits` setting is read from its CLI settings file as local fallback
evidence, not as account credit metadata; the harness never changes that setting. Monetary caps and verified
receipt imports support `extra:SERVICE` scopes; **native paid-credit execution is
not verified**. Enabled extras, automatic purchase/reload, or missing eligibility
controls block protected native inference. No setting, purchase or fallback is
activated by the harness.

## Capability map

| Client/service | Discovery and accounting | Protected execution |
| --- | --- | --- |
| Codex | Account model catalog, quota windows, native credit metadata | Native adapter exists; currently blocked because the credit schema does not establish paid-use disablement |
| Claude Code | Native selectable models/efforts, complete usage and extra-credit controls | Observed native launch/review when fresh quota and explicit disabled paid controls pass |
| Antigravity | Account model catalog and native quota groups on supported Unix platforms | Observed native launch/review when fresh quota passes and the documented `useG1Credits` CLI setting is explicitly `false`; missing, `true` or malformed values block |
| Copilot | Metadata-only models/quota and reported overage controls | Native execution unverified and blocked |
| Cursor | Selectable model catalog; no verified personal quota API | Native execution unverified and blocked |
| Kimi CLI, OpenCode, Aider, Continue, Gemini CLI | Installed-client inventory; unsupported metadata stays explicit | No protected native adapter |
| Ollama | Installed model inventory | Localhost does not prove local compute; cloud routing and execution remain unverified |
| Eight direct API services above | Explicit metadata commands, money caps and cost evidence | Explicit paid text requests; no tools, streaming or automatic retries |

A model family is distinct from its hosting client and billing service. A Claude
model through Copilot counts as Anthropic for review independence and consumes
Copilot allowance. The same model through an API has separate API accounting.
Inventory and instruction compatibility do not establish protected execution.
See [validation procedures](docs/PROVIDER-VALIDATION.md); synthetic fixtures are
not live provider evidence.

## Instructions, knowledge and context

`CLAUDE.md` and `GEMINI.md` point to repository `AGENTS.md`. Gemini CLI defaults to
`GEMINI.md`; Antigravity, Cursor and Copilot CLI support project `AGENTS.md`.
Copilot IDE/GitHub behavior varies by feature. The
[client instruction map](skills/session-harness/references/instructions.md) documents
native paths, scoped rules and supported imports.

The shared personal targets are `~/.agents/AGENTS.md` and
`~/.agents/skills/session-harness`; supported client paths link there, or use checked
copies in explicit copy mode. Cursor global User Rules require its UI. Local
installation does not configure cloud workers. Unsupported custom client homes
are rejected before installation instead of silently writing another profile.

Use an existing knowledge layer and code graph for project context and dependency
checks, including before documentation changes. Knowledge-gateway is an optional
provider of those capabilities; session-harness coordinates work and usage. It
does not replace project knowledge or require that backend.

For developing this repository, a [committed code graph](docs/code-graph.json)
is ready immediately after cloning. Queries need only Python and Git:

```sh
python scripts/code_graph.py find Ledger
python scripts/code_graph.py importers skills/session-harness/scripts/quota.py
python scripts/code_graph.py check
```

See [graph coverage and rebuilding](docs/CODE-GRAPH.md). CI rejects an outdated
snapshot. Generation uses static source analysis and makes no model calls.

For the same task, prefer native compaction with a durable checkpoint. At 60%
context use, checkpoint; at 75%, reduce new context; at 85%, compact when supported.
These are advisory thresholds: Markdown cannot compact or switch a running model.
A new session suits a different task, a required model change or failed recovery.
Neither approach guarantees quota savings.

## Verify and update

`python3 scripts/test.py` runs deterministic contracts without credentials or paid
inference. GitHub Actions runs the suite on standard public Linux, macOS and Windows
runners, with read-only permissions and no artifact/cache uploads. These standard
public runners are [free](https://docs.github.com/en/billing/concepts/product-billing/github-actions);
larger runners have separate billing and are not used.

The launcher forwards management commands (`configure`, `setup`, `version`, `update`,
`budget`, `inventory`, `usage`, `api`, `spend`, `coordination`, `hooks`, `discover`,
`review`) unchanged; a provider name launches that provider. After every push, check
README/docs/skills and configured consumers against their selected release. Upgrade
maintained profiles explicitly when a release is published and verify a second
installer preview reports no changes. Keep consumer paths and account evidence
private. Do not publish consumer repositories without authorization.

The private SQLite ledger normally resides at
`~/.local/state/session-harness/quota/ledger.sqlite3` and respects `XDG_STATE_HOME`.
It is shared locally, not a distributed account lock. Never commit it, credentials,
review packets, personal setup details or live session reports. For rollback,
restore only manifest-listed paths from private backups and preserve newer user edits.

Licensed under [Apache 2.0](LICENSE), copyright 2026 Filip Szalaj. Retain [NOTICE](NOTICE)
when redistributing; the installer includes both legal files in snapshots. See
[contributing](CONTRIBUTING.md) and [security](SECURITY.md).
