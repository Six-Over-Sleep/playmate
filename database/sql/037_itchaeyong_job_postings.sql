-- IT 채용 레이더 전용. 기존 사람인 테이블/데이터를 변경하지 않습니다.
CREATE TABLE IF NOT EXISTS itchaeyong_job_postings (
    id BIGSERIAL PRIMARY KEY,
    source TEXT NOT NULL CHECK(source = 'itchaeyong'),
    source_job_id TEXT NOT NULL,
    job_url TEXT NOT NULL,
    original_url TEXT,
    company_name TEXT,
    job_title TEXT NOT NULL,
    job_category TEXT NOT NULL CHECK(job_category = 'dev'),
    job_role TEXT[] NOT NULL DEFAULT '{}',
    experience TEXT,
    employment_type TEXT,
    location TEXT,
    tech_stack TEXT[] NOT NULL DEFAULT '{}',
    requirements TEXT[] NOT NULL DEFAULT '{}',
    preferred_qualifications TEXT[] NOT NULL DEFAULT '{}',
    posted_at TIMESTAMPTZ,
    deadline_at TIMESTAMPTZ,
    collected_at TIMESTAMPTZ NOT NULL,
    detail_status TEXT NOT NULL,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(source,source_job_id)
);
CREATE INDEX IF NOT EXISTS idx_itchaeyong_posted ON itchaeyong_job_postings(posted_at);
CREATE INDEX IF NOT EXISTS idx_itchaeyong_collected ON itchaeyong_job_postings(collected_at);
CREATE INDEX IF NOT EXISTS idx_itchaeyong_roles ON itchaeyong_job_postings USING GIN(job_role);
CREATE INDEX IF NOT EXISTS idx_itchaeyong_stacks ON itchaeyong_job_postings USING GIN(tech_stack);
