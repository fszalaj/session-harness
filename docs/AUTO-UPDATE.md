# Automatic release maintenance

**Unreleased - absent from published v0.1.2.** Existing installations retain their
selected release. This feature requires an explicitly authorized development
installation and separate owner opt-in; it never follows a development branch.

The complete [automatic maintenance reference](../skills/session-harness/references/automatic-maintenance.md)
ships inside the installed skill, so recovery does not depend on a source checkout.

## Choose and inspect the flag

See [registration, enablement, cadence and scheduler status](../skills/session-harness/references/automatic-maintenance.md#choose-and-inspect-the-flag).
Defaults remain disabled. macOS/Linux symlink profiles support scheduling; Windows
and checked-copy profiles retain [explicit updates](RELEASES.md#everyday-use).

## Activation, local overlays and shared hosts

See [idle activation, overlays and shared-host hooks](../skills/session-harness/references/automatic-maintenance.md#activation-local-overlays-and-shared-hosts).
Maintenance preserves private policy and accounting; conflicts require reconciliation.

## Recover an interrupted update

Follow the [stopped-updater recovery procedure](../skills/session-harness/references/automatic-maintenance.md#recover-an-interrupted-update).
Confirm process termination before releasing maintenance; never restore accounting.
