# Start or resume substantive work

Run this discovery at a new manager session and after a release, account, catalog
or policy change. Leaf tasks do not restart it. Use existing metadata commands;
this procedure adds no inference, background polling or new account authorization.

## Inspect the selected environment

1. Read project instructions and select one harness runtime. Run `ai-session version`;
   compare the installed profile and any project copy. Use the selected release's
   help and references. A project copy can differ from the global installation.
   Preserve existing update opt-ins; update only within authorized maintenance.
2. Identify the actual hosting client from native session controls. Read
   `ai-session configure --status`, `ai-session coordination status` and
   `ai-session budget`. Keep configured services, authority, reserves and role policy.
3. Run `ai-session discover --session CLIENT` with the actual supported client and
   `ai-session inventory`. Inspect each configured candidate through its implemented
   adapter. Distinguish detected software, public catalog, account-selectable model,
   supported execution, supported roles and current admission. None implies the next.
   If the hosting client is unknown, run `ai-session discover --session auto` first.
   It checks launcher/session markers and supported parent-process evidence. Plain
   SSH can correctly return unknown; conflicting markers return ambiguous. Confirm
   the real client before passing an explicit `--session CLIENT`; that value is an
   operator declaration, not an independent detection result.
4. Read `ai-session balance status` for configured participants, model-role
   restrictions and automatic selection eligibility. Its native quota refreshes can
   update observations and native authentication caches; they do not submit prompts
   or change authorization. Missing or denied evidence remains a stop.
5. Include registered API/free routes in the capability inventory. For an explicitly
   configured API, use `ai-session api models SERVICE` and `ai-session spend status`
   on its authority; for a configured free route, use `ai-session free status` and
   its catalog command from `ai-session free --help`. Use the current route reference.
   Use the [provider wizard](provider-onboarding.md) when the user wants to add a route.
   A public catalog or saved key is not authorization. Do not dump credentials,
   enable billing, or discover unrelated accounts. Local models have their own
   explicit catalog and residency checks (`ai-session ollama models`).
6. Check project skills and knowledge access from the actual checkout. Use its
   configured wiki/MCP and code graph. A global skill link does not prove that a
   project vault exists or that every client can connect. Text-only workers receive
   bounded excerpts from the manager when their adapter forbids tools.

Keep a compact private working note of route, billing service, upstream family,
requested/resolved model, supported roles, effort, admission, missing capabilities
and source/time. It is session evidence, never a static capability list in public
instructions. Do not store account details or runtime state in a team runbook.

## Choose current models and independent reviewers

Establish execution and role eligibility from current evidence. Within each family,
default to the newest available generation, then optimize task fit and cost within
that generation. Do not silently fall back to an older generation after a stop.
Use the strongest current hosting-provider model for the manager at advertised
`xhigh`, otherwise the highest supported level below `max`. Reserve `max` for an
explicitly selected, extremely difficult task. Verify the running model; Markdown
cannot switch it. Normal bounded workers and ordinary reviews use supported medium
effort, gathering low and difficult verification high.
Automatic helper defaults select advertised medium or the highest supported level
below it. If no routine level or required model variant exists, inspect the catalog
and select a compatible current model. Do not infer a working base-model fallback.

Select two reviewer-capable routes with different **upstream model families**, both
different from the manager. Do not prescribe a fixed pair of brands. Resolve model
identity independently from the reseller, client and billing account; two gateways
to one model family do not provide two independent families. Check the selected
model's role restrictions and fresh admission before sending the same review packet.

Native `review` adapters perform the supported isolation, model and role checks.
Opaque Auto, unknown-family output, `supervised_only` capability, free workers and
`api coding-run` output cannot satisfy an independent verdict. General `api run`
can carry a review packet under explicit monetary authorization, but does not
supply automatic reviewer-role, family or exact-model validation. Accept it only
through the separately verified API review procedure; never infer parity with a
native reviewer or route around a configured role restriction. Missing completeness
or identity metadata leaves the review unverified; confident prose is not evidence.

Reconcile actual returned identities, findings and terminal receipts using the
[review protocol](review-protocol.md). Native reasoning labels are not comparable
across providers; record unavailable controls without inventing values.

Capability selection occurs before dispatch. A missing adapter or prohibited role
is not itself quota exhaustion; inspect the other authorized reviewer-capable
routes before declaring a missing panel. A genuine quota/evidence stop still obeys
its configured scope and cannot be bypassed by switching service or account.
If fewer than two independent families qualify, name the verified coverage and
exact missing capability or decision. Continue independent preparation; do not
start gated implementation with one review, invent approval, or silently relax
policy. Ask only when that missing decision is necessary and not already authorized.

## Reusable task prompt

```text
Complete [task] in this project. Success means [observable result]; constraints are
[scope and limits]. Follow AGENTS.md and the selected session-harness runtime.
Use its session-start reference to inspect current clients, registered native/API/
free routes, model catalogs, role permissions, quotas, project skills and knowledge
access. Resolve capabilities from live evidence instead of a remembered provider list.
Select the newest available generation in each family; keep manager xhigh and normal
workers/reviews at supported medium effort. Use max only for my explicit extremely
difficult-task exception. Resolve two permitted independent upstream reviewer families
outside the manager's family. Preserve every budget and role restriction; supervised
output is not an independent verdict. Carry authorized work through verification and
report actual models, supported capabilities, tests and precise remaining gaps.
```

For each native leaf, pass the selected current model and its supported effort explicitly; record requested versus observed settings. Use the [review protocol](review-protocol.md#avoid-unnecessary-review-work) to preserve verdicts and finding dispositions across compaction.
