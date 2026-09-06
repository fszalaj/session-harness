# Session harness maintenance

Use `skills/session-harness/SKILL.md` for substantive work. This is a generic
subscription-client harness; do not add application-specific policies or data.
`CLAUDE.md` and `GEMINI.md` link here. Read only relevant references.

- Preserve user files and settings. Never commit credentials, quota ledgers, private
  review packets or account identifiers. State belongs under the user state directory.
- Write artifacts in English, follow the user's language for chat, and use plain hyphens. No assistant
  attribution. Keep comments short and explain tradeoffs in docs.
- Discover installed and account-visible models dynamically. Separate client/service,
  account quota pool and model provider. Never infer quota from token counts or models.
- Honor the daily quota budget and remaining reserve for managers, workers and reviews.
  Missing/stale/incomplete evidence is not zero usage or approval to dispatch.
- Native same-provider workers are normal. Cross-provider review remains independent.
- Test limits, concurrency, reset handling, malformed telemetry, installation and real
  capability boundaries. Simulated tests are not evidence of provider guarantees.
- Existing application instructions outrank generic defaults. Keep updates explicit,
  reversible and reviewable; do not change authentication or paid-usage preferences.
