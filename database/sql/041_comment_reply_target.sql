-- 대댓글의 실제 답글 대상 댓글 (Issue #153, 인스타그램·유튜브 방식 답글)
--
-- 의미
--   parent_comment_id   : 댓글이 속한 최상위 원댓글 ID (원댓글이면 NULL) — 기존 컬럼, 변경하지 않음
--   reply_to_comment_id : 실제로 답글을 받는 댓글 ID (원댓글 또는 같은 스레드의 대댓글)
--
-- 기존 데이터 호환 (데이터를 UPDATE하지 않는다)
--   원댓글        : parent_comment_id = NULL, reply_to_comment_id = NULL
--   기존 대댓글   : reply_to_comment_id = NULL → parent_comment_id를 답글 대상으로 해석
--   새 대댓글     : parent_comment_id = 최상위 원댓글, reply_to_comment_id = 실제 답글 대상
-- 같은 게시글·같은 스레드에 속하는지는 CHECK로 표현할 수 없어 백엔드에서 검증한다.
--
-- 인덱스는 추가하지 않는다. 답글 대상은 comments PK(comment_id)로만 조회하고, 앱은 댓글을 논리 삭제(deleted_at)만 하므로
-- FK 검사를 위한 참조 쪽 인덱스도 필요 없다. "특정 댓글에 달린 답글 찾기" 같은 쿼리가 생기면 그때 추가한다.
--
-- 다시 실행해도 안전하다
--   - 컬럼이 이미 있으면 자료형(bigint)·NULL 허용·기본값 없음이 맞는지 확인한다.
--   - FK·CHECK가 이미 있으면 이름뿐 아니라 실제 정의와 검증 완료 여부까지 확인한다.
--   - 설계와 다른 것이 있으면 덮어쓰지 않고 오류로 멈춘다(사람이 확인 후 처리).
--   - 한 트랜잭션이므로 중간에 실패하면 전부 되돌아간다(부분 적용 없음).
-- comments에 컬럼·제약만 추가한다. notifications를 포함한 다른 테이블과 기존 데이터는 바꾸지 않는다.

BEGIN;

-- 다른 세션이 comments 잠금을 오래 잡고 있으면 기다리지 않고 실패한다(서비스 요청을 막지 않기 위해). 실패하면 다시 실행한다.
SET LOCAL lock_timeout = '5s';

-- 1. 컬럼 (NULL 허용, 기본값 없음 → 기존 행은 모두 NULL, 테이블 재작성 없음)
ALTER TABLE public.comments ADD COLUMN IF NOT EXISTS reply_to_comment_id BIGINT;

DO $$
DECLARE
    col record;
    found_def text;
    found_valid boolean;
    expected_def text;
BEGIN
    -- 1-1. 컬럼 정의 확인: 이미 있던 컬럼이 설계와 다르면 멈춘다.
    SELECT data_type, is_nullable, column_default INTO col
    FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'comments'
      AND column_name = 'reply_to_comment_id';
    IF col.data_type IS DISTINCT FROM 'bigint'
       OR col.is_nullable IS DISTINCT FROM 'YES'
       OR col.column_default IS NOT NULL THEN
        RAISE EXCEPTION 'comments.reply_to_comment_id 정의가 설계와 다릅니다(자료형=%, NULL 허용=%, 기본값=%). 수동 확인이 필요합니다.',
            col.data_type, col.is_nullable, col.column_default;
    END IF;

    -- 기대 정의 문자열은 이 서버가 직접 만든 것과 비교한다(PostgreSQL 버전마다 출력 형식이 달라 문자열을 고정하지 않음).
    -- 임시 NOT VALID 제약을 만들어 정의를 읽고 바로 지운다. NOT VALID라 기존 행을 검사하지 않고, 트랜잭션 밖으로 남지 않는다.

    -- 2. FK: 답글 대상은 실제 댓글이어야 한다. 기존 fk_comments_parent와 같은 기본 동작(NO ACTION)을 쓴다.
    ALTER TABLE public.comments ADD CONSTRAINT tmp_041_expected_fk
        FOREIGN KEY (reply_to_comment_id) REFERENCES public.comments(comment_id) NOT VALID;
    SELECT regexp_replace(pg_get_constraintdef(oid), '\s+NOT VALID$', '') INTO expected_def
    FROM pg_constraint
    WHERE conrelid = 'public.comments'::regclass AND conname = 'tmp_041_expected_fk';
    ALTER TABLE public.comments DROP CONSTRAINT tmp_041_expected_fk;

    SELECT regexp_replace(pg_get_constraintdef(oid), '\s+NOT VALID$', ''), convalidated
      INTO found_def, found_valid
    FROM pg_constraint
    WHERE conrelid = 'public.comments'::regclass AND conname = 'fk_comments_reply_to';

    IF FOUND THEN
        IF found_def IS DISTINCT FROM expected_def OR NOT found_valid THEN
            RAISE EXCEPTION 'fk_comments_reply_to 정의가 설계와 다릅니다(현재: %, 검증 완료: %, 기대: %). 수동 확인이 필요합니다.',
                found_def, found_valid, expected_def;
        END IF;
    ELSE
        -- 이름이 다른 같은 FK가 이미 있으면 중복이 생기므로 멈춘다.
        IF EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conrelid = 'public.comments'::regclass
              AND contype = 'f'
              AND regexp_replace(pg_get_constraintdef(oid), '\s+NOT VALID$', '') = expected_def
        ) THEN
            RAISE EXCEPTION 'reply_to_comment_id에 이름이 다른 같은 FK가 이미 있습니다. 수동 확인이 필요합니다.';
        END IF;
        ALTER TABLE public.comments ADD CONSTRAINT fk_comments_reply_to
            FOREIGN KEY (reply_to_comment_id) REFERENCES public.comments(comment_id);
    END IF;

    -- 3. CHECK: 답글 대상은 대댓글에만 있고(parent_comment_id 필수) 자기 자신일 수 없다.
    ALTER TABLE public.comments ADD CONSTRAINT tmp_041_expected_check
        CHECK (
            reply_to_comment_id IS NULL
            OR (parent_comment_id IS NOT NULL AND reply_to_comment_id <> comment_id)
        ) NOT VALID;
    SELECT regexp_replace(pg_get_constraintdef(oid), '\s+NOT VALID$', '') INTO expected_def
    FROM pg_constraint
    WHERE conrelid = 'public.comments'::regclass AND conname = 'tmp_041_expected_check';
    ALTER TABLE public.comments DROP CONSTRAINT tmp_041_expected_check;

    SELECT regexp_replace(pg_get_constraintdef(oid), '\s+NOT VALID$', ''), convalidated
      INTO found_def, found_valid
    FROM pg_constraint
    WHERE conrelid = 'public.comments'::regclass AND conname = 'chk_comments_reply_to_not_self';

    IF FOUND THEN
        IF found_def IS DISTINCT FROM expected_def OR NOT found_valid THEN
            RAISE EXCEPTION 'chk_comments_reply_to_not_self 정의가 설계와 다릅니다(현재: %, 검증 완료: %, 기대: %). 수동 확인이 필요합니다.',
                found_def, found_valid, expected_def;
        END IF;
    ELSE
        ALTER TABLE public.comments ADD CONSTRAINT chk_comments_reply_to_not_self
            CHECK (
                reply_to_comment_id IS NULL
                OR (parent_comment_id IS NOT NULL AND reply_to_comment_id <> comment_id)
            );
    END IF;
END $$;

COMMENT ON COLUMN public.comments.reply_to_comment_id IS
'실제 답글 대상 댓글 ID. NULL이면 parent_comment_id(원댓글)에 단 답글로 해석한다.';

COMMIT;

-- 적용 확인 (읽기 전용)
SELECT column_name, data_type, is_nullable, column_default
FROM information_schema.columns
WHERE table_schema = 'public' AND table_name = 'comments'
  AND column_name IN ('parent_comment_id', 'reply_to_comment_id')
ORDER BY column_name;

-- 기대: fk_comments_reply_to·chk_comments_reply_to_not_self 모두 convalidated = true, tmp_041_* 없음
SELECT conname, contype, convalidated, pg_get_constraintdef(oid) AS definition
FROM pg_constraint
WHERE conrelid = 'public.comments'::regclass
  AND (conname IN ('fk_comments_parent', 'fk_comments_reply_to', 'chk_comments_reply_to_not_self')
       OR conname LIKE 'tmp_041_%')
ORDER BY conname;

-- 기대값: 0 (적용 직후 기존 데이터는 모두 NULL)
SELECT COUNT(*) AS rows_with_reply_target
FROM public.comments
WHERE reply_to_comment_id IS NOT NULL;
