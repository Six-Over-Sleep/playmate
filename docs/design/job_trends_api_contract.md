# 2026-10-26 구현 예정 API 계약 (Phase 1에서는 미구현)

이 문서는 제안 계약이다. 기존 프론트엔드와 합의한 확정 응답이라고 주장하지 않는다.
실제 router, service 집계 SQL, 앱 등록 및 프론트엔드 변경은 이번 작업에 포함하지 않는다.
기존 응답 관례처럼 성공 시 JSON 객체, 오류 시 FastAPI detail 형식을 사용한다.

## 공통 규칙

시간/분기 기준 Asia/Seoul. quarter는 YYYY-Q[1-4]. field/role은 내부 코드다.
잘못된 값, 존재하지 않는 코드, field와 role의 소속 불일치는 422/detail.
미지정 field/role은 전체. role만 주어지면 해당 role만 필터링한다.
유효한 분기에 데이터가 없으면 count 0과 빈 순위 배열을 반환한다.
이전 분기 데이터 자체가 없으면 previous_count=null이며 증감률도 null이다.
이전 분기 공고 수 0에서도 증감률은 null, status=zero_baseline이다.

source=mock|saramin 필터를 추가한다. 서버 설정 기본 source 하나만 사용한다.
절대 두 source를 합산하지 않는다. 모든 응답에 source/is_mock/notice를 넣는다.
mock notice는 '가상 시연 데이터이며 실제 채용 통계가 아닙니다.'이다.
saramin 표시는 실제 수집 데이터에만 사용한다. 과거 분기 수집 가능성을 보장하지 않는다.

## GET /api/job-trends/filters

source별 실제 적재된 분기만 오름차순 반환한다. fields는 8개이며 소속 roles는 30개다.

```json
{
  "source": "mock",
  "is_mock": true,
  "notice": "가상 시연 데이터이며 실제 채용 통계가 아닙니다.",
  "quarters": ["2025-Q1", "2025-Q2", "2025-Q3", "2025-Q4", "2026-Q1", "2026-Q2", "2026-Q3"],
  "fields": [{"code": "data_ai", "name": "데이터·AI", "roles": [{"code": "data_analyst", "name": "데이터 분석가"}]}]
}
```

fields/roles의 예제는 축약이며 구현은 전체 시드 목록을 반환한다.

## GET /api/job-trends/dashboard

query: quarter 필수, field/role 선택, source 선택, classification=primary|multi(기본 multi).
quarter=2026-Q3&field=data_ai&role=ai_agent_developer 예제를 지원한다.
필터 role/field 조건은 대표/다중 정책에 따라 EXISTS로 검사하고 공고를 한 번만 센다.
title만으로 자동 분류한 데이터에는 대표 직무가 없으므로 primary 결과가 0일 수 있다.
현재 분기 선택 필터를 이전 분기 및 시계열에도 똑같이 적용한다.
분야/직무 breakdown은 선택 필터를 통과한 공고 집합 내에서 계산한다.

```json
{
  "source": "mock", "is_mock": true,
  "notice": "가상 시연 데이터이며 실제 채용 통계가 아닙니다.",
  "quarter": "2026-Q3", "field": null, "role": null,
  "classification": "multi",
  "posting_count": 84,
  "previous_quarter": "2026-Q2", "previous_count": 77,
  "change_percent": 9.09, "change_status": "available",
  "field_counts": [], "role_counts": [], "quarter_counts": [],
  "skill_ranking": [], "certification_ranking": [],
  "keyword_analysis_status": "sample_dictionary",
  "salary": {"average_manwon": null, "disclosed_sample_count": 0, "status": "unavailable", "reason": "검증된 연봉 수치 변환 미지원"},
  "requirements": {"status": "unavailable", "reason": "공식 API 전문 미제공", "items": null},
  "preferences": {"status": "unavailable", "reason": "공식 API 전문 미제공", "items": null}
}
```

이 숫자는 목업 전체 생성 목표를 사용한 계약 예제이며 DB 실행 결과가 아니다.
평균 급여는 검증된 수치만 사용하며 구간 중간값/결측 0 대체는 금지한다.
disclosed_sample_count는 평균 계산에 사용 가능한 표본 수로 정의한다.
사전 미완성 상태에서 빈 자격증 순위는 시장에 자격증 수요가 없다는 뜻이 아니다.

breakdown 항목은 {code,name,count}, 시계열은 {quarter,count},
순위는 {keyword_code,keyword_name,count,rank} 형태다.
순위는 COUNT(DISTINCT posting_id), count 내림차순 및 code 오름차순, 최대 10개,
동률 rank는 DENSE_RANK를 사용한다. 동일 표준어의 title/api_keyword 중복은 한 번만 센다.
전체는 source_job_id DISTINCT, 분야별은 같은 분야의 복수 직무를 한 번만 센다.
multi 직무별 합은 전체보다 클 수 있다. primary는 is_primary=true만 사용한다.
미분류 공고도 전체에 포함하고 필터 없는 breakdown에는 code=unclassified 항목을 제공한다.
분야별 다중 분류 합도 교차 분야 공고 때문에 전체를 초과할 수 있다.
과거 분기에 현재 active=0인 공고도 포함한다. active 필터로 과거 시계열을 누락시키지 않는다.

## 10월 26일 우선순위

1. 전용 PostgreSQL에서 Phase 1 통합 테스트를 먼저 실행하고 스키마/UPSERT/FK 검증을 완료한다.
2. 프론트엔드 담당자와 source·분류 정책·결측·응답 필드 계약을 확정한다.
3. filters 조회 repository/service/schema/router를 기존 계층에 추가한다.
4. 서울 분기 경계와 동일 필터의 전분기·DISTINCT 집계 SQL을 구현한다.
5. dashboard serializer와 422/빈 표본/급여 unavailable를 구현한다.
6. 다중 분류 중복·분기 경계·source 분리·전분기 0·기존 인증/게시판 회귀 테스트를 실행한다.
7. 승인된 API 실제 응답을 확보한 뒤 동일 파서에 넣어 차이만 보정한다.
   과거 조회·호출 제한·재시도/수집 주기는 승인 후 별도로 확정한다.
