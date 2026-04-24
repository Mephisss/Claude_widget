"""Read the Claude Code OAuth token with strict isolation.

The token never touches disk via this widget, never appears in repr/str/logs/
exceptions, and is re-read on every call so refreshes are picked up automatically.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

DEFAULT_CREDENTIALS_PATH = Path(os.path.expanduser("~/.claude/.credentials.json"))
CREDENTIALS_PATH: Path = DEFAULT_CREDENTIALS_PATH
MACOS_KEYCHAIN_SERVICE = "Claude Code-credentials"


def set_credentials_path(p: str | os.PathLike | None) -> None:
    global CREDENTIALS_PATH
    if p:
        CREDENTIALS_PATH = Path(os.path.expanduser(str(p)))
    else:
        CREDENTIALS_PATH = DEFAULT_CREDENTIALS_PATH


class TokenError(Exception):
    """Message never includes token bytes."""


class _SecretToken:
    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        object.__setattr__(self, "_value", value)

    def __repr__(self) -> str:
        return "<SecretToken redacted>"

    def __str__(self) -> str:
        return "<SecretToken redacted>"

    def __setattr__(self, *_a, **_kw):
        raise AttributeError("immutable")

    def header_value(self) -> str:
        return f"Bearer {self._value}"


def _read_credentials_file() -> str | None:
    try:
        return CREDENTIALS_PATH.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return None


def _read_macos_keychain() -> str | None:
    if sys.platform != "darwin":
        return None
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", MACOS_KEYCHAIN_SERVICE, "-w"],
            capture_output=True, text=True, timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    out = result.stdout.strip()
    return out or None


def load_token() -> _SecretToken:
    raw = _read_credentials_file()
    if raw is None:
        raw = _read_macos_keychain()
    if raw is None:
        raise TokenError("credentials not found — run `claude` once to log in")

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        raise TokenError("credentials are not valid JSON") from None
    finally:
        raw = "x" * len(raw)
        del raw

    creds = data.get("claudeAiOauth") if isinstance(data, dict) else None
    if not isinstance(creds, dict):
        creds = data if isinstance(data, dict) else {}

    tok = creds.get("accessToken")
    exp = creds.get("expiresAt")
    if not tok or not isinstance(tok, str):
        raise TokenError("no accessToken in credentials")

    # Don't fail on expired access tokens — Claude Code refreshes lazily and the
    # API itself will reject the request if the token is truly stale.
    _ = exp

    secret = _SecretToken(tok)
    tok = "x" * len(tok)
    del tok, data, creds
    return secret
