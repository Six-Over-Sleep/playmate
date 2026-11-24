-- Issue #176 / GameZone final 7-table verification
-- Local PostgreSQL 18 test only
-- Negative tests are executed inside a transaction and rolled back.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';

DO $verify$
DECLARE
    v_event_id BIGINT;
    v_match_id BIGINT;
    v_member_id BIGINT;
    v_table_count INTEGER;
    v_trigger_count INTEGER;
BEGIN
    -- 1. Environment guard
    IF current_database() <> 'playmate_test_20261123210154'
       OR current_user <> 'playmate_test' THEN
        RAISE EXCEPTION 'Local test database only';
    END IF;

    -- 2. Exact GameZone table inventory
    SELECT COUNT(*) INTO v_table_count
    FROM pg_tables
    WHERE schemaname = 'public'
      AND (tablename = 'games' OR tablename ~ '^game_');

    IF v_table_count <> 7 OR EXISTS (
        SELECT expected.name
        FROM unnest(ARRAY[
            'games',
            'game_questions',
            'game_events',
            'game_event_entries',
            'game_matches',
            'game_match_players',
            'game_attempts'
        ]) AS expected(name)
        WHERE NOT EXISTS (
            SELECT 1
            FROM pg_tables AS t
            WHERE t.schemaname = 'public'
              AND t.tablename = expected.name
        )
    ) THEN
        RAISE EXCEPTION 'Final seven-table structure mismatch';
    END IF;

    RAISE NOTICE 'PASS: EXACT_SEVEN_GAMEZONE_TABLES';

    -- 3. Question and answer preservation
    IF NOT EXISTS (
        SELECT 1
        FROM public.game_questions
        WHERE prompt = 'Issue 176 migration question'
          AND answer_key->>'answer' = 'A'
          AND judge_config = '{}'::jsonb
          AND answer_updated_at IS NOT NULL
    ) THEN
        RAISE EXCEPTION 'Question answer fixture not preserved';
    END IF;

    RAISE NOTICE 'PASS: QUESTION_ANSWER_PRESERVED';

    -- 4. Team data and rankings
    SELECT event_id INTO STRICT v_event_id
    FROM public.game_events
    WHERE title = 'Issue 176 Weekly Team Migration';

    IF (
        SELECT COUNT(*)
        FROM public.game_events AS e
        CROSS JOIN LATERAL jsonb_to_recordset(e.team_set)
            AS t(
                event_team_id BIGINT,
                cohort_id BIGINT,
                team_name TEXT,
                created_at TIMESTAMPTZ
            )
        WHERE e.event_id = v_event_id
          AND t.created_at IS NOT NULL
          AND t.cohort_id IS NOT NULL
          AND t.event_team_id IS NOT NULL
          AND t.team_name IN ('Issue176 Team A', 'Issue176 Team B')
    ) <> 2 THEN
        RAISE EXCEPTION 'Migrated team metadata mismatch';
    END IF;

    RAISE NOTICE 'PASS: TWO_TEAM_RECORDS_PRESERVED';

    IF (
        SELECT COUNT(*)
        FROM public.v_game_weekly_cohort_scores
        WHERE event_id = v_event_id
    ) <> 2 OR (
        SELECT COUNT(*)
        FROM public.v_game_weekly_cohort_scores AS r
        JOIN public.game_events AS e
          ON e.event_id = r.event_id
        CROSS JOIN LATERAL jsonb_to_recordset(e.team_set)
            AS t(
                event_team_id BIGINT,
                cohort_id BIGINT,
                team_name TEXT
            )
        WHERE r.event_id = v_event_id
          AND r.event_team_id = t.event_team_id
          AND r.cohort_id = t.cohort_id
          AND (
              (
                  t.team_name = 'Issue176 Team A'
                  AND r.participants = 2
                  AND r.completed_games = 2
                  AND r.total_score = 150
              )
              OR
              (
                  t.team_name = 'Issue176 Team B'
                  AND r.participants = 1
                  AND r.completed_games = 1
                  AND r.total_score = 80
              )
          )
    ) <> 2 THEN
        RAISE EXCEPTION 'Weekly rankings changed';
    END IF;

    RAISE NOTICE 'PASS: WEEKLY_RANKING_150_AND_80';

    -- 5. Validate all existing player-to-team relationships
    IF EXISTS (
        SELECT 1
        FROM public.game_match_players AS mp
        JOIN public.game_matches AS m
          ON m.match_id = mp.match_id
        LEFT JOIN public.game_events AS e
          ON e.event_id = m.event_id
        WHERE mp.event_team_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1
              FROM jsonb_to_recordset(
                  COALESCE(e.team_set, '[]'::jsonb)
              ) AS t(event_team_id BIGINT, cohort_id BIGINT)
              WHERE t.event_team_id = mp.event_team_id
                AND t.cohort_id = mp.cohort_id
          )
    ) THEN
        RAISE EXCEPTION 'Orphaned team assignment found';
    END IF;

    RAISE NOTICE 'PASS: TEAM_ASSIGNMENTS_VALID';

    -- 6. Verify three integrity triggers are enabled
    SELECT COUNT(*) INTO v_trigger_count
    FROM pg_trigger AS t
    JOIN pg_class AS c ON c.oid = t.tgrelid
    JOIN pg_namespace AS n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public'
      AND t.tgenabled IN ('O', 'A')
      AND NOT t.tgisinternal
      AND (
          (
              c.relname = 'game_events'
              AND t.tgname = 'trg_validate_game_event_team_set_176'
          )
          OR
          (
              c.relname = 'game_match_players'
              AND t.tgname = 'trg_validate_game_player_team_176'
          )
          OR
          (
              c.relname = 'game_matches'
              AND t.tgname = 'trg_protect_game_match_event_team_176'
          )
      );

    IF v_trigger_count <> 3 THEN
        RAISE EXCEPTION 'GameZone integrity trigger missing';
    END IF;

    RAISE NOTICE 'PASS: THREE_INTEGRITY_TRIGGERS_ENABLED';

    SELECT match_id INTO STRICT v_match_id
    FROM public.game_matches
    WHERE event_id = v_event_id
      AND status = 'FINISHED';

    SELECT member_id INTO STRICT v_member_id
    FROM public.game_match_players
    WHERE match_id = v_match_id
      AND score = 100;

    -- 7. Negative test: nonexistent team ID must be rejected
    BEGIN
        UPDATE public.game_match_players
        SET event_team_id = -999
        WHERE match_id = v_match_id
          AND member_id = v_member_id;

        RAISE EXCEPTION 'INVALID_TEAM_WAS_ACCEPTED';
    EXCEPTION
        WHEN foreign_key_violation THEN
            RAISE NOTICE 'PASS: INVALID_TEAM_REJECTED';
    END;

    -- 8. Negative test: duplicate team must be rejected
    BEGIN
        UPDATE public.game_events
        SET team_set = team_set || jsonb_build_array(team_set->0)
        WHERE event_id = v_event_id;

        RAISE EXCEPTION 'DUPLICATE_TEAM_WAS_ACCEPTED';
    EXCEPTION
        WHEN check_violation THEN
            RAISE NOTICE 'PASS: DUPLICATE_TEAM_REJECTED';
    END;

    -- 9. Negative test: assigned teams cannot be removed
    BEGIN
        UPDATE public.game_events
        SET team_set = '[]'::jsonb
        WHERE event_id = v_event_id;

        RAISE EXCEPTION 'ASSIGNED_TEAM_REMOVAL_WAS_ACCEPTED';
    EXCEPTION
        WHEN foreign_key_violation THEN
            RAISE NOTICE 'PASS: ASSIGNED_TEAM_REMOVAL_REJECTED';
    END;

    -- 10. Negative test: event reassignment cannot orphan players
    BEGIN
        UPDATE public.game_matches
        SET event_id = NULL
        WHERE match_id = v_match_id;

        RAISE EXCEPTION 'INVALID_MATCH_EVENT_WAS_ACCEPTED';
    EXCEPTION
        WHEN foreign_key_violation THEN
            RAISE NOTICE 'PASS: INVALID_MATCH_EVENT_REJECTED';
    END;

    RAISE NOTICE 'PASS: GAMEZONE_7TABLE_FINAL_VERIFICATION';
END;
$verify$;

-- Verification should never persist test mutations.
ROLLBACK;