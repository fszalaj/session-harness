# Onboard a personal environment and project

Use the [short onboarding prompt](ONBOARDING-PROMPT.md) to delegate this procedure.
The result should be a working discovery setup, preserved project conventions and
a clear account of what can actually execute. Installation alone is not acceptance.

## 1. Inspect and choose scope

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

## 2. Consolidate instructions and owned skills

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
modifications and a mapping of old entry points. Do not modify vendor-managed
system skills or plugin caches. Avoid a broad rewrite of unrelated skills.

The installer snapshots `profile/AGENTS.md` and the maintained harness sources; it
does not semantically merge existing rules. If personal rules differ, prepare a
private maintained source copy, merge those rules into its `profile/AGENTS.md`,
and use `--repo /absolute/path/to/private-source` for both preview and apply.
Keep personal additions out of a public upstream commit. An existing skill
directory at a managed destination must be preserved and reconciled before
installation; do not delete it to clear the installer check.

## 3. Test, preview and install globally

From the selected harness checkout:

```sh
python3 scripts/test.py
python3 scripts/install-agent-profile.py --launcher
python3 scripts/install-agent-profile.py --launcher --apply
```

On Windows, use `python`, install `requirements-windows.txt`, and add
`--link-mode copy` to both installer commands when symlinks are unavailable.
PowerShell 7.3+ supports the installed `.ps1` launcher; Python can invoke
`ai-session.py` directly. Copy mode checks drift instead of overwriting user edits.
Read [platform support](../skills/session-harness/references/platforms.md).

Use the same optional `--repo` on both installer commands when using a private
merged source. Review preview replacements before applying; installation requested
by the user covers reversible installation, with unresolved policy conflicts
handled first. The installer records private backups and a manifest, creates
verified snapshots, links personal instructions and skills, and installs the
launcher. Keep the reported backup location for rollback.

Custom client homes are rejected when unsupported. Preserve them and configure
verified instruction paths explicitly. Add `~/.local/bin` to PATH if needed.
Restart affected clients to reload instructions. Cursor global User Rules require
its UI; local installation does not configure remote/cloud workers.

## 4. Integrate the project and knowledge layer

Keep application rules in the project's `AGENTS.md`. Add a short reference such as:

> For substantive work, use `~/.agents/skills/session-harness/SKILL.md`, unless this
> repository explicitly selects a maintained project copy. Honor shared usage and
> context safeguards. Use native same-family workers and independent reviews from
> the other two provider families when supported. Leaf assignments and trivial
> tasks do not restart orchestration. Preserve this project's rules.

A project-owned copy is appropriate when the repository needs reviewed, versioned
customization. Select one canonical skill directory, link client discovery paths
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

## 5. Discover capabilities and establish usage policy

```sh
python3 skills/session-harness/scripts/harness.py inventory
python3 skills/session-harness/scripts/harness.py usage refresh codex --initialize
python3 skills/session-harness/scripts/harness.py usage status codex
python3 skills/session-harness/scripts/harness.py usage check codex
```

Use the relevant supported client in place of `codex`. Initialization starts
prospective observation; it cannot recover earlier daily usage. Choose the ledger
timezone and private state path before initialization. A new ledger defaults to UTC;
`--timezone` can select an IANA timezone at creation, but must match an existing
ledger because its dated history is retained. Local projects share a ledger, but
separate computers do not share a distributed admission lock.

Separate installed, authenticated, account-visible and successfully invoked states.
Select current account-visible models and supported effort dynamically, verify
actual session selection, and distinguish provider family from the service owning
the quota. Do not pin current model IDs or interpret a model list as review access.

Strict mode remains the default and blocks inference without enforceable bounds.
Observed-threshold mode is an explicit local user choice accepting possible
in-flight overshoot. Preserve the existing budget strategy, reserves, grants and
history until the user authorizes a migration. New ledgers default to adaptive allocation and a 0% reserve. There is no mandatory 10% floor.
For an authorized full-utilization target, configure adaptive budgets with reserve
0 for the relevant service or pool.

Review these editable preferences during onboarding: working days, ledger timezone,
reset cutoff, fallback strategy, fixed daily limit, reserve and any service/pool overrides. The calendar defaults
to all seven days and an inclusive 08:30 cutoff in the ledger timezone. Examples:

```sh
ai-session budget calendar --workdays all --reset-cutoff 08:30 --timezone UTC
ai-session budget defaults --strategy adaptive --reserve 0
ai-session budget set codex --strategy adaptive --reserve 0
ai-session budget
ai-session budget add codex 5
ai-session budget use-rest codex
```

Apply the examples only when they match the selected policy; substitute the relevant
service. `--workdays` accepts `all`, `weekdays` or a comma-separated list such as
`mon,tue,thu`. The fallback reserve set by `defaults --reserve 0` does not override
explicit service or pool reserves. Inspect those settings before claiming migration
is complete.

Adaptive pacing divides the available balance across eligible working days. On a
working day, a reset at or before tomorrow's cutoff releases the full current native
balance, subject to the selected reserve and fresh, complete quota evidence. Days
off have no automatic allowance; explicit `add` or `use-rest` grants can make room
for authorized work. Neither calendar rules nor grants invent provider headroom,
waive missing evidence or prove that a reset has occurred.

Read [budget controls](../skills/session-harness/references/budgets.md) for daily
additions, actual reset horizons and unknown-window exceptions. Follow the maintained
[usage policy](../skills/session-harness/references/usage-and-context.md) and CLI
help for configuration. Metadata success is not admission: inspect `allowed` and
stop reasons. Do not run a paid inference merely to make onboarding appear complete.

For explicitly authorized paid work, include the eight direct API routes listed in
[API and money setup](../skills/session-harness/references/api-and-spend.md).
Discover existing key presence without exposing values, select current models and
establish a total monthly amount/currency before inference. Show `ai-session spend
status`, `spend set`, `spend add`, `api models` and bounded `api run`. Money mode is
separate from subscription mode. Never create a paid allowance merely to finish
onboarding. Native extra-credit receipt accounting does not establish protected
native paid execution; retain units and report missing eligibility controls.
Current Codex and Antigravity readers cannot establish paid-use disablement, so
their protected native adapters remain blocked despite available quota metadata.

Keep the same task in the current session through compaction by default. At 60%
context usage, save a checkpoint; at 75%, reduce new context and use bounded packets;
at 85%, use native compaction when available and resume from the checkpoint. These
are advisory thresholds: Markdown instructions cannot invoke a client's compaction
control. Start a fresh session for an unrelated task, a required model change or
failed context recovery, carrying the necessary handoff when work continues.

## 6. Verify and hand off

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
README/docs/skills against published code and synchronize configured local consumers
without publishing their repositories or private setup. Update maintained sources
and reinstall for future changes; do not edit immutable snapshots in place.

Rollback uses the manifest to restore only changed paths from private backups.
Restore symlink text without dereferencing relative links. Preserve new user edits
made since installation and retain snapshots while any managed link uses them.
Never remove entire vendor configuration directories.

When vendoring the harness, copy its root `LICENSE` and `NOTICE` into the
vendored skill directory. The installer includes both files with the shared
profile and installed skill. Preserve these Apache 2.0 licensing files in
maintained source copies.
