# Contributing

Read [README.md](README.md) and [AGENTS.md](AGENTS.md) before changing the harness.
Contributions intentionally submitted for inclusion are covered by the
[Apache License, Version 2.0](LICENSE), unless explicitly stated otherwise under
its contribution terms. Submit material you have the right to contribute and
preserve applicable third-party license and attribution notices.

Keep changes scoped and preserve user files, authentication and unrelated client
settings. Discover models at runtime. Separate observed telemetry from enforceable
provider guarantees, and keep strict admission as the default.

Query the [code graph](docs/CODE-GRAPH.md) before source or documentation changes.
After Python changes, stage new source paths and rebuild the committed snapshot;
CI verifies its contents against a fresh build. Untracked files are excluded.

Run `python3 scripts/test.py` and relevant focused checks. Tests must not require
paid inference or real account credentials. Explain the problem, resulting behavior,
validation and remaining capability limits in the pull request. Update relevant
documentation when changing installation, discovery or usage policy.

Do not include private usage records, account identifiers, transcripts or review
packets. Report security issues through [SECURITY.md](SECURITY.md).

Publish versioned releases using [the release procedure](docs/RELEASES.md). Keep
release tags immutable and consumers on explicit versions; do not rewrite a
published release to ship a correction.

## Documentation changes

Use [the documentation map](docs/README.md) to choose the existing home for a topic.
The README explains the project and entry path; onboarding contains installation
tasks; runtime references follow the CLI modules' responsibilities. Keep admission,
budgets, coordination and paid-use contracts in their corresponding references.
A new command should update its task guide and reference together.

Prefer links over repeated procedures. The installed skill ships as its own subtree,
so its runtime instructions and recovery links must resolve within that subtree.
Keep source-only contributor tasks in repository docs. Preserve linked headings
when moving detail, and mark behavior missing from the stable release as Unreleased.
Resolve releases and account models at runtime rather than embedding a current choice
in an evergreen command. Historical changelog entries retain exact versions.

Check commands against actual parser/help output and validate relative links. Read
each changed workflow from its stated working directory; shell placeholders must
be explained and must not accidentally redirect input. Documentation-only changes
do not require rebuilding an unchanged code graph or replacing installed profiles.

This structure follows [GitHub's README guidance](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-readmes)
and [Diataxis](https://diataxis.fr/start-here/): give readers a short entry point,
then distinguish task guidance from technical reference and explanation. The
[client instruction map](skills/session-harness/references/instructions.md) and
[design sources](skills/session-harness/references/sources.md) explain native loading
and context rules; a Markdown link alone does not make a client load another file.
