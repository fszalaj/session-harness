# Changelog

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
