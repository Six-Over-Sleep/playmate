"""Sequential, coalescing schedule; no delivery decisions or baseline calls."""
import logging
import math
import threading
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

log = logging.getLogger("db_runner")
KST = ZoneInfo("Asia/Seoul")


class Scheduler:
    def __init__(self, services, settings, *, clock=lambda: datetime.now(timezone.utc), monotonic=time.monotonic):
        self.services, self.settings = services, settings
        self.clock, self.monotonic = clock, monotonic
        self.next_due = {}
        self.digest_day = None
        self.lock = threading.Lock()

    def tick(self, stop):
        if not self.lock.acquire(blocking=False):
            return
        try:
            jobs = [("career", "relay", 60), ("hot", "relay", 300)]
            if self.settings.dm_mode != "disabled":
                jobs.append(("dm", self.settings.dm_mode, 600 if self.settings.dm_mode == "recover" else 60))
            for feature, action, interval in jobs:
                if stop.is_set():
                    return
                key = (feature, action)
                due = self.next_due.get(key, self.monotonic())
                if feature in self.services and self.monotonic() >= due:
                    try:
                        getattr(self.services[feature], action)(self.clock())
                        log.info("job completed feature=%s action=%s", feature, action)
                    except Exception as error:
                        log.error("job failed feature=%s action=%s error=%s", feature, action, type(error).__name__)
                    finally:
                        # No replay of missed slots, including time spent in the job.
                        elapsed = max(0, self.monotonic() - due)
                        self.next_due[key] = due + (math.floor(elapsed / interval) + 1) * interval
            if stop.is_set() or "career" not in self.services:
                return
            now = self.clock()
            local = now.astimezone(KST)
            scheduled = local.replace(hour=20, minute=0, second=0, microsecond=0)
            if (scheduled <= local <= scheduled + timedelta(minutes=self.settings.digest_grace_minutes)
                    and self.digest_day != local.date()):
                self.digest_day = local.date()  # one attempt per process/day, including empty or failed batches
                try:
                    self.services["career"].digest(now, scheduled)
                    log.info("digest completed")
                except Exception as error:
                    log.error("digest failed error=%s", type(error).__name__)
        finally:
            self.lock.release()

    def run(self, stop):
        while not stop.is_set():
            self.tick(stop)
            stop.wait(1)
