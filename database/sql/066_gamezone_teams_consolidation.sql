-- Issue #176 / GameZone weekly team consolidation
-- PostgreSQL 18 / Isolated local Docker test DB only
-- Contract: 8 GameZone tables -> 7

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';

-- 1. Safety and dependency preflight
DO $$
BEGIN
    IF current_database() <> 'playmate_test_20261123210154'
       OR current_user <> 'playmate_test' THEN
        RAISE EXCEPTION 'Local Docker test DB only';
    END IF;

    IF to_regclass('public.game_event_teams') IS NULL
       OR to_regclass('public.game_question_secrets') IS NOT NULL
       OR EXISTS (
           SELECT 1 FROM information_schema.columns
           WHERE table_schema = 'public'
             AND table_name = 'game_events'
             AND column_name = 'team_set'
       ) THEN
        RAISE EXCEPTION 'Unexpected GameZone migration stage';
    END IF;

    -- Team records may only belong to weekly cohort events.
    IF EXISTS (
        SELECT 1
        FROM public.game_event_teams t
        JOIN public.game_events e ON e.event_id = t.event_id
        WHERE e.event_type <> 'WEEKLY_COHORT'
    ) THEN
        RAISE EXCEPTION 'Team attached to non-weekly event';
    END IF;

    -- Every assigned player must belong to the referenced event/team/cohort.
    IF EXISTS (
        SELECT 1
        FROM public.game_match_players mp
        JOIN public.game_matches m ON m.match_id = mp.match_id
        LEFT JOIN public.game_event_teams t
          ON t.event_team_id = mp.event_team_id
        WHERE mp.event_team_id IS NOT NULL
          AND (
              t.event_team_id IS NULL
              OR t.event_id IS DISTINCT FROM m.event_id
              OR t.cohort_id IS DISTINCT FROM mp.cohort_id
          )
    ) THEN
        RAISE EXCEPTION 'Invalid existing team assignment';
    END IF;
END $$;

-- 2. Save the exact ranking result before modifying the view.
CREATE TEMP TABLE gamezone_weekly_ranking_before_176
ON COMMIT DROP
AS SELECT * FROM public.v_game_weekly_cohort_scores;

-- 3. Add event-level team metadata
ALTER TABLE public.game_events
ADD COLUMN team_set JSONB NOT NULL DEFAULT '[]'::jsonb;

ALTER TABLE public.game_events
ADD CONSTRAINT chk_game_events_team_set_176
CHECK (
    jsonb_typeof(team_set) = 'array'
    AND (
        event_type = 'WEEKLY_COHORT'
        OR team_set = '[]'::jsonb
    )
);

-- 4. Preserve old team identifiers, cohorts, names, and timestamps.
UPDATE public.game_events e
SET team_set = COALESCE(
    (
        SELECT jsonb_agg(
            jsonb_build_object(
                'event_team_id', t.event_team_id,
                'cohort_id', t.cohort_id,
                'team_name', t.team_name,
                'created_at', t.created_at
            )
            ORDER BY t.event_team_id
        )
        FROM public.game_event_teams t
        WHERE t.event_id = e.event_id
    ),
    '[]'::jsonb
);

-- 5. Validate full JSONB data preservation
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM public.game_events e
        WHERE e.team_set IS DISTINCT FROM (
            SELECT COALESCE(
                jsonb_agg(
                    jsonb_build_object(
                        'event_team_id', t.event_team_id,
                        'cohort_id', t.cohort_id,
                        'team_name', t.team_name,
                        'created_at', t.created_at
                    )
                    ORDER BY t.event_team_id
                ),
                '[]'::jsonb
            )
            FROM public.game_event_teams t
            WHERE t.event_id = e.event_id
        )
    ) THEN
        RAISE EXCEPTION 'Team metadata preservation mismatch';
    END IF;

    RAISE NOTICE 'PASS: TEAM_METADATA_PRESERVED';
END $$;

-- 6. Validate the JSONB team structure and protect assigned teams.
CREATE FUNCTION public.fn_validate_game_event_team_set_176()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_item JSONB;
    v_team_id BIGINT;
    v_cohort_id BIGINT;
    v_created_at TIMESTAMPTZ;
    v_team_ids BIGINT[] := ARRAY[]::BIGINT[];
    v_cohort_ids BIGINT[] := ARRAY[]::BIGINT[];
BEGIN
    IF jsonb_typeof(NEW.team_set) IS DISTINCT FROM 'array' THEN
        RAISE EXCEPTION 'team_set must be a JSON array'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.event_type <> 'WEEKLY_COHORT'
       AND NEW.team_set <> '[]'::jsonb THEN
        RAISE EXCEPTION 'Only weekly events can have teams'
            USING ERRCODE = '23514';
    END IF;

    FOR v_item IN
        SELECT value FROM jsonb_array_elements(NEW.team_set)
    LOOP
        IF jsonb_typeof(v_item) IS DISTINCT FROM 'object'
           OR (
               SELECT COUNT(*) FROM jsonb_object_keys(v_item)
           ) <> 4
           OR NOT (
               v_item ?& ARRAY[
                   'event_team_id', 'cohort_id',
                   'team_name', 'created_at'
               ]
           )
           OR jsonb_typeof(v_item->'event_team_id') IS DISTINCT FROM 'number'
           OR jsonb_typeof(v_item->'cohort_id') IS DISTINCT FROM 'number'
           OR jsonb_typeof(v_item->'team_name') IS DISTINCT FROM 'string'
           OR jsonb_typeof(v_item->'created_at') IS DISTINCT FROM 'string'
        THEN
            RAISE EXCEPTION 'Invalid team JSON structure'
                USING ERRCODE = '23514';
        END IF;

        -- Invalid numeric/timestamp representations fail atomically.
        v_team_id := (v_item->>'event_team_id')::BIGINT;
        v_cohort_id := (v_item->>'cohort_id')::BIGINT;
        v_created_at := (v_item->>'created_at')::TIMESTAMPTZ;

        IF v_team_id <= 0
           OR v_cohort_id <= 0
           OR v_created_at IS NULL
           OR length(btrim(v_item->>'team_name')) = 0
           OR v_team_id = ANY(v_team_ids)
           OR v_cohort_id = ANY(v_cohort_ids)
        THEN
            RAISE EXCEPTION 'Duplicate or invalid team identity'
                USING ERRCODE = '23514';
        END IF;

        IF NOT EXISTS (
            SELECT 1
            FROM public.cohorts
            WHERE cohort_id = v_cohort_id
        ) THEN
            RAISE EXCEPTION 'Unknown team cohort: %', v_cohort_id
                USING ERRCODE = '23503';
        END IF;

        v_team_ids := array_append(v_team_ids, v_team_id);
        v_cohort_ids := array_append(v_cohort_ids, v_cohort_id);
    END LOOP;

    -- An update cannot invalidate an existing player's team assignment.
    IF TG_OP = 'UPDATE' AND EXISTS (
        SELECT 1
        FROM public.game_match_players mp
        JOIN public.game_matches m ON m.match_id = mp.match_id
        WHERE m.event_id = NEW.event_id
          AND mp.event_team_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1
              FROM jsonb_to_recordset(NEW.team_set)
                   AS t(event_team_id BIGINT, cohort_id BIGINT)
              WHERE t.event_team_id = mp.event_team_id
                AND t.cohort_id = mp.cohort_id
          )
    ) THEN
        RAISE EXCEPTION 'Team update would orphan assigned players'
            USING ERRCODE = '23503';
    END IF;

    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_validate_game_event_team_set_176
BEFORE INSERT OR UPDATE OF team_set, event_type
ON public.game_events
FOR EACH ROW
EXECUTE FUNCTION public.fn_validate_game_event_team_set_176();

-- 7. Replace the removed FK with event-scoped team validation.
CREATE FUNCTION public.fn_validate_game_player_team_176()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_event_id BIGINT;
    v_event_type TEXT;
    v_team_set JSONB;
BEGIN
    IF NEW.event_team_id IS NULL THEN
        RETURN NEW;
    END IF;

    SELECT m.event_id
    INTO v_event_id
    FROM public.game_matches m
    WHERE m.match_id = NEW.match_id
    FOR SHARE;

    IF v_event_id IS NULL THEN
        RAISE EXCEPTION 'Assigned team requires an event match'
            USING ERRCODE = '23503';
    END IF;

    -- Lock the parent row to serialize with team_set updates.
    SELECT e.event_type, e.team_set
    INTO v_event_type, v_team_set
    FROM public.game_events e
    WHERE e.event_id = v_event_id
    FOR SHARE;

    IF v_event_type IS DISTINCT FROM 'WEEKLY_COHORT'
       OR NOT EXISTS (
           SELECT 1
           FROM jsonb_to_recordset(v_team_set)
                AS t(event_team_id BIGINT, cohort_id BIGINT)
           WHERE t.event_team_id = NEW.event_team_id
             AND t.cohort_id = NEW.cohort_id
       ) THEN
        RAISE EXCEPTION 'Invalid event team assignment'
            USING ERRCODE = '23503';
    END IF;

    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_validate_game_player_team_176
BEFORE INSERT OR UPDATE OF match_id, cohort_id, event_team_id
ON public.game_match_players
FOR EACH ROW
EXECUTE FUNCTION public.fn_validate_game_player_team_176();

-- 8. Prevent reassignment of a match to an incompatible event.
CREATE FUNCTION public.fn_protect_game_match_event_team_176()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_event_type TEXT;
    v_team_set JSONB;
BEGIN
    IF NEW.event_id IS NOT DISTINCT FROM OLD.event_id THEN
        RETURN NEW;
    END IF;

    IF EXISTS (
        SELECT 1 FROM public.game_match_players
        WHERE match_id = NEW.match_id
          AND event_team_id IS NOT NULL
    ) THEN
        SELECT e.event_type, e.team_set
        INTO v_event_type, v_team_set
        FROM public.game_events e
        WHERE e.event_id = NEW.event_id
        FOR SHARE;

        IF v_event_type IS DISTINCT FROM 'WEEKLY_COHORT'
           OR EXISTS (
               SELECT 1
               FROM public.game_match_players mp
               WHERE mp.match_id = NEW.match_id
                 AND mp.event_team_id IS NOT NULL
                 AND NOT EXISTS (
                     SELECT 1
                     FROM jsonb_to_recordset(v_team_set)
                          AS t(event_team_id BIGINT, cohort_id BIGINT)
                     WHERE t.event_team_id = mp.event_team_id
                       AND t.cohort_id = mp.cohort_id
                 )
           ) THEN
            RAISE EXCEPTION 'Match event change invalidates teams'
                USING ERRCODE = '23503';
        END IF;
    END IF;

    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_protect_game_match_event_team_176
BEFORE UPDATE OF event_id
ON public.game_matches
FOR EACH ROW
EXECUTE FUNCTION public.fn_protect_game_match_event_team_176();

-- 9. Rewrite the weekly cohort ranking view without the team table.
CREATE OR REPLACE VIEW public.v_game_weekly_cohort_scores AS
SELECT
    e.event_id,
    t.event_team_id,
    t.cohort_id,
    COUNT(DISTINCT mp.member_id)::BIGINT AS participants,
    COUNT(mp.match_id)::BIGINT AS completed_games,
    COALESCE(SUM(mp.score), 0::NUMERIC) AS total_score
FROM public.game_events e
JOIN LATERAL jsonb_to_recordset(e.team_set)
    AS t(
        event_team_id BIGINT,
        cohort_id BIGINT,
        team_name TEXT,
        created_at TIMESTAMPTZ
    )
    ON TRUE
LEFT JOIN public.game_matches m
    ON m.event_id = e.event_id
   AND m.status = 'FINISHED'
LEFT JOIN public.game_match_players mp
    ON mp.match_id = m.match_id
   AND mp.event_team_id = t.event_team_id
   AND mp.is_valid = TRUE
   AND mp.finalized_at IS NOT NULL
WHERE e.event_type = 'WEEKLY_COHORT'
GROUP BY e.event_id, t.event_team_id, t.cohort_id;

-- 10. Compare the entire ranking result before and after migration.
DO $$
BEGIN
    IF EXISTS (
        (
            SELECT * FROM pg_temp.gamezone_weekly_ranking_before_176
            EXCEPT ALL
            SELECT * FROM public.v_game_weekly_cohort_scores
        )
        UNION ALL
        (
            SELECT * FROM public.v_game_weekly_cohort_scores
            EXCEPT ALL
            SELECT * FROM pg_temp.gamezone_weekly_ranking_before_176
        )
    ) THEN
        RAISE EXCEPTION 'Weekly cohort ranking changed during migration';
    END IF;

    RAISE NOTICE 'PASS: WEEKLY_RANKING_PRESERVED';
END $$;

-- 11. Remove the old FK and redundant team table.
ALTER TABLE public.game_match_players
DROP CONSTRAINT game_match_players_event_team_id_fkey;

DROP TABLE public.game_event_teams RESTRICT;

-- 12. Verify final structure.
DO $$
DECLARE
    v_tables INTEGER;
BEGIN
    SELECT COUNT(*) INTO v_tables
    FROM pg_tables
    WHERE schemaname = 'public'
      AND (tablename = 'games' OR tablename ~ '^game_');

    IF v_tables <> 7 THEN
        RAISE EXCEPTION 'Expected 7 GameZone tables, found %', v_tables;
    END IF;

    IF EXISTS (
        SELECT 1
        FROM public.game_match_players mp
        JOIN public.game_matches m ON m.match_id = mp.match_id
        JOIN public.game_events e ON e.event_id = m.event_id
        WHERE mp.event_team_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1
              FROM jsonb_to_recordset(e.team_set)
                   AS t(event_team_id BIGINT, cohort_id BIGINT)
              WHERE t.event_team_id = mp.event_team_id
                AND t.cohort_id = mp.cohort_id
          )
    ) THEN
        RAISE EXCEPTION 'Team references were not preserved';
    END IF;

    RAISE NOTICE 'PASS: SEVEN_GAMEZONE_TABLES';
    RAISE NOTICE 'PASS: TEAM_REFERENCES_PRESERVED';
END $$;

COMMIT;
