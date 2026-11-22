"""취업 게시글 Discord 자동 공유 (Issue #163). 서버리스(Lambda + SQS) 구조.

  db_lambda.py      DB Lambda (VPC 안): 신규 글 조회/선점 -> 발송 큐, 결과 큐 -> DB 기록, 복구
  worker_lambda.py  Discord Worker Lambda (VPC 밖): 발송 큐 -> Discord REST -> 결과 큐 (DB 접근 없음)
  policy / messages / contract / state / settings / repository / service / worker / queues
기존 Gateway Bot 코드(bot.py, config.py)는 import하지 않는다.
"""
