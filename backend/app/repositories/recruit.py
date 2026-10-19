"""모임 관련 데이터베이스 조회와 저장을 담당하는 Repository.

Router는 API를 연결하고, Service는 업무 규칙을 판단함.
이 파일에서는 SQLAlchemy로 DB를 조회하거나 객체를 등록함.
트랜잭션의 commit/rollback은 Service에서 관리함.
"""

from sqlalchemy import func, or_
from sqlalchemy.orm import Session 

from backend.app.models.post import Post
from backend.app.models.recruit import Recruit, RecruitMember


# =========================================================
# 1. 모임 및 게시글 조회
# =========================================================
def find_recruit_with_post(db: Session, recruit_id: int):
    """삭제되지 않은 모임과 연결된 게시글을 조회함. 없으면 None 반환."""
    return (
        db.query(Post, Recruit)
        .join(Recruit, Post.post_id == Recruit.post_id)
        .filter(
            Recruit.recruit_id == recruit_id,
            or_(Post.post_status != "DELETED", Post.post_status.is_(None)),
        )
        .first()
    )


def list_recruits_with_posts(db: Session):
    """삭제되지 않은 모임과 게시글을 한 번의 쿼리로 조회함."""
    return (
        db.query(Post, Recruit)
        .join(Recruit, Post.post_id == Recruit.post_id)
        .filter(
            or_(Post.post_status != "DELETED", Post.post_status.is_(None))
        )
        .all()
    )


def get_recruit(db: Session, recruit_id: int):
    """모임 ID(PK)로 기본 정보를 조회함. 없으면 None 반환."""
    return db.get(Recruit, recruit_id)


def get_recruit_for_update(db: Session, recruit_id: int):
    """참여·정원 수정 작업 동안 해당 모임 행을 잠가 조회함.

    PostgreSQL에서 SELECT ... FOR UPDATE로 같은 모임의 변경 요청을 직렬화함.
    Service가 정원 확인과 참여 저장을 마친 뒤 commit/rollback해야 잠금이 풀림.
    """
    return (
        db.query(Recruit)
        .filter(Recruit.recruit_id == recruit_id)
        .with_for_update()
        .populate_existing()
        .first()
    )


def get_post(db: Session, post_id: int):
    """게시글 ID(PK)로 게시글을 조회함. 없으면 None 반환."""
    return db.get(Post, post_id)


def get_category_detail(db: Session, detail_model: type, recruit_id: int):
    """Service가 선택한 카테고리 모델에서 모임 상세 정보를 조회함.

    detail_model은 운동·게임·스터디·공동구매 상세 모델 중 하나임.
    카테고리 선택 및 유효성 판단은 Service에서 수행함.
    """
    return db.get(detail_model, recruit_id)


# =========================================================
# 2. 참여자 조회 및 인원 집계
# =========================================================
def find_member(db: Session, recruit_id: int, member_id: int):
    """특정 모임에 참여한 회원 기록을 조회함. 없으면 None 반환."""
    return (
        db.query(RecruitMember)
        .filter_by(recruit_id=recruit_id, member_id=member_id)
        .first()
    )


def list_joined_members(db: Session, recruit_id: int):
    """특정 모임에서 JOINED 상태인 회원만 조회함."""
    return (
        db.query(RecruitMember)
        .filter_by(recruit_id=recruit_id, status="JOINED")
        .all()
    )


def count_joined_members(db: Session, recruit_id: int) -> int:
    """특정 모임의 현재 참여 인원을 DB의 COUNT 함수로 계산함."""
    return (
        db.query(func.count())
        .select_from(RecruitMember)
        .filter_by(recruit_id=recruit_id, status="JOINED")
        .scalar()
    )


# =========================================================
# 3. 생성 시 DB 객체 등록
# =========================================================
def add_post(db: Session, post: Post) -> Post:
    """새 게시글을 세션에 등록하고 생성된 post_id를 확보함.

    flush는 SQL을 DB에 전달하지만 commit처럼 저장을 확정하지 않음.
    이후 모임 저장이 실패하면 Service에서 전체 rollback할 수 있음.
    """
    db.add(post)
    db.flush()
    return post


def add_recruit(db: Session, recruit: Recruit) -> Recruit:
    """새 모임을 세션에 등록하고 상세 정보에 사용할 recruit_id를 확보함."""
    db.add(recruit)
    db.flush()
    return recruit


def add_category_detail(db: Session, detail) -> None:
    """운동·게임·스터디·공동구매 중 하나의 상세 객체를 세션에 등록함.

    상세 정보 등록 후 commit 여부는 Service가 결정함.
    """
    db.add(detail)


def add_member(db: Session, member: RecruitMember) -> None:
    """신규 참여자를 DB 세션에 등록함. commit은 Service에서 수행함."""
    db.add(member)

def get_recruit_capacity_and_count(db: Session, recruit_id: int):
    """모임 존재 여부, 모집 정원, 현재 인원을 한 번에 조회함."""

    return (
        db.query(
            Recruit.capacity,
            func.count(RecruitMember.member_id).label("current_members"),
        )
        .join(Post, Post.post_id == Recruit.post_id)
        .outerjoin(
            RecruitMember,
            (RecruitMember.recruit_id == Recruit.recruit_id)
            & (RecruitMember.status == "JOINED"),
        )
        .filter(
            Recruit.recruit_id == recruit_id,
            or_(
                Post.post_status != "DELETED",
                Post.post_status.is_(None),
            ),
        )
        .group_by(Recruit.recruit_id, Recruit.capacity)
        .first()
    )