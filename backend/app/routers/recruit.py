from datetime import datetime
from sqlalchemy import func
from backend.app.models.recruit import RecruitMember
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.models.post import Post
from backend.app.models.recruit import Recruit
from backend.app.schemas.recruit import RecruitCreate, RecruitUpdate
from backend.app.services.recruit import create_recruit

from backend.app.models.recruit import (
    RecruitSportsDetail, RecruitGameDetail,
    RecruitStudyDetail, RecruitGroupBuyDetail
)


router = APIRouter(prefix="/api/recruits", tags=["모임"])


@router.get("/{recruit_id}")
def get_recruit(recruit_id: int, db: Session = Depends(get_db)):
    result = db.query(Post, Recruit).join(
        Recruit, Post.post_id == Recruit.post_id
    ).filter(
        Recruit.recruit_id == recruit_id,
        or_(Post.post_status != "DELETED", Post.post_status.is_(None))
    ).first()

    if not result:
        raise HTTPException(404, "모임이 없습니다.")

    post, recruit = result

    models = {
        "sports": RecruitSportsDetail,
        "game": RecruitGameDetail,
        "study": RecruitStudyDetail,
        "group_buy": RecruitGroupBuyDetail
    }

    detail = db.get(models[recruit.category], recruit_id)

    return {
        "recruit_id": recruit.recruit_id,
        "title": post.title,
        "body": post.body,
        "category": recruit.category,
        "capacity": recruit.capacity,
        "meeting_datetime": recruit.meeting_datetime,
        "place": recruit.place,
        "state": recruit.state,
        "detail": {
            column.name: getattr(detail, column.name)
            for column in detail.__table__.columns
            if column.name != "recruit_id"
        } if detail else {}
    }

@router.post("", status_code=201)
def add_recruit(data: RecruitCreate, db: Session = Depends(get_db)):
    return create_recruit(db, data)


@router.get("/{recruit_id}")
def get_recruit(recruit_id: int, db: Session = Depends(get_db)):
    result = db.query(Post, Recruit).join(
        Recruit, Post.post_id == Recruit.post_id
    ).filter(
        Recruit.recruit_id == recruit_id,
        or_(Post.post_status != "DELETED", Post.post_status.is_(None))
    ).first()

    if not result:
        raise HTTPException(status_code=404, detail="모임이 없습니다.")

    post, recruit = result

    return {
        "recruit_id": recruit.recruit_id,
        "title": post.title,
        "body": post.body,
        "category": recruit.category,
        "capacity": recruit.capacity,
        "meeting_datetime": recruit.meeting_datetime,
        "place": recruit.place,
        "state": recruit.state
    }


@router.patch("/{recruit_id}")
def update_recruit(recruit_id: int, data: RecruitUpdate, db: Session = Depends(get_db)):
    recruit = db.query(Recruit).filter(
        Recruit.recruit_id == recruit_id
    ).first()

    if not recruit:
        raise HTTPException(status_code=404, detail="모임이 없습니다.")

    post = db.query(Post).filter(
        Post.post_id == recruit.post_id,
        or_(Post.post_status != "DELETED", Post.post_status.is_(None))
    ).first()

    if not post:
        raise HTTPException(status_code=404, detail="모임이 없습니다.")

    changes = data.model_dump(exclude_unset=True)

    for key, value in changes.items():
        if key in ["title", "body"]:
            setattr(post, key, value)
        else:
            setattr(recruit, key, value)

    db.commit()
    return {"message": "모임 수정 완료"}


@router.delete("/{recruit_id}")
def delete_recruit(recruit_id: int, db: Session = Depends(get_db)):
    recruit = db.query(Recruit).filter(
        Recruit.recruit_id == recruit_id
    ).first()

    if not recruit:
        raise HTTPException(status_code=404, detail="모임이 없습니다.")

    post = db.query(Post).filter(
        Post.post_id == recruit.post_id,
        or_(Post.post_status != "DELETED", Post.post_status.is_(None))
    ).first()

    if not post:
        raise HTTPException(status_code=404, detail="모임이 없습니다.")

    post.post_status = "DELETED"
    post.deleted_at = datetime.now()
    recruit.state = "CLOSED"

    db.commit()
    return {"message": "모임 삭제 완료"}

@router.post("/{recruit_id}/join")
def join_recruit(recruit_id: int, db: Session = Depends(get_db)):
    member_id = -1

    recruit = db.get(Recruit, recruit_id)

    if not recruit or recruit.state != "OPEN":
        raise HTTPException(400, "참여할 수 없는 모임입니다.")

    post = db.get(Post, recruit.post_id)
    if not post or post.post_status == "DELETED":
        raise HTTPException(400, "삭제된 모임입니다.")

    member = db.query(RecruitMember).filter_by(
        recruit_id=recruit_id, member_id=member_id
    ).first()

    if member and member.status == "JOINED":
        raise HTTPException(400, "이미 참여한 모임입니다.")

    count = db.query(func.count()).select_from(RecruitMember).filter_by(
        recruit_id=recruit_id, status="JOINED"
    ).scalar()

    if count >= recruit.capacity:
        raise HTTPException(400, "모집 인원이 가득 찼습니다.")

    if member:
        member.status = "JOINED"
        member.canceled_at = None
        member.joined_at = datetime.now()
    else:
        db.add(RecruitMember(
            recruit_id=recruit_id,
            member_id=member_id,
            role="MEMBER",
            status="JOINED",
            joined_at=datetime.now()
        ))

    db.commit()
    return {"message": "모임 참여 완료"}


# 모임 참여 취소 API
@router.delete("/{recruit_id}/join")
def cancel_join(recruit_id: int, db: Session = Depends(get_db)):
    member = db.query(RecruitMember).filter_by(
        recruit_id=recruit_id, member_id=-1
    ).first()

    if not member or member.status != "JOINED":
        raise HTTPException(400, "참여 중인 모임이 아닙니다.")

    member.status = "CANCELED"
    member.canceled_at = datetime.now()

    db.commit()
    return {"message": "모임 참여 취소 완료"}

# 참여자 목록 조회 API
@router.get("/{recruit_id}/members")
def get_recruit_members(recruit_id: int, db: Session = Depends(get_db)):
    recruit = db.get(Recruit, recruit_id)

    if not recruit:
        raise HTTPException(404, "모임이 없습니다.")

    members = db.query(RecruitMember).filter_by(
        recruit_id=recruit_id, status="JOINED"
    ).all()

    return [
        {
            "member_id": member.member_id,
            "role": member.role,
            "joined_at": member.joined_at
        }
        for member in members
    ]


@router.get("/{recruit_id}/count")
def get_recruit_count(recruit_id: int, db: Session = Depends(get_db)):
    recruit = db.get(Recruit, recruit_id)

    if not recruit:
        raise HTTPException(404, "모임이 없습니다.")

    post = db.get(Post, recruit.post_id)
    if not post or post.post_status == "DELETED":
        raise HTTPException(404, "모임이 없습니다.")

    count = db.query(func.count()).select_from(RecruitMember).filter_by(
        recruit_id=recruit_id,
        status="JOINED"
    ).scalar()

    return {
        "recruit_id": recruit_id,
        "current_members": count,
        "capacity": recruit.capacity,
        "remaining": max(0, recruit.capacity - count)
    }