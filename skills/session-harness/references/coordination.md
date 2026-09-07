# Multiple sessions, accounts and teams

Session capacity and quota are separate controls. Capacity limits simultaneous
owners; quota limits their combined consumption. All native workers belonging to an
owner share its accounting. Never create independent ledgers for the same account
to give each session a fresh allowance.

| Situation | Configuration |
| --- | --- |
| Several sessions on one computer and account | One local ledger, multiple session owners |
| One account used on several computers or by approved shared-host users | One account authority; every participating client uses it |
| Teammates with separate provider accounts | Separate authenticated authorities and ledgers; a common project does not share quota |

An authority must have authentication for the same configured accounts as its clients.
The current generic SSH configuration selects one authority for all native services.
It does not automatically match arbitrary accounts or authorize credential sharing.
Use a separately maintained host adapter for multi-user authentication where applicable;
generic profile installation alone does not provision other operating-system users.

## Inspect and change capacity

```sh
ai-session coordination status
ai-session coordination set --max-sessions 8
ai-session configure
```

Run capacity changes on the authority. New configurations default to four sessions
per service. Existing explicit limits are preserved during updates. Values from
1 to 32 are supported; `--authority` can be omitted to keep the current routing.
The wizard includes capacity in its reviewed configuration. A remote client's local
capacity value cannot override its authority. Status reports `authority_max_sessions`,
`active_sessions` and `authority_sessions`; account records are private.

An increase works while owners are active and leaves their records and quota history
untouched. A decrease below the active count is rejected; first finish sessions.
Changing authority while local owners exist is also rejected. Uncertain owners do
not expire automatically. Close supervised processes normally so their owner is released;
direct Claude sessions release through supported completion hooks.

`account_session_busy` means capacity is occupied. Inspect status, close an unused
session or select a larger capacity. Do not treat this as a daily quota stop, ask
another model to retry it, or increase quota merely to obtain another session slot.

After a crash, use the exact owner shown by status, only after confirming its process
and background work have stopped:

```sh
ai-session coordination release --service claude --owner EXACT_OWNER --confirm-stopped
```

Do not delete another person's live owner. Existing native workers share their
manager's owner rather than taking an independent slot. Sessions launched outside
the configured authority remain outside its concurrency and quota controls.

## Shared accounting and its limits

Quota refreshes serialize per ledger and service across processes. Each complete
backend observation is recorded before the next refresh begins. This prevents
out-of-order counter writes and duplicate daily debits while allowing model work
to overlap. Refresh-lock timeout or backend failure denies the check; a failed new
admission releases only its own newly acquired slot. No cached redraw creates quota.

Four sessions spending 3 percentage points each consume 12 points from one account
pool. A common daily stop applies to every owner and its workers. Session capacity
does not change budgets, reserves, grants, paid eligibility or billing preferences.
Observed mode still permits in-flight overshoot, which can grow with concurrency;
strict mode continues to require enforceable request-cost bounds.
