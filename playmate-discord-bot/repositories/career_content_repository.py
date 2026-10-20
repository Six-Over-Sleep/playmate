"""취업 소식 콘텐츠 저장소 경계.

취업 카테고리의 DB/API가 아직 없어서 SQL은 작성하지 않는다. 취업 담당자 스키마가 나오면
CareerContentRepository를 구현하는 클래스를 추가하고 bot.py에서 바꿔 끼우면 된다.
그 전까지는 UnconnectedCareerContentRepository(항상 빈 결과)를 쓴다.
"""
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

JOB_POSTING = "JOB_POSTING"        # 채용공고: 신규 즉시 + 마감 D-3 / D-1 13:00 재노출
INTERVIEW_REVIEW = "INTERVIEW_REVIEW"  # 면접후기: 신규 1회
PASS_SPEC = "PASS_SPEC"            # 합격스펙: 신규 1회
NEWS = "NEWS"                      # 뉴스: 신규 1회
CAREER_KIND_LABELS = {
    JOB_POSTING: "채용공고",
    INTERVIEW_REVIEW: "면접후기",
    PASS_SPEC: "합격스펙",
    NEWS: "뉴스",
}


@dataclass(frozen=True)
class CareerContent:
    content_id: int
    kind: str
    title: str
    created_at: datetime
    deadline: date | None = None  # 채용공고 마감일 (다른 종류는 None)
    summary: str | None = None


class CareerContentRepository(Protocol):
    connected: bool

    def list_new_contents(self, since: datetime) -> list[CareerContent]:
        """since 이후 새로 등록된 취업 콘텐츠."""
        ...

    def list_job_postings_due(self, deadlines: list[date]) -> list[CareerContent]:
        """마감일이 deadlines 중 하나인 채용공고."""
        ...


class UnconnectedCareerContentRepository:
    """취업 스키마 연결 전 기본 구현. 항상 빈 결과를 돌려준다."""

    connected = False

    def list_new_contents(self, since: datetime) -> list[CareerContent]:
        return []

    def list_job_postings_due(self, deadlines: list[date]) -> list[CareerContent]:
        return []
