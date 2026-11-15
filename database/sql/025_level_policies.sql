BEGIN;

-- 종합 레벨(OVERALL)과 스킬 레벨(SKILL)의 레벨별 시작 누적 XP.
-- 레벨은 1부터 빠짐없이 이어지고, 레벨 1은 0 XP에서 시작하며,
-- 높은 레벨일수록 시작 XP가 커야 한다. 순서 조건은 앱에서 검사하고
-- 조건이 맞지 않으면 레벨 계산 API가 503을 반환한다.
CREATE TABLE IF NOT EXISTS level_policies (
    level_type TEXT NOT NULL CHECK (level_type IN ('OVERALL', 'SKILL')),
    level INTEGER NOT NULL CHECK (level >= 1),
    min_xp INTEGER NOT NULL CHECK (min_xp >= 0),
    PRIMARY KEY (level_type, level),
    UNIQUE (level_type, min_xp),
    CHECK ((level = 1) = (min_xp = 0))
);

-- 기존 코드 기준값. 다시 실행하면 누락된 행만 복구하고 변경한 값은 유지한다.
INSERT INTO level_policies (level_type, level, min_xp)
VALUES
    ('OVERALL', 1, 0),
    ('OVERALL', 2, 100),
    ('OVERALL', 3, 500),
    ('OVERALL', 4, 1500),
    ('SKILL', 1, 0),
    ('SKILL', 2, 50),
    ('SKILL', 3, 150),
    ('SKILL', 4, 300),
    ('SKILL', 5, 500)
ON CONFLICT (level_type, level) DO NOTHING;

-- 기존 member_levels는 레벨 상한을 4로 고정했다(CHECK level BETWEEN 1 AND 4).
-- 상한은 이제 level_policies가 정하므로 하한만 남긴다. 다시 실행해도 같은 결과다.
ALTER TABLE member_levels DROP CONSTRAINT IF EXISTS member_levels_level_check;
ALTER TABLE member_levels ADD CONSTRAINT member_levels_level_check CHECK (level >= 1);

COMMIT;

-- 기준값을 바꾼 뒤 저장된 레벨을 새 기준으로 맞추려면 아래를 실행한다.
-- UPDATE member_levels m
-- SET level = (SELECT MAX(p.level) FROM level_policies p
--              WHERE p.level_type = 'OVERALL' AND p.min_xp <= m.total_xp);
-- UPDATE member_skill_levels m
-- SET level = (SELECT MAX(p.level) FROM level_policies p
--              WHERE p.level_type = 'SKILL' AND p.min_xp <= m.total_xp);
