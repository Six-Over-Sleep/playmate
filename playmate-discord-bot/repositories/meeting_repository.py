"""Storage boundary for meeting lifecycle state.

This implementation retains the original empty test fixtures in memory.
There is no PostgreSQL connection, and state is lost when the process stops.
Keys are Discord category IDs; recruit_id remains the backend meeting identity.
Replace InMemoryMeetingRepository with an implementation of MeetingRepository
when persistent storage is introduced. Message content is never accepted here.

Methods are synchronous to preserve the original in-memory execution order.
An asynchronous database adapter will require an explicit interface migration.
"""
from typing import Any, Protocol

Meeting = dict[str, Any]


class MeetingRepository(Protocol):
    def list_one_time_meetings(self) -> list[Meeting]: ...
    def list_ongoing_meetings(self) -> list[tuple[int, Meeting]]: ...
    def get_ongoing_meeting(self, category_id: int) -> Meeting | None: ...
    def save_one_time_meeting(self, meeting: Meeting) -> None: ...
    def save_ongoing_meeting(self, category_id: int, meeting: Meeting) -> None: ...


class InMemoryMeetingRepository:
    def __init__(
        self,
        one_time_meetings: list[Meeting] | None = None,
        ongoing_meetings: dict[int, Meeting] | None = None,
    ):
        # Keep references, including explicitly supplied empty fixtures.
        self._one_time_meetings = (
            one_time_meetings if one_time_meetings is not None else []
        )
        self._ongoing_meetings = (
            ongoing_meetings if ongoing_meetings is not None else {}
        )

    def list_one_time_meetings(self) -> list[Meeting]:
        return self._one_time_meetings

    def list_ongoing_meetings(self) -> list[tuple[int, Meeting]]:
        return list(self._ongoing_meetings.items())

    def get_ongoing_meeting(self, category_id: int) -> Meeting | None:
        return self._ongoing_meetings.get(category_id)

    def save_one_time_meeting(self, meeting: Meeting) -> None:
        # Records returned by list_one_time_meetings are live references.
        # The explicit save boundary allows future adapters to persist updates.
        pass

    def save_ongoing_meeting(self, category_id: int, meeting: Meeting) -> None:
        self._ongoing_meetings[category_id] = meeting
