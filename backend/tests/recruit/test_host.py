"""기존(legacy) 모임 생성 시 개설자가 HOST로 자동 참여 등록되는지 확인한다.

recruit 테스트 공용 격리 SQLite(service fixture)를 사용하며 실제 DB에는 접속하지 않는다.
"""

from datetime import datetime, timedelta

from backend.app.models.post import Post
from backend.app.models.recruit import RecruitMember
from backend.app.schemas.recruit import RecruitCreate
from backend.app.services.recruit import create_recruit


def test_create_recruit_registers_creator_as_host(service):
    """모임을 만든 회원이 HOST·JOINED 상태로 등록되고 게시글 작성자와 같은지 확인한다."""
    db = service.repository.session
    now = datetime.now()
    data = RecruitCreate(
        title="[TEST] HOST 자동 등록",
        body="Discord Bot 연동 테스트",
        recruit_mode="short",
        category="study",
        capacity=5,
        deadline_at=now + timedelta(days=1),
        meeting_start=now + timedelta(days=2),
        meeting_end=now + timedelta(days=2, hours=2),
        study_topic="Python",
    )

    result = create_recruit(db, data, member_id=1)

    post = db.get(Post, result["post_id"])
    host = db.query(RecruitMember).filter_by(
        recruit_id=result["recruit_id"],
        member_id=1,
    ).first()

    assert host is not None, "HOST 등록 누락"
    assert host.role == "HOST", "HOST 역할 오류"
    assert host.status == "JOINED", "참여 상태 오류"
    assert post.author_member_id == host.member_id
