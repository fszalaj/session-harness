# Harness design sources

Recheck client behavior against installed help/runtime metadata when upgrading. These pages justify the design; they are not a pinned model list.

- [Anthropic: orchestrator/workers and parallel review](https://www.anthropic.com/engineering/building-effective-agents)
  supports a manager that decomposes tasks and combines independently obtained evidence.
- [Anthropic: long-running harnesses](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)
  supports incremental checkpoints, durable progress and concrete validation.
- [Anthropic: application harness design](https://www.anthropic.com/engineering/harness-design-long-running-apps)
  supports separating generation from evaluation and adapting scaffolding as models improve.
- [Codex instructions](https://developers.openai.com/codex/guides/agents-md),
  [skills](https://developers.openai.com/codex/skills),
  [subagents](https://developers.openai.com/codex/subagents) and
  [app-server model/list](https://developers.openai.com/codex/app-server)
  document shared instruction discovery, symlinked skills, per-agent model/effort and runtime catalogs.
- [Claude memory](https://code.claude.com/docs/en/memory),
  [skills](https://code.claude.com/docs/en/skills),
  [model configuration](https://code.claude.com/docs/en/model-config) and
  [subagents](https://code.claude.com/docs/en/sub-agents)
  document concise instructions, lazy skill context, rolling aliases and effort precedence.
- [Claude subscription coverage](https://support.claude.com/en/articles/15424964-claude-fable-models-on-your-plan)
  distinguishes included model quota from account-side extra usage. Check the actual plan.
- [Antigravity practices](https://www.antigravity.google/docs/cli/best-practices/),
  [skills](https://www.antigravity.google/docs/skills/),
  [rules](https://www.antigravity.google/docs/rules-workflows/),
  [models](https://www.antigravity.google/docs/models/),
  [headless](https://www.antigravity.google/docs/cli/headless/) and
  [subagents](https://www.antigravity.google/docs/subagents/)
  document shared paths, account catalogs, default headless permissions and custom tool lists.

The selected combination is a task-specific design judgment. No source establishes
one universally best framework or proves that more agents always improve results.

## Quotas and multi-model clients

- [Codex account RPC](https://raw.githubusercontent.com/openai/codex/main/codex-rs/app-server/README.md)
  documents account/rateLimits/read, sparse updates and usage token buckets; token
  activity is not quota percentage. Reset credits are never consumed automatically.
- [Claude statusline](https://code.claude.com/docs/en/statusline) and
  [hooks](https://code.claude.com/docs/en/hooks) distinguish post-response quota
  telemetry from prompt blocking; native hook timeout can fail open.
- [Antigravity usage](https://www.antigravity.google/docs/cli/commands/usage),
  [statusline](https://www.antigravity.google/docs/cli/statusline/) and
  [hooks](https://antigravity.google/docs/hooks/) describe interactive refresh,
  quota reports and termination after invocation.
- [CodexBar's native Antigravity protocol notes](https://github.com/steipete/CodexBar/blob/main/docs/antigravity.md)
  informed discovery of the CLI-owned localhost quota endpoint. The force-refresh
  adapter requests fresh backend metadata and rejects failed or incomplete responses.
  This harness implements its own bounded reader; no CodexBar code or OAuth fallback
  is bundled.
- [Copilot SDK usage](https://docs.github.com/en/copilot/how-tos/copilot-sdk/features/usage-and-billing),
  [SDK client source](https://raw.githubusercontent.com/github/copilot-sdk/main/python/copilot/client.py) and
  [session caps](https://docs.github.com/en/copilot/how-tos/copilot-cli/use-copilot-cli/set-session-limit)
  document metadata-only models/quota reads and explicitly soft credit caps.
- [Copilot instructions](https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-custom-instructions)
  and [skills](https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-skills)
  document personal/project discovery and combined instruction sources.
- [Cursor CLI](https://cursor.com/docs/cli/reference/parameters),
  [skills](https://cursor.com/docs/skills), [rules](https://cursor.com/docs/rules) and
  [hooks](https://cursor.com/docs/hooks) document model listing and integrations.
  Local discovery does not imply a personal quota endpoint or remote installation.

## Instruction filenames and client interfaces

The [adaptive budget reference](budgets.md) records current weekly/monthly reset
research, native timestamp precedence and the daily-allocation algorithm. The
[optional client reference](clients.md#optional-clients-and-maintained-skills)
separates advertised model families from installed clients and account entitlements,
with the concrete metadata limitations for OpenCode, Aider and Kimi. Neither a
model API catalog nor an installation is subscription execution evidence.

The [client instruction map](instructions.md) records the separate contracts for
Gemini CLI, Antigravity CLI/IDE, Copilot CLI/IDE/GitHub and Cursor local/cloud use,
with direct official sources. It also records the conflicting Antigravity global
skill paths; a documented rule filename does not establish symlink, skill or
execution compatibility. Verify loaded content in the actual interface.


## Context continuity

- [Claude best practices](https://code.claude.com/docs/en/best-practices) and
  [cost guidance](https://code.claude.com/docs/en/costs) describe managing context,
  compaction and starting fresh for unrelated tasks.
- [Codex CLI slash commands](https://developers.openai.com/codex/cli/slash-commands)
  and [app-server protocol](https://developers.openai.com/codex/app-server/)
  describe native compaction controls. Availability depends on the actual client.

The harness's 60/75/85 percent thresholds are advisory workflow choices. These
sources do not establish universal quota savings from compaction or a new session.
Markdown instructions cannot perform either operation automatically.
