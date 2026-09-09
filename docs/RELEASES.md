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
```

Configuration is guided: Enter keeps current settings and the final prompt confirms
the changes. `setup` remains an alias. Installation and updating do not authorize
inference. Native routes need configured services and fresh quota; APIs additionally
need a configured monthly money allowance. Calendar changes do not erase daily
consumption. Existing ledger timezone cannot be changed through setup because its
history is dated in that timezone.

`update` shows the release before asking to install it. In a noninteractive terminal
it only reports the command to apply. Scripts must name an exact `--version` with
`--apply`; `--check` never installs. For an exact install or rollback, replace
`VERSION` below with the published numeric version you have chosen after reading
its release notes:

```sh
ai-session update --version VERSION --apply
```

For v0.2.1, use `ai-session update --version 0.2.1 --apply`, then restart affected
clients. The manager defaults to advertised `xhigh`, otherwise the highest
supported level below `max`; `max` and `ultra` are excluded from default selection.
Existing conversations keep their selected model and runtime until restarted.

The same command selects an older release for rollback. A missing release, download
failure, invalid archive or checksum mismatch stops before installation. Since
v0.2.0, optional `auto-update` commands provide an
explicitly enabled background path; see [automatic maintenance](AUTO-UPDATE.md).
Updates need HTTPS access to GitHub; public downloads
need no GitHub token. They make no model calls.

Release archives include a committed-source manifest, installer, generic profile,
skill, documentation, license and contributor code graph. SHA-256 checksums and
GitHub's asset digest, when supplied, are verified before extraction. The updater
requires GitHub's immutable release marker. These checks establish integrity against
the published repository assets; they are not an independent publisher signature.
For an additional attestation check, use
[`gh release verify` and `gh release verify-asset`](https://docs.github.com/en/code-security/how-tos/secure-your-supply-chain/secure-your-dependencies/verify-release-integrity).

## Preserve personal policy and project rules

Run the installer examples below from the root of a verified release archive.
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

### Claude reports account_session_busy

This is a session-capacity stop. Check `ai-session coordination status`, then close
an unused session or change capacity on the authority with
`ai-session coordination set --max-sessions 8`. Starting with v0.1.2, increasing
capacity works while sessions are active. Updates preserve an existing limit of one;
they do not silently migrate it. All sessions continue to share the same quota budget.
For crashed owners, confirm termination before release. See
[session coordination](../skills/session-harness/references/coordination.md).

### Claude stops because a reset is unknown

If a hook reports `unknown_adaptive_reset` and `budget_anchor_missing`, inspect
the installed version and pool status from a terminal:

```sh
ai-session version
ai-session update --check
ai-session budget claude
```

Starting with v0.1.1, a verified native long-window duration supports conservative
daily pacing even when the reset timestamp is absent. Update older installations
with `ai-session update`, restart Claude to reload instructions, and retry the
message. A project with a vendored skill must update its selected copy too.

If both the reset and native duration are unknown, the pool still needs reliable
metadata or an explicitly chosen fixed/window policy. A genuine daily-limit stop
is separate. Do not disable the hook, delete accounting or assume a missing reset
means unlimited usage. See [budget controls](../skills/session-harness/references/budgets.md).

### Installation and updater recovery

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

For changes that affect setup, everyday commands, limits, updates or recovery,
review the affected workflow from a new user's perspective before publication:

- Follow the code graph to the implemented command and read its actual options.
- Rewrite the matching README, onboarding prompt/guide and skill references;
  replace obsolete commands and defaults rather than accumulating conflicting advice.
- Include the entry command, required configuration, expected result and recovery
  from relevant errors. Keep private environments and account evidence out of examples.
- Check that examples work in supported shells and retain documented platform limits.
- Explain upgrade or restart requirements in release notes. After the push, verify
  docs and configured consumers against their selected versions; documentation-only
  changes do not require replacing an unchanged installed runtime.

For a runtime release:

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
