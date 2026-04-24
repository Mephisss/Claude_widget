"""Aggregate Claude Code token usage from local JSONL session logs."""
from __future__ import annotations

import json
import os
import time as _time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECTS_DIR = Path(os.path.expanduser("~/.claude/projects"))

SESSION_WINDOW = timedelta(hours=5)
WEEK_WINDOW = timedelta(days=7)
_CACHE_TTL_SECONDS = 30


@dataclass
class WindowStats:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    by_model: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    earliest: datetime | None = None
    latest: datetime | None = None

    @property
    def total_tokens(self) -> int:
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_creation_tokens
            + self.cache_read_tokens
        )

    @property
    def billable_tokens(self) -> int:
        return self.input_tokens + self.output_tokens + self.cache_creation_tokens


def _iter_assistant_records(since: datetime):
    if not PROJECTS_DIR.exists():
        return
    cutoff_ts = since.timestamp()
    for jsonl in PROJECTS_DIR.rglob("*.jsonl"):
        try:
            if jsonl.stat().st_mtime < cutoff_ts:
                continue
        except OSError:
            continue
        try:
            with jsonl.open("r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if rec.get("type") != "assistant":
                        continue
                    msg = rec.get("message") or {}
                    usage = msg.get("usage")
                    if not usage:
                        continue
                    ts_str = rec.get("timestamp")
                    if not ts_str:
                        continue
                    try:
                        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    except ValueError:
                        continue
                    if ts < since:
                        continue
                    yield ts, msg.get("model", "unknown"), usage
        except OSError:
            continue


def _accumulate(stats: WindowStats, ts: datetime, model: str, usage: dict) -> None:
    stats.input_tokens += int(usage.get("input_tokens") or 0)
    stats.output_tokens += int(usage.get("output_tokens") or 0)
    stats.cache_creation_tokens += int(usage.get("cache_creation_input_tokens") or 0)
    stats.cache_read_tokens += int(usage.get("cache_read_input_tokens") or 0)
    billable = (
        int(usage.get("input_tokens") or 0)
        + int(usage.get("output_tokens") or 0)
        + int(usage.get("cache_creation_input_tokens") or 0)
    )
    stats.by_model[model] += billable
    if stats.earliest is None or ts < stats.earliest:
        stats.earliest = ts
    if stats.latest is None or ts > stats.latest:
        stats.latest = ts


_cache: dict = {"computed_at": 0.0, "session": None, "week": None}


def collect() -> tuple[WindowStats, WindowStats]:
    """Return (session_stats, week_stats), memoized for 30s to avoid re-walking JSONL on every poll."""
    now_mono = _time.monotonic()
    if (now_mono - _cache["computed_at"] < _CACHE_TTL_SECONDS
            and _cache["session"] is not None):
        return _cache["session"], _cache["week"]

    now = datetime.now(timezone.utc)
    session_cut = now - SESSION_WINDOW
    week_cut = now - WEEK_WINDOW

    session = WindowStats()
    week = WindowStats()
    for ts, model, usage in _iter_assistant_records(week_cut):
        _accumulate(week, ts, model, usage)
        if ts >= session_cut:
            _accumulate(session, ts, model, usage)

    _cache["session"] = session
    _cache["week"] = week
    _cache["computed_at"] = now_mono
    return session, week


def short_model(model: str) -> str:
    if not model:
        return "?"
    m = model.lower()
    if "opus" in m:
        return "opus"
    if "sonnet" in m:
        return "sonnet"
    if "haiku" in m:
        return "haiku"
    return model.split("-")[0]


def fmt_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


if __name__ == "__main__":
    s, w = collect()
    print(f"Session (5h): {fmt_tokens(s.billable_tokens)} billable")
    for m, t in sorted(s.by_model.items(), key=lambda x: -x[1]):
        print(f"  {short_model(m)}: {fmt_tokens(t)}")
    print(f"Week (7d):    {fmt_tokens(w.billable_tokens)} billable")
    for m, t in sorted(w.by_model.items(), key=lambda x: -x[1]):
        print(f"  {short_model(m)}: {fmt_tokens(t)}")
