"""모임 관련 데이터베이스 조회와 저장을 담당하는 Repository.

Router는 API 요청을 연결하고, Service는 업무 규칙을 판단함.
Repository는 SQLAlchemy를 이용한 DB 조회 및 객체 등록을 담당함.
commit/rollback 등 트랜잭션 처리는 Service에서 관리함.
"""

# func : SQL COUNT, COALESCE 등의 함수를 사용하기 위한 도구
# or_ : 여러 조회 조건을 OR로 연결하는 도구
from sqlalchemy import func, or_
# insert : PostgreSQL의 INSERT ... ON CONFLICT 구문 생성 (좋아요·스크랩 중복 방지)
from sqlalchemy.dialects.postgresql import insert

# Session : DB 조회 및 데이터 등록에 사용하는 SQLAlchemy 세션
from sqlalchemy.orm import Session

# 댓글 작성자 닉네임 조회에 사용하는 회원 ORM 모델
from backend.app.models.member import Member
# 모임 게시글, 모임 정보, 모임 참여자 ORM 모델
from backend.app.models.post import Post
# 좋아요·스크랩·댓글 ORM 모델 (공통 posts 기준 테이블)
from backend.app.models.comment import Comment
from backend.app.models.post_like import PostLike
from backend.app.models.post_scrap import PostScrap
from backend.app.models.recruit import Recruit, RecruitMember


# =========================================================
# 1. 모임 및 게시글 조회
# =========================================================
def find_recruit_with_post(db: Session, recruit_id: int):
    """모임 ID에 해당하는 모임과 게시글을 함께 조회함. 없으면 None 반환."""
    return (
        db.query(Post, Recruit)  # 게시글과 모임 정보를 함께 조회함
        .join(Recruit, Post.post_id == Recruit.post_id)  # 두 테이블을 post_id로 연결함
        .filter(
            Recruit.recruit_id == recruit_id,  # 요청한 모임 ID만 선택함
            # 삭제 상태가 아니거나 상태값이 없는 게시글만 조회함
            or_(Post.post_status != "DELETED", Post.post_status.is_(None)),
        )
        .first()  # 조회 결과 중 첫 번째 항목 반환, 없으면 None
    )


def list_recruits_with_posts(db: Session, category: str | None = None):
    """삭제 상태가 아닌 모임 목록과 각 모임의 참여 인원·좋아요 수를 조회함."""
    # 1단계 : 각 모임에서 JOINED 상태인 회원 수를 집계함
    # HOST도 JOINED 상태라면 인원에 포함하고, 취소한 회원은 제외함
    joined_counts = (
        db.query(
            RecruitMember.recruit_id,  # 모임별로 묶는 기준
            func.count(RecruitMember.member_id).label("participant_count"),  # 참여 인원수
        )
        .filter(RecruitMember.status == "JOINED")  # 현재 참여 중인 회원만 계산함
        .group_by(RecruitMember.recruit_id)  # 모임 ID별로 그룹화함
        .subquery()  # 집계 결과를 아래 메인 쿼리에서 사용할 임시 조회식으로 만듦
    )

    # 1-2단계 : 참여 인원과 같은 방식으로 게시글별 좋아요 수를 미리 집계함
    like_counts = (
        db.query(
            PostLike.post_id,
            func.count(PostLike.member_id).label("like_count"),
        )
        .group_by(PostLike.post_id)
        .subquery()
    )

    # 2단계 : 게시글 + 모임 + 참여 인원 + 좋아요 수를 한 쿼리로 조회함
    query = (
        db.query(
            Post,
            Recruit,
            # 참여자가 없어 집계 결과가 NULL이면 0명으로 표시함
            func.coalesce(joined_counts.c.participant_count, 0).label(
                "participant_count"
            ),
            func.coalesce(like_counts.c.like_count, 0).label("like_count"),
        )
        .join(Recruit, Post.post_id == Recruit.post_id)  # 게시글과 모임 연결
        .outerjoin(
            joined_counts,
            joined_counts.c.recruit_id == Recruit.recruit_id,
        )  # 참여자 집계가 없는 모임도 목록에 포함함
        # 좋아요가 없는 모임도 포함함
        .outerjoin(like_counts, like_counts.c.post_id == Post.post_id)
        .filter(
            or_(Post.post_status != "DELETED", Post.post_status.is_(None))
        )  # 삭제 상태인 게시글은 제외함
    )
    if category is not None:
        query = query.filter(Recruit.category == category)
    return query.all()


def get_recruit(db: Session, recruit_id: int):
    """모임 ID(PK)로 모임 기본 정보를 조회함. 없으면 None 반환."""
    # db.get() : 기본키로 ORM 객체 한 건을 조회함
    return db.get(Recruit, recruit_id)


def get_recruit_for_update(db: Session, recruit_id: int):
    """정원 확인 및 참여 처리 동안 모임 행을 잠가 조회함.

    PostgreSQL의 SELECT ... FOR UPDATE를 사용함.
    Service에서 commit 또는 rollback해야 해당 트랜잭션의 잠금이 해제됨.
    """
    return (
        db.query(Recruit)
        .filter(Recruit.recruit_id == recruit_id)  # 잠글 모임 한 건 선택
        .with_for_update()  # 동시에 정원을 수정하지 못하도록 행 잠금 요청
        .populate_existing()  # 세션에 이미 로드된 객체도 조회 값으로 다시 채움
        .first()
    )


def get_post(db: Session, post_id: int):
    """게시글 ID(PK)로 게시글을 조회함. 없으면 None 반환."""
    return db.get(Post, post_id)


def get_category_detail(db: Session, detail_model: type, recruit_id: int):
    """선택한 카테고리 모델에서 모임 상세 정보를 조회함.

    detail_model은 운동·게임·스터디·공동구매 상세 모델 중 하나임.
    어떤 모델을 사용할지 결정하고 검증하는 것은 Service의 역할임.
    """
    # 상세 테이블은 recruit_id를 기본키로 사용하므로 db.get()으로 조회 가능함
    return db.get(detail_model, recruit_id)


# =========================================================
# 2. 참여자 조회 및 인원 집계
# =========================================================
def find_member(db: Session, recruit_id: int, member_id: int):
    """특정 모임에 등록된 회원의 참여 기록을 조회함. 없으면 None 반환."""
    return (
        db.query(RecruitMember)
        # recruit_id + member_id : 참여자 테이블의 복합 기본키 조건
        .filter_by(recruit_id=recruit_id, member_id=member_id)
        .first()
    )


def list_joined_members(db: Session, recruit_id: int):
    """특정 모임에서 JOINED 상태인 회원 목록을 조회함."""
    return (
        db.query(RecruitMember)
        .filter_by(recruit_id=recruit_id, status="JOINED")  # 참여 중인 회원만 선택
        .all()
    )


def count_joined_members(db: Session, recruit_id: int) -> int:
    """특정 모임에서 현재 참여 중인 회원 수를 계산함."""
    return (
        db.query(func.count())  # SQL COUNT(*)로 행 개수를 셈
        .select_from(RecruitMember)  # 집계 대상 테이블 지정
        .filter_by(recruit_id=recruit_id, status="JOINED")
        .scalar()  # COUNT 결과 숫자 한 개만 반환
    )


# =========================================================
# 3. 생성 시 DB 객체 등록
# =========================================================
def add_post(db: Session, post: Post) -> Post:
    """게시글을 등록하고 생성된 post_id를 확보함.

    flush는 변경 사항을 DB에 전달하지만 commit처럼 확정하지 않음.
    이후 모임 생성에 실패하면 Service에서 전체 rollback할 수 있음.
    """
    db.add(post)  # 게시글 객체를 DB 세션에 등록함
    db.flush()  # INSERT를 실행하여 생성된 post_id를 사용할 수 있게 함
    return post


def add_recruit(db: Session, recruit: Recruit) -> Recruit:
    """새 모임을 등록하고 카테고리 상세 정보에 사용할 recruit_id를 확보함."""
    db.add(recruit)  # 모임 객체를 DB 세션에 등록함
    db.flush()  # INSERT를 실행하여 모임 ID를 확보함 (아직 commit 전)
    return recruit


def add_category_detail(db: Session, detail) -> None:
    """운동·게임·스터디·공동구매 상세 정보를 세션에 등록함."""
    db.add(detail)  # 상세 객체 등록; 최종 commit 여부는 Service가 결정함


def add_member(db: Session, member: RecruitMember) -> None:
    """모임 신규 참여자를 세션에 등록함."""
    db.add(member)  # 참여 기록 등록; commit은 Service에서 수행함


def get_recruit_capacity_and_count(db: Session, recruit_id: int):
    """모임 모집 정원과 현재 참여 인원을 함께 조회함. 없으면 None 반환."""
    return (
        db.query(
            Recruit.capacity,  # 모임 최대 모집 인원
            func.count(RecruitMember.member_id).label("current_members"),  # 현재 인원
        )
        .join(Post, Post.post_id == Recruit.post_id)  # 모임에 연결된 게시글 조회
        .outerjoin(
            RecruitMember,
            (RecruitMember.recruit_id == Recruit.recruit_id)
            & (RecruitMember.status == "JOINED"),
        )  # JOINED 참여자만 연결; 참여자가 0명인 모임도 조회함
        .filter(
            Recruit.recruit_id == recruit_id,
            or_(
                Post.post_status != "DELETED",
                Post.post_status.is_(None),
            ),  # 삭제 상태가 아닌 게시글에 속한 모임만 대상으로 함
        )
        .group_by(Recruit.recruit_id, Recruit.capacity)  # 모임별 참여 인원 집계
        .first()  # 모집 정원과 현재 인원 반환, 없으면 None
    )


# =========================================================
# 4. 좋아요·스크랩
# =========================================================
def add_post_like(db: Session, post_id: int, member_id: int) -> None:
    """좋아요를 등록함. 이미 있으면 기본키 충돌을 무시해 중복 행을 만들지 않음.

    INSERT ... ON CONFLICT DO NOTHING이므로 동시에 여러 번 요청해도 한 행만 남음.
    commit은 Service에서 수행함.
    """
    db.execute(
        insert(PostLike)
        .values(post_id=post_id, member_id=member_id)
        .on_conflict_do_nothing(index_elements=["post_id", "member_id"])
    )


def delete_post_like(db: Session, post_id: int, member_id: int) -> None:
    """회원의 좋아요를 삭제함. 좋아요가 없으면 아무것도 바뀌지 않음."""
    db.query(PostLike).filter_by(post_id=post_id, member_id=member_id).delete(
        synchronize_session=False
    )


def count_post_likes(db: Session, post_id: int) -> int:
    """게시글의 좋아요 수를 DB의 COUNT 함수로 계산함."""
    return (
        db.query(func.count())
        .select_from(PostLike)
        .filter_by(post_id=post_id)
        .scalar()
    )


def has_post_like(db: Session, post_id: int, member_id: int) -> bool:
    """회원이 게시글에 좋아요했는지 확인함."""
    return (
        db.query(PostLike).filter_by(post_id=post_id, member_id=member_id).first()
        is not None
    )


def add_post_scrap(db: Session, post_id: int, member_id: int) -> None:
    """스크랩을 등록함. 좋아요와 같이 중복 요청은 무시함."""
    db.execute(
        insert(PostScrap)
        .values(post_id=post_id, member_id=member_id)
        .on_conflict_do_nothing(index_elements=["post_id", "member_id"])
    )


def delete_post_scrap(db: Session, post_id: int, member_id: int) -> None:
    """회원의 스크랩을 삭제함. 스크랩이 없으면 아무것도 바뀌지 않음."""
    db.query(PostScrap).filter_by(post_id=post_id, member_id=member_id).delete(
        synchronize_session=False
    )


def has_post_scrap(db: Session, post_id: int, member_id: int) -> bool:
    """회원이 게시글을 스크랩했는지 확인함."""
    return (
        db.query(PostScrap).filter_by(post_id=post_id, member_id=member_id).first()
        is not None
    )


# =========================================================
# 5. 댓글·대댓글
# =========================================================
def list_post_comments(db: Session, post_id: int):
    """게시글의 댓글을 작성자 닉네임과 함께 작성 순서로 모두 조회함.

    삭제된 댓글도 포함함. 화면에 보일지 여부는 Service에서 판단함.
    Member 모델의 다른 컬럼은 읽지 않고 nickname만 조회함.
    """
    return (
        db.query(Comment, Member.nickname)
        .join(Member, Member.member_id == Comment.author_member_id)
        .filter(Comment.post_id == post_id)
        .order_by(Comment.created_at, Comment.comment_id)
        .all()
    )


def get_active_comment(db: Session, comment_id: int):
    """삭제되지 않은 댓글을 조회함. 없거나 삭제되었으면 None 반환."""
    return (
        db.query(Comment)
        .filter(Comment.comment_id == comment_id, Comment.deleted_at.is_(None))
        .first()
    )


def get_member_nickname(db: Session, member_id: int):
    """회원 닉네임만 조회함. 응답의 작성자 이름에 사용함."""
    return (
        db.query(Member.nickname).filter(Member.member_id == member_id).scalar()
    )


def add_comment(db: Session, comment: Comment) -> Comment:
    """새 댓글을 세션에 등록하고 생성된 comment_id를 확보함. commit은 Service에서 수행함."""
    db.add(comment)
    db.flush()
    return comment
