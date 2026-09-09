# Changelog

## Unreleased - 0.3.0

- Add Copilot native launch and supervised text execution with finite chat-pool
  checks, actual model/usage receipts and retained unresolved jobs. Auto routing
  is not an independent provider-family review.
- Add bounded local Ollama execution with loopback-only transport, residency
  checks, task deduplication and explicit recovery. Add explicit Meta and Ollama
  Cloud API transports behind existing monetary admission.
- Install a global Cursor rule pointing to shared instructions. Preserve the
  Extra High manager default introduced in 0.2.1. Cursor execution remains pending
  a verified account quota and execution adapter.

- Add explicitly configured recurring free account pools, shared request identities,
  conservative token/credit reservations, manual reconciliation and fixed-provider
  HTTPS dispatch. Preserve legacy OpenRouter exact-zero guards, native budgets and
  monetary accounting. Free-account evidence expires and never invents a refill.

- Report interactive worker pacing denials with their own status and bounded reason
  codes instead of a CLI schema error. Identify uncertain receipts without retrying
  work or releasing its journal; preserve quota supervision and cleanup failures.
- Clarify coding-model access choices across native subscriptions, direct APIs and
  gateways, including account setup and the evidence needed before claiming deployment.

- Route native `usage check` through the configured authority even without a model
  argument. Keep local status/refresh diagnostic, deny unsupported protected clients
  explicitly, and preserve quotas and paid-credit guards on every admitted response.
- Recognize Claude's signed-out auth-status exit as `auth_required` without exposing
  native account output or confusing sign-in with quota exhaustion.

- Add a reviewed coding profile for Kimi, GLM, DeepSeek, MiniMax and Qwen through
  OpenRouter. Intersect expiring evidence with fresh catalog capabilities and prices;
  reject unreviewed variants and returned-model mismatches. Keep supervised text
  execution behind existing API setup and monetary admission, separate from native
  subscription balancing. Account setup and secret delivery remain private.

- Add opt-in native subscription balancing and editable model/role supervision,
  with shared accounting and separate API monetary authorization.
- Explain interactive quota stops after restoring the terminal display. Preserve
  the original stop reason when process or terminal cleanup fails; report sanitized
  cleanup stages and retain the protected owner when process termination is unknown.
- Keep redirected output free of diagnostic terminal escapes and preserve machine
  JSON failures. Refuse to confirm cleanup when the owned child cannot be reaped.
- Read native Claude alias resolutions and use verified current Sonnet workers
  without changing the manager tier. Preserve native model-pool scope and common
  accounting; admit current alternatives after a model-specific stop.
- Track protected Claude model changes and resume an exact conversation once after
  a verified scoped stop and successful cleanup. Preserve common limits, role
  restrictions, legacy all-pool behavior and separate billing authorization.
- Re-evaluate a concurrent newer quota observation once without refreshing or
  writing accounting again. Preserve policy, completeness and final reservation guards.

## 0.2.1

- Default managers to advertised Extra High (`xhigh`), otherwise the highest
  supported level below `max`. Exclude `max` and `ultra` from default selection;
  reserve explicit `max` for extremely difficult tasks through native controls.
- Document personal-computer setup, shared-account boundaries and the supported
  native, inventory-only and explicit API routes. Recurring free API pools and
  mixed native/free routing are not included in this release.
- Update with `ai-session update --version 0.2.1 --apply`, then restart affected
  clients. Existing sessions retain their selected model and runtime.

## 0.2.0

- Add account-bound Codex confirmation of disabled automatic credit top-up and
  recognize the documented disabled default in sparse Antigravity credit settings.
  No paid fallback is enabled.
- Select concrete current Claude catalog models when advertised and verify returned
  review identity; exclude automatic orchestration from manager effort selection.
- Add explicitly enabled automatic immutable stable updates on macOS and Linux,
  with configurable cadence, scheduler status, newer-version comparison and disable.
- Coordinate idle activation with an account-wide maintenance reservation; retain
  locks on ambiguous failures and provide explicit stopped-updater recovery.
- Verify local overlays and managed installation paths, preserve private policy
  and accounting, and roll back known profile changes after activation failure.
- Document optional shared-host activation hooks, scheduler delivery boundaries,
  release integrity and recovery. Automatic updates default to off; existing
  opt-in settings are preserved, including on prerelease installations that can
  select the newer stable release after publication.
- Streamline the README, onboarding prompt and documentation navigation around
  verified release installation, preserved personal rules and guided configuration.
- Restart affected clients after installation or update to load the new instructions.

## 0.1.2

- Separate configurable session capacity from shared quota, with four sessions for
  new configurations and preservation of existing explicit choices. The wizard and
  capacity-only CLI support 1..32; increases preserve active owners and accounting.
- Explain occupied capacity in Claude hooks and show actual authority occupancy.
- Serialize native backend observations across processes to prevent out-of-order
  accounting. Failed new admissions release their own slot without touching others.
- Update onboarding, team/account guidance and recovery instructions together.

## 0.1.1

- Fix adaptive admission for native weekly pools that report usage but no reset
  timestamp, including Claude model-scoped pools after balance recovery.
- Pace over a verified full native window until a reset is reported, retaining
  daily consumption, frozen allowances, grants, reserves and work calendars.
- Distinguish conservative pacing from actual reset forecasts in budget status.
  Unknown window lengths, stale metadata and strict admission still block.

## 0.1.0

- First versioned release of the shared coding-session harness.
- Guided `ai-session configure`, release inspection, checksum-verified updates and
  exact-version rollback preserving private policy and accounting.
- Dynamic client/model discovery, bounded roles, shared quota authority, deterministic
  Claude hooks, adaptive calendar budgets and explicitly authorized API money caps.
- Portable profile installation, checked-copy support for Windows, onboarding,
  contributor code graph and deterministic tests without paid inference.

See [client capability boundaries](skills/session-harness/references/clients.md) before enabling execution. Client instruction
compatibility alone does not establish a working quota or execution adapter.
