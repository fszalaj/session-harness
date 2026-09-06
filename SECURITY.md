# Security

Do not post credentials, private quota records, transcripts or account identifiers
in public issues or pull requests. For a sensitive report, use GitHub's private
vulnerability reporting feature if enabled. If it is unavailable, ask the
maintainer for a private reporting channel without disclosing the vulnerability.
No dedicated response SLA or supported-release window is promised at this stage.

Include the affected commit, a minimal reproduction with synthetic data and the
expected security boundary. Local reproduction must not expose other users' data
or require paid inference. If a credential was exposed, revoke or rotate it through
its provider; deleting a Git commit alone does not invalidate it.

Use vendor subscription authentication and keep private runtime state outside this
repository. Strict admission cannot authorize inference without enforceable bounds;
observed-threshold mode accepts possible overshoot and requires explicit local
opt-in. Processes started outside the harness are outside its process control.
