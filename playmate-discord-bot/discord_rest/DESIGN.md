# discord_rest: 서버리스 전환 설계 메모 (인터페이스만, 구현 아님)

범위: 공통 REST 클라이언트(구현 완료)와, 이후 기능이 그것을 어떻게 쓸지의 인터페이스.
제외: `/게시글추천`, 외부 채용공고 정기 공지. 기존 Discord 채널은 재사용하고 새 공식 채널을 자동 생성하지 않는다
(`ensure_official_channels`는 이전하지 않는다).

## 공통 규칙

- Lambda 핸들러가 시크릿에서 토큰을 읽어 `DiscordRestClient(token, time_budget=<Lambda 남은 시간 - 여유>)`를 만든다.
- 부작용 요청(`send_message`, `create_guild_channel`)이 `outcome_unknown=True`로 실패하면 **다시 보내지 말고**
  먼저 결과를 확인한다 (`get_recent_messages` / `list_guild_channels` + `reuse.find_meeting_channels`).
- 상태 전이는 기존 DB 조건부 SQL(선점, 확정)이 계속 담당한다. REST 클라이언트는 상태를 갖지 않는다.

## 기능별 인터페이스

```python
# 1. HOT 최초 1회 공유 (EventBridge 주기 Lambda, 또는 SQS)
def share_hot_post(client, repo, *, hot_channel_id, post_id) -> Literal["SENT", "SKIPPED", "UNKNOWN"]:
    # repo.claim_hot_share(post_id)  -> 선점 성공한 한 곳만 진행 (신규 테이블, 아래 DB 변경)
    # payload = reuse.hot_message_payload(BOARD, content, url)
    # msg = client.send_message(hot_channel_id, **payload, nonce=f"hot-{post_id}")
    # repo.mark_hot_shared(post_id, channel_id, msg["id"])  /  outcome_unknown 이면 repo.mark_hot_unknown(post_id)

# 2. 취업 신규 글 공유 (SQS 또는 주기 Lambda). 게시판 -> 채널 매핑은 설정으로 주입
def share_career_post(client, repo, *, channel_by_board: Mapping[str, int], post) -> str:
    # 기존 career_discord_announcements 선점/재시도 흐름 재사용
    # payload = reuse.career_notice_payload(post, career_post_url(base, category, post_id))
    # client.send_message(channel_by_board[key], **payload, nonce=f"career-{post_id}")

# 3. 댓글/대댓글 DM (SQS 메시지 = notification_id 하나)
def deliver_notification(client, repo, notification_id) -> Literal["SENT", "SKIPPED", "RETRY", "FAILED", "UNKNOWN"]:
    # n = repo.claim_one(notification_id)           # 신규: 중복 방지용 선점(PROCESSING 또는 행 잠금)
    # plan = reuse.plan_dm(n)                       # 건너뜀 판정 + 문구 + 링크 (기존 로직)
    # if plan.skip_reason: repo.mark_skipped(...)
    # try: client.send_dm(plan.discord_id, content=plan.text, nonce=f"n-{notification_id}")
    # except DiscordForbidden as e: e.is_dm_blocked -> record_failure("DM 수신 차단 (403)")
    # except DiscordNotFound: mark_skipped("Discord 사용자 없음")
    # except DiscordError as e: e.outcome_unknown -> 재시도하지 않고 UNKNOWN 표시 (중복 DM 방지), 아니면 record_failure

# 4. 모임 채널 생성 / 참여 권한 (EventBridge 1분, 예약 동시성 1)
def provision_meeting(client, repo, guild_id, category_id, recruit) -> None:
    # repo.claim_provisioning(...)  # 기존 SQL 그대로
    # overwrites = permissions.meeting_channel_overwrites(guild_id, joined_ids, visibility)
    # client.create_guild_channel(guild_id, name=..., parent_id=category_id, topic=reuse.meeting_topic(id), permission_overwrites=overwrites)
    #   outcome_unknown -> reuse.find_meeting_channels(client.list_guild_channels(guild_id), id) 로 확인 후 이어가기
    # repo.complete_provisioning(...) # 기존 SQL 그대로
def sync_participant(client, channel_id, user_id, wanted: Literal["JOINED", "CANCELED"], visibility) -> bool:
    # ch = client.get_channel(channel_id); if reuse.joined_ok(ch, user_id) / reuse.revoked_ok(...): return True  (이미 목표 상태)
    # client.get_guild_member(guild_id, user_id)  # 404면 서버에 없음 -> 5분 대기 정책 유지
    # client.set_member_permissions(...) / permissions.revoked_permissions(visibility) None 이면 clear_member_permissions

# 5. 비활성 채널 정리 (EventBridge 1시간)
def check_inactivity(client, repo, meeting, now) -> None:
    # msgs = client.get_recent_messages(channel_id, 50); active = inactivity.latest_user_message_at(msgs, since)
    #   active 가 있으면 repo.record_activity(...)  (on_message 대체, 최대 1시간 지연)
    # action, scheduled = reuse.decide_inactivity(meeting, now)
    # WARN -> client.send_message(channel_id, content=INACTIVITY_WARNING_TEXT) 후 repo.record_warning(...)   # 경고 중복 주의
    # DELETE_DUE -> repo.meeting_lock(...) 안에서 reuse.safe_delete_meeting_channel(...) 후 lock.mark_deleted(...)

# 6. /알림설정 Interactions (API Gateway -> Lambda)
def handle_interaction(event) -> dict:
    # Ed25519 서명 검증 -> PING 응답 -> 3초 안에 type 5(지연) 또는 직접 응답
    # DB 조회/갱신은 기존 NotificationService.get_opt_in/toggle_opt_in 로직 재사용
    # 후속 응답은 interaction webhook(/webhooks/{app}/{token}) 이므로 DiscordRestClient 와 별개 호출 (신규 필요)
```

## 이 단계에 없는 것 (다음 단계 필요)

- Interactions 서명 검증과 응답 전송 (`/webhooks/...`은 봇 토큰 없이 interaction 토큰을 쓴다).
- 알림/HOT/취업 공유의 중복 방지 저장소와 SQS 연동.
- 429 전역 제한을 Lambda 인스턴스 간에 공유하는 방법 (현재는 호출 단위로만 대기한다).
