-- Issue #176 / Final GameZone schema verification
-- PostgreSQL 18 / READ ONLY / Local Docker database only

BEGIN TRANSACTION READ ONLY;

DO $$
DECLARE
    missing_tables TEXT;
    existing_legacy_tables TEXT;
    missing_views TEXT;
    table_count INTEGER;
BEGIN
    IF current_database() <> 'playmate_test_20261123210154'
       OR current_user <> 'playmate_test' THEN
        RAISE EXCEPTION 'Local test database only';
    END IF;

    -- 1. 최종 9개 테이블 존재 확인
    SELECT string_agg(name, ', ')
    INTO missing_tables
    FROM unnest(ARRAY[
        'games',
        'game_questions',
        'game_question_secrets',
        'game_events',
        'game_event_entries',
        'game_event_teams',
        'game_matches',
        'game_match_players',
        'game_attempts'
    ]) AS t(name)
    WHERE to_regclass('public.' || name) IS NULL;

    IF missing_tables IS NOT NULL THEN
        RAISE EXCEPTION 'Missing tables: %', missing_tables;
    END IF;

    SELECT COUNT(*)
    INTO table_count
    FROM pg_tables
    WHERE schemaname = 'public'
      AND (tablename = 'games' OR tablename LIKE 'game\_%' ESCAPE '\');

    IF table_count <> 9 THEN
        RAISE EXCEPTION 'Expected 9 tables, found %', table_count;
    END IF;

    RAISE NOTICE 'PASS: NINE_GAME_TABLES';

    -- 2. 제거한 6개 테이블이 없는지 확인
    SELECT string_agg(name, ', ')
    INTO existing_legacy_tables
    FROM unnest(ARRAY[
        'game_categories',
        'game_supported_modes',
        'game_event_questions',
        'game_results',
        'game_badges',
        'game_member_badges'
    ]) AS t(name)
    WHERE to_regclass('public.' || name) IS NOT NULL;

    IF existing_legacy_tables IS NOT NULL THEN
        RAISE EXCEPTION 'Legacy tables remain: %', existing_legacy_tables;
    END IF;

    RAISE NOTICE 'PASS: SIX_LEGACY_TABLES_REMOVED';

    -- 3. 게임 12종 및 카테고리 정보 확인
    -- Preserve the original seed games while allowing new games.
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

    -- Every registered game must have at least one supported mode.
    IF EXISTS (
        SELECT 1
        FROM public.games
        WHERE supported_modes IS NULL
           OR cardinality(supported_modes) = 0
    ) THEN
        RAISE EXCEPTION 'Game without supported modes';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM public.games AS g
        LEFT JOIN (
            VALUES
                ('PYTHON', 'Python', 10),
                ('SQL', 'SQL', 20),
                ('FRONTEND', 'Frontend', 30),
                ('CS', 'Computer Science', 40),
                ('AI', 'Artificial Intelligence', 50),
                ('GENERAL', '미니게임', 60)
        ) AS c(code, name, sort_order)
            ON g.category_code = c.code
        WHERE c.code IS NULL
           OR g.category_name IS DISTINCT FROM c.name
           OR g.category_sort_order IS DISTINCT FROM c.sort_order
    ) THEN
        RAISE EXCEPTION 'Category metadata mismatch';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM public.games
        WHERE slug = 'typing-race'
          AND supported_modes @> ARRAY['SOLO','DUEL','TEAM']::TEXT[]
    ) THEN
        RAISE EXCEPTION 'Typing race modes missing';
    END IF;

    RAISE NOTICE 'PASS: GAME_CATALOG_AND_MODES';

    -- 4. 최종 View 4개 확인
    SELECT string_agg(name, ', ')
    INTO missing_views
    FROM unnest(ARRAY[
        'v_game_member_rankings',
        'v_game_weekly_cohort_scores',
        'v_game_daily_quiz_scores',
        'v_member_all_achievements'
    ]) AS t(name)
    WHERE to_regclass('public.' || name) IS NULL;

    IF missing_views IS NOT NULL THEN
        RAISE EXCEPTION 'Missing views: %', missing_views;
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_views
        WHERE schemaname = 'public'
          AND definition ~* '\m(game_categories|game_supported_modes|game_event_questions|game_results|game_badges|game_member_badges)\M'
    ) THEN
        RAISE EXCEPTION 'Legacy view references remain';
    END IF;

    RAISE NOTICE 'PASS: FOUR_UPDATED_VIEWS';

    -- 5. 주요 무결성 트리거 활성화 확인
    IF (
        SELECT COUNT(*)
        FROM pg_trigger
        WHERE NOT tgisinternal
          AND tgenabled = 'O'
          AND tgname IN (
              'trg_validate_game_mode_176',
              'trg_protect_game_modes_176',
              'trg_validate_event_questions_176',
              'trg_protect_event_question_176',
              'trg_sync_game_category_176'
          )
    ) <> 5 THEN
        RAISE EXCEPTION 'Game integrity triggers missing';
    END IF;

    RAISE NOTICE 'PASS: FIVE_INTEGRITY_TRIGGERS';

    -- 6. 통합 전용 컬럼이 제거됐는지 확인
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND (
              (table_name = 'member_profile_preferences'
               AND column_name = 'featured_game_badge_id')
              OR (table_name = 'user_notifications'
                  AND column_name = 'game_badge_id')
          )
    ) THEN
        RAISE EXCEPTION 'Legacy badge columns remain';
    END IF;

    RAISE NOTICE 'PASS: UNIFIED_BADGE_REFERENCES';
END $$;

SELECT
    tablename AS game_table
FROM pg_tables
WHERE schemaname = 'public'
  AND (tablename = 'games' OR tablename LIKE 'game\_%' ESCAPE '\')
ORDER BY tablename;

COMMIT;
