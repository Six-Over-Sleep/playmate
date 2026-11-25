"""Separate EC2 modes; meeting polls cannot block the existing message scheduler."""
import json
import logging
import os
from datetime import datetime
from types import SimpleNamespace
from urllib.parse import urlsplit

from career_share.queues import SqsPublisher
from career_share.repository import connect_for_lambda
from career_share.settings import SettingsError
from db_runner.results import ResultConsumer
from db_runner.services import sqs_client
from meeting_share.contract import result, snowflake
from meeting_share.repository import KST, MeetingJobs
from repositories.db import Database

log = logging.getLogger(__name__)


def load(env=os.environ):
    enabled = env.get("DB_RUNNER_MEETING_ENABLED", "false") == "true"
    if not enabled:
        return None
    if any(env.get(key) == "true" for key in ("DB_RUNNER_MEETING_PERMISSIONS", "DB_RUNNER_MEETING_GRANT")):
        raise SettingsError("meeting permission handoff is unavailable; keep Gateway permission ownership")
    region = env.get("AWS_DEFAULT_REGION", "")
    environment = env.get("PLAYMATE_ENVIRONMENT", "")
    if environment not in ("test", "prod") or not region or not all(
            env.get(k) for k in ("DB_HOST", "DB_USER", "DB_PASSWORD", "DB_NAME")):
        raise SettingsError("meeting DB, environment and region required")
    urls, accounts = {}, set()
    for role in ("work", "result"):
        url = env.get(f"MEETING_{role.upper()}_QUEUE_URL", "")
        parts = urlsplit(url)
        path = parts.path.strip("/").split("/")
        suffix = ".fifo" if role == "work" else ""
        host = f"sqs.{region}.amazonaws.com" + (".cn" if region.startswith("cn-") else "")
        if (parts.scheme != "https" or parts.netloc != host or parts.query or parts.fragment
                or len(path) != 2 or len(path[0]) != 12 or not path[0].isascii() or not path[0].isdigit()
                or path[1] != f"playmate-{environment}-meeting-{role}{suffix}"):
            raise SettingsError("unexpected meeting queue URL")
        accounts.add(path[0])
        urls[role] = url
    if len(accounts) != 1:
        raise SettingsError("meeting queues must share an account")
    target = None
    if env.get("DB_RUNNER_MEETING_SCHEDULE", "false") == "true":
        try:
            create = env.get("DB_RUNNER_MEETING_CREATE") == "true"
            cutover = datetime.fromisoformat(env["MEETING_CUTOVER_AT"]) if create else None
            visibility = env.get("MEETING_VISIBILITY", "PUBLIC")
            if (create and cutover.tzinfo is None) or visibility not in ("PUBLIC", "PRIVATE"):
                raise ValueError
            if create and visibility == "PRIVATE":
                raise SettingsError("private channel creation requires a verified participant-access rollout")
            target = dict(guild_id=snowflake(env["MEETING_GUILD_ID"]), category_id=snowflake(env["MEETING_CATEGORY_ID"]),
                          visibility=visibility, cutover=cutover.astimezone(KST).replace(tzinfo=None) if create else None,
                          create=create, permissions=env.get("DB_RUNNER_MEETING_PERMISSIONS") == "true",
                          grant=env.get("DB_RUNNER_MEETING_GRANT") == "true")
        except (KeyError, ValueError):
            raise SettingsError("invalid meeting scope or cutover") from None
    return SimpleNamespace(region=region, queues={"meeting": urls["result"]}, work_url=urls["work"], target=target,
                           wait_seconds=20, read_timeout=30, visibility_seconds=360, heartbeat_seconds=60,
                           lock_dir=env.get("DB_RUNNER_LOCK_DIR", "/var/lib/discord-db-runner"))


class Consumer(ResultConsumer):
    def validate(self, body):
        return result(json.loads(body))

    def poll_once(self, stop):
        outcome = super().poll_once(stop)
        if outcome in ("empty", "acked"):
            self.service.heartbeat()
        return outcome


class MeetingResults:
    def __init__(self, jobs):
        self.jobs = jobs

    def apply_result(self, body):
        return self.jobs.apply(body)

    def heartbeat(self):
        self.jobs.heartbeat()


def tick(jobs, publisher, settings):
    jobs.expire()
    if settings.target:
        jobs.schedule(settings.target)
    for row in jobs.pending():
        if row["kind"] == "create" and not row["verify"] and not (settings.target or {}).get("create"):
            continue
        if row["kind"] == "permissions" and not (settings.target or {}).get("permissions"):
            continue
        key = str(row["job_id"])
        body = dict(v=1, job_id=key, kind=row["kind"], recruit_id=row["recruit_id"],
                    target=row["target"], verify=row["verify"], approve_before=row["approve_before"])
        dedup = f"{key}:verify:{int(datetime.now(KST).timestamp()) // 60}" if row["verify"] else key
        publisher.send(settings.work_url, json.dumps(body), group_id=str(row["recruit_id"]), dedup_id=dedup)
        jobs.sent(key)


def run(mode, settings, stop):
    if settings is None:
        return
    db = Database(lambda: connect_for_lambda(f"discord_{mode}"))
    jobs = MeetingJobs(db)
    client = sqs_client(settings)
    consumer = None
    try:
        if mode == "meeting-results":
            consumer = Consumer("meeting", MeetingResults(jobs), client, settings)
            consumer.run(stop)
        else:
            publisher = SqsPublisher(client)
            while not stop.is_set():
                try:
                    tick(jobs, publisher, settings)
                except Exception as error:
                    log.error("meeting scheduling failed type=%s", type(error).__name__)
                stop.wait(10)
    finally:
        if mode == "meeting-results":
            try:
                jobs.reset_heartbeat()
            except Exception as error:
                log.error("meeting consumer heartbeat reset failed type=%s", type(error).__name__)
        db.close()
        if consumer is None or not consumer.heartbeat_running:
            client.close()
