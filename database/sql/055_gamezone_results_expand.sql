-- Issue #176 / GameZone result consolidation
-- PostgreSQL 18 / isolated Docker test DB
-- EXPAND phase: no tables are deleted.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';

-- 1. Test database safety
DO $$
BEGIN
    IF current_database() <> 'playmate_test_20261123210154'
       OR current_user <> 'playmate_test' THEN
        RAISE EXCEPTION 'Local Docker test DB only';
    END IF;
END $$;

-- 2. Extend match player records
ALTER TABLE public.game_match_players
    ADD COLUMN IF NOT EXISTS score BIGINT,
    ADD COLUMN IF NOT EXISTS duration_ms BIGINT,
    ADD COLUMN IF NOT EXISTS accuracy_pct NUMERIC(5,2),
    ADD COLUMN IF NOT EXISTS wpm NUMERIC(8,2),
    ADD COLUMN IF NOT EXISTS is_valid BOOLEAN,
    ADD COLUMN IF NOT EXISTS finalized_at TIMESTAMPTZ;

-- 3. Migrate existing finalized results
UPDATE public.game_match_players AS mp
SET
    score = r.score,
    duration_ms = r.duration_ms,
    accuracy_pct = r.accuracy_pct,
    wpm = r.wpm,
    is_valid = r.is_valid,
    finalized_at = r.finalized_at
FROM public.game_results AS r
WHERE mp.match_id = r.match_id
  AND mp.member_id = r.member_id
  AND mp.finalized_at IS NULL;

-- 4. Verify copied result values
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM public.game_results AS r
        LEFT JOIN public.game_match_players AS mp
            ON mp.match_id = r.match_id
           AND mp.member_id = r.member_id
        WHERE mp.match_id IS NULL
           OR ROW(
                mp.score,
                mp.duration_ms,
                mp.accuracy_pct,
                mp.wpm,
                mp.is_valid,
                mp.finalized_at
           ) IS DISTINCT FROM ROW(
                r.score,
                r.duration_ms,
                r.accuracy_pct,
                r.wpm,
                r.is_valid,
                r.finalized_at
           )
    ) THEN
        RAISE EXCEPTION 'Game result migration mismatch';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'public.game_match_players'::regclass
          AND conname = 'chk_game_match_players_result'
    ) THEN
        ALTER TABLE public.game_match_players
        ADD CONSTRAINT chk_game_match_players_result
        CHECK (
            (score IS NULL OR score >= 0)
            AND (duration_ms IS NULL OR duration_ms >= 0)
            AND (accuracy_pct IS NULL OR accuracy_pct BETWEEN 0 AND 100)
            AND (wpm IS NULL OR wpm >= 0)
            AND (
                finalized_at IS NULL
                OR (score IS NOT NULL AND is_valid IS NOT NULL)
            )
        );
    END IF;
END $$;

COMMIT;
