# 운영 보안 가이드

## 1. 보안 구성

| 항목 | 적용 상태 |
|---|---|
| S3 Public Access Block | 적용 |
| CloudFront OAC | 적용 |
| Viewer HTTPS Redirect | 적용 |
| CloudFront Security Headers | 적용 |
| EC2 IMDSv2 Required | 적용 |
| EBS 암호화 | 적용 |
| IAM OIDC | 적용 |
| Parameter Store | 적용 |
| Session Cookie Secure | 적용 확인 |
| Session Cookie HttpOnly | 적용 확인 |
| Session Cookie SameSite | Lax |
| CORS Origin 제한 | 적용 |
| Origin Custom Header 검증 | 적용 |

## 2. IAM 및 접근 제어

### GitHub Actions

- 장기 AWS Access Key 대신 OIDC를 사용한다.
- main 브랜치에 해당하는 신뢰 조건을 제한한다.
- 프론트엔드와 백엔드의 IAM 역할을 분리한다.
- S3 업로드 및 CloudFront 무효화 권한을 제한한다.
- 프론트엔드 배포 역할에 S3 DeleteObject 권한을 부여하지 않는다.

### 운영 EC2

- Session Manager를 통한 서버 접근을 사용한다.
- FastAPI 포트를 인터넷에 직접 노출하지 않는다.
- Nginx 접근은 CloudFront Origin-facing 경로를 제한한다.
- 팀 서비스에 필요한 기존 접근 권한은 담당자와 협의하여 관리한다.

## 3. Parameter Store

운영 파라미터 경로:

    /playmate/prod/

| 분류 | 개수 |
|---|---|
| String | 11 |
| SecureString | 4 |
| 합계 | 15 |

SecureString 관리 대상:

- DB_USER
- DB_PASSWORD
- SESSION_SECRET_KEY
- DISCORD_CLIENT_SECRET

실제 값은 GitHub 또는 운영 문서에 저장하지 않는다.

## 4. 환경변수 파일

| 항목 | 설정 |
|---|---|
| 파일 | /etc/playmate/api.env |
| 소유자 | root:root |
| 권한 | 600 |
| 백업 경로 | /etc/playmate/backups |
| 동기화 | playmate-parameter-sync |

검증 명령어:

```bash
sudo /usr/local/bin/playmate-parameter-sync --check
sudo stat -c '%U:%G:%a' /etc/playmate/api.env
```

환경변수 원문을 출력하지 않는다.

## 5. Origin 및 인증 보안

- CloudFront에서 Origin 전용 헤더를 전달한다.
- Nginx는 보호 대상 경로의 헤더를 검증한다.
- 헤더가 없거나 일치하지 않으면 요청을 차단한다.
- 헬스체크용 공개 Nginx 경로는 별도로 관리한다.
- 운영 세션은 Secure, HttpOnly, SameSite=Lax를 적용한다.
- 회원 상태와 session_version을 DB에서 검증한다.
- 허용되지 않은 CORS Origin의 요청을 제한한다.

## 6. 남은 보안 과제

| 우선순위 | 작업 |
|---|---|
| 높음 | 노출 이력이 있는 Discord Webhook 교체 |
| 높음 | Origin 토큰의 세션 로그 노출 여부 확인 및 필요 시 재교체 |
| 높음 | CloudFront-Origin 구간 HTTPS 적용 |
| 중간 | SSM 배포 권한을 전용 문서로 제한 |
| 중간 | CSP 및 CSRF 보호 추가 검토 |
| 중간 | GitHub main 필수 CI 상태 검사 검토 |
| 중간 | 민감한 백업 파일의 보존 및 삭제 정책 확정 |

Origin 검증 헤더는 전송 구간 암호화를 대체하지 않는다.
비밀값이 포함된 로그나 스크린샷은 공유하지 않는다.
