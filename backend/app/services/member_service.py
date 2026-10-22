# Discord 회원 정보 조회 및 신규 회원가입을 처리하는 Service
# PostgreSQL에서 회원을 조회하거나 저장하고 결과를 반환함.
from psycopg.rows import dict_row

# DB 연결 함수와 회원가입 요청 스키마 불러오기
from app.core.database import get_db_connection
from app.schemas.member import MemberSignup


# 1. Discord ID로 기존 회원 조회
def get_member(discord_id: str) -> dict | None:
    """Discord ID로 회원 정보를 조회하고, 회원이 없으면 None을 반환함."""

    # get_db_connection() : PostgreSQL 데이터베이스 연결
    # with : 작업 종료 시 DB 연결 자원을 정리함.
    with get_db_connection() as conn:

        # dict_row : 조회 결과를 튜플이 아닌 딕셔너리 형태로 반환함.
        with conn.cursor(row_factory=dict_row) as cur:

            # members 테이블에서 Discord ID가 일치하는 회원을 조회함.
            # %s : SQL에 전달할 값을 안전하게 바인딩하는 자리 표시자
            cur.execute(
                """
                SELECT
                    member_id,
                    discord_id,
                    nickname,
                    course,
                    cohort,
                    role_code
                FROM members
                WHERE discord_id = %s
                """,
                (discord_id,),
            )

            # fetchone() : 조회된 회원 한 명을 반환함. 없으면 None 반환
            return cur.fetchone()


# 2. 신규 회원 등록
def register_member(
    discord_id: str,
    signup_data: MemberSignup,
) -> dict:
    """Discord 인증 정보와 회원가입 입력값을 DB에 저장하고 회원 정보를 반환함."""

    # 회원정보를 저장하기 위해 DB에 연결함.
    with get_db_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:

            # 신규 회원정보 저장
            # INSERT INTO : members 테이블에 새 회원 데이터 추가
            # RETURNING : INSERT로 생성된 회원 정보를 다시 받아옴.
            cur.execute(
                """
                INSERT INTO members (
                    discord_id,
                    nickname,
                    course,
                    cohort,
                    role_code
                )
                VALUES (%s, %s, %s, %s, %s)
                RETURNING
                    member_id,
                    discord_id,
                    nickname,
                    course,
                    cohort,
                    role_code
                """,
                (
                    discord_id,             # Discord 사용자 고유 ID
                    signup_data.nickname,   # 회원가입 시 입력한 닉네임
                    signup_data.track,      # 선택한 수강 트랙 (DB course 컬럼)
                    signup_data.cohort,     # 수강 기수
                    "USER",                  # 신규 회원의 기본 권한 코드
                ),
            )

            # DB에 등록된 회원 정보를 딕셔너리로 가져옴.
            member = cur.fetchone()

        # commit() : 신규 회원 등록 내용을 DB에 최종 반영함.
        conn.commit()

    # 생성된 회원 정보를 Router에 반환함.
    return member
