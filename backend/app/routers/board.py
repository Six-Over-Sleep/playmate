# 게시판, 게시글, 댓글 API 요청을 처리하고 Service와 연결하는 Router
# Router는 요청값 검증 및 응답 반환을 담당하고, 실제 DB 처리는 Service에서 수행함.
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

# 로그인한 회원 ID를 확인하는 인증 함수
from app.core.auth import get_current_member_id
# DB 커밋 결과가 불확실한 경우의 예외와 연결 풀 종료 함수
from app.core.db_connect import CommitOutcomeUnknownError, close_pool
# 업로드 이미지 저장 및 저장한 파일 삭제 함수
from app.core.uploads import remove_saved_images, save_images
# API 요청과 응답 데이터 형식을 정의하는 Pydantic 스키마
from app.schemas.board import (
    BoardCreate,
    BoardResponse,
    CommentResponse,
    CommentWrite,
    PostResponse,
    PostWrite,
)
# 게시판·게시글·댓글의 실제 업무 로직을 처리하는 Service
from app.services import board_service

# prefix="/api" : 이 Router의 모든 API 주소 앞에 /api를 붙임.
# tags=["boards"] : FastAPI 자동 API 문서에서 boards 그룹으로 표시함.
router = APIRouter(prefix="/api", tags=["boards"])

# 애플리케이션 종료 시 DB 연결 풀을 정리하도록 종료 이벤트 등록
router.add_event_handler("shutdown", close_pool)


# =========================================================
# 1. 게시판 조회 및 생성
# =========================================================

# GET /api/boards : 전체 게시판 목록 조회
# response_model : 응답 데이터가 BoardResponse 목록 형식인지 검증함.
@router.get("/boards", response_model=list[BoardResponse])
def list_boards(_: int = Depends(get_current_member_id)):
    # Depends() : 로그인 회원을 확인하는 인증 함수 실행
    # _ : 회원 ID를 직접 쓰지 않고 인증 여부만 확인할 때 사용하는 변수명
    return board_service.list_boards()


# POST /api/boards : 새 게시판 생성
# HTTP 201 : 새 리소스 생성 성공을 의미함.
@router.post(
    "/boards", response_model=BoardResponse, status_code=status.HTTP_201_CREATED
)
def create_board(payload: BoardCreate, member_id: int = Depends(get_current_member_id)):
    # payload : 게시판 이름, 설명, 생성 사유를 담은 요청 데이터
    # member_id : 현재 로그인한 회원 ID (게시판 생성자)
    return board_service.create_board(
        payload.name, payload.description, payload.creation_reason, member_id
    )


# GET /api/boards/{board_id} : 특정 게시판 상세 조회
@router.get("/boards/{board_id}", response_model=BoardResponse)
def get_board(board_id: int, _: int = Depends(get_current_member_id)):
    # board_id : 주소에 포함된 게시판 고유 번호
    return board_service.get_board(board_id)


# =========================================================
# 2. 게시글 목록 조회 및 생성
# =========================================================

# GET /api/boards/{board_id}/posts : 게시판별 게시글 목록 조회
@router.get("/boards/{board_id}/posts", response_model=list[PostResponse])
def list_posts(
    board_id: int,
    q: str | None = Query(default=None, max_length=100),
    sort: str = "latest",
    member_id: int = Depends(get_current_member_id),
):
    # q : 검색어 (선택값, 최대 100자)
    # sort : 정렬 기준 (기본값 latest)
    # member_id : 게시글에 대한 본인 작성 여부 등을 판단할 때 전달함.
    return board_service.list_posts(board_id, q, sort, member_id)


# POST /api/boards/{board_id}/posts : 이미지 첨부가 가능한 게시글 생성
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
    # Form() : multipart/form-data 형식으로 전달된 제목과 본문을 받음.
    # File() / UploadFile : 함께 첨부한 이미지 파일 목록을 받음.
    # strip() : 제목과 본문의 앞뒤 공백 제거
    title, body = title.strip(), body.strip()

    # 공백만 입력한 경우 길이 검증을 통과할 수 있어 별도로 확인함.
    if not title or not body:
        raise HTTPException(status_code=422, detail="제목과 내용은 공백일 수 없습니다.")

    # 이미지를 먼저 저장하고 파일 메타데이터를 확보함.
    saved = await save_images(images)
    try:
        # 동기 Service 함수를 스레드 풀에서 실행하여 이벤트 루프 차단을 줄임.
        # 게시글·이미지 정보를 DB에 저장하고 게시글 응답을 반환함.
        return await run_in_threadpool(
            board_service.create_post, board_id, title, body, member_id, saved
        )
    except CommitOutcomeUnknownError:
        # DB 커밋 성공 여부를 알 수 없을 때는 이미지 파일을 바로 삭제하지 않음.
        # 실제 커밋되었다면 DB에서 해당 파일을 참조할 수 있기 때문임.
        raise
    except Exception:
        # 커밋 결과가 불확실한 경우를 제외한 오류 발생 시 저장된 이미지를 정리함.
        remove_saved_images(saved)
        raise


# =========================================================
# 3. 게시글 상세 조회, 수정 및 삭제
# =========================================================

# GET /api/boards/{board_id}/posts/{post_id} : 게시글 상세 조회
@router.get("/boards/{board_id}/posts/{post_id}", response_model=PostResponse)
def get_post(
    board_id: int, post_id: int, member_id: int = Depends(get_current_member_id)
):
    # post_id : 조회할 게시글 고유 번호
    return board_service.get_post(board_id, post_id, member_id)


# PATCH /api/boards/{board_id}/posts/{post_id} : 게시글 내용 수정
@router.patch("/boards/{board_id}/posts/{post_id}", response_model=PostResponse)
def update_post(
    board_id: int,
    post_id: int,
    payload: PostWrite,
    member_id: int = Depends(get_current_member_id),
):
    # PostWrite : 수정할 제목과 본문을 검증하는 요청 스키마
    # 수정 권한과 실제 DB 변경 처리는 Service에서 담당함.
    return board_service.update_post(
        board_id, post_id, payload.title, payload.body, member_id
    )


# DELETE /api/boards/{board_id}/posts/{post_id} : 게시글 삭제
# HTTP 204 : 삭제 성공 후 응답 본문이 없음을 의미함.
@router.delete(
    "/boards/{board_id}/posts/{post_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_post(
    board_id: int, post_id: int, member_id: int = Depends(get_current_member_id)
):
    # Service에서 삭제 권한을 확인하고 게시글 삭제를 처리함.
    board_service.delete_post(board_id, post_id, member_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# =========================================================
# 4. 댓글 조회 및 생성
# =========================================================

# GET /api/boards/{board_id}/posts/{post_id}/comments : 게시글 댓글 목록 조회
@router.get(
    "/boards/{board_id}/posts/{post_id}/comments", response_model=list[CommentResponse]
)
def list_comments(
    board_id: int, post_id: int, member_id: int = Depends(get_current_member_id)
):
    # 게시판 및 게시글 정보를 전달하여 해당 게시글의 댓글 목록을 가져옴.
    return board_service.list_comments(board_id, post_id, member_id)


# POST /api/boards/{board_id}/posts/{post_id}/comments : 새 댓글 작성
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
    # CommentWrite : 댓글 내용을 전달받는 요청 스키마
    # member_id : 댓글 작성자의 회원 ID

    return board_service.create_comment(
        board_id,
        post_id,
        payload.body,
        member_id,
        payload.parent_comment_id
    )


# =========================================================
# 5. 댓글 수정 및 삭제
# =========================================================

# PATCH /api/comments/{comment_id} : 기존 댓글 수정
@router.patch("/comments/{comment_id}", response_model=CommentResponse)
def update_comment(
    comment_id: int,
    payload: CommentWrite,
    member_id: int = Depends(get_current_member_id),
):
    # comment_id : 수정할 댓글 고유 번호
    # 작성자 확인 및 댓글 수정은 Service에서 수행함.
    return board_service.update_comment(comment_id, payload.body, member_id)


# DELETE /api/comments/{comment_id} : 기존 댓글 삭제
@router.delete("/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_comment(comment_id: int, member_id: int = Depends(get_current_member_id)):
    # 댓글 삭제를 처리한 후 본문 없이 HTTP 204 응답을 반환함.
    board_service.delete_comment(comment_id, member_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
