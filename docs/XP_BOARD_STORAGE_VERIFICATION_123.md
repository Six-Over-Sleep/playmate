# #123 남은 연동 검증 결과 (2026-11-14 KST 00시대)

브랜치 `feature/123-xp-board-storage`, 미커밋 변경 보존. 모든 쓰기는 일회용 Docker PostgreSQL `pm123-d5b3e739`(127.0.0.1:62109, `playmate_test`)에만 적용했다. 공유 DB 연결·변경 없음. 커밋·푸시 없음.

## 실행 환경

| 항목 | 내용 |
|---|---|
| 기존 8000 백엔드 | 일회용 DB에만 연결됨을 확인. 21:12 시작으로 21:25 수정 코드 미반영 → 종료 권한이 거부되어 유지 |
| 검증용 백엔드 | 현재 작업 트리 코드, 8001, 같은 일회용 DB, `ENABLE_RECRUIT_PROGRAMS=true` (검증 후 종료) |
| 검증용 프론트 | 5174, 프록시 → 8001 (검증 후 종료) |
| 실제 Discord | 사용자 Chrome의 로그인 세션(회원 2 에키드나)으로 5174 → 8001 사용 |
| 테스트 인증 | `X-Dev-Member-ID` (APP_ENV=development). 표기: **[테스트 인증]** / **[Discord 브라우저]** |
| 테스트 회원 | 3 QA참여자A(개설자), 4·5 참여자, 6 QA관리자(ADMIN), 1001~1100 좋아요 집계용, 2001~2005 출석용 |

## 로컬 DB 보완 (저장소 근거)

| 누락 | 근거 | 조치 |
|---|---|---|
| 모임 프로그램·출석·뉴스·스킬사전·알림 테이블 | `database/sql/012,013_member_activity,017,021,022` | 해당 마이그레이션 적용 |
| `recruit_game/study/group_buy_details` | `backend/app/models/recruit.py` | ORM 정의로 생성 |
| `recruits.created_at/updated_at` 기본값 | `database/scripts/create_meetup_table.py` | `DEFAULT CURRENT_TIMESTAMP` 추가, 기존 NULL 채움 |
| `member_xp_history.history_id`, `created_at` | `xp_service.py`, `meetup_xp_service.py`, `mypage.py`의 `RETURNING history_id`·정렬 | IDENTITY PK·`timestamptz DEFAULT now()` 추가 |

적용 전 덤프: 스크래치패드 `backup/playmate_test_before.sql`.

## 결과 요약

| 영역 | 결과 | 비고 |
|---|---|---|
| 1. 타코야끼 좋아요·스크랩 | **통과** [Discord 브라우저] | |
| 2. 다섯 모임 유형 | **통과** 89/89 [테스트 인증] | 첫 실행의 프로젝트 4건 실패는 시나리오 오류(필수 기술 외 담당 기술) → 수정 후 11/11 |
| 3. 모임 XP 승인 | **통과** 17/17 [테스트 인증] | |
| 4. 게시판·취업·마이페이지 | **통과** (결함 1건 수정 후) [테스트 인증] | 댓글 XP 날짜 결함 수정 |
| 5. 방문·출석 | **통과** 32/32 [테스트 인증] + 화면 진입 [Discord 브라우저] | |
| 백엔드 전체 테스트 | 669 passed, 57 skipped, 2 failed | 실패 2건은 깨끗한 HEAD에서도 동일 실패 |

## 1. 실제 Discord 로그인 — 타코야끼 먹는 모임(recruit 1, post 11)

| 단계 | 요청 → 응답 | DB (post_likes / post_scraps) | 화면 |
|---|---|---|---|
| 초기 | `GET /auth/me` 200 (member 2) | 0 / 0 | ♡ 좋아요 0, 스크랩 |
| 등록 클릭 | `PUT /api/recruits/1/like` 200, `PUT /api/recruits/1/scrap` 200 | 1 / 1 | ♥ 좋아요 1, 스크랩됨 |
| 반복 PUT 각 2회 | 모두 200, like_count 1 유지 | 1 / 1 (중복 없음) | — |
| 새로고침 | — | 1 / 1 | ♥ 좋아요 1, 스크랩됨 유지 |
| 목록 | `GET /api/recruits` like_count 1 | — | 카드 "♡ 1" |
| 마이페이지 스크랩 | `GET /api/mypage/scraps` 첫 항목 post 11 | — | "타코야끼 먹는 모임 · 스크랩 · 2026-11-14 00:11" |
| 취소 클릭 | `DELETE …/like` 200, `DELETE …/scrap` 200 | 0 / 0 | ♡ 좋아요 0, 스크랩 |
| 반복 DELETE | 200, like_count 0 (멱등) | 0 / 0 | — |
| 새로고침 | — | 0 / 0 | 취소 상태 유지, 마이페이지에서 제외 |

관찰: 목록 응답에 `liked_by_me`가 없어 목록 카드 하트는 좋아요한 상태에서도 빈 하트(♡ 1)로 보임.

## 2. 다섯 모임 유형 [테스트 인증]

- 운동(단기)·게임(정기 토·일)·공동구매(단기): 등록 201 → 상세 200 → 카테고리 목록 포함·다른 카테고리 제외 → 비개설자 수정·삭제 403 → 개설자 수정 200·재조회 반영(상세 테이블 값 변경 확인) → 삭제 200 → 목록 제외·상세 404, DB `state=CLOSED`, `post_status=DELETED`.
- 일정 저장: 단기 `meeting_start/end` KST(2026-11-20 19:00~21:00), 정기 `regular_days ['토','일']`·`20:00`·`2026-11-21`, 공동구매 `product_name·pickup_method·purchase_url·estimated_price_per_person` 저장.
- 참여(정원 2): 참여 200 확정 1→2, 중복 400 "이미 참여한 모임", 정원 초과 400, DB JOINED 2, 취소 200 → 1(MEMBER CANCELED), 개설자 취소 403.
- 스터디(정기 수, TECHNOLOGY/BEGINNER/SQL): 등록·상세·수정·삭제(신청 이력 없음) 통과. 정원 2에서 A ACCEPTED, A 중복 409, B WAITING(CAPACITY_FULL), A 취소 → B 자동 승격(확정 2/대기 0), 타인 신청 이후 정원 변경 409, 삭제 409.
- 프로젝트(필수 Python·React·SQL, 정원 3): A(Python 중복) WAITING(SKILL_SLOTS_RESERVED), B(React) ACCEPTED, C(SQL) ACCEPTED, D(React) WAITING(CAPACITY_FULL), 중복 409, 필수 외 기술 422. B 취소 → 앞 대기자 A를 건너뛰고 D 승격. 비개설자 수정 403, 정원 변경 409, 제목 수정 200. 참여자 응답에 신청 자료 미포함.

관찰: 기존 3유형은 타인 참여 이력 후에도 개설자 정원 변경 200(계약 문서상 기존 유형 적용은 협의 보류 상태).
관찰(기존 코드): `Post` ORM이 `created_at`을 명시 NULL로 넣어 모임 게시글 `posts.created_at`이 NULL로 저장됨(`recruit.py`는 이번 브랜치 미변경).

## 3. 모임 XP 승인 [테스트 인증]

모임 12(스터디)·14(프로젝트)를 일회용 DB에서 `IN_PROGRESS`, 시작 2026-11-11로 변경 후 실행.

| 시나리오 | 요청 → 응답 | DB 결과 |
|---|---|---|
| 활동 제출 | `POST /activities` 201 ×3, 취소 회원 403 | |
| 일반 회원 승인 | `POST /api/recruits/12/xp/approve` (m=3) 403 | 변화 없음 |
| 관리자 본인 활동 승인 | (m=6, member 6) 403 | 변화 없음 |
| 정책 행 `MEETUP_PARTICIPATION` 삭제 | 503 "모임 XP 지급 정책이 없습니다." | 인정·이력·XP 변화 없음 |
| 023 재실행 후 재시도 | 200 awarded, +10 | total 0→10, 이력 1, 인정 APPROVED |
| 재승인 | 200 awarded=false DUPLICATE | 변화 없음 |
| `xp_award_policies` DROP | STUDY_WEEKLY 503 "XP 정책을 사용할 수 없습니다." | 변화 없음 |
| 023 재실행 후 재시도 | 200 awarded, +15 | total 10→25, 이력 +1 (정책 18행 복구) |
| 재승인 | DUPLICATE | 변화 없음 |
| 마이페이지 XP 이력 | `GET /api/mypage/xp-history` 200 | MEETUP_STUDY_WEEKLY 15, MEETUP_PARTICIPATION 10 |

## 4. 게시판·취업·마이페이지 [테스트 인증]

- 데이터 없음: 게시판 5, HOT, 명예의 전당, 라운지·연구소·톡톡 목록 200 빈 목록, 마이페이지 스크랩 200 빈 목록.
- 자유게시판: 작성 201·POST +5XP. 좋아요 PUT 2회 → 1행, 작성자 POST_LIKE +1 1회. 목록·상세 수치 일치. 취소 0 → 재좋아요 1(추가 XP 없음). 본인 좋아요 XP 없음. 스크랩 PUT 2회 → 1행, 마이페이지 포함 → 취소 시 제외. 댓글 COMMENT +2, 대댓글 REPLY +2, 댓글 2건 = 목록 comment_count 2, 마이페이지 내 댓글·XP 이력 반영.
- 내 과정 게시판(family-ai 36): 과정 회원 조회·작성·스크랩 → 마이페이지 반영, 다른 과정 회원 작성 403. 관찰: 다른 과정 회원 목록 조회 200(기존 테스트 기준 작성만 제한).
- HOT·명예의 전당: 로컬 회원 100명 좋아요 추가 후 두 목록에 표시, HOT·명예의 전당·상세 like_count 101 일치, liked_by_me 반영.
- 라운지·연구소·톡톡: 작성 → 목록 포함, 좋아요 2회 → 1행·상세 liked, 목록·상세 수치 일치, 작성자 POST_LIKE +1, 스크랩 → 상세·마이페이지, 댓글 1 = comment_count 1·댓글러 +2XP, 취소 후 상태 복원.

### 수정한 결함 — 댓글 XP 날짜 비교

- 재현: KST 00:01(UTC 15:01)에 댓글 201, COMMENT/REPLY XP 0. 커리어 댓글도 동일.
- 원인: `grant_xp`가 `comments.created_at`(시간대 없는 `TIMESTAMP`, DB 세션 시간대 값)의 날짜를 KST 오늘과 그대로 비교 → UTC DB에서는 KST 00~09시 댓글이 `INVALID_COMMENT_DATE`. HEAD에도 존재하던 결함.
- 수정: `backend/app/services/xp_service.py`에서 `(created_at::timestamptz AT TIME ZONE 'Asia/Seoul')::date`로 KST 날짜를 조회해 비교(시간대 유무와 무관).
- 재실행: 자유게시판 댓글 +2·대댓글 +2, 라운지·연구소·톡톡 댓글 각 +2, 마이페이지 XP 이력 COMMENT 표시. 백엔드 전체 테스트 재실행.

## 5. 방문 동시성과 출석 경계

### API·DB [테스트 인증]

| 시나리오 | 결과 |
|---|---|
| 024 테이블 제거(백업) 후 | 게시판 목록 200(기본 정렬), visit_id 포함·미포함 방문 200 + 전체 통계 +1씩, HOT 200, 없는 게시판 404, 관리자 통계 200 |
| 같은 앱에 024 적용(재시작 없음) | 개인 집계 Test B 3 / Test A 1, 목록 Test B → Test A 정렬, 다른 회원 정렬 영향 없음, 자유게시판 개인 집계 제외·전체 +1 |
| 같은 ID 순차 재요청 | 두 번째 recorded=false, 개인·전체 각 +1 |
| HTTP 독립 연결 2개 동시 × 20회 | 매회 개인·전체·이벤트 각 1, recorded [true,false] |
| DB 독립 연결 겹침 | 2번 연결이 1번 커밋까지 대기 후 recorded=false, 각 +1 |
| 새 ID 재방문 | 추가 집계 |
| 오류 주입(트리거) | 500, 방문 ID·개인·전체 미저장 → 트리거 제거 후 같은 ID 재시도 1회 집계 |

### 실제 로그인 화면 [Discord 브라우저, 회원 2]

| 동작 | board-view 요청 | 집계 변화 |
|---|---|---|
| 직접 링크 `/board/2` | 1회 200 | 개인 Test A +1, 전체 +1, 이벤트 +1 |
| 사이드바 Test B | 1회 200 | 개인 7→8, 전체 4→5, 이벤트 72 |
| Test B → Test A 돌아오기 | 1회 200 | 개인 7→8, 전체 6→7, 이벤트 73 |
| 사이드바 자유게시판 | 1회 200 | 전체 7→8, 개인 집계 없음(고정 게시판) |
| 상세 → 뒤로 → 다른 상세 | 0회 (상세·댓글 GET만) | 변화 없음 |
| 정렬 변경·검색 재렌더링 | 0회 (검색 GET만) | 변화 없음 |

화면 사이드바 일반 게시판 순서가 DB 회원별 방문 수(Test B > Test A > Test C > Test E)와 일치. 측정 초반 사용자 조작으로 섞인 요청 5건(집계 4)은 제외하고 재측정했다.

### 출석 (`POST /api/mypage/attendance`, KST 2026-11-14) [테스트 인증, 이전 출석 이력은 DB에 사전 입력]

| 경계 | 응답 | 지급 이력 | 누적 | 재요청 |
|---|---|---|---|---|
| 6→7일 | earned 1, bonus 5 | ATTEND, STREAK_7 | +6, streak 7 | DUPLICATE, 변화 없음 |
| 29→30일 | earned 1, bonus 20 | ATTEND, STREAK_30 | +21, streak 30 | DUPLICATE |
| 30→31일 | earned 1, bonus 0 | ATTEND | +1, streak 31 | DUPLICATE |
| 중간 결석 | earned 1, bonus 0 | ATTEND | +1, streak 4 | DUPLICATE |
| 첫 출석 | earned 1, bonus 0 | ATTEND | +1, streak 1 | DUPLICATE |

## 백엔드 테스트

`PLAYMATE_LOCAL_TEST_DB_URL` = 일회용 DB, 수정 후 `pytest backend/tests`: 669 passed, 57 skipped, 2 failed.
실패 `test_recruit_join_member.py::test_router_passes_authenticated_member_id[POST-join_recruit|DELETE-cancel_join]`는 HEAD 임시 worktree에서도 동일 실패(브랜치 무관).

## 병합 전 확인 필요

- 병합을 막는 결함: 없음(댓글 XP 날짜 결함은 수정·재검증 완료, 미커밋).
- 미확인·보류:
  - 실제 출석의 날짜 경과(자정 넘김)는 이력 사전 입력으로 대체 검증.
  - 기존 8000 백엔드는 종료 권한 거부로 구 코드 상태. 브라우저 검증은 현재 코드 8001로 수행.
  - 게시판·취업 좋아요·스크랩·댓글 새로고침은 API 재조회로 확인(브라우저 새로고침은 모임 화면만).
  - 공유 DB 스키마의 `member_xp_history.history_id`·`recruits` 기본값 존재 여부는 미확인(로컬 보완만 수행).
  - 기존 `HEAD` 실패 테스트 2건, 모임 게시글 `posts.created_at` NULL 저장은 별도 이슈.
