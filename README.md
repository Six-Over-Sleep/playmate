# PlayMate DB 확장 최종 점검 패키지

대상: PostgreSQL 18, 028~035 마이그레이션 완료된 `public` 스키마.

**이 패키지는 DB 스키마나 데이터를 변경하지 않습니다.**

1. `database/audit/playmate_db_integrity_check.sql`을 DBeaver에서 Alt+X 전체 실행합니다.
2. 결과 세트를 순서대로 확인합니다.
   - 신규 테이블: `30/30`, 누락 `0`
   - 신규 뷰: `4/4`, 누락 없음
   - NOT VALID 제약: 0행
   - 무효 인덱스: 0행
   - FK 선행 인덱스 후보: 출력되더라도 실패가 아닌 검토 대상
   - `board_id=8`: `COHORT`, `2`, `ALL_VERIFIED`, `SCOPE_ONLY`
   - Self-block/역전 DM 참가자/비참가자 송신: 각각 0
   - DM 트리거: 5개
3. `database/erd/PLAYMATE_ERD_GUIDE.md`의 요약 ERD를 참고해 DBeaver에서 실제 ERD 이미지로 내보냅니다.
4. `git status --short`, `git diff --check`, `git log -5 --oneline`으로 기록을 확인합니다.

참고: 새 테이블·뷰의 존재 확인은 충분하지만 실제 SQL 기능/권한/부하 테스트를 대체하지 않습니다. 특히 034의 차단 검사는 DM 송신 시 DB 트리거와 API 권한 검사를 모두 적용해야 합니다.
