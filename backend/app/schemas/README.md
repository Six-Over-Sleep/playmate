# schemas | Pydantic 요청/응답 자료형

## 파일
- `recruit.py`: `RecruitCreate`(생성 입력), `RecruitUpdate`(수정 입력), `RecruitResponse`(응답용 초안) 정의함.

## 주요 입력
`title`, `body`, `recruit_mode`, `category`, `capacity`, 날짜·장소·연락방법을 입력함. `capacity`는 0보다 커야 함.

## 카테고리별 상세 입력
| category | 속성 |
|---|---|
| sports | `sport_name` |
| game | `game_name` |
| study | `study_topic`, `study_period`, `study_method` |
| group_buy | `product_name`, `purchase_url`, `estimated_price_per_person`, `pickup_method` |

현재 상세 속성은 선택 입력임. 카테고리별 필수값 검사는 후속 작업임. `RecruitResponse`는 정의되어 있어도 라우터가 자동 적용되는 것은 아님.
