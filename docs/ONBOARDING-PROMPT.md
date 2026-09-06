# Copy-paste onboarding prompt

Use this prompt with a coding assistant that can inspect your local files. Name the
harness checkout and target project when they are not already clear.

```text
Onboard session-harness globally and into this project. Read its README and
docs/ONBOARDING.md and skills/session-harness/references/instructions.md. Identify
the hosting client and installed clients I use: Codex, Claude Code, Gemini CLI,
Antigravity, GitHub Copilot (CLI, IDE or GitHub) and Cursor (local or cloud), plus
Kimi CLI, OpenCode, Aider, Continue, Ollama and any others discovered. Distinguish
Grok/xAI, DeepSeek, Kimi/Moonshot and GLM/Z.ai model families from their hosting
client and billing service. Check current official rules for the actual client/version;
do not infer support from the model provider. Inspect instructions, skills and dirty
state, then carry out reversible changes and verification within this request.

Audit AGENTS.md, CLAUDE.md, GEMINI.md, Copilot instructions and scoped rules, Cursor
rules/User Rules, and other detected clients' native entry points at personal and
project scope. Preserve unique rules, scope, activation settings and user edits.
Use one canonical personal AGENTS.md and one canonical AGENTS.md per project,
with one shared skills root at each scope. Consolidate compatible rules and create
relative symlinks from supported native instruction/skill paths to those targets.
Verify actual client loading; where symlinks do not load, use a supported import
or checked generated view. Preserve scoped rules and avoid duplicate context.
Gemini CLI defaults to GEMINI.md; keep its compatibility link unless AGENTS.md
discovery is explicitly configured and verified. Do not conflate Gemini CLI with
Antigravity CLI or IDE. Copilot support varies by feature; do not assume AGENTS.md
covers every IDE or GitHub surface. Cursor reads project AGENTS.md, but global
User Rules require its supported UI. A local skill does not configure cloud workers.
For another AI client, verify its documented entry points before adding integration.

Audit relevant user/project-owned skills for necessity,
length, triggers and actual functions; consolidate duplication without losing
behavior. Do not edit vendor-managed skills or silently discard conflicts.

Preserve backups before changes. Merge personal policy before applying the
installer; backups alone do not keep rules active. Prefer existing project
knowledge and graph tools, including knowledge-gateway if available, without
adding a mandatory backend. Document the reading order and durable handoff path.
Discover installed clients, current selectable models and supported effort without
version pins or assumptions based on a subscription name. Separate advertised
catalogs, account-selectable options and verified execution; retain unknowns.
Preserve persisted quota strategies, reserves, grants, mode and history until I
authorize migration. New ledgers use fixed 20 percentage points/day and reserve 0;
there is no mandatory 10% floor. For a full-utilization target I select, configure
adaptive per-pool budgets with reserve 0 from actual reset metadata. Otherwise
retain the existing policy or new-ledger defaults.

Review editable calendar preferences with me: working days (all seven by default),
IANA timezone (UTC for a new ledger), inclusive reset cutoff (08:30 by default),
fallback reserve and service/pool overrides. Show `ai-session budget calendar
--workdays all --reset-cutoff 08:30 --timezone UTC`; working days also accept
`weekdays` or a list such as `mon,tue,thu`. Timezone can initialize a new ledger but
must match an existing ledger to preserve dated history. `ai-session budget defaults
--reserve 0` changes only the fallback; explicit service/pool reserves take precedence.
Apply changes only within my chosen policy. Adaptive pacing divides the balance over
eligible working days. On a working day, a reset at or before tomorrow's cutoff
releases the full current native balance subject to the selected reserve and fresh,
complete evidence. Days off have no automatic allowance; explicit grants can add it.
Show `ai-session budget`, `ai-session budget add SERVICE 5` and
`ai-session budget use-rest SERVICE`. Unknown reset schedules need an explicit
policy, not an invented renewal date. Calendar rules and grants cannot create
provider headroom or bypass missing evidence.

Continue the same task through compaction by default: checkpoint at 60% context,
reduce new context at 75%, use native compaction at 85% when available, then resume.
These thresholds are advisory; Markdown cannot invoke the client's native compact
control. Use a fresh session for an unrelated task, a required model change or failed
context recovery, with a handoff when continuing work.

Run deterministic tests and an install preview, install globally, integrate the
project, restart or report the required restart, and verify actual discovery and
idempotence. Report instruction loading, skill discovery, model access and protected
execution separately. Copilot/Cursor instruction compatibility does not establish
working review, quota or manager adapters; Gemini CLI is not an Antigravity adapter.
Keep the existing explicit quota-mode choice; otherwise use strict mode unless I
opt into observed-threshold stopping with possible in-flight overshoot. Do not change billing, authentication,
repository visibility or publish anything. Report changes, checks, rollback paths
and any remaining decisions or unavailable capabilities.
```
