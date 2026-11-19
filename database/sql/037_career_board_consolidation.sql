-- 037: career boards only. News, jobs and their collectors are excluded.
-- One transaction; no DROP CASCADE. Existing IDs and compatibility interfaces remain.
-- Run once, after 036. Rehearse and take a verified backup before applying.
BEGIN;
SET LOCAL lock_timeout = '10s';
SET LOCAL statement_timeout = '120s';
SET LOCAL search_path = public, pg_catalog;
LOCK TABLE posts, career_posts, career_reviews, career_talks, career_lounges,
 career_labs, career_lab_poll_options, career_lab_poll_votes,
 career_talk_attachments, post_images IN ACCESS EXCLUSIVE MODE;

-- Refuse ambiguous legacy subtype rows rather than silently dropping information.
DO $$ BEGIN
 IF EXISTS (
  SELECT 1 FROM career_posts cp JOIN posts p USING(post_id)
  LEFT JOIN career_reviews r USING(post_id) LEFT JOIN career_talks t USING(post_id)
  LEFT JOIN career_lounges l USING(post_id) LEFT JOIN career_labs b USING(post_id)
  WHERE p.post_type IS DISTINCT FROM 'CAREER'
    OR (CASE WHEN r.post_id IS NOT NULL THEN 1 ELSE 0 END
       +CASE WHEN t.post_id IS NOT NULL THEN 1 ELSE 0 END
       +CASE WHEN l.post_id IS NOT NULL THEN 1 ELSE 0 END
       +CASE WHEN b.post_id IS NOT NULL THEN 1 ELSE 0 END) <> 1
    OR (cp.category_code='reviews' AND r.post_id IS NULL)
    OR (cp.category_code='talk' AND t.post_id IS NULL)
    OR (cp.category_code='lounge' AND l.post_id IS NULL)
    OR (cp.category_code='lab' AND b.post_id IS NULL)
 ) THEN RAISE EXCEPTION 'Career subtype mismatch: resolve before migration'; END IF;
END $$;

-- Used for exact before/after checks, not persistent duplicate tables.
CREATE TEMP TABLE career_037_expected (relation_name text, data jsonb) ON COMMIT DROP;

INSERT INTO career_037_expected SELECT 'career_posts', to_jsonb(t) FROM career_posts t;
INSERT INTO career_037_expected SELECT 'career_reviews', to_jsonb(t) FROM career_reviews t;
INSERT INTO career_037_expected SELECT 'career_talks', to_jsonb(t) FROM career_talks t;
INSERT INTO career_037_expected SELECT 'career_lounges', to_jsonb(t) FROM career_lounges t;
INSERT INTO career_037_expected SELECT 'career_labs', to_jsonb(t) FROM career_labs t;
INSERT INTO career_037_expected SELECT 'career_lab_poll_options', to_jsonb(t) FROM career_lab_poll_options t;
INSERT INTO career_037_expected SELECT 'career_talk_attachments', to_jsonb(t) FROM career_talk_attachments t;
INSERT INTO career_037_expected SELECT 'post_images', to_jsonb(t) FROM post_images t;

CREATE TEMP TABLE career_037_grants ON COMMIT DROP AS
 SELECT table_name, grantee, privilege_type, is_grantable
 FROM information_schema.table_privileges WHERE table_schema='public'
 AND table_name IN ('career_posts','career_reviews','career_talks','career_lounges',
 'career_labs','career_lab_poll_options','career_talk_attachments','post_images');

ALTER TABLE posts
 ADD COLUMN career_category varchar(20),
 ADD COLUMN career_subcategory varchar(50),
 ADD COLUMN career_details jsonb NOT NULL DEFAULT '{}'::jsonb,
 ADD COLUMN poll_options jsonb NOT NULL DEFAULT '[]'::jsonb;
UPDATE posts p SET career_category=cp.category_code,
 career_subcategory=cp.subcategory_code, is_anonymous=cp.is_anonymous
FROM career_posts cp WHERE p.post_id=cp.post_id;

UPDATE posts p SET career_details=to_jsonb(d)-'post_id' FROM career_reviews d WHERE p.post_id=d.post_id;
UPDATE posts p SET career_details=to_jsonb(d)-'post_id' FROM career_talks d WHERE p.post_id=d.post_id;
UPDATE posts p SET career_details=to_jsonb(d)-'post_id' FROM career_lounges d WHERE p.post_id=d.post_id;
UPDATE posts p SET career_details=to_jsonb(d)-'post_id' FROM career_labs d WHERE p.post_id=d.post_id;

UPDATE posts p SET poll_options=q.options FROM (
 SELECT post_id, jsonb_agg(jsonb_build_object('option_id',option_id,
 'option_text',option_text,'display_order',display_order) ORDER BY display_order) options
 FROM career_lab_poll_options GROUP BY post_id
) q WHERE p.post_id=q.post_id;

CREATE FUNCTION playmate_career_details_valid(category text, d jsonb)
RETURNS boolean LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE k text; max_length integer;
BEGIN
 IF jsonb_typeof(d) IS DISTINCT FROM 'object' THEN RETURN false; END IF;
 -- A legacy client creates posts, classification, then subtype in one transaction.
 IF d='{}'::jsonb THEN RETURN true; END IF;
 FOR k,max_length IN SELECT * FROM (VALUES
 ('company_name',150),('job_category_code',50),('application_type',20),
 ('process_stage',30),('process_result',20),('interview_format',50),
 ('current_status',20),('post_type',20)) limits(key,maxlen) LOOP
  IF d->>k IS NOT NULL AND (jsonb_typeof(d->k)<>'string' OR length(d->>k)>max_length)
  THEN RETURN false; END IF;
 END LOOP;
 IF d->>'process_date' IS NOT NULL THEN PERFORM (d->>'process_date')::date; END IF;
 IF category='reviews' THEN
  RETURN COALESCE(length(btrim(d->>'job_category_code'))>0
   AND jsonb_typeof(d->'is_company_private')='boolean'
   AND (d->>'process_stage') IN ('DOCUMENT','CODING_TEST','ASSIGNMENT','INTERVIEW','FINAL')
   AND (d->>'process_result') IN ('PASS','FAIL','PENDING')
   AND ((d->>'application_type') IS NULL OR (d->>'application_type') IN ('NEW','EXPERIENCED')),false);
 ELSIF category='talk' THEN
  RETURN ((d->>'job_category_code') IS NULL OR length(btrim(d->>'job_category_code'))>0)
   AND ((d->>'current_status') IS NULL OR (d->>'current_status') IN ('PREPARING','NEW','EXPERIENCED','JOB_CHANGE','OTHER'));
 ELSIF category='lounge' THEN
  RETURN ((d->>'job_category_code') IS NULL OR length(btrim(d->>'job_category_code'))>0)
   AND ((d->>'company_name') IS NULL OR length(btrim(d->>'company_name'))>0)
   AND ((d->>'experience_years') IS NULL OR (d->>'experience_years')::smallint>=0);
 ELSIF category='lab' THEN
  RETURN COALESCE((d->>'post_type') IN ('QUESTION','DISCUSSION','GUIDE')
   AND jsonb_typeof(d->'is_resolved')='boolean'
   AND ((d->>'post_type')='QUESTION' OR (d->>'is_resolved')::boolean=false)
   AND (((d->>'post_type')='GUIDE'
         AND length(btrim(d->>'guide_experience'))>=100
         AND length(btrim(d->>'guide_advice'))>=100)
     OR ((d->>'post_type')<>'GUIDE' AND (d->>'guide_experience') IS NULL
         AND (d->>'guide_advice') IS NULL)),false);
 END IF;
 RETURN false;
EXCEPTION WHEN invalid_text_representation OR numeric_value_out_of_range OR invalid_datetime_format OR datetime_field_overflow THEN RETURN false;
END $$;

CREATE FUNCTION playmate_poll_options_valid(options jsonb)
RETURNS boolean LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE n integer; ids integer; orders integer; valid boolean;
BEGIN
 IF jsonb_typeof(options) IS DISTINCT FROM 'array' THEN RETURN false; END IF;
 SELECT count(*), count(DISTINCT (x->>'option_id')::bigint),
  count(DISTINCT (x->>'display_order')::smallint),
  COALESCE(bool_and(COALESCE(jsonb_typeof(x)='object'
   AND jsonb_typeof(x->'option_id')='number'
   AND jsonb_typeof(x->'display_order')='number'
   AND jsonb_typeof(x->'option_text')='string'
   AND (x->>'option_id')::bigint>0
   AND (x->>'display_order')::smallint BETWEEN 1 AND 10
   AND length(btrim(x->>'option_text')) BETWEEN 1 AND 200,false)),true)
 INTO n,ids,orders,valid FROM jsonb_array_elements(options) x;
 RETURN n<=10 AND ids=n AND orders=n AND valid;
EXCEPTION WHEN invalid_text_representation OR numeric_value_out_of_range THEN RETURN false;
END $$;

ALTER TABLE posts ADD CONSTRAINT ck_posts_career_classification CHECK (
 (career_category IS NULL AND career_subcategory IS NULL AND career_details='{}'::jsonb AND poll_options='[]'::jsonb)
 OR (career_category IS NOT NULL AND career_category IN ('reviews','talk','lounge','lab')
 AND post_type IS NOT DISTINCT FROM 'CAREER' AND career_subcategory IS NOT NULL
 AND length(btrim(career_subcategory))>0));
ALTER TABLE posts ADD CONSTRAINT ck_posts_career_details
 CHECK (playmate_career_details_valid(career_category,career_details));
ALTER TABLE posts ADD CONSTRAINT ck_posts_poll_options CHECK (
 playmate_poll_options_valid(poll_options)
 AND (poll_options='[]'::jsonb OR
   (career_category IS NOT DISTINCT FROM 'lab' AND career_details->>'post_type' IS NOT DISTINCT FROM 'DISCUSSION')));
CREATE INDEX idx_posts_career_listing ON posts(career_category,career_subcategory,post_id DESC)
 WHERE career_category IS NOT NULL;
CREATE INDEX idx_posts_career_job ON posts(career_category,(career_details->>'job_category_code'))
 WHERE career_category IS NOT NULL;

-- Replace the option FK with a parent FK and a serialized JSON membership check.
ALTER TABLE career_lab_poll_votes DROP CONSTRAINT fk_career_lab_vote_option;
ALTER TABLE career_lab_poll_votes ADD CONSTRAINT fk_career_votes_post
 FOREIGN KEY(post_id) REFERENCES posts(post_id) ON DELETE CASCADE;
CREATE FUNCTION playmate_career_vote_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE p posts%ROWTYPE;
BEGIN
 SELECT * INTO p FROM posts WHERE post_id=NEW.post_id FOR UPDATE;
 IF NOT FOUND OR p.deleted_at IS NOT NULL OR p.career_category IS DISTINCT FROM 'lab'
  OR p.career_details->>'post_type' IS DISTINCT FROM 'DISCUSSION'
  OR NOT EXISTS (SELECT 1 FROM jsonb_array_elements(p.poll_options) x
                 WHERE (x->>'option_id')::bigint=NEW.option_id)
 THEN RAISE EXCEPTION 'Invalid career poll option' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER trg_career_vote_guard BEFORE INSERT OR UPDATE ON career_lab_poll_votes
 FOR EACH ROW EXECUTE FUNCTION playmate_career_vote_guard();
CREATE FUNCTION playmate_poll_options_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF (NEW.poll_options IS DISTINCT FROM OLD.poll_options
     OR NEW.career_category IS DISTINCT FROM OLD.career_category
     OR NEW.career_details->>'post_type' IS DISTINCT FROM OLD.career_details->>'post_type')
 AND EXISTS(SELECT 1 FROM career_lab_poll_votes WHERE post_id=OLD.post_id)
 THEN RAISE EXCEPTION 'Cannot change a poll after voting' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER trg_posts_poll_options_guard BEFORE UPDATE ON posts
 FOR EACH ROW EXECUTE FUNCTION playmate_poll_options_guard();

-- IDs remain unchanged within each existing endpoint namespace.
CREATE SEQUENCE post_attachment_id_seq;
CREATE TABLE post_attachments (
 attachment_scope varchar(20) NOT NULL CHECK(attachment_scope IN ('BOARD','CAREER_TALK')),
 attachment_id bigint NOT NULL DEFAULT nextval('post_attachment_id_seq'),
 post_id bigint NOT NULL REFERENCES posts(post_id),
 original_filename varchar(255) NOT NULL,
 stored_path varchar(500) NOT NULL,
 attachment_type varchar(10) NOT NULL CHECK(attachment_type IN ('IMAGE','FILE')),
 content_type varchar(100) NOT NULL,
 file_size_bytes bigint NOT NULL,
 display_order smallint NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 -- Keep the original board timestamp, whose timezone was not specified.
 board_created_at timestamp,
 PRIMARY KEY(attachment_scope,attachment_id),
 CHECK ((attachment_scope='BOARD' AND attachment_type='IMAGE'
   AND file_size_bytes BETWEEN 1 AND 5242880 AND display_order BETWEEN 0 AND 2
   AND length(content_type)<=50 AND length(stored_path)<=255 AND board_created_at IS NOT NULL)
  OR (attachment_scope='CAREER_TALK' AND file_size_bytes BETWEEN 1 AND 10485760
   AND display_order BETWEEN 1 AND 5 AND board_created_at IS NULL))
);
ALTER SEQUENCE post_attachment_id_seq OWNED BY post_attachments.attachment_id;
CREATE UNIQUE INDEX uq_post_attachments_talk_path ON post_attachments(stored_path)
 WHERE attachment_scope='CAREER_TALK';
CREATE UNIQUE INDEX uq_post_attachments_talk_order ON post_attachments(post_id,display_order)
 WHERE attachment_scope='CAREER_TALK';
CREATE INDEX idx_post_attachments_post ON post_attachments(post_id,attachment_scope,display_order);
INSERT INTO post_attachments(attachment_scope,attachment_id,post_id,original_filename,stored_path,
 attachment_type,content_type,file_size_bytes,display_order,created_at)
 SELECT 'CAREER_TALK',attachment_id,post_id,original_filename,stored_path,
 attachment_type,content_type,file_size_bytes,display_order,created_at FROM career_talk_attachments;
INSERT INTO post_attachments(attachment_scope,attachment_id,post_id,original_filename,stored_path,
 attachment_type,content_type,file_size_bytes,display_order,created_at,board_created_at)
 SELECT 'BOARD',image_id,post_id,original_name,stored_name,'IMAGE',content_type,
 file_size,display_order,created_at AT TIME ZONE 'Asia/Seoul',created_at FROM post_images;
SELECT setval('post_attachment_id_seq',COALESCE((SELECT max(attachment_id) FROM post_attachments),0)+1,false);
-- Preserve the former ON DELETE CASCADE for talk attachments; board images
-- keep their original restrictive parent relationship.
CREATE FUNCTION playmate_delete_career_attachments() RETURNS trigger LANGUAGE plpgsql
 SECURITY DEFINER SET search_path=public,pg_catalog AS $$
BEGIN
 DELETE FROM post_attachments WHERE post_id=OLD.post_id AND attachment_scope='CAREER_TALK';
 RETURN OLD;
END $$;
CREATE TRIGGER trg_posts_delete_career_attachments BEFORE DELETE ON posts
 FOR EACH ROW EXECUTE FUNCTION playmate_delete_career_attachments();
CREATE SEQUENCE career_poll_option_id_seq;
SELECT setval('career_poll_option_id_seq',COALESCE((SELECT max(option_id) FROM career_lab_poll_options),0)+1,false);

DROP TABLE career_talk_attachments;
DROP TABLE career_lab_poll_options;
DROP TABLE career_reviews;
DROP TABLE career_talks;
DROP TABLE career_lounges;
DROP TABLE career_labs;
DROP TABLE career_posts;
DROP TABLE post_images;

CREATE VIEW career_posts AS SELECT post_id, career_category AS category_code,
 career_subcategory AS subcategory_code, is_anonymous FROM posts WHERE career_category IS NOT NULL;

CREATE VIEW career_reviews AS SELECT post_id, (career_details->>'company_name')::varchar(150) AS company_name, (career_details->>'is_company_private')::boolean AS is_company_private, (career_details->>'job_category_code')::varchar(50) AS job_category_code, (career_details->>'application_type')::varchar(20) AS application_type, (career_details->>'process_stage')::varchar(30) AS process_stage, (career_details->>'process_result')::varchar(20) AS process_result, (career_details->>'process_date')::date AS process_date, (career_details->>'interview_format')::varchar(50) AS interview_format FROM posts WHERE career_category='reviews' AND career_details<>'{}'::jsonb;
CREATE VIEW career_talks AS SELECT post_id, (career_details->>'job_category_code')::varchar(50) AS job_category_code, (career_details->>'current_status')::varchar(20) AS current_status FROM posts WHERE career_category='talk' AND career_details<>'{}'::jsonb;
CREATE VIEW career_lounges AS SELECT post_id, (career_details->>'job_category_code')::varchar(50) AS job_category_code, (career_details->>'experience_years')::smallint AS experience_years, (career_details->>'company_name')::varchar(150) AS company_name FROM posts WHERE career_category='lounge' AND career_details<>'{}'::jsonb;
CREATE VIEW career_labs AS SELECT post_id, (career_details->>'post_type')::varchar(20) AS post_type, (career_details->>'is_resolved')::boolean AS is_resolved, (career_details->>'guide_experience')::text AS guide_experience, (career_details->>'guide_advice')::text AS guide_advice FROM posts WHERE career_category='lab' AND career_details<>'{}'::jsonb;

CREATE VIEW career_lab_poll_options AS SELECT x.option_id,p.post_id,x.option_text,x.display_order
 FROM posts p CROSS JOIN LATERAL jsonb_to_recordset(p.poll_options)
 AS x(option_id bigint,option_text varchar(200),display_order smallint);
CREATE VIEW career_talk_attachments AS SELECT attachment_id,post_id,original_filename,stored_path,
 attachment_type,content_type,file_size_bytes,display_order,created_at
 FROM post_attachments WHERE attachment_scope='CAREER_TALK';
CREATE VIEW post_images AS SELECT attachment_id AS image_id,post_id,stored_path::varchar(255) AS stored_name,
 original_filename AS original_name,content_type::varchar(50) AS content_type,
 file_size_bytes::integer AS file_size,display_order,board_created_at AS created_at
 FROM post_attachments WHERE attachment_scope='BOARD';

ALTER VIEW career_posts ALTER COLUMN is_anonymous SET DEFAULT true;
ALTER VIEW career_reviews ALTER COLUMN is_company_private SET DEFAULT false;
ALTER VIEW career_labs ALTER COLUMN is_resolved SET DEFAULT false;

CREATE FUNCTION playmate_career_complete_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF EXISTS(SELECT 1 FROM posts WHERE post_id=NEW.post_id AND career_category IS NOT NULL
           AND career_details='{}'::jsonb) THEN
  RAISE EXCEPTION 'Career subtype details required before commit' USING ERRCODE='23514';
 END IF;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER trg_career_complete AFTER INSERT OR UPDATE ON posts
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION playmate_career_complete_guard();

CREATE FUNCTION playmate_career_compat_write() RETURNS trigger LANGUAGE plpgsql
 SECURITY DEFINER SET search_path=public,pg_catalog AS $$
DECLARE category text; details jsonb; p posts%ROWTYPE;
BEGIN
 IF TG_OP='DELETE' THEN
  RAISE EXCEPTION 'Use posts soft deletion, not compatibility view deletion';
 END IF;
 IF TG_OP='UPDATE' AND NEW.post_id IS DISTINCT FROM OLD.post_id THEN
  RAISE EXCEPTION 'Cannot move career details to another post'; END IF;
 SELECT * INTO p FROM posts WHERE post_id=NEW.post_id FOR UPDATE;
 IF NOT FOUND OR p.post_type IS DISTINCT FROM 'CAREER' THEN
  RAISE EXCEPTION 'Career parent post required' USING ERRCODE='23503'; END IF;
 IF TG_TABLE_NAME='career_posts' THEN
  IF TG_OP='INSERT' AND p.career_category IS NOT NULL THEN
   RAISE EXCEPTION 'Career classification already exists' USING ERRCODE='23505'; END IF;
  IF NEW.is_anonymous IS NULL THEN RAISE EXCEPTION 'Anonymous flag required' USING ERRCODE='23502'; END IF;
  IF p.career_category IS NOT NULL AND NEW.category_code IS DISTINCT FROM p.career_category THEN RAISE EXCEPTION 'Career category is immutable'; END IF;
  UPDATE posts SET career_category=NEW.category_code,
    career_subcategory=NEW.subcategory_code,is_anonymous=NEW.is_anonymous WHERE post_id=NEW.post_id;
 ELSE
  category:=CASE TG_TABLE_NAME WHEN 'career_reviews' THEN 'reviews' WHEN 'career_talks' THEN 'talk'
    WHEN 'career_lounges' THEN 'lounge' WHEN 'career_labs' THEN 'lab' END;
  IF p.career_category IS DISTINCT FROM category THEN
   RAISE EXCEPTION 'Career subtype does not match category' USING ERRCODE='23514'; END IF;
  IF TG_OP='INSERT' AND p.career_details<>'{}'::jsonb THEN
   RAISE EXCEPTION 'Career details already exist' USING ERRCODE='23505'; END IF;
  details:=to_jsonb(NEW)-'post_id';

  UPDATE posts SET career_details=details WHERE post_id=NEW.post_id;
 END IF;
 RETURN NEW;
END $$;

CREATE TRIGGER trg_career_posts_compat INSTEAD OF INSERT OR UPDATE OR DELETE ON career_posts FOR EACH ROW EXECUTE FUNCTION playmate_career_compat_write();
CREATE TRIGGER trg_career_reviews_compat INSTEAD OF INSERT OR UPDATE OR DELETE ON career_reviews FOR EACH ROW EXECUTE FUNCTION playmate_career_compat_write();
CREATE TRIGGER trg_career_talks_compat INSTEAD OF INSERT OR UPDATE OR DELETE ON career_talks FOR EACH ROW EXECUTE FUNCTION playmate_career_compat_write();
CREATE TRIGGER trg_career_lounges_compat INSTEAD OF INSERT OR UPDATE OR DELETE ON career_lounges FOR EACH ROW EXECUTE FUNCTION playmate_career_compat_write();
CREATE TRIGGER trg_career_labs_compat INSTEAD OF INSERT OR UPDATE OR DELETE ON career_labs FOR EACH ROW EXECUTE FUNCTION playmate_career_compat_write();

CREATE FUNCTION playmate_poll_compat_write() RETURNS trigger LANGUAGE plpgsql
 SECURITY DEFINER SET search_path=public,pg_catalog AS $$
DECLARE p posts%ROWTYPE;
BEGIN
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Poll options are immutable through legacy interface'; END IF;
 SELECT * INTO p FROM posts WHERE post_id=NEW.post_id FOR UPDATE;
 IF NOT FOUND OR p.career_category IS DISTINCT FROM 'lab'
 OR p.career_details->>'post_type' IS DISTINCT FROM 'DISCUSSION' THEN
  RAISE EXCEPTION 'Discussion parent required' USING ERRCODE='23514'; END IF;
 NEW.option_id:=COALESCE(NEW.option_id,nextval('career_poll_option_id_seq'));
 UPDATE posts SET poll_options=poll_options||jsonb_build_array(jsonb_build_object(
 'option_id',NEW.option_id,'option_text',NEW.option_text,'display_order',NEW.display_order))
 WHERE post_id=NEW.post_id;
 RETURN NEW;
END $$;
CREATE TRIGGER trg_poll_options_compat INSTEAD OF INSERT OR UPDATE OR DELETE ON career_lab_poll_options
 FOR EACH ROW EXECUTE FUNCTION playmate_poll_compat_write();

CREATE FUNCTION playmate_attachment_compat_write() RETURNS trigger LANGUAGE plpgsql
 SECURITY DEFINER SET search_path=public,pg_catalog AS $$
DECLARE scope text; id bigint; p posts%ROWTYPE;
BEGIN
 scope:=CASE TG_TABLE_NAME WHEN 'post_images' THEN 'BOARD' ELSE 'CAREER_TALK' END;
 IF TG_OP='DELETE' THEN
  id:=CASE WHEN scope='BOARD' THEN (to_jsonb(OLD)->>'image_id')::bigint ELSE (to_jsonb(OLD)->>'attachment_id')::bigint END;
  DELETE FROM post_attachments WHERE attachment_scope=scope AND attachment_id=id;
  RETURN OLD;
 END IF;
 SELECT * INTO p FROM posts WHERE post_id=NEW.post_id FOR UPDATE;
 IF NOT FOUND OR (scope='CAREER_TALK' AND p.career_category IS DISTINCT FROM 'talk') THEN
  RAISE EXCEPTION 'Attachment parent mismatch' USING ERRCODE='23503'; END IF;
 IF scope='BOARD' THEN
  IF TG_OP='INSERT' THEN
   NEW.image_id:=COALESCE(NEW.image_id,nextval('post_attachment_id_seq'));
   NEW.created_at:=COALESCE(NEW.created_at,CURRENT_TIMESTAMP::timestamp);
   NEW.display_order:=COALESCE(NEW.display_order,0);
   INSERT INTO post_attachments(attachment_scope,attachment_id,post_id,original_filename,stored_path,
    attachment_type,content_type,file_size_bytes,display_order,created_at,board_created_at)
   VALUES(scope,NEW.image_id,NEW.post_id,NEW.original_name,NEW.stored_name,'IMAGE',NEW.content_type,
    NEW.file_size,NEW.display_order,NEW.created_at AT TIME ZONE 'Asia/Seoul',NEW.created_at);
  ELSE
   UPDATE post_attachments SET post_id=NEW.post_id,original_filename=NEW.original_name,
    stored_path=NEW.stored_name,content_type=NEW.content_type,file_size_bytes=NEW.file_size,
    display_order=NEW.display_order,board_created_at=NEW.created_at,
    created_at=NEW.created_at AT TIME ZONE 'Asia/Seoul'
   WHERE attachment_scope=scope AND attachment_id=OLD.image_id;
  END IF;
 ELSE
  IF TG_OP='INSERT' THEN
   NEW.attachment_id:=COALESCE(NEW.attachment_id,nextval('post_attachment_id_seq'));
   NEW.created_at:=COALESCE(NEW.created_at,now());
   INSERT INTO post_attachments(attachment_scope,attachment_id,post_id,original_filename,stored_path,
    attachment_type,content_type,file_size_bytes,display_order,created_at)
   VALUES(scope,NEW.attachment_id,NEW.post_id,NEW.original_filename,NEW.stored_path,
    NEW.attachment_type,NEW.content_type,NEW.file_size_bytes,NEW.display_order,NEW.created_at);
  ELSE
   UPDATE post_attachments SET post_id=NEW.post_id,original_filename=NEW.original_filename,
    stored_path=NEW.stored_path,attachment_type=NEW.attachment_type,content_type=NEW.content_type,
    file_size_bytes=NEW.file_size_bytes,display_order=NEW.display_order,created_at=NEW.created_at
   WHERE attachment_scope=scope AND attachment_id=OLD.attachment_id;
  END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER trg_post_images_compat INSTEAD OF INSERT OR UPDATE OR DELETE ON post_images
 FOR EACH ROW EXECUTE FUNCTION playmate_attachment_compat_write();
CREATE TRIGGER trg_talk_attachments_compat INSTEAD OF INSERT OR UPDATE OR DELETE ON career_talk_attachments
 FOR EACH ROW EXECUTE FUNCTION playmate_attachment_compat_write();

-- Fail atomically if any projected row differs, including old IDs/timestamps/nulls.
DO $$ DECLARE n text; mismatch boolean; BEGIN
 FOR n IN SELECT DISTINCT relation_name FROM career_037_expected LOOP
  EXECUTE format('SELECT EXISTS ((SELECT data FROM career_037_expected WHERE relation_name=%L EXCEPT ALL SELECT to_jsonb(t) FROM %I t) UNION ALL (SELECT to_jsonb(t) FROM %I t EXCEPT ALL SELECT data FROM career_037_expected WHERE relation_name=%L))',n,n,n,n) INTO mismatch;
  IF mismatch THEN RAISE EXCEPTION 'Migration data mismatch: %',n; END IF;
 END LOOP;
END $$;

-- Restore interface grants. Narrow compatibility trigger functions run as owner
-- with fixed search_path; callers still require privileges on the original view.
-- Canonical writers require posts INSERT/UPDATE and poll sequence USAGE.
DO $$ DECLARE g record; BEGIN
 FOR g IN SELECT * FROM career_037_grants LOOP
  EXECUTE format('GRANT %s ON %I TO %s%s',g.privilege_type,g.table_name,
   CASE WHEN g.grantee='PUBLIC' THEN 'PUBLIC' ELSE quote_ident(g.grantee) END,
   CASE WHEN g.is_grantable='YES' THEN ' WITH GRANT OPTION' ELSE '' END);
 END LOOP;
END $$;
-- Existing post writers may allocate option IDs via the canonical writer.
DO $$ DECLARE g record; BEGIN
 FOR g IN SELECT DISTINCT grantee FROM information_schema.table_privileges
  WHERE table_schema='public' AND table_name='posts' AND privilege_type='INSERT' LOOP
  EXECUTE format('GRANT USAGE ON SEQUENCE career_poll_option_id_seq TO %s',
   CASE WHEN g.grantee='PUBLIC' THEN 'PUBLIC' ELSE quote_ident(g.grantee) END);
 END LOOP;
END $$;
COMMIT;
