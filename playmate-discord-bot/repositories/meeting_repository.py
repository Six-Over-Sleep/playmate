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
    def list_regular_meetings(self) -> list[tuple[int, Meeting]]: ...

    def get_regular_meeting(self, category_id: int) -> Meeting | None: ...

    def save_regular_meeting(
        self, category_id: int, meeting: Meeting
    ) -> None: ...


class InMemoryMeetingRepository:
    def __init__(
        self,
        regular_meetings: dict[int, Meeting] | None = None,
    ):
        self._regular_meetings = (
            regular_meetings if regular_meetings is not None else {}
        )


    def list_regular_meetings(self) -> list[tuple[int, Meeting]]:
        return list(self._regular_meetings.items())

    def get_regular_meeting(self, category_id: int) -> Meeting | None:
        return self._regular_meetings.get(category_id)

    def save_regular_meeting(
        self, category_id: int, meeting: Meeting
    ) -> None:
        self._regular_meetings[category_id] = meeting

