-- 043: curriculum → recruit_programs
-- 실행 전 반드시 취업 037~040 및 댓글 041이 반영된 최신 스키마/DB 변경 이력을 확인하세요.
-- 이관을 위한 SQL 초안이며 로컬 PostgreSQL 복원본에서 검증 전 Aiven/RDS 실행 금지.
-- 042과 043는 서로 별도 트랜잭션이며 PostgreSQL에서만 실행합니다.
-- 게시판/취업/공용 posts, career, post_attachments 테이블은 수정하지 않습니다.

-- DATABASE.ZIP 교차검증 후 수정된 검토용 SQL. Aiven/RDS 직접 실행 금지.
-- OPTIONAL REVIEW DRAFT / NOT APPLIED
-- recruit_curricula 물리 테이블 1개를 recruit_programs 컬럼으로 통합한 뒤
-- 기존 코드의 읽기/쓰기 호환을 위해 동일한 이름의 가변 뷰를 둔다.
-- 반드시 database/audit/meetup_preflight.sql 결과와 최신 database/sql 의존성 검토 후 결정.
-- 스터디 커리큘럼은 버전 충돌/잠금 로직이 있으므로 01과 별도 단계로 적용/테스트.
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
