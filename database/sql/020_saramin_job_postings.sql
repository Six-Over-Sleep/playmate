CREATE TABLE IF NOT EXISTS saramin_job_postings (
 id BIGSERIAL PRIMARY KEY,
 source TEXT NOT NULL,
 source_id TEXT NOT NULL,
 title TEXT NOT NULL,
 company TEXT,
 url TEXT NOT NULL,
 deadline_text TEXT,
 location TEXT,
 career TEXT,
 education TEXT,
 employment_type TEXT,
 job_roles JSONB NOT NULL DEFAULT '[]'::jsonb,
 specialties JSONB NOT NULL DEFAULT '[]'::jsonb,
 tech_stacks JSONB NOT NULL DEFAULT '[]'::jsonb,
 preferences JSONB NOT NULL DEFAULT '[]'::jsonb,
 raw_tags JSONB NOT NULL DEFAULT '[]'::jsonb,
 role_classification_source TEXT NOT NULL,
 specialty_classification_source TEXT NOT NULL,
 detail_status TEXT NOT NULL,
 collected_at TIMESTAMP NOT NULL,
 collection_year SMALLINT NOT NULL,
 collection_quarter SMALLINT NOT NULL CHECK (collection_quarter BETWEEN 1 AND 4),
 first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 UNIQUE(source,source_id)
);
CREATE INDEX IF NOT EXISTS idx_saramin_quarter ON saramin_job_postings(collection_year,collection_quarter);
CREATE INDEX IF NOT EXISTS idx_saramin_roles ON saramin_job_postings USING GIN(job_roles);
CREATE INDEX IF NOT EXISTS idx_saramin_specialties ON saramin_job_postings USING GIN(specialties);
CREATE INDEX IF NOT EXISTS idx_saramin_stacks ON saramin_job_postings USING GIN(tech_stacks);
