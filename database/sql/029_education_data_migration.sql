
-- PostgreSQL 18
-- PlayMate 교육기관 초기 데이터 및 기존 회원 소속 이관
-- 기존 members.course, members.cohort 컬럼 유지

BEGIN;

-- 1. 교육기관 등록
INSERT INTO public.institutions (
    institution_code,
    institution_name
)
VALUES (
    'playdata',
    '플레이데이터'
)
ON CONFLICT (institution_code) DO NOTHING;

-- 2. 교육과정 등록
INSERT INTO public.programs (
    institution_id,
    program_code,
    program_name
)
SELECT
    institution_id,
    'family-ai',
    'SK네트웍스 Family AI 캠프'
FROM public.institutions
WHERE institution_code = 'playdata'
  AND institution_name = '플레이데이터'
ON CONFLICT (institution_id, program_code) DO NOTHING;

-- 3. 36기 등록
-- 캠퍼스 정보는 미확정이므로 NULL 유지
INSERT INTO public.cohorts (
    institution_id,
    program_id,
    campus_id,
    cohort_no
)
SELECT
    p.institution_id,
    p.program_id,
    NULL,
    36
FROM public.programs p
JOIN public.institutions i
    ON i.institution_id = p.institution_id
WHERE i.institution_code = 'playdata'
  AND i.institution_name = '플레이데이터'
  AND p.program_code = 'family-ai'
  AND p.program_name = 'SK네트웍스 Family AI 캠프'
ON CONFLICT (program_id, campus_id, cohort_no) DO NOTHING;

-- 4. 기존 활성 회원 7명 이관
-- 인증 완료 처리하지 않고 PENDING으로 등록
INSERT INTO public.member_enrollments (
    member_id,
    cohort_id,
    enrollment_status
)
SELECT
    m.member_id,
    c.cohort_id,
    'PENDING'
FROM public.members m
JOIN public.institutions i
    ON i.institution_code = 'playdata'
   AND i.institution_name = '플레이데이터'
JOIN public.programs p
    ON p.institution_id = i.institution_id
   AND p.program_code = 'family-ai'
   AND p.program_name = 'SK네트웍스 Family AI 캠프'
JOIN public.cohorts c
    ON c.program_id = p.program_id
   AND c.institution_id = i.institution_id
   AND c.cohort_no = 36
   AND c.campus_id IS NULL
WHERE m.member_status = 'ACTIVE'
  AND m.course = 'family-ai'
  AND m.cohort = 36
ON CONFLICT (member_id, cohort_id) DO NOTHING;

-- 5. 이관 검증
SELECT
    i.institution_name,
    p.program_name,
    c.cohort_no,
    e.enrollment_status,
    COUNT(*) AS member_count
FROM public.member_enrollments e
JOIN public.cohorts c ON c.cohort_id = e.cohort_id
JOIN public.programs p ON p.program_id = c.program_id
JOIN public.institutions i ON i.institution_id = p.institution_id
WHERE i.institution_code = 'playdata'
  AND p.program_code = 'family-ai'
  AND c.cohort_no = 36
GROUP BY
    i.institution_name,
    p.program_name,
    c.cohort_no,
    e.enrollment_status;

COMMIT;
