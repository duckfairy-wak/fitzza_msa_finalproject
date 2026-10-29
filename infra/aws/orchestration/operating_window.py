"""Run-window check for pipeline Jobs on the scheduled, shared EKS node."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

# Korea has no daylight saving time, so a fixed offset avoids depending on tzdata in Lambda.
KST = timezone(timedelta(hours=9), "Asia/Seoul")
DAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
# The node starts at 09:00 and stops at 18:00 on weekdays; leave time for readiness and the run itself.
DEFAULT_RUN_WINDOW = "MON-FRI 09:30-16:00"
_WINDOW = re.compile(
    r"(MON|TUE|WED|THU|FRI|SAT|SUN)-(MON|TUE|WED|THU|FRI|SAT|SUN) "
    r"([01]\d|2[0-3]):([0-5]\d)-([01]\d|2[0-3]):([0-5]\d)"
)


def parse_window(spec: str) -> tuple[frozenset[int], int, int]:
    """Return weekdays and start/end minutes for a window such as 'MON-FRI 09:30-16:00' (Asia/Seoul)."""
    match = _WINDOW.fullmatch(spec.strip())
    if not match:
        raise ValueError("run window must look like 'MON-FRI 09:30-16:00' in Asia/Seoul time")
    first, last = DAYS.index(match[1]), DAYS.index(match[2])
    start = int(match[3]) * 60 + int(match[4])
    end = int(match[5]) * 60 + int(match[6])
    if last < first or end <= start:
        raise ValueError("run window days and times must be increasing")
    return frozenset(range(first, last + 1)), start, end


def is_within_window(now: datetime, spec: str = DEFAULT_RUN_WINDOW) -> bool:
    """Whether a new pipeline Job may be created at the given aware datetime."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    days, start, end = parse_window(spec)
    local = now.astimezone(KST)
    minutes = local.hour * 60 + local.minute
    return local.weekday() in days and start <= minutes < end
