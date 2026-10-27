-- PLAYMATE 커리어 연구소 GUIDE 필수 입력 항목 추가
-- 선행 작업: 008_career_labs.sql 및 010_career_guide_post_type.sql 적용
-- 기존 QUESTION / DISCUSSION 데이터는 변경하지 않음

BEGIN;

ALTER TABLE career_labs
    ADD COLUMN IF NOT EXISTS guide_experience TEXT;

ALTER TABLE career_labs
    ADD COLUMN IF NOT EXISTS guide_advice TEXT;

-- GUIDE에는 경험·근거, 실질적인 조언을 각각 100자 이상 저장한다.
-- 질문·토론에는 GUIDE 전용 필드를 저장하지 않는다.
ALTER TABLE career_labs
    DROP CONSTRAINT IF EXISTS ck_career_labs_guide_fields;

ALTER TABLE career_labs
    ADD CONSTRAINT ck_career_labs_guide_fields
    CHECK (
        (
            post_type = 'GUIDE'
            AND guide_experience IS NOT NULL
            AND CHAR_LENGTH(BTRIM(guide_experience)) >= 100
            AND guide_advice IS NOT NULL
            AND CHAR_LENGTH(BTRIM(guide_advice)) >= 100
        )
        OR (
            post_type <> 'GUIDE'
            AND guide_experience IS NULL
            AND guide_advice IS NULL
        )
    );

COMMIT;

-- 컬럼 추가 확인
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema = current_schema()
  AND table_name = 'career_labs'
  AND column_name IN ('guide_experience', 'guide_advice')
ORDER BY column_name;
