# models | SQLAlchemy ORM

## 파일별 역할
| 파일 | 모델/테이블 |
|---|---|
| `member.py` | `Member` → `members` |
| `post.py` | `Post` → `posts` |
| `recruit.py` | `Recruit`, `RecruitMember`, 4가지 상세 모델 → 모임 관련 6개 테이블 |

## ORM이란?
DB 행을 Python 객체로 다루기 위한 매핑임. 예를 들어 `db.query(Recruit).all()`로 `recruits`의 행을 조회함.

## 키 관계
`posts.author_member_id → members.member_id`, `recruits.post_id → posts.post_id`, `recruit_members`는 `(recruit_id, member_id)` 복합 PK임. 상세 테이블은 `recruit_id`를 PK 및 FK로 사용함.

**주의:** 모델 import가 누락되면 `NoReferencedTableError`가 발생할 수 있음. 관련 모델을 같은 Base에 등록해야 함. ORM 클래스가 존재한다고 DB가 자동으로 만들어지는 것은 아님.
