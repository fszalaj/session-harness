---
name: session-harness
description: Coordinate substantive work across Codex, Claude and Antigravity, with installed-client/model discovery and adaptive quota/context safeguards. Detect the active session, resolve current models, have the strongest session model plan and manage, obtain two independent provider reviews, and delegate implementation at appropriate effort. Skip orchestration for trivial edits and leaf assignments.
---

# Session harness

Use the active client's native agent controls, with the local CLI helper for
provider discovery and isolated reviews. This is a manager/worker workflow with
independent review, not a replacement for the clients' permission controls.

## 0. Check resources before dispatch

Read [usage and context](references/usage-and-context.md) before any model call,
including manager continuation, native workers, external review and retries. The
same account budgets apply across projects. Read the persisted budget strategy and
reserve for every pool. New ledgers default to fixed 20 points/day and 0% reserve,
UTC, all seven workdays and an 08:30 reset cutoff. Preserve existing configuration.
An explicit adaptive policy distributes the balance across scheduled workdays
until the actual reset; a fresh reset due by tomorrow's local cutoff releases
current headroom on a scheduled workday without predicting a refill. Honor existing settings and dated grants. See [budget controls](references/budgets.md)
for daily additions and use-rest. Record fresh observations; unknown usage is not
zero and a reset forecast alone never creates headroom.

Use `harness.py usage refresh <service>` and `harness.py usage check <service>`.
Refresh persisted policy before a stop and report its actual reserve; loaded
instructions may describe stale settings. There is no mandatory 10% floor.
Global reserve defaults do not replace existing service/pool overrides.
A strict cap requires a provable execution boundary and request-cost bound. If the
client cannot supply these, strict mode refuses inference. Observed-threshold
monitoring is a separately named weaker mode, enabled through private persisted
configuration after an explicit owner choice. Honor an existing choice without
asking again. It uses observed daily lower bounds where earlier history is partial.
Never silently substitute modes. A stop saves a checkpoint and does not switch
billing services, start replacement workers or consume reset credits to bypass it.
The launcher and external review runner poll while their owned processes run;
direct native sessions remain outside that process boundary.

## 1. Establish the manager

- If assigned a leaf task, or `SESSION_HARNESS_LEAF=1`, perform only that task.
  Do not discover providers, invoke this skill recursively or spawn reviewers.
- If a repository explicitly links this skill, select that repository copy; otherwise
  select the installed personal snapshot. Keep one runtime path/hash per plan and
  report drift. Same-named project/profile entries may coexist in the selector.
- Read applicable `AGENTS.md` and relevant durable context. Preserve the user's
  objective, existing authorization, dirty changes and release boundaries.
- Run `python3 <skill-dir>/scripts/harness.py discover --session <client>`.
  Set `<client>` from the actual session identity: `codex`, `claude`, or
  `antigravity`. Run `harness.py inventory` for Copilot, Cursor, Gemini CLI, Kimi,
  OpenCode, Aider, Continue and Ollama discovery. Installed clients, advertised
  catalogs, account-selectable models and verified entitlement are different states.
  Grok/xAI, DeepSeek, Kimi/Moonshot and GLM/Z.ai can appear through multi-model
  clients; never infer an installed application or paid route from a model name.
  Additional clients require verified quota, selection and execution adapters.
  Use auto-detection only when identity is unknown; installed
  binaries do not identify the current session. Conflicting evidence stays unknown.
- Prefer the current session's advertised model/effort capabilities over another
  client's catalog. See [client adapters](references/clients.md) for CLI details.
  Never read credentials or transcripts to guess identity or entitlements.
- The manager/planner uses the strongest available **active-provider** model and
  its highest advertised reasoning effort. Use a supported model switch or launch
  a fresh manager through `harness.py launch <client> --execute` when necessary.
  A running model cannot promote itself by writing instructions. If switching is
  unavailable, report the mismatch, prepare a handoff, and keep planning explicitly
  provisional; never claim the stronger model managed work that it did not.

During installation or repair of this harness itself, reversible local scaffolding
needed to make the reviewers callable may precede their review. Mark that work as
bootstrap, validate it independently, then obtain the real pair before claiming
the harness verified. This exception does not waive review for application changes,
release, unrelated work or a routine provider outage.

## 2. Resolve roles before dispatch

Resolve exact models at each new session and after quota/model availability changes.
Use account-visible catalogs and documented rolling aliases, with source and time.
Catalog order and a `Pro`/`Flash` name alone do not prove capability. Read current
provider guidance when capability or successor relationships remain uncertain.

- Exclude hidden, retired and superseded generations before optimizing cost.
  Compare versions numerically within a provider family, never lexicographically
  or across vendors. An alias alone does not prove current-generation eligibility:
  check its resolved model against available successors before assigning a worker.
- Prefer a cheaper **current-generation** model for bounded work. If none exists,
  use the current flagship at medium effort instead of an older cheap model.
- Only use effort levels advertised by that model/client. Normal workers use
  medium; simple evidence collection may use low; complex implementation and
  final review use high. Reserve maximum effort for manager/planner and difficult
  plan decisions. Do not force global max effort onto workers through environment.
- No fixed provider-to-specialty stereotype. Choose from demonstrated capability,
  task risk, required tools, context size, latency and remaining subscription quota.
  Use native workers from the manager's model family by default: OpenAI workers
  for an OpenAI manager, Anthropic workers for an Anthropic manager, and Google
  workers for a Google manager. In multi-model clients, select the family explicitly.
  Another provider may implement in an isolated
  worktree when its supported client offers a material benefit.

| Role | Model and effort | Ownership |
| --- | --- | --- |
| Manager/planner | Strongest current session model, highest supported effort | Plan, reconciliation, integration, final verification |
| Two plan reviewers | Strong current models from the other two providers, high or highest supported effort for difficult plans | Independent findings on the same plan |
| Investigator | Current suitable model, low/medium | Bounded evidence gathering, no edits |
| Implementer | Current suitable model, medium; high for hard changes | One non-overlapping file/task scope |
| Verifier | Current suitable model, high | Independent diff/test review, no self-approval |

Both external reviewers have equal standing. The manager resolves the union of
findings using evidence; majority voting does not erase a concrete defect.

## 3. Plan and cross-check

1. Save a concise plan: outcome, constraints, evidence, proposed changes, task
   dependencies/file ownership, acceptance checks and rollback where relevant.
   Record model/provider/effort selections with reasons. Keep it in the client's
   plan artifact or private run directory, not a new committed progress log.
2. Hash the exact review packet. Include sufficient relevant code/contracts inline,
   sanitize secrets and personal data, and omit irrelevant conversation history.
3. Give the same packet separately to the other two provider families. For Codex
   manager use Claude + Gemini; for Claude use Codex + Gemini; for Antigravity/Gemini
   use Codex + Claude. A Claude model accessed through Antigravity is still Claude.
   Reviewers do not see each other's verdict before their first response.
4. Request `approve`, `revise` or `blocked`, with concrete findings, severity,
   evidence, missing assumptions and required checks. A completed process is not
   approval. Do not ask for private reasoning traces.
5. Reconcile all material findings. A changed decision, interface, data invariant or
   acceptance scope invalidates the old plan digest. Obtain both verdicts on the
   revised packet before implementation. Limit to two review rounds; unresolved
   disagreement becomes an explicit decision with evidence, not endless retries.

Only the manager starts reviews. Prefer `harness.py review <provider>` with the
packet on stdin when that adapter reports verified isolation. Otherwise use a
supported native/provider bridge with equivalent scope and execution restrictions. See
[review protocol](references/review-protocol.md). Never replace a missing provider
with a same-provider agent and call that independent cross-provider review.

On unavailable auth, quota, tooling or an unverified model, record the precise
missing review and continue independent preparation. Do not start implementation
behind a mandatory missing verdict. Request only the missing setup/decision when
independent work is exhausted; this skill does not require routine plan approval.

## 4. Implement and verify

- Dispatch only useful parallel tasks. Respect the actual concurrency limit and
  keep one slot for the manager. Each worker gets a leaf marker, task/plan version,
  owned files/worktree, relevant rules, selected model/effort, acceptance criteria
  and a concise return format: changes, checks, residual risks, paths/commit.
- Check context capacity before dispatch. At 60% prepare a checkpoint; at 75%
  reduce irrelevant context and avoid large new tasks; at 85% prefer native
  compaction for the same task. These thresholds are advisory context safeguards.
  Markdown cannot trigger compaction or change models. Use a new session for an
  unrelated task, required model change or unrecoverable context, without claiming
  universal quota savings. Give workers bounded packets.
- Pass sufficient context directly; fresh workers do not inherit hidden assumptions.
  Avoid full-history forks when an explicit model/effort override needs a fresh
  context. Do not set a CLI-wide subagent-model or effort override that defeats
  per-task selection. Workers never expand scope or start another harness.
- Assign one writer per file, serialize overlapping changes and use isolated
  worktrees for separate clients. Integrate inspected changes only. Escalate a
  worker's effort after a concrete failed attempt; do not default everyone to max.
  When a native role fixes effort, choose another role or a fresh configurable leaf
  instead of assuming a spawn parameter overrides it. Verify effective controls.
- The manager independently reviews the integrated diff and runs applicable gates.
  Use a fresh verifier for substantial changes. Material plan drift returns to
  plan review. Follow any repository requirement for final cross-provider review.
- Checkpoint durable decisions and resumable state through the project's knowledge
  workflow. Record completed/pending tasks, exact plan digest, reviews, selected
  versus observed models, checks and remaining blockers before compaction/handoff.
- Reinstall the shared profile after changing its maintained sources. Profile
  links target a verified immutable local snapshot, so branch changes cannot break
  other clients. Compare the runtime path/hash when project and profile skills coexist.
- Report delivered behavior and evidence, plus any missing provider or unsupported
  control. Do not label unrun tests, provisional plans or timed-out reviews complete.

For the design rationale and current official references, read
[sources](references/sources.md) only when maintaining this skill or an adapter.
