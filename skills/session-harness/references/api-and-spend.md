# Explicit API requests and monetary budgets

Use this procedure only for an explicitly selected paid route and budget. Native
subscription authentication does not become API authentication. Installation,
model inventory and quota exhaustion never authorize paid fallback, credit
purchase, automatic reload or new billing settings.

## Configure a budget

```sh
ai-session spend set total --monthly 50 --currency USD --mode observed
ai-session spend set api:xai --monthly 10 --currency USD --mode observed
ai-session spend set extra:claude --monthly 5 --currency USD --mode observed
ai-session spend status
ai-session spend add total 5 --id monthly-addition
```

Amounts above are illustrative owner choices. API services are selected in
`ai-session setup`, which also requires the positive monthly total and an explicit
money mode; `spend set` edits caps afterwards. Without a configured total cap,
paid dispatch is denied. `total` constrains all recorded money together; an
optional `api:SERVICE` or `extra:SERVICE` cap constrains that scope additionally.
A topup affects only its named cap for the current calendar month. To increase
both an exhausted total and exhausted scope, adjust both. Reuse the printed ID
when retrying; a different payload under the same ID is rejected.

Money mode is independent of subscription mode. Strict money mode is the default;
current API adapters cannot prove an exact maximum charge and therefore require
explicit `observed` mode. A per-request reservation limits local admission but
is not a provider billing parameter. Delayed or unexpected charges can exceed it.
No credit-card, service spending limit or automatic payment setting is changed.

The monthly balance is paced across the scheduled working days remaining in the
local month. `spend status` reports `day`, `workdays_remaining`, `scheduled_workday`,
`daily_allowance`, `daily_debit` and `daily_available` per cap. The allowance is
frozen at a day's first reservation in the same transaction, so concurrent requests
share one anchor; settlement below a reservation releases the unused part that
day, a day off denies dispatch even after a topup, and cap or calendar changes
redistribute the remainder without refunding today's debit. Status never writes
anchors. Direct transport accepts only a single-use admission from the budgeted
coordinator; `generate` without accounting is rejected.

Month boundaries use the quota ledger's persisted timezone. A request belongs to
the month of its atomic dispatch authorization, not the eventual invoice date.
This calendar budget is separate from provider billing cycles and native credit
resets. Different currencies are rejected, never converted. API pricing currently
requires USD. Exact decimal amounts use 10 billion ticks per currency unit, with
charges rounded upward. Status also provides readable decimal amounts.

## Discover and select an API route

| Service name | Existing key variable | Catalog and billing evidence |
| --- | --- | --- |
| `openai` | `OPENAI_API_KEY` | Account models; explicit token rates required |
| `anthropic` | `ANTHROPIC_API_KEY` | Account models; explicit token/cache-tier rates required |
| `gemini` | `GEMINI_API_KEY` | Model catalog with generation capability markers; explicit token/thought rates required |
| `xai` | `XAI_API_KEY` | Account models; response `usage.cost_in_usd_ticks` is actual billed USD |
| `deepseek` | `DEEPSEEK_API_KEY` | Model catalog; explicit token/cache rates required |
| `kimi` | `MOONSHOT_API_KEY` | International Moonshot model catalog; explicit rates required |
| `zai` | `ZAI_API_KEY` | General API only; catalog unavailable, explicit model/rates required |
| `openrouter` | `OPENROUTER_API_KEY` | Advertised model catalog; response `usage.cost` is billed USD |

```sh
ai-session api models xai
ai-session api run xai --model ACCOUNT_MODEL --max-output-tokens 1000 --reserve-cost 0.25 < plan.txt
```

For PowerShell, use `Get-Content -Raw -Encoding utf8 plan.txt | ai-session.ps1 api
run xai --model ACCOUNT_MODEL --max-output-tokens 1000 --reserve-cost 0.25`; shell
input redirection with `<` is a POSIX example.

Keys are read only for the selected service and retained in memory for its request.
Use the client's existing secure environment setup; never paste keys into a prompt,
command argument, tracked file or report. `inventory` reports key presence only,
not authenticated access. Catalog metadata does not prove model entitlement or
rank model strength. Check current provider evidence and account-visible options;
never infer a current generation from listing order or create a `latest` alias.

Requests use official fixed HTTPS origins with certificate verification, ignore
proxy environment variables, reject redirects and perform no automatic retry.
Google authentication uses a header, not a query parameter. Requests are bounded
text-only, one candidate, non-streaming, with no tools. Unsupported model-specific
effort options fail before dispatch. Z.ai Coding Plan routing is a different
service contract and is not substituted for the general API.

## Explicit pricing for estimated routes

Import a private JSON rate record with `ai-session spend rates SERVICE MODEL
--file rates.json`. Required fields are `currency`, `rates`, `observed_at`,
`expires_at` and a short nonsecret `evidence` reference. Timestamps need an explicit
offset. `rates` maps token classes to exact decimal prices per million tokens;
use current applicable provider prices, including context or service tiers.
No generic price sample is treated as current pricing.

Recognized disjoint classes are `input_tokens`, `output_tokens`, `cache_read_tokens`,
`cache_write_tokens`, `cache_write_5m_tokens`, `cache_write_1h_tokens` and
`reasoning_tokens`. Only the classes actually billed by the selected protocol are
used. OpenAI reasoning already included in completion tokens is not counted twice;
Gemini thoughts outside candidate tokens are counted separately. Unknown billing
classes, missing usage or expired rates cannot settle as zero.

The adapter labels token-derived charges `estimated`. They are not invoices.
xAI and OpenRouter receipts can settle actual cost even when unexpected tool or
nontext output is rejected. Other service receipts can be reconciled explicitly
when obtained through the provider's supported billing interface.

## Crash, retry and reconciliation

Reservation and the `DISPATCHED` record commit together before any HTTP request.
No database write lock spans the network call. Fresh request IDs permit repeated
identical prompts; repeating a prior `--id` returns accounting status and never
sends another request. Prompt/response text is not stored in the ledger.

Timeouts, HTTP errors, interrupted processes and invalid responses retain liability.
An unfinished dispatch counts against later months until reconciled; midnight,
process death or a predicted reset cannot erase it. An HTTP error alone does not
prove that the provider charged zero. There is no timeout-only release.

```sh
ai-session spend reconcile REQUEST_ID --actual 0.12 --evidence invoice:verified-line
ai-session spend record extra:claude --actual 2.50 --currency USD --evidence invoice:credit-use --id unique-receipt
```

Use actual evidence, including for a zero charge. Reconciliation cannot reduce an
already evidenced actual charge; refunds do not erase consumption. An actual
charge above reservation is recorded in full and latches a review requirement.
Topups do not clear that latch; explicit reconciliation with evidence does.
Receipt imports record already incurred expenses without initiating inference or
buying credits. They are attributed to the current local accounting month. Give
the same import its original ID to avoid counting it twice.

## Native extra credits

Credit metadata remains in native units with its source and eligibility controls.
A Codex balance string has no verified currency scale; Copilot quota/overage units
are not automatically AI credits or dollars. Promotional, purchased and reset
credits are not merged into subscription percentages.

A money configuration does not make a native paid-credit route safe. Until a
verified adapter can establish billing eligibility and associate charges with
requests, paid native execution is unsupported. Version 0.1.2 blocked protected
Codex execution and required an explicit disabled Antigravity setting.

The Codex confirmation commands and absent-file/key Antigravity default handling
below are available in v0.2.0. Retain an existing installation until the owner
requests an update or an already enabled automatic maintenance policy applies.

Claude can establish subscription-
only eligibility from explicit disabled controls. Antigravity's documented
`useG1Credits` CLI setting is read from `~/.gemini/antigravity-cli/settings.json`
as local fallback-control evidence: explicit `false`, or the [documented disabled
default](https://antigravity.google/docs/cli/reference) for an absent file/key,
admits with fresh quota. Enabled, unreadable or malformed settings block. Defaults
have separate source provenance and do not supply account balance or purchase
metadata. Codex does not report automatic top-up controls. Its owner may record an
explicit disabled-setting confirmation for the current ChatGPT account:

```sh
ai-session usage credit-policy codex --auto-top-up disabled
ai-session usage credit-policy codex
ai-session usage credit-policy codex --revoke-credit-policy
```

Only record confirmation after the owner states the setting is disabled; never
infer it from a zero balance or finish confirmation autonomously. The private
record binds a hash of the current authenticated account and survives sessions
and updates. It is owner evidence, not a provider-reported billing control.
Admission additionally requires fresh account credit metadata showing zero balance,
no credits and no unlimited credits, plus every ordinary subscription quota check.
Scoped rows without credit metadata may use the same account-wide confirmation;
conflicting, positive or invalid credit data still blocks. Account changes and
revocation invalidate the record. Revoke it before enabling top-up or changing the
billing policy. Paid native execution remains unsupported. On a coordinated setup,
record this once on the authority; team members must not create separate policies.
This confirmation adapter currently requires a POSIX authority with file-backed
ChatGPT authentication; Windows clients can use that authority through coordination.
The declaration remains effective until revoked or the account changes, matching
the owner-controlled setting. It cannot detect a later website change automatically;
observed mode and the owner's obligation to revoke before enabling top-up remain explicit.
Unknown purchase/reload controls cannot authorize spending in either mode.
Never change those settings automatically to clear a stop.

Primary contracts: [xAI cost tracking](https://docs.x.ai/developers/cost-tracking),
[OpenRouter accounting](https://openrouter.ai/docs/cookbook/administration/usage-accounting),
[OpenAI API](https://developers.openai.com/api/reference/),
[Anthropic models](https://platform.claude.com/docs/en/api/models/list),
[Gemini generation](https://ai.google.dev/api/generate-content),
[DeepSeek API](https://api-docs.deepseek.com/api/create-chat-completion/),
[Kimi API](https://platform.kimi.ai/docs/api/chat),
[Z.ai API](https://docs.z.ai/api-reference/llm/chat-completion).
