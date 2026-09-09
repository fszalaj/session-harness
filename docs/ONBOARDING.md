# Onboard a personal environment and project

Use the [short onboarding prompt](ONBOARDING-PROMPT.md) to delegate this procedure.
The result should be a working discovery setup, preserved project conventions and
a clear account of what can actually execute. Installation alone is not acceptance.

## 1. Select and verify the release

For an existing installation, run `ai-session version` and inspect its recorded
provenance. Keep that selected release unless the owner requests an update;
`ai-session update --check` is read-only. Use [releases and rollback](RELEASES.md)
for an authorized version change. To select v0.3.2, run
`ai-session update --version 0.3.2 --apply`, then restart affected clients.
Do not reinstall from an arbitrary checkout.

For a new installation, open the [latest stable release](https://github.com/fszalaj/session-harness/releases/latest)
once and stay on that release's page. Record the selected tag. Download the named
`session-harness-VERSION.zip` asset and `SHA256SUMS` from that same release into an
otherwise empty directory. `VERSION` denotes the version shown on the page, not a
literal filename. Use these published assets, not GitHub's generic source archives.
Do not follow `main` or resolve `latest` again midway through installation.

Python 3.11+ and Git are prerequisites. On Windows, substitute `python` for
`python3`. In the download directory, this portable Python command checks the
single-archive checksum format produced by `scripts/release.py`:

```sh
python3 -c "from pathlib import Path; import hashlib; digest, name = Path('SHA256SUMS').read_text().strip().split(); archive = Path(name); actual = hashlib.sha256(archive.read_bytes()).hexdigest(); print(archive.name, actual); raise SystemExit(0 if actual == digest else 'Checksum mismatch - stop')"
```

Continue only on a successful match. SHA-256 checks download integrity; a checksum
from the same publisher is not an independent signature. Extract the verified ZIP
using your archive tool, then open a terminal inside its `session-harness-VERSION`
root, where `scripts/` and `RELEASE.json` are present. The release metadata records
the source version and commit; the installer records provenance in its private
manifest. Keep that record with the selected tag and checksum for verification.

## 2. Inspect and choose scope

Identify the hosting client, harness checkout, target project and dirty files.
Distinguish application, interface and model provider: Copilot CLI, VS Code Chat
and GitHub code review are different instruction consumers; Gemini CLI and
Antigravity are different clients even when both use Google models. Check the
[client instruction map](../skills/session-harness/references/instructions.md)
against installed versions and current official documentation. Include other
discovered clients without assuming they share a filename or execution adapter.
Inspect personal and applicable project instructions, including linked targets and
nested rules. List relevant user-owned skills and their discovery paths. Read the
project's existing durable summary and knowledge entry point before architecture
work. Do not collect credentials, transcripts or unrelated personal files.

Use existing authenticated subscriptions. Inventory does not authorize installing
clients, purchasing subscriptions or changing paid-usage settings. A normal local
installation needs filesystem access, not a GitHub PAT or repository-admin scope.
Cloning a private repository separately requires access to that repository.

## 3. Consolidate instructions and owned skills

Compare native instruction sources at each scope, including `AGENTS.md`,
`CLAUDE.md`, `GEMINI.md`, `.github/copilot-instructions.md`, Copilot
`*.instructions.md`, `.cursor/rules`, legacy `.cursorrules` and Cursor User Rules
when present. Keep scoped conditions and activation metadata with their native
rules; do not flatten them into unconditional global instructions. Keep personal policy
separate from project rules. Merge unique compatible rules into that scope's
canonical `AGENTS.md`, preserve originals privately and point supported aliases to
it with relative symlinks. Preserve meaningful client-specific content through
client-supported scoped files or references. Resolve material conflicts with the
user when current instructions do not settle them. Verify each link resolves and
the actual client loads its contents. A Git symlink can be read as link text by a
remote integration; use a supported import or maintained generated view if verified
symlink loading is unavailable. A Markdown hyperlink alone does not prove automatic
context loading. Keep one authoritative source and check generated-view drift.

Retain the `GEMINI.md` compatibility alias for default Gemini CLI and the documented
Antigravity global rule entry point. Configuring Gemini CLI `context.fileName` to
`AGENTS.md` is an alternative, not a prerequisite imposed by this installer. Avoid
loading identical rules through several configured filenames. Do not create a
Copilot repository alias solely for CLI users whose existing `AGENTS.md` already
loads; add a verified native entry point when the selected Copilot surface needs it.

For relevant user/project-owned skills, inspect purpose, trigger precision, actual
scripts/functions and references. Retain useful unique behavior; remove redundant
prose, move lengthy procedures to linked references and consolidate duplicate
skills only when their discovery and functions remain covered. Preserve local
modifications, installed standalone skills and a mapping of old entry points. Do not modify vendor-managed
system skills or plugin caches. Avoid a broad rewrite of unrelated skills.

The installer snapshots the generic profile and harness sources. Save unique personal
rules in a private Markdown addendum outside the upstream checkout, then pass
`--personal-policy /absolute/path/to/personal.md` to preview and apply. Subsequent
updates reuse that registered file automatically. The installer does not semantically
merge conflicting policies. An existing skill directory at a managed destination
must be preserved and reconciled before installation.

## 4. Test, preview and install globally

On Windows, first install timezone data from the extracted release root with
`python -m pip install -r requirements-windows.txt`.

From the verified extracted release root (or the retained source of an existing
installation):

```sh
python3 scripts/test.py
python3 scripts/install-agent-profile.py --launcher
python3 scripts/install-agent-profile.py --launcher --apply
```

On Windows, use `python`, first run
`python -m pip install -r requirements-windows.txt`, and add
`--link-mode copy` to both installer commands when symlinks are unavailable.
PowerShell 7.3+ supports the installed `.ps1` launcher; Python can invoke
`ai-session.py` directly. Copy mode checks drift instead of overwriting user edits.
Read [platform support](../skills/session-harness/references/platforms.md).

Use the same optional `--personal-policy` on both installer commands. `--repo`
selects the release source checkout when it differs from the installer location. Review preview replacements before applying; installation requested
by the user covers reversible installation, with unresolved policy conflicts
handled first. The installer records private backups and a manifest, creates
verified snapshots, links personal instructions and skills, and installs the
launcher. Keep the reported backup location for rollback.

Custom client homes are rejected when unsupported. Preserve them and configure
verified instruction paths explicitly. Add `~/.local/bin` to PATH if needed.
Restart affected clients to reload instructions. The installer also adds a global Cursor
rule in `~/.cursor/rules/session-harness.mdc`. Local installation does not configure
remote/cloud workers or editor inline completions.

## 5. Configure with the owner

```sh
ai-session configure
ai-session configure --status
ai-session coordination status
ai-session budget
```

`configure` is the interactive alias for `setup`; existing selections are defaults.
`ai-session setup` is the owner's explicit environment authorization. Run it
interactively with the owner: it selects the native and API services allowed to
run inference, confirms timezone, working days, reset cutoff, quota mode and session capacity, and
for API services requires a positive monthly total and money mode. Until it is
complete, launch, review and API dispatch return `environment_setup_required`.
Repeating setup, reinstalling or changing budgets keeps accounting history. Do
not complete it noninteractively on the owner's behalf.

New configurations allow four sessions per service; all share the account budget.
Existing explicit capacity is retained. Use `ai-session coordination status` to
inspect actual authority occupancy and `ai-session coordination set --max-sessions 8`
on that authority to change it. Different accounts have separate authorities; joining
the same repository does not merge their quotas. See [session coordination](../skills/session-harness/references/coordination.md).

Ask whether the same account is used on several computers. Choose `local` for one
machine, or configure one already trusted SSH quota authority with
`ai-session coordination set --authority user@host`. Set up that authority first
with the same accounts; verify connectivity privately. Separate installations do
not coordinate automatically. Cross-machine API dispatch is blocked; paid requests
run on the monetary authority. Read the [coordination procedure](../skills/session-harness/references/coordination.md)
before configuring shared use. Direct clients outside its controls remain unprotected.

Offer deterministic Claude hooks where applicable: `ai-session hooks --install`
previews the settings merge; append `--apply` for the authorized installation.
Preserve existing hooks/settings and restart Claude. Hooks cover supported events,
not every client or streaming response. Follow the coordination reference for limits.

Strict mode is the default and denies inference without enforceable bounds.
Observed mode requires the owner's explicit choice and accepts possible in-flight
overshoot. Keep existing authentication, mode, strategies, reserves, grants and
history. Do not use an example budget as authorization to change private policy.
Review calendar, timezone, cutoff, fallback strategy and service/pool overrides
using [budget controls](../skills/session-harness/references/budgets.md). An existing
ledger's timezone must remain consistent with its dated history. No mandatory 10%
reserve applies. If the owner defers configuration, report
`environment_setup_required` and complete the remaining read-only verification.

Only if the owner requests paid API use, follow [API and money setup](../skills/session-harness/references/api-and-spend.md)
for supported services, existing key presence, explicit monthly authorization,
separate money mode and bounded dispatch. Never reveal keys, buy credits, enable
automatic reload or infer API entitlement from a subscription. Installation itself
creates no paid allowance and changes no authentication.

Version 0.3.0 offers a [reviewed coding profile](../skills/session-harness/references/coding-models.md)
for five additional model families through one OpenRouter account. Inspect it with
`ai-session api coding-models` before choosing an exact ID. Follow the guide to add
private key delivery and explicit API money authorization; public catalog access
does not establish account entitlement. Keep account records out of project docs.

For recurring free API allowances, use the separate
[free-access procedure](../skills/session-harness/references/free-access.md).
Verify the account's no-paid-overage controls, model, rates and remaining allowance
before configuring it. Select one execution host and use its SSH interface from
other computers. A saved key alone does not enable dispatch; missing evidence
keeps a provider disabled. No monetary budget or billing upgrade is created.

Use the newest available generation within each model family by default. In v0.3.1,
automatic native `work` selects Codex, Claude or Antigravity and resolves its current
worker model. To choose platform Auto explicitly, use `work --provider copilot` or
`work --provider cursor`; these routes do not verify newest-generation selection.

For version 0.3.1 installations, a user requesting even native
subscription use can enable [shared fractional pacing](../skills/session-harness/references/balancing.md).
Use only configured services with protected execution adapters. API money budgets
and inventory-only clients remain separate; installation does not opt anyone in.
The same guide explains optional model/role supervision settings controlled by the
owner. They apply through the common authority and survive disabling balancing.

Version 0.3.0 installations print a readable explanation when a protected session
stops. A daily allowance stop ends the owned client process; reopen the client and
use its resume option after admission is restored. Inspect `ai-session coordination
status` and run `ai-session budget SERVICE` on the account authority. If cleanup is
reported as unconfirmed, inspect the retained owner's processes before recovery.
See [stop recovery](../skills/session-harness/references/usage-and-context.md#when-a-protected-session-stops).

Inspect the requested and actual worker model in each receipt. Development Claude
selection resolves current aliases and prefers a current Sonnet for bounded work.
Fable and overall weekly limits are separate. Version 0.3.0 checks the actual
model and can resume on current Opus after a verified Fable-only stop.
See [model allowances and recovery](../skills/session-harness/references/model-allowances.md)
for the shared-authority check command and supported interactive launch controls.

## 6. Integrate the project and knowledge layer

Keep application rules in the project's `AGENTS.md`. Add a short reference such as:

> For substantive work, use `~/.agents/skills/session-harness/SKILL.md`, unless this
> repository explicitly selects a maintained project copy. Honor shared usage and
> context safeguards. Use enabled subscription balancing for bounded workers (otherwise native same-family workers) and independent reviews from
> the other two provider families when supported. Leaf assignments and trivial
> tasks do not restart orchestration. Preserve this project's rules.

Prefer the installed release for projects that need no harness customization. Run
`ai-session update --check` to inspect releases and `ai-session update` for a confirmed
update; see [release management](RELEASES.md). Version 0.2.0 also offers
explicitly enabled [automatic maintenance](AUTO-UPDATE.md): register reviewed local
overlays, choose `auto-update enable --interval-hours 24`, and verify actual scheduler
delivery and maintenance-aware authority entry points. Keep it off unless the owner
chooses it, and preserve existing opt-ins. Do not equate this flag with provider
billing auto top-up. A project-owned copy is appropriate when the repository needs
reviewed, versioned customization. Select one canonical skill directory, link client discovery paths
where supported, and identify its source and update procedure. Do not copy this
repository's maintenance policy over another project's `AGENTS.md`.

Reuse the project's durable documentation or vault. Record its entry point, reading
order, session handoff location and how decisions/tests update durable pages. If a
code graph exists, document its query command, measured blind spots and rebuild
procedure. Use that graph for dependencies and blast radius before code, README or documentation changes. If neither exists,
start with a small project-owned knowledge entry page and source inspection; do
not add a service merely to satisfy onboarding.

Knowledge-gateway can supply knowledge access and graph queries. Session harness
supplies workflow, review and usage admission. Neither replaces the other's role,
and harness installation does not require knowledge-gateway or migrate its data.

## 7. Discover capabilities and verify admission

```sh
ai-session inventory
ai-session usage refresh SERVICE
ai-session usage status SERVICE
ai-session usage check SERVICE
```

Replace `SERVICE` with the configured supported service. For first-time prospective
observation only, explicitly initialize with `ai-session usage refresh SERVICE --initialize`.
Run initialization on the quota authority for a shared account, preserving its history.
In version 0.3.0, `usage check` for Codex, Claude, Antigravity, Copilot and Cursor refreshes
that configured authority, including when no model is supplied. `usage status` reads
the local ledger; a remote check does not refresh this local cache, so it can remain
stale. `usage refresh` updates only the machine where it runs and is not coordinated
admission. Cursor requires a verified personal Free account with on-demand usage disabled.
Follow the [additional client runbook](CLIENT-EXECUTION.md) for Copilot and Cursor
execution, account limits and recovery.
Retain existing observation history. `usage check` reports
`environment_setup_required` until `ai-session setup` names that service.
Initialization starts prospective observation; it cannot recover earlier daily usage. Choose the ledger
timezone and private state path before initialization. A new ledger defaults to UTC;
`--timezone` can select an IANA timezone at creation, but must match an existing
ledger because its dated history is retained. Local projects share a ledger, but
separate computers do not share a distributed admission lock.

Separate installed, authenticated, account-visible and successfully invoked states.
For Claude, `auth_required` from discovery means the native client reported no signed-in
account in that execution context. Check native sign-in in the affected terminal or
application; a successful shared quota check does not authenticate that client.
Select current account-visible models and supported effort dynamically, verify
actual session selection, and distinguish provider family from the service owning
the quota. Do not pin current model IDs or interpret a model list as review access.

Follow the selected release's [usage and context procedure](../skills/session-harness/references/usage-and-context.md)
and [provider validation guide](PROVIDER-VALIDATION.md). Inspect `allowed` and stop
reasons: metadata success is not admission. Missing, stale or incomplete evidence
blocks inference; calendar rules and grants cannot create provider headroom. Do
not run a paid request merely to make onboarding appear complete.

Version 0.1.2 blocked protected Codex execution because its credit
schema did not establish paid-use disablement. Version 0.2.0 accepts
owner-bound confirmation of disabled Auto top-up with fresh zero-credit evidence;
check the selected release before using that route. Antigravity requires verified
disabled `useG1Credits`, including its documented default for an absent file/key;
enabled, malformed or unreadable settings block. The harness never changes billing
settings. Native extra-credit accounting retains reported units and does not prove
protected paid execution.

Select the strongest account-available hosting-provider model as manager at Extra
High (`xhigh`), falling back to the highest advertised level below `max` if needed.
Use `max` only by explicit task-level selection for an extremely difficult task.
Since v0.2.1, the launcher applies this default and excludes `max` and `ultra` from
default selection. Use native model/effort controls for an explicit exception;
the launcher has no generic `--effort` flag. Use bounded fresh-context native workers at
medium effort, low for gathering. Two distinct other-provider families review the
same plan independently, normally at medium effort. Reconcile findings and report
missing reviews accurately. Do not start a new harness cycle for trivial or leaf work.

Keep the same task in the current session through compaction by default. At 60%
context usage, save a checkpoint; at 75%, reduce new context and use bounded packets;
at 85%, use native compaction when available and resume from the checkpoint. These
are advisory thresholds: Markdown instructions cannot invoke a client's compaction
control. Start a fresh session for an unrelated task, a required model change or
failed context recovery, carrying the necessary handoff when work continues.

## 8. Verify and hand off

Rerun the installer preview and confirm expected paths are unchanged. Resolve
instruction/skill links and verify the loaded runtime path/hash after restart.
Run deterministic tests after any source changes. Report discovery and admission
separately; unavailable clients or blocked inference are capability limits, not
successful live reviews. Copilot and Cursor execution is not verified by inventory. Gemini CLI has no
verified harness launch/review adapter. For other clients, record instruction/skill
compatibility separately from unavailable model, quota, worker and review controls.
Use Copilot CLI `/instructions`, Gemini CLI `/memory show` and the client's rule/skill
UI where documented. File existence and symlink resolution alone are insufficient.

Leave a concise durable record of selected scope, preserved rules, changed skills,
knowledge/graph integration, tests, restart needs, quota mode and unresolved items.
Keep private paths/account evidence in private notes. After every push, verify
README/docs/skills and configured consumers against their selected release without
publishing consumer repositories or private setup. Use explicit release updates;
do not follow development main or edit immutable snapshots in place.

Rollback uses the manifest to restore only changed paths from private backups.
Restore symlink text without dereferencing relative links. Preserve new user edits
made since installation and retain snapshots while any managed link uses them.
Never remove entire vendor configuration directories.

When vendoring the harness, copy its root `LICENSE` and `NOTICE` into the
vendored skill directory. The installer includes both files with the shared
profile and installed skill. Preserve these Apache 2.0 licensing files in
maintained source copies.
