-- Job postings storage for career insights.
-- Schema mirrors the job_postings table created during the 2026-11-22 DB refactor.
-- Confirm migration number is unused on the target branch before merging.
-- Existing environments: CREATE TABLE IF NOT EXISTS does NOT validate an existing schema.

CREATE TABLE IF NOT EXISTS public.job_postings (
    source_id TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'saramin',
    title TEXT NOT NULL,
    company TEXT,
    url TEXT NOT NULL,
    job_roles TEXT[] NOT NULL DEFAULT '{}',
    specialties TEXT[] NOT NULL DEFAULT '{}',
    tech_stacks TEXT[] NOT NULL DEFAULT '{}',
    raw_tags JSONB,
    role_classification_source TEXT,
    detail_status TEXT,
    collected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    collection_year INTEGER,
    collection_quarter INTEGER,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT pk_job_postings PRIMARY KEY (source, source_id),
    CONSTRAINT ck_job_postings_quarter CHECK (collection_quarter BETWEEN 1 AND 4),
    CONSTRAINT uq_job_postings_url UNIQUE (url)
);

-- Indexes to support commonly used quarterly and array-filter queries.
CREATE INDEX IF NOT EXISTS idx_job_postings_quarter
    ON public.job_postings (collection_year, collection_quarter);
CREATE INDEX IF NOT EXISTS idx_job_postings_roles
    ON public.job_postings USING GIN (job_roles);
CREATE INDEX IF NOT EXISTS idx_job_postings_specialties
    ON public.job_postings USING GIN (specialties);
CREATE INDEX IF NOT EXISTS idx_job_postings_stacks
    ON public.job_postings USING GIN (tech_stacks);
