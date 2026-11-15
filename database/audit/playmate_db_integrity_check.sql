-- PlayMate DB final integrity audit, PostgreSQL 18.
-- READ ONLY: SELECT / catalog inspection only. No INSERT/UPDATE/DELETE/DDL.
-- Assumes migrations through 035 were successfully applied to schema public.
-- Execute whole script in DBeaver (Alt+X), inspect each result set.

-- 1) Database object inventory: no fixed expected number of all old tables.
SELECT
    current_database() AS database_name,
    current_schema() AS search_path_schema,
    COUNT(*) FILTER (WHERE c.relkind IN ('r', 'p')) AS tables,
    COUNT(*) FILTER (WHERE c.relkind = 'v') AS views,
    COUNT(*) FILTER (WHERE c.relkind = 'm') AS materialized_views
FROM pg_class AS c
JOIN pg_namespace AS n ON n.oid = c.relnamespace
WHERE n.nspname = 'public';

-- 2) Exact 028/033/034/035 table coverage: expected present_count=30, missing_count=0.
WITH expected(name) AS (
    VALUES
      ('institutions'), ('campuses'), ('programs'), ('cohorts'),
      ('member_enrollments'), ('enrollment_verifications'),
      ('game_categories'), ('games'), ('game_supported_modes'),
      ('game_questions'), ('game_question_secrets'), ('game_events'),
      ('game_event_questions'), ('game_event_entries'), ('game_event_teams'),
      ('game_matches'), ('game_match_players'), ('game_attempts'),
      ('game_results'), ('game_badges'), ('game_member_badges'),
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

-- 3) Expected application views: expected present_count=4.
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

-- 4) INVALID/NOT VALID constraints, especially FK and CHECK: expect zero rows.
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

-- 4b) Critical constraint names from 034/035: expect zero missing rows.
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
      ('member_profile_preferences', 'fk_member_profile_owned_game_badge'),
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

-- 5) Invalid or not-ready indexes: expect zero rows.
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

-- 6) FK without a suitable left-leading full index: REVIEW candidates, not necessarily errors.
-- NOTE: PostgreSQL creates indexes for referenced PK/UNIQUE keys, not automatically
-- for every referencing FK. Index recommendations require workload/rowcount review.
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

-- 7) Member affiliation breakdown (ACTIVE/COMPLETED still have access after course end).
SELECT e.enrollment_status, COUNT(*) AS enrollments
FROM public.member_enrollments AS e
GROUP BY e.enrollment_status
ORDER BY e.enrollment_status;

-- 8) The previously migrated board 8: expected COHORT / 2 / ALL_VERIFIED / SCOPE_ONLY.
-- The policy name ALL_VERIFIED is legacy nomenclature; API permits ACTIVE/COMPLETED.
SELECT board_id, board_name, scope_type, cohort_id, read_policy, write_policy
FROM public.boards
WHERE board_id = 8;

-- 9) No invalid self-block, reversed DM pair, or nonparticipant sender: expect zero rows each.
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

-- 11) Duplicate table names inside public: PostgreSQL namespace prevents duplicates.
-- Review the public FK graph and ERD source; no database modifications.
SELECT
    fk.conrelid::regclass::text AS child_table,
    fk.confrelid::regclass::text AS parent_table,
    fk.conname,
    pg_get_constraintdef(fk.oid) AS relation
FROM pg_constraint AS fk
JOIN pg_namespace AS ns ON ns.oid = fk.connamespace
WHERE ns.nspname = 'public' AND fk.contype = 'f'
ORDER BY child_table, parent_table, fk.conname;
