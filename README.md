# Bootcamp Community

부트캠프 수강생을 위한 통합 커뮤니티 웹 서비스 개발 프로젝트임.

게시판, 모임, 정보공유, 분실물, 자격증, 취업 등의 기능을 하나의 서비스에서 제공하는 것을 목표로 함.

Discord 계정을 기반으로 사용자를 인증하며 별도의 자체 회원가입은 제공하지 않음.

---

## 1. 프로젝트 소개

부트캠프 수강생들이 정보를 얻기 위해 여러 플랫폼을 따로 이용해야 하는 불편함을 줄이기 위해 개발하는 커뮤니티 서비스임.

일반적인 게시판 기능뿐만 아니라 맛집, IT 뉴스, 취업정보 등의 외부 데이터를 자동으로 수집하고,
AI 기능을 활용하여 사용자에게 필요한 정보를 보다 편리하게 제공하는 것을 목표로 함.

### 주요 목표

- 부트캠프 수강생 간 커뮤니케이션 공간 제공
- 스터디, 운동, 게임 등 모임 생성 및 참여 지원
- IT 뉴스 및 취업정보 자동 수집
- 학원 주변 맛집 정보 제공
- 학원별 분실물 정보 공유
- 자격증 일정 및 합격 후기 공유
- 취업 후기 및 채용정보 제공
- AI 기반 커뮤니티 기능 확장

---

## 2. 주요 카테고리

서비스는 총 6개의 메인 카테고리로 구성함.

| 카테고리 | 주요 기능 |
|---|---|
| 게시판 | 자유게시판 및 일반 커뮤니티 글 작성 |
| 모임 | 운동, 게임, 스터디, 공동구매 모임 |
| 정보공유 | IT 뉴스, 맛집 정보 등 |
| 자격증 | 자격증 일정 및 합격 후기 |
| 취업 | 취업정보, 채용공고, 취업 후기 |

### 게시판

자유롭게 글을 작성하고 다른 사용자와 소통하는 공간임.

### 모임

부트캠프 수강생끼리 다양한 모임을 만들고 참여할 수 있도록 구성함.

- 운동
- 게임
- 스터디
- 공동구매

### 정보공유

수강생에게 필요한 외부 정보를 제공함.

- IT 뉴스 자동 수집
- 학원 주변 맛집 정보
- 맛집 평점 및 리뷰 정보


### 자격증

IT 관련 자격증 일정과 합격 후기를 공유함.

### 취업

취업 준비에 필요한 정보를 제공함.

- 채용정보
- 취업 관련 정보
- 취업 후기

---

## 3. 로그인 및 사용자 관리

별도의 자체 회원가입 기능을 제공하지 않음.

Discord OAuth를 이용하여 로그인 및 사용자 인증을 처리함.

```text
Discord Login
      ↓
Discord OAuth
      ↓
Discord 사용자 정보 확인
      ↓
커뮤니티 사용자 정보 연동
      ↓
서비스 이용
```

Discord 사용자 ID를 기준으로 커뮤니티 활동 정보를 관리함.

---

## 4. 주요 기능

### Community

- 게시글 작성 / 수정 / 삭제
- 댓글 작성 / 수정 / 삭제
- 게시글 좋아요
- 게시글 조회
- 카테고리별 게시글 조회
- BEST 게시글 조회

### Group

- 운동 모임
- 게임 모임
- 스터디 모집
- 공동구매 모집

### Information

- IT 뉴스 자동 수집
- 맛집 정보 수집
- 맛집 평점 및 리뷰 제공

### Lost Item

- 분실물 등록
- 분실물 조회
- 학원 지점별 조회

### Certificate

- 자격증 정보
- 자격증 일정
- 합격 후기

### Employment

- 취업정보
- 채용공고
- 취업 후기

---

## 5. AI

커뮤니티 서비스에 적용할 AI 기능을 별도 영역으로 개발함.

```text
AI
├─ Machine Learning
├─ Deep Learning
├─ LLM
└─ Fine-tuning
```

### ML

머신러닝을 활용한 분류, 추천 등의 기능을 개발함.

### DL

이미지 및 텍스트 기반 딥러닝 기능을 개발함.

### LLM

LLM을 활용한 챗봇, 요약, RAG 등의 기능을 개발함.

### Fine-tuning

커뮤니티 목적에 맞는 LLM 파인튜닝을 실험하고 적용함.

AI 기능은 프로젝트 진행 상황에 따라 단계적으로 적용할 예정임.

---

## 6. 데이터 수집

일부 정보는 크롤링을 통해 자동으로 수집함.

### 맛집

학원 주변 맛집 데이터를 수집함.

수집 대상 예시는 다음과 같음.

- 매장명
- 카테고리
- 주소
- 위치
- 평점
- 리뷰
- 도보 정보

### IT News

IT 관련 최신 뉴스 및 정보를 수집함.

### Jobs

취업 및 채용 관련 정보를 수집함.

---

## 7. 기술 스택

### Frontend

- React
- JavaScript
- HTML
- CSS

### Backend

- FastAPI
- Python

### Database

- MySQL

### Authentication

- Discord OAuth

### Data Collection

- Python
- Web Crawling
- Kakao Map 기반 맛집 데이터 수집

### AI

- Machine Learning
- Deep Learning
- LLM
- RAG
- Fine-tuning

### Collaboration

- Git
- GitHub

---

## 8. 프로젝트 구조

```text
bootcamp_community/
│
├─ ai/
│  ├─ ml/
│  ├─ dl/
│  ├─ llm/
│  ├─ fine_tuning/
│  └─ README.md
│
├─ backend/
│  ├─ app/
│  │  ├─ routers/
│  │  ├─ models/
│  │  ├─ schemas/
│  │  ├─ services/
│  │  └─ core/
│  └─ README.md
│
├─ crawler/
│  ├─ restaurant/
│  ├─ it_news/
│  ├─ jobs/
│  ├─ data/
│  └─ README.md
│
├─ database/
│  ├─ sql/
│  ├─ scripts/
│  └─ README.md
│
├─ docs/
│  ├─ design/
│  ├─ qa/
│  ├─ deliverables/
│  └─ README.md
│
├─ frontend/
│  ├─ public/
│  ├─ src/
│  │  ├─ components/
│  │  ├─ pages/
│  │  ├─ services/
│  │  └─ assets/
│  └─ README.md
│
├─ .gitignore
└─ README.md
```

각 메인 폴더의 자세한 구조 및 역할은 해당 폴더 내부의 `README.md`에서 확인할 수 있음.

---

## 9. 시스템 구성

```text
              ┌─────────────────┐
              │     Discord     │
              │      OAuth      │
              └────────┬────────┘
                       │
                       ▼
┌─────────────┐   ┌─────────────┐
│    React    │ → │   FastAPI   │
│  Frontend   │ ← │   Backend   │
└─────────────┘   └──────┬──────┘
                         │
                  ┌──────▼──────┐
                  │    MySQL    │
                  │  Database   │
                  └─────────────┘
                         ▲
                         │
                 ┌───────┴───────┐
                 │    Crawler    │
                 ├───────────────┤
                 │ Restaurant    │
                 │ IT News       │
                 │ Jobs          │
                 └───────────────┘
```

필요에 따라 AI 서비스와 Backend를 연동하는 구조로 확장함.

---

## 10. 문서 관리

프로젝트 관련 문서는 `docs/`에서 관리함.

```text
docs/
├─ design/        # 설계 문서
├─ qa/            # 검수 및 테스트 문서
└─ deliverables/  # 보고서 및 최종 제출 자료
```

### Design

다음과 같은 프로젝트 설계 자료를 관리함.

- 요구사항 정의서
- ERD
- 테이블 정의서
- API 명세서
- 화면 설계서
- 시스템 구성도

### QA

다음과 같은 검수 자료를 관리함.

- 기능 테스트
- 검수 체크리스트
- 버그 목록
- 수정 내역

### Deliverables

다음과 같은 프로젝트 산출물을 관리함.

- 프로젝트 계획서
- 중간 보고서
- 최종 보고서
- 발표자료
- 발표대본

---

## 11. 개발 규칙

### Branch

기본적으로 다음 브랜치를 기준으로 개발함.

```text
main
develop
feature/*
```

- `main` : 최종 배포 및 안정 버전 관리
- `develop` : 개발 내용 통합
- `feature/*` : 기능별 개발

예시는 다음과 같음.

```text
feature/login
feature/board
feature/crawler
feature/restaurant
feature/lost-item
```

### Commit

작업 내용을 확인할 수 있도록 명확한 Commit Message 작성을 권장함.

예시는 다음과 같음.

```text
feat: 게시글 작성 API 구현
fix: Discord 로그인 오류 수정
docs: ERD 수정
refactor: 게시글 서비스 로직 분리
chore: 프로젝트 환경설정 수정
```

---

## 12. 개발 진행 상태

현재 프로젝트 개발 진행 중임.

- 요구사항 정의
- 화면 설계
- ERD 설계
- Database 구축
- 맛집 데이터 수집
- Backend 개발
- Frontend 개발
- AI 기능 개발
- 기능 통합
- QA
- 최종 배포

각 기능은 개발 진행 상황에 따라 지속적으로 수정 및 추가함.