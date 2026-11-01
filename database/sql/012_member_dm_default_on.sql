-- Discord DM 알림 기본값 ON (Issue #61)
-- 적용 전 검토용: 공용 DB 적용은 DB 담당자와 협의 후 진행
--
-- 값의 의미
--   TRUE  : 알림 받음 (신규 가입 기본값, /알림설정으로 켬)
--   FALSE : 회원이 /알림설정으로 직접 끔 -> 그대로 유지
--   NULL  : 아직 선택 안 함 -> Discord Bot이 ON으로 처리
-- 기존 행은 바꾸지 않음 (UPDATE 없음). 컬럼 기본값만 바꿔 이후 INSERT에 적용됨.

BEGIN;

ALTER TABLE members
ALTER COLUMN external_dm_opt_in SET DEFAULT TRUE;

COMMENT ON COLUMN members.external_dm_opt_in IS
'Discord DM 알림. TRUE: 받음(기본) / FALSE: 회원이 끔 / NULL: 선택 안 함(ON으로 처리)';

COMMIT;

-- 되돌리기
-- ALTER TABLE members ALTER COLUMN external_dm_opt_in DROP DEFAULT;
