# Claude model allowances

Development builds admit a concrete Claude model against its common limits and the
native pools that apply to that model. A verified Fable-only limit does not block
Opus or Sonnet. Unknown scope metadata remains required for every model. Existing
pool identifiers, daily consumption, reset history and grants are preserved.
The reader uses reported percentages; it never invents a remaining 50% balance.

Run `ai-session discover --session claude` to resolve the current account catalog.
Use a concrete ID from that output:

```sh
ai-session usage check claude --model CONCRETE_ID
ai-session usage status claude --model CONCRETE_ID
```

`check` refreshes the shared authority. `status` reads local evidence, which may be
stale on a coordinated client. Each pool retains its `model_scope`, `applicable`
flag and diagnostic `reasons`. An unscoped check conservatively includes all pools.
Shared weekly/session budgets, reserve, calendar, dated grants, fresh complete
observations, strict mode and billing controls still apply.

## Selection and conversation continuity

The launcher prefers the current planning model. If only its model-specific
allowance is exhausted, it checks the current account-visible Opus and its role
permissions. Bounded workers prefer current Sonnet, then an admitted current Opus
at nonmaximum effort. The balancer compares common non-session pacing pools;
model-specific limits still gate the actual worker before inference.

Protected interactive Claude on POSIX requires CLI 2.1.251 or newer for model hooks.
The supervisor waits for startup metadata before accepting terminal input. Hooks
track model changes and refuse unaffordable or role-restricted targets. Unknown
native subagent models retain all-pool admission; use `ai-session work` for a
bounded worker whose model can be verified. Earlier clients and custom launch
arguments retain conservative all-pool supervision.

After a verified model-only stop interrupts an owned process, successful process
and terminal cleanup permits one automatic resume of the exact conversation UUID
on an admitted alternative. The terminal explains the switch. No prompt is replayed.
Normal quit, final-observation denial, unknown cleanup or missing metadata never
starts a replacement session. Automatic recovery supports a default launch or an
explicit UUID supplied with `--resume`, `-r` or `--session-id`; other arguments use
manual native resume. In-flight overshoot remains possible in observed mode.

This differs from Claude's availability fallback chains, which do not handle rate
limits. See the [native hooks](https://code.claude.com/docs/en/hooks),
[model controls and resume precedence](https://code.claude.com/docs/en/model-config)
and [Fable plan allowances](https://support.claude.com/en/articles/15424964-claude-fable-models-on-your-plan).

## Other billing services

This change does not authorize a different account, subscription, paid credit or
API route. Claude through Copilot, Cursor or another host uses that host's resources.
Their protected execution capabilities remain separately documented in
[client adapters](clients.md). Explicit API routes retain their monetary admission.
