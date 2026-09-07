# Configure and maintain an installed release

- `ai-session configure`: owner-guided setup, keeping existing choices as defaults.
  `setup` remains a compatible alias. Never complete `--yes` on the owner's behalf.
- `ai-session configure --status`: inspect authorized services without inference.
- `ai-session version`: inspect the running installed version and runtime path.
- `ai-session update --check`: compare against the latest immutable stable release.
- `ai-session update`: show the selected release and ask before installation.
- `ai-session update --version X.Y.Z --apply`: explicitly install or roll back to
  that published version. No moving branch.
- Development `ai-session auto-update register`, `enable --interval-hours 24`,
  `status`, `run` and `disable`: explicitly enabled macOS/Linux background updates.
  This feature is not in published v0.1.2. Registration accepts reviewed local
  skill overlays against a verified published baseline. New releases install only
  while the configured authority has no protected sessions and holds maintenance;
  conflicts defer. Windows and checked-copy installations retain explicit updates.
  Linux logout delivery requires user lingering; a Mac LaunchAgent requires login.
  No billing, automatic credit top-up, authentication or accounting changes occur.

Updates preserve the registered private Markdown addendum, setup, budgets, grants,
quota history and unrelated settings. Keep the addendum at its registered path;
a missing file blocks installation. Reconcile changed managed instructions or copies
before updating. Do not edit immutable snapshots directly. Restart clients after an
update and keep an existing task on one selected runtime until its handoff.

Most projects reference the shared installed skill. A repository that explicitly
selects a vendored skill remains on that copy: global updates do not modify project
files. Check that consumer's documented source pin and update procedure separately.
After each upstream push, check docs, skills and configured consumers against their
selected release; development commits do not silently become installed releases.

Updates verify published asset checksums over HTTPS and require GitHub's immutable
release marker. This is repository-origin integrity, not an independent publisher
signature. Private state records installation metadata and backups. `update.lock`
prevents concurrent updater runs; after a crash, verify that no updater is running
before removing that directory and retrying. Do not update during another installer
run or remove quota ownership/locks as part of release recovery.

Automatic maintenance can retain its token and update lock after an ambiguous
failure. Status exposes the owner and marks maintenance older than 15 minutes for
attention. Inspect processes and managed backups, restore or complete only profile
changes, then explicitly release the stopped maintenance owner with `coordination
maintenance-release --owner TOKEN --confirm-stopped`. `auto-update recover
--confirm-stopped` clears the empty local update lock only after maintenance is
absent. Never restore accounting. The source archive's `docs/AUTO-UPDATE.md` gives
the full scheduler, shared activation hook and crash-recovery contract.

The full release and bootstrap guide ships in `docs/RELEASES.md` in the source
checkout and published archive. Public release downloads need no GitHub token.
