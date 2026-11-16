
-- PostgreSQL 18
-- PlayMate 게시판 접근 범위 확장
-- 기존 게시판은 LEGACY로 보존

BEGIN;

ALTER TABLE public.boards
    ADD COLUMN IF NOT EXISTS scope_type VARCHAR(20)
        NOT NULL DEFAULT 'LEGACY',
    ADD COLUMN IF NOT EXISTS institution_id BIGINT
        REFERENCES public.institutions(institution_id),
    ADD COLUMN IF NOT EXISTS program_id BIGINT
        REFERENCES public.programs(program_id),
    ADD COLUMN IF NOT EXISTS cohort_id BIGINT
        REFERENCES public.cohorts(cohort_id),
    ADD COLUMN IF NOT EXISTS read_policy VARCHAR(20)
        NOT NULL DEFAULT 'SCOPE_ONLY',
    ADD COLUMN IF NOT EXISTS write_policy VARCHAR(20)
        NOT NULL DEFAULT 'SCOPE_ONLY';

-- 접근 범위 및 권한 정책 검증
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'public.boards'::regclass
          AND conname = 'ck_boards_access_scope'
    ) THEN
        ALTER TABLE public.boards
        ADD CONSTRAINT ck_boards_access_scope
        CHECK (
            (
                scope_type IN ('LEGACY', 'NATIONAL')
                AND institution_id IS NULL
                AND program_id IS NULL
                AND cohort_id IS NULL
            )
            OR (
                scope_type = 'INSTITUTION'
                AND institution_id IS NOT NULL
                AND program_id IS NULL
                AND cohort_id IS NULL
            )
            OR (
                scope_type = 'PROGRAM'
                AND institution_id IS NULL
                AND program_id IS NOT NULL
                AND cohort_id IS NULL
            )
            OR (
                scope_type = 'COHORT'
                AND institution_id IS NULL
                AND program_id IS NULL
                AND cohort_id IS NOT NULL
            )
        );
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'public.boards'::regclass
          AND conname = 'ck_boards_read_policy'
    ) THEN
        ALTER TABLE public.boards
        ADD CONSTRAINT ck_boards_read_policy
        CHECK (
            read_policy IN ('SCOPE_ONLY', 'ALL_VERIFIED')
        );
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'public.boards'::regclass
          AND conname = 'ck_boards_write_policy'
    ) THEN
        ALTER TABLE public.boards
        ADD CONSTRAINT ck_boards_write_policy
        CHECK (
            write_policy IN ('SCOPE_ONLY', 'STAFF_ONLY')
        );
    END IF;
END $$;

-- 게시판 범위별 조회 인덱스
CREATE INDEX IF NOT EXISTS idx_boards_access_scope
    ON public.boards (
        scope_type,
        institution_id,
        program_id,
        cohort_id
    );

-- 기존 게시판은 자동으로 전국 공개하지 않음
-- 기존 course_code / cohort 컬럼 유지

COMMIT;
