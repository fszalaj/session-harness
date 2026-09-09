# Copy-paste onboarding prompt

Use with an assistant that can inspect local files. Identify the harness source and
target project if they are not already clear. This prompt delegates the canonical
[onboarding workflow](ONBOARDING.md); its conditional references preserve detail.

```text
Onboard session-harness globally and into the current project. If no project is
open, ask me which directory to use. The official release source is
https://github.com/fszalaj/session-harness/releases/latest.
For an existing installation, inspect ai-session version and retain its selected
release unless I authorize an update or my existing automatic-update opt-in applies.
Read its onboarding workflow from the retained source, or retrieve that same
verified release archive if the source is absent.
For a new installation, resolve the latest
published stable release once. Download session-harness-VERSION.zip and SHA256SUMS
from that same release, verify the archive, and extract it. VERSION is the selected
release number. Read docs/ONBOARDING.md inside that verified extracted release and
follow it throughout. Never install maintained profiles from moving main.

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

Walk me through ai-session onboard PROVIDER for one provider, or ai-session configure
for full account settings, interactively; never authorize services with
--yes on my behalf. Preserve settings, authentication, budgets, grants, history and
quota mode. Read the coordination and budget references for shared accounts and
policy choices; read API/money guidance only if paid use is requested. Do not enable
billing, top-up or paid fallback. Strict remains the default unless I choose observed mode.

After installation and at each new manager session, follow the selected skill's
references/session-start.md and its reusable task prompt. Discover current configured
routes, model catalogs, role permissions, budgets, skills and project knowledge access.
Do not use a remembered client list or fixed reviewer pair. Separate upstream model
family from the client and billing service. Select only verified reviewer-capable
routes; preserve restrictions and report missing coverage after checking alternatives.

Resolve models dynamically: newest available generation within each family before
cost optimization, strongest hosting-provider manager at Extra High (xhigh),
or the highest advertised level below max if unavailable. Use max only by explicit
task-level selection for an extremely difficult task. Verify older releases' native
effort control; instructions cannot change a running session. Use bounded native
workers normally at medium (low for gathering), with two independent
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
