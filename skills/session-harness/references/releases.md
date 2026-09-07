# Configure and maintain an installed release

- `ai-session configure`: owner-guided setup, keeping existing choices as defaults.
  `setup` remains a compatible alias. Never complete `--yes` on the owner's behalf.
- `ai-session configure --status`: inspect authorized services without inference.
- `ai-session version`: inspect the running installed version and runtime path.
- `ai-session update --check`: compare against the latest immutable stable release.
- `ai-session update`: show the selected release and ask before installation.
- `ai-session update --version X.Y.Z --apply`: explicitly install or roll back to
  that published version. No automatic background update or moving branch.

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

The full release and bootstrap guide ships in `docs/RELEASES.md` in the source
checkout and published archive. Public release downloads need no GitHub token.
