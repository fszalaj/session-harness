# Session harness maintenance

Use `skills/session-harness/SKILL.md` for substantive work. This is a generic
coding-client and explicit API harness; do not add application-specific policies or data.
`CLAUDE.md` and `GEMINI.md` link here. Read only relevant references.

- Preserve user files and settings. Never commit credentials, quota ledgers, private
  review packets or account identifiers. State belongs under the user state directory.
- Write artifacts in English, follow the user's language for chat, and use plain hyphens. No assistant
  attribution. Keep comments short and explain tradeoffs in docs.
- Discover installed and account-visible models dynamically. Separate client/service,
  account quota pool and model provider. Never infer quota from token counts or models.
- Honor the daily quota budget and remaining reserve for managers, workers and reviews.
  Missing/stale/incomplete evidence is not zero usage or approval to dispatch.
- Follow enabled subscription balancing for bounded work; otherwise native same-provider
  workers are normal. Cross-provider review remains independent.
- Test limits, concurrency, reset handling, malformed telemetry, installation and real
  capability boundaries. Simulated tests are not evidence of provider guarantees.
- Existing application instructions outrank generic defaults. Keep updates explicit,
  reversible and reviewable; do not change authentication or paid-usage preferences.
- Ship usability changes with matching documentation. Rewrite affected user workflows,
  commands and recovery steps in README, onboarding, skills and release notes;
  remove obsolete guidance instead of only appending new sections. Verify examples
  against the implemented CLI and distinguish released behavior from development.

- Use the code graph before code and documentation changes; inspect measured blind
  spots in source. After every push, verify README/docs/skills and synchronize
  configured local consumers against their selected release; development commits
  do not automatically upgrade maintained profiles. Keep their paths and setup out of public commits.
- Query the committed graph with `python scripts/code_graph.py find SYMBOL`,
  `imports FILE` or `importers FILE`. Run `check` to verify freshness; after Python
  changes, stage new source paths and run `build`. See `docs/CODE-GRAPH.md`.
- API dispatch requires explicit money authorization; preserve liabilities after
  ambiguous failures. Never convert unknown credits or enable paid fallback.
