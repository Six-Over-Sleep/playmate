
# 게시글 좋아요 API 응답 데이터 형식
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class PostLikeResponse(BaseModel):
    # 좋아요를 누른 게시글 ID
    post_id: int

    # 좋아요를 누른 회원 ID
    member_id: int

    # 좋아요 등록 시간
    created_at: datetime

    # SQLAlchemy 객체를 Pydantic 응답으로 변환
    model_config = ConfigDict(from_attributes=True)
