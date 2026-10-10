# routers | 모임 API 주소

## 파일
`recruit.py`에서 HTTP 메서드와 URL을 선언함. FastAPI의 `APIRouter(prefix="/api/recruits")`를 사용함.

## API 목록
```text
GET    /api/recruits
GET    /api/recruits/{recruit_id}
POST   /api/recruits
PATCH  /api/recruits/{recruit_id}
DELETE /api/recruits/{recruit_id}
POST   /api/recruits/{recruit_id}/join
DELETE /api/recruits/{recruit_id}/join
GET    /api/recruits/{recruit_id}/members
GET    /api/recruits/{recruit_id}/count
```

## 주의
모임 삭제는 DB 행 삭제가 아니라 `post_status="DELETED"` 및 `recruit.state="CLOSED"` 처리임. 상세/목록 조회는 삭제된 글을 제외함.

테스트용 참가자 ID `-1`은 실제 Discord 연동 때 제거해야 함. 인증·권한 검사는 아직 미구현임.
