"""Run runner + delivery regressions with DB/AWS access blocked and PG suites skipped.

Usage (from playmate-discord-bot): python -B tests/run_db_runner_offline.py
Existing HTTP fakes bind loopback; public network access is never permitted.
"""
import importlib.util
import os
from pathlib import Path
import socket
import sys
import unittest
from contextlib import ExitStack
from unittest import mock


def main():
    os.environ["PLAYMATE_TEST_PG_DSN"] = ""
    os.environ["AWS_EC2_METADATA_DISABLED"] = "true"
    os.environ["AWS_ACCESS_KEY_ID"] = "offline-test-only"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "offline-test-only"
    root = Path(__file__).resolve().parents[1]
    sys.path[:0] = [str(root), str(root / "tests")]
    real_lookup, real_connect = socket.getaddrinfo, socket.socket.connect
    blocked = []

    def lookup(host, *args, **kwargs):
        if str(host).strip("[]") not in ("127.0.0.1", "localhost", "::1"):
            blocked.append("lookup")
            raise AssertionError("offline suite: public DNS forbidden")
        return real_lookup(host, *args, **kwargs)

    def connect(sock, address):
        if not isinstance(address, tuple) or str(address[0]).strip("[]") not in ("127.0.0.1", "localhost", "::1"):
            blocked.append("connect")
            raise AssertionError("offline suite: public connection forbidden")
        return real_connect(sock, address)

    with ExitStack() as stack:
        stack.enter_context(mock.patch("socket.getaddrinfo", lookup))
        stack.enter_context(mock.patch.object(socket.socket, "connect", connect))
        for driver in ("psycopg", "psycopg2"):
            if importlib.util.find_spec(driver):
                stack.enter_context(mock.patch(f"{driver}.connect", side_effect=AssertionError("offline suite: DB forbidden")))
        if importlib.util.find_spec("boto3"):
            stack.enter_context(mock.patch("boto3.client", side_effect=AssertionError("offline suite: AWS forbidden")))
            stack.enter_context(mock.patch("boto3.session.Session.client", side_effect=AssertionError("offline suite: AWS forbidden")))
        suite = unittest.defaultTestLoader.loadTestsFromNames([
            "test_db_runner", "test_career_share", "test_hot_share", "test_dm_share", "test_dm_fifo",
            "test_serverless_infra", "test_db_integration",
        ])
        result = unittest.TextTestRunner(verbosity=1).run(suite)
    print(f"Offline network attempts blocked: {len(blocked)}; PostgreSQL DSN disabled")
    return 0 if result.wasSuccessful() and not blocked else 1


if __name__ == "__main__":
    raise SystemExit(main())
