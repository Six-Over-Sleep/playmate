-- Issue #176 / Badge FK cutover
-- PostgreSQL 18 / isolated Docker test DB only
-- Legacy badge tables are preserved.

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


    -- 통합 업적 FK가 실제로 존재하는지 검증
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'public.member_profile_preferences'::regclass
          AND confrelid = 'public.member_achievements'::regclass
          AND conname = 'fk_member_profile_owned_achievement'
    ) THEN
        RAISE EXCEPTION 'Unified profile achievement FK is missing';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'public.user_notifications'::regclass
          AND confrelid = 'public.achievement_definitions'::regclass
          AND conname = 'user_notifications_achievement_id_fkey'
    ) THEN
        RAISE EXCEPTION 'Unified notification achievement FK is missing';
    END IF;
END $$;

-- 2. 대표 배지 참조를 통합 업적 컬럼 하나로 정리

-- Map existing profile and notification references before removing old columns.
DO $$
DECLARE
    v_profiles_before BIGINT;
    v_notifications_before BIGINT;
    v_profiles_updated BIGINT;
    v_notifications_updated BIGINT;
BEGIN
    SELECT COUNT(*) INTO v_profiles_before
    FROM public.member_profile_preferences
    WHERE featured_game_badge_id IS NOT NULL;

    SELECT COUNT(*) INTO v_notifications_before
    FROM public.user_notifications
    WHERE game_badge_id IS NOT NULL;

    -- A featured GAME achievement must already belong to the member.
    IF EXISTS (
        SELECT 1
        FROM public.member_profile_preferences AS p
        LEFT JOIN public.game_badges AS gb
          ON gb.badge_id = p.featured_game_badge_id
        LEFT JOIN public.achievement_definitions AS ad
          ON ad.achievement_code = gb.badge_code
         AND ad.category = 'GAME'
        LEFT JOIN public.member_achievements AS ma
          ON ma.member_id = p.member_id
         AND ma.achievement_id = ad.achievement_id
        WHERE p.featured_game_badge_id IS NOT NULL
          AND (
              ad.achievement_id IS NULL
              OR ma.member_id IS NULL
              OR p.featured_achievement_id IS NOT NULL
          )
    ) THEN
        RAISE EXCEPTION 'Unmappable or conflicting featured game badge';
    END IF;

    -- Every legacy badge notification must have a GAME achievement.
    IF EXISTS (
        SELECT 1
        FROM public.user_notifications AS n
        LEFT JOIN public.game_badges AS gb
          ON gb.badge_id = n.game_badge_id
        LEFT JOIN public.achievement_definitions AS ad
          ON ad.achievement_code = gb.badge_code
         AND ad.category = 'GAME'
        WHERE n.game_badge_id IS NOT NULL
          AND (
              ad.achievement_id IS NULL
              OR n.achievement_id IS NOT NULL
          )
    ) THEN
        RAISE EXCEPTION 'Unmappable or conflicting game badge notification';
    END IF;

    -- Set the new reference and clear the old one atomically.
    UPDATE public.member_profile_preferences AS p
    SET featured_achievement_id = ad.achievement_id,
        featured_game_badge_id = NULL
    FROM public.game_badges AS gb
    JOIN public.achievement_definitions AS ad
      ON ad.achievement_code = gb.badge_code
     AND ad.category = 'GAME'
    WHERE p.featured_game_badge_id = gb.badge_id;

    GET DIAGNOSTICS v_profiles_updated = ROW_COUNT;

    UPDATE public.user_notifications AS n
    SET achievement_id = ad.achievement_id,
        game_badge_id = NULL
    FROM public.game_badges AS gb
    JOIN public.achievement_definitions AS ad
      ON ad.achievement_code = gb.badge_code
     AND ad.category = 'GAME'
    WHERE n.game_badge_id = gb.badge_id;

    GET DIAGNOSTICS v_notifications_updated = ROW_COUNT;

    IF v_profiles_updated <> v_profiles_before
       OR v_notifications_updated <> v_notifications_before
       OR EXISTS (
           SELECT 1 FROM public.member_profile_preferences
           WHERE featured_game_badge_id IS NOT NULL
       )
       OR EXISTS (
           SELECT 1 FROM public.user_notifications
           WHERE game_badge_id IS NOT NULL
       ) THEN
        RAISE EXCEPTION 'Legacy badge reference migration mismatch';
    END IF;

    RAISE NOTICE
        'PASS: LEGACY_BADGE_REFERENCES_MAPPED profiles=%, notifications=%',
        v_profiles_updated,
        v_notifications_updated;
END $$;

ALTER TABLE public.member_profile_preferences
    DROP CONSTRAINT chk_member_profile_one_badge;

ALTER TABLE public.member_profile_preferences
    DROP COLUMN featured_game_badge_id RESTRICT;

ALTER TABLE public.member_profile_preferences
    ADD CONSTRAINT chk_member_profile_one_badge
    CHECK (
        featured_achievement_id IS NULL
        OR featured_achievement_id > 0
    );

-- 3. 알림 대상도 통합 업적 컬럼으로 정리
ALTER TABLE public.user_notifications
    DROP CONSTRAINT chk_user_notifications_one_target;

ALTER TABLE public.user_notifications
    DROP COLUMN game_badge_id RESTRICT;

ALTER TABLE public.user_notifications
    ADD CONSTRAINT chk_user_notifications_one_target
    CHECK (
        NUM_NONNULLS(
            post_id,
            comment_id,
            dm_message_id,
            achievement_id
        ) <= 1
    );

COMMIT;
