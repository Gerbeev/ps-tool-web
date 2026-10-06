from datetime import datetime, timedelta

from app.time_utils import execution_time_seconds, format_duration_hms


def test_execution_time_seconds_and_hms_format():
    start = datetime(2026, 10, 2, 1, 2, 3)
    end = start + timedelta(hours=1, minutes=10, seconds=33)
    assert execution_time_seconds(start, end) == 4233
    assert format_duration_hms(4233) == "01:10:33"


def test_duration_format_does_not_wrap_after_24_hours_and_supports_signed_delta():
    assert format_duration_hms(27 * 3600 + 61) == "27:01:01"
    assert format_duration_hms(600, signed=True) == "+00:10:00"
    assert format_duration_hms(-90, signed=True) == "-00:01:30"
    assert execution_time_seconds(datetime(2026, 1, 2), datetime(2026, 1, 1)) is None
