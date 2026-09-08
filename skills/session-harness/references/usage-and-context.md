# Usage and context policy

Every manager, worker, reviewer and retry shares the account's budget. Track the
service that bills the request independently from the vendor producing the model.
Use all applicable quota windows, including model-specific and monthly pools.

## Admission

Setup authorization precedes every admission decision. `require_admission` returns
`environment_setup_required` until `ai-session setup` records the owner's selected
services, and `service_not_configured` for a service outside that record. Refresh,
status, inventory and budget commands do not need it. Invalid or partial records
fail closed; `setup --reset` clears only the authorization.

Read the persisted per-service/pool policy. New ledgers default to adaptive allocation, reserve 0, UTC, all seven workdays and an 08:30 cutoff.
Existing policies are preserved. Adaptive policies distribute long-window
balance across scheduled workdays until the actual reset; reserve 0 targets full use.
Fresh evidence of a reset due by tomorrow's local cutoff releases current headroom
on a scheduled workday, without predicting renewal. There is no mandatory 10% floor.
Before stopping, refresh persisted policy and report the actual configured reserve;
instructions loaded earlier may be stale. Global defaults do not replace explicit
service/pool settings. [Budget controls](budgets.md) explain allocation, window strategy,
daily grants and the use-rest override. Preserve the calendar timezone and all
daily consumption. Never switch account/service, use credits or retry to bypass a stop.

An exact cap needs control of every inference and a provable upper bound on each
request's quota cost. None of the current adapters exposes that contract. Strict
mode therefore refuses model execution even when counters show headroom. This is
an explicit capability limitation, not an account quota-exhaustion claim.

Observed-threshold admission is weaker: a delayed counter, rounding, another
computer or a response in flight can cross the limit before cancellation. The
private ledger persists the explicitly selected mode. Enable observed mode only when
the user accepts those limits; honor that choice in later sessions without asking again.
The public default stays strict. Configuration changes never erase daily counts.

For explicit API routes, use [money admission](api-and-spend.md) with a separate
monthly total cap and per-request liability. Native paid-credit controls must also
be verified; missing or enabled eligibility blocks protected native inference.
**Since v0.2.0:** Codex requires an account-bound owner confirmation
that automatic top-up is disabled,
plus fresh zero-credit evidence; see [API and spend](api-and-spend.md). Antigravity
uses its documented local `useG1Credits` control, including the disabled default
for an absent file/key; unreadable, malformed or enabled settings block.
Version 0.1.2 instead blocked protected Codex execution and required an explicit
Antigravity `false` setting. A money cap does not authorize native credits.

## Observations and daily history

- Refresh Codex through `account/rateLimits/read` and Copilot through
  `account.getQuota`; neither requires inference. Never convert tokens to quota.
- Claude refresh uses its native metadata control protocol, including global and
  scoped pools, and requires evidence of a successful backend read. Antigravity
  refresh forces a native backend request through an owned idle CLI
  and keeps every quota bucket.
  Neither reader submits a model prompt. Both reject malformed or incomplete
  responses; Claude also rejects unexpected inference events.
- Statusline capture remains monitoring input. Its receipt time does not prove a
  backend refresh; repeating a redraw must not manufacture fresh headroom.
- Persist only service/pool identifiers, observation times, percentages, reset
  instants, daily deltas and sanitized native credit resources. No credentials,
  emails, prompt text or transcripts. Money records additionally retain digests,
  reservations, charges and evidence references.
- Preserve a quota pool even when its backend omits the reset schedule. Store
  `resets_at: null` as unknown, retain percentage/daily accounting and require fresh
  observations. A verified native long-window duration permits conservative full-window
  pacing without inventing a reset or activating the cutoff release; see [budgets](budgets.md).
  A later schedule never recredits the daily anchor. Observed balance recovery
  may re-anchor an adaptive allocation; it never refunds daily consumption or replays grants.
- Initialize a first prospective baseline explicitly. Earlier daily use remains
  marked unknown. Do not erase a ledger or change its timezone to gain allowance.
- Count positive deltas once in a locked transaction. Decreases do not refund
  daily use. Record reset changes and early renewal observations. Missing intervals
  around a reset may hide usage, so retain uncertainty rather than inventing a zero.
- Gaps and reset ambiguity mark historical coverage partial. In observed mode,
  fresh complete reports can resume admission using the retained daily lower bound;
  this never claims complete past use. A usage drop adds the new window's observed
  consumption. A drifting reset estimate alone is not a confirmed renewal.
  Strict mode retains the uncertainty block.
- A local ledger is shared by projects, not computers. Complete cross-device
  coordination requires an account-wide admission service or a server-side cap.

Run these commands with the installed or selected project skill directory as your
working directory (the directory containing `SKILL.md`):

```sh
# Explicit local opt-in after accepting observed-mode limitations:
python3 scripts/quota.py configure --mode observed
python3 scripts/harness.py usage refresh codex --initialize
python3 scripts/harness.py usage refresh copilot --initialize
python3 scripts/harness.py usage refresh claude --initialize
python3 scripts/harness.py usage refresh antigravity --initialize
python3 scripts/harness.py usage status codex
python3 scripts/harness.py usage check codex
python3 scripts/usage.py capture claude < native-statusline-payload.json
python3 scripts/usage.py capture antigravity < native-statusline-payload.json
python3 scripts/usage.py context < native-statusline-payload.json
```

For an existing trusted statusline renderer, `capture <service> --renderer '<existing
command>'` forwards its original input/output after allowlisted recording. Do not
commit or retain the raw native payload. Installation does not replace statuslines
or hooks automatically; prepare a reversible merge for the actual client config.

Claude's `usage.py hook claude` follows persisted admission, emitting a synchronous
UserPromptSubmit block when denied. Native
hook timeout can fail open and the hook does not gate all autonomous inference.
Antigravity PostInvocation can terminate after consumption, while documented
PreInvocation has no deny result. Copilot's credit cap is explicitly soft. None is
an exact subscription quota cap. Existing parent/IDE sessions are not owned child
processes and must not be killed by name to implement a stop.

## Process supervision

POSIX manager launches use an owned pseudo-terminal process group; Windows uses
a gated kill-on-close job and bounded pipes (see [platforms](platforms.md)). Native external review calls
use their isolated subprocess group or Windows job. Explicit API requests use
[monetary reservation and transport deadlines](api-and-spend.md), not this polling loop. Both check before inference, poll every 15
seconds and check after completion. A denied or unavailable observation terminates
the owned group and restores the terminal; it does not kill unrelated processes.
Each poll performs native metadata work and may contact the provider. Rate limiting
(HTTP 429), persistent server errors or changed protocol diagnostics stop the owned
run; cached results are not substituted. Refresh latency adds to the polling delay.
Polling is synchronous: output draining can pause during its bounded metadata
request, causing temporary pipe backpressure. The reader does not depend on the
inference child, and draining resumes after the request returns or fails. Poll time
counts toward the outer execution deadline. Use an execution timeout well above
the 15-second metadata bound; external reviews default to 180 seconds. A short
execution timeout can expire during a quota check.
Parent/IDE sessions started elsewhere,
other computers and deliberately detached child sessions are outside this boundary.
The wrapper cannot reliably cancel charges already incurred or responses in flight.

Built-in native readers use the start of the bounded metadata request as the
observation time; they do not claim a vendor-signed freshness timestamp. Claude
requires matching control replies and native successful-GET diagnostics because
its quota protocol can silently fall back to cache. Antigravity uses the native
`forceRefresh` request and validates the complete grouped bucket schema. Changes
to those native contracts block admission until the adapter is verified again.
Raw account payloads and debug logs are discarded; only allowlisted quota metadata
reaches the ledger. Native clients may maintain their ordinary local caches and
authentication state. The Antigravity reader discovers IPv4-reachable listeners
owned by its CLI leader, including listeners appearing later during startup;
child-only or IPv6-loopback-only listeners remain unsupported and block admission.

The local machine, executable PATH and installed vendor clients are trusted.
Antigravity uses self-signed TLS on an owned loopback listener without sending
credentials. Ownership checks before connection do not authenticate the peer or
eliminate a local port-rebinding race. A malicious local process could spoof
observed-mode metadata; strict admission still refuses unbounded execution. This
is not a security boundary against a compromised host.

`quota.py status --observed-only` is diagnostic. That flag is rejected by `check`;
a successful metadata/status command must never be used as execution permission.
Use `harness.py usage check` or the supervised launcher for admission.

The optional `quota_observation` statusline envelope remains a separate trusted-
adapter contract, not vendor fields or authenticated provenance. Do not fabricate
it or run inference to obtain the first quota report. Enabled extra-usage credit
pools require complete supported telemetry; the adapter may block those accounts
without changing their settings.

## When a protected session stops

**Development behavior, beyond published v0.2.0:** an interactive launch prints the
reason and recovery steps after restoring its output terminal, including leaving a
child's alternate screen. Machine-readable failure JSON remains on stdout;
redirected streams receive no diagnostic terminal escape sequences.

`daily_limit` means today's configured harness allowance was reached. It does not
establish that the provider subscription is exhausted. Capacity, maintenance,
reserve and unavailable quota evidence have separate explanations. Inspect
`ai-session coordination status`; inspect or change budgets on the account authority
using `ai-session budget SERVICE`. A new grant requires the owner's instruction.
After admission is restored, reopen `ai-session SERVICE` and use the client's native
resume option. Transcript persistence depends on that client. No automatic restart,
provider switch, grant or paid fallback occurs.

The harness stops its owned client process group when work is denied. It restores
terminal attributes, descriptor flags and signal handlers independently, so failure
of one restoration does not skip the others. A cleanup failure keeps the original
quota reason and adds only fixed stage names and numeric errno metadata. When process
termination is unconfirmed, the protected owner is retained and reported for inspection;
do not blindly release it or start replacement work. Terminal restoration errors after
confirmed process termination are reported separately and do not imply a live process.
Deliberately detached descendants outside the owned process group remain outside this
boundary. Operating-system permission failures are not treated as permission to ignore
live processes; see Apple's [process-group signal contract](https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man2/killpg.2.html).

## Context

Read actual context-window size/percentage from native session metadata. At 60%,
write a concise resumable checkpoint. At 75%, avoid a large new task, reduce irrelevant
context and give workers fresh bounded packets. At 85%, prefer native compaction
to continue the same task when supported. These are advisory context thresholds,
not usage-budget calculations. Markdown cannot invoke compaction or switch models.
Start a new session for an unrelated task, a required model change or context that
cannot be recovered. Compaction and restarting do not guarantee quota savings;
actual cost depends on the client, caching and the context subsequently supplied.

A checkpoint contains the objective, plan digest, decisions, owned files/worktrees,
completed/pending checks, current quota observations, stop reason and next action.
It must survive compaction without requiring the next session to reread transcripts.
Do not duplicate full history into every worker or repeatedly fetch whole catalogs.


Use supported native controls and verify their result. Claude documents manual
compaction and focused context management in its [best practices](https://code.claude.com/docs/en/best-practices)
and [cost guidance](https://code.claude.com/docs/en/costs). Codex documents `/compact`
in its [CLI slash commands](https://developers.openai.com/codex/cli/slash-commands)
and thread compaction in its [app-server protocol](https://developers.openai.com/codex/app-server/).
These interfaces do not make a Markdown threshold an automatic client action.

## Multiple sessions and machines

`coordination.py` admits owners atomically up to the configured session capacity.
New configurations allow four owners per billing service; existing explicit values
are preserved. All owners and their native workers share the aggregate provider
counters and daily allowance. Native backend refreshes serialize per ledger/service,
including direct refresh commands, to retain observation order. Model work may overlap.
Owner records never expire just because time passes.
After a crash, confirm the process stopped before explicitly releasing its owner ID.

`ai-session setup --authority user@host` selects one already-trusted SSH authority.
It must have this harness and authentication for the same accounts. Its ledger,
calendar and quota checks govern all participating native sessions. Missing SSH,
unknown host keys, authentication failure and malformed responses fail closed.
Budget edits belong on the authority. Never put SQLite on an unreliable network
filesystem or copy ledgers between active machines. Remote monetary dispatch is
unsupported; run API requests at the monetary authority instead.

Capacity is editable through `ai-session configure` or
`ai-session coordination set --max-sessions NUMBER` on the authority. Increasing it
does not alter quota, grants or active owners. Different accounts use separate
authorities; repository membership is not an account identity. See
[coordination and recovery](coordination.md) before responding to `account_session_busy`.

`ai-session hooks --install --apply` merges deterministic Claude command hooks for
prompt submission and tool boundaries, plus owner release at completion. It preserves
existing hooks and records a private backup. Denial emits `continue: false`; it does
not return a Stop-hook block that asks the model to continue. Restart the client.
These controls reduce races and detect aggregate use; observed mode still cannot
promise an exact charge boundary for provider streaming or unprotected clients.
