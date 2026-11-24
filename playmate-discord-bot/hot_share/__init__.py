"""HOT 게시글 Discord 자동 공유 (Issue #165). 취업 공유(#163, career_share)의 서버리스 구조와 처리 규칙을 재사용한다.

  db_lambda.py      DB Lambda (VPC 안): baseline / 5분 주기 HOT 후보 선점 -> 발송 큐, 결과 큐 -> DB 기록, 복구
  worker_lambda.py  Discord Worker Lambda (VPC 밖): 발송 큐 -> Discord REST -> 결과 큐 (DB 접근 없음)
  policy / messages / settings / repository / service

재사용 (수정 없이 import): career_share.contract(이벤트 계약), state(상태 전이), queues(SQS), messages(제목 정리·마커),
service.CareerShareService(발행/복구/결과 반영 흐름), worker.CareerShareWorker(마커 확인·발송·오류 분류), worker_lambda.handle_records,
settings.web_base_url, discord_rest.DiscordRestClient(#161).
분리: 이력 테이블(hot_discord_shares), 작업 단위(hot-<id>), 큐, Worker 채널(HOT 채널), advisory lock 키, 환경변수(HOT_SHARE_*).
기존 Gateway Bot 코드(bot.py, config.py, /게시글추천)는 import하지도 바꾸지도 않는다.
"""
