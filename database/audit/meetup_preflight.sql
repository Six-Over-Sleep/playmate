-- PlayMate meetup DB consolidation preflight (READ-ONLY)
-- Aiven/RDS에서 읽기만 수행합니다. 78개 테이블이라는 숫자를 가정하지 않습니다.
-- 실행 결과를 확인하기 전에는 아래 migration draft를 실행하지 마세요.

-- 전체 물리 테이블 수와 뷰 수: information_schema.tables 대신 pg_class로 정확히 분리.
SELECT c.relkind, COUNT(*) AS object_count
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
GROUP BY c.relkind ORDER BY c.relkind;

-- 모임 영역 실제 객체 유형.
SELECT c.relname AS object_name, c.relkind AS object_type,
       pg_get_userbyid(c.relowner) AS object_owner
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND (c.relname = 'recruits' OR c.relname LIKE 'recruit_%')
  AND c.relkind IN ('r','p','v','m','f')
ORDER BY c.relname;

-- 대상 5개 테이블의 컬럼 정보 (4종 상세 + 커리큘럼).
SELECT table_name, ordinal_position, column_name, data_type, udt_name,
       character_maximum_length, numeric_precision, numeric_scale, is_nullable, column_default
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name IN ('recruits','recruit_programs','recruit_sports_details',
                     'recruit_game_details','recruit_study_details','recruit_group_buy_details',
                     'recruit_curricula')
ORDER BY table_name, ordinal_position;

-- 상세 / 커리큘럼 외래키와 의존 관계. 서로 참조하는 다른 테이블이 있으면 중단 후 검토.
SELECT con.conname, con.contype, con.conrelid::regclass AS from_relation,
       NULLIF(con.confrelid,0)::regclass AS to_relation,
       pg_get_constraintdef(con.oid) AS definition
FROM pg_constraint con
WHERE con.conrelid IN ('public.recruit_sports_details'::regclass,
                       'public.recruit_game_details'::regclass,
                       'public.recruit_study_details'::regclass,
                       'public.recruit_group_buy_details'::regclass,
                       'public.recruit_curricula'::regclass)
   OR con.confrelid IN ('public.recruit_sports_details'::regclass,
                       'public.recruit_game_details'::regclass,
                       'public.recruit_study_details'::regclass,
                       'public.recruit_group_buy_details'::regclass,
                       'public.recruit_curricula'::regclass)
ORDER BY con.conrelid::regclass::text, con.conname;

-- 각 테이블의 인덱스 및 기존 사용자 정의 트리거.
SELECT tablename, indexname, indexdef FROM pg_indexes
WHERE schemaname='public'
 AND tablename IN ('recruit_sports_details','recruit_game_details',
                   'recruit_study_details','recruit_group_buy_details','recruit_curricula')
ORDER BY tablename, indexname;
SELECT tgrelid::regclass AS relation_name, tgname,
       pg_get_triggerdef(oid) AS trigger_definition
FROM pg_trigger WHERE NOT tgisinternal
  AND tgrelid IN ('public.recruit_sports_details'::regclass,
                  'public.recruit_game_details'::regclass,
                  'public.recruit_study_details'::regclass,
                  'public.recruit_group_buy_details'::regclass,
                  'public.recruit_curricula'::regclass)
ORDER BY 1,2;

-- 데이터 건수 및 비정상 카테고리 첨부 여부.
SELECT 'recruit_sports_details' AS table_name, COUNT(*) AS row_count FROM public.recruit_sports_details
UNION ALL SELECT 'recruit_game_details', COUNT(*) FROM public.recruit_game_details
UNION ALL SELECT 'recruit_study_details', COUNT(*) FROM public.recruit_study_details
UNION ALL SELECT 'recruit_group_buy_details', COUNT(*) FROM public.recruit_group_buy_details
UNION ALL SELECT 'recruit_curricula', COUNT(*) FROM public.recruit_curricula;

SELECT 'sports' AS type, COUNT(*) AS mismatches
FROM recruit_sports_details d LEFT JOIN recruits r USING (recruit_id)
WHERE r.recruit_id IS NULL OR r.category IS DISTINCT FROM 'sports'
UNION ALL SELECT 'game', COUNT(*) FROM recruit_game_details d LEFT JOIN recruits r USING (recruit_id)
WHERE r.recruit_id IS NULL OR r.category IS DISTINCT FROM 'game'
UNION ALL SELECT 'study', COUNT(*) FROM recruit_study_details d LEFT JOIN recruits r USING (recruit_id)
WHERE r.recruit_id IS NULL OR r.category IS DISTINCT FROM 'study'
UNION ALL SELECT 'group_buy', COUNT(*) FROM recruit_group_buy_details d LEFT JOIN recruits r USING (recruit_id)
WHERE r.recruit_id IS NULL OR r.category IS DISTINCT FROM 'group_buy';

-- DB 역할별 권한. DROP TABLE 시 뷰에 자동 승계되지 않으므로 반드시 확인.
SELECT table_name, grantee, privilege_type, is_grantable
FROM information_schema.role_table_grants
WHERE table_schema='public' AND table_name IN (
 'recruit_sports_details','recruit_game_details','recruit_study_details',
 'recruit_group_buy_details','recruit_curricula')
ORDER BY table_name, grantee, privilege_type;
