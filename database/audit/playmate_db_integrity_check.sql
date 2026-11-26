-- PlayMate DB final integrity audit, PostgreSQL 18.
-- READ ONLY: SELECT / catalog inspection only. No INSERT/UPDATE/DELETE/DDL.
-- Final GameZone contract: migrations 054-066 applied after historical 028/033/034/035.
-- Execute the entire script in DBeaver and review EACH result set.
-- It does not migrate any data and is NOT a production deployment script.

-- 1) Database object inventory (informational).
SELECT
    current_database() AS database_name,
    current_schema() AS search_path_schema,
    COUNT(*) FILTER (WHERE c.relkind IN ('r', 'p')) AS tables,
    COUNT(*) FILTER (WHERE c.relkind = 'v') AS views,
    COUNT(*) FILTER (WHERE c.relkind = 'm') AS materialized_views
FROM pg_class AS c
JOIN pg_namespace AS n ON n.oid = c.relnamespace
WHERE n.nspname = 'public';

-- 2) 028 + final GameZone 7 + 034/035: expected_count=22, present_count=22, missing_count=0.
WITH expected(name) AS (
    VALUES
      ('institutions'), ('campuses'), ('programs'), ('cohorts'),
      ('member_enrollments'), ('enrollment_verifications'),
      ('games'), ('game_questions'), ('game_events'),
      ('game_event_entries'), ('game_matches'), ('game_match_players'),
      ('game_attempts'),
      ('member_blocks'), ('member_dm_preferences'), ('dm_conversations'),
      ('dm_messages'), ('achievement_definitions'), ('member_achievements'),
      ('member_profile_preferences'), ('notification_preferences'),
      ('user_notifications')
)
SELECT
    COUNT(*) AS expected_count,
    COUNT(*) FILTER (WHERE c.oid IS NOT NULL) AS present_count,
    COUNT(*) FILTER (WHERE c.oid IS NULL) AS missing_count,
    COALESCE(string_agg(e.name, ', ' ORDER BY e.name)
        FILTER (WHERE c.oid IS NULL), '') AS missing_names
FROM expected AS e
LEFT JOIN pg_class AS c
  ON c.relnamespace = 'public'::regnamespace
 AND c.relname = e.name AND c.relkind IN ('r', 'p');

-- 2b) Eight removed GameZone tables must be absent: remaining_legacy_tables=0.
WITH removed(name) AS (
    VALUES
      ('game_categories'), ('game_supported_modes'),
      ('game_results'), ('game_event_questions'),
      ('game_badges'), ('game_member_badges'),
      ('game_question_secrets'), ('game_event_teams')
)
SELECT
    COUNT(*) FILTER (WHERE to_regclass('public.' || name) IS NOT NULL)
      AS remaining_legacy_tables,
    COALESCE(string_agg(name, ', ' ORDER BY name)
      FILTER (WHERE to_regclass('public.' || name) IS NOT NULL), '')
      AS remaining_legacy_names
FROM removed;

-- 2c) New columns for consolidated GameZone: expected_columns=8, present_columns=8.
WITH expected(table_name, column_name) AS (
    VALUES
      ('games','category_name'), ('games','category_sort_order'),
      ('games','supported_modes'),
      ('game_questions','answer_key'), ('game_questions','judge_config'),
      ('game_questions','answer_updated_at'),
      ('game_events','question_set'), ('game_events','team_set')
)
SELECT COUNT(*) AS expected_columns,
       COUNT(c.column_name) AS present_columns,
       COALESCE(string_agg(e.table_name || '.' || e.column_name, ', ')
           FILTER (WHERE c.column_name IS NULL), '') AS missing_columns
FROM expected e
LEFT JOIN information_schema.columns c
  ON c.table_schema = 'public' AND c.table_name = e.table_name
 AND c.column_name = e.column_name;

-- 3) Four application views must exist: expected_count=4, present_count=4.
WITH expected(name) AS (
    VALUES ('v_game_member_rankings'), ('v_game_weekly_cohort_scores'),
           ('v_game_daily_quiz_scores'), ('v_member_all_achievements')
)
SELECT
    COUNT(*) AS expected_count,
    COUNT(*) FILTER (WHERE c.oid IS NOT NULL) AS present_count,
    COALESCE(string_agg(e.name, ', ' ORDER BY e.name)
        FILTER (WHERE c.oid IS NULL), '') AS missing_names
FROM expected AS e
LEFT JOIN pg_class AS c
  ON c.relnamespace = 'public'::regnamespace
 AND c.relname = e.name AND c.relkind = 'v';

-- 3b) No public view references removed GameZone relations: expect zero rows.
SELECT viewname AS legacy_view
FROM pg_views
WHERE schemaname = 'public'
  AND definition ~* '\m(game_categories|game_supported_modes|game_results|game_event_questions|game_badges|game_member_badges|game_question_secrets|game_event_teams)\M';

-- 4) Invalid/not validated FK and CHECK constraints: expect zero rows.
SELECT
    c.conrelid::regclass::text AS table_name,
    c.conname AS constraint_name,
    CASE c.contype WHEN 'f' THEN 'FOREIGN KEY' WHEN 'c' THEN 'CHECK'
        WHEN 'p' THEN 'PRIMARY KEY' WHEN 'u' THEN 'UNIQUE' ELSE c.contype::text END AS kind,
    c.convalidated,
    pg_get_constraintdef(c.oid) AS definition
FROM pg_constraint AS c
JOIN pg_namespace AS n ON n.oid = c.connamespace
WHERE n.nspname = 'public'
  AND c.contype IN ('f', 'c')
  AND NOT c.convalidated
ORDER BY table_name, constraint_name;

-- 4b) Critical 034/035 constraints AFTER legacy badge FK cutover: expect zero rows.
WITH expected(table_name, constraint_name) AS (
    VALUES
      ('member_blocks', 'chk_member_blocks_no_self'),
      ('dm_conversations', 'chk_dm_conversations_order'),
      ('dm_conversations', 'uq_dm_conversations_members'),
      ('dm_messages', 'uq_dm_messages_idempotency'),
      ('dm_messages', 'chk_dm_messages_body'),
      ('achievement_definitions', 'chk_achievement_category'),
      ('member_achievements', 'chk_member_achievements_metadata'),
      ('member_profile_preferences', 'chk_member_profile_one_badge'),
      ('member_profile_preferences', 'fk_member_profile_owned_achievement'),
      ('user_notifications', 'user_notifications_achievement_id_fkey'),
      ('notification_preferences', 'chk_notification_preferences_system'),
      ('user_notifications', 'chk_user_notifications_one_target')
)
SELECT e.table_name, e.constraint_name AS missing_constraint
FROM expected AS e
LEFT JOIN pg_class AS t ON t.relnamespace = 'public'::regnamespace
                         AND t.relname = e.table_name
LEFT JOIN pg_constraint AS c ON c.conrelid = t.oid
                             AND c.conname = e.constraint_name
WHERE c.oid IS NULL
ORDER BY e.table_name, e.constraint_name;

-- 4c) Final GameZone integrity triggers: expected_triggers=8, enabled_triggers=8.
WITH expected(name) AS (
    VALUES
      ('trg_validate_game_mode_176'), ('trg_protect_game_modes_176'),
      ('trg_validate_event_questions_176'), ('trg_protect_event_question_176'),
      ('trg_sync_game_category_176'), ('trg_validate_game_event_team_set_176'),
      ('trg_validate_game_player_team_176'), ('trg_protect_game_match_event_team_176')
)
SELECT COUNT(*) AS expected_triggers,
       COUNT(t.oid) AS enabled_triggers,
       COALESCE(string_agg(e.name, ', ' ORDER BY e.name)
         FILTER (WHERE t.oid IS NULL), '') AS missing_triggers
FROM expected e
LEFT JOIN (
    SELECT t.oid, t.tgname
    FROM pg_trigger t
    JOIN pg_class c ON c.oid = t.tgrelid
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public' AND t.tgenabled = 'O'
      AND NOT t.tgisinternal
) t ON t.tgname = e.name;

-- 5) Invalid/not-ready indexes: expect zero rows.
SELECT
    t.oid::regclass::text AS table_name,
    ix.indexrelid::regclass::text AS index_name,
    ix.indisvalid,
    ix.indisready
FROM pg_index AS ix
JOIN pg_class AS t ON t.oid = ix.indrelid
JOIN pg_namespace AS n ON n.oid = t.relnamespace
WHERE n.nspname = 'public'
  AND (NOT ix.indisvalid OR NOT ix.indisready)
ORDER BY table_name, index_name;

-- 6) FK without suitable left-leading full index: REVIEW candidates, not necessarily errors.
SELECT
    fk.conrelid::regclass::text AS child_table,
    fk.conname AS fk_name,
    pg_get_constraintdef(fk.oid) AS fk_definition
FROM pg_constraint AS fk
JOIN pg_class AS t ON t.oid = fk.conrelid
JOIN pg_namespace AS ns ON ns.oid = t.relnamespace
WHERE ns.nspname = 'public'
  AND fk.contype = 'f'
  AND NOT EXISTS (
      SELECT 1 FROM pg_index AS ix
      WHERE ix.indrelid = fk.conrelid
        AND ix.indisvalid
        AND ix.indpred IS NULL
        AND ix.indexprs IS NULL
        AND ix.indnkeyatts >= cardinality(fk.conkey)
        AND ARRAY(
          SELECT ix.indkey[pos]::smallint
          FROM generate_series(0, cardinality(fk.conkey) - 1) AS g(pos)
          ORDER BY pos
        ) = fk.conkey
  )
ORDER BY child_table, fk_name;

-- 7) Member affiliation breakdown (informational).
SELECT e.enrollment_status, COUNT(*) AS enrollments
FROM public.member_enrollments AS e
GROUP BY e.enrollment_status
ORDER BY e.enrollment_status;

-- 8) Previously migrated board 8 (informational).
SELECT board_id, board_name, scope_type, cohort_id, read_policy, write_policy
FROM public.boards
WHERE board_id = 8;

-- 9) Invalid self-block, DM pair, or nonparticipant sender: expect zeros.
SELECT COUNT(*) AS invalid_self_blocks
FROM public.member_blocks WHERE blocker_member_id = blocked_member_id;

SELECT COUNT(*) AS invalid_dm_conversation_pairs
FROM public.dm_conversations WHERE member_low_id >= member_high_id;

SELECT COUNT(*) AS invalid_dm_senders
FROM public.dm_messages AS m
JOIN public.dm_conversations AS c ON c.conversation_id = m.conversation_id
WHERE m.sender_member_id NOT IN (c.member_low_id, c.member_high_id);

-- 10) DM guard trigger count: expected 5.
SELECT COUNT(*) AS actual_dm_triggers
FROM pg_trigger
WHERE tgrelid IN ('public.dm_conversations'::regclass,
                   'public.dm_messages'::regclass)
  AND tgname LIKE 'trg_playmate_dm_%'
  AND NOT tgisinternal;

-- 11) Public foreign key graph (informational).
SELECT
    fk.conrelid::regclass::text AS child_table,
    fk.confrelid::regclass::text AS parent_table,
    fk.conname,
    pg_get_constraintdef(fk.oid) AS relation
FROM pg_constraint AS fk
JOIN pg_namespace AS ns ON ns.oid = fk.connamespace
WHERE ns.nspname = 'public' AND fk.contype = 'f'
ORDER BY child_table, parent_table, fk.conname;

-- 12) SECURITY REVIEW: in final schema answer_key/judge_config share
-- game_questions with public content. Table-level SELECT grants to the app role
-- grant read access to these columns; review API projection AND database grants.
-- Informational only; NOT evidence of an API data leak.
SELECT grantee, privilege_type, is_grantable
FROM information_schema.table_privileges
WHERE table_schema = 'public'
  AND table_name = 'game_questions'
  AND privilege_type = 'SELECT'
ORDER BY grantee;
