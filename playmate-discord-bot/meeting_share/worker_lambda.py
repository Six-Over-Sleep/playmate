"""Dedicated, DB-free meeting Worker. Approval is consumed before each write."""
import hashlib
import hmac
import json
import logging
import os
import time
from functools import lru_cache
from urllib.parse import urlsplit
from uuid import uuid4

from career_share.queues import SqsPublisher
from discord_rest import DiscordRestClient
from discord_rest.errors import DiscordError, DiscordForbidden, DiscordNotFound
from discord_rest.permissions import everyone_overwrite, PARTICIPANT_ALLOW, revoked_permissions
from discord_rest.transport import urllib_transport
from meeting_share.contract import CREATE_MANUAL_REASONS, job_id, snowflake

log = logging.getLogger(__name__)
PATH = "/internal/discord-meeting/approve"
STAFF_BITS = sum(1 << bit for bit in (1, 2, 3, 4, 5, 13, 28, 40))
CATEGORY_CAPACITY = 50
MEMBER_ABSENT = object()


class Approval:
    def __init__(self, url, secret, transport=urllib_transport, clock=time.time):
        parts = urlsplit(url)
        if (parts.scheme != "https" or not parts.hostname or parts.username or parts.password
                or parts.path != PATH or parts.query or parts.fragment or len(secret) < 32):
            raise ValueError("invalid meeting approval configuration")
        self.url, self.secret, self.transport, self.clock = url, secret, transport, clock

    def __call__(self, job, grant_from):
        nonce = str(uuid4())
        body = json.dumps({"job_id": job, "nonce": nonce, "grant_from": grant_from}, separators=(",", ":")).encode()
        stamp = str(int(self.clock()))
        signed = b"POST " + PATH.encode() + b"\n" + stamp.encode() + b"\n" + body
        signature = hmac.new(self.secret.encode(), signed, hashlib.sha256).hexdigest()
        status, _, raw = self.transport("POST", self.url, {
            "Content-Type": "application/json", "X-Meeting-Time": stamp, "X-Meeting-Signature": signature,
        }, body, 3)
        if status == 409:
            return None
        if status != 200:
            raise RuntimeError("meeting approval unavailable")
        result = json.loads(raw)
        if result["approval_id"] != nonce or not self.clock() < result["expires_at"] <= self.clock() + 10:
            raise ValueError("invalid or expired approval")
        return result


def matches(channel, guild, category, marker):
    return (channel.get("type") == 0 and channel.get("guild_id") == guild
            and channel.get("parent_id") == category and channel.get("topic") == marker)


class MeetingWorker:
    def __init__(self, discord, approve, guild, category, protected=(), staff_roles=(), *,
                 additional_categories=(), grant=False, clock=time.time):
        self.discord, self.approve = discord, approve
        self.guild, self.category = snowflake(guild), snowflake(category)
        self.protected, self.staff_roles = set(protected), set(staff_roles)
        self.categories = (self.category, *(snowflake(value) for value in additional_categories))
        if len(set(self.categories)) != len(self.categories) or self.protected.intersection(self.categories):
            raise ValueError("invalid or protected meeting category")
        self.grant, self.clock = grant, clock

    def process(self, data):
        key = job_id(data)
        rid, kind = data["recruit_id"], data["kind"]
        if type(rid) is not int or rid < 1 or kind not in ("create", "permissions"):
            raise ValueError("invalid meeting job")

        def outcome(value, **extra):
            return {"v": 1, "job_id": key, "kind": kind, "outcome": value, **extra}

        def skip(reason):
            if kind == "create" and reason in CREATE_MANUAL_REASONS:
                log.warning("MEETING_WRITE_FAILURE create skipped reason=%s job_id=%s", reason, key)
            return outcome("skipped", reason=reason)

        target = data["target"]
        visibility = target["visibility"]
        if ((target["guild_id"], target["category_id"]) != (self.guild, self.category)
                or visibility not in ("PUBLIC", "PRIVATE")):
            if kind == "create":
                return skip("job_scope_mismatch")
            raise ValueError("unexpected meeting scope")
        marker = f"PlayMate 모임 #{rid} "
        topic = marker + f"({visibility})"

        deadline = data.get("approve_before")
        if deadline is not None and data.get("verify") is False and self.clock() >= deadline:
            return skip("approval_window_elapsed")

        if kind == "create":
            channels = self.discord.list_guild_channels(int(self.guild))
            marked = [c for c in channels if str(c.get("topic") or "").startswith(marker)]
            if len(marked) > 1:
                return skip("duplicate_marker")
            if marked:
                candidate = marked[0]
                if (candidate.get("parent_id") not in self.categories
                        or candidate.get("guild_id") != self.guild or candidate.get("type") != 0):
                    return skip("marker_outside_scope")
                if candidate["topic"] != topic or candidate["id"] in self.protected:
                    return skip("marker_policy_mismatch")
                return outcome("found", channel_id=snowflake(candidate["id"]))
            if data.get("verify") is not False:
                return skip("verification_not_found")
            selected = next((category for category in self.categories
                             if sum(c.get("parent_id") == category for c in channels) < CATEGORY_CAPACITY), None)
            if selected is None:
                return skip("categories_full")
            try:
                category = self.discord.get_channel(int(selected))
            except (DiscordNotFound, DiscordForbidden):
                return skip("invalid_category")
            if (category.get("id"), category.get("guild_id"), category.get("type")) != (selected, self.guild, 4):
                return skip("invalid_category")
        else:
            channel = snowflake(target["channel_id"])
            user = snowflake(target["user_id"])
            current = self.inspect_permission(channel, user, topic)
            if current is MEMBER_ABSENT:
                return outcome("member_absent")
            if current is None:
                return outcome("skipped")

        grant_from = "disabled"
        if kind == "permissions" and self.grant:
            if not current:
                grant_from = "absent"
            elif current == revoked_permissions("PUBLIC"):
                grant_from = "readonly"
        approval = self.approve(key, grant_from)
        if not approval:
            return skip("approval_denied")
        if any(approval.get(k) != v for k, v in target.items()):
            return skip("approval_scope_mismatch")
        action, approval_id = approval["action"], approval["approval_id"]
        result = {"approval_id": approval_id}
        if self.clock() >= approval["expires_at"]:
            return outcome("unknown", **result)
        try:
            if kind == "create" and action == "create":
                made = self.discord.create_guild_channel(
                    int(self.guild), name=approval["name"], parent_id=int(selected),
                    topic=topic,
                    permission_overwrites=[everyone_overwrite(int(self.guild), visibility)],
                )
                if not matches(made, self.guild, selected, topic) or made.get("id") in self.protected:
                    return outcome("unknown", **result)
                return outcome("applied", channel_id=snowflake(made["id"]), **result)
            if kind == "permissions" and action == "revoke":
                bits = revoked_permissions(visibility)
                if current and current != bits:
                    if bits is None:
                        self.discord.clear_member_permissions(int(channel), int(user))
                    else:
                        self.discord.set_member_permissions(int(channel), int(user), allow=bits[0], deny=bits[1])
            elif kind == "permissions" and action == "grant" and self.grant:
                if current != (PARTICIPANT_ALLOW, 0):
                    self.discord.set_member_permissions(int(channel), int(user), allow=PARTICIPANT_ALLOW, deny=0)
            else:
                return outcome("rejected", **result)
            return outcome("applied", **result)
        except DiscordError as error:
            status = getattr(error, "status", None)
            definitive = status in (400, 401, 403, 404, 429) and not getattr(error, "outcome_unknown", False)
            code = error.code if type(error.code) is int else None
            log.warning("MEETING_WRITE_FAILURE status=%s code=%s error=%s job_id=%s",
                        status, code, type(error).__name__, key)
            return outcome("rejected" if definitive else "unknown", **result)

    def inspect_permission(self, channel, user, marker):
        if channel in self.protected or user in self.protected:
            return None
        current = self.discord.get_channel(int(channel))
        if (current.get("id") != channel or current.get("parent_id") not in self.categories
                or not matches(current, self.guild, current["parent_id"], marker)):
            return None
        members = [o for o in current["permission_overwrites"] if o["id"] == user and o["type"] == 1]
        bits = ()
        if members:
            bits = (int(members[0]["allow"]), int(members[0]["deny"]))
            if len(members) != 1 or bits not in ((PARTICIPANT_ALLOW, 0), revoked_permissions("PUBLIC")):
                return None
        guild = self.discord.get_guild(int(self.guild))
        try:
            member = self.discord.get_guild_member(int(self.guild), int(user))
        except DiscordNotFound as error:
            if error.code == 10007:
                return MEMBER_ABSENT
            raise
        if guild["id"] != self.guild or user == guild["owner_id"] or member["user"]["id"] != user:
            return None
        if member["user"].get("bot") or set(member["roles"]) & self.staff_roles:
            return None
        roles = {r["id"]: int(r["permissions"]) for r in self.discord.list_guild_roles(int(self.guild))}
        if any(roles[role] & STAFF_BITS for role in [self.guild, *member["roles"]]):
            return None
        return bits


@lru_cache(maxsize=1)
def build_worker():
    import boto3
    secret = boto3.client("secretsmanager").get_secret_value(
        SecretId=os.environ["MEETING_APPROVAL_SECRET_ARN"])["SecretString"].strip()
    return MeetingWorker(
        DiscordRestClient(os.environ["DISCORD_BOT_TOKEN"], max_retries=0, timeout=5),
        Approval(os.environ["MEETING_APPROVAL_URL"], secret),
        os.environ["MEETING_GUILD_ID"], os.environ["MEETING_CATEGORY_ID"],
        os.environ.get("MEETING_PROTECTED_IDS", "").split(","),
        os.environ.get("MEETING_STAFF_ROLE_IDS", "").split(","),
        additional_categories=os.environ.get("MEETING_ADDITIONAL_CATEGORY_IDS", "").split(",")
        if os.environ.get("MEETING_ADDITIONAL_CATEGORY_IDS") else (),
        grant=os.environ.get("MEETING_ALLOW_GRANT") == "true",
    )


def handler(event, context=None, *, worker=None, publisher=None, queue_url=None):
    worker = worker or build_worker()
    publisher = publisher or SqsPublisher()
    queue_url = queue_url or os.environ["MEETING_RESULT_QUEUE_URL"]
    records = event.get("Records", [])
    for index, record in enumerate(records):
        try:
            output = worker.process(json.loads(record["body"]))
            publisher.send(queue_url, json.dumps(output))
        except Exception as error:
            log.error("MEETING_WRITE_FAILURE job error=%s", type(error).__name__)
            return {"batchItemFailures": [{"itemIdentifier": r["messageId"]} for r in records[index:]]}
    return {"batchItemFailures": []}
