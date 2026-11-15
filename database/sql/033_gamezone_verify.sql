-- PostgreSQL 18 / Read-only acceptance checks AFTER 033_gamezone_schema.sql is COMMITTED.
-- If any check fails, the DO block raises an exception. No data is changed.
DO $$
DECLARE
    missing_tables TEXT;
    missing_views TEXT;
BEGIN
    SELECT string_agg(n, ', ') INTO missing_tables
    FROM unnest(ARRAY[
      'game_categories','games','game_supported_modes','game_questions',
      'game_question_secrets','game_events','game_event_questions',
      'game_event_entries','game_event_teams','game_matches',
      'game_match_players','game_attempts','game_results',
      'game_badges','game_member_badges'
    ]) AS required(n)
    WHERE to_regclass('public.' || required.n) IS NULL;
    IF missing_tables IS NOT NULL THEN
        RAISE EXCEPTION 'GameZone missing tables: %', missing_tables;
    END IF;

    SELECT string_agg(n, ', ') INTO missing_views
    FROM unnest(ARRAY['v_game_member_rankings','v_game_weekly_cohort_scores','v_game_daily_quiz_scores']) AS required(n)
    WHERE to_regclass('public.' || required.n) IS NULL;
    IF missing_views IS NOT NULL THEN
        RAISE EXCEPTION 'GameZone missing views: %', missing_views;
    END IF;

    IF (SELECT count(*) FROM public.game_categories) < 6 THEN
        RAISE EXCEPTION 'GameZone category seeds missing';
    END IF;
    IF (SELECT count(*) FROM public.games) < 12 THEN
        RAISE EXCEPTION 'GameZone catalog seeds missing';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.game_supported_modes gm
        JOIN public.games g ON g.game_id = gm.game_id
        WHERE g.slug = 'typing-race' AND gm.game_mode = 'DUEL'
    ) THEN
        RAISE EXCEPTION 'Typing duel support missing';
    END IF;
END $$;

SELECT category_code, category_name FROM public.game_categories ORDER BY sort_order;
SELECT g.slug, g.title, g.game_type, g.status,
       string_agg(sm.game_mode, ', ' ORDER BY sm.game_mode) AS available_modes
FROM public.games g
JOIN public.game_supported_modes sm ON sm.game_id = g.game_id
GROUP BY g.game_id, g.slug, g.title, g.game_type, g.status
ORDER BY g.slug;

-- Empty rankings are NORMAL until the backend writes finished, valid results.
SELECT * FROM public.v_game_member_rankings LIMIT 5;
SELECT * FROM public.v_game_weekly_cohort_scores LIMIT 5;
SELECT * FROM public.v_game_daily_quiz_scores LIMIT 5;
