BEGIN;

CREATE TABLE IF NOT EXISTS xp_award_policies (
    activity_type TEXT PRIMARY KEY,
    xp_amount INTEGER NOT NULL CHECK (xp_amount > 0)
);

INSERT INTO xp_award_policies (activity_type, xp_amount)
VALUES
    ('ATTEND', 1),
    ('POST', 5),
    ('COMMENT', 2),
    ('REPLY', 2),
    ('STREAK_7', 5),
    ('STREAK_30', 20),
    ('POST_LIKE', 1),
    ('CAREER_DOCUMENT', 30),
    ('CAREER_INTERVIEW', 50),
    ('CAREER_SUCCESS', 50),
    ('CAREER_GUIDE', 50),
    ('MEETUP_PARTICIPATION', 10),
    ('MEETUP_STUDY_WEEKLY', 15),
    ('MEETUP_PROJECT_INTERIM', 15),
    ('MEETUP_STUDY_COMPLETE', 30),
    ('MEETUP_PROJECT_COMPLETE', 50),
    ('MEETUP_REVIEW', 10),
    ('MEETUP_PROJECT_LEADER', 20),
    ('CAREER_SPEC_PUBLIC', 50)
ON CONFLICT (activity_type) DO NOTHING;

COMMIT;
