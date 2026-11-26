-- Issue #176 / GameZone question-answer consolidation
-- PostgreSQL 18 / Local Docker test only
-- Contract: 9 GameZone tables -> 8

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';

-- 1. Target and schema preflight
DO $$
BEGIN
    IF current_database() <> 'playmate_test_20261123210154'
       OR current_user <> 'playmate_test' THEN
        RAISE EXCEPTION 'Local Docker test DB only';
    END IF;

    IF to_regclass('public.game_question_secrets') IS NULL
       OR to_regclass('public.game_questions') IS NULL THEN
        RAISE EXCEPTION 'Required question tables missing';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'game_questions'
          AND column_name IN (
              'answer_key',
              'judge_config',
              'answer_updated_at'
          )
    ) THEN
        RAISE EXCEPTION 'Question-answer migration already started';
    END IF;
END $$;

-- 2. Add answer fields to question records
ALTER TABLE public.game_questions
    ADD COLUMN answer_key JSONB,
    ADD COLUMN judge_config JSONB,
    ADD COLUMN answer_updated_at TIMESTAMPTZ;

-- 3. Copy legacy secret data
UPDATE public.game_questions AS q
SET
    answer_key = s.answer_key,
    judge_config = s.judge_config,
    answer_updated_at = s.updated_at
FROM public.game_question_secrets AS s
WHERE q.question_id = s.question_id;

-- 4. Preserve optional-answer semantics
ALTER TABLE public.game_questions
ADD CONSTRAINT chk_game_questions_answers_176
CHECK (
    (
        answer_key IS NULL
        AND judge_config IS NULL
        AND answer_updated_at IS NULL
    )
    OR
    (
        answer_key IS NOT NULL
        AND jsonb_typeof(answer_key) = 'object'
        AND judge_config IS NOT NULL
        AND jsonb_typeof(judge_config) = 'object'
        AND answer_updated_at IS NOT NULL
    )
);

-- 5. Verify all migrated answer fields
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM public.game_question_secrets AS s
        LEFT JOIN public.game_questions AS q
          ON q.question_id = s.question_id
        WHERE q.question_id IS NULL
           OR ROW(
               q.answer_key,
               q.judge_config,
               q.answer_updated_at
           ) IS DISTINCT FROM ROW(
               s.answer_key,
               s.judge_config,
               s.updated_at
           )
    ) THEN
        RAISE EXCEPTION 'Question answer preservation mismatch';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM public.game_questions AS q
        LEFT JOIN public.game_question_secrets AS s
          ON s.question_id = q.question_id
        WHERE s.question_id IS NULL
          AND (
              q.answer_key IS NOT NULL
              OR q.judge_config IS NOT NULL
              OR q.answer_updated_at IS NOT NULL
          )
    ) THEN
        RAISE EXCEPTION 'Unexpected question answer data';
    END IF;

    RAISE NOTICE 'PASS: QUESTION_ANSWER_DATA_PRESERVED';
END $$;

-- 6. Remove redundant secret table
-- RESTRICT prevents removal if an unhandled dependency exists.
DROP TABLE public.game_question_secrets RESTRICT;

-- 7. Verify eight GameZone tables remain
DO $$
DECLARE
    v_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO v_count
    FROM pg_tables
    WHERE schemaname = 'public'
      AND (
          tablename = 'games'
          OR tablename ~ '^game_'
      );

    IF v_count <> 8 THEN
        RAISE EXCEPTION 'Expected 8 GameZone tables, found %', v_count;
    END IF;

    RAISE NOTICE 'PASS: EIGHT_GAMEZONE_TABLES';
END $$;

COMMIT;
