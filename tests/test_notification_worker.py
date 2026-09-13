from datetime import datetime, timezone

from services.notification_worker import retry_at


def test_retry_wait_grows_and_is_bounded():
    now = datetime(2026, 9, 11, tzinfo=timezone.utc)

    assert retry_at(now, 1) > now
    assert retry_at(now, 6) <= now.replace(hour=23, minute=59)
