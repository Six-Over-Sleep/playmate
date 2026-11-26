-- DBeaver / PostgreSQL: 아래 SELECT로 먼저 ADMIN 존재 여부를 확인하세요.
SELECT member_id, role_code
FROM members
ORDER BY member_id;

-- ADMIN이 한 명 이상 있는 경우에만 공지사항 게시판을 생성합니다.
-- 운영 전용 게시판은 일반 사용자가 POST /api/boards로 생성할 수 없습니다.
INSERT INTO boards (
    board_name, description, creation_reason, created_by
)
SELECT
    '공지사항',
    'PLAYMATE 운영 공지사항',
    '운영자 전용 공지',
    m.member_id
FROM members AS m
WHERE UPPER(TRIM(COALESCE(m.role_code, ''))) = 'ADMIN'
  AND NOT EXISTS (
      SELECT 1 FROM boards WHERE board_name = '공지사항'
  )
ORDER BY m.member_id
LIMIT 1;

-- 결과 확인
SELECT board_id, board_name, description, created_by
FROM boards
WHERE board_name = '공지사항';

-- [수동 설정 예시 - 관리자 지정 전 반드시 올바른 회원인지 확인]
-- UPDATE members SET role_code = 'ADMIN' WHERE member_id = 1;
