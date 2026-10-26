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

모임 생성·참여·취소는 로그인 세션의 `member_id`를 사용함(없으면 401). 모임장은 일반 참여할 수 없음(403). 모임 수정·삭제의 작성자 권한 검사는 아직 미구현임.
