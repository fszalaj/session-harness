# Copy-paste onboarding prompt

Use with an assistant that can inspect local files. Identify the harness source and
target project if they are not already clear. This prompt delegates the canonical
[onboarding workflow](ONBOARDING.md); its conditional references preserve detail.

```text
Onboard session-harness globally and into this project using docs/ONBOARDING.md.
For an existing installation, inspect ai-session version and retain its selected
release unless I authorize an update or my existing automatic-update opt-in applies.
For a new installation, resolve the latest
published stable release once, verify its matching archive/checksum and keep that
version throughout. Never install maintained profiles from moving main.

Read the workflow and client instruction reference before changing files. Inspect
hosting/installed clients, dirty state, personal/project rules and relevant owned
skills. Preserve unique rules, scoped activation, user edits and standalone skills;
do not edit vendor-managed skills. Use a private registered personal-policy addendum.
Resolve conflicts from my current instructions or ask only when a decision is needed.
Use the existing project knowledge and code graph before structural/documentation work.

Carry out authorized reversible installation and project integration: test, preview,
apply, restart or report restart needs, then verify real client loading and idempotence.
Follow the Windows section when applicable. Keep one canonical policy/skills root per
scope, supported discovery aliases and project-owned customizations. Read the linked
instruction/platform guides for each detected client; local files do not configure cloud workers.

Walk me through ai-session configure interactively; never authorize services with
--yes on my behalf. Preserve settings, authentication, budgets, grants, history and
quota mode. Read the coordination and budget references for shared accounts and
policy choices; read API/money guidance only if paid use is requested. Do not enable
billing, top-up or paid fallback. Strict remains the default unless I choose observed mode.

Resolve models dynamically: strongest hosting-provider manager at highest standalone
effort, bounded native workers normally medium (low for gathering), two independent
other-provider plan reviews. Follow the selected skill's admission/context procedure;
missing capabilities or reviews are not success. Do not restart orchestration for leaf tasks.

Report version/provenance, preserved rules, changes, tests, actual loading, discovery
and protected execution separately, plus rollback and unresolved items. Read release
and recovery guides when updating, rolling back or considering optional maintenance;
check support in my selected release. Preserve existing maintenance opt-ins and
enable optional maintenance only if I choose it.
Keep account evidence and consumer paths private. After any authorized push, check
README/docs/skills and consumers against their selected release. Do not change
repository visibility, publish, or alter authentication as part of onboarding.
```
