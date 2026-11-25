# API 연동 지도와 화면별 점검 결과 (2026-11-15)

브랜치 `feature/123-xp-board-storage`. 백엔드는 현재 작업 트리 코드(8001), 프론트는 그 백엔드를 보는 Vite(5174), DB는 일회용 로컬 PostgreSQL(`pm123-d5b3e739`)만 사용했다. 공유 DB에는 연결하지 않았고 커밋하지 않았다.

- **[Discord]** 실제 Discord 로그인 세션(회원 2)으로 Chrome 화면 조작
- **[테스트 인증]** `X-Dev-Member-ID`로 개설자·참여자·관리자 역할 재현
- 관리자 화면은 일회용 DB에서 회원 2의 역할을 잠시 ADMIN으로 바꿔 확인한 뒤 USER로 되돌렸다.

상태: **정상** 그대로 연동됨 · **수정함** 이번에 고쳐서 재검증 · **미연결** 한쪽만 있음 · **보류** 시도했으나 환경 제약

## 1. 경로·메서드 대조

프론트 `services/*`, 훅, 컴포넌트의 `apiRequest`/`fetch` 호출에서 뽑은 메서드·경로 106개(이번에 추가한 화면 연결 전 기준)를 FastAPI `app.routes`와 메서드·경로 단위로 대조했다.

- 프론트가 부르는데 백엔드에 없는 경로: **0개**
- 백엔드에만 있던 화면 기능: `POST/GET /api/mypage/attendance`, `GET /api/recruits/{id}/activities`, `GET /api/admin/meetup-xp/activities`, `POST /api/recruits/{id}/xp/approve·revoke` → **이번에 화면 연결**
- 백엔드에만 있고 아직 화면 없음: `GET/PUT /api/recruits/{id}/curriculum`, `GET /api/mypage/skills/topics`, `GET /api/mypage/skills/accuracy`, `GET /api/mypage/career-specs/public/{id}`, `GET /api/admin/board-reports`(요약형, 화면은 `details` 사용), `GET /api/boards/{id}`

## 2. 화면별 결과

### 게시판 [Discord]
| 기능 | 요청 → 응답 | DB·화면 | 상태 |
|---|---|---|---|
| 자유·HOT·명예의 전당·내 과정·일반 게시판 목록/상세 | GET 200 (4xx·5xx 0건) | 렌더 정상 | 정상 |
| 글쓰기 + 이미지 첨부 | `POST /boards/1/posts` 201, `GET /uploads/posts/*.png` 200 | `post_images` 저장, POST XP +5 | 정상 |
| 글 수정 / 삭제 | PATCH 200 / DELETE 204 | 삭제 시 XP -5 회수, 목록 제외 | 정상 |
| 익명 댓글·수정·삭제 | POST 201 / PATCH 200 | `is_anonymous=true`, 화면 "익명" | 정상 |
| 댓글 작성 시각 표시 | 응답 `04:15`(시간대 없음) → 화면 "오전 4:15"(실제 13:15) | **9시간 이르게 표시** | **수정함** → 응답 `…Z`, 화면 "오후 1:28" |
| 신고 | `POST …/reports` 201 | ABUSE·사유 저장 | 정상 |
| 게시판 생성 | `POST /boards` 201 | 사이드바 즉시 표시 | 정상 |
| 좋아요·스크랩·방문 집계 | 이전 검증(XP_BOARD_STORAGE_VERIFICATION_123.md) | | 정상 |

### 모임 [Discord + 테스트 인증]
| 기능 | 요청 → 응답 | DB·화면 | 상태 |
|---|---|---|---|
| 운동 단기 / 게임 정기 / 공동구매 등록 (실제 폼) | `POST /recruits` 201 ×3 | KST 일정·종목·요일·상품·가격(“12,000”→12000) 저장 | 정상 |
| 스터디 정기 / 프로젝트 단기 등록 (실제 폼) | 201 ×2 | UTC 변환(19:00 KST→10:00Z), 개설자 신청 ACCEPTED·담당 기술·팀장 희망 | 정상 |
| 수정·삭제 | PATCH 200 / DELETE | 상세 반영 | 정상 |
| 모임 댓글 작성·수정·삭제 | 201 / 200 / 200 | 논리삭제 | 정상 |
| 모임 댓글 시각 | 작성은 UTC, 수정·삭제는 서버 로컬(`datetime.now()`, KST)로 기록 | **같은 컬럼에 기준 혼재, 9시간 오차** | **수정함** → DB 시계(`func.now()`), 응답 `+00:00` |
| 기존 모임 참여·취소 | POST/DELETE `/join` 200 | 1→2→1명 | 정상 |
| 프로젝트 신청 모달(담당 기술·직접 입력) | `POST /recruits/8/join` 200 | skills 쉼표 분리, 경험·포트폴리오 저장, 확정 2/3 | 정상 |
| 활동 작성 모달(중간 결과물·참여 인증) | `POST /activities` 201 | payload·링크 저장 | 정상 |
| 활동 기록 목록 | 프론트 호출 없음 | **제출한 활동을 화면에서 볼 수 없음** | **수정함** → `MeetupActivityList`, 등록 후 1→2건 갱신 |
| 커리어 불러오기(신청서) | 화면 "준비 중", 백엔드는 `career_item_ids=[]`만 허용 | | 미연결(양쪽 미구현) |
| 커리큘럼 | 백엔드만 있음 | | 미연결 |
| 장소 지도 좌표 | 프론트가 좌표를 요청에서 제외, 백엔드 컬럼 없음 | | 미연결(설계상 텍스트 장소만 저장) |

### 취업 [Discord]
| 기능 | 요청 → 응답 | DB·화면 | 상태 |
|---|---|---|---|
| 취준 도감·톡톡·라운지·연구소 목록/상세 | GET 200 | | 정상 |
| 취업 후기 작성(500자) | `POST /career/reviews` 201 | 직무 코드 `SOFTWARE_DEVELOPMENT`, CAREER_INTERVIEW +50 | 정상 |
| 연구소 토론 + 투표 선택지 | `POST /career/labs` 201, `POST …/votes` 201 | 선택지 2개, 투표 1건 | 정상 |
| 커리어 브리핑 뉴스 목록·스크랩 | GET 200 / PUT 200 | 새로고침 후 ♥ 유지, 스크랩 목록 반영 | 정상 |
| 커리어 댓글 시각 | 게시판 댓글과 같은 저장소 사용 | | 수정함(게시판과 함께) |
| 채용 인사이트 | 화면 "데이터 연동 준비 중" | | 미연결 |

### 마이페이지 [Discord]
| 기능 | 요청 → 응답 | DB·화면 | 상태 |
|---|---|---|---|
| 레벨·스킬·XP 내역·활동 9개 탭 | GET 200 | | 정상 |
| 나의 스펙 | 로컬 DB에 `member_career_specs` 없음 → 500 | 저장소 DDL 없음, 코드 근거로 로컬 생성 | 보류→정상(로컬) |
| 스펙 저장·최초 공개 | PUT 200 / PATCH 200 | 공개 보상 50XP가 **코드 하드코딩** | **수정함** → `xp_award_policies.CAREER_SPEC_PUBLIC` |
| 출석 체크 | 프론트 호출 없음 | **"출석으로 XP 획득" 안내만 있고 방법 없음** | **수정함** → 종합 레벨에 출석 현황·버튼 (11→12XP, 재요청 DUPLICATE) |
| XP 내역 라벨 | `STREAK_7/30`, `CAREER_GUIDE`, `REVOKE`가 영문 코드로 표시 | | **수정함** |
| 닉네임 변경 | PATCH 200 | | 정상 |
| 프로필 이미지 업로드 | 백엔드가 403(Discord 아바타 사용) | 프론트 `uploadMyProfileImage`는 미사용 | 의도적 비활성 |

### 관리자 [Discord, 로컬 ADMIN]
| 기능 | 요청 → 응답 | DB·화면 | 상태 |
|---|---|---|---|
| 대시보드·공지·게시글·신고·회원·이용 통계 탭 | GET 200 | | 정상 |
| 공지 등록·수정·삭제 | 201 / 200 / 204 | (로컬에 공지사항 게시판이 없어 첫 시도 409 → 저장소 015 시드 적용) | 정상 |
| 게시글 숨김·공개 | PATCH 204, 일반 회원 403 | 숨김 시 목록 제외 | 정상 |
| 신고 시각 | 시간대 없음 | | **수정함** → `…+00:00` |
| 이용 통계 회원 목록 | 서버는 10명 단위 페이지, 화면은 1페이지만 | **11번째 회원부터 볼 수 없음**(사용 중 아닌 `AdminUsagePanel (1).jsx`에만 페이지 이동) | **수정함** → 1/3→2/3, 기간 변경 시 1페이지 |
| 모임 XP 승인·회수 | 화면 없음 | **관리자가 모임 XP를 지급할 방법이 없음** | **수정함** → "모임 XP" 탭: 승인 10·15XP, 재승인 중복, 본인 활동 403, 회수 -15 |

## 3. 수정 내용과 회귀 테스트

| 결함 | 수정 | 테스트 |
|---|---|---|
| 댓글·신고 시각 9시간 오차 | `board_repository`(세션 시간대 부착), `recruit_comment`(DB 시계·시간대 부착), `mypage`·`board_moderation` SQL `::timestamptz` | `test_comment_timezone.py` |
| 스펙 공개 보상 하드코딩 | `read_xp_amount("CAREER_SPEC_PUBLIC")`, 023에 행 추가, 화면 문구는 서버 지급량 표시 | `test_xp_policy_coverage.py`, API: 행 없음 503·30으로 변경 시 30XP |
| 레벨 기준 하드코딩 | `025_level_policies.sql`, 종합·스킬 레벨 공통 계산 | `test_level_policies.py` |
| 출석·활동 목록·모임 XP·통계 페이지 미연결 | 화면 연결 (`OverallLevel`, `MeetupActivityList`, `AdminMeetupXPPanel`, `AdminUsagePanel`) | 실제 화면 재실행 |

전체: 백엔드 705 passed / 2 failed(`test_recruit_join_member.py`, HEAD에서도 동일 실패) / 55 skipped (기준 스키마 회귀 테스트 포함), 프론트 빌드 성공, 프론트 단위 테스트 20/20.

## 4. 기준 스키마 (000·026)

공유 DB(PostgreSQL 18.7) 카탈로그를 **읽기 전용 세션**(`default_transaction_read_only=on`)으로 조회해 만들었다. 데이터는 읽지 않았고 공유 DB에는 아무것도 쓰지 않았다.

- `000_baseline_schema.sql`: 저장소에 DDL이 없던 16개 테이블(`members`, `posts`, `recruits`, `recruit_members`, 모임 상세 4종, `member_levels`, `member_xp_history`, `member_skill_attempts·levels·xp_history`, `member_career_specs`, `post_likes`, `post_scraps`)의 컬럼·기본값·식별자·PK/UNIQUE/CHECK/FK·인덱스. 모두 `IF NOT EXISTS`.
- `026_baseline_followups.sql`: `001` 이후 테이블과 얽혀 000에 둘 수 없는 항목 — `posts.board_id → boards` 외래키, 그리고 저장소 어디에도 없던 **`comments.parent_comment_id`(대댓글) 컬럼·외래키·인덱스**.
- `025_level_policies.sql`: 공유 DB의 `member_levels` 레벨 상한 제약(`level <= 4`)을 하한(`level >= 1`)만 남기도록 변경. 상한은 `level_policies`가 정한다.

검증(빈 PostgreSQL 16 컨테이너):

| 항목 | 결과 |
|---|---|
| `000`~`026` 파일 이름 순 적용 | 29개 모두 오류 없음 |
| `000`·`025`·`026` 재실행 | 오류 없음(기존 004·012_recruit_programs는 재실행 시 오류 — 기존 파일). 컬럼이 빠진 예전 로컬 DB에도 적용됨(빠진 컬럼만 추가) |
| 공유 DB와 테이블 비교 | 공유 49개 모두 생성, 신규 3개(024·025) |
| 컬럼 차이 | 2건 — `boards.category`(공유 DB에 003 미적용), `members.external_dm_opt_in` 기본값(공유 DB에 012_member_dm_default_on 미적용) |
| 제약·인덱스 차이 | 레벨 CHECK(025 의도), `notifications(comment_id)` 인덱스(공유 DB에 022 일부 미적용), 스킬 코드 CHECK 표기 차이(PG16/18 출력 형식, 의미 동일) |
| 새 DB로 백엔드 실행 | 모임 50/50·11/11(테스트 데이터 1건 제외), XP 승인 17/17, 레벨 정책 11/11 |
| 새 DB로 백엔드 전체 테스트 | 701 passed / 2 failed(기존) / 55 skipped |
| 회귀 테스트 | `test_schema_coverage.py` — SQL이 쓰는 테이블 35개가 모두 마이그레이션에 있는지 검사(000을 빼면 12개 누락 검출) |

## 5. 공유 DB 적용 순서 (적용하지 않음)

공유 DB는 `000`·`026`이 이미 반영된 상태라 실행해도 변경이 없다(확인용으로 실행 가능).

1. `023_xp_award_policies.sql` — 공유 DB에 테이블은 이미 있음. 재실행하면 이번에 추가한 `CAREER_SPEC_PUBLIC` 행만 들어간다.
2. `024_member_board_visits.sql`
3. `025_level_policies.sql` — 정책 테이블 생성 + `member_levels` 레벨 상한 제약 완화
4. `027_xp_rule_policies.sql` — 023 적용 후 스킬 지급 정책 3개와 XP 지급 한도 3개를 추가한다.
5. (선택) 공유 DB에 빠진 기존 마이그레이션 확인: `003_remove_board_category`, `012_member_dm_default_on`, `022`의 `idx_notifications_comment`

## 6. 남은 항목

- 미연결: 모임 커리큘럼, 신청서 커리어 불러오기, 채용 인사이트, 스킬 세부·정확도, 공개 스펙 조회 화면.
- 시간대 위험(표시 안 됨): `recruit_members.joined_at/canceled_at`, `posts.deleted_at`(모임)을 서버 로컬 `datetime.now()`로 기록.
- 모임 게시글 `posts.created_at`이 ORM에서 NULL로 저장됨(기존 코드).
- 사용하지 않는 중복 파일 `frontend/src/components/admin/AdminUsagePanel (1).jsx`.
- ORM 정합성 개선(#186): DB에 없는 `members.public_anonymous_id`, `members.student_verification_status`, `members.verified_at` 매핑을 제거하고 컬럼 타입·NULL 제약을 정렬했다.
- ORM 매핑 예외: `posts.board_id`의 DB 외래키는 존재하지만 `boards` 테이블은 ORM에 매핑하지 않아 FK를 별도로 선언하지 않았다.
- 기존 `004_career_posts.sql`, `012_recruit_programs.sql`은 다시 실행하면 오류가 난다(IF NOT EXISTS 없음).
