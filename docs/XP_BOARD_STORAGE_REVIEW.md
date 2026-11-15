# 게시판 목록 정렬과 이미지 저장 점검

- 사이드바는 공지사항, 명예의 전당, HOT 게시판, 자유게시판 순서로 고정한다.
- 내 과정·기수 게시판은 기존대로 상단 영역에 표시한다.
- 일반 게시판은 회원별 방문 횟수 내림차순으로 표시한다. 동률이면 기본 게시판, 생성일, ID 순서를 사용한다.
- 기존 전체 방문 통계는 유지한다. 개인 방문 집계는 마이그레이션 적용 후 실제 게시판 진입부터 시작한다.
- 배포 전 기본 게시판·회원 스키마와 014가 적용된 DB에 024_member_board_visits.sql을 적용한다.
- 게시글 이미지 원본은 uploads/posts에 UUID 파일명으로 저장한다. post_images는 저장 키와 메타데이터를 관리하며 기존 URL은 /uploads/posts 경로로 제공된다. 추후 S3 전환 시 기존 저장 키와 URL 호환성을 검토한다.

XP 정책 적용은 database/sql/023_xp_award_policies.sql을 앱 배포 전에 실행한다. 활동별 지급 수치는 xp_award_policies에서 변경한다. 이미 지급한 수치와 회수는 XP 이력을 기준으로 처리한다.
- 게시글 수정 API는 제목·본문·익명 여부를 수정하며 이미지 교체 기능은 제공하지 않는다. 3개·파일당 5MB 제한은 생성 시 적용한다.

Before deployment, apply 023 and check that all 19 activity types listed in
the migration exist in xp_award_policies. Re-running 023 restores missing
rows while retaining changed amounts. Missing policy data returns HTTP 503
for synchronous XP operations. Post and comment creation paths that award
XP after committing preserve the saved content and log the award failure.

배포 전에 대상 PostgreSQL에 024_member_board_visits.sql을 적용합니다.
SELECT to_regclass('member_board_visits'), to_regclass('member_board_visit_events'); 로 두 테이블을 확인합니다.
적용 전에는 기본 목록과 전체 방문 통계를 제공하며 개인 집계와 방문 ID 중복 제거는 적용 후 시작됩니다.

레벨 기준은 앱 배포 전에 025_level_policies.sql로 level_policies에 저장합니다.
- 종합 레벨(OVERALL) 1~4: 0·100·500·1500 XP, 스킬 레벨(SKILL) 1~5: 0·50·150·300·500 XP (기존 코드 값).
- 레벨은 1부터 빠짐없이, 1레벨은 0 XP, 높은 레벨일수록 시작 XP가 커야 합니다. 테이블이 없거나 조건이 맞지 않으면 레벨 계산이 필요한 API(레벨·스킬 조회, 출석, XP 지급·회수)는 503을 반환하고 부분 저장하지 않습니다.
- 기준을 바꾸면 레벨·스킬 조회 API는 즉시 새 기준으로 계산합니다. member_levels·member_skill_levels에 저장된 level은 다음 XP 변동 때 갱신되므로, 즉시 맞추려면 025 파일 하단의 UPDATE 문을 실행합니다.

지급 한도·스킬 학습 지급량은 027_xp_rule_policies.sql로 저장합니다(xp_limit_policies: POST_DAILY_COUNT 3, COMMENT_DAILY_COUNT 10, POST_LIKE_XP_PER_POST 10 / xp_award_policies: SKILL_QUIZ·PRACTICE·ADVANCED).
- 027이 없으면 글·댓글은 201로 저장되지만 XP가 빠지고(서버 로그에만 기록), 좋아요는 503이며 저장되지 않습니다.
- 배포 순서: 023 → 024 → 025 → 027 적용 후 `python -m backend.scripts.check_deploy_schema`가 종료 코드 0인지 확인합니다. 누락 시 필요한 SQL 파일·정책 행을 출력합니다.
- 앱은 기동 시 같은 검사를 한 번 실행하며, 운영 기본(strict)에서는 누락 시 기동하지 않습니다. 결과는 GET /health/schema로 확인합니다.
- 연속 출석 보너스 기준일은 xp_award_policies의 STREAK_<일수> 행으로 정합니다.
