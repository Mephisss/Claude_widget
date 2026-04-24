"""Call Claude's /api/oauth/usage endpoint for real session + weekly utilization."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from auth import TokenError, load_token

USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
BETA_HEADER = "oauth-2025-04-20"
TIMEOUT_S = 8


@dataclass(frozen=True, slots=True)
class WindowUsage:
    utilization_pct: float
    resets_at: datetime | None

    def time_left(self) -> str:
        if self.resets_at is None:
            return "--"
        delta = self.resets_at - datetime.now(timezone.utc)
        secs = int(delta.total_seconds())
        if secs <= 0:
            return "0m"
        d, rem = divmod(secs, 86400)
        h, rem = divmod(rem, 3600)
        m = rem // 60
        if d:
            return f"{d}d{h}h"
        if h:
            return f"{h}h{m:02d}m"
        return f"{m}m"


@dataclass(frozen=True, slots=True)
class LiveUsage:
    session: WindowUsage
    week: WindowUsage
    week_opus: WindowUsage | None
    week_sonnet: WindowUsage | None
    week_oauth_apps: WindowUsage | None
    week_cowork: WindowUsage | None
    fetched_at: datetime

    def per_model_breakdown(self) -> list[tuple[str, WindowUsage]]:
        return [(label, w) for label, w in (
            ("opus 7d", self.week_opus),
            ("sonnet 7d", self.week_sonnet),
            ("oauth apps 7d", self.week_oauth_apps),
            ("cowork 7d", self.week_cowork),
        ) if w is not None]


def _parse_window(d: dict[str, Any] | None) -> WindowUsage | None:
    if not isinstance(d, dict):
        return None
    util = d.get("utilization")
    if util is None:
        return None
    resets_str = d.get("resets_at")
    resets = None
    if isinstance(resets_str, str):
        try:
            resets = datetime.fromisoformat(resets_str.replace("Z", "+00:00"))
        except ValueError:
            resets = None
    return WindowUsage(utilization_pct=float(util), resets_at=resets)


class LiveUsageError(Exception):
    """Never carries the token."""


class RateLimited(LiveUsageError):
    def __init__(self, retry_after: int) -> None:
        super().__init__(f"rate-limited; retry in {retry_after}s")
        self.retry_after = retry_after


def fetch() -> LiveUsage:
    try:
        token = load_token()
    except TokenError as exc:
        raise LiveUsageError(f"auth: {exc}") from None

    req = urllib.request.Request(
        USAGE_URL,
        headers={
            "Authorization": token.header_value(),
            "anthropic-beta": BETA_HEADER,
            "Content-Type": "application/json",
            "User-Agent": "claude-widget/1.0",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        if e.code == 429:
            ra = e.headers.get("Retry-After") if e.headers else None
            try:
                retry_after = int(ra) if ra else 120
            except (TypeError, ValueError):
                retry_after = 120
            raise RateLimited(retry_after) from None
        # Strip request headers from any propagated error to avoid leaking the token.
        try:
            err_body = e.read().decode("utf-8", errors="replace")[:200]
        except Exception:
            err_body = ""
        raise LiveUsageError(f"http {e.code}: {err_body}") from None
    except urllib.error.URLError as e:
        raise LiveUsageError(f"network: {e.reason}") from None
    finally:
        del token

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise LiveUsageError("invalid JSON from server") from None

    session = _parse_window(payload.get("five_hour")) or WindowUsage(0.0, None)
    week = _parse_window(payload.get("seven_day")) or WindowUsage(0.0, None)
    return LiveUsage(
        session=session,
        week=week,
        week_opus=_parse_window(payload.get("seven_day_opus")),
        week_sonnet=_parse_window(payload.get("seven_day_sonnet")),
        week_oauth_apps=_parse_window(payload.get("seven_day_oauth_apps")),
        week_cowork=_parse_window(payload.get("seven_day_cowork")),
        fetched_at=datetime.now(timezone.utc),
    )


if __name__ == "__main__":
    try:
        u = fetch()
    except LiveUsageError as exc:
        print(f"ERR: {exc}")
    else:
        print(f"Session (5h): {u.session.utilization_pct:.0f}%  resets in {u.session.time_left()}")
        print(f"Week (7d):    {u.week.utilization_pct:.0f}%  resets in {u.week.time_left()}")
        if u.week_opus:
            print(f"  opus 7d:   {u.week_opus.utilization_pct:.0f}%")
        if u.week_sonnet:
            print(f"  sonnet 7d: {u.week_sonnet.utilization_pct:.0f}%")
