-- Issue #176 / GameZone event question consolidation
-- PostgreSQL 18 / EXPAND phase
-- Local Docker test database only

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';

-- 1. Local test DB safety check
DO $$
BEGIN
    IF current_database() <> 'playmate_test_20261123210154'
       OR current_user <> 'playmate_test' THEN
        RAISE EXCEPTION 'Local Docker test DB only';
    END IF;
END $$;

-- 2. Add event question configuration
ALTER TABLE public.game_events
ADD COLUMN IF NOT EXISTS question_set JSONB
NOT NULL DEFAULT '[]'::jsonb;

-- 3. Validate JSONB type
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'public.game_events'::regclass
          AND conname = 'chk_game_events_question_set'
    ) THEN
        ALTER TABLE public.game_events
        ADD CONSTRAINT chk_game_events_question_set
        CHECK (jsonb_typeof(question_set) = 'array');
    END IF;
END $$;

-- 4. Migrate existing event questions
UPDATE public.game_events AS e
SET question_set = COALESCE(
    (
        SELECT jsonb_agg(
            jsonb_build_object(
                'question_id', eq.question_id,
                'display_order', eq.display_order,
                'points', eq.points
            )
            ORDER BY eq.display_order
        )
        FROM public.game_event_questions AS eq
        WHERE eq.event_id = e.event_id
    ),
    '[]'::jsonb
)
WHERE e.question_set = '[]'::jsonb;

-- 5. Check that all configurations were copied
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM public.game_events AS e
        WHERE e.question_set IS DISTINCT FROM (
            SELECT COALESCE(
                jsonb_agg(
                    jsonb_build_object(
                        'question_id', eq.question_id,
                        'display_order', eq.display_order,
                        'points', eq.points
                    )
                    ORDER BY eq.display_order
                ),
                '[]'::jsonb
            )
            FROM public.game_event_questions AS eq
            WHERE eq.event_id = e.event_id
        )
    ) THEN
        RAISE EXCEPTION 'Event question migration mismatch';
    END IF;
END $$;

COMMIT;
