# Recurring free account pools

Development feature; not part of the published v0.2.0 release. Account creation,
installation and catalog access do not enable inference. Keep credentials and
account evidence outside repositories and shared documents.

`free` performs supervised text work. It has no tools or independent reviewer
role. Explicit free-access configuration is separate from paid API setup: no
monthly money budget, automatic paid fallback, purchase or billing upgrade occurs.
Groq, Mistral, Hugging Face, Morph and NVIDIA have fixed chat/catalog adapters;
only accounts with verified applicable free/no-overage evidence may be enabled.
An available adapter is not proof that a given account qualifies.

## Configure the executor

Use one physical host for an account. Its ledger must reside on local disk under
`~/.local/state/session-harness`, never iCloud Drive, NFS or SMB. SQLite uses
DELETE journaling, FULL synchronization and a 10-second busy timeout. Other hosts
send bounded packets through the existing trusted SSH executor. There is no
replication, alternate executor or local fallback when SSH fails. The native
subscription authority can be a different host; native and money ledgers retain
their existing settings and history.

```sh
ai-session free configure --file /private/account-settings.json
ai-session free status
ai-session free models
ai-session free run --id unique-task-id --model groq --max-output-tokens 256 --timeout 60 < task.txt
```

Schema 1 remains the legacy OpenRouter-only configuration. It requires explicit
zero key credit cap, fresh reviewed `:free` models, zero catalog prices, zero-price
provider routing with fallback disabled, and a response confirming zero cost and
model identity. Its existing ledger is not migrated or replaced.

Schema 2 uses `schema_version: 2`, `authority: local`, `mode: observed`, explicit
boolean `enabled` and `mixed_work`, and an `accounts` object keyed by provider.
An excluded account is `{ "enabled": false, "reason": "unverified_entitlement" }`.
The `openrouter` value may contain a complete enabled local schema-1 configuration.
Other enabled entries have these fields (see `free_accounts.validate_config`):

| Field | Required evidence or purpose |
| --- | --- |
| `credential_file` | Absolute private file containing one `API key: VALUE` line; mode 0600, current owner, no symlink |
| `credential_sha256`, `account_sha256` | Private key/account binding; a different account must not inherit allowance |
| `model`, `response_models`, `family` | Reviewed exact request ID, bounded expected response identities and actual model family |
| `context_tokens`, `max_output_tokens` | Verified model capacities; local output ceiling at most 8192 |
| `evidence` | Observation/expiry timestamps, account UI/API provenance, HTTPS account/coding/pricing/tokenizer sources, explicit no-paid-overage contract and `tokenizer: byte_bpe` |
| `reasoning_effort` | Optional verified Groq/Mistral control; `none`, `low`, `medium` or `high`; receipts record the requested setting |
| `limits` | Local `rpm`, `rpd`, `tpm`, `tpd` ceilings, observed `credit_usd`, exact decimal input/output rates per million, and observed `period_start` |

Evidence keys are `observed_at`, `expires_at`, `kind` (`account_ui_observation` or
`account_api_observation`), `source`, `coding`, `pricing_source`, `tokenizer_source`,
`no_paid_overage`, `tokenizer`, `hf_routing_only`. The local expiry must be at most
24 hours after observation. This is a conservative local freshness policy, not
a provider reset promise. Catalogs are refreshed at dispatch; billing and tokenizer
facts must be independently verified before renewing account evidence.

Hugging Face requires one explicit hosting-provider suffix, such as
`model-id:novita`, verified HF routing without custom provider keys, a personal
account identity, live provider metadata and prices within the configured bound.
No organization billing header is sent. API catalog listing alone does not prove
remaining credits or no-paid-overage controls. Mistral/HF/Morph require a positive
observed free credit balance and positive verified rates. Unknown separately
billed reasoning, tokenizer bounds or account overage behavior blocks enablement.
Morph's advertised allowance and current balance must be reconciled; NVIDIA
requires verified free development/testing entitlement. Both start disabled.

On the other host, schema 2 uses `authority: ssh` and a `command` string array
beginning with `ssh` and invoking the executor's `harness.py free serve`. It has
no `accounts` or credentials. Preserve trusted host verification and authentication.
The server refuses another SSH hop. Test reachability and compare status from both
clients before enabling mixed work. Secrets stay exclusively at the executor.

## Admission and receipts

`--model auto` selects an enabled account by its largest consumed/limit fraction
across request, token and credit dimensions, then by provider name for ties.
`--model groq` selects that configured account's exact model. These fractions are
quota progress, not equal tokens, model quality or monetary spending. Explicit
`mixed_work: true` lets `ai-session work` compare the free group with admitted
native subscription fractions. A native common stop still blocks mixed work.
Missing/stale evidence for an enabled account blocks the group; excluded accounts
are explicit and never become automatic fallbacks.

One task ID is permanently bound before POST. Reusing it returns accounting only;
changing its payload is rejected. Provider failure never retries or changes route.
Reservations use the larger original/NFC UTF-8 byte length plus 1024 template tokens and bounded
output, only for reviewed byte-BPE text tokenizers. Rates are decimal strings.
Actual usage/identity must fit the reservation before output is returned.
Request/token ceilings use conservative rolling 60-second/24-hour windows when
the provider reset timezone is unknown. A persisted clock-backward check blocks
unsafe counter renewal; HTTP deadlines use monotonic time.

Credit reservations stay consumed even after successful output. This deliberately
underuses allowances rather than refunding an unverified invoice estimate. Add
provider billing settlement only when a verified receipt adapter exists. Receipts
separate reserved free credit from actual monetary cost, which remains unknown
when not reported. They retain no prompts, response text, credentials or raw
provider diagnostics. HTTP failures retain sanitized status codes. A billing-class
402/403 requires account re-verification before explicit reconciliation.

## Recover and renew

A crash, timeout or uncertain response retains the whole reservation and blocks
that account, including after a date change. Inspect the exact process and receipt.
Once stopped and any billing concern re-verified, reconcile on the executor:

```sh
ai-session free reconcile EXACT_ID --confirm-stopped --evidence process:verified-stopped
```

This records a nonsecret evidence reference and releases the pending slot, without
refunding quota. For an uncertain legacy OpenRouter dispatch inside a group, inspect
and reconcile both its legacy ledger (using the schema-1 config) and group record.
A genuinely new attempt needs a new ID and fresh admission; never automate it.

Monthly credits never automatically refill. After verifying an actual new provider
period and remaining allowance, with no unresolved requests, update the private
configuration and explicitly record its start on the executor:

```sh
ai-session free renew-period PROVIDER --start VERIFIED_UNIX_TIMESTAMP --evidence billing:verified-new-period
```

Historical rows remain. Do not use this command merely because a predicted reset
passed. Refreshing same-period evidence must preserve its original start and total
local cap; subtracting local usage again would double-count consumption.

Back up existing config and SQLite through its backup API before deployment.
Rollback software must retain all newer accounting. Restore a ledger snapshot only
if no dispatch happened after that snapshot. Never change a provider account,
purchase credits or weaken a guard to clear a stop.

## Sources and verification

Account-visible controls take precedence over marketing. Consult current
[Groq rate limits](https://console.groq.com/docs/rate-limits),
[Mistral pricing](https://docs.mistral.ai/inference/pricing),
[Hugging Face billing](https://huggingface.co/docs/inference-providers/en/pricing),
[NVIDIA free development access](https://docs.api.nvidia.com/nim/docs/product)
and [OpenRouter limits](https://openrouter.ai/docs/api_reference/limits).
Live acceptance should perform one bounded useful task per eligible account and
verify model, usage and shared accounting from both hosts. A unit test or catalog
response does not prove account entitlement or a live successful request.
