
import sys
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

sys.path.insert(0, "backend")

from backend.app.core.database import engine
from backend.app.models.member import Member
from backend.app.models.post import Post
from backend.app.models.recruit import RecruitMember
from backend.app.schemas.recruit import RecruitCreate
from backend.app.services.recruit import create_recruit




# 테스트용 모임 데이터
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

# 테스트용 회원 ID (DB에 존재하는 회원)
test_member_id = 1

# 실제 DB에 연결하지만 마지막에 전체 테스트 변경을 취소함
with engine.connect() as conn:
    transaction = conn.begin()

    try:
        with Session(
            bind=conn,
            join_transaction_mode="create_savepoint",
        ) as db:
            result = create_recruit(
                db, data, member_id=test_member_id
            )

            recruit_id = result["recruit_id"]

            post = db.get(Post, result["post_id"])

            host = db.query(RecruitMember).filter_by(
                recruit_id=recruit_id,
                member_id=test_member_id,
            ).first()

            print("생성 모임 ID:", recruit_id)
            print("게시글 작성자:", post.author_member_id)
            print("HOST 등록 여부:", host is not None)

            if host is not None:
                print("HOST 역할:", host.role)
                print("참여 상태:", host.status)

            assert host is not None, "HOST 등록 누락"
            assert host.role == "HOST", "HOST 역할 오류"
            assert host.status == "JOINED", "참여 상태 오류"
            assert post.author_member_id == host.member_id

            print("HOST 자동 등록 테스트 통과!")

    finally:
        # 테스트 데이터가 팀 공용 DB에 남지 않도록 취소
        transaction.rollback()
        print("테스트 데이터 롤백 완료")
