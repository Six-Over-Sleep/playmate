-- Forward-only expansion. Apply separately after schema review and approval.
-- This is not a bootstrap script for pre-existing PlayMate relations.
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';

-- An issued job can never authorize another Discord write, even after SQS dedup expires.
CREATE TABLE public.discord_meeting_jobs (
    job_id UUID PRIMARY KEY, -- also the fencing generation for this scope
    recruit_id BIGINT NOT NULL,
    member_id BIGINT,
    kind TEXT NOT NULL CHECK (kind IN ('create', 'permissions')),
    target JSONB NOT NULL,
    fingerprint TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    sent_at TIMESTAMPTZ,
    approved_at TIMESTAMPTZ,
    approval_id UUID UNIQUE,
    approved_action TEXT,
    finished_at TIMESTAMPTZ,
    outcome TEXT,
    result_channel_id TEXT,
    CHECK ((kind = 'create') = (member_id IS NULL)),
    CHECK ((approved_at IS NULL) = (approval_id IS NULL)
       AND (approved_at IS NULL) = (approved_action IS NULL))
);
CREATE UNIQUE INDEX discord_meeting_active_create ON public.discord_meeting_jobs(recruit_id)
    WHERE kind = 'create' AND finished_at IS NULL;
CREATE UNIQUE INDEX discord_meeting_active_permission ON public.discord_meeting_jobs(recruit_id, member_id)
    WHERE kind = 'permissions' AND finished_at IS NULL;
CREATE INDEX discord_meeting_permission_history ON public.discord_meeting_jobs(recruit_id, member_id, created_at DESC)
    WHERE kind = 'permissions';

-- Deployment changes ownership only after the previous writer has drained.
CREATE TABLE public.discord_meeting_control (
    singleton BOOLEAN PRIMARY KEY CHECK (singleton),
    create_owner TEXT NOT NULL DEFAULT 'gateway' CHECK (create_owner IN ('gateway','paused','lambda')),
    permission_owner TEXT NOT NULL DEFAULT 'gateway' CHECK (permission_owner = 'gateway'),
    result_seen_at TIMESTAMPTZ
);
INSERT INTO public.discord_meeting_control(singleton) VALUES (TRUE);

CREATE FUNCTION public.discord_meeting_guard_handoff() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
BEGIN
    IF NEW.create_owner IS DISTINCT FROM OLD.create_owner THEN
        IF NOT pg_try_advisory_xact_lock(18801) THEN
            RAISE EXCEPTION 'Gateway create must drain before handoff';
        END IF;
        IF NEW.create_owner = 'gateway' AND EXISTS (
            SELECT 1 FROM public.discord_meeting_jobs WHERE kind='create'
            AND finished_at IS NULL
        ) THEN RAISE EXCEPTION 'Meeting create approvals must be reconciled before handoff'; END IF;
    END IF;
    IF NEW.permission_owner IS DISTINCT FROM OLD.permission_owner THEN
        IF NOT pg_try_advisory_xact_lock(18802) THEN
            RAISE EXCEPTION 'Gateway permission writes must drain before handoff';
        END IF;
        IF NEW.permission_owner = 'gateway' AND EXISTS (
            SELECT 1 FROM public.discord_meeting_jobs WHERE kind='permissions'
            AND approved_at IS NOT NULL
            AND (finished_at IS NULL OR outcome IN ('unknown','expired'))
        ) THEN RAISE EXCEPTION 'Meeting permission approvals must be reconciled before handoff'; END IF;
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER discord_meeting_guard_handoff
BEFORE UPDATE OF create_owner, permission_owner ON public.discord_meeting_control
FOR EACH ROW EXECUTE FUNCTION public.discord_meeting_guard_handoff();

CREATE FUNCTION public.discord_meeting_permission_snapshot(p_recruit_id BIGINT, p_member_id BIGINT)
RETURNS TABLE(discord_id TEXT, desired TEXT, fingerprint TEXT, managed BOOLEAN)
LANGUAGE sql STABLE SECURITY INVOKER SET search_path = pg_catalog, public AS $$
    SELECT CASE WHEN m.member_status = 'ACTIVE' AND m.discord_id ~ '^[0-9]{15,25}$'
                THEN m.discord_id::text ELSE prior.target->>'user_id' END,
           CASE WHEN m.member_status = 'ACTIVE' AND m.discord_id ~ '^[0-9]{15,25}$'
                     AND rm.status = 'JOINED' THEN 'grant' ELSE 'revoke' END,
           md5(jsonb_build_array(m.member_status, m.discord_id, rm.status, rm.joined_at,
                                rm.canceled_at, rc.discord_text_channel_id)::text),
           prior.target IS NOT NULL AND (m.member_status <> 'ACTIVE' OR prior.target->>'user_id'=m.discord_id)
    FROM public.recruit_discord_channels rc
    JOIN public.recruits r USING (recruit_id)
    JOIN public.posts p ON p.post_id = r.post_id
    JOIN public.members m ON m.member_id = p_member_id
    LEFT JOIN public.recruit_members rm ON rm.recruit_id = rc.recruit_id AND rm.member_id = m.member_id
    LEFT JOIN LATERAL (
        SELECT j.target FROM public.discord_meeting_jobs j
        WHERE j.recruit_id = rc.recruit_id AND j.member_id = m.member_id AND j.approved_action = 'grant'
          AND j.target->>'channel_id' = rc.discord_text_channel_id
          AND j.outcome IS DISTINCT FROM 'rejected'
          AND NOT EXISTS (
              SELECT 1 FROM public.members other
              WHERE other.member_id <> m.member_id AND other.member_status = 'ACTIVE'
                AND other.discord_id = j.target->>'user_id'
          )
        ORDER BY j.approved_at DESC LIMIT 1
    ) prior ON TRUE
    WHERE rc.recruit_id = p_recruit_id AND r.recruit_mode IN ('regular','short')
      AND p.post_status IS DISTINCT FROM 'DELETED' AND rc.sync_status = 'SUCCESS'
      AND rc.discord_deleted_at IS NULL AND rc.discord_category_id IS NULL
      AND (rm.status IN ('JOINED','CANCELED') OR prior.target IS NOT NULL)
$$;

REVOKE EXECUTE ON FUNCTION public.discord_meeting_permission_snapshot(BIGINT, BIGINT) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.discord_meeting_guard_handoff() FROM PUBLIC;

-- Do not run this migration or grant permissions implicitly from any application.
COMMIT;
