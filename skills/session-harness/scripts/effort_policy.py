"""Reasoning preference shared by runtime selection and profile installation."""
import os
import re
import stat
from pathlib import Path

DEFAULT = "high"
ENV = "SESSION_HARNESS_DEFAULT_EFFORT"
RELATIVE_PATH = ".config/session-harness/default-effort"
CODEX_MODEL_PATH = ".config/session-harness/default-codex-model"


def preference(home=None):
    # Explicit homes ignore the caller environment during installation.
    if home is None and ENV in os.environ:
        value = os.environ[ENV]
    else:
        path = (Path.home() if home is None else Path(home)) / RELATIVE_PATH
        try:
            if path.is_symlink():
                raise ValueError("Default effort preference must be a regular file")
            fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
            with os.fdopen(fd, "rb") as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size > 64:
                    raise ValueError("Default effort preference must be a small regular file")
                value = stream.read(65).decode("utf-8").strip()
        except FileNotFoundError:
            return DEFAULT
        except (OSError, UnicodeError) as error:
            raise ValueError("Cannot read default effort preference") from error
    if value not in {"low", "medium", "high"}:
        raise ValueError("Default effort must be low, medium or high; repair " + RELATIVE_PATH + " or " + ENV)
    return value


def codex_model_preference(home=None):
    path = (Path.home() if home is None else Path(home)) / CODEX_MODEL_PATH
    try:
        if path.is_symlink():
            raise ValueError("Codex model preference must be a regular file")
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > 128:
                raise ValueError("Codex model preference must be a small regular file")
            value = stream.read(129).decode("utf-8").strip()
    except FileNotFoundError:
        return None
    except (OSError, UnicodeError) as error:
        raise ValueError("Cannot read Codex model preference") from error
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", value):
        raise ValueError("Invalid Codex model preference")
    return value


def render_profile(content, provider, effort):
    text = content.decode("utf-8")
    prefix = 'model_reasoning_effort = ' if provider == "codex" else 'effort: '
    lines = text.splitlines(keepends=True)
    matches = [index for index, line in enumerate(lines) if line.startswith(prefix)]
    if len(matches) != 1:
        raise ValueError("Native profile must declare exactly one effort field")
    value = '"' + effort + '"' if provider == "codex" else effort
    lines[matches[0]] = prefix + value + "\n"
    return "".join(lines).encode("utf-8")
