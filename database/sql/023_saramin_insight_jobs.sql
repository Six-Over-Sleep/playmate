-- 신규 인사이트 전용 테이블. 기존 saramin_job_postings / career_news 테이블을 변경하지 않습니다.
CREATE TABLE IF NOT EXISTS saramin_insight_jobs (
    source_id TEXT PRIMARY KEY,
    source TEXT NOT NULL DEFAULT 'saramin_web',
    title TEXT NOT NULL,
    company TEXT,
    url TEXT NOT NULL,
    job_roles TEXT[] NOT NULL DEFAULT '{}',
    specialties TEXT[] NOT NULL DEFAULT '{}',
    tech_stacks TEXT[] NOT NULL DEFAULT '{}',
    certifications TEXT[] NOT NULL DEFAULT '{}',
    preferences TEXT[] NOT NULL DEFAULT '{}',
    raw_tags TEXT[] NOT NULL DEFAULT '{}',
    role_classification_source TEXT,
    detail_status TEXT,
    collected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    collection_year INT NOT NULL,
    collection_quarter INT NOT NULL CHECK(collection_quarter BETWEEN 1 AND 4),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_saramin_insight_quarter ON saramin_insight_jobs(collection_year,collection_quarter);
CREATE INDEX IF NOT EXISTS idx_saramin_insight_roles ON saramin_insight_jobs USING GIN(job_roles);
CREATE INDEX IF NOT EXISTS idx_saramin_insight_specialties ON saramin_insight_jobs USING GIN(specialties);
CREATE INDEX IF NOT EXISTS idx_saramin_insight_stacks ON saramin_insight_jobs USING GIN(tech_stacks);
