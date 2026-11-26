
# 게시글 스크랩 API 응답 데이터 형식
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class PostScrapResponse(BaseModel):
    # 스크랩한 게시글 ID
    post_id: int

    # 스크랩한 회원 ID
    member_id: int

    # 스크랩 등록 시간
    created_at: datetime

    # SQLAlchemy 객체를 Pydantic 응답으로 변환
    model_config = ConfigDict(from_attributes=True)
