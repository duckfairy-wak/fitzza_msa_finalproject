from datetime import datetime, timezone

import pytest

from infra.aws.orchestration.operating_window import DEFAULT_RUN_WINDOW, is_within_window, parse_window


def utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (utc(2026, 10, 29, 0, 30), True),    # Thu 09:30 KST, first allowed minute
        (utc(2026, 10, 29, 0, 29), False),   # Thu 09:29 KST, node may not be ready
        (utc(2026, 10, 29, 6, 59), True),    # Thu 15:59 KST
        (utc(2026, 10, 29, 7, 0), False),    # Thu 16:00 KST, too close to the 18:00 shutdown
        (utc(2026, 10, 28, 18, 0), False),   # Thu 03:00 KST, node is stopped
        (utc(2026, 10, 31, 1, 0), False),    # Sat 10:00 KST
    ],
)
def test_default_window_follows_weekday_node_hours(now, expected):
    assert is_within_window(now, DEFAULT_RUN_WINDOW) is expected


def test_custom_window_for_a_dedicated_node():
    assert is_within_window(utc(2026, 10, 31, 18, 0), "MON-SUN 00:00-23:59") is True  # Sun 03:00 KST


@pytest.mark.parametrize("spec", ["", "MON-FRI 9:30-16:00", "FRI-MON 09:30-16:00", "MON-FRI 16:00-09:30", "weekdays"])
def test_invalid_window_is_rejected(spec):
    with pytest.raises(ValueError):
        parse_window(spec)


def test_naive_datetime_is_rejected():
    with pytest.raises(ValueError):
        is_within_window(datetime(2026, 10, 29, 10, 0))
