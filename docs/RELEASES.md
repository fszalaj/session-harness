# Releases and updates

## 0.8.1

Copilot `usage` output names quota pools alongside stable credit-resource IDs.
An active token-billed Business pool that permits exhausted-quota usage or
paid overage remains blocked with `copilot_hard_user_budget_unverified`.
`account.getQuota` does not return the effective user budget, and read-only budget
records do not bind a specific SDK request to an account, model, billing pool and
freshly enforced hard stop. A positive balance or a declared budget is insufficient.
An exhausted finite pool also stops before a request is sent.

An optional local Codex model preference selects an exact current-generation
catalog ID for manager and worker launches. The preference is stored outside the
release and does not override authentication or quota checks.

Upgrade with `ai-session update --version 0.8.1 --apply` and restart affected
clients. This release changes no account, billing, budget or usage-history settings.

## 0.8.0

Use risk-based review by default: routine reversible work runs directly with tests;
material production changes to DNS, access, secrets or data require one independent
other-family review before execution. Exceptionally risky or irreversible changes
require two other-family plan reviews. Useful delegation remains available without
mandatory per-stage workers or repeated full review panels.

This changes instruction defaults, not quota, billing or CLI enforcement. Existing
stricter project/private policies still take precedence and must be reconciled
explicitly by their owner. No admission bypass or automatic paid fallback is added.
Upgrade with `ai-session update --version 0.8.0 --apply` and restart clients. Existing
sessions must explicitly adopt the new instructions; Markdown cannot reload them.

Use a published version for maintained installations. `main` is development code;
installing a checkout is an explicit development choice. Version 0.x is still evolving:
read release notes before upgrading. Published tags and assets are immutable. A fix
gets a new version, including during initial development.

## 0.7.2

All reasoning roles now default to advertised high, or the highest supported lower
level. A local `~/.config/session-harness/default-effort` can select low, medium or
high without changing public release files. Runtime commands also accept
`SESSION_HARNESS_DEFAULT_EFFORT`; explicit supported task effort takes precedence.

Installers render Codex and Claude role fields from the target home's preference,
including automatic-update baselines, while preserving published source integrity.
A changed preference after preview stops apply. Refresh installed profiles after
changing the file; environment overrides do not change static client roles or
running conversations. Clients without effort controls remain client-managed.
Rollback to older versions restores their historical effort behavior.

Upgrade with `ai-session update --version 0.7.2 --apply`, then restart clients.
See [effort configuration](ONBOARDING.md#default-reasoning-effort). Authentication,
quota policy, accounting and existing task-level overrides are unchanged.

## 0.7.1

Claude reviews and bounded text work now accept equivalent native aliases when
initialization confirms the same account-selectable concrete model, context suffix
and effort controls. Conflicting or unverified entries still stop with an ambiguous
catalog error. Exact-ID precedence, model-scoped admission, role policy and returned
model validation remain unchanged.

This patch removes a review blocker; it does not implement automatic Codex context
handoff. Upgrade with `ai-session update --version 0.7.1 --apply`, then restart
clients. Use the registered activation workflow for shared installations. Existing
private policy, authentication, accounting and automatic-update settings are preserved.

## 0.7.0

Native work now ranks fresh fractional allowance consumption before dispatch count.
Optional task-fit subsets can compare whole weekly quota usage with `--basis weekly`;
`--strong-model` and per-service effort select capable native workers explicitly.
Strong Claude work falls back only to a verified current Opus alternative. All daily
admission, reserve, concurrency and configured-service quota checks remain in force.
Copilot monthly pools cannot substitute for weekly evidence, and named Copilot
models retain their separate explicit selection path.

Quota corrections and rebounds no longer count twice within a verified reset window.
Claude's account-bound sub-minute native cache keeps its original timestamp; stale or
ambiguous evidence still blocks. Existing consumption is preserved, including past
overcounts. Shared audit reports authority accounting separately from deduplicated
local session/role telemetry; cached input is not additional usage or billing proof.

OpenRouter coding responses accept verified current canonical catalog identities.
Reasoning-only truncated responses retain model identity and actual cost while failing
as empty output. This does not add a paid fallback, automatic retry or spending grant.

The portable suite covers 777 tests, with platform-specific skips reported explicitly.
An isolated 0.6.1 upgrade, repeated install and rollback validate private-policy and
accounting preservation. Real bounded native and API probes verify their tested
routes, not universal model quality or a guarantee of equal future quota use.

Upgrade with `ai-session update --version 0.7.0 --apply`, then reload affected clients.
Existing private policy, accounting, authentication and maintenance preferences remain.
Identical registered overlays can be absorbed; inspect any conflict against the
published bytes before explicit reconciliation. Shared installations retain their
activation hooks. See [balancing](../skills/session-harness/references/balancing.md),
[role workflow](OWNER-WORKFLOW.md) and [automatic maintenance](AUTO-UPDATE.md).

## 0.6.1

This patch repairs Windows executable discovery and immutable launcher snapshots.
Recognized npm wrappers resolve directly to Node or a contained native executable;
no batch shell is invoked. Launcher imports and child interpreters no longer add
bytecode files to installed snapshots, preserving repeat-install checks.

Copilot discovery reads an isolated session catalog, which can include models
missing from the global SDK list. Named execution applies and verifies the model
and supported effort before sending text, then requires the exact usage-event
model identity. The session protocol was checked with Copilot CLI 1.0.86.

Bounded work accepts one configured native billing service. Copilot accepts one
finite token-billed `chat` or `premium_interactions` pool. Multiple model families
inside Copilot still share one billing service; independent reviewer-family
requirements do not change. Quota, role, concurrency and unresolved-job checks
remain in place.

Strict mode still rejects execution without enforceable bounds. Paid overage must
remain disabled for the standard native adapter; this release does not authorize
spending or introduce a hard per-request Copilot cost cap. Account counters may
lag, and advertised or selected models alone do not prove successful inference.

Verification includes the portable contract suite and an isolated upgrade from
0.6.0, repeat installation with zero changes, launcher execution without snapshot
bytecode, and rollback preserving synthetic private settings and accounting.
Platform-specific checks report explicit skips on other operating systems.

Upgrade with `ai-session update --version 0.6.1 --apply`, then restart clients.
Private policy, accounting, authentication and automatic-update preferences are
preserved. See [Copilot execution](CLIENT-EXECUTION.md#explicit-models) and
[platform boundaries](../skills/session-harness/references/platforms.md).

## 0.6.0

This feature release adds budgeted Jev structured decisions through OpenRouter,
validated OpenRouter reasoning-effort controls, and explicit Copilot model selection
for launch, bounded text work and isolated reviews. It packages the reviewed runtime
changes developed after 0.5.1; updating documentation alone does not add these adapters
to an older installation. See [Jev setup](../skills/session-harness/references/decisions.md)
and [Copilot selection](CLIENT-EXECUTION.md#explicit-models).

Copilot reviews require a known upstream family outside the declared manager family
and exact returned model identity. Two reviewer families still share one Copilot
billing pool. Auto remains supervised-only. Account-selectable models, advertised
effort, finite token-billed allowance and disabled paid overage are required;
premium-request-only plans are unsupported. Automatic worker routing is unchanged.

Verification has these limits:

| Route | Evidence and remaining checks |
| --- | --- |
| Jev | A synthetic decision verified typed probability, choice and score outputs and actual-cost settlement; the upstream decision API remains alpha |
| Native Gemini | One bounded coding task passed 18 deterministic checks; this is not evidence of global optimality |
| Named Copilot Claude/Gemini | Selection, isolation and identity regression fixtures pass; named execution must be verified on the intended paid account before relying on reviews |
| OpenRouter DeepSeek | The initial coding probe timed out without a verifiable result/cost; its reservation remains unresolved and must not be retried automatically |

The [bounded evaluation](OWNER-WORKFLOW.md#initial-synthetic-evaluation-2026-09-21)
records observed model identities without making them routing defaults. Requested
effort is not verified actual effort when telemetry does not report it.

Upgrade with `ai-session update --version 0.6.0 --apply`, then restart clients.
Installation preserves private policy, authentication, service selection, accounting,
pending liabilities and existing automatic-update opt-ins. It authorizes no API
spend, top-up or paid fallback. Identical registered skill overlays can be absorbed;
changed overlays require explicit reconciliation against the published payload.
Use the configured activation hook for shared installations. Never restore accounting
as part of profile rollback; retain 0.5.1 or newer after quota-pool reconciliation.

## 0.5.1

Add explicit Codex missing-pool reconciliation on the account authority, preserving
all consumption and policy. Disappearing pools still fail closed until the owner
verifies and names them; reappearing pools resume accounting from their archived
observation. Empty nonnull limit maps and malformed rows are now explicitly
incomplete rather than silently falling back to a legacy response.

CLI discovery now catches errors from adapters importing the running harness,
so one provider's quota/metadata failure does not crash the entire inventory.
The failed provider remains unavailable; no fallback or admission guard is changed.

Upgrade with `ai-session update --version 0.5.1 --apply` on every consumer and
restart clients. Reconciliation is optional and is never run by the installer.
After reconciling, keep 0.5.1 or newer for archived-pool reactivation support; do not
restore accounting to downgrade. See the [recovery procedure](#codex-reports-missing-historical-pools).

## 0.5.0

Automatic native work now includes configured Copilot and Cursor Auto routes as
supervised text workers. Their output requires manager inspection and cannot serve
as an independent review or proof of the newest model generation. Existing quota,
paid-overage, role, concurrency and request-id checks remain in force. Cursor
catalog parsing accepts combined current/default markers without weakening model
or sign-in verification.

`ai-session auth status` reports configured native sign-in and detects lost sign-in
from private local history. Managed interactive startup offers native login through
`ai-session auth login PROVIDER`; supported POSIX flows use the existing supervised
terminal with a ten-minute deadline and process cleanup. Windows receives the native
command to run manually. Direct app sessions use the startup command explicitly.
Unknown metadata, missing clients, quota exhaustion and expired free-plan evidence
are not reported as a confirmed logout. No tokens or account names enter history.

For configured free providers, explicit login opens the account page; opening it
does not verify a plan or renew evidence. An account whose only denial is expired
free-plan evidence no longer blocks other verified accounts. Credit, quota,
unresolved-request and binding denials still stop the group. All-expired groups
remain blocked; explicit requests never silently switch accounts.

Upgrade with `ai-session update --version 0.5.0 --apply`, then restart clients.
Preserve setup, accounting and private policy; no reauthorization or billing change
is required. Registered identical skill overlays are absorbed by automatic updates;
conflicting local changes require reconciliation. Authentication reports do not
prove a provider can execute: fresh admission and successful execution remain
separate checks.

## 0.4.4

Claude native quota refresh accepts the optional `seven_day_breakdown` product
statistics returned by current clients. Its validated rows do not become quota
pools. Session, weekly, model-scoped and unknown quota limits still undergo the
existing checks; credit eligibility and accounting are unchanged. Malformed
breakdown metadata continues to stop refresh.

Run `ai-session update` to install the published release on each maintained
computer. Retry fresh shared-authority admission with
`ai-session usage check claude`. No setup, quota-ledger reset, authentication or
paid-usage change is needed.

## 0.4.3

The onboarding prompt includes its official source and archive bootstrap. README
provides launcher PATH recovery, configuration defaults and a first task. Startup
instructions distinguish detected clients, active session identity and explicit
operator declarations. A plain SSH session can correctly have an unknown active
assistant. The computer guide no longer directs upgrades to an older fixed release.

This documentation release changes no inference adapters, model/effort selection,
authorization, quota or billing behavior. Existing settings remain selected. Use
the [interactive setup defaults](ONBOARDING.md#5-configure-interactively) and
[onboarding prompt](ONBOARDING-PROMPT.md) with the selected release.

## 0.4.2

Automatic worker and review effort selection uses advertised `medium`, otherwise
the highest advertised level below it. A model exposing only `low` or `medium`
is usable. Models advertising only higher levels are ineligible for automatic
work; some catalogs that previously selected high, xhigh or max now stop with
`unsupported_capability`. Select a compatible current model. Explicit supported
high reviews and native high verification remain available on compatible routes.
Manager defaults and quota, role and authorization checks are unchanged.

Copilot's no-override task path now derives effort from its selected catalog row.
It replaces inherited manager effort, using client-managed `None` when the model
advertises no effort control. An explicit supported override remains explicit.
Cursor's existing client-managed behavior is unchanged.

Discovery, worker qualification and review share strict effort-variant resolution.
An absent variant map preserves the selected base or resolved model. An explicit
map must contain a valid selected-effort variant; empty, malformed or incomplete
maps fail before launch. A missing strongest-manager variant stops discovery.
An invalid worker candidate may yield to a usable candidate in the same current
generation. No guessed base-model fallback is used for an explicit variant map.

## 0.4.1

Native reviews choose and validate effort against the same selected model. An
unsupported explicit effort, ambiguous catalog match or missing model variant fails
before execution. Copilot accepts efforts advertised for its selected model;
Cursor keeps client-managed effort and rejects overrides.
Successful review receipts add duration and byte counts, plus effort provenance.
Actual provider effort remains unknown when it is not reported. These fields do
not change accounting or establish a token price or subscription percentage.

The skill now routes conditional procedures to existing references and requires
explicit model/effort selection for native workers. Use its private checkpoint to
distinguish defects, incomplete evidence and control failures before another review.
Manager defaults, authorization, quotas and mandatory independent reviews remain.
See [review protocol](../skills/session-harness/references/review-protocol.md#avoid-unnecessary-review-work).

## 0.4.0

Add one provider through `ai-session onboard PROVIDER` or `ai-session PROVIDER onboard`.
The interactive wizard discovers installed route types, reuses existing setup and
preserves other services and account policy. It supports native/API authorization,
selected-provider imports of verified free configurations and local Ollama checks.
See [provider onboarding](../skills/session-harness/references/provider-onboarding.md)
for authentication, incomplete results and shared-authority boundaries. No inference,
secret store, model download or provider billing change is added.

## 0.3.2

The installed skill and personal profile now use one [dynamic session-start procedure](../skills/session-harness/references/session-start.md).
It discovers current configured capabilities, model/role eligibility and project
knowledge access, and includes a reusable task prompt. Reviewer selection uses
verified upstream families instead of fixed client pairs. Execution adapters,
account authorization, limits and accounting are unchanged.

## 0.3.1

Automatic native work now uses adapters that resolve a current model before
execution. Copilot and Cursor Auto remain available through explicit provider
commands. Their configured quotas still constrain every coordinated batch.
Legacy reserved automatic Auto jobs are denied at start and retain their history;
running jobs are not restarted. Inspect the new selection domain in status and
receipts. See [balancing](../skills/session-harness/references/balancing.md).

## 0.3.0

Version 0.3.0 adds opt-in subscription balancing, bounded text work and
metadata-only usage audits, Copilot and Cursor Auto workers, and local Ollama execution. It preserves independent provider reviews, API money
admission and installed release selection. See [behavior and capability boundaries](../skills/session-harness/references/balancing.md).
Optional model/role supervision settings keep quality decisions separate from usage
balancing; the owner selects restrictions without a hardcoded provider ranking.
A published v0.2.0 installation does not gain these commands from documentation alone.

## Everyday use

```sh
ai-session configure
ai-session configure --status
ai-session version
ai-session update --check
ai-session update
```

Configuration is guided: Enter keeps current settings and the final prompt confirms
the changes. `setup` remains an alias. Installation and updating do not authorize
inference. Native routes need configured services and fresh quota; APIs additionally
need a configured monthly money allowance. Calendar changes do not erase daily
consumption. Existing ledger timezone cannot be changed through setup because its
history is dated in that timezone.

`update` shows the release before asking to install it. In a noninteractive terminal
it only reports the command to apply. Scripts must name an exact `--version` with
`--apply`; `--check` never installs. For an exact install or rollback, replace
`VERSION` below with the published numeric version you have chosen after reading
its release notes:

```sh
ai-session update --version VERSION --apply
```

For v0.7.0, use `ai-session update --version 0.7.0 --apply`, then restart affected
clients. The manager defaults to advertised `xhigh`, otherwise the highest
supported level below `max`; `max` and `ultra` are excluded from default selection.
Existing conversations keep their selected model and runtime until restarted.

The same command selects an older release for rollback. A missing release, download
failure, invalid archive or checksum mismatch stops before installation. Since
v0.2.0, optional `auto-update` commands provide an
explicitly enabled background path; see [automatic maintenance](AUTO-UPDATE.md).
Updates need HTTPS access to GitHub; public downloads
need no GitHub token. They make no model calls.

Release archives include a committed-source manifest, installer, generic profile,
skill, documentation, license and contributor code graph. SHA-256 checksums and
GitHub's asset digest, when supplied, are verified before extraction. The updater
requires GitHub's immutable release marker. These checks establish integrity against
the published repository assets; they are not an independent publisher signature.
For an additional attestation check, use
[`gh release verify` and `gh release verify-asset`](https://docs.github.com/en/code-security/how-tos/secure-your-supply-chain/secure-your-dependencies/verify-release-integrity).

## Preserve personal policy and project rules

Run the installer examples below from the root of a verified release archive.
First reconcile existing instructions using [onboarding](ONBOARDING.md). Save unique
personal rules in a private Markdown file outside the public repository:

```sh
python3 scripts/install-agent-profile.py --launcher --personal-policy /absolute/path/to/personal.md
python3 scripts/install-agent-profile.py --launcher --personal-policy /absolute/path/to/personal.md --apply
```

The installer appends the file to the generic personal policy and remembers its
location. Every update and rollback reuses it. Keep lengthy environment notes in
private on-demand references linked by that addendum. Do not edit an immutable
installed snapshot. A missing registered addendum or modified managed copy blocks
replacement until reconciled. The update leaves setup authorization, the quota and
money ledgers, grants, history and unrelated client settings intact. Reverting code
does not restore an old ledger or undo spending. Future incompatible state migrations
must document supported rollback boundaries; v0.1.0 introduces no destructive migration.

Projects normally keep one canonical `AGENTS.md`, supported client aliases, and a
short reference to `~/.agents/skills/session-harness/SKILL.md`. They share the installed
release and need no source-copy update. A project that explicitly vendors a customized
skill keeps its own source pin and review process. `ai-session update` does not change
those files or enforce project-specific version selection. Report runtime drift instead
of claiming that every project has upgraded.

On Windows, updates retain the explicitly selected checked-copy mode. The installed
PowerShell launcher requires PowerShell 7.3+; Python can run `ai-session.py` directly.
On macOS/Linux, the launcher uses the Python interpreter selected during installation.
Restart clients after an update. Active sessions keep their already-selected runtime.
Claude hook installation is separate and idempotent; review and apply a hook refresh
when release notes require it. Updates do not rewrite unrelated settings or hooks.

## Recovery

## Codex reports missing historical pools

A pool disappearing from a quota response still blocks admission. First inspect
`ai-session usage check codex` and verify that the named pool is no longer applicable;
a partial outage or missing telemetry is not permission to retire it. Back up the
ledger with SQLite's backup API before changing accounting metadata.

On the configured **account authority**, explicitly reconcile only those names:

```sh
ai-session usage reconcile-pools codex --retire-pool 'optional:primary' --confirm-retired
ai-session usage check codex
```

Repeat `--retire-pool` for each verified obsolete pool. Remote clients refuse local
reconciliation; run the command on their authority. A fresh, complete native read is
required. Empty or malformed quota maps and partial rows remain blocked, including
during reconciliation. Legacy responses without a limit map remain supported.

Reconciliation archives the last observations without deleting daily consumption,
reset history, budget anchors, grants or policy. A reappearing pool resumes accounting
from its archived observation and again participates in all limits. This command
neither grants quota nor changes strict/observed mode or paid-usage settings.

A failed final refresh can leave an already committed retirement. Inspect
`ai-session usage status codex`, then retry `ai-session usage check codex`; do not
blindly repeat retirement. A midnight boundary can require another fresh attempt.
Keep runtime 0.5.1 or newer after reconciliation: older versions do not understand
reactivating archived observations. Never restore an old ledger to roll back code.


### Claude reports account_session_busy

This is a session-capacity stop. Check `ai-session coordination status`, then close
an unused session or change capacity on the authority with
`ai-session coordination set --max-sessions 8`. Starting with v0.1.2, increasing
capacity works while sessions are active. Updates preserve an existing limit of one;
they do not silently migrate it. All sessions continue to share the same quota budget.
For crashed owners, confirm termination before release. See
[session coordination](../skills/session-harness/references/coordination.md).

### Claude stops because a reset is unknown

If a hook reports `unknown_adaptive_reset` and `budget_anchor_missing`, inspect
the installed version and pool status from a terminal:

```sh
ai-session version
ai-session update --check
ai-session budget claude
```

Starting with v0.1.1, a verified native long-window duration supports conservative
daily pacing even when the reset timestamp is absent. Update older installations
with `ai-session update`, restart Claude to reload instructions, and retry the
message. A project with a vendored skill must update its selected copy too.

If both the reset and native duration are unknown, the pool still needs reliable
metadata or an explicitly chosen fixed/window policy. A genuine daily-limit stop
is separate. Do not disable the hook, delete accounting or assume a missing reset
means unlimited usage. See [budget controls](../skills/session-harness/references/budgets.md).

### Installation and updater recovery

Installer previews and private backups describe replaced files. A failed download
leaves the installed release intact; installation failures report their error and
retain backups for inspection. File replacement is individually atomic, not an
all-files transaction. Stop concurrent installers, inspect the manifest, then rerun
the selected version or restore only the affected instruction links. Never restore
an old quota database to undo an update.

`update.lock` under the private state directory excludes another updater. After a
crash, confirm that no updater is running before removing that directory. It is
unrelated to quota locks and session ownership. Keep old immutable snapshots for
running sessions and recovery; automatic cleanup is deliberately absent.

## Maintainer publication

For changes that affect setup, everyday commands, limits, updates or recovery,
review the affected workflow from a new user's perspective before publication:

- Follow the code graph to the implemented command and read its actual options.
- Rewrite the matching README, onboarding prompt/guide and skill references;
  replace obsolete commands and defaults rather than accumulating conflicting advice.
- Include the entry command, required configuration, expected result and recovery
  from relevant errors. Keep private environments and account evidence out of examples.
- Check that examples work in supported shells and retain documented platform limits.
- Explain upgrade or restart requirements in release notes. After the push, verify
  docs and configured consumers against their selected versions; documentation-only
  changes do not require replacing an unchanged installed runtime.

For a runtime release:

1. Update `skills/session-harness/VERSION`, release notes and the relevant README,
   onboarding, profile and skill instructions. Query the code graph before edits.
2. Stage new Python paths and rebuild the committed graph. Run the portable suite
   and inspect Linux, macOS and Windows CI. Test a release install in an isolated
   home, including private-policy preservation and accounting-safe rollback.
3. Commit the reviewed source. Build from that commit into a private directory:
   `python3 scripts/release.py --ref HEAD --output /absolute/path/outside/checkout`.
   The builder reads Git objects, never untracked files or dirty working-tree content.
4. Enable repository release immutability. Create a draft for a new `vX.Y.Z` tag,
   attach `session-harness-X.Y.Z.zip` and `SHA256SUMS`, verify both and publish.
   GitHub recommends [attaching assets before publication](https://docs.github.com/en/code-security/concepts/supply-chain-security/immutable-releases).
5. Check release metadata and download/install the public artifact. After each push,
   check README/docs/skills and configured consumers. Upgrade consumers explicitly
   to the published release; keep their paths and state in private records.

Never move or reuse a published tag, rewrite release history, include private setup
in an artifact, or silently upgrade consumers to an unreleased branch.
