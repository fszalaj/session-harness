# Run additional clients

Use the commands supplied by your selected release. Inspect the client separately
from the model provider and the account that pays for execution. Inventory
`execution_supported` identifies an implemented adapter; `execution_admission`
remains `not_checked` until a protected command verifies the account and quota.
Automatic native work can select configured Copilot and Cursor Auto workers.
Their output requires manager inspection; Auto does not establish the strongest
model or an independent reviewer. Explicit provider requests remain available.

## Copilot CLI

1. Install the official Copilot CLI and sign in with `copilot login`.
2. Run `ai-session inventory` and inspect Copilot's authentication, model catalog
   and quota records.
3. Select Copilot in `ai-session configure` on the client and its account authority.
   Preserve existing services, budgets and mode. Keep paid overage disabled.
4. Initialize a first accounting baseline on the authority with
   `ai-session usage refresh copilot --initialize`. For an existing baseline, omit
   `--initialize`. Run `ai-session usage check copilot` before execution.
5. Start an interactive session with `ai-session copilot`. For bounded text work,
   explicitly enable bounded routing on the authority and run:

   ```sh
   ai-session balance enable --services copilot
   ai-session work --provider copilot --id unique-task-id < task.txt
   ```

The single-service enable command is supported by version 0.6.1. Release 0.6.0 requires two services. Multiple models through Copilot are
one billing service; do not add another account solely to satisfy that old limit.
With one service, relative balancing has no competing provider, but admission,
one open task per service, stable task IDs and unresolved-job stops still apply.

The worker uses Copilot's native session protocol with tools, MCP, hooks, skill
discovery and additional agents disabled. Its return value is text for the manager
to inspect. The interactive client retains its normal project tools and policy.
Shared quota checks apply to both routes. Strict mode remains blocked without an
enforceable request bound; an existing observed-mode choice is preserved.

An account advertising only `auto` cannot establish the strongest model before
execution. Inspect `actual_model` and token counts in the completed worker receipt.
Copilot auto is not an independent provider-family reviewer. An absent effort
control is recorded as unavailable; no effort value is invented.

### Explicit models

These controls require harness version 0.6.0 or newer.
Copilot supports `--model` and `--effort`, and interactive `/model`
shows account-selectable IDs. A Free account may expose only Auto; flags cannot
grant access to models outside its catalog. Paid account and organization policies
still determine which named models are available.

Copy exact IDs from fresh `ai-session inventory` output, choosing the newest
eligible generation in each family. The following placeholders are not model IDs:

```sh
ai-session launch copilot --model MODEL_ID --effort medium --execute
ai-session work --provider copilot --model MODEL_ID --effort medium --id unique-task-id < task.txt
ai-session review copilot --model CLAUDE_MODEL_ID --manager-family openai --effort medium < plan.txt
ai-session review copilot --model GEMINI_MODEL_ID --manager-family openai --effort medium < plan.txt
```

Use only advertised effort labels; omitting effort selects the configured default
(publicly high) or the highest supported lower level for every role.
No advertised effort means the field is omitted. These flags are Copilot-only;
automatic routing is unchanged. Model and effort bind a worker's existing task ID,
so changing either requires a new task ID, not a retry of a completed request.

Named reviews use separate sessions with the same isolation as text workers and
require a declared actual manager family. Auto, unknown families and the manager's
family cannot review. Compare the two receipts' `model_family` values as well:
they must differ from each other and the manager. Both use the **same Copilot
account quota**. Existing role restrictions, finite token-billed allowance and
disabled-overage requirements still apply; request-billed plans are unsupported.

The 0.6.1 adapter reads `session.model.list` in an isolated,
empty session because the global SDK `models.list` can omit models available in
the interactive picker. Inventory sends no prompt. This path was checked with
Copilot CLI 1.0.86; older protocol versions may fail discovery or selection.
Execution rechecks this session catalog, applies `session.model.switchTo` with
`requireAvailable`, and verifies the selected model and effort before sending text.
Every reported usage model must exactly equal the requested catalog ID. Missing
identity, aliases that resolve to a different string or model fallback stop the
request; do not loosen matching without separately verified alias evidence.
Session settings confirm selection, not inference. Effort is not confirmed by
usage telemetry. A model name in a text
answer is not identity evidence. Interactive launches cannot verify a strongest
model merely because an explicit ID was supplied.

Named Claude/Gemini execution requires a first-account smoke test. A Free-only
catalog permits metadata and rejection checks, not proof that named execution
works on a paid account. Test each named route before relying on its review.
See GitHub's [CLI command reference](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-command-reference).

A legacy quota upgrade archives the original service state. Active pool identifiers
and their daily usage, policies and grants move to verified billing-unit names.
Native `hasQuota:false` pools leave current admission but retain their historical
entries and archived observation; they cannot authorize requests. If old and new
aliases both contain consumption for a day, stop for reconciliation rather than
counting the same usage twice. Existing newer observations are preserved.

The 0.6.1 worker accepts exactly one active finite token-billed `chat` or
`premium_interactions` pool, with any other active pools unlimited. Release 0.6.0
accepts only finite chat. Missing quota/overage flags, unknown finite pools or
multiple finite pools stop execution. All pools must report disabled exhaustion
and overage use. The selected pool, its entitlement and other pool definitions
must remain consistent before and after execution; receipts identify that pool.
The worker checks aggregate account consumption. These deltas can include other sessions;
they are not an exclusive per-task bill. Native reset timestamps at or before the
observation remain unknown. Monthly pacing uses a conservative 31-day window.

On missing usage, a model mismatch, timeout or failed execution, inspect the retained
job and stop the owned client process before recording recovery:

```sh
ai-session balance status
ai-session balance reconcile TASK_ID --confirm-stopped
ai-session usage check copilot
```

Recovery preserves accounting. Do not automatically replay the task or switch
services to bypass a stop. Small responses may not move rounded account counters;
the receipt preserves the zero observed delta and reports the per-task charge as
unknown. Token counts do not establish a quota debit or a monetary charge.

## Ollama local

1. Install Ollama, start its server in local-only mode and install a model using
   Ollama's native commands. Model downloads require disk space and are explicit.
2. List eligible installed models with `ai-session ollama models`.
3. Run a bounded task with an exact model identifier from that list:

   ```sh
   ai-session ollama run --id unique-local-task --model MODEL_ID --max-output-tokens 256 < task.txt
   ```

Requests use only `127.0.0.1:11434`; proxy and `OLLAMA_HOST` overrides do not reroute
them. Cloud tags and remote-model metadata are rejected. Catalog digest/size and
local model metadata must confirm residency before execution. This route provides
text, not an autonomous tool-using coding session or independent review.

Local execution uses computer resources and a separate local job ledger. It does
not claim a native subscription allowance or a cloud API credit balance. One
unresolved generation blocks further local jobs. After confirming that generation
has stopped, run `ai-session ollama reconcile --id TASK_ID --confirm-stopped`.
Reusing an ID returns only its existing receipt and never repeats inference.

## Meta and Ollama Cloud

Use `ai-session api models meta` or `ai-session api models ollama` to inspect the
explicit account catalog. Keep keys in the supported private credential source.
Select the service and monetary policy through [API setup](../skills/session-harness/references/api-and-spend.md)
before `api run`. Installation and catalog access authorize no spending.

Meta uses its official `/v1` API. Contributor/training-tier model names are rejected.
Meta API access and running a Meta Llama model locally through Ollama are separate
routes. Check the account's current eligibility; a Llama model name does not grant
Meta-hosted API access.

Ollama Cloud uses the native `/api/chat` endpoint and `/api/tags` catalog. Its
native response lacks a request ID; accounting uses the harness task ID rather
than treating the response timestamp as a unique provider receipt. Its
included free allowance is not automatically converted into a dollar budget.
Without the configured admission evidence, cloud execution stays blocked.

## Cursor CLI

1. Install the official Cursor CLI and sign in with `agent login`.
2. Run `ai-session discover --session cursor`. Use a personal Free account with
   on-demand usage disabled and no credit grants. Other account configurations stop.
3. Select `cursor` in `ai-session configure` on the client and account authority.
4. On a first baseline only, run `ai-session usage refresh cursor --initialize` on
   the authority. Run `ai-session usage check cursor`.
5. Start `ai-session cursor`, or enable balancing and submit bounded text:

   ```sh
   ai-session work --provider cursor --id unique-cursor-task < task.txt
   ```

The Free CLI requires Auto. Named models shown by `agent models` can still require
an upgrade; the harness does not upgrade or switch to paid usage. Auto does not
expose the routed model or reasoning effort. Receipts keep `actual_model` and
`model_family` unknown and report native token counts. Do not count this route as
an independent provider-family review or a verified strongest-model manager.

The text worker uses an empty workspace and native configuration, ask mode,
explicit sandboxing, denied file/shell/web/MCP permissions and blocked web tools.
It rejects tool events and validates session, response and token metadata. Native
system instructions and skill metadata may still contribute context. Interactive
sessions retain normal project tools and existing permissions.

Quota reads use the installed CLI's read-only native account transport. Unknown
native schemas, plans, grants or paid-usage controls fail closed. The reader does
not modify the vendor installation. The reader accepts reviewed entry-file hashes
for CLI 2026.09.08-6caf4ff on Linux x64 and macOS arm64. Other builds fail closed;
update the adapter when a changed CLI reports unavailable metadata. Quota deltas
are aggregate lower bounds, not per-task charges. Interrupted or unverified jobs
require the same inspection and explicit reconciliation as Copilot.

## Other inventory clients

Gemini CLI, Kimi CLI, OpenCode, Aider and Continue retain their separately documented
inventory boundaries. Antigravity CLI has its own execution adapter and is distinct
from Gemini CLI. See the [client map](../skills/session-harness/references/clients.md).
