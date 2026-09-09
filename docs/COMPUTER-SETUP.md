# Use your own computer

The harness can run on a laptop or desktop. A shared server is optional. Choose
where the AI client runs and whose provider accounts it uses before installing.

| Setup | Where work runs | Accounts and accounting |
| --- | --- | --- |
| Personal computer, personal accounts | Locally | Sign in through each native client; one local quota authority |
| Same account on several computers | On each configured computer | One trusted authority for the account; authenticate each client through supported provider flows |
| Team service through SSH or a remote editor | On the managed server | Administrator-managed accounts and authority; no provider credentials copied to the laptop |

A repository, shared folder or harness installation does not grant access to
another person's subscription. For a team service that keeps authentication on
the server, use its existing remote terminal or editor integration. Generic
installation does not turn a laptop client into a proxy for that service.

## Install locally with your own accounts

1. Install Python 3.11+, Git and the native clients you already use. Sign in with
   your own accounts through their supported flows. Inventory alone does not
   authorize purchasing or installing additional clients.
2. Follow [release selection and checksum verification](ONBOARDING.md#1-select-and-verify-the-release).
   Keep the selected release and its provenance; do not install from `main`.
3. From the verified extracted release, preview and apply the profile:

   ```sh
   python3 scripts/test.py
   python3 scripts/install-agent-profile.py --launcher
   python3 scripts/install-agent-profile.py --launcher --apply
   ai-session configure
   ```

   Preserve unique instructions with the same optional
   `--personal-policy /absolute/path/to/personal.md` in both installer commands.
   The owner completes configuration interactively, selecting authorized services
   and quota policy. Existing accounting and settings remain in place.
4. Restart affected clients, open your local project and inspect the installation:

   ```sh
   ai-session version
   ai-session configure --status
   ai-session inventory
   ai-session coordination status
   ai-session budget
   ai-session usage check codex
   ```

   Replace `codex` with the configured client. A successful inventory is separate
   from admitted execution. Missing quota, authentication or paid-use evidence
   must be resolved before starting useful work with `ai-session codex` or
   `ai-session claude`.

On Windows, use `python`, install `requirements-windows.txt` first, and add
`--link-mode copy` to both installer commands if symlinks are unavailable.
Use PowerShell 7.3+ or the Python launcher. See the
[platform limits](../skills/session-harness/references/platforms.md), including
unsupported native Windows Antigravity quota/terminal supervision.

For an existing installation, select this release with
`ai-session update --version 0.2.1 --apply`, then restart affected clients.

## Share one account across computers

Set up one already trusted authority with the same authorized provider accounts.
On each participating client, after verifying SSH authentication and the host key:

```sh
ai-session coordination set --authority user@host
ai-session coordination status
ai-session usage check codex
```

Replace `user@host` with the authority assigned to that account. Do not copy
tokens, browser sessions or SQLite files between computers. Authenticate native
clients separately through supported flows. Every participating session must use
the same authority; independent local ledgers cannot coordinate one subscription.
An unavailable authority blocks admission, without a local fallback. The current
generic configuration selects one authority for all native services, so do not
mix unrelated personal and company accounts behind that authority. See
[coordination](../skills/session-harness/references/coordination.md).

For team accounts whose credentials must remain server-side, open your own remote
checkout in an SSH terminal or a remote editor, then run the server's existing
`ai-session` command there. The laptop is the interface; execution remains remote.
Local native execution against team accounts needs a separately verified,
administrator-managed authentication and quota adapter.

## Save a repeatable setup recipe

Store the following nonsecret record in an access-appropriate document. Each user
fills in their own choices; it is a recipe, not an importable credential bundle.

```text
Operating system and client versions:
Selected release tag and verified archive checksum:
Execution location: personal computer / managed remote host
Account ownership: personal / administrator-managed team access
Authorized native services:
Quota authority: local / approved SSH alias
Quota mode, timezone, workdays, reset cutoff and reserve:
Session capacity:
Private personal-policy file location:
Manager: xhigh when advertised; otherwise highest supported level below max
Max exception: explicit task-level selection for an extremely difficult task
Verification: version, configure --status, coordination status, usage check
```

Record actual policy from the configured authority, not example budgets. Keep
account identifiers, host details and local paths in a private copy where needed.
Never upload credentials, entire client settings directories or quota databases
to a shared document or repository. Each person authorizes their own setup.

## Manager effort and release availability

Use the strongest eligible model of the hosting provider at Extra High (`xhigh`).
When unavailable, use the highest advertised reasoning level below `max`.
Use `max` only for an extremely difficult task, selected explicitly in the native
model/effort control, and return to the default afterwards. Worker effort remains
medium, or low for gathering. Do not set a global worker effort override.

Since v0.2.1, the launcher implements this manager default and excludes `max` and
`ultra` from default selection. Editing Markdown or a configuration file does not
switch an already-running conversation. There is no generic launcher `--effort` flag.

Recurring free API pools and mixed native/free routing are not included in v0.2.1.
Paid API use separately requires explicit monetary authorization. No setup path
enables billing, automatic top-up or paid fallback.
