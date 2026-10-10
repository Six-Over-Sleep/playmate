from backend.app.models.member import Member
from backend.app.models.post import Post
from backend.app.models.recruit import (
    Recruit, RecruitSportsDetail, RecruitGameDetail,
    RecruitStudyDetail, RecruitGroupBuyDetail
)


def create_recruit(db, data):
    try:
        post = Post(
            author_member_id=-1,
            title=data.title,
            body=data.body,
            post_type="RECRUIT"
        )
        db.add(post)
        db.flush()

        recruit = Recruit(
            post_id=post.post_id,
            recruit_mode=data.recruit_mode,
            category=data.category,
            capacity=data.capacity,
            meeting_datetime=data.meeting_datetime,
            place=data.place,
            is_online=data.is_online,
            contact_method=data.contact_method,
            deadline_at=data.deadline_at,
            state="OPEN"
        )
        db.add(recruit)
        db.flush()

        details = {
            "sports": (RecruitSportsDetail, {"sport_name": data.sport_name}),
            "game": (RecruitGameDetail, {"game_name": data.game_name}),
            "study": (RecruitStudyDetail, {
                "study_topic": data.study_topic,
                "study_period": data.study_period,
                "study_method": data.study_method
            }),
            "group_buy": (RecruitGroupBuyDetail, {
                "product_name": data.product_name,
                "purchase_url": data.purchase_url,
                "estimated_price_per_person": data.estimated_price_per_person,
                "pickup_method": data.pickup_method
            })
        }

        if data.category not in details:
            raise ValueError("지원하지 않는 모임 카테고리입니다.")

        model, values = details[data.category]
        db.add(model(recruit_id=recruit.recruit_id, **values))

        db.commit()
        return {"recruit_id": recruit.recruit_id, "post_id": post.post_id}

    except:
        db.rollback()
        raise