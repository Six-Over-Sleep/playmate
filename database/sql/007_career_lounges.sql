
-- =========================================================
-- PLAYMATE 현직자 라운지
-- STEP 14-1. career_lounges 테이블 생성
-- =========================================================

BEGIN;

-- ---------------------------------------------------------
-- 1. 현직자 라운지 추가 정보 테이블
-- ---------------------------------------------------------

CREATE TABLE IF NOT EXISTS career_lounges (

    -- 게시글 ID (PK + FK)
    post_id BIGINT PRIMARY KEY
        REFERENCES career_posts(post_id)
        ON DELETE CASCADE,

    -- 직무 코드
    -- 예: SOFTWARE_DEVELOPMENT, DATA_AI
    job_category_code VARCHAR(50),

    -- 경력 연차
    -- 0 = 신입 또는 1년 미만
    experience_years SMALLINT,

    -- 회사명 (선택)
    company_name VARCHAR(150),

    -- 경력 연차 유효성 검사
    CONSTRAINT ck_career_lounges_experience
        CHECK (
            experience_years IS NULL
            OR experience_years >= 0
        ),

    -- 직무 코드 공백 방지
    CONSTRAINT ck_career_lounges_job_category
        CHECK (
            job_category_code IS NULL
            OR BTRIM(job_category_code) <> ''
        ),

    -- 회사명 공백 방지
    CONSTRAINT ck_career_lounges_company_name
        CHECK (
            company_name IS NULL
            OR BTRIM(company_name) <> ''
        )
);


-- ---------------------------------------------------------
-- 2. 직무별 조회 인덱스
-- ---------------------------------------------------------

CREATE INDEX IF NOT EXISTS idx_career_lounges_job
    ON career_lounges (job_category_code);


-- ---------------------------------------------------------
-- 3. 경력 연차별 조회 인덱스
-- ---------------------------------------------------------

CREATE INDEX IF NOT EXISTS idx_career_lounges_experience
    ON career_lounges (experience_years);


COMMIT;
