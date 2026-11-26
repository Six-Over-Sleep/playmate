-- PLAYMATE 일반 게시글의 선택 익명 기능
-- 기존 글은 닉네임 공개(FALSE)를 유지합니다.
-- DB에 실제 author_member_id를 그대로 두어 작성자 권한은 보존됩니다.

ALTER TABLE posts
ADD COLUMN IF NOT EXISTS is_anonymous BOOLEAN NOT NULL DEFAULT FALSE;

-- 컬럼 생성 확인
SELECT column_name, data_type, column_default
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'posts'
  AND column_name = 'is_anonymous';
