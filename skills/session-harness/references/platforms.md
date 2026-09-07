# Runtime platforms

Core Python accounting, explicit API routes and profile installation target
Linux, macOS and Windows with Python 3.11+. Windows also needs `tzdata` because
its system does not provide the IANA database consumed by `zoneinfo`.

From the root of a verified release archive:

```powershell
python -m pip install -r requirements-windows.txt
python scripts/test.py
python scripts/install-agent-profile.py --launcher --link-mode copy
python scripts/install-agent-profile.py --launcher --link-mode copy --apply
```

Use symlink mode when supported. Explicit copy mode installs checked views from
one canonical source and records their hashes. An edited managed copy is a conflict,
not permission to overwrite it. Backups and immutable snapshots remain private.
Do not edit release snapshots directly; update maintained source and reinstall.

The Windows launcher uses PowerShell 7.3+ standard native argument passing. For
other shells, invoke the installed `ai-session.py` with Python directly. No batch
wrapper interpolates prompts through `cmd.exe`. Trusted executable lookup excludes
the current directory; arbitrary `.cmd` files are rejected. Recognized standard
npm shims are normalized to a direct Node/script argument vector.

Windows subprocesses enter a kill-on-close Job Object through a gated helper
before a target can spawn descendants. Breakaway is not enabled. Failed job
assignment stops execution with an actionable error; there is no unsupervised
fallback. Bounded threaded pipe transport replaces unsupported Windows pipe
selectors. Private state checks reject reparse paths and apply a user-specific ACL.

Native Windows Antigravity quota ownership/terminal protocols are unsupported.
A generic Windows subprocess test does not establish a native client's quota,
model or paid-credit controls. All native admission requirements still apply;
see [client adapter boundaries](clients.md#explicit-apis-and-platform-boundaries).

**Unreleased (absent from v0.1.2):** the portable settings reader distinguishes an
absent Antigravity settings file
from an invalid parent path. Windows can report both as `FileNotFoundError`, so
the reader validates the nearest existing ancestor before using the disabled
default. A regular file in the parent path or a permission error remains invalid.

CI uses standard GitHub-hosted Linux, macOS and Windows runners. Windows-specific
checks exercise job descendants, parent death, pipe bounds, argument forwarding,
copy drift and private state controls. POSIX terminal/socket tests run on their
applicable platforms. A skipped test is not evidence for another operating system.
Provider fixtures contain no account credentials and make no paid inference calls.

References: [Python selectors](https://docs.python.org/3/library/selectors.html),
[zoneinfo](https://docs.python.org/3/library/zoneinfo.html),
[Windows Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects),
[GitHub-hosted runners](https://docs.github.com/en/actions/reference/runners/github-hosted-runners).
