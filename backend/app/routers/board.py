from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from fastapi.concurrency import run_in_threadpool

from app.core.auth import get_current_member_id
from app.core.db_connect import CommitOutcomeUnknownError, close_pool
from app.core.uploads import remove_saved_images, save_images
from app.schemas.board import (
    BoardCreate,
    BoardResponse,
    CommentResponse,
    CommentWrite,
    PostLikeResponse,
    PostResponse,
    PostScrapResponse,
    PostWrite,
)
from app.services import board_service

router = APIRouter(prefix="/api", tags=["boards"])
router.add_event_handler("shutdown", close_pool)


@router.get("/boards", response_model=list[BoardResponse])
def list_boards(_: int = Depends(get_current_member_id)):
    return board_service.list_boards()


@router.post(
    "/boards", response_model=BoardResponse, status_code=status.HTTP_201_CREATED
)
def create_board(payload: BoardCreate, member_id: int = Depends(get_current_member_id)):
    return board_service.create_board(
        payload.name, payload.description, payload.creation_reason, member_id
    )


@router.get("/boards/{board_id}", response_model=BoardResponse)
def get_board(board_id: int, _: int = Depends(get_current_member_id)):
    return board_service.get_board(board_id)


@router.get("/boards/{board_id}/posts", response_model=list[PostResponse])
def list_posts(
    board_id: int,
    q: str | None = Query(default=None, max_length=100),
    sort: str = "latest",
    member_id: int = Depends(get_current_member_id),
):
    return board_service.list_posts(board_id, q, sort, member_id)


@router.post(
    "/boards/{board_id}/posts",
    response_model=PostResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_post(
    board_id: int,
    title: str = Form(min_length=1, max_length=100),
    body: str = Form(min_length=1, max_length=20000),
    images: list[UploadFile] = File(default=[]),
    member_id: int = Depends(get_current_member_id),
):
    title, body = title.strip(), body.strip()
    if not title or not body:
        raise HTTPException(status_code=422, detail="제목과 내용은 공백일 수 없습니다.")
    # DB 저장·응답 조회를 커밋 전에 마친 뒤에만 성공 응답을 반환한다.
    saved = await save_images(images)
    try:
        return await run_in_threadpool(
            board_service.create_post, board_id, title, body, member_id, saved
        )
    except CommitOutcomeUnknownError:
        # DB가 이미 참조할 수 있는 파일은 결과를 확인하기 전까지 보존한다.
        raise
    except Exception:
        remove_saved_images(saved)
        raise


@router.get("/boards/{board_id}/posts/{post_id}", response_model=PostResponse)
def get_post(
    board_id: int, post_id: int, member_id: int = Depends(get_current_member_id)
):
    return board_service.get_post(board_id, post_id, member_id)


@router.patch("/boards/{board_id}/posts/{post_id}", response_model=PostResponse)
def update_post(
    board_id: int,
    post_id: int,
    payload: PostWrite,
    member_id: int = Depends(get_current_member_id),
):
    return board_service.update_post(
        board_id, post_id, payload.title, payload.body, member_id
    )


@router.delete(
    "/boards/{board_id}/posts/{post_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_post(
    board_id: int, post_id: int, member_id: int = Depends(get_current_member_id)
):
    board_service.delete_post(board_id, post_id, member_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/boards/{board_id}/posts/{post_id}/like", response_model=PostLikeResponse)
def like_post(
    board_id: int, post_id: int, member_id: int = Depends(get_current_member_id)
):
    return board_service.like_post(board_id, post_id, member_id)


@router.delete(
    "/boards/{board_id}/posts/{post_id}/like", response_model=PostLikeResponse
)
def unlike_post(
    board_id: int, post_id: int, member_id: int = Depends(get_current_member_id)
):
    return board_service.unlike_post(board_id, post_id, member_id)


@router.put(
    "/boards/{board_id}/posts/{post_id}/scrap", response_model=PostScrapResponse
)
def scrap_post(
    board_id: int, post_id: int, member_id: int = Depends(get_current_member_id)
):
    return board_service.scrap_post(board_id, post_id, member_id)


@router.delete(
    "/boards/{board_id}/posts/{post_id}/scrap", response_model=PostScrapResponse
)
def unscrap_post(
    board_id: int, post_id: int, member_id: int = Depends(get_current_member_id)
):
    return board_service.unscrap_post(board_id, post_id, member_id)


@router.get(
    "/boards/{board_id}/posts/{post_id}/comments", response_model=list[CommentResponse]
)
def list_comments(
    board_id: int, post_id: int, member_id: int = Depends(get_current_member_id)
):
    return board_service.list_comments(board_id, post_id, member_id)


@router.post(
    "/boards/{board_id}/posts/{post_id}/comments",
    response_model=CommentResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_comment(
    board_id: int,
    post_id: int,
    payload: CommentWrite,
    member_id: int = Depends(get_current_member_id),
):
    return board_service.create_comment(
        board_id, post_id, payload.body, member_id, payload.parent_comment_id
    )


@router.patch("/comments/{comment_id}", response_model=CommentResponse)
def update_comment(
    comment_id: int,
    payload: CommentWrite,
    member_id: int = Depends(get_current_member_id),
):
    if payload.parent_comment_id is not None:
        raise HTTPException(status_code=422, detail="댓글 위치는 수정할 수 없습니다.")
    return board_service.update_comment(comment_id, payload.body, member_id)


@router.delete("/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_comment(comment_id: int, member_id: int = Depends(get_current_member_id)):
    board_service.delete_comment(comment_id, member_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
