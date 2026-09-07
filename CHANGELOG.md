# Changelog

## Unreleased

- Carry the existing verified client repairs: account-bound Codex confirmation of
  disabled automatic credit top-up, sparse disabled Antigravity credit settings,
  and concrete current Claude catalog selection. No paid fallback is enabled.

- Add explicitly enabled automatic immutable stable updates on macOS and Linux,
  with configurable cadence, scheduler status, newer-version comparison and disable.
- Coordinate idle activation with an account-wide maintenance reservation; retain
  locks on ambiguous failures and provide explicit stopped-updater recovery.
- Verify local overlays and managed installation paths, preserve private policy
  and accounting, and roll back known profile changes after activation failure.
- Document optional shared-host activation hooks, scheduler delivery boundaries,
  release integrity and recovery. Existing installations remain opted out.

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

See README capability boundaries before enabling execution. Client instruction
compatibility alone does not establish a working quota or execution adapter.
