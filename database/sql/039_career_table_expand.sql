-- 039: 취업 분류·상세를 career로 분리하는 준비 단계
-- 선행 조건: 037, 038 적용 완료
-- 뉴스·채용공고·수집 테이블은 변경하지 않는다.
-- 재실행용 SQL이 아니므로 한 번만 적용한다.

BEGIN;

SET LOCAL lock_timeout = '10s';
SET LOCAL statement_timeout = '120s';
SET LOCAL search_path = pg_catalog, public, pg_temp;

-- 복사 도중 기존 게시글 데이터가 변경되지 않도록 보호한다.
-- 일반 SELECT는 허용한다.
LOCK TABLE public.posts IN SHARE ROW EXCLUSIVE MODE;

CREATE TABLE public.career (
    post_id BIGINT PRIMARY KEY
        REFERENCES public.posts(post_id)
        ON DELETE CASCADE,

    category_code VARCHAR(20) NOT NULL,
    subcategory_code VARCHAR(50) NOT NULL,

    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    poll_options JSONB NOT NULL DEFAULT '[]'::jsonb,

    CONSTRAINT ck_career_category
        CHECK (
            category_code IN ('reviews', 'talk', 'lounge', 'lab')
        ),

    CONSTRAINT ck_career_subcategory
        CHECK (
            LENGTH(BTRIM(subcategory_code)) > 0
        ),

    -- 037에서 검증한 유형별 상세 규칙을 재사용한다.
    CONSTRAINT ck_career_details
        CHECK (
            public.playmate_career_details_valid(
                category_code,
                details
            )
        ),

    CONSTRAINT ck_career_poll_options
        CHECK (
            public.playmate_poll_options_valid(poll_options)
            AND (
                poll_options = '[]'::jsonb
                OR (
                    category_code = 'lab'
                    AND (
                        details ->> 'post_type'
                    ) IS NOT DISTINCT FROM 'DISCUSSION'
                )
            )
        )
);

CREATE INDEX idx_career_category_listing
    ON public.career (
        category_code,
        subcategory_code,
        post_id DESC
    );

CREATE INDEX idx_career_job
    ON public.career (
        category_code,
        (details ->> 'job_category_code')
    );

-- 게시글 ID와 상세·선택지 데이터를 그대로 복사한다.
-- 제목·본문·작성자·익명 여부는 posts에 유지한다.
INSERT INTO public.career (
    post_id,
    category_code,
    subcategory_code,
    details,
    poll_options
)
SELECT
    post_id,
    career_category,
    career_subcategory,
    career_details,
    poll_options
FROM public.posts
WHERE career_category IS NOT NULL;

-- 전환 기간에는 posts가 기준 저장소다.
-- 기존 서버의 쓰기를 career에 자동 반영한다.
CREATE FUNCTION public.playmate_sync_career_from_posts()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF NEW.career_category IS NULL THEN
        DELETE FROM public.career
        WHERE post_id = NEW.post_id;

        RETURN NEW;
    END IF;

    INSERT INTO public.career (
        post_id,
        category_code,
        subcategory_code,
        details,
        poll_options
    )
    VALUES (
        NEW.post_id,
        NEW.career_category,
        NEW.career_subcategory,
        NEW.career_details,
        NEW.poll_options
    )
    ON CONFLICT (post_id)
    DO UPDATE SET
        category_code = EXCLUDED.category_code,
        subcategory_code = EXCLUDED.subcategory_code,
        details = EXCLUDED.details,
        poll_options = EXCLUDED.poll_options;

    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_posts_sync_career
AFTER INSERT OR UPDATE OF
    career_category,
    career_subcategory,
    career_details,
    poll_options
ON public.posts
FOR EACH ROW
EXECUTE FUNCTION public.playmate_sync_career_from_posts();

-- 일반 계정이 이 소유자 권한 함수를 다른 테이블에
-- 임의로 연결하지 못하도록 제한한다.
REVOKE ALL
ON FUNCTION public.playmate_sync_career_from_posts()
FROM PUBLIC;

-- 건수뿐 아니라 모든 이관 필드가 같은지 검증한다.
-- 불일치하면 트랜잭션 전체가 실패한다.
DO $$
BEGIN
    IF (
        SELECT COUNT(*)
        FROM public.career
    ) <> (
        SELECT COUNT(*)
        FROM public.posts
        WHERE career_category IS NOT NULL
    ) THEN
        RAISE EXCEPTION 'career 이관 건수가 일치하지 않습니다.';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM public.posts AS p
        LEFT JOIN public.career AS c
            ON c.post_id = p.post_id
        WHERE p.career_category IS NOT NULL
          AND ROW(
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
        RAISE EXCEPTION 'career 이관 데이터가 일치하지 않습니다.';
    END IF;
END;
$$;

COMMENT ON TABLE public.career IS
    '취업 분류·상세·투표 선택지. 039 전환 단계에서는 posts에서 동기화하며, 직접 쓰기는 040 전환 이후 사용한다.';

COMMIT;