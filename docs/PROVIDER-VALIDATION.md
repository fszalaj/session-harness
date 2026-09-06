# Provider validation

Validate integrations against the installed client and current runtime metadata.
Native protocols and available controls can change. Keep account metadata, quota
snapshots, local paths, review packets and session results in private records.

## Deterministic checks

Run `python3 scripts/test.py` after source changes. The suite covers quota admission,
concurrent accounting, reset handling, malformed telemetry, process cleanup, model
selection, profile installation and license preservation. Budget tests exercise
calendar boundaries, pacing policies, grants and partial history. Provider fixtures
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
- PATH, vendor clients and localhost are trusted. Loopback ownership checks and
  self-signed TLS do not eliminate malicious local port rebinding.
- Synchronous metadata polling consumes the execution timeout. Parent sessions,
  other computers and detached processes are outside the owned-process boundary.
- Antigravity review restrictions do not provide full filesystem isolation. A
  visible tool registry does not establish tool use; inspect actual events.
- Copilot and Cursor inventory and instruction links do not establish protected
  execution. Other optional clients require their own supported adapters.
- Raw account replies and quota-probe output are discarded by the harness. Vendor
  clients can retain their normal private authentication and cache files.

Consult the [client adapter boundaries](../skills/session-harness/references/clients.md)
and [budget/reset sources](../skills/session-harness/references/budgets.md) when
validating an integration. Keep public documentation focused on reproducible
procedures and supported behavior.
