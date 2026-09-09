# Balance useful work across subscriptions

Available in version 0.3.0. Check the installed CLI before using these commands.
Installation does not enable balancing or billing.

The updated runtime also accepts these commands through the older published
launcher. A maintainer can retain the published profile and installer while
registering reviewed skill-only overlays; preserve private addenda and verify the
resulting registration. This compatibility does not activate an installed profile.

The manager remains the strongest supported model of the hosting provider. With
balancing enabled, it delegates bounded work across configured native subscriptions.
Choose tasks before reaching a quota stop. Keep manager work to planning, decisions,
integration and verification; provider reviews remain separate independent judgments.
Enabling the profile alone does not move the interactive manager's work or tokens.
Submit the bounded task through `work` and verify its receipt before claiming delegation.

```sh
ai-session balance status
ai-session balance enable
ai-session work --id unique-task-id < task.txt
ai-session audit --since 2026-01-01
```

Enable only after the owner requests balancing. Run configuration on the account
authority; clients on other computers use that same authority for every reservation.
Existing setup, budgets, calendar, reserves, grants and API money authorization are
preserved. `enable --services codex,claude` selects a supported subset explicitly.
`--max-lead 0.15` sets a maximum lead of 15% of a day's local budget at dispatch.
It is neither a token cap nor 15 percentage points of a provider's entire quota.

## Selection and evidence

Every decision refreshes every participant's native admission evidence. The target
is equal **fractional consumption of each subscription's daily allowance**. Providers
have different capacities, prices and reset schedules, so equal fractions need not
mean equal tokens, dollars, requests or useful output. No work is invented to burn
quota. Comparisons are approximate and expose partial history and reset timestamps.

For each service, divide observed cumulative daily consumption by the current daily
ceiling for each common non-session pacing pool, and use the highest ratio.
Verified model-specific pools constrain model selection instead of ranking an entire
subscription; see [model allowances](model-allowances.md). Overlapping
pools are never added together. Short renewable windows still constrain admission
but do not rank providers against weekly budgets. Missing or invalid pacing evidence
blocks enablement and work. Status shows binding pools, drift and unresolved jobs.

Concurrent protected sessions can record a newer observation during evaluation.
If settings are unchanged and only observation identity changed, the router performs
one read-only re-evaluation against current ledger evidence. This makes no model or
backend call and records no timestamp. A second race, stale/incomplete data, failed
refresh, quota denial or policy change still stops dispatch. The final snapshot
comparison remains mandatory; this mitigates the sequential-refresh race rather
than promising an atomic multi-provider backend snapshot.

Since v0.3.1, automatic native requests (`auto`, including an omitted provider)
rank only Codex, Claude and Antigravity, whose adapters resolve a current worker
model. Copilot and Cursor Auto require an explicit provider request. All configured
services still participate in quota/evidence admission; an excluded Auto route with
a genuine stop still pauses the batch. No service or accounting history is removed.

Status reports `automatic_selection`; reservation `decision` and `start_admission`
record the mode, eligible services, explicit-only services and minimum progress.
Automatic lead checks use that eligible domain at both reserve and start. Explicit
provider requests retain the all-participant lead check. All-participant drift stays
informational and may exceed the tolerance while automatic work remains admitted.
No eligible automatic service returns `current_model_selection_required`; busy
eligible services return `busy`. Legacy reserved automatic Auto jobs become denied
at start, freeing their slot atomically while retaining history. Running jobs and
repeated IDs never redispatch. Missing saved provider intent means automatic.

The next useful chunk comes from eligible services within the configured lead of the least
consumed fraction. Within that band, choose the fewest recorded dispatches today,
then the service name. This rotates ties when native counters remain rounded to
zero. Atomic reservations allow one open work item per billing service. A reservation
is a concurrency slot, never an invented quota debit. Manager, native workers and
reviews affect future choices through aggregate account counters even when they
are absent from the work journal.

`work` selects a current model at supported worker effort and runs one text-only
leaf through the existing restricted native adapter. Supply the complete task and
relevant source excerpts, at most 8 KiB. It can draft text, propose a patch or analyze
test cases; the manager inspects and applies its result. The worker cannot execute
tests or claim file changes. The maximum deadline is 180 seconds. Explicit
`--provider SERVICE` requests still obey the lead limit. Interactive worker launches
also reserve a slot and check the lead before starting; their existing session quota
supervision applies, and their task length must remain bounded by the manager.

Completion stores requested and observed model separately. Quota observations before
and after work remain aggregate account evidence, not per-task charges. Concurrent
clients may have consumed part of any delta. A repeated task ID never invokes a
model again; changed input under that ID is rejected. Only a private keyed fingerprint
and bounded metadata enter the journal; prompts and responses are not stored there.
The key is private ledger state, not a signature against someone who controls that
ledger. Local audit reads only allowlisted token/cost metadata into its report.

## Configure which models need supervision

The owner can restrict independent roles for selected models, without changing the
public defaults or excluding them from useful supervised work. Save a JSON list:

```json
[{"service":"antigravity","model":"*","roles":["manager","reviewer","verifier"]}]
```

Apply it on the account authority with
`ai-session balance constraints --file model-constraints.json`. `balance status`
shows the setting to every coordinated client. This example is optional, not a
built-in provider ranking. Choose `codex`, `claude`, `antigravity`, `copilot` or `cursor`, a model pattern,
and any of `manager`, `reviewer`, `verifier`, `worker`, `investigator`. Patterns are
case-sensitive: only `*` and `?` are wildcards; brackets are literal. Use runtime
catalog identities rather than assuming an alias's resolved model.

Matching independent launches/reviews stop before inference. `work` remains supervised
and marks output as requiring manager inspection, never independent approval. Review
responses are checked again against their observed model before returning content;
unknown identities cannot bypass an applicable restriction. Consumed quota is retained.
If constraints exclude a required reviewer, report the gap and follow the owner's
review choices; never promote supervised output to fill the count.

The command replaces only these settings. They survive balance disable/re-enable;
applying `[]` explicitly clears them. Corrupt settings and unknown roles fail closed.
An absent setting means no restrictions, including in legacy or reset state. This is
configuration for trusted controllers, not a security boundary against the ledger
owner. The remote protocol cannot edit it, and text workers have no tools. Direct
IDE calls and API routes without protected role adapters remain outside this control.
Interactive launches check the selected model at startup. Supported protected Claude
sessions also check model changes through native hooks; other client adapters retain
their documented startup-only role boundary.

## Other AI clients and billing routes

Match work against verified adapter capabilities:

| Provider or tool | Execution status | Quota and billing scope |
| --- | --- | --- |
| Codex, Claude Code, Antigravity CLI | Protected native execution | Fresh native quota readers; balance fractions of local daily budgets |
| Copilot, Cursor | Native launch and supervised text | Finite Copilot chat pool or personal Cursor Free Auto; fresh no-overage evidence required |
| Gemini CLI, Kimi CLI, OpenCode, Aider, Continue | Discovery | No protected native execution adapter |
| Ollama local | Bounded text with local residency checks | Separate local job ledger, outside subscription balancing |
| Paid OpenAI, Anthropic, Gemini, xAI, DeepSeek, Kimi, Z.ai, OpenRouter APIs | Explicit text requests | Separate monthly money admission; never subscription fallback |

Resolve the **billing service** independently from the **model family**. For example,
a third-party model through Antigravity would use Antigravity's resources, not that
vendor's direct subscription. The current Google review adapter selects Gemini;
third-party catalog access alone does not add a balancing execution route. Local
Ollama models are not a subscription budget. Unsupported configured services and
excluded API services appear explicitly in balance status.

The [reviewed coding profile](coding-models.md) adds explicit OpenRouter
text work across five model families. It remains in the separate API money ledger;
`api coding-run` does not consume or balance native subscription allowances.
The separate [recurring free account pools](free-access.md) can participate in
`work` only with explicit `mixed_work` configuration and verified no-overage
entitlement. They use a dedicated shared executor and free quota ledger.

For a multi-model platform, distinguish the billing service, its account pool, the
requested and observed model IDs, and the model's vendor. Claude through Copilot
draws on Copilot resources, not the direct Claude subscription. Two Claude models
on different platforms are not two independent provider families. A model's role
constraints and the platform's available allowance answer different questions.

Current selection resolves the supported native worker from the account catalog
after choosing its billing service by quota fraction. It does not rank every model
in Copilot or Cursor for implementation/review. Their explicitly selected Auto routes produce supervised
text; automatic native routing excludes them. Copilot reports the routed model; Cursor currently exposes only Auto. OpenRouter requests require
an explicit model and monetary admission; they do not participate in native balancing.
The native model/role configuration above does not claim enforcement in those
unsupported role adapters. Adding a platform requires verified quota/billing units,
model selection, role checks, execution isolation and observed-model receipts.

Keep platform pricing dynamic: [Copilot's SDK](https://docs.github.com/en/copilot/how-tos/copilot-sdk/features/usage-and-billing)
exposes model billing metadata and distinguishes AI-credit and premium-request
counters. [Cursor](https://cursor.com/docs/models-and-pricing) documents distinct
model usage pools. [OpenRouter](https://openrouter.ai/docs/guides/routing/provider-selection)
can route a requested model among hosting providers; routing does not create another
subscription or independent model family. Catalog visibility alone never authorizes
execution, automatic model fallback or additional charges.

## Interpreting the audit output

`audit` reports quota history and local token history separately. Quota history
counts cumulative positive percentage-point changes per pool. Do not add overlapping
pools together. A reset never refunds consumption recorded for that day. Incomplete
observation windows provide lower bounds, not totals.

Token history comes from local files. Codex `token_usage_record` rows are deduplicated
by `response_id`; Claude assistant metadata is deduplicated by message ID, keeping
maximum streaming counters. Codex cached input is a subset of `input_tokens`, while
Claude exposes cache classes separately. Cross-tool totals are not directly comparable.

Reports scan files modified since a UTC date cutoff and include timestamped token
rows from that date onward. Claude cost-state `totalCostUSD` values are cumulative
token-price estimates over the examined sessions, not date-filtered charges or
proof of an API invoice.

- Zero recorded monetary requests describes the local harness journal; it cannot
  establish an external API invoice of zero.
- A transcript may be mirrored. Its location does not identify the compute host;
  do not sum host reports on that basis.
- Antigravity has native quota history, but no verified local token-history adapter.
  Older unsupported Codex formats are also outside token-audit coverage.
- Account metadata may verify a plan category without verifying its multiplier.
  Actual quotas govern admission.

## Stops and recovery

Interactive workers report `balance_blocked` with a phase and reason codes when
pacing prevents launch. `max_lead_exceeded` means that service is ahead of the
configured fraction of daily budgets; it is not a CLI schema failure or proof that
the subscription is exhausted. Inspect `ai-session balance status`. Keep useful work
within the admitted band; changing the lead requires an explicit configuration choice.

After execution, `balance_receipt_unavailable` means the completion receipt is
unconfirmed, even when the provider process returned success. The command exits 2
and reports the task ID. Work may have completed; inspect its result, journal and
process state before recovery. Transport failures at reserve/start can also leave
an unresolved task. Neither case automatically retries, reconciles or frees a slot.

Missing evidence, unsupported controls or a participant's quota denial pauses the
coordinated batch. Status distinguishes evidence failures from quota denials. There
is no silent participant removal, billing-service retry, API fallback, quota grant or
credit purchase. A Mac client being offline does not stop a reachable authority;
that Mac cannot reserve locally while disconnected. Older authorities that do not
understand the balance protocol fail closed and need a reviewed update.

Interrupted jobs retain their slot. Inspect the exact job and confirm its process
and background work stopped before using the command printed by status:

```sh
ai-session balance reconcile EXACT_TASK_ID --confirm-stopped
```

Completed, failed, denied and abandoned attempts remain in history. Budget changes
and resets change future decisions without refunding daily usage. At the owner's
explicit instruction, `ai-session balance disable` restores the original selection
policy while preserving quota, monetary and job accounting. It does not override a
quota stop and must never be an autonomous workaround for one.

Observed mode still permits delayed telemetry and in-flight overshoot. Direct or
unwrapped native calls cannot be intercepted by this router. It controls submitted
work, not every token emitted by an already running IDE or manager. Strict mode
continues to refuse execution without enforceable request-cost bounds. Meaningful
live acceptance must identify the actual runtime, model, authority and outputs;
deterministic rotation tests alone do not prove account usage was balanced.
