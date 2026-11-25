
-- Issue #176 / GameZone consolidation - Expand phase
-- PostgreSQL 18 / Local Docker test DB only
-- Existing tables and foreign keys are preserved.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';

-- 1. Test database safety check
DO $$
BEGIN
    IF current_database() <> 'playmate_test_20261123210154'
       OR current_user <> 'playmate_test' THEN
        RAISE EXCEPTION 'Local test database only';
    END IF;

    IF EXISTS (
        SELECT required.slug
        FROM (
            VALUES
                ('daily-quiz'),
                ('python-quiz'),
                ('sql-quiz'),
                ('frontend-quiz'),
                ('cs-quiz'),
                ('ai-quiz'),
                ('code-challenge'),
                ('bug-hunt'),
                ('typing-race'),
                ('reaction-time'),
                ('memory-flip'),
                ('arcade')
        ) AS required(slug)
        EXCEPT
        SELECT slug FROM public.games
    ) THEN
        RAISE EXCEPTION 'Required GameZone seed game missing';
    END IF;

    -- Additional games are permitted, but each needs a supported mode.
    IF EXISTS (
        SELECT 1
        FROM public.games AS g
        WHERE NOT EXISTS (
            SELECT 1
            FROM public.game_supported_modes AS sm
            WHERE sm.game_id = g.game_id
        )
    ) THEN
        RAISE EXCEPTION 'Game without supported modes';
    END IF;
END $$;

-- 2. Add consolidated columns
ALTER TABLE public.games
    ADD COLUMN IF NOT EXISTS category_name VARCHAR(60);

ALTER TABLE public.games
    ADD COLUMN IF NOT EXISTS supported_modes TEXT[];

-- 3. Copy category names
UPDATE public.games AS g
SET category_name = c.category_name
FROM public.game_categories AS c
WHERE g.category_code = c.category_code
  AND g.category_name IS NULL;

-- 4. Copy supported modes
UPDATE public.games AS g
SET supported_modes = source.modes
FROM (
    SELECT
        game_id,
        ARRAY_AGG(game_mode::TEXT ORDER BY game_mode) AS modes
    FROM public.game_supported_modes
    GROUP BY game_id
) AS source
WHERE g.game_id = source.game_id
  AND g.supported_modes IS NULL;

-- 5. Validate migrated values
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM public.games AS g
        JOIN public.game_categories AS c
          ON c.category_code = g.category_code
        WHERE g.category_name IS DISTINCT FROM c.category_name
    ) THEN
        RAISE EXCEPTION 'Category migration mismatch';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM public.games AS g
        WHERE g.category_name IS NULL
           OR g.supported_modes IS NULL
           OR CARDINALITY(g.supported_modes) = 0
    ) THEN
        RAISE EXCEPTION 'Incomplete game catalog migration';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM public.games AS g
        WHERE g.supported_modes IS DISTINCT FROM (
            SELECT ARRAY_AGG(sm.game_mode::TEXT ORDER BY sm.game_mode)
            FROM public.game_supported_modes AS sm
            WHERE sm.game_id = g.game_id
        )
    ) THEN
        RAISE EXCEPTION 'Supported mode migration mismatch';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'public.games'::regclass
          AND conname = 'chk_games_supported_modes'
    ) THEN
        ALTER TABLE public.games
        ADD CONSTRAINT chk_games_supported_modes
        CHECK (
            array_ndims(supported_modes) = 1
            AND CARDINALITY(supported_modes) BETWEEN 1 AND 3
            AND supported_modes <@ ARRAY['SOLO','DUEL','TEAM']::TEXT[]
            AND array_position(supported_modes, NULL) IS NULL
            AND (
                CARDINALITY(supported_modes) < 2
                OR supported_modes[1] <> supported_modes[2]
            )
            AND (
                CARDINALITY(supported_modes) < 3
                OR (
                    supported_modes[1] <> supported_modes[3]
                    AND supported_modes[2] <> supported_modes[3]
                )
            )
        );
    END IF;
END $$;

-- 6. Require consolidated values
ALTER TABLE public.games
    ALTER COLUMN category_name SET NOT NULL;

ALTER TABLE public.games
    ALTER COLUMN supported_modes SET NOT NULL;

COMMIT;
