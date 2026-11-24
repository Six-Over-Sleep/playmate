-- PREPARED ONLY: do not run as part of tests or automatic schema bootstrap.
-- Deploy the refactored application first; stop all older workers/bots/clients.
-- Run python -m backend.scripts.check_compat_view_references against the deployed
-- source and audit external consumers (SQL cannot inspect application source).
-- Only after both audits pass, the deployment operator may set in this session:
--   SET playmate.compat_views_application_audit = 'verified';
-- No data or physical tables are removed. Existing migrations remain unchanged.
-- Known INSTEAD OF triggers belong to each view and disappear with that view.
-- Their functions are inspected and retained; physical-table guards are retained.
-- Any unknown dependency stops the entire transaction. No cascade is used.

BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';

DO $preflight$
DECLARE
    target record;
    relation record;
    dependency record;
    trigger_row record;
    function_row record;
    names text[] := ARRAY[
        'career_posts', 'career_reviews', 'career_talks', 'career_lounges',
        'career_labs', 'career_lab_poll_options', 'career_talk_attachments',
        'recruit_sports_details', 'recruit_game_details', 'recruit_study_details',
        'recruit_group_buy_details', 'recruit_curricula'
    ];
    compat_functions text[] := ARRAY[
        'playmate_career_compat_write', 'playmate_poll_compat_write',
        'playmate_attachment_compat_write', '_meetup_compat_detail_write',
        '_meetup_compat_curriculum_write'
    ];
BEGIN
    IF current_setting('playmate.compat_views_application_audit', true)
       IS DISTINCT FROM 'verified' THEN
        RAISE EXCEPTION 'Application/external consumer audit is required before 068';
    END IF;

    -- Inspect every target before issuing any DROP. Missing views allow reruns.
    FOR target IN
        SELECT * FROM (VALUES
            ('career_posts', 'trg_career_posts_compat', 'playmate_career_compat_write'),
            ('career_reviews', 'trg_career_reviews_compat', 'playmate_career_compat_write'),
            ('career_talks', 'trg_career_talks_compat', 'playmate_career_compat_write'),
            ('career_lounges', 'trg_career_lounges_compat', 'playmate_career_compat_write'),
            ('career_labs', 'trg_career_labs_compat', 'playmate_career_compat_write'),
            ('career_lab_poll_options', 'trg_poll_options_compat', 'playmate_poll_compat_write'),
            ('career_talk_attachments', 'trg_talk_attachments_compat', 'playmate_attachment_compat_write'),
            ('recruit_sports_details', 'meetup_detail_write_instead', '_meetup_compat_detail_write'),
            ('recruit_game_details', 'meetup_detail_write_instead', '_meetup_compat_detail_write'),
            ('recruit_study_details', 'meetup_detail_write_instead', '_meetup_compat_detail_write'),
            ('recruit_group_buy_details', 'meetup_detail_write_instead', '_meetup_compat_detail_write'),
            ('recruit_curricula', 'meetup_curriculum_write_instead', '_meetup_compat_curriculum_write')
        ) AS expected(view_name, trigger_name, function_name)
    LOOP
        SELECT c.oid, c.relkind, c.reltype INTO relation
        FROM pg_catalog.pg_class c
        JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relname = target.view_name;
        IF NOT FOUND THEN
            CONTINUE;
        END IF;
        IF relation.relkind <> 'v' THEN
            RAISE EXCEPTION 'Refusing to drop public.%: object is not a VIEW', target.view_name;
        END IF;

        FOR trigger_row IN
            SELECT t.tgname, t.tgtype, p.proname, n.nspname
            FROM pg_catalog.pg_trigger t
            JOIN pg_catalog.pg_proc p ON p.oid = t.tgfoid
            JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace
            WHERE t.tgrelid = relation.oid
        LOOP
            IF trigger_row.tgname <> target.trigger_name
               OR trigger_row.proname <> target.function_name
               OR trigger_row.nspname <> 'public'
               OR (trigger_row.tgtype::integer & 64) = 0 THEN
                RAISE EXCEPTION 'Unexpected trigger on public.%: %', target.view_name, trigger_row.tgname;
            END IF;
            RAISE NOTICE 'View-owned trigger %.% uses retained function public.%',
                target.view_name, trigger_row.tgname, trigger_row.proname;
        END LOOP;

        FOR dependency IN
            SELECT pg_catalog.pg_describe_object(d.classid, d.objid, d.objsubid) AS description
            FROM pg_catalog.pg_depend d
            WHERE d.refclassid = 'pg_catalog.pg_class'::regclass
              AND d.refobjid = relation.oid
              -- Only the view's own implementation objects may be removed.
              AND NOT (
                  (d.classid = 'pg_catalog.pg_rewrite'::regclass AND d.objid IN (
                      SELECT oid FROM pg_catalog.pg_rewrite
                      WHERE ev_class = relation.oid AND rulename = '_RETURN'))
                  OR (d.classid = 'pg_catalog.pg_type'::regclass AND d.objid = relation.reltype)
                  OR (d.classid = 'pg_catalog.pg_trigger'::regclass AND d.objid IN (
                      SELECT oid FROM pg_catalog.pg_trigger WHERE tgrelid = relation.oid))
                  OR (d.classid = 'pg_catalog.pg_attrdef'::regclass AND d.objid IN (
                      SELECT oid FROM pg_catalog.pg_attrdef WHERE adrelid = relation.oid))
              )
        LOOP
            RAISE EXCEPTION 'public.% is referenced by %', target.view_name, dependency.description;
        END LOOP;
    END LOOP;

    -- PL/pgSQL/dynamic SQL references may not appear in pg_depend. Conservatively
    -- stop on textual references in other user functions, including comments.
    -- This cannot detect SQL assembled from fragments: external audit is required.
    FOR function_row IN
        SELECT p.oid, n.nspname, p.proname, p.prosrc
        FROM pg_catalog.pg_proc p
        JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
          AND p.prokind IN ('f', 'p')
    LOOP
        IF function_row.nspname = 'public' AND function_row.proname = ANY(compat_functions) THEN
            -- A compatibility writer must not also serve a non-target relation.
            IF EXISTS (
                SELECT 1 FROM pg_catalog.pg_trigger t
                JOIN pg_catalog.pg_class c ON c.oid = t.tgrelid
                JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
                WHERE t.tgfoid = function_row.oid
                  AND NOT (n.nspname = 'public' AND c.relname = ANY(names))
            ) THEN
                RAISE EXCEPTION 'Compatibility function %.% has external trigger users',
                    function_row.nspname, function_row.proname;
            END IF;
            RAISE NOTICE 'Retaining compatibility function %.% (review definition before deployment)',
                function_row.nspname, function_row.proname;
        ELSIF function_row.prosrc ~* ('\m(' || array_to_string(names, '|') || ')\M') THEN
            RAISE EXCEPTION 'Function %.% may reference compatibility views',
                function_row.nspname, function_row.proname;
        END IF;
    END LOOP;
END;
$preflight$;

-- RESTRICT is also the final, race-safe dependency check. A failure rolls back
-- every preceding drop in this transaction; never replace it with cascade.
DROP VIEW IF EXISTS public.career_posts RESTRICT;
DROP VIEW IF EXISTS public.career_reviews RESTRICT;
DROP VIEW IF EXISTS public.career_talks RESTRICT;
DROP VIEW IF EXISTS public.career_lounges RESTRICT;
DROP VIEW IF EXISTS public.career_labs RESTRICT;
DROP VIEW IF EXISTS public.career_lab_poll_options RESTRICT;
DROP VIEW IF EXISTS public.career_talk_attachments RESTRICT;
DROP VIEW IF EXISTS public.recruit_sports_details RESTRICT;
DROP VIEW IF EXISTS public.recruit_game_details RESTRICT;
DROP VIEW IF EXISTS public.recruit_study_details RESTRICT;
DROP VIEW IF EXISTS public.recruit_group_buy_details RESTRICT;
DROP VIEW IF EXISTS public.recruit_curricula RESTRICT;
COMMIT;
