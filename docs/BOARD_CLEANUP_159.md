# 게시판 테이블 정리 (#159) — 044·045

모임 DB 통합(#157, 042·043) 브랜치를 반영한 뒤 작업했다. 마이그레이션은 `044_board_table_cleanup.sql`, `045_post_reactions.sql`이다.

## 변경
| 대상 | 변경 | 이유 |
|---|---|---|
| `board_notice_posts` | 삭제 | 019가 과정 게시판 안내 공지를 한 번씩만 만들려고 쓴 대응표. 앱 코드 미사용 |
| `post_images` (호환 뷰) | 삭제 | 037에서 실제 저장은 `post_attachments`(BOARD)로 옮겨졌고, 게시판 코드가 직접 사용 |
| `member_board_visits` | 삭제 | 회원별 방문 횟수를 `member_board_visit_events.board_id`로 집계 |
| `member_board_visit_events` | `board_id`, `visited_at` 추가 | 방문 1건 = 기록 1행. 기존 횟수는 같은 수의 기록으로 이관 |
| `019_board_notices_reports.sql` | 수정 | 대응표 대신 공지사항 게시판의 같은 제목 안내글로 중복 확인(재실행 시 중복 공지 방지) |
| `post_likes`·`post_scraps`·`post_reports` | `post_reactions` 하나로 통합(045) | 모두 "회원 × 게시글" 관계. `reaction_type`(LIKE·SCRAP·REPORT)으로 구분, 신고만 `reason`·`details` |

- 게시판 영역 물리 테이블: 11개 → 7개. 뷰 1개(`post_images`) 제거.
  남는 7개: `boards`, `posts`, `comments`, `post_attachments`, `post_reactions`, `board_daily_visits`, `member_board_visit_events`
- 성능: 테이블 수 자체는 성능과 무관하다. 045는 기본키 `(post_id, reaction_type, member_id)`와 회원별·신고 인덱스로
  기존 조회와 같은 인덱스 경로를 유지한다. 방문 통계용 `board_daily_visits`는 미리 집계한 테이블이라 일부러 남겼다.
- 신고 번호(`report_id`)는 `reaction_id`로 그대로 옮겨 관리자 화면 식별이 유지된다. 회원 탈퇴는 예전처럼 좋아요·스크랩만 지우고 신고는 남긴다.
- API 요청·응답 형식은 바뀌지 않는다. 게시판 목록 개인 정렬도 같다(공지사항·자유게시판 등은 계속 개인 횟수에서 제외).
- `playmate_attachment_compat_write()` 트리거 함수는 `career_talk_attachments` 호환 뷰가 계속 쓰므로 남긴다.

## 코드
- `board_repository`: 이미지 조회·저장·삭제·순서 정리를 `post_attachments WHERE attachment_scope = 'BOARD'`로 변경
- `activity_repository.record_tracked_board_view`: 횟수 테이블 대신 방문 기록에 `board_id` 저장
- `board_repository.list_boards`: 방문 기록을 집계해 개인 정렬(024·044 미적용 개발 DB는 기본 정렬)
- `schema_check`: `post_images`·`post_likes`·`post_scraps` 필수 해제, `post_attachments`(037)·`member_board_visit_events.board_id`(044)·`post_reactions`(045) 필수
- ORM: `PostLike`·`PostScrap`은 `post_reactions`의 단일 테이블 상속 하위 클래스(`models/post_reaction.py`).
  조회에는 종류 조건이 자동으로 붙어 모임 코드 조회는 그대로이고, INSERT 두 곳(`recruit.py`)만 종류 값과 충돌 기준을 넣었다.
- 신고 조회(`board_moderation.py`)는 `post_reactions`의 REPORT 행을 기존 컬럼 이름으로 꺼낸 하위 쿼리(`_REPORTS`)를 쓴다.

## 배포 순서
1. 대상 DB 백업
2. 042 → 043(모임, #158) → 044 → 045 적용. 044는 037·024 적용과 `post_images`가 뷰인지 먼저 확인하고, 아니면 중단한다.
   045는 건수를 확인하며 옮기고, 다르면 전체를 되돌린다.
3. `python -m backend.scripts.check_deploy_schema` 종료 코드 0 확인
4. #158 → #159 순서로 병합(develop 자동 배포 전에 DB 전환 필수)
5. 확인: `board_notice_posts`·`post_images`·`member_board_visits`·`post_likes`·`post_scraps`·`post_reports`의 `to_regclass`가 모두 NULL,
   `SELECT reaction_type, COUNT(*) FROM post_reactions GROUP BY 1;`이 이관 전 건수와 같음
