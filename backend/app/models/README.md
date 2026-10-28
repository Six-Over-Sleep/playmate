# models | SQLAlchemy ORM

## 파일별 역할

| 파일 | 모델/테이블 | 주요 역할 |
|---|---|---|
| `member.py` | `Member` → `members` | 회원 정보, 권한, 계정 상태 및 Discord DM 수신 동의 관리 |
| `post.py` | `Post` → `posts` | 게시글 제목, 본문, 작성자 및 게시 상태 관리 |
| `recruit.py` | `Recruit`, `RecruitMember`, 4가지 상세 모델 → 모임 관련 6개 테이블 | 모임 모집 정보, 참여자 및 카테고리별 상세 정보 관리 |
| `notification.py` | `Notification` → `notifications` | 댓글, 답글, 반응에 따른 Discord DM 알림 및 전송 상태 관리 |

## ORM이란?

ORM(Object-Relational Mapping)은 DB 테이블을 Python 클래스와 연결하여 데이터를 객체 형태로 다루는 기술임.

SQLAlchemy ORM을 사용하면 SQL을 직접 작성하지 않고 데이터를 조회하거나 저장할 수 있음.

**예시**
```python
db.query(Recruit).all()
```

위 코드는 `recruits` 테이블의 데이터를 조회함.

각 모델의 `__tablename__`은 연결할 DB 테이블 이름을 지정함.

## 키 관계

- `posts.author_member_id` → `members.member_id`
- `recruits.post_id` → `posts.post_id`
- `recruit_members.recruit_id` → `recruits.recruit_id`
- `recruit_members.member_id` → `members.member_id`
- `notifications.receiver_member_id` → `members.member_id`
- `notifications.actor_member_id` → `members.member_id`
- `notifications.post_id` → `posts.post_id`
- `notifications.comment_id` → `comments.comment_id`

`recruit_members`는 `(recruit_id, member_id)`를 복합 PK로 사용함.

모임 상세 테이블 4개는 `recruit_id`를 PK이자 FK로 사용하여 `recruits`와 1:1 관계를 구성함.

## Notification 모델

Discord 개인 DM 알림 내역과 전송 상태를 관리하는 모델임.

**알림 유형**

| 유형 | 설명 |
|---|---|
| `COMMENT` | 게시글 댓글 알림 |
| `REPLY` | 댓글 답글 알림 |
| `REACTION` | 게시글 또는 댓글 반응 알림 |

**전송 상태**

| 상태 | 설명 |
|---|---|
| `PENDING` | 알림 전송 대기 |
| `SENT` | 알림 전송 완료 |
| `SKIPPED` | 알림 전송 생략 |
| `FAILED` | 알림 전송 실패 |

알림을 받을 회원은 `receiver_member_id`, 행동한 회원은 `actor_member_id`로 구분함.

Discord DM 수신 동의 여부는 `members.external_dm_opt_in` 컬럼을 사용함.

전송 실패 시 `error_message`, `retry_count`, `last_attempt_at`을 통해 오류 및 재시도 정보를 관리함.

## 주의사항

- 모델 import가 누락되면 FK 참조 과정에서 `NoReferencedTableError`가 발생할 수 있음.
- FK로 연결된 모델은 동일한 `Base`의 메타데이터에 등록되어야 함.
- `notifications.comment_id`가 참조하는 `comments` 테이블도 메타데이터에 등록되어 있어야 함.
- ORM 클래스가 존재한다고 실제 DB 테이블이 자동으로 생성되는 것은 아님.
- 모델 변경 후 실제 PostgreSQL 테이블 구조와 일치하는지 확인해야 함.
- Discord DM은 기본 ON임. `external_dm_opt_in`이 `False`(회원이 `/알림설정`으로 끔)인 회원에게만 보내지 않음.
  `NULL`(선택 안 함)은 ON으로 처리하고, 신규 가입은 `True`로 저장함.
