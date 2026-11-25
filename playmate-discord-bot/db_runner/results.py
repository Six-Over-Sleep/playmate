"""SQS transport adapter. Service return is the existing transaction commit boundary."""
import logging
import math
import random
import re
import threading
import time

from career_share import contract

log = logging.getLogger("db_runner")
SQS_MAX_VISIBILITY_SECONDS = 43_200
HEARTBEAT_JOIN_SECONDS = 10
UNITS = {"career": {"IMMEDIATE": r"post-\d{1,18}", "DIGEST": r"digest-\d{4}-\d{2}-\d{2}"},
         "hot": {"HOT": r"hot-\d{1,18}"}, "dm": {"DM": r"dm-\d{1,18}"}}


def validate_result(feature, body):
    result = contract.validate_result(contract.loads(body))
    pattern = UNITS[feature].get(result.get("kind"))
    if pattern is None or re.fullmatch(pattern, result["unit_id"]) is None:
        raise contract.ContractError("result does not belong to this queue")
    return result


class Lease:
    """Renew while DB work is running, also during graceful drain. Failed renewal forbids ACK."""
    def __init__(self, client, queue, receipt, settings, receive_started=None):
        self.client, self.queue, self.receipt, self.settings = client, queue, receipt, settings
        self.receive_started = time.monotonic() if receive_started is None else receive_started
        self.done = threading.Event()
        self.failed = threading.Event()
        self.deadline = 0
        self.thread = threading.Thread(target=self.run, name="result-visibility", daemon=True)

    def renew(self):
        started = time.monotonic()
        # SQS limits total visibility from the original ReceiveMessage request.
        # Start the clock before polling and allow a second for request transit.
        remaining = math.floor(SQS_MAX_VISIBILITY_SECONDS - (started - self.receive_started)) - 1
        timeout = min(self.settings.visibility_seconds, remaining)
        if timeout <= 0:
            self.failed.set()
            log.warning("SQS visibility limit exhausted")
            return
        try:
            self.client.change_message_visibility(QueueUrl=self.queue, ReceiptHandle=self.receipt,
                                                  VisibilityTimeout=timeout)
            self.deadline = started + timeout
        except Exception as error:
            self.failed.set()
            log.error("visibility renewal failed error=%s", type(error).__name__)

    def run(self):
        while not self.done.wait(self.settings.heartbeat_seconds):
            self.renew()
            if self.failed.is_set():
                return

    def __enter__(self):
        # Establish a conservative deadline independent of how long ReceiveMessage took.
        self.renew()
        self.thread.start()
        return self

    def safe_to_ack(self):
        return not self.failed.is_set() and time.monotonic() < self.deadline - (2 * self.settings.read_timeout + 15)

    def __exit__(self, *args):
        self.done.set()
        self.thread.join(timeout=HEARTBEAT_JOIN_SECONDS)
        if self.thread.is_alive():
            self.failed.set()
            log.warning("visibility heartbeat did not stop before the join deadline")


class ResultConsumer:
    def __init__(self, feature, service, client, settings, *, lease_factory=Lease):
        self.feature, self.service, self.client, self.settings = feature, service, client, settings
        self.queue = settings.queues[feature]
        self.lease_factory = lease_factory
        self.lease = None

    @property
    def heartbeat_running(self):
        return self.lease is not None and self.lease.thread.is_alive()

    def process(self, message, receive_started=None):
        receipt = message.get("ReceiptHandle")
        if not isinstance(receipt, str) or not receipt:
            log.error("invalid SQS envelope feature=%s", self.feature)
            return "invalid"
        try:
            result = self.validate(message.get("Body"))
        except (contract.ContractError, TypeError, ValueError):
            # No ACK: SQS's existing maxReceiveCount/redrive policy owns poison messages.
            log.error("invalid result feature=%s", self.feature)
            return "invalid"
        try:
            self.lease = self.lease_factory(self.client, self.queue, receipt, self.settings, receive_started)
            with self.lease as lease:
                if lease.failed.is_set():
                    return "lease_failed"
                self.service.apply_result(result)
        except Exception as error:
            # Includes commit response loss. Never infer a successful commit from an exception.
            log.error("DB result failed feature=%s error=%s", self.feature, type(error).__name__)
            return "db_failed"
        if self.heartbeat_running or not lease.safe_to_ack():
            return "lease_failed"
        try:
            self.client.delete_message(QueueUrl=self.queue, ReceiptHandle=receipt)
        except Exception as error:
            log.error("result delete failed feature=%s error=%s", self.feature, type(error).__name__)
            return "delete_failed"
        log.info("result acknowledged feature=%s", self.feature)
        return "acked"

    def validate(self, body):
        return validate_result(self.feature, body)

    def poll_once(self, stop):
        if stop.is_set():
            return "stopped"
        if self.heartbeat_running:
            return "lease_failed"  # keep this queue from accumulating stuck heartbeat threads
        receive_started = time.monotonic()
        response = self.client.receive_message(QueueUrl=self.queue, MaxNumberOfMessages=1,
                                               WaitTimeSeconds=self.settings.wait_seconds,
                                               VisibilityTimeout=self.settings.visibility_seconds)
        if stop.is_set():
            return "stopped"  # received but not started: leave invisible until SQS redelivers
        messages = response.get("Messages", [])
        return self.process(messages[0], receive_started) if messages else "empty"

    def run(self, stop):
        failures = 0
        while not stop.is_set():
            try:
                outcome = self.poll_once(stop)
            except Exception as error:
                log.error("result poll failed feature=%s error=%s", self.feature, type(error).__name__)
                outcome = "poll_failed"
            if outcome in ("db_failed", "poll_failed", "lease_failed", "delete_failed"):
                failures += 1
                stop.wait(min(300, 2 ** min(failures, 8)) + random.uniform(0, 1))
            else:
                failures = 0
