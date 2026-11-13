# models | SQLAlchemy ORM 모델

실제 PostgreSQL 테이블에 대응하는 SQLAlchemy 모델을 정의합니다. **ORM 클래스가 존재한다고 테이블이 자동으로 생성되거나 마이그레이션이 적용되는 것은 아닙니다.**

## 파일별 모델

| 파일 | 테이블·대상 |
|---|---|
| `member.py` | `members`: 회원, Discord ID, 상태, DM 설정 등 |
| `post.py` | `posts`: 게시글 |
| `comment.py` | `comments`: 댓글·답글 |
| `post_like.py` | `post_likes`: 게시글 좋아요 |
| `post_scrap.py` | `post_scraps`: 스크랩 |
| `notification.py` | `notifications`: Discord DM 알림 대기/이력 |
| `recruit.py` | `recruits`, `recruit_members` 및 운동·게임·스터디·공동구매 상세 테이블 |
| `recruit_program.py` | `recruit_programs`, `recruit_applications`, `recruit_eligibility`, `recruit_withdrawals`, `recruit_curricula`, `recruit_activities`, `recruit_recognitions`, `recruit_outbox`, `recruit_program_commands`, `recruit_skills` |

게시판·취업·관리자 기능의 일부 데이터 접근은 SQLAlchemy 모델 대신 **repositories의 직접 SQL**을 사용하므로 이 파일 목록이 DB 전체 테이블 목록을 의미하지는 않습니다.

## 주요 관계

```text
members ── posts ── comments
   │         │
   │         ├── post_likes
   │         ├── post_scraps
   │         └── recruits ── recruit_members
   │                          ├── 카테고리별 상세
   │                          └── 프로그램/신청/커리큘럼/활동
   └── notifications (수신자/행동자)
```

**DB 구조의 최종 기준은 실제 PostgreSQL 스키마와 `database/sql/` 적용 이력**입니다. `recruit_id`, `post_id`, `member_id` 간 FK 및 제약조건은 수정 전 DB에서 확인합니다.

## 데이터 정책 메모

- 회원 탈퇴에는 `members.member_status` 컬럼이 필요합니다. 관련 SQL: `020_member_withdrawal.sql`.
- 익명 게시글·댓글은 **작성자 식별 및 화면 표시 정책을 분리**합니다. DB 소유권을 익명 표시 문자열로 대체하지 않습니다.
- 알림은 `PENDING`, `SENT`, `SKIPPED`, `FAILED` 상태를 다룹니다. Bot/Backend가 공유하는 스키마 변경 시 양쪽을 함께 수정합니다.
- `recruit_program.py` 사용은 신규 모임 마이그레이션 및 기능 설정에 영향을 받습니다.

## 변경 순서

1. 적용 대상 DB/ERD와 실제 컬럼을 확인합니다.
2. 필요한 SQL 마이그레이션을 작성합니다.
3. ORM·repository·schema·service 및 테스트를 수정합니다.
4. 격리 테스트 DB에서 검증한 뒤 팀 합의하에 공유 DB에 반영합니다.

참고: [DB 가이드](../../../database/README.md)
