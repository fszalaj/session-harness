# Provider validation

Validate integrations against the installed client and current runtime metadata.
Native protocols and available controls can change. Keep account metadata, quota
snapshots, local paths, review packets and session results in private records.

## Deterministic checks

Run `python3 scripts/test.py` after source changes. The suite covers quota admission,
concurrent accounting, reset handling, malformed telemetry, process cleanup, model
selection, profile installation and license preservation. Budget tests exercise
calendar boundaries, pacing policies, grants, partial history,
missing resets with verified native durations, frozen allowances across session
restarts, actual recovery and subsequent reset reporting. Money tests cover
concurrent reservations, exact decimal rounding, crashes, duplicate IDs, month
rollover and reconciliation. API fixtures cover eight protocol routes and malformed
cost/output data. Windows checks exercise jobs, IPC, ACLs and checked-copy installs. Provider fixtures
are synthetic and do not establish account access or successful model execution.
Run platform-specific process and socket checks on their target operating system;
a skipped test provides no evidence for that platform.

## Runtime checks

Discover installed clients and inspect the provenance of model and quota metadata.
Distinguish executable presence, advertised catalogs, selectable options and
verified execution. Resolve model IDs and supported effort at runtime.
Metadata discovery alone does not authorize inference.

Quota reads must establish freshness and include every relevant pool. Cached
responses, missing fields, failed backend reads and ambiguous reset metadata must
not create admission headroom. Test zero-remaining and malformed responses with
synthetic fixtures; record any live validation separately in private notes.

For an authorized review, check the adapter's isolation controls before dispatch.
Confirm a valid final response, the actual model when exposed, and the absence of
prohibited tool or subagent activity. Preserve literal reviewer verdicts and
reconcile material findings. Successful process completion is insufficient proof
of a successful review.

## Capability boundaries

- Strict mode refuses inference without enforceable request-cost bounds. Observed
  mode requires explicit local opt-in and accepts possible in-flight overshoot.
- Unknown schemas, incomplete pools, failed freshness checks and backend errors
  deny admission or stop execution owned by the harness.
- Configured executable directories, vendor clients and localhost are trusted.
  Executable lookup excludes the current directory and rejects arbitrary batch shims. Loopback ownership checks and
  self-signed TLS do not eliminate malicious local port rebinding.
- Synchronous metadata polling consumes the execution timeout. Parent sessions,
  unconfigured computers and detached processes are outside the owned-process boundary.
  Configured SSH clients share the authority ledger with separate owners up to its capacity;
  account matching and existing SSH trust must be verified during private setup.
- Antigravity review restrictions do not provide full filesystem isolation. A
  visible tool registry does not establish tool use; inspect actual events.
- Native paid-credit eligibility is a separate gate. Published v0.1.2 blocks the
  protected Codex route and requires explicit `useG1Credits: false` for Antigravity.
  **Unreleased:** Codex adds account-bound owner confirmation plus fresh zero-credit
  evidence; Antigravity also accepts its documented disabled default when the
  file/key is absent. Enabled, unreadable or malformed controls still block.
  Claude requires explicit disabled controls without unknown purchase eligibility.
  A configured money budget does not waive these gates. See the
  [credit contract](../skills/session-harness/references/api-and-spend.md#native-extra-credits).
- Explicit API text routes require separate monetary authorization. Deterministic
  fixtures do not establish live access, provider-enforced cost limits or support
  for model-specific effort. Z.ai catalog discovery remains unavailable.
- Copilot and Cursor inventory and instruction links do not establish protected
  execution. Other optional clients require their own supported adapters.
- Raw account replies and quota-probe output are discarded by the harness. Vendor
  clients can retain their normal private authentication and cache files.

Consult the [client adapter boundaries](../skills/session-harness/references/clients.md)
and [budget/reset sources](../skills/session-harness/references/budgets.md) when
validating an integration. Keep public documentation focused on reproducible
procedures and supported behavior.

Standard public GitHub Actions jobs run deterministic contracts on Linux, macOS
and Windows without credentials or paid requests. Check the actual run results;
workflow presence alone proves no platform. Missing live provider validation may
be published as an explicit limitation; never label it a successful test.

## Efficiency and coordination regression checks

Exercise simultaneous owners, reconnects, authority failure, missing setup and
explicit recovery after confirmed process termination. No expiry may silently
release an uncertain owner. Claude hook denial must stop the supported event with
`continue: false`, never ask a model to retry. Preserve unrelated settings when
installing hooks, and verify a second preview is empty. Test cap decreases, small
topups and calendar cycles after daily exhaustion; they must not refund debit.
Test concurrent backend observations from separate processes against one daily cap,
live capacity increases, refusal of unsafe decreases and preservation of explicit
existing limits. Distinct account authorities must remain independent. Capacity
errors must identify concurrency rather than claiming quota exhaustion.

Review protocols default to medium effort and 16 KiB packets. Confirm native effort
from the actual catalog; fixtures cannot establish the current cheapest tier.
On published v0.1.2, Antigravity clients that omit a false setting when persisting
sparse configuration remain blocked. The Unreleased adapter distinguishes a
documented absent default from invalid settings; test both provenance and denial.
