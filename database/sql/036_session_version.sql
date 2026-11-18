-- PlayMate session revocation: re-runnable migration.
BEGIN;
ALTER TABLE public.members
    ADD COLUMN IF NOT EXISTS session_version INTEGER NOT NULL DEFAULT 0;
COMMIT;
