-- PLAYMATE 취업 커뮤니티 게시글 확장 테이블 (STEP 11-5)
-- 적용 전 검토용: 기존 posts / boards / members / comments 테이블은 변경하지 않습니다.
-- 게시글 본문과 작성자는 기존 posts에 저장합니다.
-- 취업 커뮤니티 글은 posts.post_type='CAREER', posts.board_id=NULL로 생성할 예정입니다.
-- 실제 posts INSERT와 career_posts/career_reviews INSERT는 서비스에서 동일 트랜잭션으로 처리해야 합니다.

BEGIN;

-- 취업 게시글 공통 분류: posts와 1:1
CREATE TABLE career_posts (
    post_id BIGINT PRIMARY KEY
        REFERENCES posts(post_id) ON DELETE CASCADE,
    category_code VARCHAR(20) NOT NULL,
    subcategory_code VARCHAR(50) NOT NULL,
    is_anonymous BOOLEAN NOT NULL DEFAULT TRUE,

    -- 실제 프론트엔드 메인 게시판 ID와 동일한 코드 사용
    CONSTRAINT ck_career_posts_category
        CHECK (category_code IN ('reviews', 'talk', 'lounge', 'lab')),
    CONSTRAINT ck_career_posts_subcategory_not_blank
        CHECK (BTRIM(subcategory_code) <> '')
);

-- 취준 도감의 추가 입력 정보: career_posts와 1:1
CREATE TABLE career_reviews (
    post_id BIGINT PRIMARY KEY
        REFERENCES career_posts(post_id) ON DELETE CASCADE,
    company_name VARCHAR(150),
    is_company_private BOOLEAN NOT NULL DEFAULT FALSE,
    job_category_code VARCHAR(50) NOT NULL,
    application_type VARCHAR(20),
    process_stage VARCHAR(30) NOT NULL,
    process_result VARCHAR(20) NOT NULL,
    process_date DATE,
    interview_format VARCHAR(50),

    CONSTRAINT ck_career_reviews_job_category_not_blank
        CHECK (BTRIM(job_category_code) <> ''),
    CONSTRAINT ck_career_reviews_application_type
        CHECK (application_type IS NULL OR application_type IN ('NEW', 'EXPERIENCED')),
    CONSTRAINT ck_career_reviews_process_stage
        CHECK (process_stage IN ('DOCUMENT', 'CODING_TEST', 'ASSIGNMENT', 'INTERVIEW', 'FINAL')),
    CONSTRAINT ck_career_reviews_process_result
        CHECK (process_result IN ('PASS', 'FAIL', 'PENDING'))
);

-- 하위 게시판 목록 검색에 사용할 인덱스
CREATE INDEX idx_career_posts_category_subcategory
    ON career_posts (category_code, subcategory_code, post_id DESC);

-- 취업 후기 검색 및 필터링에 사용할 인덱스
CREATE INDEX idx_career_reviews_job_stage_result
    ON career_reviews (job_category_code, process_stage, process_result);

COMMIT;

-- 후속 API 개발 시 유의사항
-- 1. 취준 도감 작성에서는 posts + career_posts + career_reviews를 하나의 트랜잭션으로 INSERT.
-- 2. posts.body의 최소 500자 검증은 FastAPI에서 처리 (기존 posts는 변경하지 않음).
-- 3. 인증 없이 is_anonymous만으로 닉네임이 가려지지는 않으므로, 응답 SQL에서 표시 이름 분기 필요.
-- 4. career_reviews는 category_code='reviews'인 글에만 연결되도록 서비스 계층에서 검증.
-- 5. 직무 코드 마스터 테이블 및 subcategory_code 표준 목록은 API 계약 확정 시 추가.
