# Adaptive budgets and daily grants

Use these commands from the installed `ai-session` launcher. Without installation,
replace `ai-session` with `python3 <skill-dir>/scripts/harness.py`. They inspect or
change private local policy without sending a model prompt or altering provider billing.

```sh
ai-session budget
ai-session budget codex
ai-session budget calendar --workdays weekdays --reset-cutoff 08:30
ai-session budget defaults --reserve 0
ai-session budget set codex --strategy adaptive --reserve 0
ai-session budget add codex 5
ai-session budget use-rest codex
ai-session budget codex --json
```

`set` persists a service policy; `--pool EXACT_ID` scopes it to one pool. `add`
increases today's local allowance by percentage points, and `use-rest` permits the
currently observed remaining balance until midnight in the ledger timezone. Neither
changes the provider balance. Use the printed `--id` on a retry to avoid applying
an add twice; a new invocation without that ID intentionally creates another grant.
Amounts and combined extra grants are limited to 100 points per pool/day. Native
headroom always clips what can actually be spent. New pools never inherit an
earlier grant. History survives configuration, resets, grants and reinstalls.

```sh
ai-session budget add claude 5 --pool EXACT_POOL_ID --id my-extra-work-today
ai-session budget set claude --strategy fixed --daily-limit 20 --reserve 0
ai-session budget reset claude --pool EXACT_POOL_ID
```

`reset` removes a configuration override; it does not reset usage or delete grant
history. A service reset removes its default override while preserving narrower
pool overrides. Existing explicitly granted
today allowances retain their expiry. Configuration is separate from admission
mode: strict remains strict after any budget change and currently blocks execution
because request cost cannot be bounded exactly. Existing observed-mode opt-in is
preserved; delayed counters and in-flight work can overshoot its reported thresholds.

## Calendar and defaults

`ai-session budget calendar` shows the private global calendar. Options are
`--workdays all|weekdays|mon,tue,...`, `--reset-cutoff HH:MM` and `--timezone IANA`.
A new ledger uses UTC, all seven weekdays and an 08:30 cutoff. Existing ledgers
retain their timezone. The timezone argument initializes a new ledger or validates
an existing one; it cannot rewrite accounting history. Configure a different
initial timezone before any command creates the ledger, for example:

```sh
ai-session budget calendar --timezone America/New_York --workdays mon,tue,wed,thu,fri --reset-cutoff 08:30
```

Calendar updates are atomic and preserve daily counters and grants. An allocation
anchored under the previous calendar blocks until fresh quota metadata supplies a
matching anchor. The calendar applies across services and projects in this ledger.

`ai-session budget defaults --reserve 0` changes the global fallback reserve.
Pool overrides win over service overrides, which win over that fallback. A new
ledger has reserve 0; no mandatory 10% floor exists. Existing explicit settings
survive upgrades. To remove an old reserve, inspect `ai-session budget`, change the
global fallback, and update every configured service and pool override that retains
it, preserving each strategy and daily limit. For an adaptive service/pool:

```sh
ai-session budget defaults --reserve 0
ai-session budget set codex --strategy adaptive --reserve 0
ai-session budget set codex --pool EXACT_POOL_ID --strategy adaptive --reserve 0
```

Use the existing `fixed` or `window` strategy instead when preserving such an
override. Refresh persisted settings before deciding to stop, and report the actual
reserve. Instructions loaded earlier in a session may describe an old policy.

## Strategies

| Strategy | Behavior |
| --- | --- |
| Fixed | Daily limit, initially 20 points, and the effective configured reserve. Provider renewal does not erase daily consumption. |
| Adaptive | Divide available long-window balance across eligible scheduled workdays until the actual reset. Verified short windows use the window strategy. |
| Window | Permit actual native balance above the configured reserve, without separate daily pacing. Intended for renewable session windows or an explicit owner choice. |

Choose adaptive explicitly to target full weekly/monthly utilization. Existing
settings are never silently replaced. Reserve 0 removes the local reserve, not the
provider exhaustion stop. Exactly 100% consumption is not guaranteed. Do useful
authorized work only; never generate tasks merely to spend an allowance.

Adaptive allocation includes today if it is a scheduled workday. A reset date
counts only when its local reset time is later than the configured cutoff; equality
excludes that date. For example, 60 points of native headroom across three eligible
workdays gives 20 points today. Consuming 5 leaves 15, without repeatedly dividing
the reduced balance. The next scheduled day's fresh balance is redistributed across
the remaining eligible dates. There is no separate carryover credit.

On a scheduled workday, fresh metadata with an unexpired reset no later than
**tomorrow's local cutoff, inclusive**, permits the full current native headroom
above reserve. This releases existing balance; it never predicts a refill. A later
reset observation withdraws that release. Outside this deadline rule, reset forecast
drift does not increase an already anchored allocation. If the first daily anchor
was created during that release, a later reset instead redistributes the remaining
balance over the newly reported working-day horizon. Consumption is never refunded.

Adaptive allowance is zero on a day outside the work schedule unless an explicit
`add` or `use-rest` grant permits work. Fixed and window policies retain their
explicit semantics rather than acquiring an adaptive workday restriction. Dates
and midnight grant expiry use the persisted timezone, including daylight-saving
transitions. Stored reset instants remain UTC timestamps.

All reported pools must pass independently. Do not add percentages from unrelated
windows or assume a model-scoped pool is irrelevant without a verified mapping.
Automatic short-window classification requires validated native duration evidence;
a model name or a reset a few hours away does not establish the window length.
Unknown reset schedules block adaptive allocation. Select an explicit fixed/window
policy for that pool when authorized, or retain the block until reliable metadata exists.

## Resets and evidence

| Service | Documented reset behavior | Runtime authority |
| --- | --- | --- |
| Codex | Session and longer limits depend on account; no universal weekly reset weekday | All `account/rateLimits/read` windows, durations and `resetsAt` |
| Claude | Five-hour session windows and account-specific weekly reset times; additional/model pools can differ | Fresh native usage read, including explicit unknown dates |
| Antigravity | Five-hour and weekly windows depend on plan/model group | Forced native backend refresh, all grouped buckets |
| Copilot | Monthly AI credits reset on the first day at 00:00 UTC; additional session/weekly caps may apply | Account-returned pool reset dates; the billing date is a different concept |
| Other clients/services | No universal calendar or shared allowance | A verified service-specific quota adapter is required |

These are documented schedules, not permission to manufacture a fresh balance.
Prefer the actual account reset over a forecast. An elapsed timestamp or a changed
reset estimate alone never creates a new balance epoch. The deadline rule above
can release only the balance already observed, and a later reset withdraws it. A fresh complete observation
showing a usage drop creates a recorded balance-recovery epoch; adaptive allocation
can then pace the newly observed balance without erasing cumulative daily use.
The drop may reflect renewal, a correction or a plan change; do not assert its cause.
This also handles an early renewal that is visible before the previous forecast.

Existing grants cannot be credited again on recovery. `use-rest` pins an absolute
today ceiling to the balance available when requested; later recovery cannot enlarge
it. Within an epoch, both cumulative daily deltas and native usage growth constrain
spending. Missing intervals remain marked as partial history. The local ledger
cannot coordinate other computers or reconstruct usage it never observed.

Freshness, completeness, unknown pools, native exhaustion, authentication and strict
mode still apply after any grant. Unsupported refresh adapters cannot authorize
execution from manually supplied snapshots. Daily observations and audits are retained
locally for diagnosis; this version intentionally does not prune accounting history.

Provider references: [Codex account API](https://developers.openai.com/codex/app-server/),
[Claude Pro limits](https://support.claude.com/en/articles/8325606-what-is-the-pro-plan),
[Claude Max limits](https://support.claude.com/en/articles/11049741-what-is-the-max-plan),
[Antigravity plans](https://antigravity.google/docs/plans),
[Copilot monthly billing](https://docs.github.com/en/copilot/concepts/billing/usage-based-billing-for-individuals),
and [Copilot quota service](https://raw.githubusercontent.com/microsoft/vscode/main/extensions/copilot/src/platform/chat/common/chatQuotaServiceImpl.ts).
