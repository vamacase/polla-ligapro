from datetime import datetime, timezone

from core.deadlines import DeadlineMatch, calculate_deadlines


UTC = timezone.utc


def test_first_two_keep_own_kickoff_and_rest_use_second():
    matches = [
        DeadlineMatch(3, datetime(2026, 9, 13, 0, 0, tzinfo=UTC)),
        DeadlineMatch(1, datetime(2026, 9, 12, 19, 0, tzinfo=UTC)),
        DeadlineMatch(2, datetime(2026, 9, 12, 21, 30, tzinfo=UTC)),
        DeadlineMatch(4, datetime(2026, 9, 13, 18, 0, tzinfo=UTC)),
    ]

    deadlines = calculate_deadlines(matches)

    assert deadlines[1] == matches[1].kickoff
    assert deadlines[2] == matches[2].kickoff
    assert deadlines[3] == matches[2].kickoff
    assert deadlines[4] == matches[2].kickoff


def test_one_match_uses_its_own_kickoff():
    only = DeadlineMatch(1, datetime(2026, 9, 12, 19, 0, tzinfo=UTC))

    assert calculate_deadlines([only]) == {1: only.kickoff}


def test_empty_match_list_has_no_deadlines():
    assert calculate_deadlines([]) == {}
