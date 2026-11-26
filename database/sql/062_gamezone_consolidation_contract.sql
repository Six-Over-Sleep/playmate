-- Issue #176 / GameZone Contract
-- PostgreSQL 18 / LOCAL DOCKER ONLY
-- Reduce 15 GameZone tables to 9

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';

-- 1. 대상 DB와 기존 데이터 확인
DO $$
BEGIN
    IF current_database() <> 'playmate_test_20261123210154'
       OR current_user <> 'playmate_test' THEN
        RAISE EXCEPTION 'Local test database only';
    END IF;

    -- The six category codes are part of the current GameZone contract.
    -- Verify their metadata because the sync trigger embeds these values.
    IF EXISTS (
        WITH expected(category_code, category_name, sort_order) AS (
            VALUES
                ('PYTHON', 'Python', 10),
                ('SQL', 'SQL', 20),
                ('FRONTEND', 'Frontend', 30),
                ('CS', 'Computer Science', 40),
                ('AI', 'Artificial Intelligence', 50),
                (
                    'GENERAL',
                    convert_from(
                        decode('ebafb8eb8b88eab28cec9e84', 'hex'),
                        'UTF8'
                    ),
                    60
                )
        )
        SELECT 1
        FROM expected AS e
        FULL OUTER JOIN public.game_categories AS c
          ON c.category_code = e.category_code
        WHERE e.category_code IS NULL
           OR c.category_code IS NULL
           OR c.category_name IS DISTINCT FROM e.category_name
           OR c.sort_order IS DISTINCT FROM e.sort_order
    ) THEN
        RAISE EXCEPTION 'Unsupported category taxonomy or metadata';
    END IF;

    -- Game and mode counts are allowed to grow beyond seed values.
    IF NOT EXISTS (SELECT 1 FROM public.games)
       OR EXISTS (
           SELECT 1
           FROM public.games AS g
           WHERE NOT EXISTS (
               SELECT 1
               FROM public.game_supported_modes AS sm
               WHERE sm.game_id = g.game_id
           )
       ) THEN
        RAISE EXCEPTION 'Empty game catalog or missing supported modes';
    END IF;

    -- 2. Verify all legacy records were preserved before dropping tables.

    -- Game results: compare all six migrated result fields.
    IF EXISTS (
        SELECT 1
        FROM public.game_results AS r
        LEFT JOIN public.game_match_players AS mp
          ON mp.match_id = r.match_id
         AND mp.member_id = r.member_id
        WHERE mp.match_id IS NULL
           OR ROW(
               mp.score, mp.duration_ms, mp.accuracy_pct,
               mp.wpm, mp.is_valid, mp.finalized_at
           ) IS DISTINCT FROM ROW(
               r.score, r.duration_ms, r.accuracy_pct,
               r.wpm, r.is_valid, r.finalized_at
           )
    ) THEN
        RAISE EXCEPTION 'Game result preservation mismatch';
    END IF;

    -- Event questions: compare the complete ordered JSONB array.
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
        RAISE EXCEPTION 'Event question preservation mismatch';
    END IF;

    -- Game badges: preserve definition fields and award rules.
    IF EXISTS (
        SELECT 1
        FROM public.game_badges AS gb
        LEFT JOIN public.achievement_definitions AS ad
          ON ad.achievement_code = gb.badge_code
        WHERE ad.achievement_id IS NULL
           OR ad.category IS DISTINCT FROM 'GAME'
           OR ad.achievement_name IS DISTINCT FROM gb.badge_name
           OR ad.description IS DISTINCT FROM gb.description
           OR ad.award_rule IS DISTINCT FROM gb.award_rule
           OR ad.is_active IS DISTINCT FROM gb.is_active
           OR ad.created_at IS DISTINCT FROM gb.created_at
    ) THEN
        RAISE EXCEPTION 'Game badge definition preservation mismatch';
    END IF;

    -- Member badge awards: preserve ownership, source match,
    -- award timestamp, event key, and legacy badge ID mapping.
    IF EXISTS (
        SELECT 1
        FROM public.game_member_badges AS mgb
        JOIN public.game_badges AS gb
          ON gb.badge_id = mgb.badge_id
        LEFT JOIN public.achievement_definitions AS ad
          ON ad.achievement_code = gb.badge_code
         AND ad.category = 'GAME'
        LEFT JOIN public.member_achievements AS ma
          ON ma.member_id = mgb.member_id
         AND ma.achievement_id = ad.achievement_id
        WHERE ma.member_id IS NULL
           OR ma.source_match_id IS DISTINCT FROM mgb.source_match_id
           OR ma.awarded_at IS DISTINCT FROM mgb.awarded_at
           OR ma.award_event_key IS DISTINCT FROM
              ('GAME_BADGE:' || gb.badge_code)
           OR ma.award_metadata->>'legacy_game_badge_id'
              IS DISTINCT FROM mgb.badge_id::text
    ) THEN
        RAISE EXCEPTION 'Member game badge preservation mismatch';
    END IF;

    RAISE NOTICE
        'PASS: LEGACY_DATA_PRESERVED results=%, event_questions=%, badges=%, member_badges=%',
        (SELECT COUNT(*) FROM public.game_results),
        (SELECT COUNT(*) FROM public.game_event_questions),
        (SELECT COUNT(*) FROM public.game_badges),
        (SELECT COUNT(*) FROM public.game_member_badges);

    -- 원본 카테고리·지원 모드와 새 컬럼이 동일한지 확인
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
        SELECT 1 FROM public.games AS g
        WHERE g.supported_modes IS DISTINCT FROM (
            SELECT array_agg(
                sm.game_mode::TEXT ORDER BY sm.game_mode
            )
            FROM public.game_supported_modes AS sm
            WHERE sm.game_id = g.game_id
        )
    ) THEN
        RAISE EXCEPTION 'Mode migration mismatch';
    END IF;

    -- 기존 경기의 모드가 새 컬럼에서도 유효해야 함
    IF EXISTS (
        SELECT 1
        FROM public.game_matches AS m
        JOIN public.games AS g ON g.game_id = m.game_id
        WHERE NOT (m.game_mode = ANY(g.supported_modes))
    ) THEN
        RAISE EXCEPTION 'Existing match mode mismatch';
    END IF;

    -- 대체 제약조건 확인
    IF (
        SELECT COUNT(*)
        FROM pg_constraint
        WHERE conname IN (
            'chk_games_supported_modes',
            'chk_games_category_code_176',
            'chk_game_questions_category_code_176'
        )
          AND convalidated
    ) <> 3 THEN
        RAISE EXCEPTION 'Required constraints missing';
    END IF;

    -- 대체 트리거 확인
    IF (
        SELECT COUNT(*)
        FROM pg_trigger
        WHERE NOT tgisinternal
          AND tgenabled = 'O'
          AND tgname IN (
              'trg_validate_game_mode_176',
              'trg_protect_game_modes_176',
              'trg_validate_event_questions_176',
              'trg_protect_event_question_176'
          )
    ) <> 4 THEN
        RAISE EXCEPTION 'Required integrity triggers missing';
    END IF;
END $$;

-- 2. 카테고리 정렬 순서까지 보존
ALTER TABLE public.games
ADD COLUMN category_sort_order INTEGER;

UPDATE public.games AS g
SET category_sort_order = c.sort_order
FROM public.game_categories AS c
WHERE g.category_code = c.category_code;

ALTER TABLE public.games
ALTER COLUMN category_sort_order SET NOT NULL;

-- 3. 앞으로 게임 등록·카테고리 변경 시 메타데이터 자동 동기화
CREATE FUNCTION public.fn_sync_game_category_176()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    CASE NEW.category_code
        WHEN 'PYTHON' THEN
            NEW.category_name := 'Python';
            NEW.category_sort_order := 10;
        WHEN 'SQL' THEN
            NEW.category_name := 'SQL';
            NEW.category_sort_order := 20;
        WHEN 'FRONTEND' THEN
            NEW.category_name := 'Frontend';
            NEW.category_sort_order := 30;
        WHEN 'CS' THEN
            NEW.category_name := 'Computer Science';
            NEW.category_sort_order := 40;
        WHEN 'AI' THEN
            NEW.category_name := 'Artificial Intelligence';
            NEW.category_sort_order := 50;
        WHEN 'GENERAL' THEN
            NEW.category_name := '미니게임';
            NEW.category_sort_order := 60;
        ELSE
            RAISE EXCEPTION 'Unknown game category: %',
                NEW.category_code
                USING ERRCODE = '23514';
    END CASE;

    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_sync_game_category_176
BEFORE INSERT OR UPDATE OF
    category_code, category_name, category_sort_order
ON public.games
FOR EACH ROW
EXECUTE FUNCTION public.fn_sync_game_category_176();

-- 4. 최종 카테고리 데이터 이관 검증
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM public.games AS g
        JOIN public.game_categories AS c
          ON c.category_code = g.category_code
        WHERE g.category_sort_order IS DISTINCT FROM c.sort_order
    ) THEN
        RAISE EXCEPTION 'Category sort order mismatch';
    END IF;
END $$;

-- 5. 대체 검증 로직이 준비된 기존 FK 제거
ALTER TABLE public.games
DROP CONSTRAINT games_category_code_fkey;

ALTER TABLE public.game_questions
DROP CONSTRAINT game_questions_category_code_fkey;

ALTER TABLE public.game_matches
DROP CONSTRAINT game_matches_game_id_game_mode_fkey;

-- 6. 기존 테이블 제거
-- RESTRICT: 남아 있는 의존성이 있으면 실패하고 전체 롤백
DROP TABLE public.game_member_badges RESTRICT;
DROP TABLE public.game_badges RESTRICT;
DROP TABLE public.game_results RESTRICT;
DROP TABLE public.game_event_questions RESTRICT;
DROP TABLE public.game_supported_modes RESTRICT;
DROP TABLE public.game_categories RESTRICT;

-- 7. 최종 GameZone 테이블 개수 검증
DO $$
DECLARE
    remaining_tables INTEGER;
BEGIN
    SELECT COUNT(*) INTO remaining_tables
    FROM pg_class AS c
    JOIN pg_namespace AS n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public'
      AND c.relkind = 'r'
      AND (
          c.relname = 'games'
          OR LEFT(c.relname, 5) = 'game_'
      );

    IF remaining_tables <> 9 THEN
        RAISE EXCEPTION
            'Expected 9 game tables, found %',
            remaining_tables;
    END IF;
END $$;

COMMIT;
