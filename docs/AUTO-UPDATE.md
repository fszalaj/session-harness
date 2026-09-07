# Automatic release maintenance

**Available in v0.2.0.** Automatic updates default to off and require owner opt-in;
they never follow a development branch. Existing opt-in settings are preserved,
including prerelease installations that can select the newer stable release after
publication, subject to normal cadence and activation checks.

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
