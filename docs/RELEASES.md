# Releases and updates

Use a published version for maintained installations. `main` is development code;
installing a checkout is an explicit development choice. Version 0.x is still evolving:
read release notes before upgrading. Published tags and assets are immutable. A fix
gets a new version, including during initial development.

## Everyday use

```sh
ai-session configure
ai-session configure --status
ai-session version
ai-session update --check
ai-session update
ai-session update --version 0.1.1 --apply
```

Configuration is guided: Enter keeps current settings and the final prompt confirms
the changes. `setup` remains an alias. Installation and updating do not authorize
inference. Native routes need configured services and fresh quota; APIs additionally
need a configured monthly money allowance. Calendar changes do not erase daily
consumption. Existing ledger timezone cannot be changed through setup because its
history is dated in that timezone.

`update` shows the release before asking to install it. In a noninteractive terminal
it only reports the command to apply. Scripts must name an exact `--version` with
`--apply`; `--check` never installs. The same command selects an older release for
rollback. A missing release, download failure, invalid archive or checksum mismatch
stops before installation. Updates need HTTPS access to GitHub; public downloads
need no GitHub token. They make no model calls.

Release archives include a committed-source manifest, installer, generic profile,
skill, documentation, license and contributor code graph. SHA-256 checksums and
GitHub's asset digest, when supplied, are verified before extraction. The updater
requires GitHub's immutable release marker. These checks establish integrity against
the published repository assets; they are not an independent publisher signature.
For an additional attestation check, use
[`gh release verify` and `gh release verify-asset`](https://docs.github.com/en/code-security/how-tos/secure-your-supply-chain/secure-your-dependencies/verify-release-integrity).

## Preserve personal policy and project rules

First reconcile existing instructions using [onboarding](ONBOARDING.md). Save unique
personal rules in a private Markdown file outside the public repository:

```sh
python3 scripts/install-agent-profile.py --launcher --personal-policy /absolute/path/to/personal.md
python3 scripts/install-agent-profile.py --launcher --personal-policy /absolute/path/to/personal.md --apply
```

The installer appends the file to the generic personal policy and remembers its
location. Every update and rollback reuses it. Keep lengthy environment notes in
private on-demand references linked by that addendum. Do not edit an immutable
installed snapshot. A missing registered addendum or modified managed copy blocks
replacement until reconciled. The update leaves setup authorization, the quota and
money ledgers, grants, history and unrelated client settings intact. Reverting code
does not restore an old ledger or undo spending. Future incompatible state migrations
must document supported rollback boundaries; v0.1.0 introduces no destructive migration.

Projects normally keep one canonical `AGENTS.md`, supported client aliases, and a
short reference to `~/.agents/skills/session-harness/SKILL.md`. They share the installed
release and need no source-copy update. A project that explicitly vendors a customized
skill keeps its own source pin and review process. `ai-session update` does not change
those files or enforce project-specific version selection. Report runtime drift instead
of claiming that every project has upgraded.

On Windows, updates retain the explicitly selected checked-copy mode. The installed
PowerShell launcher requires PowerShell 7.3+; Python can run `ai-session.py` directly.
On macOS/Linux, the launcher uses the Python interpreter selected during installation.
Restart clients after an update. Active sessions keep their already-selected runtime.
Claude hook installation is separate and idempotent; review and apply a hook refresh
when release notes require it. Updates do not rewrite unrelated settings or hooks.

## Recovery

Installer previews and private backups describe replaced files. A failed download
leaves the installed release intact; installation failures report their error and
retain backups for inspection. File replacement is individually atomic, not an
all-files transaction. Stop concurrent installers, inspect the manifest, then rerun
the selected version or restore only the affected instruction links. Never restore
an old quota database to undo an update.

`update.lock` under the private state directory excludes another updater. After a
crash, confirm that no updater is running before removing that directory. It is
unrelated to quota locks and session ownership. Keep old immutable snapshots for
running sessions and recovery; automatic cleanup is deliberately absent.

## Maintainer publication

1. Update `skills/session-harness/VERSION`, release notes and the relevant README,
   onboarding, profile and skill instructions. Query the code graph before edits.
2. Stage new Python paths and rebuild the committed graph. Run the portable suite
   and inspect Linux, macOS and Windows CI. Test a release install in an isolated
   home, including private-policy preservation and accounting-safe rollback.
3. Commit the reviewed source. Build from that commit into a private directory:
   `python3 scripts/release.py --ref HEAD --output /absolute/path/outside/checkout`.
   The builder reads Git objects, never untracked files or dirty working-tree content.
4. Enable repository release immutability. Create a draft for a new `vX.Y.Z` tag,
   attach `session-harness-X.Y.Z.zip` and `SHA256SUMS`, verify both and publish.
   GitHub recommends [attaching assets before publication](https://docs.github.com/en/code-security/concepts/supply-chain-security/immutable-releases).
5. Check release metadata and download/install the public artifact. After each push,
   check README/docs/skills and configured consumers. Upgrade consumers explicitly
   to the published release; keep their paths and state in private records.

Never move or reuse a published tag, rewrite release history, include private setup
in an artifact, or silently upgrade consumers to an unreleased branch.
