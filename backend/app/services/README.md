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

작성자·참여자 ID는 Router가 로그인 세션에서 꺼내 전달함. `join_recruit`의 `member_id=-1` 기본값은 Service를 직접 호출하는 테스트용이며, 웹 API에서는 사용하지 않음.
