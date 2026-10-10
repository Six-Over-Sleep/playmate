from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class BoardCreate(StrictModel):
    name: str = Field(min_length=1, max_length=40)
    category: str = Field(pattern="^(자유|정보공유|분실물|취업)$")
    description: str | None = Field(default=None, max_length=200)
    creation_reason: str | None = Field(default=None, max_length=500)


class BoardResponse(BaseModel):
    id: int
    name: str
    description: str | None = None
    category: str
    created_at: datetime


class PostWrite(StrictModel):
    title: str = Field(min_length=1, max_length=100)
    body: str = Field(min_length=1, max_length=20000)


class PostImageResponse(BaseModel):
    id: int
    url: str
    original_name: str

class PostResponse(BaseModel):
    id: int
    board_id: int
    title: str
    body: str
    author_id: int
    author_name: str
    created_at: datetime
    updated_at: datetime
    comment_count: int = 0
    is_owner: bool = False
    images: list[PostImageResponse] = Field(default_factory=list)


class CommentWrite(StrictModel):
    body: str = Field(min_length=1, max_length=2000)


class CommentResponse(BaseModel):
    id: int
    post_id: int
    body: str
    author_id: int
    author_name: str
    created_at: datetime
    updated_at: datetime
    is_owner: bool = False
