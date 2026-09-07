# Copy-paste onboarding prompt

Use this prompt with a coding assistant that can inspect your local files. Name the
harness checkout and target project when they are not already clear.

```text
Onboard the latest published stable session-harness release globally and into this project.
Use a fixed release tag, never a moving main branch for a maintained installation. Read its README and
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

Preserve backups before changes. Keep unique personal policy in a private Markdown
addendum outside the public checkout and register it with --personal-policy during
installation; updates must retain it. Backups alone do not keep rules active. Use the existing code graph before code, README or documentation changes,
checking measured blind spots in source. Prefer existing project
knowledge and graph tools, including knowledge-gateway if available, without
adding a mandatory backend. Document the reading order and durable handoff path.
Discover installed clients, current selectable models and supported effort without
version pins or assumptions based on a subscription name. Separate advertised
catalogs, account-selectable options and verified execution; retain unknowns.
Preserve persisted quota strategies, reserves, grants, mode and history until I
authorize migration. New ledgers use adaptive allocation and reserve 0;
there is no mandatory 10% floor. For a full-utilization target I select, configure
adaptive per-pool budgets with reserve 0 from actual reset metadata. Otherwise
retain the existing policy or new-ledger defaults.

On Windows, install the timezone dependency and use explicit --link-mode copy
when symlinks are unavailable. Preserve checked-copy drift and backups; use
PowerShell 7.3+ or the Python launcher, not a cmd.exe interpolation wrapper.

Review editable calendar preferences with me: working days (all seven by default),
IANA timezone (UTC for a new ledger), inclusive reset cutoff (08:30 by default),
fallback strategy, fixed daily limit, reserve and service/pool overrides. Show `ai-session budget calendar
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

Include explicit API support for OpenAI, Anthropic, Gemini, xAI/Grok, DeepSeek,
Moonshot/Kimi, Z.ai/GLM and OpenRouter. Read references/api-and-spend.md within the
skill. Inventory existing key presence without exposing values. Do not assume a
subscription supplies an API key or that catalog order ranks model strength.
If I authorize paid use, establish my total monthly amount/currency and optional
service caps with `ai-session spend`; preserve separate monetary and subscription
modes. Show `spend status`, `spend add`, `api models` and bounded `api run`.
Missing monetary authorization leaves paid execution disabled. Native extra credits
retain their units; record verified monetary receipts under extra:SERVICE when
applicable. Never buy credits, enable automatic reload or invent dollar conversion.
Report missing paid-eligibility controls honestly, including native Codex and
Antigravity limitations. Keep account evidence and personal setup out of public files.

Continue the same task through compaction by default: checkpoint at 60% context,
reduce new context at 75%, use native compaction at 85% when available, then resume.
These thresholds are advisory; Markdown cannot invoke the client's native compact
control. Use a fresh session for an unrelated task, a required model change or failed
context recovery, with a handoff when continuing work.

Run deterministic tests and an install preview, install globally, integrate the
project, restart or report the required restart, and verify actual discovery and
idempotence. Then walk me through `ai-session configure` interactively so I authorize
which native and API services may run inference; never complete it with --yes on
my behalf, and report `environment_setup_required` as the next step if I defer it. Report instruction loading, skill discovery, model access and protected
execution separately. Copilot/Cursor instruction compatibility does not establish
working review, quota or manager adapters; Gemini CLI is not an Antigravity adapter.
Show ai-session version, update --check, interactive update and an exact-version
rollback. Prefer a shared installed release plus a short project AGENTS.md reference;
keep explicitly vendored customizations on their own reviewed version. After every
push, check README/docs/skills and configured consumers against their selected release.
Do not silently move maintained profiles to development main. Store consumer paths
and setup privately; do not publish consumer repositories without authorization.
Keep the existing explicit quota-mode choice; otherwise use strict mode unless I
opt into observed-threshold stopping with possible in-flight overshoot. Do not change billing, authentication,
repository visibility or publish anything. Report changes, checks, rollback paths
and any remaining decisions or unavailable capabilities.
```

## Session efficiency and shared usage

Ask whether the same subscriptions are used on several computers. Configure one
trusted SSH quota authority through `ai-session setup --authority user@host`, or
choose `local` for one machine. Never infer successful cross-machine enforcement
from two installed copies. Verify connectivity and the same account setup privately.
Offer the deterministic Claude hooks with `ai-session hooks --install`, then apply
the reviewed merge when authorized. Keep all hostnames, account evidence and quota
state out of public files. Direct clients without these controls are unprotected.

Resolve a current economical tier for execution at medium effort and low for simple
investigation. Plan with the strongest manager; do not duplicate its entire context
or maximum effort into workers. Keep review packets short and ordinary reviews at
medium. Check actual selected models and efforts in private session metadata.
