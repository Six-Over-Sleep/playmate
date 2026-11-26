-- PostgreSQL 18 / 기존 36기 게시판 8을 신규 COHORT 범위로 전환
-- 반드시 백엔드 신규 권한 서비스와 032 정책 적용 및 테스트 이후 실행하세요.
BEGIN;

DO $$
DECLARE
    target_cohort_id BIGINT;
    inactive_count INTEGER;
BEGIN
    SELECT c.cohort_id INTO STRICT target_cohort_id
    FROM public.cohorts AS c
    JOIN public.programs AS p ON p.program_id = c.program_id
    JOIN public.institutions AS i ON i.institution_id = p.institution_id
    WHERE i.institution_code = 'playdata'
      AND p.program_code = 'family-ai'
      AND c.cohort_no = 36
      AND c.campus_id IS NULL;

    SELECT COUNT(*) INTO inactive_count
    FROM public.members AS m
    WHERE m.member_status = 'ACTIVE'
      AND m.course = 'family-ai'
      AND m.cohort = 36
      AND NOT EXISTS (
        SELECT 1 FROM public.member_enrollments AS e
        WHERE e.member_id = m.member_id
          AND e.cohort_id = target_cohort_id
          AND e.enrollment_status IN ('ACTIVE', 'COMPLETED')
      );
    IF inactive_count > 0 THEN
        RAISE EXCEPTION '소속 미활성 기존 회원 %명: 게시판 전환 중단', inactive_count;
    END IF;

    UPDATE public.boards
    SET scope_type = 'COHORT',
        cohort_id = target_cohort_id,
        read_policy = 'ALL_VERIFIED',
        write_policy = 'SCOPE_ONLY'
    WHERE board_id = 8
      AND course_code = 'family-ai'
      AND cohort = 36
      AND scope_type = 'LEGACY';

    IF NOT FOUND THEN
        RAISE EXCEPTION '8번 게시판을 LEGACY에서 전환하지 못했습니다.';
    END IF;
END $$;

COMMIT;
