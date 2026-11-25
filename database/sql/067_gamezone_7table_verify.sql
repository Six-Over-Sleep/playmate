-- Issue #176: Final GameZone 7-table structure verification, PostgreSQL 18.
-- READ ONLY. Does not depend on fixture rows or change any database objects.
-- Safe ONLY for the isolated local Docker migration clone.
-- Historical 063 verifies the intermediate 9-table stage and is not changed.
BEGIN TRANSACTION READ ONLY;
SET LOCAL statement_timeout = '60s';

DO $verify$
DECLARE
    v_count integer;
BEGIN
    IF current_database() <> 'playmate_migration_176'
       OR current_user <> 'playmate_restore' THEN
        RAISE EXCEPTION 'Local Docker migration clone only';
    END IF;

    SELECT COUNT(*) INTO v_count
    FROM pg_tables
    WHERE schemaname = 'public'
      AND (tablename = 'games' OR tablename ~ '^game_');

    IF v_count <> 7 OR EXISTS (
        SELECT 1 FROM unnest(ARRAY[
            'games', 'game_questions', 'game_events', 'game_event_entries',
            'game_matches', 'game_match_players', 'game_attempts'
        ]) AS required(name)
        WHERE to_regclass('public.' || name) IS NULL
    ) THEN
        RAISE EXCEPTION 'Final seven GameZone tables mismatch';
    END IF;
    RAISE NOTICE 'PASS: EXACT_SEVEN_GAMEZONE_TABLES';

    IF EXISTS (
        SELECT 1 FROM unnest(ARRAY[
            'game_categories', 'game_supported_modes', 'game_results',
            'game_event_questions', 'game_badges', 'game_member_badges',
            'game_question_secrets', 'game_event_teams'
        ]) AS removed(name)
        WHERE to_regclass('public.' || name) IS NOT NULL
    ) THEN
        RAISE EXCEPTION 'Legacy GameZone tables still exist';
    END IF;
    RAISE NOTICE 'PASS: EIGHT_LEGACY_TABLES_REMOVED';

    SELECT COUNT(*) INTO v_count
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND (
          (table_name = 'games' AND column_name IN (
             'category_name', 'category_sort_order', 'supported_modes'))
       OR (table_name = 'game_questions' AND column_name IN (
             'answer_key', 'judge_config', 'answer_updated_at'))
       OR (table_name = 'game_events' AND column_name IN (
             'question_set', 'team_set'))
      );
    IF v_count <> 8 THEN
        RAISE EXCEPTION 'Consolidated columns mismatch: %', v_count;
    END IF;
    RAISE NOTICE 'PASS: EIGHT_CONSOLIDATED_COLUMNS';

    IF EXISTS (
        SELECT required.slug
        FROM (VALUES
          ('daily-quiz'), ('python-quiz'), ('sql-quiz'),
          ('frontend-quiz'), ('cs-quiz'), ('ai-quiz'),
          ('code-challenge'), ('bug-hunt'), ('typing-race'),
          ('reaction-time'), ('memory-flip'), ('arcade')
        ) AS required(slug)
        EXCEPT SELECT slug FROM public.games
    ) OR EXISTS (
        SELECT 1 FROM public.games
        WHERE supported_modes IS NULL
           OR cardinality(supported_modes) = 0
    ) THEN
        RAISE EXCEPTION 'Game catalog or supported modes invalid';
    END IF;
    RAISE NOTICE 'PASS: GAME_CATALOG_AND_MODES';

    SELECT COUNT(*) INTO v_count
    FROM pg_views
    WHERE schemaname = 'public'
      AND viewname IN (
         'v_game_member_rankings', 'v_game_weekly_cohort_scores',
         'v_game_daily_quiz_scores', 'v_member_all_achievements'
      );
    IF v_count <> 4 THEN
        RAISE EXCEPTION 'Four required views not found';
    END IF;
    RAISE NOTICE 'PASS: FOUR_VIEWS_PRESENT';

    IF EXISTS (
        SELECT 1 FROM pg_views
        WHERE schemaname = 'public'
          AND definition ~* '\m(game_categories|game_supported_modes|game_results|game_event_questions|game_badges|game_member_badges|game_question_secrets|game_event_teams)\M'
    ) THEN
        RAISE EXCEPTION 'View uses removed GameZone table';
    END IF;
    RAISE NOTICE 'PASS: NO_LEGACY_VIEW_REFERENCES';

    SELECT COUNT(*) INTO v_count
    FROM pg_trigger AS t
    JOIN pg_class c ON c.oid = t.tgrelid
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public'
      AND NOT t.tgisinternal AND t.tgenabled = 'O'
      AND t.tgname IN (
        'trg_validate_game_mode_176',
        'trg_protect_game_modes_176',
        'trg_validate_event_questions_176',
        'trg_protect_event_question_176',
        'trg_sync_game_category_176',
        'trg_validate_game_event_team_set_176',
        'trg_validate_game_player_team_176',
        'trg_protect_game_match_event_team_176'
      );
    IF v_count <> 8 THEN
        RAISE EXCEPTION 'Eight enabled integrity triggers missing';
    END IF;
    RAISE NOTICE 'PASS: EIGHT_INTEGRITY_TRIGGERS';

    IF EXISTS (
        SELECT 1
        FROM public.game_match_players mp
        LEFT JOIN public.game_matches m ON m.match_id = mp.match_id
        LEFT JOIN public.game_events e ON e.event_id = m.event_id
        WHERE mp.event_team_id IS NOT NULL
          AND NOT EXISTS (
            SELECT 1
            FROM jsonb_to_recordset(COALESCE(e.team_set, '[]'::jsonb))
              AS t(event_team_id bigint, cohort_id bigint)
            WHERE t.event_team_id = mp.event_team_id
              AND t.cohort_id = mp.cohort_id
          )
    ) THEN
        RAISE EXCEPTION 'Orphan team assignment detected';
    END IF;
    RAISE NOTICE 'PASS: TEAM_ASSIGNMENTS_VALID';
    RAISE NOTICE 'PASS: GAMEZONE_7TABLE_STRUCTURE';
END;
$verify$;

-- Running SELECT statements also verifies that each view is queryable.
SELECT 'member_rankings' AS view_name, COUNT(*) AS records
FROM public.v_game_member_rankings
UNION ALL
SELECT 'weekly_scores', COUNT(*)
FROM public.v_game_weekly_cohort_scores
UNION ALL
SELECT 'daily_scores', COUNT(*)
FROM public.v_game_daily_quiz_scores
UNION ALL
SELECT 'all_achievements', COUNT(*)
FROM public.v_member_all_achievements;

COMMIT;
