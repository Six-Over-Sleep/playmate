-- Issue #176: GameZone view cutover
-- PostgreSQL 18 / Local Docker DB only
-- No table deletion or Aiven changes

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';

DO $$
BEGIN
    IF current_database() <> 'playmate_test_20261123210154'
       OR current_user <> 'playmate_test' THEN
        RAISE EXCEPTION 'Local Docker test DB only';
    END IF;
END $$;

-- 1. 게임별 회원 랭킹
-- game_results 대신 game_match_players의 결과 컬럼 사용
CREATE OR REPLACE VIEW public.v_game_member_rankings AS
SELECT
    mp.member_id,
    m.game_id,
    mp.cohort_id,
    p.institution_id,
    COUNT(*)::BIGINT AS games_played,
    SUM(mp.score)::NUMERIC AS total_score,
    MAX(mp.score)::BIGINT AS best_score,
    MIN(mp.duration_ms)::BIGINT AS fastest_ms,
    MAX(mp.wpm)::NUMERIC AS best_wpm,
    MAX(mp.finalized_at) AS last_played_at
FROM public.game_match_players AS mp
JOIN public.game_matches AS m
    ON m.match_id = mp.match_id
JOIN public.cohorts AS c
    ON c.cohort_id = mp.cohort_id
JOIN public.programs AS p
    ON p.program_id = c.program_id
WHERE mp.is_valid = TRUE
  AND mp.finalized_at IS NOT NULL
  AND m.status = 'FINISHED'
GROUP BY
    mp.member_id,
    m.game_id,
    mp.cohort_id,
    p.institution_id;

-- 2. 주간 기수 대항전 점수
CREATE OR REPLACE VIEW public.v_game_weekly_cohort_scores AS
SELECT
    e.event_id,
    t.event_team_id,
    t.cohort_id,
    COUNT(DISTINCT mp.member_id)::BIGINT AS participants,
    COUNT(mp.match_id)::BIGINT AS completed_games,
    COALESCE(SUM(mp.score), 0)::NUMERIC AS total_score
FROM public.game_events AS e
JOIN public.game_event_teams AS t
    ON t.event_id = e.event_id
LEFT JOIN public.game_matches AS m
    ON m.event_id = e.event_id
   AND m.status = 'FINISHED'
LEFT JOIN public.game_match_players AS mp
    ON mp.match_id = m.match_id
   AND mp.event_team_id = t.event_team_id
   AND mp.is_valid = TRUE
   AND mp.finalized_at IS NOT NULL
WHERE e.event_type = 'WEEKLY_COHORT'
GROUP BY
    e.event_id,
    t.event_team_id,
    t.cohort_id;

-- 3. 일일 퀴즈 랭킹
CREATE OR REPLACE VIEW public.v_game_daily_quiz_scores AS
SELECT
    e.event_id,
    e.event_date,
    mp.member_id,
    mp.cohort_id,
    MAX(mp.score)::BIGINT AS best_score,
    MIN(mp.duration_ms)::BIGINT AS fastest_ms,
    COUNT(*)::BIGINT AS completed_runs
FROM public.game_events AS e
JOIN public.game_matches AS m
    ON m.event_id = e.event_id
   AND m.status = 'FINISHED'
JOIN public.game_match_players AS mp
    ON mp.match_id = m.match_id
   AND mp.is_valid = TRUE
   AND mp.finalized_at IS NOT NULL
JOIN public.game_event_entries AS ee
    ON ee.event_id = e.event_id
   AND ee.member_id = mp.member_id
   AND ee.entry_status = 'COMPLETED'
WHERE e.event_type = 'DAILY_QUIZ'
GROUP BY
    e.event_id,
    e.event_date,
    mp.member_id,
    mp.cohort_id;

-- 4. 게임 배지와 일반 업적 통합 조회
-- 기존 View의 출력 컬럼 및 타입 유지
CREATE OR REPLACE VIEW public.v_member_all_achievements AS
SELECT
    a.member_id,
    CASE
        WHEN d.category = 'GAME' THEN 'GAME'::TEXT
        ELSE 'ACHIEVEMENT'::TEXT
    END AS source_type,
    d.achievement_code::VARCHAR AS badge_code,
    d.achievement_name::VARCHAR(100) AS badge_name,
    d.description::TEXT AS description,
    d.category::TEXT AS category,
    a.awarded_at
FROM public.member_achievements AS a
JOIN public.achievement_definitions AS d
    ON d.achievement_id = a.achievement_id;

COMMIT;
