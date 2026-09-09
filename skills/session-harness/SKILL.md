---
name: session-harness
description: Coordinate substantive work across coding clients and explicitly configured API providers. Discover current models, have the strongest session model manage, obtain two independent provider reviews, and delegate bounded work with quota, money and context safeguards. Skip orchestration for trivial edits and leaf assignments.
---

# Session harness

Use the active client's native agent controls, with the local CLI helper for
provider discovery and isolated reviews. This is a manager/worker workflow with
independent review, not a replacement for the clients' permission controls.

Use the selected [session startup procedure](references/session-start.md) once per
substantive task. It resolves current capabilities without loading every provider
procedure. Trivial questions, edits and assigned leaf tasks do not start a new cycle.

## 0. Check resources before dispatch

Before any inference, including native workers, reviewers and retries, inspect the
existing setup, shared authority and fresh per-pool admission. Use `ai-session usage
check SERVICE` through that authority; cached local status is diagnostic. Preserve
its budget strategy, reserve, calendar, dated grants, capacity and daily history.
A reset timestamp alone does not grant quota. Missing or stale evidence blocks.
Do not bypass a stop by switching accounts/services, enabling paid fallback or
restoring an old ledger. A model-specific stop permits only a verified current
alternative within the same subscription when all common limits still pass.

Existing authorization persists. If setup is absent, the user completes
`ai-session configure` or [provider onboarding](references/provider-onboarding.md)
interactively; never supply real authorization answers on their behalf. Adding a
key or detecting an installed client does not authorize inference. For accounts
shared across computers, keep one verified SSH authority and existing settings.
Independent local ledgers do not coordinate budgets or concurrent sessions.

Respect the persisted strict or observed mode. Strict requires enforceable bounds;
observed mode permits possible in-flight overshoot and must have been explicitly
selected. Do not substitute modes or invent a mandatory reserve. Read current
policy again before reporting a stop; instructions are not live quota evidence.

Load only the procedure needed for the selected operation:

- [Usage and context](references/usage-and-context.md): mandatory admission,
  observations, accounting, bounded process supervision, recovery and compaction.
- [Budget controls](references/budgets.md) and [coordination](references/coordination.md):
  policy changes, shared authority, capacity and exact-owner maintenance/recovery.
- [API and spend](references/api-and-spend.md): explicit API money authorization,
  cost reservations and native paid-credit eligibility. No automatic paid fallback.
- [Balancing](references/balancing.md): when enabled, route bounded work through
  `ai-session work` using fresh account evidence. When disabled, use native
  same-family workers. Preserve model-role restrictions in either case.
- [Free accounts](references/free-access.md), [coding models](references/coding-models.md)
  or [model allowances](references/model-allowances.md): only for those routes.
- [Client controls](references/clients.md) and [platform support](references/platforms.md):
  supported model/effort, isolation, authentication and operating-system limits.
- [Release maintenance](references/releases.md): inspect with `ai-session version`,
  update from an explicitly selected published release and preserve registered
  private policy, accounting and existing automatic-update opt-in. Never silently
  replace maintained profiles with development main or steal an update lock.

## 1. Establish the manager

Follow the [session startup procedure](references/session-start.md) to discover the
current configured capabilities, model-role policy and project knowledge access.
Use that single procedure in new sessions; do not carry a fixed provider panel
from a previous conversation. Read-only discovery does not authorize inference.

- If assigned a leaf task, or `SESSION_HARNESS_LEAF=1`, perform only that task.
  Do not discover providers, invoke this skill recursively or spawn reviewers.
- If a repository explicitly links this skill, select that repository copy; otherwise
  select the installed personal snapshot. Keep one runtime path/hash per plan and
  report drift. Same-named project/profile entries may coexist in the selector.
- Read applicable `AGENTS.md` and relevant durable context. Preserve the user's
  objective, existing authorization, dirty changes and release boundaries.
- With the selected skill directory as the working directory, run
  `python3 scripts/harness.py discover --session CLIENT`.
  Replace `CLIENT` with the actual session identity: `codex`, `claude`, or
  `antigravity`, `copilot` or `cursor`. Copilot and Cursor Auto cannot establish a strongest manager or
  independent provider family; use it for admitted supervised text work.
  Run `harness.py inventory` for Cursor, Gemini CLI, Kimi,
  OpenCode, Aider, Continue and Ollama discovery. Installed clients, advertised
  catalogs, account-selectable models and verified entitlement are different states.
  Grok/xAI, DeepSeek, Kimi/Moonshot and GLM/Z.ai can appear through multi-model
  clients; never infer an installed application or paid route from a model name.
  Use `harness.py api models SERVICE` for an explicitly selected API catalog.
  Direct API text routes cover OpenAI, Anthropic, Gemini, xAI, DeepSeek, Kimi,
  Z.ai and OpenRouter; Z.ai catalog discovery remains unsupported. Additional
  native clients require verified quota, selection and execution adapters.
  For another unsupported host, establish session identity from its native controls
  rather than supplying an unsupported `discover --session` value.
  Use auto-detection only when identity is unknown; installed
  binaries do not identify the current session. Conflicting evidence stays unknown.
- Prefer the current session's advertised model/effort capabilities over another
  client's catalog. See [client adapters](references/clients.md) for CLI details.
  Never read credentials or transcripts to guess identity or entitlements.
- The manager/planner uses the strongest available **active-provider** model and
  Extra High (`xhigh`), or the highest advertised level below `max` when unavailable. Use a supported model switch or launch
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
- Default to the newest available generation within each family. Opaque platform
  Auto is an explicit exception, never evidence of a current model. Automatic native
  `work` uses Codex, Claude or Antigravity; Copilot/Cursor requires an explicit provider.
- Prefer a cheaper **current-generation** model for bounded work. If none exists,
  use the current flagship at medium effort instead of an older cheap model.
- At each native leaf dispatch, pass both the current catalog-selected model and
  supported effort explicitly. Read the returned effective configuration when exposed.
  A role's name, an omitted parameter or a rolling alias alone does not prove those
  settings. If a role fixes effort, choose a compatible role; Markdown cannot override
  native controls. Record requested settings separately from verified observations.
- Only use effort levels advertised by that model/client. Normal workers use
  medium; simple evidence collection may use low; complex implementation and
  final review use high. Reserve `max` for explicit task-level escalation on
  extremely difficult tasks. Do not force global max effort onto workers through environment.
- No fixed provider-to-specialty stereotype. Choose from demonstrated capability,
  task risk, required tools, context size, latency and remaining subscription quota.
  When the owner enables subscription balancing, read [balancing](references/balancing.md)
  and select bounded work through `ai-session work` before every dispatch. Keep the
  manager focused on planning and integration; the billing service comes from fresh
  relative budget use, not the manager family. Explicit worker launches obey the same
  lead check. With balancing disabled, native same-family workers remain the default.
  In multi-model clients, verify billing service and model family separately.
  Verify an actual work receipt; an enabled profile does not move manager tokens.
  Claude's native alias resolution can establish current Sonnet workers. Check
  [client limits](references/clients.md#claude-code): scoped Fable allowance is not
  total subscription allowance. Use [model-aware admission](references/model-allowances.md)
  for current alternatives and supervised exact-session recovery.
  Installed Claude investigator/implementer roles use the rolling `sonnet` alias
  (investigator: low; implementer: medium) and the verifier inherits the manager
  model at high effort; pass a per-call model only for a verified better fit. Keep leaf work off the
  flagship unless task fit requires escalation; maximum effort requires an
  explicitly selected, extremely difficult task.
  Another provider may implement in an isolated
  worktree when its supported client offers a material benefit.

| Role | Model and effort | Ownership |
| --- | --- | --- |
| Manager/planner | Strongest current session model, `xhigh` by default; highest advertised level below `max` if unavailable | Plan, reconciliation, integration, final verification |
| Two plan reviewers | Current suitable models from two other distinct provider families, medium; high for demonstrated difficult risks | Independent findings on the same plan |
| Investigator | Current suitable model, low/medium | Bounded evidence gathering, no edits |
| Implementer | Current suitable model, medium; high for hard changes | One non-overlapping file/task scope |
| Verifier | Current suitable model, high | Independent diff/test review, no self-approval |

Both external reviewers have equal standing. The manager resolves the union of
findings using evidence; majority voting does not erase a concrete defect.

## 3. Plan and cross-check

Before another review, consult the private checkpoint's phase/artifact/family index.
Reuse a completed verdict only for the same scope and evidence; preserve missing,
blocked and supervised results as such. Classify each finding as a confirmed defect,
missing context, control/transport failure or optional improvement. Supply missing
contracts before increasing effort; raise it only for an unresolved reasoning problem.
Do not repeat full reviews merely to obtain an `approve` word. A material change or
unresolved material finding still requires the appropriate independent review.

1. Save a concise plan: outcome, constraints, evidence, proposed changes, task
   dependencies/file ownership, acceptance checks and rollback where relevant.
   Record model/provider/effort selections with reasons. Keep it in the client's
   plan artifact or private run directory, not a new committed progress log.
2. Hash the exact review packet. Include sufficient relevant code/contracts inline,
   sanitize secrets and personal data, and omit irrelevant conversation history.
3. Use the [session startup procedure](references/session-start.md) to select two
   eligible upstream model families different from each other and the manager.
   Resolve the model family separately from its client, gateway and billing service.
   Give both the same packet; reviewers do not see each other's first verdict.
   Honor current role restrictions, model selection, isolation and admission.
   Inventory-only, opaque Auto and supervised-only routes do not fill the panel.
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
  Aim for a 2-4 KiB task packet and a 300-word return; include additional code
  when it is needed to verify a contract instead of silently truncating it.
- Keep verbose catalogs, test logs and document JSON in private files. Return a
  compact summary and relevant excerpts; read more when evidence requires it.
  Poll an existing process only for changed state. Reuse unchanged catalog evidence
  while fresh; refresh on expiry, a changed account or a model/control failure.
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
- Before documentation changes, use the project code graph and inspect measured
  blind spots. After each push, verify docs/README/skill against code and synchronize
  configured local consumers against their selected published release. Keep
  consumer paths, private setup details and session evidence out of public commits.
- Prepare a profile refresh when maintained sources change; apply it only within
  the owner-authorized installation or update scope. Existing profiles retain their
  selected release. Profile links target a verified immutable local snapshot, so
  branch changes cannot break other clients. Compare the runtime path/hash when
  project and profile skills coexist.
- Report delivered behavior and evidence, plus any missing provider or unsupported
  control. Do not label unrun tests, provisional plans or timed-out reviews complete.

For the design rationale and current official references, read
[sources](references/sources.md) only when maintaining this skill or an adapter.
