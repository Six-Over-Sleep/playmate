-- Owner-privileged compatibility triggers are attached only by the DB owner.
-- Trigger execution does not require callers to have function EXECUTE;
-- revoking PUBLIC prevents an unprivileged role from attaching these functions
-- to a table of its own and impersonating a compatibility interface.
BEGIN;
ALTER FUNCTION public.playmate_career_compat_write() SET search_path = pg_catalog, public, pg_temp;
ALTER FUNCTION public.playmate_poll_compat_write() SET search_path = pg_catalog, public, pg_temp;
ALTER FUNCTION public.playmate_attachment_compat_write() SET search_path = pg_catalog, public, pg_temp;
ALTER FUNCTION public.playmate_delete_career_attachments() SET search_path = pg_catalog, public, pg_temp;
REVOKE ALL ON FUNCTION public.playmate_career_compat_write() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.playmate_poll_compat_write() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.playmate_attachment_compat_write() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.playmate_delete_career_attachments() FROM PUBLIC;
COMMIT;
