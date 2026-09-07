# Client adapters

Read when discovering capabilities, switching managers or launching external agents.
The Python helper uses the standard library. Its `discover` and default `launch`
commands inspect metadata only; `review` and `launch --execute` invoke a model.
For instruction filenames and skill paths, read the [client instruction map](instructions.md).
Keep Gemini CLI, Antigravity CLI and their IDE interfaces separate.

With the selected skill directory (containing `SKILL.md`) as your working directory:

```sh
python3 scripts/harness.py discover --session codex
python3 scripts/harness.py launch codex
python3 scripts/harness.py launch claude --execute
python3 scripts/harness.py review claude < /absolute/path/to/plan-packet.md
```

Reviews default to 180 seconds. POSIX input redirection is shown; in PowerShell,
pipe `Get-Content -Raw -Encoding utf8` from the packet file into the review command.
The execution commands still require setup, fresh admission and review isolation.

Use `--session claude` or `--session antigravity` when that client owns the current
conversation. Automatic environment/ancestor detection is a fallback. Presence of
another client's inherited variable is weaker than the actual hosting session.

## Codex

Native session model metadata and `model/list` from `codex app-server` expose models
and supported effort. The helper initializes the app server, paginates the catalog
and reads account type without returning account identifiers. It may report a
fresh local model cache as an explicitly labeled fallback; stale cache data does
not authorize a launch. API model availability does not prove Codex subscription
availability. `priority`/default rank needs current-generation filtering first.
Newest-generation eligibility is an owner preference, not proof that a newer tier
outperforms every older tier. A unique current candidate needs no within-generation
ranking; multiple candidates require explicit provider capability evidence. The
helper refuses ambiguous manager ranking. Worker suggestions still require the
manager to verify task fit, tools and cost.

Use the exact runtime-selected ID and highest supported standalone reasoning effort
for the manager. Codex `ultra` combines maximum reasoning with automatic delegation;
the **Unreleased** selector excludes `ultra`, selects `max` when advertised and owns delegation through its existing
review, role and budget rules. If `max` is unavailable, select the highest advertised
standalone level. Published v0.1.2 does not exclude `ultra` automatically; verify
its effective selection before launching. The catalog still reports `ultra`; it
is not a manager policy default.
See [Codex models](https://learn.chatgpt.com/docs/models). Claude's `max` is a reasoning
level, while `ultracode` is a separate orchestration mode. Effort labels across clients
do not establish equal cost or quality, and this choice makes no savings guarantee.
There is no invented `latest` alias. Launch resolves afresh; a persistent exact
`model` in `config.toml` will age. Native sessions opened without the launcher must
check their selected model before planning. Workers may use the same current model
at medium effort when all cheaper catalog alternatives are older generations.

The restricted review adapter uses a read-only sandbox, ignored user config/rules,
disabled execution/delegation/integrations and no project instructions. Residual
built-in tool names are not proof of an executable tool surface. Reject any actual
tool use; report requested and observed model identity separately.

Native custom agents can specify `model_reasoning_effort` without pinning a model;
they inherit the manager's model only when no configured default subagent model
takes precedence. Inspect effective settings metadata and explicitly pass the verified
current model when a default exists, or verify the observed inherited model.
Per-task selection can override this with
another verified current model. Full-history forks may prohibit explicit overrides;
use a fresh bounded task packet where the native tool requires it. A custom agent
file's configured effort overrides spawn effort: select a role with matching effort,
or use a built-in/fresh leaf worker with explicit supported effort for escalation.
Verify the effective effort instead of assuming a spawn argument won.

## Claude Code

**Unreleased:** prefer concrete account-selectable model IDs when the initialize
catalog supplies them. Select the newest numeric generation and advertised effort; do not let an
unresolved `best` or `sonnet` alias override a visible newer generation. When no
current cheaper concrete tier is available, use the selected current model at
medium effort for execution. A concrete review verifies the returned actual model;
alias-only catalogs remain explicitly unresolved until native session evidence.
Published v0.1.2 reports unresolved alias suggestions; verify the actual model
through native session evidence before accepting a manager or reviewer.

Use documented versionless aliases after checking the installed CLI and current
subscription coverage. `best` chooses the strongest eligible model; the actual
model must be recorded from runtime metadata. An initialize-only native control
request lists the current client's selectable options and supported effort, including
context suffixes. These are not proven account entitlements, and aliases remain
unresolved. Never build a model list from a subscription name. A smaller alias such as `sonnet` is
only a candidate: reject it if its resolved generation has been superseded under
the current policy, and use the current manager model at lower effort instead.

The manager launcher uses the highest reasoning effort supported by the CLI/model.
Persistent `effortLevel` does not accept every CLI effort value. Do not put a max
value in an unsupported setting or globally set `CLAUDE_CODE_EFFORT_LEVEL`: that
environment variable overrides worker effort. `ultracode` is an orchestration mode,
not an extra leaf reasoning tier. Installed Claude roles use the rolling `sonnet`
alias at low effort for the investigator and medium for the implementer and inherit the manager
model at high effort for the verifier. A per-invocation `model` overrides
frontmatter and `CLAUDE_CODE_SUBAGENT_MODEL_FORCE` overrides both; reject `sonnet`
when its resolved generation is superseded and pass the current flagship at medium.

For isolated subscription reviews use `--safe-mode`, an empty tools list, empty
strict MCP config, disabled slash commands and no session persistence. Safe mode
preserves authentication; `--bare` disables OAuth/keychain and is unsuitable here.
Accept evidence only after the result confirms a valid final response, actual
model and no tools/MCP. Do not configure automatic model or API-key fallbacks.
Existing account-side extra-usage settings remain the user's settings; a CLI
subscription check alone cannot promise a monetary cap.

Quota refresh sends only native `initialize` and `get_usage` control requests, with
`skip_behaviors: true`, so it does not ask a model or inspect past session behavior.
Global and model-scoped limits must agree with the complete native limit list.
Freshness requires native GET/200 diagnostics captured only in memory; an apparent
success containing cached quota is rejected. This protocol is capability-checked
against the installed client, not promised as a stable public SDK interface.

## Antigravity (Gemini review provider)

`agy models` provides the account-visible catalog; select a Gemini model for the
Google review. A newer Flash can supersede an older Pro: verify capability as well
as numeric release. Resolve both model suffix and supported effort. Never assume
Antigravity subscription credentials also authenticate Gemini CLI or a paid API.

Antigravity CLI documents workspace `AGENTS.md` and `GEMINI.md`; global rules
use `~/.gemini/GEMINI.md`. Workspace skills use `.agents/skills`. Shared and CLI
documentation disagree on the global skill path/layout; follow the instruction
map and verify actual discovery. Gemini CLI instead defaults to `GEMINI.md` and
has no harness execution adapter. `launch antigravity --execute` starts Antigravity;
changing a model in the IDE uses its supported picker, not this CLI command.

Headless mode normally permits workspace file writes. `--mode plan` and
`--disable-slash-commands` alone do not provide a no-tools review boundary. A
dedicated custom agent must be discovered in a new scratch project with
`--new-project`; otherwise the CLI can silently fall back to its default agent.
Use the terminal sandbox, explicit leaf instructions and bounded inline input.
The init event can list the global tool registry even for a custom agent; record
that limitation and reject actual tool/subagent events or an agent-fallback warning.
This is a constrained, monitored review, not a zero-tools or full-filesystem sandbox.
If the adapter reports unsupported controls, preserve the failure instead of using
an unrestricted CLI invocation.

Quota refresh starts an owned idle CLI and calls its process-scoped localhost
`RetrieveUserQuotaSummary` endpoint with `forceRefresh: true`. The CLI retains
subscription authentication; the helper neither reads credentials nor submits a
model prompt. Parse every grouped quota bucket at full precision. Require both
windows per group and reject HTTP failures or incomplete responses. Close only
the owned process group after reading.

Admission additionally reads the documented `useG1Credits` setting from the CLI
settings file. Published v0.1.2 requires explicit `false`; absent values block.
**Unreleased:** explicit `false` and the documented default for an absent file/key
disable paid fallback. The CLI [persists only nondefault settings](https://antigravity.google/docs/cli/settings),
so it can remove explicit `false` at startup. The harness distinguishes
`antigravity.cli_defaults` from `antigravity.cli_settings` evidence, rereads the
effective control at admission, and rejects enabled, unreadable or malformed settings.
It never writes that file or infers account balances from a local setting.
`metadata_status: reported` means the control was resolved; its source distinguishes
documented defaults from an explicit file value. An interrupted read denies that
check and can recover on the next successful refresh. If the CLI reports enabled
credits, subscription-only admission remains blocked until the owner explicitly
chooses to disable `useG1Credits`; never change the setting to bypass a stop.
When upgrading the CLI, revalidate its documented default and sparse persistence;
they are part of this adapter's provider contract.

A successful headless `/usage` response alone is insufficient: it can accompany
cache refresh failures. Require a successful forced backend response; reject errors
or incomplete quota. Loopback discovery uses process-owned socket inodes on Linux
and `lsof` on macOS. This native protocol is not a stable public SDK promise; verify
compatibility with the installed client.

## Optional clients and maintained skills

`harness.py inventory` checks a registry of executable names rather than guessing
which application a model belongs to. Copilot, Cursor, Kimi CLI, OpenCode, Aider,
Continue (`cn`), Ollama and Gemini CLI have separate records. Unknown clients and
model generations stay unknown. Grok/xAI, DeepSeek, Kimi/Moonshot and GLM/Z.ai names
identify model families, not a new subscription authentication route.

Claude's selectable options and Copilot/Cursor catalogs do not prove execution
entitlement. Ollama reports local installed models through forced loopback; it does
not authorize a remote subscription. Kimi, OpenCode, Aider, Continue and Gemini CLI
currently report executable presence without claiming a verified model catalog.
This registry does not promise protected launch/review support for those clients.

The optional catalog gap is explicit: OpenCode model discovery initializes plugins
and can migrate global configuration; verified isolation controls are needed per
installed version. Aider's list-models startup loads native credential environment
files before its metadata-only early return. Kimi public catalog listing requires
a provider ID and a verified JSON schema; raw configured-provider tables are excluded.
Do not turn a public catalog or an untested CLI command into account entitlement.
Sources: [OpenCode models](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/cli/cmd/models.ts),
[OpenCode flags](https://github.com/anomalyco/opencode/blob/dev/packages/core/src/flag/flag.ts),
[Aider startup](https://github.com/Aider-AI/aider/blob/main/aider/main.py),
[Kimi commands](https://www.kimi.com/code/docs/en/kimi-code-cli/reference/kimi-command.html),
[Continue CLI](https://continue-docs.mintlify.app/guides/cli),
and [Ollama local inventory](https://docs.ollama.com/api/tags).

Install only user-owned shared skills through profile links. Bundled system skills
and plugin caches remain managed by their installer, because direct cache edits
disappear on upgrades and can break discovery. Audit their routing when relevant
to a task; do not load an unrelated plugin's skill merely because it is installed.


## Explicit APIs and platform boundaries

For OpenAI, Anthropic, Gemini, xAI/Grok, DeepSeek, Kimi/Moonshot, Z.ai/GLM and
OpenRouter direct text requests, follow [API and money setup](api-and-spend.md).
These routes use separate credentials and explicit monetary caps. They do not
consume a native subscription allowance or become an automatic fallback.
Z.ai catalog discovery and generic model-specific API effort controls are unsupported.

Native quota discovery is separate from paid-credit eligibility. **Unreleased:**
Codex supports a private owner confirmation that automatic top-up is disabled for the authenticated
account, combined with fresh zero-credit evidence and unchanged quota admission.
Antigravity uses its verified disabled CLI setting/default. Claude requires disabled
paid controls. Enabled native paid credits remain unsupported. See
[API and spend](api-and-spend.md) for confirmation and revocation commands.

Core accounting/API and checked profile installation target Windows as well as
Unix. Native Antigravity Windows quota is unsupported; see [platforms](platforms.md).
