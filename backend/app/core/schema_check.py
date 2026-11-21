"""배포 전 필수 스키마·XP 정책 검사 (읽기 전용).

새 버전이 트래픽을 받기 전에 한 번만 실행한다. API 요청마다 실행하지 않는다.
- 배포 담당자: python -m backend.scripts.check_deploy_schema   (누락 시 종료 코드 1)
- 앱 기동: PLAYMATE_SCHEMA_CHECK=strict이면 누락 시 기동 실패(운영 기본값)
- 기동 결과: GET /health/schema (상세 내용은 서버 로그와 위 스크립트로 확인)

검사 순서: 기본 스키마(000·001) → 023 → 024 → 025 → 027 → 037 → 044 → 045.
정책 값은 읽기만 한다. 누락을 고정 기본값으로 채우지 않는다.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# 000·001이 만드는 기본 테이블 (게시판·회원·XP 이력)
# 게시판 이미지(post_images)는 037에서 post_attachments로 옮겨졌고 044에서 호환 뷰를 제거했다.
# 좋아요·스크랩·신고(post_likes·post_scraps·post_reports)는 045에서 post_reactions로 합쳤다.
BASE_TABLES = (
    "members", "posts", "comments", "boards",
    "member_levels", "member_xp_history", "recruits", "recruit_members",
)
# 기본 테이블 중 코드가 직접 쓰는 컬럼 (예전 로컬 DB에 빠져 있던 것)
BASE_COLUMNS = (
    ("member_xp_history", "history_id"),
    ("member_xp_history", "created_at"),
    ("comments", "parent_comment_id"),
    ("comments", "reply_to_comment_id"),
    ("recruits", "details"),
    ("recruit_programs", "meetup_curriculum_version"),
    ("recruit_programs", "meetup_curriculum_items"),
    ("member_board_visit_events", "board_id"),
)
# 위 컬럼 중 000·026이 아닌 별도 마이그레이션이 만드는 것: 누락 시 표시할 (출처, 안내할 SQL 파일)
COLUMN_FIXES = {
    ("comments", "reply_to_comment_id"): ("041", "database/sql/041_comment_reply_target.sql 적용"),
    ("recruits", "details"): ("042", "database/sql/042_recruit_category_details_consolidation.sql 적용"),
    ("recruit_programs", "meetup_curriculum_version"): ("043", "database/sql/043_recruit_curricula_consolidation.sql 적용"),
    ("recruit_programs", "meetup_curriculum_items"): ("043", "database/sql/043_recruit_curricula_consolidation.sql 적용"),
    ("member_board_visit_events", "board_id"): ("044", "database/sql/044_board_table_cleanup.sql 적용(회원별 방문 횟수 이관)"),
}
BASE_COLUMN_FIX = ("000·001", "database/sql/000_baseline_schema.sql·026_baseline_followups.sql 재실행")
# 027 지급 한도
REQUIRED_LIMITS = ("POST_DAILY_COUNT", "COMMENT_DAILY_COUNT", "POST_LIKE_XP_PER_POST")


def required_award_types() -> tuple[str, ...]:
    """코드가 지급 시 읽는 xp_award_policies 행. 연속 출석 STREAK_<일수>는 선택(없으면 보너스 없음)."""
    from backend.app.services.meetup_xp_service import MEETUP_REWARD_TYPES
    from backend.app.services.skill_xp_service import SKILL_ACTIVITY_TYPES

    types = {
        "ATTEND", "POST", "COMMENT", "REPLY", "POST_LIKE",
        "CAREER_DOCUMENT", "CAREER_INTERVIEW", "CAREER_SUCCESS", "CAREER_GUIDE", "CAREER_SPEC_PUBLIC",
    }
    types.update(f"MEETUP_{reward}" for reward in MEETUP_REWARD_TYPES)
    types.update(f"SKILL_{kind}" for kind in SKILL_ACTIVITY_TYPES)
    return tuple(sorted(types))


@dataclass
class Issue:
    level: str          # "error" 배포 차단 / "warning" 호환 동작
    step: str           # 000·001, 023, 024, 025, 027
    message: str
    fix: str


@dataclass
class Report:
    issues: list[Issue] = field(default_factory=list)
    checked: list[str] = field(default_factory=list)

    @property
    def errors(self) -> list[Issue]:
        return [issue for issue in self.issues if issue.level == "error"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def lines(self) -> list[str]:
        out = [f"검사: {' → '.join(self.checked)}"]
        if not self.issues:
            out.append("결과: 필수 스키마·정책 모두 확인")
        for issue in self.issues:
            mark = "오류" if issue.level == "error" else "경고"
            out.append(f"[{mark}][{issue.step}] {issue.message}\n    조치: {issue.fix}")
        return out


def _rows(cursor, sql, params=None):
    cursor.execute(sql, params)
    return cursor.fetchall()


def check_schema(cursor) -> Report:
    """읽기 전용 커서로 필수 스키마·정책을 검사한다(쓰기 없음)."""
    report = Report()
    tables = {row[0] for row in _rows(
        cursor, "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")}
    columns = {(row[0], row[1]) for row in _rows(
        cursor, "SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = 'public'")}

    # 1. 기본 스키마
    report.checked.append("000·001")
    for table in BASE_TABLES:
        if table not in tables:
            report.issues.append(Issue("error", "000·001", f"기본 테이블 {table} 없음",
                                       "database/sql/000_baseline_schema.sql, 001_board_mvp.sql 적용"))
    if "recruit_programs" not in tables:
        report.issues.append(Issue("error", "012", "recruit_programs 테이블 없음",
                                   "database/sql/012_recruit_programs.sql 적용 후 043 확인"))
    for table, column in BASE_COLUMNS:
        if table in tables and (table, column) not in columns:
            step, fix = COLUMN_FIXES.get((table, column), BASE_COLUMN_FIX)
            report.issues.append(Issue("error", step, f"{table}.{column} 컬럼 없음", fix))
    if "boards" in tables:
        for column in ("course_code", "cohort"):
            if ("boards", column) not in columns:
                report.issues.append(Issue("error", "018", f"boards.{column} 컬럼 없음",
                                           "database/sql/018_course_cohort_boards.sql 적용"))

    # 2. 023 지급량
    report.checked.append("023")
    if "xp_award_policies" not in tables:
        report.issues.append(Issue("error", "023", "xp_award_policies 테이블 없음",
                                   "database/sql/023_xp_award_policies.sql 적용 후 027 적용"))
    else:
        present = {row[0] for row in _rows(cursor, "SELECT activity_type FROM xp_award_policies")}
        for name in required_award_types():
            if name not in present:
                source = "027_xp_rule_policies.sql" if name.startswith("SKILL_") else "023_xp_award_policies.sql"
                report.issues.append(Issue("error", "023", f"지급 정책 행 {name} 없음",
                                           f"database/sql/{source} 재실행(설정값 유지, 누락 행만 추가)"))

    # 3. 024 회원별 방문 (없으면 기존 기본 정렬·전체 통계로 동작)
    #    회원별 횟수는 044부터 방문 기록(member_board_visit_events.board_id)에서 집계한다.
    report.checked.append("024")
    if "member_board_visit_events" not in tables:
        report.issues.append(Issue("warning", "024", "member_board_visit_events 없음 — 기본 게시판 정렬·전체 방문 통계로 동작",
                                   "회원별 정렬이 필요하면 database/sql/024_member_board_visits.sql, 044_board_table_cleanup.sql 적용"))

    # 4. 025 레벨 기준
    report.checked.append("025")
    if "level_policies" not in tables:
        report.issues.append(Issue("error", "025", "level_policies 테이블 없음(레벨 계산 API 503)",
                                   "database/sql/025_level_policies.sql 적용"))
    else:
        from fastapi import HTTPException
        from backend.app.services.xp_service import validate_level_thresholds

        for level_type in ("OVERALL", "SKILL"):
            rows = _rows(cursor, "SELECT level, min_xp FROM level_policies WHERE level_type = %s", (level_type,))
            try:
                thresholds = validate_level_thresholds(rows)
            except HTTPException:
                report.issues.append(Issue("error", "025", f"{level_type} 레벨 기준이 비었거나 1레벨 0XP부터 이어지지 않음",
                                           "level_policies 행을 확인하거나 025 재실행(누락 행만 추가)"))
                continue
            if level_type == "OVERALL" and len(thresholds) > 4:
                capped = _rows(cursor, """
                    SELECT 1 FROM pg_constraint
                    WHERE conrelid = 'public.member_levels'::regclass AND contype = 'c'
                      AND pg_get_constraintdef(oid) LIKE '%%level <= 4%%'""")
                if capped:
                    report.issues.append(Issue("error", "025", "종합 레벨 5 이상 정책이 있으나 member_levels 레벨 상한(4) 제약이 남아 있음",
                                               "database/sql/025_level_policies.sql 재실행(제약 완화)"))

    # 5. 027 지급 한도
    report.checked.append("027")
    if "xp_limit_policies" not in tables:
        report.issues.append(Issue("error", "027", "xp_limit_policies 테이블 없음(글·댓글 XP 누락, 좋아요 503)",
                                   "database/sql/027_xp_rule_policies.sql 적용"))
    else:
        present = {row[0] for row in _rows(cursor, "SELECT limit_key FROM xp_limit_policies")}
        for key in REQUIRED_LIMITS:
            if key not in present:
                report.issues.append(Issue("error", "027", f"지급 한도 행 {key} 없음",
                                           "database/sql/027_xp_rule_policies.sql 재실행(설정값 유지, 누락 행만 추가)"))

    # 6. 037 게시판 이미지 저장 위치
    report.checked.append("037")
    if "post_attachments" not in tables:
        report.issues.append(Issue("error", "037", "post_attachments 테이블 없음(게시판 이미지 저장·조회 실패)",
                                   "database/sql/037_career_board_consolidation.sql 적용 후 044 적용"))

    # 7. 044 게시판 정리: 방문 기록 board_id는 BASE_COLUMNS에서 확인한다(024 테이블이 있을 때).
    report.checked.append("044")

    # 8. 045 게시글 반응(좋아요·스크랩·신고)
    report.checked.append("045")
    if "post_reactions" not in tables:
        report.issues.append(Issue("error", "045", "post_reactions 테이블 없음(좋아요·스크랩·신고 실패)",
                                   "database/sql/045_post_reactions.sql 적용"))
    return report


def run_check() -> Report:
    """설정된 DB에 읽기 전용으로 접속해 검사한다."""
    from backend.app.core.database import get_db_connection

    with get_db_connection() as conn:
        conn.read_only = True
        with conn.cursor() as cursor:
            return check_schema(cursor)


def check_mode() -> str:
    """off | warn | strict. 운영(APP_ENV 미설정 포함) 기본 strict, 개발 warn, 테스트 off."""
    mode = os.getenv("PLAYMATE_SCHEMA_CHECK", "").strip().lower()
    if mode in {"off", "warn", "strict"}:
        return mode
    env = os.getenv("APP_ENV", "production").lower()
    return {"test": "off", "development": "warn"}.get(env, "strict")


def startup_check() -> dict:
    """앱 기동 시 1회 실행. strict에서 오류가 있으면 RuntimeError로 기동을 막는다."""
    mode = check_mode()
    if mode == "off":
        return {"status": "skipped"}
    try:
        report = run_check()
    except Exception as exc:  # DB 접속 실패도 배포 차단 대상
        logger.error("배포 스키마 검사를 실행하지 못했습니다: %s", type(exc).__name__)
        if mode == "strict":
            raise RuntimeError("배포 스키마 검사 실패: DB에 접속할 수 없습니다.") from exc
        return {"status": "unavailable"}
    for line in report.lines():
        (logger.warning if report.issues else logger.info)("[schema-check] %s", line)
    if not report.ok and mode == "strict":
        raise RuntimeError(
            "필수 스키마·XP 정책 누락으로 기동을 중단합니다: "
            + "; ".join(issue.message for issue in report.errors)
        )
    return {
        "status": "ok" if report.ok else "error",
        "errors": len(report.errors),
        "warnings": len(report.issues) - len(report.errors),
    }
