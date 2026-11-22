"""댓글·대댓글 Discord DM의 Lambda 전송 (Issue #171). 취업(#163)·HOT(#165) 공유와 같은 서버리스 구조와 처리 규칙을 쓴다.

  db_lambda.py      DM DB Lambda (VPC 안): 공동 선점 -> 발송 큐, 결과 큐 -> DB 기록, 복구(마커 확인·마감)
  worker_lambda.py  DM Worker Lambda (VPC 밖, DB 없음): 발송 큐 -> DM 채널 열기 -> Discord REST -> 결과 큐
  messages / settings / service

공동 선점 저장소는 Gateway Bot과 함께 쓰므로 repositories/dm_delivery_repository.py에 있다.
재사용: career_share.contract/state/queues, CareerShareService(발행·결과 반영), CareerShareWorker(마커 확인·발송),
career_share.worker_lambda.handle_records, career_share.db_lambda.handle_results, services.notification_policy(문구·건너뜀 규칙),
services.web_links.notification_post_url, discord_rest.DiscordRestClient(#161).
"""
