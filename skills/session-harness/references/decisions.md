# Jev decisions through OpenRouter

Available since version 0.6.0. Check that your selected
installation exposes `api decide` in `ai-session api --help`.

Prefer authorized, available Jev for narrow semantic judgments with defined outputs:
email/ticket triage, document tags, comment moderation, rubric scores, relevance
ranking, selecting supplied candidates, and checking a claim against evidence.
Keep deterministic rules and lookups in code. Use general models for writing,
explanations, code and complex reasoning. Jev is never a manager or independent reviewer.
This is task-level agent guidance and a typed CLI, not interception of every prompt.
It does not install email, social-media, trading or other application automations.

## Set up and inspect

1. On the existing monetary authority, expose the authorized `OPENROUTER_API_KEY`
   through its secure environment. Preserve separate free-route credentials.
2. Run `ai-session onboard openrouter`, select `api`, and let the owner confirm
   authorization, money cap and mode interactively. A funded account or installed
   skill alone does not authorize dispatch. Check `ai-session spend status`.
3. Run `ai-session api decision-models`. This anonymous public metadata GET does
   not prove account entitlement or successful inference.

Strict money mode refuses requests without enforceable cost bounds; observed mode
accepts possible overruns. Harness caps, provider key limits and prepaid balances
are separate controls. OpenRouter still depends on upstream TypeSafe; its gateway
cannot guarantee avoidance of a TypeSafe outage.

The default resolves the official latest Jev alias target to a concrete model from
the current decision catalog. Returned identity must match that row's ID or canonical
slug. No stale catalog, guessed model or paid fallback is used. If the default cannot
be resolved, inspect the catalog and pass a verified `--model` explicitly.

## Run a decision

Save this synthetic request as `decision.json`:

```json
{
  "state": "Checkout stopped working after today's release.",
  "questions": {
    "urgent": {
      "type": "noul",
      "instructions": "Does this report describe a service interruption?"
    },
    "team": {
      "type": "choice",
      "instructions": "Which team should investigate?",
      "criteria": {"engineering": "Broken software", "support": "Other requests"}
    },
    "severity": {
      "type": "score",
      "instructions": "How much does this problem prevent use?",
      "criteria": ["Minor inconvenience", "A core function is unusable"]
    }
  }
}
```

```sh
ai-session api decide openrouter --reserve-cost 0.01 < decision.json
```

PowerShell: `Get-Content -Raw -Encoding utf8 decision.json | ai-session.ps1 api decide openrouter --reserve-cost 0.01`.

The USD reservation is an illustrative caller choice, not a provider maximum charge.
Every call passes total, scope and daily money checks. `api run`/chat completions
are not the Jev interface. Successful output contains `requested_model`, actual
`model`, typed `answers` and `accounting`.

| Primitive | Meaning | Handling |
| --- | --- | --- |
| `noul` | Probability of yes, 0-1 | Near 0.5 is uncertainty, not medium intensity |
| `choice` | One supplied option | Include other/no-match when appropriate |
| `score` | Position on ordered rubric levels | May be fractional; range 0 through number of levels minus 1 |

OpenRouter may omit confidence, probabilities and score legends. Never invent them.
When present, the adapter validates ranges, exact candidate/index keys and legends;
probability sums tolerate rounding up to 0.001. All answer IDs and types must match.
Typed output is not proof of truth or permission to act. Evaluate thresholds on
representative task data and languages. Escalate uncertain work through an already
authorized route with its own admission; never bypass stops.

Client bounds: 128 questions, 24 KiB serialized UTF-8 body, 1-255 Choice options,
2-10 Score levels. These are not a tokenizer or a guarantee of provider context fit.
Batch independent questions over shared state; dependent questions need new state.

## Costs, errors and privacy

Actual `usage.cost` uses exact decimal accounting even when answers or model identity
are rejected. Missing/invalid cost, HTTP errors (including 4xx) and timeouts retain
the reservation. No usable answers are exposed on rejection; there are no automatic
retries. Verified zero cost is recorded as zero; missing cost never becomes zero.
An overrun is charged in full and blocks further dispatch pending reconciliation.

Use OpenRouter activity/billing evidence before
`ai-session spend reconcile REQUEST_ID --actual AMOUNT --evidence RECEIPT_REFERENCE`.
Timeouts may lack a provider ID: use request time and key activity or provider support.
The harness cannot self-recover or infer non-execution from an HTTP error. Reusing
`--id` returns accounting without a second POST. Mock tests do not prove provider billing.

State and questions go to OpenRouter and upstream TypeSafe. Send only authorized,
necessary task data; never include credentials. Retention is outside harness control.
The ledger stores request digests and costs, not state, answers or keys. CLI receipts
can contain task data; keep private receipts out of public repositories.

## Optional official skill and rollback

The [TypeSafe skill](https://github.com/typesafe-ai/skills/tree/main/skills/typesafe-ai)
helps design judgments. Inspect and pin a revision before installing it with your
client's skill installer. It is optional; the adapter needs no SDK. For harness
workloads use budgeted `api decide`, even when upstream examples show raw API/SDK
calls. Never bypass accounting or enable SDK retries around the harness.

Rollback removes only the installed skill and its task-owned client links/preferences.
Restore the previously selected harness release to remove the adapter while preserving
setup, schedules, usage history and unresolved costs. Reviewed skill overlays use
the existing [maintenance workflow](automatic-maintenance.md#activation-local-overlays-and-shared-hosts).

Contracts checked 2026-09-21: [OpenRouter OpenAPI](https://openrouter.ai/openapi.json),
[decision SDK](https://github.com/OpenRouterTeam/typescript-sdk/blob/main/docs/sdks/decisions/README.mdx),
[TypeSafe primitives](https://docs.typesafe.ai/primitives),
[TypeSafe API](https://docs.typesafe.ai/api), [TypeSafe models](https://docs.typesafe.ai/models).
Use these contracts instead of third-party speed or reliability claims.
