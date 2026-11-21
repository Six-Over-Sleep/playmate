-- 042: legacy category details → recruits.details
-- 실행 전 반드시 취업 037~040 및 댓글 041이 반영된 최신 스키마/DB 변경 이력을 확인하세요.
-- 이관을 위한 SQL 초안이며 로컬 PostgreSQL 복원본에서 검증 전 Aiven/RDS 실행 금지.
-- 042과 043는 서로 별도 트랜잭션이며 PostgreSQL에서만 실행합니다.
-- 게시판/취업/공용 posts, career, post_attachments 테이블은 수정하지 않습니다.

-- DATABASE.ZIP 교차검증 후 수정된 검토용 SQL. Aiven/RDS 직접 실행 금지.
-- REVIEW DRAFT / NOT APPLIED: 모임 상세 4종 → recruits.details JSONB
-- 반드시 동일 버전 스키마 백업, 복원 DB의 테스트 및 SQL 사전검증 후 적용.
-- 이 파일은 사용자가 제공한 backend(2).zip + 이전 playmate_schema.sql을 기준으로 작성.
-- 현재 Aiven/RDS 객체·권한·의존성을 직접 검증하지 않은 상태.
-- 이슈 #157: 기존 댓글 041과 번호 충돌을 피하기 위해 042/043으로 변경. 최종 적용 전 최신 번호 재확인.
-- 트랜잭션 중 ACCESS EXCLUSIVE LOCK이 걸리므로 유지보수 시간에만 수행.
-- 기존 백엔드 소스 변경 없이 조회/INSERT/UPDATE/DELETE를 지원하는 호환 뷰를 생성.

BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '120s';
SELECT pg_advisory_xact_lock(87520042);

LOCK TABLE public.recruits,
           public.recruit_sports_details, public.recruit_game_details,
           public.recruit_study_details, public.recruit_group_buy_details
IN ACCESS EXCLUSIVE MODE;

-- 이미 변환된 DB, 테이블이 아닌 동명 뷰, 별도 세부 컬럼 사용 등은 자동 덮어쓰지 않음.
DO $$
DECLARE relation_name text;
BEGIN
    FOREACH relation_name IN ARRAY ARRAY[
        'recruit_sports_details','recruit_game_details',
        'recruit_study_details','recruit_group_buy_details']
    LOOP
        IF NOT EXISTS (
            SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='public' AND c.relname=relation_name AND c.relkind='r'
        ) THEN
            RAISE EXCEPTION 'Expected ordinary physical table public.%, aborting', relation_name;
        END IF;
        IF EXISTS (
            SELECT 1 FROM pg_trigger t
            WHERE t.tgrelid=to_regclass(format('public.%I',relation_name))
              AND NOT t.tgisinternal
        ) THEN
            RAISE EXCEPTION 'Custom trigger on %. Review before migration', relation_name;
        END IF;
        IF EXISTS (
            SELECT 1 FROM pg_indexes i WHERE i.schemaname='public'
              AND i.tablename=relation_name AND i.indexname <> relation_name || '_pkey'
        ) THEN
            RAISE EXCEPTION 'Additional index on %. Review before migration', relation_name;
        END IF;
    END LOOP;
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema='public' AND table_name='recruits' AND column_name='details'
    ) THEN
        RAISE EXCEPTION 'recruits.details already exists: potential naming collision';
    END IF;
    -- 운영자의 ROLE이 현재 상세 테이블 소유자가 아닌 경우 권한/OWNER 복원이 달라질 수 있으므로 중단.
    IF EXISTS (
        SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='public' AND c.relname IN
          ('recruit_sports_details','recruit_game_details',
           'recruit_study_details','recruit_group_buy_details')
          AND pg_get_userbyid(c.relowner) <> current_user
    ) THEN
        RAISE EXCEPTION 'Execute as the owner of all 4 detail tables (check current_user)';
    END IF;
    -- 타 역할이 사용하던 TRUNCATE/REFERENCES 권한은 VIEW로 유지할 수 없어 자동 적용 금지.
    IF EXISTS (
        SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        CROSS JOIN LATERAL aclexplode(COALESCE(c.relacl,acldefault('r',c.relowner))) e
        WHERE n.nspname='public' AND c.relname IN
          ('recruit_sports_details','recruit_game_details',
           'recruit_study_details','recruit_group_buy_details')
          AND e.grantee <> c.relowner
          AND e.privilege_type IN ('TRUNCATE','REFERENCES')
    ) THEN
        RAISE EXCEPTION 'Non-owner TRUNCATE/REFERENCES grants cannot be preserved on views';
    END IF;
    IF EXISTS (
       SELECT 1 FROM public.recruit_sports_details d LEFT JOIN public.recruits r USING(recruit_id)
       WHERE r.recruit_id IS NULL OR r.category IS DISTINCT FROM 'sports'
    ) OR EXISTS (
       SELECT 1 FROM public.recruit_game_details d LEFT JOIN public.recruits r USING(recruit_id)
       WHERE r.recruit_id IS NULL OR r.category IS DISTINCT FROM 'game'
    ) OR EXISTS (
       SELECT 1 FROM public.recruit_study_details d LEFT JOIN public.recruits r USING(recruit_id)
       WHERE r.recruit_id IS NULL OR r.category IS DISTINCT FROM 'study'
    ) OR EXISTS (
       SELECT 1 FROM public.recruit_group_buy_details d LEFT JOIN public.recruits r USING(recruit_id)
       WHERE r.recruit_id IS NULL OR r.category IS DISTINCT FROM 'group_buy'
    ) THEN
        RAISE EXCEPTION 'Category / detail mismatch; resolve rows manually before migration';
    END IF;
END $$;

-- 원본 권한 백업. 테이블을 뷰로 대체하면 권한은 자동 상속되지 않음.
CREATE TEMP TABLE _meetup_previous_grants ON COMMIT DROP AS
SELECT c.relname AS relation_name, e.grantee, e.privilege_type, e.is_grantable
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
CROSS JOIN LATERAL aclexplode(COALESCE(c.relacl,acldefault('r',c.relowner))) e
WHERE n.nspname='public' AND c.relname IN (
 'recruit_sports_details','recruit_game_details','recruit_study_details','recruit_group_buy_details')
AND e.grantee <> c.relowner
AND e.privilege_type IN ('SELECT','INSERT','UPDATE','DELETE','TRIGGER');

CREATE TEMP TABLE _meetup_original_counts (relation_name text PRIMARY KEY, total bigint NOT NULL) ON COMMIT DROP;
INSERT INTO _meetup_original_counts VALUES
  ('recruit_sports_details',(SELECT COUNT(*) FROM public.recruit_sports_details)),
  ('recruit_game_details',(SELECT COUNT(*) FROM public.recruit_game_details)),
  ('recruit_study_details',(SELECT COUNT(*) FROM public.recruit_study_details)),
  ('recruit_group_buy_details',(SELECT COUNT(*) FROM public.recruit_group_buy_details));

-- 전체 행 스냅샷을 임시 테이블로 보존하여 뷰 변환 후 컬럼/값을 양방향 비교.
-- 실제 원본 삭제는 이 트랜잭션의 모든 검증을 마칠 때까지 커밋하지 않음.
CREATE TEMP TABLE _meetup_orig_sports ON COMMIT DROP AS SELECT * FROM public.recruit_sports_details;
CREATE TEMP TABLE _meetup_orig_game ON COMMIT DROP AS SELECT * FROM public.recruit_game_details;
CREATE TEMP TABLE _meetup_orig_study ON COMMIT DROP AS SELECT * FROM public.recruit_study_details;
CREATE TEMP TABLE _meetup_orig_group_buy ON COMMIT DROP AS SELECT * FROM public.recruit_group_buy_details;

ALTER TABLE public.recruits ADD COLUMN details JSONB NULL;
COMMENT ON COLUMN public.recruits.details IS '유형별 모임 상세(기존 4종 상세 테이블 통합); NULL이면 상세 행이 없음';
-- JSON literal null은 SQL NULL과 달라 호환 뷰에서 유령 상세 행으로 나타날 수 있음.
-- 상세 데이터는 SQL NULL(상세 행 없음) 또는 JSON 객체만 허용.
ALTER TABLE public.recruits ADD CONSTRAINT ck_recruits_details_object
 CHECK (details IS NULL OR jsonb_typeof(details) = 'object');

UPDATE public.recruits r SET details=jsonb_build_object('sport_name',d.sport_name)
FROM public.recruit_sports_details d WHERE r.recruit_id=d.recruit_id;
UPDATE public.recruits r SET details=jsonb_build_object('game_name',d.game_name)
FROM public.recruit_game_details d WHERE r.recruit_id=d.recruit_id;
UPDATE public.recruits r SET details=jsonb_build_object(
 'study_topic',d.study_topic,'study_period',d.study_period,'study_method',d.study_method)
FROM public.recruit_study_details d WHERE r.recruit_id=d.recruit_id;
UPDATE public.recruits r SET details=jsonb_build_object(
 'product_name',d.product_name,'purchase_url',d.purchase_url,
 'estimated_price_per_person',d.estimated_price_per_person,'pickup_method',d.pickup_method)
FROM public.recruit_group_buy_details d WHERE r.recruit_id=d.recruit_id;

-- 원본 상세 행별 값 비교. JSON null을 추출하면 SQL NULL이므로 NULL 값도 검증 가능.
DO $$
BEGIN
 IF EXISTS (
   SELECT 1 FROM public.recruit_sports_details d JOIN public.recruits r USING(recruit_id)
   WHERE (r.details->>'sport_name') IS DISTINCT FROM d.sport_name
 ) OR EXISTS (
   SELECT 1 FROM public.recruit_game_details d JOIN public.recruits r USING(recruit_id)
   WHERE (r.details->>'game_name') IS DISTINCT FROM d.game_name
 ) OR EXISTS (
   SELECT 1 FROM public.recruit_study_details d JOIN public.recruits r USING(recruit_id)
   WHERE (r.details->>'study_topic') IS DISTINCT FROM d.study_topic
      OR (r.details->>'study_period') IS DISTINCT FROM d.study_period
      OR (r.details->>'study_method') IS DISTINCT FROM d.study_method
 ) OR EXISTS (
   SELECT 1 FROM public.recruit_group_buy_details d JOIN public.recruits r USING(recruit_id)
   WHERE (r.details->>'product_name') IS DISTINCT FROM d.product_name
      OR (r.details->>'purchase_url') IS DISTINCT FROM d.purchase_url
      OR ((r.details->>'estimated_price_per_person')::numeric) IS DISTINCT FROM d.estimated_price_per_person
      OR (r.details->>'pickup_method') IS DISTINCT FROM d.pickup_method
 ) THEN
   RAISE EXCEPTION 'Data verification failed before replacing legacy tables';
 END IF;
END $$;

-- 다른 뷰/함수/FK가 이 테이블에 의존하면 DROP TABLE RESTRICT 오류로 전체 ROLLBACK.
DROP TABLE public.recruit_sports_details RESTRICT;
DROP TABLE public.recruit_game_details RESTRICT;
DROP TABLE public.recruit_study_details RESTRICT;
DROP TABLE public.recruit_group_buy_details RESTRICT;

-- 구 코드의 SELECT와 SQLAlchemy 모델 컬럼 계약 유지 (NULL 값도 원본 행으로 표시).
CREATE VIEW public.recruit_sports_details AS
 SELECT recruit_id, (details->>'sport_name')::varchar(100) AS sport_name
 FROM public.recruits WHERE category='sports' AND details IS NOT NULL;
CREATE VIEW public.recruit_game_details AS
 SELECT recruit_id, (details->>'game_name')::varchar(150) AS game_name
 FROM public.recruits WHERE category='game' AND details IS NOT NULL;
CREATE VIEW public.recruit_study_details AS
 SELECT recruit_id, (details->>'study_topic')::varchar(200) AS study_topic,
        (details->>'study_period')::varchar(100) AS study_period,
        (details->>'study_method')::varchar(100) AS study_method
 FROM public.recruits WHERE category='study' AND details IS NOT NULL;
CREATE VIEW public.recruit_group_buy_details AS
 SELECT recruit_id, (details->>'product_name')::varchar(200) AS product_name,
        (details->>'purchase_url')::varchar(500) AS purchase_url,
        (details->>'estimated_price_per_person')::numeric(10,2) AS estimated_price_per_person,
        (details->>'pickup_method')::varchar(150) AS pickup_method
 FROM public.recruits WHERE category='group_buy' AND details IS NOT NULL;

-- INSTEAD OF 트리거: SQLAlchemy INSERT/UPDATE/DELETE를 recruits JSONB에 반영.
-- 이 뷰는 일반적인 단순 가변 뷰가 아니므로 쓰기 트리거가 필수.
CREATE FUNCTION public._meetup_compat_detail_write() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE expected_category text; new_details jsonb;
BEGIN
 CASE TG_TABLE_NAME
   WHEN 'recruit_sports_details' THEN
     expected_category := 'sports';
     IF TG_OP <> 'DELETE' THEN new_details := jsonb_build_object('sport_name',NEW.sport_name); END IF;
   WHEN 'recruit_game_details' THEN
     expected_category := 'game';
     IF TG_OP <> 'DELETE' THEN new_details := jsonb_build_object('game_name',NEW.game_name); END IF;
   WHEN 'recruit_study_details' THEN
     expected_category := 'study';
     IF TG_OP <> 'DELETE' THEN new_details := jsonb_build_object(
       'study_topic',NEW.study_topic,'study_period',NEW.study_period,'study_method',NEW.study_method); END IF;
   WHEN 'recruit_group_buy_details' THEN
     expected_category := 'group_buy';
     IF TG_OP <> 'DELETE' THEN new_details := jsonb_build_object(
       'product_name',NEW.product_name,'purchase_url',NEW.purchase_url,
       'estimated_price_per_person',NEW.estimated_price_per_person,'pickup_method',NEW.pickup_method); END IF;
   ELSE RAISE EXCEPTION 'Unsupported detail view %',TG_TABLE_NAME;
 END CASE;
 IF TG_OP = 'UPDATE' AND NEW.recruit_id IS DISTINCT FROM OLD.recruit_id THEN
   RAISE EXCEPTION 'recruit_id is immutable';
 END IF;
 IF TG_OP = 'DELETE' THEN
   UPDATE public.recruits SET details=NULL
   WHERE recruit_id=OLD.recruit_id AND category=expected_category AND details IS NOT NULL;
   IF NOT FOUND THEN RAISE EXCEPTION 'Detail to delete does not exist in %',TG_TABLE_NAME; END IF;
   RETURN OLD;
 END IF;
 IF jsonb_typeof(new_details) <> 'object' THEN
   RAISE EXCEPTION 'Invalid details payload';
 END IF;
 -- 과거 PK/행 존재 의미 유지: 중복 INSERT는 실패, 없는 행 UPDATE도 실패.
 IF TG_OP = 'INSERT' THEN
   UPDATE public.recruits SET details=new_details
   WHERE recruit_id=NEW.recruit_id AND category=expected_category AND details IS NULL;
   IF NOT FOUND THEN
     IF EXISTS (SELECT 1 FROM public.recruits
                WHERE recruit_id=NEW.recruit_id AND category=expected_category) THEN
       RAISE EXCEPTION 'Duplicate detail for recruit % in %',NEW.recruit_id,TG_TABLE_NAME
          USING ERRCODE='23505';
     END IF;
     RAISE EXCEPTION 'Recruit % missing or category mismatch for %',NEW.recruit_id,TG_TABLE_NAME
        USING ERRCODE='23503';
   END IF;
 ELSE
   UPDATE public.recruits SET details=new_details
   WHERE recruit_id=NEW.recruit_id AND category=expected_category AND details IS NOT NULL;
   IF NOT FOUND THEN RAISE EXCEPTION 'Detail to update does not exist in %',TG_TABLE_NAME; END IF;
 END IF;
 RETURN NEW;
END; $$;

CREATE TRIGGER meetup_detail_write_instead INSTEAD OF INSERT OR UPDATE OR DELETE
ON public.recruit_sports_details FOR EACH ROW EXECUTE FUNCTION public._meetup_compat_detail_write();
CREATE TRIGGER meetup_detail_write_instead INSTEAD OF INSERT OR UPDATE OR DELETE
ON public.recruit_game_details FOR EACH ROW EXECUTE FUNCTION public._meetup_compat_detail_write();
CREATE TRIGGER meetup_detail_write_instead INSTEAD OF INSERT OR UPDATE OR DELETE
ON public.recruit_study_details FOR EACH ROW EXECUTE FUNCTION public._meetup_compat_detail_write();
CREATE TRIGGER meetup_detail_write_instead INSTEAD OF INSERT OR UPDATE OR DELETE
ON public.recruit_group_buy_details FOR EACH ROW EXECUTE FUNCTION public._meetup_compat_detail_write();

-- 동적 뷰 캐스팅으로 인한 문자 잘림/숫자 변환까지 양방향 값 비교로 차단.
DO $$
BEGIN
 IF EXISTS (SELECT * FROM _meetup_orig_sports EXCEPT ALL SELECT * FROM public.recruit_sports_details)
 OR EXISTS (SELECT * FROM public.recruit_sports_details EXCEPT ALL SELECT * FROM _meetup_orig_sports)
 OR EXISTS (SELECT * FROM _meetup_orig_game EXCEPT ALL SELECT * FROM public.recruit_game_details)
 OR EXISTS (SELECT * FROM public.recruit_game_details EXCEPT ALL SELECT * FROM _meetup_orig_game)
 OR EXISTS (SELECT * FROM _meetup_orig_study EXCEPT ALL SELECT * FROM public.recruit_study_details)
 OR EXISTS (SELECT * FROM public.recruit_study_details EXCEPT ALL SELECT * FROM _meetup_orig_study)
 OR EXISTS (SELECT * FROM _meetup_orig_group_buy EXCEPT ALL SELECT * FROM public.recruit_group_buy_details)
 OR EXISTS (SELECT * FROM public.recruit_group_buy_details EXCEPT ALL SELECT * FROM _meetup_orig_group_buy)
 THEN RAISE EXCEPTION 'View rows/columns/values not identical to original physical tables'; END IF;
END $$;

-- 데이터 건수도 원본 물리 테이블과 같아야 커밋 허용.
DO $$ DECLARE actual bigint; expected bigint; v text;
BEGIN
 FOR v IN SELECT relation_name FROM _meetup_original_counts LOOP
   EXECUTE format('SELECT count(*) FROM public.%I',v) INTO actual;
   SELECT total INTO expected FROM _meetup_original_counts WHERE relation_name=v;
   IF actual <> expected THEN
     RAISE EXCEPTION 'View count mismatch for %: % vs %',v,actual,expected;
   END IF;
 END LOOP;
END $$;

-- 소유자가 부여한 명시 권한까지 복구 (서비스 계정 접근 불가 예방).
DO $$ DECLARE x record; grantee_sql text;
BEGIN
 FOR x IN SELECT * FROM _meetup_previous_grants LOOP
   grantee_sql := CASE WHEN x.grantee=0 THEN 'PUBLIC' ELSE format('%I',pg_get_userbyid(x.grantee)) END;
   EXECUTE format('GRANT %s ON TABLE public.%I TO %s %s',
       x.privilege_type,x.relation_name,grantee_sql,
       CASE WHEN x.is_grantable THEN 'WITH GRANT OPTION' ELSE '' END);
 END LOOP;
END $$;


-- Preserve the original VARCHAR limits and NUMERIC(10,2) assignment semantics
-- on the direct JSONB write path. NULL values remain permitted as before.
CREATE FUNCTION public._meetup_validate_detail_values() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE field_spec record; raw_value jsonb; rounded_price numeric(10,2);
BEGIN
 IF NEW.details IS NULL THEN RETURN NEW; END IF;
 IF jsonb_typeof(NEW.details) <> 'object' THEN
  RAISE EXCEPTION 'details must be a JSON object' USING ERRCODE='23514';
 END IF;
 FOR field_spec IN SELECT * FROM (VALUES
   ('sport_name',100),('game_name',150),('study_topic',200),
   ('study_period',100),('study_method',100),('product_name',200),
   ('purchase_url',500),('pickup_method',150)
 ) AS f(key_name,max_chars) LOOP
  raw_value := NEW.details -> field_spec.key_name;
  IF raw_value IS NOT NULL AND raw_value <> 'null'::jsonb THEN
   IF jsonb_typeof(raw_value) <> 'string' THEN
    RAISE EXCEPTION 'Invalid detail type: %',field_spec.key_name USING ERRCODE='23514';
   END IF;
   IF char_length(NEW.details ->> field_spec.key_name) > field_spec.max_chars THEN
    RAISE EXCEPTION 'Detail value too long: %',field_spec.key_name USING ERRCODE='22001';
   END IF;
  END IF;
 END LOOP;
 raw_value := NEW.details -> 'estimated_price_per_person';
 IF raw_value IS NOT NULL AND raw_value <> 'null'::jsonb THEN
  IF jsonb_typeof(raw_value) <> 'number' THEN
   RAISE EXCEPTION 'Price must be numeric' USING ERRCODE='23514';
  END IF;
  rounded_price := (NEW.details ->> 'estimated_price_per_person')::numeric(10,2);
  NEW.details := jsonb_set(NEW.details, '{estimated_price_per_person}', to_jsonb(rounded_price));
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER meetup_validate_detail_values
BEFORE INSERT OR UPDATE OF details ON public.recruits
FOR EACH ROW EXECUTE FUNCTION public._meetup_validate_detail_values();

COMMIT;
