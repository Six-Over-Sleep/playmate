
-- PostgreSQL 18
-- PlayMate 기존 36기 게시판의 신규 접근 범위 전환
-- 백엔드 권한 검사 및 수강생 인증 완료 후 실행

BEGIN;

DO $$
DECLARE
    target_cohort_id BIGINT;
    unverified_count INTEGER;
BEGIN
    -- 교육기관과 과정이 일치하는 36기 확인
    SELECT c.cohort_id
      INTO STRICT target_cohort_id
    FROM public.cohorts c
    JOIN public.programs p ON p.program_id = c.program_id
    JOIN public.institutions i
      ON i.institution_id = p.institution_id
    WHERE i.institution_code = 'playdata'
      AND p.program_code = 'family-ai'
      AND c.cohort_no = 36
      AND c.campus_id IS NULL;

    -- 기존 활성 회원 중 인증되지 않은 회원 확인
    SELECT COUNT(*)
      INTO unverified_count
    FROM public.members m
    WHERE m.member_status = 'ACTIVE'
      AND m.course = 'family-ai'
      AND m.cohort = 36
      AND NOT EXISTS (
          SELECT 1
          FROM public.member_enrollments e
          WHERE e.member_id = m.member_id
            AND e.cohort_id = target_cohort_id
            AND e.enrollment_status = 'VERIFIED'
            AND e.verified_at IS NOT NULL
            AND e.expires_at > NOW()
      );

    IF unverified_count > 0 THEN
        RAISE EXCEPTION
            '인증되지 않은 기존 회원 %명: 게시판 전환 중단',
            unverified_count;
    END IF;

    -- 기존 게시판을 신규 기수에 연결
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
        RAISE EXCEPTION '8번 게시판을 전환하지 못했습니다.';
    END IF;
END $$;

COMMIT;
