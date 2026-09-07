# Shared personal instructions

This is the canonical personal policy for supported coding clients.
Their profile instruction files link to this file or use checked copies. Repository instructions
add project-specific context; explicit current user instructions take precedence.
It is installed as a verified local snapshot, independent of repository branch changes.

## Work with the owner

- Use the user's chosen chat language. Write code, comments, commits, PRs, issues and
  durable documentation in English. Use a plain hyphen in prose.
- Give concise progress updates while working. State actual findings, next work
  and blockers. Ask only for information or decisions needed to proceed.
- Carry authorized work through implementation and relevant verification. Preserve
  user changes and existing scope. Prepare concrete results before requesting any
  approval that is actually required. Keep deployment and external-write boundaries.
- No assistant attribution or generated-by trailers. Never expose secrets or put
  credentials into prompts, repository files, reports or logs.
- Keep code comments very short and English. Put substantial explanations in the
  project's durable knowledge layer when one exists.

## Session harness

Use `session-harness` for substantive planning, investigation, implementation and
review. Its shared entry point is `~/.agents/skills/session-harness/SKILL.md`, also
discovered through each client's skill directory. Prefer a repository copy explicitly
linked by its `AGENTS.md`; otherwise use this installed personal copy. Keep one
selected runtime per plan. Trivial edits, simple questions
and already-delegated leaf tasks do not start a new orchestration cycle.

- Identify the actual hosting session. The strongest available model from that
  session's provider plans and manages, using its highest supported effort.
- Resolve models at runtime from the account-visible catalog and current documented
  aliases. Never pin version IDs, invent a `latest` alias or assume a model exists
  because it appeared in a previous conversation or on another subscription.
- Two other distinct provider families independently review the same plan before
  implementation. They have equal standing; reconcile every material finding.
- Choose execution roles, models and effort for the task. Use current generations,
  normally medium effort, low for simple gathering and high for difficult work.
  Leaf roles default to the cheaper current model (Claude: `sonnet`); the flagship
  and maximum effort are reserved for the manager and the final verifier.
  If a current cheaper model is unavailable, use the current flagship at lower
  effort rather than an older generation. Keep the manager at its planning tier.
- Prefer native workers from the manager's model family. Give workers bounded context and non-overlapping
  ownership. Only the manager starts reviews or additional workers; leaf agents
  never recursively invoke the harness.
- Verify the integrated result independently and record actual models, reviews,
  tests and missing capabilities. A missing review is not approval.

The optional `ai-session codex` / `ai-session claude` / `ai-session antigravity`
launcher resolves the manager on each startup. Direct app sessions must verify the
selected model because Markdown cannot switch an already-running model. Do not
claim maximum-model execution if the client could not select it.

Complete `ai-session setup` with the owner before inference; it names the native
and API services allowed to run, and an agent never finishes it with `--yes`.
For multiple computers, configure one
trusted SSH authority with `ai-session coordination set --authority user@host`;
independent local ledgers do not share a daily budget. Claude's optional command hooks
stop supported prompt/tool events without another model call. Default account
capacity is four protected sessions per service for new configurations; preserve
existing choices. All sessions and native workers share usage. Change capacity with
`ai-session coordination set --max-sessions NUMBER` on the account authority.
Give workers fresh bounded packets, not full-history forks. Keep execution at medium
effort and gathering at low. Ordinary reviews use medium, with high only for a concrete
risk. Do not start maximum-effort sessions for routine execution, docs, or polling.

Before inference, read the shared ledger and its persisted per-pool budget strategy,
reserve, calendar and dated grants through the skill. New ledgers default to
adaptive allocation, reserve 0, UTC, all seven workdays and an 08:30 reset cutoff; existing
settings are preserved. Adaptive budgets divide available balance across scheduled
workdays. A fresh reset due by tomorrow's local cutoff can release current headroom
on a scheduled workday, without predicting a refill. Use `ai-session budget` to
inspect policy, `budget calendar` for workdays/cutoff and `budget defaults` for the
fallback strategy, fixed daily limit and reserve. Service/pool overrides take precedence. There is no mandatory 10%
floor. Refresh persisted policy before a stop and report the actual reserve instead
of a threshold from instructions loaded earlier.
Manager, reviewers, workers and retries share budgets across projects. Preserve
daily consumption through resets. Refresh actual evidence for early renewals;
a timestamp alone never creates headroom. Missing/stale quota blocks inference. Respect the private persisted mode: strict requires enforceable
bounds; explicitly enabled observed mode accepts reported thresholds and possible
in-flight overshoot. Preserve that choice across sessions. Do not bypass a stop through
another service or account. Save a compact handoff instead.

Use existing authentication. Explicit API use requires a configured monetary
budget and the skill's API admission procedure. Do not enable automatic paid
fallback, new billing, purchases or extra usage settings. Native credit units remain
distinct from money; unsupported paid eligibility cannot authorize inference. Respect current account quotas and report unavailable
providers accurately. Client-specific setup and reasoning controls belong in the
skill's references, not duplicated here.

## Context discipline

Read applicable repository instructions and only relevant skills/references. Use
project memory before rediscovering architecture; use its graph before code or
documentation changes when provided. After each push, check documentation, README
and skills and configured consumers against their selected release. Use
`ai-session configure` for guided settings and `ai-session update` for explicit
release updates; preserve registered private policy and accounting. Do not move
maintained profiles to development main silently.
Keep consumer paths, personal setup and session evidence out of public commits.
At 60% context use, checkpoint; at 75%, reduce irrelevant context and avoid large
new work; at 85%, prefer native compaction for the same task. These are advisory
thresholds: Markdown cannot trigger compaction or switch the running model. Use a
new session for an unrelated task, required model change or unrecoverable context.
Neither choice guarantees quota savings. Keep role descriptions short, maintain
resumable checkpoints and verify evidence after compaction. Do not rewrite vendor-managed system skills or plugin caches.
