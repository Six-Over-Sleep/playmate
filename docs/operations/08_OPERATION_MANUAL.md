# PLAYMATE 운영자 매뉴얼

## 1. 실행 환경 구분

| 실행 환경 | 용도 |
|---|---|
| PC PowerShell | Git 및 로컬 개발 |
| AWS CloudShell | AWS 리소스 조회 및 관리 |
| EC2 Session Manager | 서버 내부 서비스 관리 |
| Browser Console | 웹 요청 검증 |

서버 내부 systemctl 명령어는 EC2에서 실행한다.

## 2. EC2 접속

AWS Console - EC2 - Instances -
playmate-api-prod - Connect - Session Manager

접속 확인:

```bash
hostname
ps -p 1 -o comm=
```

## 3. 운영 상태 확인

```bash
free -h
df -h /
uptime
swapon --show
vmstat 1 5
```

## 4. 서비스 확인

```bash
systemctl status nginx --no-pager
systemctl status playmate-api --no-pager
systemctl status postgresql --no-pager
systemctl --failed --no-pager
```

로그 확인:

```bash
sudo journalctl -u playmate-api -n 100 --no-pager
sudo journalctl -u nginx -n 100 --no-pager
```

로그 공유 전 비밀값이나 개인정보 포함 여부를 확인한다.

## 5. API 헬스체크

```bash
/usr/local/bin/playmate-healthcheck
```

정상 결과:

    PASS: /health
    PASS: /health/db
    PASS: /health/schema

## 6. 외부 접속 확인

```bash
BASE="https://d6oimxkex2dki.cloudfront.net"

curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/"
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/_nginx_health"
```

## 7. 서비스 장애 대응

1. Discord 경보 이름 및 발생 시각을 확인한다.
2. CloudWatch 지표와 경보 상태를 확인한다.
3. EC2 및 서비스 로그를 확인한다.
4. API, DB, Schema 헬스체크를 수행한다.
5. 최근 배포 여부 및 Git SHA를 확인한다.
6. 장애 원인에 적합한 복구 절차를 수행한다.
7. 복구 후 헬스체크와 실제 웹 기능을 확인한다.
8. 장애 원인, 대응 내역, 재발 방지 사항을 기록한다.

## 8. API 재시작

재시작은 운영 요청에 영향을 줄 수 있으므로
장애 원인을 확인하고 담당자와 협의하여 수행한다.

```bash
sudo /usr/local/bin/playmate-restart
/usr/local/bin/playmate-healthcheck
```

## 9. 환경변수 확인

```bash
sudo /usr/local/bin/playmate-parameter-sync --check
```

환경변수 원문을 출력하거나 채팅에 공유하지 않는다.

## 10. CloudWatch 확인

```bash
systemctl status amazon-cloudwatch-agent --no-pager
systemctl status playmate-health-metric.timer --no-pager
sudo journalctl -u playmate-health-metric.service -n 30 --no-pager
```

## 11. 백업 확인

AWS CloudShell에서 실행:

```bash
aws dlm get-lifecycle-policies \
  --region ap-northeast-2 \
  --output table

aws ec2 describe-snapshots \
  --owner-ids self \
  --region ap-northeast-2 \
  --output table
```

## 12. 일일 운영 체크리스트

- [ ] 웹사이트 접속 정상.
- [ ] API Health 정상.
- [ ] CloudWatch 경보 상태 확인.
- [ ] 메모리 및 디스크 사용률 확인.
- [ ] CPU Credit 잔액 확인.
- [ ] DB 백업 결과 확인.
- [ ] EBS 스냅샷 생성 결과 확인.
- [ ] GitHub Actions 배포 결과 확인.

## 13. 주간 운영 체크리스트

- [ ] AWS 청구 비용 및 예산 확인.
- [ ] 불필요한 리소스 점검.
- [ ] IAM 권한 변경 이력 확인.
- [ ] 서비스 오류 및 지연 분석.
- [ ] 백업 복구 가능성 점검.
- [ ] 운영 문서 최신화.

## 14. 운영 주의사항

- 운영 중 임의로 EC2를 중지하지 않는다.
- 담당자 협의 없이 PostgreSQL을 재시작하지 않는다.
- Discord 및 뉴스 관련 서비스를 임의로 수정하지 않는다.
- 환경변수, Webhook 및 세션 정보를 출력하지 않는다.
- 스냅샷이나 S3 이전 버전을 검증 없이 삭제하지 않는다.
- 실제 장애 주입 테스트는 별도 환경에서 진행한다.
