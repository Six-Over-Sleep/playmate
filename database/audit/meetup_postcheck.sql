-- 적용 후 읽기 전용 점검. 01만 적용한 경우 4종 뷰/데이터만, 02도 적용한 경우 커리큘럼 추가 확인.
SELECT c.relname, c.relkind, pg_get_userbyid(c.relowner) AS owner
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE n.nspname='public' AND c.relname IN (
 'recruits','recruit_programs',
 'recruit_sports_details','recruit_game_details','recruit_study_details',
 'recruit_group_buy_details','recruit_curricula')
ORDER BY c.relname;

SELECT 'sports' AS category, COUNT(*) AS view_rows FROM public.recruit_sports_details
UNION ALL SELECT 'game', COUNT(*) FROM public.recruit_game_details
UNION ALL SELECT 'study', COUNT(*) FROM public.recruit_study_details
UNION ALL SELECT 'group_buy', COUNT(*) FROM public.recruit_group_buy_details;

SELECT category, COUNT(*) AS rows_with_details
FROM public.recruits WHERE details IS NOT NULL
GROUP BY category ORDER BY category;

SELECT c.relname AS name, c.relkind AS kind, COUNT(*) OVER (PARTITION BY c.relkind) AS objects_of_kind
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE n.nspname='public' AND c.relkind IN ('r','p','v')
ORDER BY c.relkind, c.relname;

SELECT event_object_table AS view_name, trigger_name
FROM information_schema.triggers
WHERE event_object_schema='public'
  AND event_object_table IN (
   'recruit_sports_details','recruit_game_details',
   'recruit_study_details','recruit_group_buy_details','recruit_curricula')
ORDER BY event_object_table;

-- 보존되어야 할 기능은 실제 API E2E로 검증:
-- 생성, 상세, 수정, 삭제, 참여/취소, 카테고리 전환,
-- 프로젝트/스터디 전환, 커리큘럼 저장+충돌검출, 활동 인증/XP, Discord/Bot.
