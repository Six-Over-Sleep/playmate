-- DB 적용 후 DBeaver 검증. 모든 SELECT는 읽기 전용이며 데이터 변경 없음.

-- 예상 9개: 034 테이블 4개 + 035 테이블 5개
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
  AND table_name = ANY (ARRAY[
    'member_blocks', 'member_dm_preferences', 'dm_conversations', 'dm_messages',
    'achievement_definitions', 'member_achievements', 'member_profile_preferences',
    'notification_preferences', 'user_notifications'
  ])
ORDER BY table_name;

-- 기대: actual_tables = 9, actual_views = 1, actual_dm_triggers = 5
SELECT
  (SELECT COUNT(*) FROM information_schema.tables
   WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
     AND table_name = ANY (ARRAY[
       'member_blocks','member_dm_preferences','dm_conversations','dm_messages',
       'achievement_definitions','member_achievements','member_profile_preferences',
       'notification_preferences','user_notifications'
     ])) AS actual_tables,
  (SELECT COUNT(*) FROM information_schema.views
   WHERE table_schema='public' AND table_name='v_member_all_achievements') AS actual_views,
  (SELECT COUNT(*) FROM pg_trigger
   WHERE tgrelid IN ('public.dm_conversations'::regclass, 'public.dm_messages'::regclass)
     AND tgname LIKE 'trg_playmate_dm_%' AND NOT tgisinternal) AS actual_dm_triggers;

-- 게시글 신고 및 Discord 전송 큐는 신규 설계와 독립적으로 남아 있어야 한다.
SELECT
  to_regclass('public.post_reports') IS NOT NULL AS post_reports_preserved,
  to_regclass('public.notifications') IS NOT NULL AS discord_queue_preserved,
  to_regclass('public.game_member_badges') IS NOT NULL AS game_badges_preserved;

-- 빈 업적 목록/알림 목록도 SELECT 가능해야 한다.
SELECT * FROM public.v_member_all_achievements LIMIT 5;
SELECT notification_type, COUNT(*) FROM public.user_notifications
GROUP BY notification_type ORDER BY notification_type;
