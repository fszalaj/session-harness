# Automatic release maintenance

**Available in v0.2.0.** Automatic updates default to off. Existing owner opt-ins
are preserved, including prerelease installations that can select the newer stable
release after publication, subject to normal cadence and activation checks.
Ordinary release checks do not follow a development branch. Automatic installation
selects only numerically newer
stable `major.minor.patch` releases from GitHub's immutable release endpoint.
Drafts, prereleases and malformed tags are rejected. No model call, provider
upgrade, credit purchase, billing change or quota refresh is involved.

## Choose and inspect the flag

After installing a release that includes this feature with the standard profile installer:

```sh
ai-session auto-update register
ai-session auto-update enable --interval-hours 24
ai-session auto-update status
ai-session auto-update run
ai-session auto-update disable
```

`register` downloads the installed version's published baseline and verifies the
current immutable snapshot and managed instruction, skill, role and launcher paths.
It records explicitly accepted skill-file overlays privately. Inspect local changes
before registering; registration is an owner maintenance action, not automatic
approval of unknown checkout code. `--base-source /absolute/path/to/release` accepts
an already verified matching release source. Personal instructions outside the
registered addendum, missing files and modified snapshots require reconciliation.

Automatic updates default to disabled, independently of inference setup. Enabling
requires an installed launcher, a registered installation and an authority with
maintenance protocol support. It requires an existing initialized coordination
ledger and never creates replacement accounting after a missing-file failure.
Enabling records the selected authority; changing that authority requires inspecting
the change and re-enabling automatic maintenance. Custom state locations retain
explicit updates. The interval is 1..168 hours; default 24. The hourly
scheduler invokes `run` with an absolute Python interpreter and stable launcher.
Successful checks defer the next network check by the selected interval. Busy
sessions, network errors and conflicts retry on the next hourly invocation. Status
shows enabled policy, loaded scheduler, last result and coordination state separately.
`run` obeys the same flag and cadence; it is not a force-update command.

macOS uses `~/Library/LaunchAgents/org.session-harness.auto-update.plist`, runs while
the owner is logged in and resumes checking after wake/login. Remote authorities
require an existing trusted, noninteractive SSH key and known host; the job has no
interactive shell or SSH-agent dependency. Missing connectivity defers or requires
recovery after an ambiguous activation; there is no local ledger fallback.

Linux uses `session-harness-auto-update.timer` and `.service` in the user systemd
directory. Inspect with `systemctl --user status session-harness-auto-update.timer`
and `journalctl --user -u session-harness-auto-update.service`. Enable user lingering
through an authorized administrator when updates must run after logout. Status
reports whether lingering is enabled. The product does not change lingering itself.
Automatic scheduling supports symlink profiles on macOS/Linux. Windows and
checked-copy profiles retain the explicit release updater.

Disabling persists the flag before unloading the owned scheduler. During a running
update it leaves the job alive to finish safely; repeat `disable` after completion
to unload it. A modified scheduler file is retained and reported. Disabling
auto-update does not disable session-harness or change provider automatic top-up.

## Activation, local overlays and shared hosts

The updater takes the local `update.lock`, downloads and verifies the release,
builds immutable candidates and previews managed changes. It then requests an
account-wide maintenance reservation from the configured authority. The authority
atomically proves that no protected native session owns any service before reserving
maintenance. New native admissions deny with `account_maintenance` until release.
Existing session rows are never expired or deleted by the updater.

Both local and authority owners are inspected. Leaked owners after a client crash
can keep an update deferred: verify termination and use the existing
`coordination release --service SERVICE --owner OWNER --confirm-stopped` procedure.
Do not delete a live owner for an upgrade. All managed authority entry points must
use the maintenance-aware runtime before enabling timers. Independently invoked old
snapshots, direct installers and unprotected clients remain outside this boundary.
Do not explicitly reconfigure a client's authority while its updater is running;
concurrent manual authority changes are outside this maintenance guarantee.

Installation preserves the registered private addendum, authentication, environment
setup, session capacity, budgets, grants and usage history. Registered skill-file
overlays are reapplied only if the incoming file still matches their base checksum.
An identical upstream fix absorbs an overlay; other changes defer for reconciliation.
Unknown installation changes are never silently discarded. Project-vendored skills
retain their own source pins and update workflow.

An optional `enable --activation-hook /absolute/path/to/trusted-executable` supports
an explicitly configured shared-host adapter. It runs as the owner without a shell,
with arguments `prepare|activate|rollback` and a private preview JSON path. Preparation
must validate and stage shared changes before personal activation. Activation occurs
inside maintenance; rollback must affect only that attempt's managed paths. Generic
hooks return 0 on completed success and 1 only on a confirmed completed failure.
Other exits (including 75 for an ambiguous outcome), signals and timeouts retain
maintenance for inspection. A wrapper must wait for its privileged child and
validate its completion reply; do not turn a child timeout into ordinary exit 1.
Generic
owner metadata cannot authorize privileged changes. A root helper must independently
validate published bytes and a root-owned override allowlist, copy into root-owned
staging before checking its bytes, and impose its own deadline. Keep shared host
configuration and scripts outside public product commits.

The old immutable updater runs the entire transaction; subsequent invocations use
the newly selected snapshot. Successful updates retain old snapshots and backups.
Restart clients to load current instructions. Automatic cleanup is not provided.
Profile files are individually replaced atomically, not as one filesystem transaction.
Known activation failures restore touched profile paths with compare-before-restore
checks and invoke shared rollback. A conflicting target or unknown outcome requires
inspection; rollback never restores a quota database.

## Recover an interrupted update

`manual_recovery_required`, `update_busy` and maintenance older than 15 minutes are
visible in status and scheduler output. No timer steals a maintenance token. A TTL
cannot prove that a slow or remotely disconnected installer stopped, so recovery
deliberately requires an operator. An ambiguous SSH acknowledgement can mean the
authority acquired maintenance even when the caller did not receive the reply.

1. Disable future attempts. Inspect the local scheduler process, privileged hook
   descendants where configured, `auto-update status`, authority status and the
   private `auto-update-runs` manifests. Confirm the updater actually stopped.
2. Restore or complete only the affected managed installation paths, using the
   recorded old and new snapshots. Verify personal and shared runtime agreement;
   preserve ledgers, login files and unrelated sessions.
3. On the authority, release only the recorded stopped maintenance owner:
   `ai-session coordination maintenance-release --owner TOKEN --confirm-stopped`.
4. Run `ai-session auto-update recover --confirm-stopped`. It requires maintenance
   to be absent, removes the empty local update lock and records recovery. Re-register
   only if a reviewed installation repair changed the recorded fingerprint.
5. Inspect status and re-enable the flag when the installation is consistent.

HTTPS, archive constraints, published SHA-256 checksums and GitHub's immutable
marker establish repository-origin integrity. They are not an independent publisher
signature. A simulated newer-release test validates installer behavior; an actual
automatic upgrade is reported only after a newer published release was installed.
