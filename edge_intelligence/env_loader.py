"""Load simple KEY=VALUE local settings without evaluating shell content."""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import MutableMapping, Optional

_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _parse_value(raw: str) -> str:
    value = raw.strip()
    if not value:
        return ""
    if value[0] in ("'", '"'):
        quote = value[0]
        chars = []
        escaped = False
        closing = None
        for index, char in enumerate(value[1:], start=1):
            if escaped:
                chars.append({"n": "\n", "r": "\r", "t": "\t"}.get(char, char))
                escaped = False
            elif char == "\\" and quote == '"':
                escaped = True
            elif char == quote:
                closing = index
                break
            else:
                chars.append(char)
        if closing is not None:
            tail = value[closing + 1:].strip()
            if not tail or tail.startswith("#"):
                return "".join(chars)
    # Unquoted values may have a trailing comment when separated by whitespace.
    return re.split(r"\s+#", value, maxsplit=1)[0].rstrip()


def load_env_file(path: Path, environ: Optional[MutableMapping[str, str]] = None) -> int:
    """Load values from a local env file without overriding process variables.

    This intentionally supports the project's KEY=VALUE convention only. It
    does not expand variables or execute shell syntax from the file.
    Returns the number of variables loaded, never their names or values.
    """
    target = environ if environ is not None else os.environ
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except FileNotFoundError:
        return 0
    except OSError:
        return 0

    loaded = 0
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped[7:].lstrip()
        if "=" not in stripped:
            continue
        key, raw_value = stripped.split("=", 1)
        key = key.strip()
        if not _KEY.fullmatch(key) or key in target:
            continue
        target[key] = _parse_value(raw_value)
        loaded += 1
    return loaded
