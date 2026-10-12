# services | DB 처리 로직

## 파일
`recruit.py`의 `create_recruit(db, data)`가 게시글과 모임, 카테고리별 상세 행을 한 트랜잭션으로 저장함.

## 생성 순서
1. `posts` INSERT 후 `db.flush()`로 `post_id` 확보함.
2. `recruits` INSERT 후 `db.flush()`로 `recruit_id` 확보함.
3. category에 해당하는 상세 테이블 INSERT함.
4. 모두 성공하면 `db.commit()`; 오류 시 `db.rollback()`함.

## 상세 테이블
`sports` → `recruit_sports_details`, `game` → `recruit_game_details`, `study` → `recruit_study_details`, `group_buy` → `recruit_group_buy_details`.

현재 작성자 ID는 임시 `-1`이므로 운영 전 인증 연동 필수임.
