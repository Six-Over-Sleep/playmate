
# 마이페이지 API
from fastapi import APIRouter, Depends, HTTPException
from psycopg.rows import dict_row

from backend.app.core.database import get_db_connection
from backend.app.core.auth import get_current_member_id
from backend.app.schemas.mypage import MyProfileResponse, MyProfileUpdate
from psycopg.errors import UniqueViolation
from fastapi import File, UploadFile
from backend.app.core.uploads import save_profile_image

from backend.app.schemas.mypage import MyLevelResponse
from backend.app.services.xp_service import calculate_level
from backend.app.schemas.mypage import MyXPHistoryResponse
from backend.app.services.xp_service import grant_xp

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from backend.app.schemas.mypage import MyAttendanceResponse
from backend.app.services.xp_service import calculate_attendance_streak
from backend.app.schemas.mypage import MySkillResponse
from backend.app.schemas.mypage import MySkillTopicResponse
from backend.app.schemas.mypage import MySkillAccuracyResponse
from backend.app.schemas.mypage import MyPostResponse
from backend.app.schemas.mypage import MyCommentResponse
from backend.app.schemas.mypage import MyScrapResponse
from backend.app.schemas.mypage import MyMeetupResponse
from fastapi import Query
from backend.app.schemas.mypage import MyPostPageResponse
from backend.app.schemas.mypage import MyCommentPageResponse

router = APIRouter(prefix="/mypage", tags=["마이페이지"])


# 내 프로필 조회
@router.get("/profile", response_model=MyProfileResponse)
def get_my_profile(
    member_id: int = Depends(get_current_member_id)
):
    with get_db_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT
                    member_id,
                    COALESCE(NULLIF(nickname, ''), '익명') AS nickname,
                    profile_image_url
                FROM members
                WHERE member_id = %s
                """,
                (member_id,)
            )

            profile = cursor.fetchone()

    if profile is None:
        raise HTTPException(
            status_code=404,
            detail="회원 정보를 찾을 수 없습니다."
        )

    return profile


# 내 프로필 닉네임 수정

# 내 프로필 닉네임 수정
@router.patch("/profile", response_model=MyProfileResponse)
def update_my_profile(
    data: MyProfileUpdate,
    member_id: int = Depends(get_current_member_id)
):
    try:
        with get_db_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    UPDATE members
                    SET nickname = %s
                    WHERE member_id = %s
                    RETURNING member_id, nickname, profile_image_url
                    """,
                    (data.nickname, member_id)
                )

                profile = cursor.fetchone()

    except UniqueViolation as e:
        if e.diag.constraint_name == "uq_members_nickname_normalized":
            raise HTTPException(
                status_code=409,
                detail="이미 사용 중인 닉네임입니다."
            ) from e
        raise

    if profile is None:
        raise HTTPException(
            status_code=404,
            detail="회원 정보를 찾을 수 없습니다."
        )

    return profile



# 내 프로필 이미지 변경
@router.post("/profile/image", response_model=MyProfileResponse)
async def update_profile_image(
    file: UploadFile = File(...),
    member_id: int = Depends(get_current_member_id)
):
    saved = None

    try:
        # 1. 이미지 파일 저장
        saved = await save_profile_image(file)

        # 2. 이미지 URL 생성
        image_url = f"/uploads/{saved['stored_name']}"

        # 3. 회원 프로필 이미지 URL 변경
        with get_db_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    UPDATE members
                    SET profile_image_url = %s
                    WHERE member_id = %s
                    RETURNING member_id, nickname, profile_image_url
                    """,
                    (image_url, member_id)
                )

                profile = cursor.fetchone()

                if profile is None:
                    raise HTTPException(
                        status_code=404,
                        detail="회원 정보를 찾을 수 없습니다."
                    )

        return profile

    except Exception:
        # DB 저장 실패 시 이번에 업로드한 파일 삭제
        if saved is not None:
            saved["path"].unlink(missing_ok=True)
        raise

    finally:
        await file.close()



# 내 종합 레벨 조회
@router.get("/level", response_model=MyLevelResponse)
def get_my_level(
    member_id: int = Depends(get_current_member_id)
):
    with get_db_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT COALESCE(l.total_xp, 0) AS total_xp
                FROM members m
                LEFT JOIN member_levels l
                    ON m.member_id = l.member_id
                WHERE m.member_id = %s
                """,
                (member_id,)
            )

            result = cursor.fetchone()

    if result is None:
        raise HTTPException(
            status_code=404,
            detail="회원 정보를 찾을 수 없습니다."
        )

    total_xp = result["total_xp"]
    level = calculate_level(total_xp)

    # 다음 레벨에 필요한 누적 XP
    level_requirements = {
        1: 100,
        2: 500,
        3: 1500,
        4: None
    }

    next_level_xp = level_requirements[level]

    # 다음 레벨까지 남은 XP
    remaining_xp = (
        max(0, next_level_xp - total_xp)
        if next_level_xp is not None
        else 0
    )

    
    # 현재 레벨의 시작 경험치
    level_start_xp = {
        1: 0,
        2: 100,
        3: 500,
        4: 1500
    }

    # 경험치 진행률 계산
    if level == 4:
        progress_percent = 100.0
    else:
        start_xp = level_start_xp[level]
        required_xp = next_level_xp - start_xp

        progress_percent = round(
            (total_xp - start_xp) / required_xp * 100,
            1
        )


    return {
        "level": level,
        "total_xp": total_xp,
        "next_level_xp": next_level_xp,
        "remaining_xp": remaining_xp,
        "progress_percent": progress_percent
    }


# 내 경험치 획득 및 회수 내역 조회
@router.get("/xp-history", response_model=list[MyXPHistoryResponse])
def get_my_xp_history(
    member_id: int = Depends(get_current_member_id)
):
    with get_db_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT
                    history_id,
                    activity_type,
                    xp_change,
                    activity_date,
                    created_at
                FROM member_xp_history
                WHERE member_id = %s
                ORDER BY created_at DESC, history_id DESC
                LIMIT 30
                """,
                (member_id,)
            )

            history = cursor.fetchall()

    return history


# 일일 출석 체크
@router.post("/attendance")
def check_attendance(
    member_id: int = Depends(get_current_member_id)
):
    return grant_xp(member_id, "ATTEND")


# 내 출석 현황 조회
@router.get("/attendance", response_model=MyAttendanceResponse)
def get_my_attendance(
    member_id: int = Depends(get_current_member_id)
):
    today = datetime.now(ZoneInfo("Asia/Seoul")).date()

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT activity_date
                FROM member_xp_history
                WHERE member_id = %s
                    AND activity_type = 'ATTEND'
                    AND xp_change > 0
                    AND activity_date BETWEEN %s AND %s
                """,
                (member_id, today - timedelta(days=30), today)
            )

            dates = {row[0] for row in cursor.fetchall()}

    # 오늘 출석 여부
    attended_today = today in dates

    # 오늘 출석 전이면 어제까지의 연속 출석 계산
    reference_date = (
        today if attended_today
        else today - timedelta(days=1)
    )

    streak_days = calculate_attendance_streak(
        dates, reference_date
    )

    return {
        "attended_today": attended_today,
        "streak_days": streak_days,
        "achieved_7_days": streak_days >= 7,
        "achieved_30_days": streak_days >= 30
    }


# 내 스킬 레벨 조회
@router.get("/skills", response_model=list[MySkillResponse])
def get_my_skills(
    member_id: int = Depends(get_current_member_id)
):
    with get_db_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                WITH skills(skill_code, skill_name) AS (
                    VALUES
                        ('PYTHON', 'Python'),
                        ('SQL', 'SQL'),
                        ('GIT', 'Git/GitHub'),
                        ('REACT', 'React'),
                        ('LANGCHAIN', 'LangChain')
                )
                SELECT
                    s.skill_code,
                    s.skill_name,
                    COALESCE(l.level, 1) AS level,
                    COALESCE(l.total_xp, 0) AS total_xp
                FROM members m
                CROSS JOIN skills s
                LEFT JOIN member_skill_levels l
                    ON l.member_id = m.member_id
                    AND l.skill_code = s.skill_code
                WHERE m.member_id = %s
                ORDER BY
                    CASE s.skill_code
                        WHEN 'PYTHON' THEN 1
                        WHEN 'SQL' THEN 2
                        WHEN 'GIT' THEN 3
                        WHEN 'REACT' THEN 4
                        WHEN 'LANGCHAIN' THEN 5
                    END
                """,
                (member_id,)
            )

            skills = cursor.fetchall()


    # 레벨별 시작 경험치
    level_start_xp = {
        1: 0,
        2: 50,
        3: 150,
        4: 300,
        5: 500
    }

    # 다음 레벨에 필요한 누적 경험치
    next_level_requirements = {
        1: 50,
        2: 150,
        3: 300,
        4: 500,
        5: None
    }

    for skill in skills:
        level = skill["level"]
        total_xp = skill["total_xp"]

        next_level_xp = next_level_requirements[level]

        if next_level_xp is None:
            remaining_xp = 0
            progress_percent = 100.0
        else:
            start_xp = level_start_xp[level]

            remaining_xp = max(
                0, next_level_xp - total_xp
            )

            progress_percent = round(
                (total_xp - start_xp)
                / (next_level_xp - start_xp) * 100,
                1
            )

        skill["next_level_xp"] = next_level_xp
        skill["remaining_xp"] = remaining_xp
        skill["progress_percent"] = progress_percent

    return skills


# 내 스킬별 세부 학습 영역 조회
@router.get("/skills/topics", response_model=list[MySkillTopicResponse])
def get_my_skill_topics(
    member_id: int = Depends(get_current_member_id)
):
    with get_db_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT
                    skill_code,
                    topic_code,
                    COUNT(*)::INT AS solved_count,
                    SUM(xp_change)::INT AS earned_xp
                FROM member_skill_xp_history
                WHERE member_id = %s
                    AND xp_change > 0
                    AND topic_code IS NOT NULL
                    AND activity_type IN (
                        'QUIZ', 'PRACTICE', 'ADVANCED'
                    )
                GROUP BY skill_code, topic_code
                ORDER BY skill_code, topic_code
                """,
                (member_id,)
            )

            topics = cursor.fetchall()

    return topics



# 내 스킬별 세부 학습 영역 정답률 조회
@router.get(
    "/skills/accuracy",
    response_model=list[MySkillAccuracyResponse]
)
def get_my_skill_accuracy(
    member_id: int = Depends(get_current_member_id)
):
    with get_db_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT
                    skill_code,
                    topic_code,
                    COUNT(*)::INT AS total_attempts,
                    COUNT(*) FILTER (
                        WHERE is_correct = TRUE
                    )::INT AS correct_count,
                    COUNT(*) FILTER (
                        WHERE is_correct = FALSE
                    )::INT AS incorrect_count,
                    ROUND(
                        100.0 * COUNT(*) FILTER (
                            WHERE is_correct = TRUE
                        ) / COUNT(*),
                        1
                    )::FLOAT AS accuracy_percent
                FROM member_skill_attempts
                WHERE member_id = %s
                GROUP BY skill_code, topic_code
                ORDER BY skill_code, topic_code
                """,
                (member_id,)
            )

            return cursor.fetchall()



# 내가 작성한 게시글 조회
@router.get("/posts", response_model=list[MyPostResponse])

# 내가 작성한 게시글 조회 (페이지네이션)
@router.get("/posts", response_model=MyPostPageResponse)
def get_my_posts(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=50),
    member_id: int = Depends(get_current_member_id)
):
    offset = (page - 1) * page_size

    with get_db_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cursor:

            # 전체 게시글 수
            cursor.execute(
                """
                SELECT COUNT(*) AS total
                FROM posts
                WHERE author_member_id = %s
                  AND deleted_at IS NULL
                """,
                (member_id,)
            )

            total = cursor.fetchone()["total"]

            # 현재 페이지의 게시글 조회
            cursor.execute(
                """
                SELECT
                    p.post_id,
                    p.board_id,
                    CASE
                        WHEN b.board_name IS NOT NULL
                            THEN b.board_name
                        WHEN p.post_type = 'RECRUIT'
                            THEN '모임'
                        ELSE '기타 게시글'
                    END AS board_name,
                    COALESCE(p.title, '제목 없음') AS title,
                    p.created_at
                FROM posts p
                LEFT JOIN boards b
                    ON p.board_id = b.board_id
                WHERE p.author_member_id = %s
                  AND p.deleted_at IS NULL
                ORDER BY
                    p.created_at DESC NULLS LAST,
                    p.post_id DESC
                LIMIT %s OFFSET %s
                """,
                (member_id, page_size, offset)
            )

            items = cursor.fetchall()

            return {
                "items": items,
                "total": total,
                "page": page,
                "page_size": page_size
            }



# 내가 작성한 댓글 및 대댓글 조회
@router.get("/comments", response_model=list[MyCommentResponse])

@router.get("/comments", response_model=MyCommentPageResponse)
def get_my_comments(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=50),
    member_id: int = Depends(get_current_member_id)
):
    offset = (page - 1) * page_size

    with get_db_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cursor:

            # 전체 댓글 수
            cursor.execute(
                """
                SELECT COUNT(*) AS total
                FROM comments c
                JOIN posts p ON c.post_id = p.post_id
                WHERE c.author_member_id = %s
                  AND c.deleted_at IS NULL
                  AND p.deleted_at IS NULL
                """,
                (member_id,)
            )
            total = cursor.fetchone()["total"]

            # 현재 페이지 댓글 조회
            cursor.execute(
                """
                SELECT
                    c.comment_id,
                    c.post_id,
                    p.board_id,
                    COALESCE(p.title, '제목 없음') AS post_title,
                    c.body,
                    c.parent_comment_id,
                    c.created_at
                FROM comments c
                JOIN posts p ON c.post_id = p.post_id
                WHERE c.author_member_id = %s
                  AND c.deleted_at IS NULL
                  AND p.deleted_at IS NULL
                ORDER BY
                    c.created_at DESC NULLS LAST,
                    c.comment_id DESC
                LIMIT %s OFFSET %s
                """,
                (member_id, page_size, offset)
            )

            return {
                "items": cursor.fetchall(),
                "total": total,
                "page": page,
                "page_size": page_size
            }


# 내가 스크랩한 게시글 조회
@router.get("/scraps", response_model=list[MyScrapResponse])
def get_my_scraps(
    member_id: int = Depends(get_current_member_id)
):
    with get_db_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT
                    p.post_id,
                    p.board_id,
                    COALESCE(p.title, '제목 없음') AS title,
                    s.created_at AS scrapped_at
                FROM post_scraps s
                JOIN posts p
                    ON s.post_id = p.post_id
                WHERE s.member_id = %s
                    AND p.deleted_at IS NULL
                ORDER BY s.created_at DESC, s.post_id DESC
                LIMIT 20
                """,
                (member_id,)
            )

            return cursor.fetchall()


# 내가 생성하거나 참여한 모임 조회
@router.get("/meetups", response_model=list[MyMeetupResponse])
def get_my_meetups(
    member_id: int = Depends(get_current_member_id)
):
    with get_db_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                """
                SELECT
                    r.recruit_id,
                    r.post_id,
                    COALESCE(p.title, '제목 없음') AS title,
                    rm.role,
                    rm.status,
                    r.category,
                    r.recruit_mode,
                    r.state,
                    r.created_at
                FROM recruit_members rm
                JOIN recruits r
                    ON rm.recruit_id = r.recruit_id
                JOIN posts p
                    ON r.post_id = p.post_id
                WHERE rm.member_id = %s
                    AND rm.status = 'JOINED'
                    AND p.deleted_at IS NULL
                ORDER BY r.created_at DESC NULLS LAST,
                            r.recruit_id DESC
                LIMIT 20
                """,
                (member_id,)
            )

            return cursor.fetchall()
