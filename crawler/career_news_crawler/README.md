# Career News Crawler (취업 분야별 뉴스 수집기)

업로드한 `it_news_crawler.zip`을 바탕으로, **Google News RSS → 분야별 필터링 → SQLite 저장 → HTML/JSON API 조회** 구조를 유지한 버전입니다.

## 파일별 역할

| 파일 | 역할 |
|---|---|
| `config.py` | 분야 이름, 구글 뉴스 검색어, 제목 필터 키워드 관리 |
| `main.py` | 모든 분야의 RSS를 호출하고, 성공한 분야의 뉴스만 DB 갱신 |
| `src/rss_collector.py` | RSS 읽기, 제목/언론사/날짜 추출, 기본 관련성 검사 |
| `src/database.py` | `data/career_news.db` 생성, 분야별 뉴스 저장·조회 |
| `app.py` | Flask HTML 화면 및 `GET /api/news` JSON API |
| `templates/index.html` | 분야별 뉴스 목록과 탭 화면 |

## 제공 분야 — 기존 취업 대시보드와 이름·코드 통일

`job_trends_catalog.py`의 `FIELDS` 8개 분류를 그대로 사용합니다.

| 분야명 | 코드 |
|---|---|
| 데이터·AI | `data_ai` |
| 백엔드·서버 | `backend` |
| 프론트엔드·웹 | `frontend` |
| 모바일 개발 | `mobile` |
| 클라우드·인프라 | `cloud_infra` |
| 정보보안 | `security` |
| QA·테스트 | `qa_test` |
| IT기획·디자인 | `it_product` |

`config.py`에서 분야마다 `queries`와 `title_keywords`를 변경할 수 있습니다.

```python
"데이터·AI": {
    "code": "data_ai",
    "queries": ["인공지능 산업", "생성형 AI 기술", "데이터 분석 산업"],
    "title_keywords": ["인공지능", "AI", "LLM", "데이터 분석"],
},
```

`queries`는 **기사 검색**에 사용하고, `title_keywords`는 **해당 분야와 관련 있는 기사인지 검사**하는 데 사용합니다. 제목에 키워드가 있는 간단한 규칙 기반 필터여서 완벽한 분류는 아닙니다.

## 실행 방법 (Windows PowerShell)

```powershell
cd career_news_crawler
uv sync
uv run python main.py
uv run python app.py
```

또는 패키지를 먼저 설치한 경우:

```powershell
python -m pip install -e .
python main.py --days 7
python app.py
```

브라우저에서 `http://127.0.0.1:5000`에 접속하세요. 단순 HTML 화면은 **수집 결과를 조회**하는 곳이고, `main.py`는 **새로 수집해서 DB에 저장**하는 명령입니다.

> 인터넷이 필요합니다. 실행 환경에서 Google News RSS에 접근할 수 있어야 실제 데이터가 수집됩니다.

## API

```http
GET http://127.0.0.1:5000/api/news?category=데이터·AI&limit=20
```

응답 예시 (가상 데이터):

```json
{
  "category": "데이터·AI",
  "count": 1,
  "news": [
    {
      "news_id": 1,
      "category": "데이터·AI",
      "field_code": "data_ai",
      "title": "예시: AI 산업 투자 증가",
      "source": "예시신문",
      "link": "https://example.com/article",
      "published": "2026-10-29T00:00:00+00:00",
      "collected_at": "2026-10-29 00:00:00"
    }
  ]
}
```

React·FastAPI 대시보드에 붙일 때는 Flask API를 임시 조회용으로 사용하거나, `news` 테이블 접근 로직을 기존 FastAPI 라우터로 옮겨 통합할 수 있습니다. **이 ZIP은 기존 PostgreSQL DB/대시보드에 자동 연결되지 않습니다.** 서로 다른 개발 서버에서 호출하려면 CORS/프록시도 설정해야 합니다.

## 수집 동작과 데이터 보호

1. 카테고리별 Google News RSS 검색을 수행합니다.
2. 제목에서 취업 분야 관련 키워드를 확인하고 최근 `--days`일 자료만 남깁니다.
3. 성공적으로 1건 이상 모인 분야만 DB에서 결과를 교체합니다.
4. RSS 실패 또는 수집 결과가 없는 분야는 기존 데이터를 보존합니다.
5. 동일 카테고리 내 동일 제목·출처는 중복 저장하지 않습니다. 동일 기사가 서로 다른 분야에 보이는 것은 허용합니다.

기본 14일, 검색어별 최대 30건을 대상으로 합니다. `--days 7`처럼 기간을 조절할 수 있습니다. 검색 결과·시각은 Google RSS 제공 상황에 따라 달라집니다. 기사의 상세 본문은 수집하지 않습니다.

기존 IT 프로젝트의 `data/news.db`를 복사하지 않고 **새 `data/career_news.db`에 저장**하므로 원본 DB를 덮어쓰지 않습니다.

## 자동 실행

원본과 마찬가지로 Windows 작업 스케줄러에서 `uv run python main.py`를 3시간마다 실행하도록 설정할 수 있습니다. 각 실행은 1회만 수집하고 종료합니다.

## 점검

```powershell
python -m unittest discover -s tests -v
```

이 테스트는 네트워크 연결 없이 제목 필터·SQLite 저장 동작을 확인합니다. 실제 Google News RSS 수집 테스트는 인터넷 환경에서 `python main.py`로 확인해야 합니다.

## 주의 사항

- 검색·분류 결과는 **산업 뉴스 요약 리스트**이며 실제 채용공고 DB와 다릅니다.
- 뉴스 헤드라인만으로 기업 실적·채용규모를 확정하지 마세요.
- 뉴스 전문이나 이미지 대신 제목·출처·원문 URL·발행일만 저장합니다. 원문 및 RSS 제공 조건을 확인하세요.
