-- PLAYMATE #85 회원 탈퇴 상태 관리. 운영 DB 백업 후 1회 실행.
-- 자동 수정 스크립트는 SQL 파일만 만들며 DB에 직접 접속하지 않습니다.
BEGIN;

ALTER TABLE members ADD COLUMN IF NOT EXISTS member_status VARCHAR(20);
UPDATE members SET member_status = 'ACTIVE' WHERE member_status IS NULL;
ALTER TABLE members ALTER COLUMN member_status SET DEFAULT 'ACTIVE';
ALTER TABLE members ALTER COLUMN member_status SET NOT NULL;

COMMIT;
