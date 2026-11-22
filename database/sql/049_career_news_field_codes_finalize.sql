-- 기존 DB의 STEP 1~4(백업, field_codes 추가, 데이터 이전, 양방향 EXCEPT 검증)가
-- 완료된 뒤 실행하는 비파괴 보강 마이그레이션입니다.
-- 기존 career_news_fields는 여기서 삭제하지 않습니다.
-- 주의: 본 스크립트 실행 중에는 뉴스 수집 작업을 일시 중지하세요.
BEGIN;

ALTER TABLE career_news
    ADD COLUMN IF NOT EXISTS field_codes TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[];

-- 예전 매핑 테이블이 남아 있다면 기존 배열의 값까지 보존하면서 누락된 분야만 보충합니다.
DO $migration$
BEGIN
    IF to_regclass('career_news_fields') IS NOT NULL THEN
        UPDATE career_news AS n
        SET field_codes = ARRAY(
            SELECT DISTINCT code
            FROM (
                SELECT unnest(n.field_codes) AS code
                UNION ALL
                SELECT f.field_code AS code
                FROM career_news_fields AS f
                WHERE f.news_id = n.news_id
            ) all_codes
            ORDER BY code
        )
        WHERE EXISTS (
            SELECT 1 FROM career_news_fields f
            WHERE f.news_id = n.news_id
              AND NOT (f.field_code = ANY(n.field_codes))
        );
    END IF;
END
$migration$;

-- 허용된 직무 코드만 배열에 저장하도록 기존 제약조건을 대체합니다.
ALTER TABLE career_news DROP CONSTRAINT IF EXISTS ck_career_news_field_codes;
ALTER TABLE career_news
    ADD CONSTRAINT ck_career_news_field_codes CHECK (
        field_codes <@ ARRAY[
            'data_ai', 'backend', 'frontend', 'mobile',
            'cloud_infra', 'security', 'qa_test', 'it_product'
        ]::TEXT[]
    );

CREATE INDEX IF NOT EXISTS idx_career_news_field_codes
    ON career_news USING GIN (field_codes);

COMMIT;

-- 결과 확인 (분야 매핑 수와 등록된 뉴스 개수)
SELECT COUNT(*) AS news_count,
       COALESCE(SUM(cardinality(field_codes)), 0) AS field_mapping_count
FROM career_news;
