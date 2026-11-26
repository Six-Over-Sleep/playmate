-- PLAYMATE: 과정·기수별 게시판
-- 적용 대상: feature/80-board-beta (develop 기반)
-- 재실행해도 같은 과정·기수의 게시판을 중복 생성하지 않습니다.
-- 운영 DB에 적용하기 전 백업을 권장합니다.

BEGIN;

-- 기존 boards 테이블에 과정·기수 구분만 추가합니다.
ALTER TABLE boards
    ADD COLUMN IF NOT EXISTS course_code VARCHAR(30);
ALTER TABLE boards
    ADD COLUMN IF NOT EXISTS cohort INTEGER;

-- 동일 과정·기수당 게시판 1개를 DB에서 보장합니다.
CREATE UNIQUE INDEX IF NOT EXISTS uq_boards_course_cohort
    ON boards (course_code, cohort)
    WHERE course_code IS NOT NULL AND cohort IS NOT NULL;

-- 기존 회원 데이터에 존재하는 과정·기수 조합을 초기 생성합니다.
-- 과정 이름은 현재 MemberSignup의 네 가지 트랙과 일치합니다.
WITH groups AS (
    SELECT DISTINCT course, cohort
    FROM members
    WHERE course IN ('family-ai', 'multi-agent', 'data-engineering', 'data-ml')
      AND cohort IS NOT NULL
      AND cohort >= 1
)
INSERT INTO boards (
    board_name, description, creation_reason, created_by,
    course_code, cohort, is_default
)
SELECT
    CASE g.course
        WHEN 'family-ai' THEN '패밀리 AI'
        WHEN 'multi-agent' THEN '멀티 에이전트'
        WHEN 'data-engineering' THEN '데이터 엔지니어링'
        WHEN 'data-ml' THEN '데이터·머신러닝'
    END || ' ' || g.cohort || '기',
    '같은 과정·기수 수강생을 위한 게시판입니다. 다른 과정에서는 열람만 가능합니다.',
    '회원 과정·기수 기준 자동 생성',
    NULL,
    g.course,
    g.cohort,
    FALSE
FROM groups AS g
ON CONFLICT DO NOTHING;

COMMIT;

-- 생성 결과 검증 (마이그레이션 실행 후 확인)
SELECT board_id, board_name, course_code, cohort, description
FROM boards
WHERE course_code IS NOT NULL
ORDER BY course_code, cohort;

-- 만약 동일한 이름의 일반 게시판이 먼저 존재한다면 자동 연결하지 않습니다.
-- 아래 쿼리 결과가 있으면 수동 확인이 필요합니다.
WITH expected AS (
    SELECT DISTINCT
        course,
        cohort,
        CASE course
            WHEN 'family-ai' THEN '패밀리 AI'
            WHEN 'multi-agent' THEN '멀티 에이전트'
            WHEN 'data-engineering' THEN '데이터 엔지니어링'
            WHEN 'data-ml' THEN '데이터·머신러닝'
        END || ' ' || cohort || '기' AS expected_name
    FROM members
    WHERE course IN ('family-ai', 'multi-agent', 'data-engineering', 'data-ml')
      AND cohort IS NOT NULL AND cohort >= 1
)
SELECT e.course, e.cohort, e.expected_name
FROM expected e
LEFT JOIN boards b ON b.course_code = e.course AND b.cohort = e.cohort
WHERE b.board_id IS NULL;
