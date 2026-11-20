# IT 채용 레이더 HTTP 요청 설정과 검증

## 범위와 기존 구조

실제 HTTP 요청은 `crawler/itchaeyong_crawler/crawler.py`의 `request()`가
`requests.Session.get()`으로 수행한다. `load_robots()`가 robots를 확인하고 `get()`은
정책 확인 후 공개 HTML을 요청한다. 목록/상세 파서·CSV·DB·통계 구조는 유지했다.
이 경로에 httpx/aiohttp/브라우저 자동화를 추가하지 않았다.

이전 설정은 CLI/환경변수로 받은 User-Agent, `Accept: text/html`, robots 전용
`Accept: text/plain`, 기본 타임아웃 20초와 최소 3초(기본 4초) 간격이었다.
기존 리다이렉트 비활성화·HTTP 오류 중단·DOM 기반 challenge 판정은 보존했다.

## 현재 기본 헤더

```http
User-Agent: PlaymateResearchBot/1.0 (PlayMate student project; public job postings; low rate)
Accept: text/html,application/xhtml+xml;q=0.9,*/*;q=0.8
Accept-Language: ko-KR,ko;q=0.9,en;q=0.5
```

robots.txt에는 `Accept: text/plain`만 요청 단위로 적용한다. Session의 HTML 기본값은 바꾸지 않는다.
`ITCHAEYONG_USER_AGENT` 또는 수집 CLI의 `--user-agent`로 운영자가 정직한 식별자를
명시할 수 있지만, 403을 피하려고 `TEST`/브라우저 식별자로 교체하거나 순환하지 않는다.
User-Agent에 연락처를 강제로 포함하지 않는다. 연락처는 아래 별도 From 설정을 사용할 수 있다.

| 헤더 | 적용 여부/이유 |
|---|---|
| From | 팀이 승인한 실제 이메일을 `ITCHAEYONG_CONTACT_EMAIL`로 명시했을 때만 추가. 기본 미포함 |
| If-None-Match | 검증된 캐시 본문과 서버의 ETag가 함께 존재할 때만 추가 |
| If-Modified-Since | 검증된 캐시 본문과 서버의 Last-Modified가 함께 존재할 때만 추가 |
| X-Request-ID | 미추가. 현재 URL·시각·순차 요청 기록으로 추적 가능하며 서버와 공유할 추적 체계가 없음 |
| Host, Connection, Accept-Encoding, Content-Length | requests/urllib3 자동 관리. 직접 구성하거나 덮어쓰지 않음 |
| Cache-Control | 요청 기본값 미추가. 강제 갱신/캐시 무시가 필요하지 않음. 응답의 no-store/private는 준수 |
| Referer | 미추가. 브라우저 탐색을 재현하지 않음 |
| Content-Type | GET 요청 본문이 없으므로 미추가 |
| Authorization, Cookie | 미추가. 기존에 정당하게 설정된 Session 정보는 임의 생성하지 않으며 진단 출력에서 마스킹 |
| Sec-Fetch-*, Sec-CH-UA | 브라우저 위장용 헤더 미추가 |

requests의 PreparedRequest에는 `Host`처럼 송신 계층에서 나중에 생성하는 헤더가 없을 수 있다.
dry-run 출력은 준비된 헤더이고 TCP/TLS 또는 HTTP/2 지문을 변경하는 기능이 아니다.

## 네트워크 정책

- Session 재사용, requests 어댑터의 자동 재시도 0, 연결/읽기 타임아웃 각각 10초.
  requests의 timeout은 전체 다운로드가 반드시 10초 안에 끝난다는 의미가 아니다.
- 이전 응답 완료부터 다음 요청까지 최소 4초. robots Crawl-delay/Request-rate가 더 길면 그 값을 따른다.
- HTTP 401/403/429 및 실제 챌린지에서 즉시 중단하고 같은 클라이언트의 후속 요청도 차단한다.
  429의 Retry-After는 보존하며 자동 대기 후 재시도하지 않는다. 500 등 다른 오류도 재시도 없이 중단한다.
- HTTPS `itchaeyong.com`의 robots와 허용된 `/jobs/` HTML 경로만 요청한다.
  `/api/`, `_rsc`, `.rsc`, 인증정보가 들어간 URL, 외부 도메인은 허용하지 않는다.
- 리다이렉트는 자동으로 따라가지 않는다. Location의 허용 여부를 기록하고 중단하므로
  허용되지 않은 도메인으로 후속 요청을 보내지 않는다.
- robots는 `text/plain`, HTML은 `text/html` 또는 `application/xhtml+xml` MIME을 확인한다.
- 기본 requests의 환경 프록시·TLS 인증서 설정은 유지한다. 프록시 회전, 인증 우회,
  TLS 검증 비활성화, 브라우저 사칭은 구현하지 않았다.

## 조건부 GET

같은 클라이언트 실행 안에서 최대 16개/총 본문 8MiB의 메모리 캐시를 유지한다.
robots의 유효한 정책 본문 또는 정상 판정된 채용 HTML만 캐시한다. 응답에 ETag나
Last-Modified가 없다면 캐시하지 않는다. URL과 요청 헤더별로 분리한다.

다음 요청은 서버의 검증자를 그대로 전달한다. 304이면 저장된 본문과 Content-Type을
재사용하고 다시 페이지 구조를 검사한다. 캐시 본문이 없는 304는 오류로 중단하며 추가
무조건 GET으로 재시도하지 않는다. 매번 요청 예산과 지연을 적용한다.
인증/쿠키/API 키 등 민감한 요청, Set-Cookie, Cache-Control: private/no-store,
Vary: * 응답은 저장하지 않는다. 요청 캐시는 CSV/보고서에 영속화하지 않는다.
서로 다른 URL을 한 번씩만 읽는 일반 수집이나 새 진단 프로세스에서는 캐시가 비어 있어
조건부 헤더가 나타나지 않는 것이 정상이다.

## 환경변수·로그

이 수집 경로는 `.env`를 자동 로드하지 않는다. 현재 셸의 `ITCHAEYONG_USER_AGENT`,
`ITCHAEYONG_CONTACT_EMAIL` 또는 기존 CLI 설정을 사용한다. DB 설정을 읽거나 연결하지 않는다.
From은 승인된 연락처를 운영자가 설정한 경우에만 사용하며 개행이 있는 값은 거부한다.

실제 응답이 있으면 응답의 PreparedRequest에서 송신 헤더를 얻어 기록한다.
Authorization/Proxy-Authorization/Cookie/API 키/토큰/From은 마스킹하며 User-Agent에
포함된 이메일도 마스킹한다. 네트워크 예외는 원문 URL·인증값 대신 예외 종류만 표시한다.
응답 시간, 상태, Content-Type, 캐시 재사용, 리다이렉트 및 DOM 판정은 `http_responses`에 기록한다.
기존 선택적 디버그 HTML 저장도 유지하며 이메일과 인증 문자열을 추가 마스킹한다.

## PowerShell 진단 명령

```powershell
Set-Location 'C:\Users\Playdata\Desktop\playmate\playmate'
uv sync --frozen --python 3.13
$env:PYTHONIOENCODING = 'utf-8'

# 기본 봇 식별자를 사용하려면 이전 임시 TEST 설정이 남아 있지 않은지 확인
# 다른 정직한 운영 식별자가 필요하면 운영자가 승인한 값을 명시
Remove-Item Env:ITCHAEYONG_USER_AGENT -ErrorAction SilentlyContinue

# 네트워크 요청 없음 (옵션 생략 시에도 dry-run)
uv run --frozen python scripts/inspect_crawler_headers.py --dry-run
uv run --frozen python scripts/inspect_crawler_headers.py --dry-run --url 'https://itchaeyong.com/jobs/dev'
```

승인된 연락처가 실제로 있을 때만 다음 환경변수를 설정한다. 설정값을 Git에 저장하지 않는다.

```powershell
$env:ITCHAEYONG_CONTACT_EMAIL = '팀에서승인한실제이메일'
```

**아래 live 명령은 사이트의 봇 접근 허용과 별도 네트워크 진단 승인을 받은 뒤에만 사용한다.**
이번 작업에서는 실행하지 않았다. `--live`만 있으면 요청 전에 거부한다.

```powershell
# robots.txt 한 번만 확인
uv run --frozen python scripts/inspect_crawler_headers.py --live --authorized

# robots 선확인 + 허용되는 경우에만 목록 GET 한 번 (최대 2요청)
uv run --frozen python scripts/inspect_crawler_headers.py `
  --live --authorized --url 'https://itchaeyong.com/jobs/dev'
```

스크립트는 URL, 준비된/실제 전송 헤더(마스킹), 상태, Content-Type, 응답 시간,
리다이렉트 여부와 오류 원인을 JSON으로 출력한다. 403/429에서 더 요청하지 않는다.
현재 헤더 변경은 403 해결을 의미하지 않는다. `PlaymateResearchBot`과 `TEST`의 상태 차이만으로
원인을 확정할 수 없으며 차단된 봇의 허용 여부는 운영자와 확인해야 한다.

## 테스트

```powershell
uv run --frozen --with pytest python -m pytest crawler/itchaeyong_crawler/test crawler/saramin_crawler/test -q
uv run --frozen python -m unittest backend.tests.test_career_insight_preview -q
```

작업 시작 시 기존 110개 테스트가 통과했고, HTTP 테스트 34개를 추가한 뒤
pytest 140개 + unittest 4개, 총 144개가 통과했다. 새 테스트의 live 경로도 send()를
모의 처리하므로 외부 네트워크 요청은 없다. dry-run 실행에서도 요청 0건을 확인했다.
CSV·DB·통계·DOM 판정 파일은 작업 전후 SHA256이 동일하다. 실제 사이트 접근, 403 해결,
운영 DB 접속/적재, 배포는 검증하거나 실행하지 않았다.

추가 개선 후보는 실행 간 캐시 영속화, 사이트 운영자와 합의한 식별자/연락처 관리,
실제 허용 환경에서의 단일 robots/목록 확인이다. 현재 범위에는 포함하지 않는다.
