-- 043: 모임 커리큘럼 테이블 통합
-- Issue: #157
-- 대상 DB: PostgreSQL 18
--
-- 변경 내용:
--   recruit_curricula 물리 테이블을 recruit_programs로 통합.
--   기존 커리큘럼 이름은 쓰기 가능한 호환 뷰로 유지.
--   커리큘럼 버전 및 데이터 관리 구조 통합.
--
-- 적용 및 검증 상태 (2026-11-22):
--   [완료] PostgreSQL 18 로컬 복원본 마이그레이션 검증
--   [완료] Aiven DB 마이그레이션 적용
--   [완료] recruit_curricula 호환 뷰 생성 확인
--   [완료] 관련 제약조건 및 트리거 확인
--   [미적용] AWS RDS 마이그레이션
--
-- 주의사항:
--   1. 042 적용 이후 실행할 것.
--   2. 적용 완료된 Aiven DB에 재실행하지 말 것.
--   3. 신규 DB 적용 전 백업·권한·객체 의존성 확인.
--   4. 커리큘럼 버전 충돌 및 잠금 정책 검증 필요.
--   5. ACCESS EXCLUSIVE LOCK이 발생하므로 유지보수 시간에 적용.

BEGIN;
SET LOCAL lock_timeout='5s';
SET LOCAL statement_timeout='120s';
SELECT pg_advisory_xact_lock(87520043);
LOCK TABLE public.recruit_programs, public.recruit_curricula IN ACCESS EXCLUSIVE MODE;
DO $$
BEGIN
 IF NOT EXISTS (
  SELECT 1 FROM pg_class c JOIN pg_namespace n ON c.relnamespace=n.oid
  WHERE n.nspname='public' AND c.relname='recruit_curricula' AND c.relkind='r'
 ) THEN RAISE EXCEPTION 'recruit_curricula is not a physical table'; END IF;
 IF pg_get_userbyid((SELECT relowner FROM pg_class WHERE oid='public.recruit_curricula'::regclass)) <> current_user THEN
   RAISE EXCEPTION 'Execute as owner of recruit_curricula'; END IF;
 IF EXISTS (
  SELECT 1 FROM pg_class c CROSS JOIN LATERAL
    aclexplode(COALESCE(c.relacl,acldefault('r',c.relowner))) e
  WHERE c.oid='public.recruit_curricula'::regclass AND e.grantee <> c.relowner
    AND e.privilege_type IN ('TRUNCATE','REFERENCES')
 ) THEN RAISE EXCEPTION 'Unsupported non-owner grant on curriculum table'; END IF;
 IF EXISTS (
  SELECT 1 FROM information_schema.columns
  WHERE table_schema='public' AND table_name='recruit_programs'
    AND column_name IN ('meetup_curriculum_version','meetup_curriculum_items')
 ) THEN RAISE EXCEPTION 'Curriculum destination columns already exist'; END IF;
 IF EXISTS (
  SELECT 1 FROM pg_trigger t
  WHERE t.tgrelid='public.recruit_curricula'::regclass AND NOT t.tgisinternal
 ) THEN RAISE EXCEPTION 'Custom recruit_curricula trigger detected'; END IF;
 IF EXISTS (
  SELECT 1 FROM pg_indexes i WHERE i.schemaname='public'
   AND i.tablename='recruit_curricula' AND i.indexname <> 'recruit_curricula_pkey'
 ) THEN RAISE EXCEPTION 'Additional curriculum index detected'; END IF;
END $$;

CREATE TEMP TABLE _meetup_curriculum_grants ON COMMIT DROP AS
SELECT c.relname AS relation_name, e.grantee, e.privilege_type, e.is_grantable
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
CROSS JOIN LATERAL aclexplode(COALESCE(c.relacl,acldefault('r',c.relowner))) e
WHERE n.nspname='public' AND c.relname='recruit_curricula'
 AND e.grantee <> c.relowner
 AND e.privilege_type IN ('SELECT','INSERT','UPDATE','DELETE','TRIGGER');

CREATE TEMP TABLE _meetup_curriculum_original_count ON COMMIT DROP AS
SELECT COUNT(*)::bigint AS total FROM public.recruit_curricula;
CREATE TEMP TABLE _meetup_curriculum_original_rows ON COMMIT DROP AS
SELECT recruit_id, version, items::jsonb AS items FROM public.recruit_curricula;

ALTER TABLE public.recruit_programs
 ADD COLUMN meetup_curriculum_version integer NULL,
 ADD COLUMN meetup_curriculum_items jsonb NULL;
ALTER TABLE public.recruit_programs ADD CONSTRAINT ck_recruit_curriculum_pair
 CHECK ((meetup_curriculum_version IS NULL) = (meetup_curriculum_items IS NULL));

UPDATE public.recruit_programs p
SET meetup_curriculum_version=c.version, meetup_curriculum_items=c.items::jsonb
FROM public.recruit_curricula c WHERE p.recruit_id=c.recruit_id;

DO $$ BEGIN
 IF EXISTS (
  SELECT 1 FROM public.recruit_curricula c
  LEFT JOIN public.recruit_programs p USING(recruit_id)
  WHERE p.recruit_id IS NULL OR p.meetup_curriculum_version IS DISTINCT FROM c.version
     OR p.meetup_curriculum_items IS DISTINCT FROM c.items::jsonb
 ) THEN RAISE EXCEPTION 'Curriculum data comparison failed'; END IF;
END $$;

-- 참조 FK/뷰 등이 있으면 RESTRICT가 안전하게 실패시킴.
DROP TABLE public.recruit_curricula RESTRICT;
CREATE VIEW public.recruit_curricula AS
 SELECT recruit_id, meetup_curriculum_version AS version,
        meetup_curriculum_items::json AS items
 FROM public.recruit_programs WHERE meetup_curriculum_version IS NOT NULL;

CREATE FUNCTION public._meetup_compat_curriculum_write() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP <> 'DELETE' AND (NEW.version IS NULL OR NEW.items IS NULL) THEN
  RAISE EXCEPTION 'Curriculum version/items cannot be NULL' USING ERRCODE='23502';
 END IF;
 IF TG_OP='DELETE' THEN
  UPDATE public.recruit_programs SET meetup_curriculum_version=NULL,meetup_curriculum_items=NULL
  WHERE recruit_id=OLD.recruit_id AND meetup_curriculum_version IS NOT NULL;
  IF NOT FOUND THEN RAISE EXCEPTION 'Missing curriculum for %',OLD.recruit_id; END IF;
  RETURN OLD;
 ELSIF TG_OP='UPDATE' THEN
  IF NEW.recruit_id IS DISTINCT FROM OLD.recruit_id THEN
   RAISE EXCEPTION 'Curriculum recruit_id is immutable';
  END IF;
  UPDATE public.recruit_programs
  SET meetup_curriculum_version=NEW.version, meetup_curriculum_items=NEW.items::jsonb
  WHERE recruit_id=NEW.recruit_id AND meetup_curriculum_version IS NOT NULL;
 ELSIF TG_OP='INSERT' THEN
  UPDATE public.recruit_programs
  SET meetup_curriculum_version=NEW.version, meetup_curriculum_items=NEW.items::jsonb
  WHERE recruit_id=NEW.recruit_id AND meetup_curriculum_version IS NULL;
 ELSE RAISE EXCEPTION 'Unsupported curriculum operation %',TG_OP;
 END IF;
 IF NOT FOUND THEN RAISE EXCEPTION 'Missing program or duplicate curriculum %',NEW.recruit_id; END IF;
 RETURN NEW;
END $$;

CREATE TRIGGER meetup_curriculum_write_instead INSTEAD OF INSERT OR UPDATE OR DELETE
ON public.recruit_curricula FOR EACH ROW EXECUTE FUNCTION public._meetup_compat_curriculum_write();

DO $$ BEGIN
 IF EXISTS (
  SELECT recruit_id, version, items FROM _meetup_curriculum_original_rows
  EXCEPT ALL SELECT recruit_id, version, items::jsonb FROM public.recruit_curricula
 ) OR EXISTS (
  SELECT recruit_id, version, items::jsonb FROM public.recruit_curricula
  EXCEPT ALL SELECT recruit_id, version, items FROM _meetup_curriculum_original_rows
 ) THEN RAISE EXCEPTION 'Curriculum values differ after view conversion'; END IF;
END $$;

DO $$ DECLARE total bigint; BEGIN
 SELECT count(*) INTO total FROM public.recruit_curricula;
 IF total <> (SELECT c.total FROM _meetup_curriculum_original_count c) THEN
  RAISE EXCEPTION 'Curriculum view count mismatch'; END IF;
END $$;

DO $$ DECLARE x record; target_sql text;
BEGIN
 FOR x IN SELECT * FROM _meetup_curriculum_grants LOOP
  target_sql := CASE WHEN x.grantee=0 THEN 'PUBLIC' ELSE format('%I',pg_get_userbyid(x.grantee)) END;
  EXECUTE format('GRANT %s ON TABLE public.%I TO %s %s',
    x.privilege_type,x.relation_name,target_sql,
    CASE WHEN x.is_grantable THEN 'WITH GRANT OPTION' ELSE '' END);
 END LOOP;
END $$;
COMMIT;
