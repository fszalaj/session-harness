# Instruction and skill entry points

Use the linked official documentation and identify the actual client,
interface, version and settings before consolidating files. A model name does not
identify the application loading its instructions. This is a compatibility map,
not a claim that every client has a working harness execution adapter.

## Instructions

| Client/interface | Project instructions | Personal instructions |
| --- | --- | --- |
| Codex | `AGENTS.md` and supported scoped overrides | `~/.codex/AGENTS.md` |
| Claude Code | `CLAUDE.md` or `.claude/CLAUDE.md`; supported imports and scoped rules | `~/.claude/CLAUDE.md` |
| Gemini CLI | Defaults to `GEMINI.md`; `context.fileName` can select `AGENTS.md` | Default `~/.gemini/GEMINI.md`; inspect configured filename |
| Antigravity CLI | Documents both workspace `AGENTS.md` and `GEMINI.md` | Documents `~/.gemini/GEMINI.md` |
| Antigravity IDE | Documents `.agents/rules/`, with legacy `.agent/rules/` | `~/.gemini/GEMINI.md` |
| Copilot CLI | `AGENTS.md`, `.github/copilot-instructions.md`, scoped instructions and other agent filenames | `~/.copilot/copilot-instructions.md`; modular personal instructions also supported |
| Copilot in IDEs / GitHub | Depends on feature; `.github/copilot-instructions.md` has broader coverage than `AGENTS.md` | Depends on interface; CLI profile files are not universal personal settings |
| Cursor editor / CLI | `AGENTS.md` and `.cursor/rules`; CLI also reads root `CLAUDE.md` | User Rules in Cursor UI; no documented universal `~/.cursor/AGENTS.md` |

Sources: [Codex instructions](https://developers.openai.com/codex/guides/agents-md),
[Claude memory](https://code.claude.com/docs/en/memory),
[Gemini CLI context](https://geminicli.com/docs/cli/gemini-md/),
[Antigravity CLI migration](https://antigravity.google/docs/cli/gcli-migration/),
[Antigravity rules](https://antigravity.google/docs/rules-workflows/),
[Copilot CLI instructions](https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-custom-instructions),
[Copilot feature matrix](https://docs.github.com/en/copilot/reference/custom-instructions-support),
[Cursor rules](https://cursor.com/docs/rules) and
[Cursor CLI rules](https://cursor.com/docs/cli/using#rules).

## Why keep GEMINI.md?

For default Gemini CLI, a verified `GEMINI.md -> AGENTS.md` link preserves its entry point
while sharing one source. Alternatively, explicitly configure
`{"context":{"fileName":"AGENTS.md"}}` in the appropriate Gemini CLI settings.
Inspect existing settings first: this affects context discovery beyond one alias.
A filename array is supported, but selecting both names can load duplicate content.
Use `/memory show` to inspect loaded context. This installer does not edit Gemini
CLI settings. These choices follow the [Gemini CLI context contract](https://geminicli.com/docs/cli/gemini-md/).

Antigravity CLI already documents `AGENTS.md`, so a project used only by that CLI
need not add another alias for discovery. Its global `~/.gemini/GEMINI.md` entry is
separate from a repository alias. The IDE rules page does not establish root
`AGENTS.md` discovery; verify the IDE's native rules instead of extending a CLI
claim to the editor. Antigravity authentication is not Gemini CLI authentication.

## Copilot and Cursor distinctions

Copilot CLI combines sources and documents deduplication of identical applicable
instruction content. `/instructions` shows enabled sources. This does not establish
symlink support or identical behavior in other Copilot features. For example,
GitHub Chat and some IDE review surfaces use repository-wide instructions while
VS Code Chat supports `AGENTS.md`. Inspect the current feature matrix before adding
`.github/copilot-instructions.md`; preserve its existing unique rules.

Cursor supports nested project `AGENTS.md`; its scoped rule metadata must retain
activation conditions. Global User Rules apply to Agent Chat, not every completion
or editing feature. A shared project file does not replace those personal UI rules.

## Skills are a separate discovery mechanism

`AGENTS.md` is policy; `SKILL.md` is a discoverable procedure. A client can read the
policy without finding the procedure or having quota, review and worker adapters.

- Gemini CLI discovers project/user `.agents/skills` and `.gemini/skills`; the shared
  skill installed under `~/.agents/skills` fits its documented global search path.
  See [Gemini CLI skills](https://geminicli.com/docs/cli/skills/).
- Cursor discovers `.agents/skills`, `.cursor/skills` and documented compatibility
  directories. Local skills are not automatically installed on remote workers.
  Personal Cloud Agent sync is a separate choice for `~/.cursor/skills`; do not
  infer it from a local symlink. See [Cursor skills](https://cursor.com/docs/skills).
- Antigravity's [shared skills page](https://antigravity.google/docs/skills/) documents
  project `.agents/skills` and global `~/.gemini/config/skills`. Its
  [CLI plugins page](https://antigravity.google/docs/cli/plugins/) instead names
  `~/.gemini/antigravity-cli/skills` and describes a different layout. The installer
  currently uses the shared-page path; verify the installed CLI's actual discovery
  before claiming its global skill loaded. Do not silently install both layouts.
- The existing profile also links Codex, Claude and Copilot skill directories.
  Other clients require their own documented paths and discovery evidence.

## Consolidation and verification

Prefer one canonical `AGENTS.md` per scope, native discovery and only necessary
compatibility aliases. Symlink support, import syntax and duplicate elimination
are separate client capabilities. A Markdown link is not necessarily an automatic
import. Verify actual loaded content, especially in GitHub or cloud integrations
that may read a Git symlink as its target text. Use supported imports or a generated
native view with a drift check when a verified link cannot serve that surface.

Preserve scoped rules and user settings. Check instruction loading, skill discovery,
model access and supervised execution separately. Gemini CLI has no harness
execution adapter; Copilot/Cursor execution remains unverified. New clients do not
become supported merely because they accept `AGENTS.md` or offer a familiar model.
