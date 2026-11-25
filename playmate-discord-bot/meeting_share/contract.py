import re
from uuid import UUID

CREATE_MANUAL_REASONS = {
    "duplicate_marker": "reconcile duplicate Discord topic markers before retry",
    "marker_outside_scope": "inspect the existing channel and correct its registered category or type",
    "marker_policy_mismatch": "inspect the protected channel or mismatched topic policy",
    "invalid_category": "verify the registered category ID, guild, type and bot access",
    "categories_full": "free capacity or register another category before retry",
    "job_scope_mismatch": "align the Runner and Worker guild, category and visibility configuration",
    "approval_scope_mismatch": "reconcile the returned approval scope and inspect Discord before retry",
}
CREATE_TRANSIENT_REASONS = {"approval_window_elapsed", "verification_not_found", "approval_denied"}


def job_id(data):
    if not isinstance(data, dict) or type(data.get("v")) is not int or data["v"] != 1:
        raise ValueError("invalid meeting contract")
    value = data.get("job_id")
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError("invalid meeting job ID")
    return value


def snowflake(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{15,25}", value):
        raise ValueError("invalid snowflake")
    return value


def result(data):
    job_id(data)
    if data.get("kind") not in ("create", "permissions"):
        raise ValueError("invalid kind")
    if data.get("outcome") not in ("applied", "found", "unknown", "skipped", "rejected", "member_absent"):
        raise ValueError("invalid outcome")
    if data.get("outcome") == "found" and data["kind"] != "create":
        raise ValueError("invalid recovery result")
    if data.get("outcome") == "member_absent" and data["kind"] != "permissions":
        raise ValueError("invalid permission result")
    if data["kind"] == "create" and data["outcome"] == "skipped":
        reason = data.get("reason")
        if not isinstance(reason, str) or (reason not in CREATE_MANUAL_REASONS and reason not in CREATE_TRANSIENT_REASONS):
            raise ValueError("invalid creation skip reason")
    if data["kind"] == "create" and data["outcome"] in ("applied", "found"):
        snowflake(data.get("channel_id"))
    if data["outcome"] in ("applied", "unknown", "rejected"):
        job_id({"v": 1, "job_id": data.get("approval_id")})
    return data
