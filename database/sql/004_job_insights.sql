-- 기존 public 스키마와 분리된 취업 통계 저장소. 호출자가 트랜잭션을 관리한다.
CREATE SCHEMA IF NOT EXISTS job_insights;

CREATE TABLE IF NOT EXISTS job_insights.fields (
    field_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    field_code TEXT NOT NULL UNIQUE,
    field_name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS job_insights.roles (
    role_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    field_id BIGINT NOT NULL REFERENCES job_insights.fields(field_id),
    role_code TEXT NOT NULL UNIQUE,
    role_name TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS roles_field_idx ON job_insights.roles(field_id);

CREATE TABLE IF NOT EXISTS job_insights.postings (
    posting_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source TEXT NOT NULL CHECK (source IN ('mock', 'saramin')),
    source_job_id TEXT NOT NULL CHECK (length(trim(source_job_id)) > 0),
    source_url TEXT,
    is_active BOOLEAN,
    posted_at TIMESTAMPTZ,
    modified_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,
    company_name TEXT,
    title TEXT,
    location_code TEXT,
    location_name TEXT,
    job_type_code TEXT,
    industry_code TEXT,
    industry_name TEXT,
    job_mid_code TEXT,
    job_code TEXT,
    experience_code TEXT,
    education_code TEXT,
    keyword_text TEXT,
    salary_code TEXT,
    salary_name TEXT,
    salary_min_manwon INTEGER CHECK (salary_min_manwon >= 0),
    salary_max_manwon INTEGER CHECK (salary_max_manwon >= salary_min_manwon),
    raw_payload JSONB NOT NULL CHECK (jsonb_typeof(raw_payload) = 'object'),
    collected_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (source, source_job_id)
);
CREATE INDEX IF NOT EXISTS postings_source_date_idx ON job_insights.postings(source, posted_at);
CREATE TABLE IF NOT EXISTS job_insights.posting_roles (
    posting_id BIGINT NOT NULL REFERENCES job_insights.postings(posting_id) ON DELETE CASCADE,
    role_id BIGINT NOT NULL REFERENCES job_insights.roles(role_id),
    is_primary BOOLEAN NOT NULL DEFAULT FALSE,
    assignment_source TEXT NOT NULL DEFAULT 'manual' CHECK (assignment_source IN ('manual', 'title')),
    PRIMARY KEY (posting_id, role_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS posting_one_primary_idx
    ON job_insights.posting_roles(posting_id) WHERE is_primary;
CREATE INDEX IF NOT EXISTS posting_roles_role_idx ON job_insights.posting_roles(role_id);
CREATE TABLE IF NOT EXISTS job_insights.keywords (
    keyword_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    keyword_code TEXT NOT NULL UNIQUE,
    keyword_name TEXT NOT NULL,
    keyword_type TEXT NOT NULL CHECK (keyword_type IN ('skill', 'certification'))
);
CREATE TABLE IF NOT EXISTS job_insights.keyword_aliases (
    alias_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    keyword_id BIGINT NOT NULL REFERENCES job_insights.keywords(keyword_id),
    alias_text TEXT NOT NULL CHECK (length(trim(alias_text)) > 0),
    UNIQUE (keyword_id, alias_text)
);
CREATE TABLE IF NOT EXISTS job_insights.posting_keywords (
    posting_id BIGINT NOT NULL REFERENCES job_insights.postings(posting_id) ON DELETE CASCADE,
    keyword_id BIGINT NOT NULL REFERENCES job_insights.keywords(keyword_id),
    mention_source TEXT NOT NULL CHECK (mention_source IN ('api_keyword', 'title', 'requirement', 'preference')),
    PRIMARY KEY (posting_id, keyword_id, mention_source)
);
CREATE INDEX IF NOT EXISTS posting_keywords_keyword_idx ON job_insights.posting_keywords(keyword_id);
