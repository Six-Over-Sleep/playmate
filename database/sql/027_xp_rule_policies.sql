BEGIN;

-- 스킬 학습 XP 지급량. 코드(skill_xp_service.SKILL_XP_RULES)에 있던 값을 정책 행으로 옮긴다.
INSERT INTO xp_award_policies (activity_type, xp_amount)
VALUES
    ('SKILL_QUIZ', 5),
    ('SKILL_PRACTICE', 10),
    ('SKILL_ADVANCED', 20)
ON CONFLICT (activity_type) DO NOTHING;

-- XP 지급 한도. 코드에 있던 하루 횟수·게시글당 상한을 정책 행으로 옮긴다.
-- 행이 없으면 해당 XP 지급 API는 503을 반환한다(지급량 정책과 같은 규칙).
CREATE TABLE IF NOT EXISTS xp_limit_policies (
    limit_key TEXT PRIMARY KEY,
    limit_value INTEGER NOT NULL CHECK (limit_value > 0)
);

INSERT INTO xp_limit_policies (limit_key, limit_value)
VALUES
    ('POST_DAILY_COUNT', 3),        -- 게시글 작성 XP 하루 지급 횟수
    ('COMMENT_DAILY_COUNT', 10),    -- 댓글·대댓글 XP 하루 지급 횟수(합산)
    ('POST_LIKE_XP_PER_POST', 10)   -- 게시글 하나가 받은 좋아요로 작성자가 얻는 최대 XP
ON CONFLICT (limit_key) DO NOTHING;

COMMIT;

-- 연속 출석 보너스 기준일은 별도 컬럼 없이 xp_award_policies의 'STREAK_<일수>' 행으로 정한다.
-- 예: INSERT INTO xp_award_policies VALUES ('STREAK_100', 50); → 100일째 출석에 50XP 보너스
