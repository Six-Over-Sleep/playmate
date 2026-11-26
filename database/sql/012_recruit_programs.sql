-- 신규 프로젝트/스터디 전용 추가형 마이그레이션. 기존 데이터 변경 없음.

-- 공유 DB에는 별도 검토/승인 후 적용. ORM 메타데이터의 PostgreSQL DDL과 동일.

BEGIN;

CREATE TABLE recruit_eligibility (
	member_id BIGINT NOT NULL, 
	withdrawal_count INTEGER NOT NULL, 
	restricted_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (member_id), 
	CONSTRAINT program_withdrawal_nonnegative CHECK (withdrawal_count >= 0), 
	FOREIGN KEY(member_id) REFERENCES members (member_id)
);

CREATE TABLE recruit_programs (
	recruit_id BIGINT NOT NULL, 
	starts_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	ends_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	schedule_version INTEGER NOT NULL, 
	lifecycle_status VARCHAR NOT NULL, 
	payload JSON NOT NULL, 
	details JSON NOT NULL, 
	PRIMARY KEY (recruit_id), 
	CONSTRAINT program_period_valid CHECK (ends_at > starts_at), 
	CONSTRAINT program_version_positive CHECK (schedule_version >= 1), 
	CONSTRAINT program_lifecycle_valid CHECK (lifecycle_status IN ('RECRUITING','READY','IN_PROGRESS','COMPLETED','CANCELED','ABORTED')), 
	FOREIGN KEY(recruit_id) REFERENCES recruits (recruit_id)
);

CREATE INDEX ix_recruit_programs_lifecycle_status ON recruit_programs (lifecycle_status);

CREATE INDEX ix_recruit_programs_starts_at ON recruit_programs (starts_at);

CREATE TABLE recruit_withdrawals (
	event_key VARCHAR(180) NOT NULL, 
	member_id BIGINT NOT NULL, 
	recruit_id BIGINT NOT NULL, 
	occurred_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (event_key), 
	FOREIGN KEY(member_id) REFERENCES members (member_id), 
	FOREIGN KEY(recruit_id) REFERENCES recruits (recruit_id)
);

CREATE TABLE recruit_activities (
	activity_id BIGSERIAL NOT NULL, 
	recruit_id BIGINT NOT NULL, 
	author_member_id BIGINT NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	payload JSON NOT NULL, 
	PRIMARY KEY (activity_id), 
	FOREIGN KEY(recruit_id) REFERENCES recruit_programs (recruit_id), 
	FOREIGN KEY(author_member_id) REFERENCES members (member_id)
);

CREATE INDEX ix_recruit_activities_recruit_id ON recruit_activities (recruit_id);

CREATE TABLE recruit_applications (
	application_id BIGSERIAL NOT NULL, 
	recruit_id BIGINT NOT NULL, 
	member_id BIGINT NOT NULL, 
	sequence INTEGER NOT NULL, 
	submitted_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	status VARCHAR NOT NULL, 
	payload JSON NOT NULL, 
	PRIMARY KEY (application_id), 
	CONSTRAINT program_application_order_positive CHECK (sequence >= 1), 
	CONSTRAINT program_application_status_valid CHECK (status IN ('ACCEPTED','WAITING','CANCELED','LEFT')), 
	CONSTRAINT program_application_sequence_unique UNIQUE (recruit_id, sequence), 
	FOREIGN KEY(recruit_id) REFERENCES recruit_programs (recruit_id), 
	FOREIGN KEY(member_id) REFERENCES members (member_id)
);

CREATE UNIQUE INDEX program_active_member_unique ON recruit_applications (recruit_id, member_id) WHERE status IN ('ACCEPTED', 'WAITING');

CREATE INDEX program_waiting_order ON recruit_applications (recruit_id, status, submitted_at, sequence);

CREATE TABLE recruit_curricula (
	recruit_id BIGINT NOT NULL, 
	version INTEGER NOT NULL, 
	items JSON NOT NULL, 
	PRIMARY KEY (recruit_id), 
	FOREIGN KEY(recruit_id) REFERENCES recruit_programs (recruit_id)
);

CREATE TABLE recruit_outbox (
	event_key VARCHAR(240) NOT NULL, 
	recruit_id BIGINT NOT NULL, 
	kind VARCHAR(50) NOT NULL, 
	schedule_version INTEGER, 
	status VARCHAR(30) NOT NULL, 
	attempts INTEGER NOT NULL, 
	payload JSON NOT NULL, 
	PRIMARY KEY (event_key), 
	FOREIGN KEY(recruit_id) REFERENCES recruit_programs (recruit_id)
);

CREATE INDEX program_outbox_status ON recruit_outbox (status, kind);

CREATE TABLE recruit_program_commands (
	recruit_id BIGINT NOT NULL, 
	request_key VARCHAR(100) NOT NULL, 
	member_id BIGINT NOT NULL, 
	request JSON NOT NULL, 
	response JSON NOT NULL, 
	PRIMARY KEY (recruit_id, request_key), 
	FOREIGN KEY(recruit_id) REFERENCES recruit_programs (recruit_id)
);

CREATE TABLE recruit_recognitions (
	recognition_key VARCHAR(180) NOT NULL, 
	recruit_id BIGINT NOT NULL, 
	member_id BIGINT NOT NULL, 
	activity_id BIGINT NOT NULL, 
	payload JSON NOT NULL, 
	PRIMARY KEY (recognition_key), 
	FOREIGN KEY(recruit_id) REFERENCES recruit_programs (recruit_id), 
	FOREIGN KEY(member_id) REFERENCES members (member_id), 
	FOREIGN KEY(activity_id) REFERENCES recruit_activities (activity_id)
);

COMMIT;
