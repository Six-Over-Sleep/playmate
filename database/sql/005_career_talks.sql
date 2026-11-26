
-- =========================================
-- PLAYMATE 커리어 톡톡 테이블
-- STEP 12-1
-- =========================================

BEGIN;

-- 커리어 톡톡 추가 정보
CREATE TABLE IF NOT EXISTS career_talks (
    post_id BIGINT PRIMARY KEY
        REFERENCES career_posts(post_id)
        ON DELETE CASCADE,

    -- 선택한 직무
    job_category_code VARCHAR(50),

    -- 현재 취업 상태
    current_status VARCHAR(20),

    -- 직무 코드는 공백 문자열 저장 방지
    CONSTRAINT ck_career_talks_job_category
        CHECK (
            job_category_code IS NULL
            OR BTRIM(job_category_code) <> ''
        ),

    -- 현재 상태에 허용된 코드만 저장
    CONSTRAINT ck_career_talks_status
        CHECK (
            current_status IS NULL
            OR current_status IN (
                'PREPARING',
                'NEW',
                'EXPERIENCED',
                'JOB_CHANGE',
                'OTHER'
            )
        )
);

-- 직무별 검색 인덱스
CREATE INDEX IF NOT EXISTS idx_career_talks_job
    ON career_talks (job_category_code);

-- 현재 상태별 검색 인덱스
CREATE INDEX IF NOT EXISTS idx_career_talks_status
    ON career_talks (current_status);

COMMIT;
