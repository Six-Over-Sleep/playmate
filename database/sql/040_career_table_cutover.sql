-- 040: 취업 분류·상세의 기준 저장소를 career로 전환
-- 선행 조건: 037, 038, 039 적용 완료
-- 먼저 로컬 테스트 DB에서 검증한다.
-- 뉴스·채용공고·수집 테이블은 변경하지 않는다.
-- 한 번만 적용하는 마이그레이션이다.

BEGIN;

SET LOCAL lock_timeout = '10s';
SET LOCAL statement_timeout = '120s';
SET LOCAL search_path = pg_catalog, public, pg_temp;

LOCK TABLE
    public.posts,
    public.career,
    public.career_lab_poll_votes,
    public.post_attachments
IN ACCESS EXCLUSIVE MODE;

-- =========================================================
-- 1. 원본과 이관 데이터가 같은지 확인
-- =========================================================

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM (
            SELECT
                post_id,
                career_category,
                career_subcategory,
                career_details,
                poll_options
            FROM public.posts
            WHERE career_category IS NOT NULL
        ) AS p
        FULL JOIN public.career AS c USING (post_id)
        WHERE p.post_id IS NULL
           OR c.post_id IS NULL
           OR ROW(
               p.career_category,
               p.career_subcategory,
               p.career_details,
               p.poll_options
           ) IS DISTINCT FROM ROW(
               c.category_code,
               c.subcategory_code,
               c.details,
               c.poll_options
           )
    ) THEN
        RAISE EXCEPTION
            'posts와 career 데이터가 다릅니다. 전환을 중단합니다.';
    END IF;
END;
$$;

-- 기존 인터페이스가 반환하던 데이터를 임시 보관한다.
-- 영구 테이블이 아니며 COMMIT 시 제거된다.
CREATE TEMP TABLE career_040_expected (
    relation_name TEXT NOT NULL,
    data JSONB NOT NULL
) ON COMMIT DROP;

DO $$
DECLARE
    relation_name TEXT;
BEGIN
    FOREACH relation_name IN ARRAY ARRAY[
        'career_posts',
        'career_reviews',
        'career_talks',
        'career_lounges',
        'career_labs',
        'career_lab_poll_options',
        'career_talk_attachments',
        'post_images',
        'career_lab_poll_votes'
    ]
    LOOP
        EXECUTE format(
            'INSERT INTO pg_temp.career_040_expected
             SELECT %L, to_jsonb(t) FROM public.%I AS t',
            relation_name,
            relation_name
        );
    END LOOP;
END;
$$;

-- =========================================================
-- 2. posts에 연결된 임시 동기화·취업 검증 트리거 제거
--    동일한 검증을 아래에서 career에 연결한다.
-- =========================================================

DROP TRIGGER trg_posts_sync_career ON public.posts;
DROP FUNCTION public.playmate_sync_career_from_posts();

DROP TRIGGER trg_posts_poll_options_guard ON public.posts;
DROP TRIGGER trg_career_complete ON public.posts;

-- =========================================================
-- 3. 기존 조회 인터페이스를 career 기준으로 전환
--    CREATE OR REPLACE는 기존 뷰 권한과 트리거를 유지한다.
-- =========================================================

CREATE OR REPLACE VIEW public.career_posts AS
SELECT
    c.post_id,
    c.category_code,
    c.subcategory_code,
    p.is_anonymous
FROM public.career AS c
JOIN public.posts AS p ON p.post_id = c.post_id;

CREATE OR REPLACE VIEW public.career_reviews AS
SELECT
    post_id,
    (details ->> 'company_name')::VARCHAR(150)
        AS company_name,
    (details ->> 'is_company_private')::BOOLEAN
        AS is_company_private,
    (details ->> 'job_category_code')::VARCHAR(50)
        AS job_category_code,
    (details ->> 'application_type')::VARCHAR(20)
        AS application_type,
    (details ->> 'process_stage')::VARCHAR(30)
        AS process_stage,
    (details ->> 'process_result')::VARCHAR(20)
        AS process_result,
    (details ->> 'process_date')::DATE
        AS process_date,
    (details ->> 'interview_format')::VARCHAR(50)
        AS interview_format
FROM public.career
WHERE category_code = 'reviews'
  AND details <> '{}'::JSONB;

CREATE OR REPLACE VIEW public.career_talks AS
SELECT
    post_id,
    (details ->> 'job_category_code')::VARCHAR(50)
        AS job_category_code,
    (details ->> 'current_status')::VARCHAR(20)
        AS current_status
FROM public.career
WHERE category_code = 'talk'
  AND details <> '{}'::JSONB;

CREATE OR REPLACE VIEW public.career_lounges AS
SELECT
    post_id,
    (details ->> 'job_category_code')::VARCHAR(50)
        AS job_category_code,
    (details ->> 'experience_years')::SMALLINT
        AS experience_years,
    (details ->> 'company_name')::VARCHAR(150)
        AS company_name
FROM public.career
WHERE category_code = 'lounge'
  AND details <> '{}'::JSONB;

CREATE OR REPLACE VIEW public.career_labs AS
SELECT
    post_id,
    (details ->> 'post_type')::VARCHAR(20)
        AS post_type,
    (details ->> 'is_resolved')::BOOLEAN
        AS is_resolved,
    (details ->> 'guide_experience')::TEXT
        AS guide_experience,
    (details ->> 'guide_advice')::TEXT
        AS guide_advice
FROM public.career
WHERE category_code = 'lab'
  AND details <> '{}'::JSONB;

CREATE OR REPLACE VIEW public.career_lab_poll_options AS
SELECT
    x.option_id,
    c.post_id,
    x.option_text,
    x.display_order
FROM public.career AS c
CROSS JOIN LATERAL jsonb_to_recordset(c.poll_options)
    AS x(
        option_id BIGINT,
        option_text VARCHAR(200),
        display_order SMALLINT
    );

ALTER VIEW public.career_posts
    ALTER COLUMN is_anonymous SET DEFAULT TRUE;

ALTER VIEW public.career_reviews
    ALTER COLUMN is_company_private SET DEFAULT FALSE;

ALTER VIEW public.career_labs
    ALTER COLUMN is_resolved SET DEFAULT FALSE;

-- =========================================================
-- 4. 기존 취업 저장 인터페이스를 career로 전환
-- =========================================================

CREATE OR REPLACE FUNCTION public.playmate_career_compat_write()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    expected_category TEXT;
    parent_type TEXT;
    current_career public.career%ROWTYPE;
    has_career BOOLEAN;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION
            '게시글 삭제는 posts의 논리 삭제 경로를 사용하세요.';
    END IF;

    IF TG_OP = 'UPDATE'
       AND NEW.post_id IS DISTINCT FROM OLD.post_id THEN
        RAISE EXCEPTION '게시글 ID는 변경할 수 없습니다.';
    END IF;

    -- 기존 서비스와 같은 순서로 부모 게시글을 먼저 잠근다.
    SELECT p.post_type
    INTO parent_type
    FROM public.posts AS p
    WHERE p.post_id = NEW.post_id
    FOR UPDATE;

    IF NOT FOUND
       OR parent_type IS DISTINCT FROM 'CAREER' THEN
        RAISE EXCEPTION '취업 게시글 부모가 필요합니다.'
            USING ERRCODE = '23503';
    END IF;

    SELECT *
    INTO current_career
    FROM public.career
    WHERE post_id = NEW.post_id
    FOR UPDATE;

    has_career := FOUND;

    IF TG_TABLE_NAME = 'career_posts' THEN
        IF NEW.is_anonymous IS NULL THEN
            RAISE EXCEPTION '익명 설정은 필수입니다.'
                USING ERRCODE = '23502';
        END IF;

        IF TG_OP = 'INSERT' THEN
            IF has_career THEN
                RAISE EXCEPTION '취업 분류가 이미 존재합니다.'
                    USING ERRCODE = '23505';
            END IF;

            -- 기존 코드는 같은 트랜잭션의 다음 문장에서
            -- 유형별 상세를 저장한다.
            INSERT INTO public.career (
                post_id,
                category_code,
                subcategory_code
            )
            VALUES (
                NEW.post_id,
                NEW.category_code,
                NEW.subcategory_code
            );
        ELSE
            IF NOT has_career THEN
                RETURN NULL;
            END IF;

            IF NEW.category_code
               IS DISTINCT FROM current_career.category_code THEN
                RAISE EXCEPTION '취업 게시글 유형은 변경할 수 없습니다.';
            END IF;

            UPDATE public.career
            SET subcategory_code = NEW.subcategory_code
            WHERE post_id = NEW.post_id;
        END IF;

        -- 익명 여부는 공통 posts에만 저장한다.
        UPDATE public.posts
        SET is_anonymous = NEW.is_anonymous
        WHERE post_id = NEW.post_id;

    ELSE
        expected_category := CASE TG_TABLE_NAME
            WHEN 'career_reviews' THEN 'reviews'
            WHEN 'career_talks' THEN 'talk'
            WHEN 'career_lounges' THEN 'lounge'
            WHEN 'career_labs' THEN 'lab'
            ELSE NULL
        END;

        IF expected_category IS NULL
           OR NOT has_career
           OR current_career.category_code
              IS DISTINCT FROM expected_category THEN
            RAISE EXCEPTION '취업 분류와 상세 유형이 다릅니다.'
                USING ERRCODE = '23514';
        END IF;

        IF TG_OP = 'INSERT'
           AND current_career.details <> '{}'::JSONB THEN
            RAISE EXCEPTION '취업 상세가 이미 존재합니다.'
                USING ERRCODE = '23505';
        END IF;

        UPDATE public.career
        SET details = to_jsonb(NEW) - 'post_id'
        WHERE post_id = NEW.post_id;
    END IF;

    RETURN NEW;
END;
$$;

-- =========================================================
-- 5. 취업 부모 및 상세 완성 검증
-- =========================================================

CREATE FUNCTION public.playmate_career_parent_guard()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF TG_OP = 'UPDATE'
       AND (
           NEW.post_id IS DISTINCT FROM OLD.post_id
           OR NEW.category_code IS DISTINCT FROM OLD.category_code
       ) THEN
        RAISE EXCEPTION '취업 게시글 ID와 유형은 변경할 수 없습니다.'
            USING ERRCODE = '23514';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM public.posts
        WHERE post_id = NEW.post_id
          AND post_type = 'CAREER'
    ) THEN
        RAISE EXCEPTION '취업 게시글 부모가 필요합니다.'
            USING ERRCODE = '23503';
    END IF;

    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_career_parent_guard
BEFORE INSERT OR UPDATE ON public.career
FOR EACH ROW
EXECUTE FUNCTION public.playmate_career_parent_guard();

CREATE OR REPLACE FUNCTION public.playmate_career_complete_guard()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM public.career
        WHERE post_id = NEW.post_id
          AND details = '{}'::JSONB
    ) THEN
        RAISE EXCEPTION
            '트랜잭션 종료 전 취업 상세를 저장해야 합니다.'
            USING ERRCODE = '23514';
    END IF;

    RETURN NULL;
END;
$$;

CREATE CONSTRAINT TRIGGER trg_career_complete
AFTER INSERT OR UPDATE ON public.career
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW
EXECUTE FUNCTION public.playmate_career_complete_guard();

-- =========================================================
-- 6. 투표 검증을 career 기준으로 전환
-- =========================================================

ALTER TABLE public.career_lab_poll_votes
    DROP CONSTRAINT fk_career_votes_post;

ALTER TABLE public.career_lab_poll_votes
    ADD CONSTRAINT fk_career_votes_career
    FOREIGN KEY (post_id)
    REFERENCES public.career(post_id)
    ON DELETE CASCADE;

CREATE OR REPLACE FUNCTION public.playmate_career_vote_guard()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    current_career public.career%ROWTYPE;
    parent_deleted_at TIMESTAMP;
BEGIN
    SELECT deleted_at
    INTO parent_deleted_at
    FROM public.posts
    WHERE post_id = NEW.post_id
    FOR UPDATE;

    IF NOT FOUND OR parent_deleted_at IS NOT NULL THEN
        RAISE EXCEPTION '투표 가능한 게시글이 아닙니다.'
            USING ERRCODE = '23514';
    END IF;

    SELECT *
    INTO current_career
    FROM public.career
    WHERE post_id = NEW.post_id
    FOR UPDATE;

    IF NOT FOUND
       OR current_career.category_code IS DISTINCT FROM 'lab'
       OR current_career.details ->> 'post_type'
          IS DISTINCT FROM 'DISCUSSION'
       OR NOT EXISTS (
           SELECT 1
           FROM jsonb_array_elements(
               current_career.poll_options
           ) AS option
           WHERE (option ->> 'option_id')::BIGINT = NEW.option_id
       ) THEN
        RAISE EXCEPTION '유효하지 않은 투표 선택지입니다.'
            USING ERRCODE = '23514';
    END IF;

    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION public.playmate_poll_options_guard()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF (
        NEW.poll_options IS DISTINCT FROM OLD.poll_options
        OR NEW.category_code IS DISTINCT FROM OLD.category_code
        OR NEW.details ->> 'post_type'
           IS DISTINCT FROM OLD.details ->> 'post_type'
    )
    AND EXISTS (
        SELECT 1
        FROM public.career_lab_poll_votes
        WHERE post_id = OLD.post_id
    ) THEN
        RAISE EXCEPTION
            '투표가 시작된 후 선택지와 유형을 변경할 수 없습니다.'
            USING ERRCODE = '23514';
    END IF;

    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_career_poll_options_guard
BEFORE UPDATE ON public.career
FOR EACH ROW
EXECUTE FUNCTION public.playmate_poll_options_guard();

CREATE OR REPLACE FUNCTION public.playmate_poll_compat_write()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    current_career public.career%ROWTYPE;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION
            '기존 인터페이스에서는 투표 선택지를 변경할 수 없습니다.';
    END IF;

    PERFORM 1
    FROM public.posts
    WHERE post_id = NEW.post_id
    FOR UPDATE;

    SELECT *
    INTO current_career
    FROM public.career
    WHERE post_id = NEW.post_id
    FOR UPDATE;

    IF NOT FOUND
       OR current_career.category_code IS DISTINCT FROM 'lab'
       OR current_career.details ->> 'post_type'
          IS DISTINCT FROM 'DISCUSSION' THEN
        RAISE EXCEPTION '토론 게시글이 필요합니다.'
            USING ERRCODE = '23514';
    END IF;

    NEW.option_id := COALESCE(
        NEW.option_id,
        nextval('public.career_poll_option_id_seq')
    );

    UPDATE public.career
    SET poll_options = poll_options || jsonb_build_array(
        jsonb_build_object(
            'option_id', NEW.option_id,
            'option_text', NEW.option_text,
            'display_order', NEW.display_order
        )
    )
    WHERE post_id = NEW.post_id;

    RETURN NEW;
END;
$$;

-- =========================================================
-- 7. 첨부 저장의 취업 분류 확인을 career로 전환
--    기존 첨부 ID와 파일 경로는 유지한다.
-- =========================================================

CREATE OR REPLACE FUNCTION public.playmate_attachment_compat_write()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    scope TEXT;
    target_id BIGINT;
BEGIN
    scope := CASE TG_TABLE_NAME
        WHEN 'post_images' THEN 'BOARD'
        WHEN 'career_talk_attachments' THEN 'CAREER_TALK'
        ELSE NULL
    END;

    IF scope IS NULL THEN
        RAISE EXCEPTION '지원하지 않는 첨부 인터페이스입니다.';
    END IF;

    IF TG_OP = 'DELETE' THEN
        target_id := CASE
            WHEN scope = 'BOARD'
                THEN (to_jsonb(OLD) ->> 'image_id')::BIGINT
            ELSE (to_jsonb(OLD) ->> 'attachment_id')::BIGINT
        END;

        DELETE FROM public.post_attachments
        WHERE attachment_scope = scope
          AND attachment_id = target_id;

        RETURN OLD;
    END IF;

    PERFORM 1
    FROM public.posts
    WHERE post_id = NEW.post_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION '첨부할 게시글이 없습니다.'
            USING ERRCODE = '23503';
    END IF;

    IF scope = 'CAREER_TALK'
       AND NOT EXISTS (
           SELECT 1
           FROM public.career
           WHERE post_id = NEW.post_id
             AND category_code = 'talk'
       ) THEN
        RAISE EXCEPTION '톡톡 게시글이 필요합니다.'
            USING ERRCODE = '23503';
    END IF;

    IF scope = 'BOARD' THEN
        IF TG_OP = 'INSERT' THEN
            NEW.image_id := COALESCE(
                NEW.image_id,
                nextval('public.post_attachment_id_seq')
            );
            NEW.created_at := COALESCE(
                NEW.created_at,
                CURRENT_TIMESTAMP::TIMESTAMP
            );
            NEW.display_order := COALESCE(NEW.display_order, 0);

            INSERT INTO public.post_attachments (
                attachment_scope, attachment_id, post_id,
                original_filename, stored_path, attachment_type,
                content_type, file_size_bytes, display_order,
                created_at, board_created_at
            )
            VALUES (
                scope, NEW.image_id, NEW.post_id,
                NEW.original_name, NEW.stored_name, 'IMAGE',
                NEW.content_type, NEW.file_size, NEW.display_order,
                NEW.created_at AT TIME ZONE 'Asia/Seoul',
                NEW.created_at
            );
        ELSE
            IF NEW.image_id IS DISTINCT FROM OLD.image_id THEN
                RAISE EXCEPTION '첨부 ID는 변경할 수 없습니다.';
            END IF;

            UPDATE public.post_attachments
            SET post_id = NEW.post_id,
                original_filename = NEW.original_name,
                stored_path = NEW.stored_name,
                content_type = NEW.content_type,
                file_size_bytes = NEW.file_size,
                display_order = NEW.display_order,
                board_created_at = NEW.created_at,
                created_at =
                    NEW.created_at AT TIME ZONE 'Asia/Seoul'
            WHERE attachment_scope = scope
              AND attachment_id = OLD.image_id;
        END IF;
    ELSE
        IF TG_OP = 'INSERT' THEN
            NEW.attachment_id := COALESCE(
                NEW.attachment_id,
                nextval('public.post_attachment_id_seq')
            );
            NEW.created_at := COALESCE(NEW.created_at, NOW());

            INSERT INTO public.post_attachments (
                attachment_scope, attachment_id, post_id,
                original_filename, stored_path, attachment_type,
                content_type, file_size_bytes, display_order,
                created_at
            )
            VALUES (
                scope, NEW.attachment_id, NEW.post_id,
                NEW.original_filename, NEW.stored_path,
                NEW.attachment_type, NEW.content_type,
                NEW.file_size_bytes, NEW.display_order,
                NEW.created_at
            );
        ELSE
            IF NEW.attachment_id
               IS DISTINCT FROM OLD.attachment_id THEN
                RAISE EXCEPTION '첨부 ID는 변경할 수 없습니다.';
            END IF;

            UPDATE public.post_attachments
            SET post_id = NEW.post_id,
                original_filename = NEW.original_filename,
                stored_path = NEW.stored_path,
                attachment_type = NEW.attachment_type,
                content_type = NEW.content_type,
                file_size_bytes = NEW.file_size_bytes,
                display_order = NEW.display_order,
                created_at = NEW.created_at
            WHERE attachment_scope = scope
              AND attachment_id = OLD.attachment_id;
        END IF;
    END IF;

    RETURN NEW;
END;
$$;

-- career를 직접 삭제하는 경우에도 취업 첨부를 정리한다.
-- posts 삭제 시 기존 트리거와 함께 실행돼도 중복 삭제는 무해하다.
CREATE TRIGGER trg_career_delete_attachments
BEFORE DELETE ON public.career
FOR EACH ROW
EXECUTE FUNCTION public.playmate_delete_career_attachments();

-- =========================================================
-- 8. 소유자 권한 함수의 임의 사용 제한
-- =========================================================

REVOKE ALL
ON FUNCTION public.playmate_career_compat_write()
FROM PUBLIC;

REVOKE ALL
ON FUNCTION public.playmate_poll_compat_write()
FROM PUBLIC;

REVOKE ALL
ON FUNCTION public.playmate_attachment_compat_write()
FROM PUBLIC;

REVOKE ALL
ON FUNCTION public.playmate_delete_career_attachments()
FROM PUBLIC;

-- 기존 투표 검증 함수는 호출 계정의 권한으로 career를 읽는다.
-- 기존 투표 기록 테이블 사용 계정에 필요한 SELECT만 부여한다.
DO $$
DECLARE
    permission_row RECORD;
BEGIN
    FOR permission_row IN
        SELECT DISTINCT grantee
        FROM information_schema.table_privileges
        WHERE table_schema = 'public'
          AND table_name = 'career_lab_poll_votes'
          AND privilege_type IN ('INSERT', 'UPDATE')
    LOOP
        EXECUTE format(
            'GRANT SELECT ON public.career TO %s',
            CASE
                WHEN permission_row.grantee = 'PUBLIC'
                    THEN 'PUBLIC'
                ELSE quote_ident(permission_row.grantee)
            END
        );
    END LOOP;
END;
$$;

-- =========================================================
-- 9. posts에서 취업 전용 컬럼 제거
--    공통 제목·본문·작성자·익명 여부 등은 유지한다.
-- =========================================================

ALTER TABLE public.posts
    DROP CONSTRAINT ck_posts_career_classification,
    DROP CONSTRAINT ck_posts_career_details,
    DROP CONSTRAINT ck_posts_poll_options;

ALTER TABLE public.posts
    DROP COLUMN career_category,
    DROP COLUMN career_subcategory,
    DROP COLUMN career_details,
    DROP COLUMN poll_options;

-- 관련 posts 인덱스는 해당 컬럼 제거와 함께 제거된다.
-- career의 분류·직무 인덱스는 039에서 이미 생성했다.

-- =========================================================
-- 10. 기존 인터페이스의 결과가 동일한지 최종 검증
-- =========================================================

DO $$
DECLARE
    target_relation TEXT;
    mismatch BOOLEAN;
BEGIN
    FOR target_relation IN
        SELECT DISTINCT relation_name
        FROM pg_temp.career_040_expected
    LOOP
        EXECUTE format(
            'SELECT EXISTS (
                (
                    SELECT data
                    FROM pg_temp.career_040_expected
                    WHERE relation_name = %L
                    EXCEPT ALL
                    SELECT to_jsonb(t)
                    FROM public.%I AS t
                )
                UNION ALL
                (
                    SELECT to_jsonb(t)
                    FROM public.%I AS t
                    EXCEPT ALL
                    SELECT data
                    FROM pg_temp.career_040_expected
                    WHERE relation_name = %L
                )
            )',
            target_relation,
            target_relation,
            target_relation,
            target_relation
        )
        INTO mismatch;

        IF mismatch THEN
            RAISE EXCEPTION
                '전환 후 데이터가 다릅니다: %',
                target_relation;
        END IF;
    END LOOP;
END;
$$;

COMMENT ON TABLE public.career IS
    '취업 분류·상세·투표 선택지의 기준 저장소. 공통 게시글 정보와 익명 여부는 posts에서 관리한다.';

COMMIT;