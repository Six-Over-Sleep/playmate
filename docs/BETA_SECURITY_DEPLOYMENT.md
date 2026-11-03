# 베타 운영 배포 보안 전제조건 (#82)

베타 서버를 열기 전에 아래 항목을 배포 담당자가 직접 확인한다.
코드는 `APP_ENV` 값 하나로 개발/운영 동작을 나누므로, **운영 서버의 `APP_ENV` 설정이 가장 중요하다.**

## 1. `APP_ENV`에 따른 동작

| 항목 | `development`·`test` | 그 외 모든 값·미설정(운영) |
|---|---|---|
| 세션 쿠키 `Secure` | 꺼짐(로컬 HTTP 로그인 가능) | **켜짐(HTTPS에서만 쿠키 전송)** |
| 세션 쿠키 `HttpOnly`·`SameSite=Lax` | 켜짐 | 켜짐 |
| `X-Dev-Member-ID` 개발용 헤더 | 세션이 없을 때만 허용 | **무시(401)** |
| `/docs`, `/redoc`, `/openapi.json` | 제공 | **404** |
| `/health/db` 응답 | `{"status": "ok"}` | `{"status": "ok"}` |
| 서버 내부 `RuntimeError` 응답 | 고정 문구 503 | 고정 문구 503 |

- 운영 서버는 `APP_ENV=production`을 명시한다. 로컬 `.env`를 그대로 복사하면 `development`가 되어
  **누구나 `X-Dev-Member-ID` 헤더로 다른 회원(관리자 포함)으로 위장할 수 있다.**
- 오타·`prod`·`staging` 같은 값은 모두 운영으로 처리된다(안전한 기본값).

## 2. HTTPS 전제조건

운영에서는 세션 쿠키에 `Secure`가 붙으므로 **HTTPS가 아니면 로그인이 유지되지 않는다.**

- [ ] 사용자가 접속하는 프론트 주소와 API 주소가 모두 `https://`이다.
- [ ] 리버스 프록시(또는 호스팅 서비스)에서 `http://` 요청을 `https://`로 리다이렉트한다.
      리다이렉트·HSTS는 실제 프록시 구성을 확정한 뒤 프록시에서 설정한다(앱 코드에는 추가하지 않았다).
- [ ] `DISCORD_REDIRECT_URI`가 `https://<운영 도메인>/auth/discord/callback`이며 Discord 개발자 포털에도 같은 값이 등록되어 있다.
- [ ] `FRONTEND_URL`이 운영 프론트 `https://` 주소이다(미설정 시 `http://localhost:5173`으로 이동한다).
- [ ] `FRONTEND_ORIGINS`에는 운영 프론트 `https://` origin만 쉼표로 적는다. **`*`는 절대 사용하지 않는다**
      (쿠키 인증과 함께 쓰면 모든 사이트가 로그인 사용자 권한으로 API 응답을 읽을 수 있다).
- [ ] 프록시가 TLS를 종료하고 앱에는 HTTP로 전달하는 구조여도 쿠키 `Secure` 동작에는 문제가 없다
      (브라우저↔프록시 구간이 HTTPS이면 된다).

## 3. 비밀값·빌드 환경

- [ ] 운영용 `SESSION_SECRET_KEY`는 로컬과 다른 새 값을 사용한다(32자 이상 무작위).
- [ ] 프론트 운영 빌드 환경에는 `VITE_DEV_MEMBER_ID`를 두지 않는다.
      `VITE_` 값은 모두 공개 JS 번들에 포함되므로 토큰·비밀번호를 넣지 않는다.
- [ ] 공용 DB는 신뢰 IP(허용 목록)에서만 접속되도록 설정한다.

## 4. 배포 직후 확인 (운영 주소에서)

```bash
# 개발용 헤더만으로는 인증되지 않아야 한다 → 401
curl -s -o /dev/null -w "%{http_code}\n" -H "X-Dev-Member-ID: 1" https://<운영 API>/api/boards
# API 문서는 비공개 → 404
curl -s -o /dev/null -w "%{http_code}\n" https://<운영 API>/docs
# DB 상태는 내부 정보 없이 {"status":"ok"}
curl -s https://<운영 API>/health/db
# 로그인 시작 응답의 쿠키에 Secure; HttpOnly; SameSite=Lax 포함
curl -s -D - -o /dev/null https://<운영 API>/auth/discord/login | grep -i set-cookie
```

## 5. 아직 남은 위험 (별도 이슈)

- Legacy 모임 PATCH/DELETE 작성자 권한 검사 없음(Critical, 모임 담당자와 협의 후 진행)
- CSRF는 `SameSite=Lax`에만 의존(Origin 검사 미들웨어 미도입)
- 세션 14일 유지·로그아웃 시 서버 측 무효화 없음
- `/health/db`는 인증 없이 DB 연결을 사용(요청 제한은 프록시에서 검토)
- 업로드 요청 크기 제한·이미지 메타데이터 제거·`nosniff` 헤더 미적용
