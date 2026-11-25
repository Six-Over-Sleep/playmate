-- Issue #176 / GameZone achievements consolidation
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

-- 2. Allow GAME achievement category
ALTER TABLE public.achievement_definitions
DROP CONSTRAINT IF EXISTS chk_achievement_category;

ALTER TABLE public.achievement_definitions
ADD CONSTRAINT chk_achievement_category
CHECK (
    category IN (
        'COMMUNITY',
        'SKILL',
        'SOCIAL',
        'EVENT',
        'GAME'
    )
);

-- 3. Preserve source game match relationship
ALTER TABLE public.member_achievements
ADD COLUMN IF NOT EXISTS source_match_id BIGINT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'public.member_achievements'::regclass
          AND conname = 'fk_member_achievements_source_match'
    ) THEN
        ALTER TABLE public.member_achievements
        ADD CONSTRAINT fk_member_achievements_source_match
        FOREIGN KEY (source_match_id)
        REFERENCES public.game_matches(match_id)
        ON DELETE SET NULL;
    END IF;
END $$;

-- 4. Reject conflicting achievement codes
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM public.game_badges AS gb
        JOIN public.achievement_definitions AS ad
          ON ad.achievement_code = gb.badge_code
        WHERE ad.category <> 'GAME'
           OR ad.award_rule IS DISTINCT FROM gb.award_rule
    ) THEN
        RAISE EXCEPTION 'Conflicting achievement definitions';
    END IF;
END $$;

-- 5. Copy legacy game badge definitions
INSERT INTO public.achievement_definitions (
    achievement_code,
    achievement_name,
    description,
    category,
    award_rule,
    is_active,
    created_at
)
SELECT
    badge_code,
    badge_name,
    description,
    'GAME',
    award_rule,
    is_active,
    created_at
FROM public.game_badges
ON CONFLICT (achievement_code) DO NOTHING;

-- 6. Copy legacy member game badge awards
INSERT INTO public.member_achievements (
    member_id,
    achievement_id,
    award_event_key,
    awarded_at,
    award_metadata,
    source_match_id
)
SELECT
    mgb.member_id,
    ad.achievement_id,
    'GAME_BADGE:' || gb.badge_code,
    mgb.awarded_at,
    jsonb_build_object(
        'legacy_game_badge_id', mgb.badge_id
    ),
    mgb.source_match_id
FROM public.game_member_badges AS mgb
JOIN public.game_badges AS gb
  ON gb.badge_id = mgb.badge_id
JOIN public.achievement_definitions AS ad
  ON ad.achievement_code = gb.badge_code
 AND ad.category = 'GAME'
ON CONFLICT (member_id, achievement_id) DO NOTHING;

-- 7. Verify preservation of legacy badge records
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM public.game_badges AS gb
        LEFT JOIN public.achievement_definitions AS ad
          ON ad.achievement_code = gb.badge_code
        WHERE ad.achievement_id IS NULL
           OR ad.category IS DISTINCT FROM 'GAME'
           OR ad.award_rule IS DISTINCT FROM gb.award_rule
    ) THEN
        RAISE EXCEPTION 'Game badge definition migration mismatch';
    END IF;

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
    ) THEN
        RAISE EXCEPTION 'Member game badge migration mismatch';
    END IF;
END $$;

COMMIT;
