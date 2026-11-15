-- PostgreSQL 18 / PlayMate: 관리자 승인 없는 소속 가입 및 졸업 후 접근 유지
-- 기존 028/029/030이 먼저 적용된 경우에만 실행할 것.
BEGIN;

-- 이 제약조건명은 028 CREATE TABLE에서 PostgreSQL이 생성한 이름입니다.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'public.member_enrollments'::regclass
          AND conname = 'member_enrollments_enrollment_status_check'
          AND contype = 'c'
    ) THEN
        RAISE EXCEPTION '기존 enrollment_status 제약조건을 찾을 수 없습니다.';
    END IF;
END $$;

ALTER TABLE public.member_enrollments
    DROP CONSTRAINT member_enrollments_enrollment_status_check;

ALTER TABLE public.member_enrollments
    ADD CONSTRAINT member_enrollments_enrollment_status_check
    CHECK (enrollment_status IN (
        'PENDING', 'ACTIVE', 'COMPLETED', 'VERIFIED',
        'REJECTED', 'EXPIRED', 'REVOKED'
    ));

-- 직접 소속을 선택한 기존 Family AI 36기 7명을 ACTIVE로 전환.
-- 인원 수를 하드코딩하지 않으므로 현재 매칭 회원만 전환합니다.
UPDATE public.member_enrollments AS e
SET enrollment_status = 'ACTIVE'
FROM public.members AS m
WHERE e.member_id = m.member_id
  AND m.member_status = 'ACTIVE'
  AND m.course = 'family-ai' AND m.cohort = 36
  AND e.enrollment_status = 'PENDING'
  AND EXISTS (
      SELECT 1
      FROM public.cohorts AS c
      JOIN public.programs AS p ON p.program_id = c.program_id
      JOIN public.institutions AS i ON i.institution_id = p.institution_id
      WHERE c.cohort_id = e.cohort_id
        AND c.cohort_no = 36
        AND p.program_code = 'family-ai'
        AND i.institution_code = 'playdata'
  );

SELECT enrollment_status, COUNT(*) AS member_count
FROM public.member_enrollments
GROUP BY enrollment_status
ORDER BY enrollment_status;

COMMIT;
