"""Deadline policy for prediction rounds."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class DeadlineMatch:
    id: int
    kickoff: datetime


def calculate_deadlines(matches: list[DeadlineMatch]) -> dict[int, datetime]:
    """Return the saving deadline for every match in one round.

    Matches one and two close at their own kickoff; every later match closes
    at the second chronological kickoff. ``id`` makes tied kickoffs stable.
    """
    ordered = sorted(matches, key=lambda match: (match.kickoff, match.id))
    if len(ordered) < 2:
        return {match.id: match.kickoff for match in ordered}

    second_kickoff = ordered[1].kickoff
    return {
        match.id: match.kickoff if index < 2 else second_kickoff
        for index, match in enumerate(ordered)
    }
