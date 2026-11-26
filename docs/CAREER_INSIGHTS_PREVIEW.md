# 채용 인사이트 JSON 미리보기

`saramin_insights_preview.json`의 공개 채용공고를 서버에서 읽고, 중복을 제거한 집계만 화면에 전달합니다. DB 적재나 인증 정보는 필요하지 않습니다. 전체 Playmate 앱은 기존 인증·DB 환경 설정이 필요합니다.

## Windows PowerShell 실행

프로젝트 루트에서 두 터미널을 사용합니다.

```powershell
uv sync --link-mode copy
uv run uvicorn backend.app.career_insights_preview:app --host 127.0.0.1 --port 8000
```

```powershell
cd frontend
npm ci
$env:INSIGHTS_PREVIEW='1'
npm run dev
```

브라우저에서 `http://localhost:5173/insights-preview.html`을 엽니다. 이 페이지는 채용 인사이트 컴포넌트를 독립적으로 보여줍니다. 전체 앱의 취업 메뉴를 확인하려면 루트 `.env`에 기존 앱의 인증·DB 설정을 준비하고 `backend.app.main:app`을 실행한 뒤 `/career`에서 채용 인사이트를 선택합니다.

필터 항목은 실제 JSON에 있는 수집 분기, 분야, 기술명만 표시합니다. 분기·분야·기술 스택을 함께 고르면 AND 조건으로 집계합니다. 조회 실패 시 수치가 사라지고 오류 안내가 나타납니다. 한 분기만 수집된 경우 추세를 만들지 않습니다.

검증 명령:

```powershell
uv run python -m unittest backend.tests.test_career_insight_preview -v
uv run python -m unittest discover -s crawler/saramin_crawler/test -p test_tech_extraction.py -v
cd frontend
npm run build
```
