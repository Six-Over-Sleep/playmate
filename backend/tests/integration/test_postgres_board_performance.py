"""#159 regression scenarios; writes only to an explicitly supplied local test DB."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Event
from time import perf_counter
from urllib.parse import urlsplit
import os
import uuid

import pytest
from sqlalchemy import create_engine

from app.core import db_connect, uploads
from app.core.auth import get_current_member_id
from app.main import app
from app.services import board_service
from backend.app.core import database

URL = os.getenv("PLAYMATE_BOARD_TEST_DB_URL")
pytestmark = pytest.mark.skipif(not URL, reason="explicit disposable PostgreSQL required")
PNG = b"\x89PNG\r\n\x1a\nfixture"


@pytest.fixture
def local_board(monkeypatch, tmp_path, client):
    target = urlsplit(URL)
    if target.hostname not in {"localhost", "127.0.0.1", "::1"} or "test" not in target.path.lower():
        pytest.skip("local test database only")
    db_connect.close_pool()
    for key, value in {"DB_HOST": target.hostname, "DB_PORT": str(target.port or 5432),
                       "DB_USER": target.username or "postgres", "DB_PASSWORD": target.password or "unused",
                       "DB_NAME": target.path.lstrip("/"), "DB_SSLMODE": "disable", "APP_ENV": "test"}.items():
        monkeypatch.setenv(key, value)
    engine = create_engine(URL.replace("postgresql://", "postgresql+psycopg://"), connect_args={"sslmode": "disable"}, pool_size=1, max_overflow=0)
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(uploads, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(uploads, "UPLOAD_DIR", tmp_path / "uploads" / "posts")
    with db_connect.db_cursor(commit=True) as c:
        c.execute("INSERT INTO members(nickname,role_code) VALUES (%s,'MEMBER') RETURNING member_id", ("quality159-" + uuid.uuid4().hex[:12],))
        member = c.fetchone()["member_id"]
        c.execute("INSERT INTO boards(board_name,created_by) VALUES (%s,%s) RETURNING board_id", ("quality159-" + uuid.uuid4().hex[:12], member))
        board = c.fetchone()["board_id"]
    app.dependency_overrides[get_current_member_id] = lambda: member
    yield client, board, member, tmp_path
    app.dependency_overrides.clear()
    with db_connect.db_cursor(commit=True) as c:
        c.execute("DELETE FROM member_xp_history WHERE member_id=%s", (member,))
        c.execute("DELETE FROM post_attachments WHERE post_id IN (SELECT post_id FROM posts WHERE board_id=%s)", (board,))
        c.execute("DELETE FROM comments WHERE post_id IN (SELECT post_id FROM posts WHERE board_id=%s)", (board,))
        c.execute("DELETE FROM posts WHERE board_id=%s", (board,))
        c.execute("DELETE FROM boards WHERE board_id=%s", (board,))
        c.execute("DELETE FROM member_levels WHERE member_id=%s", (member,))
        c.execute("DELETE FROM members WHERE member_id=%s", (member,))
    engine.dispose()
    db_connect.close_pool()


def create(client, board, images=1):
    r = client.post(f"/api/boards/{board}/posts", data={"title": "fixture", "body": "body"},
                    files=[("images", (f"{i}.png", PNG, "image/png")) for i in range(images)])
    assert r.status_code == 201, r.text
    return r.json()


def edit(client, board, post, keep=None, new=1):
    data = {"title": "edited", "body": "changed", "original_image_ids": [p["id"] for p in post["images"]],
            "keep_image_ids": [p["id"] for p in post["images"]] if keep is None else keep}
    return client.patch(f"/api/boards/{board}/posts/{post['id']}/images", data=data,
                        files=[("images", (f"new{i}.png", PNG, "image/png")) for i in range(new)])


def test_page_global_order_search_and_legacy(local_board):
    client, board, member, _ = local_board
    with db_connect.db_cursor(commit=True) as c:
        c.execute("INSERT INTO posts(board_id,author_member_id,post_type,title,body,created_at) "
                  "SELECT %s,%s,'BOARD','item '||g,repeat('body',100),CURRENT_TIMESTAMP-g*INTERVAL '1 second' FROM generate_series(1,65)g", (board, member))
    path = f"/api/boards/{board}/posts"
    legacy = client.get(path).json()
    first = client.get(path + "?limit=30&summary=true").json()
    second = client.get(path + "?limit=30&offset=30").json()
    oldest = client.get(path + "?limit=30&sort=oldest").json()
    assert len(legacy) == 65 and len(first) == len(second) == len(oldest) == 30
    assert [p["id"] for p in first] == [p["id"] for p in legacy[:30]]
    assert [p["id"] for p in second] == [p["id"] for p in legacy[30:60]]
    assert [p["id"] for p in oldest] == [p["id"] for p in reversed(legacy[-30:])]
    assert len(first[0]["body"]) == 200 and len(legacy[0]["body"]) == 400
    assert client.get(path + "?limit=0").status_code == 422
    assert len(client.get(path + "?q=item%2065&limit=30").json()) == 1


def test_deleted_parent_with_reply_keeps_placeholder_and_order(local_board):
    client, board, member, _ = local_board
    post = create(client, board)
    path = f"/api/boards/{board}/posts/{post['id']}/comments"
    parent = client.post(path, json={"body": "parent"})
    assert parent.status_code == 201
    child = client.post(path, json={"body": "reply", "parent_comment_id": parent.json()["id"]})
    assert child.status_code == 201
    assert client.delete(f"/api/comments/{parent.json()['id']}").status_code == 204
    rows = client.get(path).json()
    assert [r["id"] for r in rows] == [parent.json()["id"], child.json()["id"]]
    assert rows[0]["is_deleted"] is True and rows[0]["body"] == ""
    assert rows[1]["body"] == "reply"


@pytest.mark.parametrize("case,expected", [("owner",403),("stale",409),("limit",422)])
def test_rejected_edit_does_not_write(local_board, monkeypatch, case, expected):
    client, board, member, _ = local_board
    post = create(client, board, 2)
    calls=[]
    monkeypatch.setattr(uploads.post_image_storage, "save", lambda *args: calls.append(args))
    if case == "owner":
        app.dependency_overrides[get_current_member_id] = lambda: member + 1
    elif case == "stale":
        post = dict(post, images=[])
    response = edit(client, board, post, new=2 if case == "limit" else 1)
    assert response.status_code == expected, response.text
    assert calls == []


@pytest.mark.parametrize("stage", ["partial_write", "database"])
def test_image_failure_keeps_original_files_and_metadata(local_board, monkeypatch, stage):
    client, board, member, root = local_board
    post = create(client, board, 2)
    before = {p.name for p in (root / "uploads" / "posts").glob("*")}
    if stage == "partial_write":
        real = uploads.post_image_storage.save
        def fail(key, data, content_type):
            real(key, data[:2], content_type)
            raise OSError("partial write fixture")
        monkeypatch.setattr(uploads.post_image_storage, "save", fail)
    else:
        def fail(*args, **kwargs):
            raise RuntimeError("metadata insert failure fixture")
        monkeypatch.setattr(board_service.repository, "insert_post_images", fail)
    if stage == "partial_write":
        # ASGITransport surfaces unhandled storage errors instead of wrapping a 500.
        with pytest.raises(OSError, match="partial write fixture"):
            edit(client, board, post, [post["images"][0]["id"]], 1)
    else:
        response = edit(client, board, post, [post["images"][0]["id"]], 1)
        assert response.status_code == 503
    current = client.get(f"/api/boards/{board}/posts/{post['id']}").json()
    assert current["title"] == post["title"] and current["images"] == post["images"]
    assert {p.name for p in (root / "uploads" / "posts").glob("*")} == before


def test_image_replace_add_and_remove_all(local_board):
    client, board, member, root = local_board
    post = create(client, board, 2)
    replaced = edit(client, board, post, [post["images"][0]["id"]], 1)
    assert replaced.status_code == 200
    current = replaced.json()
    assert current["images"][0]["id"] == post["images"][0]["id"]
    assert current["images"][1]["id"] != post["images"][1]["id"]
    added = edit(client, board, current, new=1)
    assert added.status_code == 200 and len(added.json()["images"]) == 3
    cleared = edit(client, board, added.json(), [], 0)
    assert cleared.status_code == 200 and cleared.json()["images"] == []
    assert not list((root / "uploads" / "posts").glob("*"))


def test_storage_does_not_hold_post_lock_and_final_conflict_cleans_files(local_board, monkeypatch):
    client, board, member, root = local_board
    post = create(client, board)
    entered, release = Event(), Event()
    original = uploads.post_image_storage.save
    def slow(key, data, content_type):
        entered.set()
        assert release.wait(5)
        original(key, data, content_type)
    monkeypatch.setattr(uploads.post_image_storage, "save", slow)
    with ThreadPoolExecutor(2) as pool:
        pending = pool.submit(edit, client, board, post, [], 1)
        assert entered.wait(5)
        start = perf_counter()
        # A separate transaction can lock/change attachments before storage ends.
        with db_connect.db_cursor(commit=True) as c:
            c.execute("SET LOCAL lock_timeout = '500ms'")
            c.execute("SELECT post_id FROM posts WHERE post_id=%s FOR UPDATE", (post["id"],))
            c.execute("DELETE FROM post_attachments WHERE post_id=%s", (post["id"],))
        duration = perf_counter() - start
        release.set()
        assert pending.result().status_code == 409
    assert duration < .5
    # The stale request's new file is removed; the previous file remains untouched.
    assert len(list((root / "uploads" / "posts").glob("*"))) == 1


def test_unknown_commit_preserves_new_and_old_files(local_board, monkeypatch):
    client, board, member, root = local_board
    post = create(client, board)
    original = board_service.db_cursor
    @contextmanager
    def lost_response(**kwargs):
        with original(**kwargs) as cursor:
            yield cursor
        if kwargs.get("commit"):
            raise db_connect.CommitOutcomeUnknownError("test response lost after commit")
    monkeypatch.setattr(board_service, "db_cursor", lost_response)
    r = edit(client, board, post, [], 1)
    assert r.status_code == 503
    current = client.get(f"/api/boards/{board}/posts/{post['id']}").json()
    assert len(current["images"]) == 1
    assert len(list((root / "uploads" / "posts").glob("*"))) == 2


def test_pool_alias_and_pooled_psycopg_transaction(local_board):
    from backend.app.core import db_connect as alias
    assert db_connect is alias
    with database.pooled_db_connection() as first:
        pid = first.info.backend_pid
        with first.cursor() as c:
            c.execute("SELECT 1")
            assert c.fetchone() == (1,)
    with database.pooled_db_connection() as second:
        assert second.info.backend_pid == pid
        assert second.info.transaction_status == 2  # active transaction scope


def test_real_pool_wait_return_and_restart(local_board):
    ready = [Event(), Event()]
    release = Event()
    def hold(index):
        with db_connect.db_cursor(read_only=True) as c:
            c.execute("SELECT pg_backend_pid() AS pid")
            pid = c.fetchone()["pid"]
            ready[index].set()
            assert release.wait(5)
            return pid
    def queued():
        started = perf_counter()
        with db_connect.db_cursor(read_only=True) as c:
            c.execute("SELECT pg_backend_pid() AS pid")
            return c.fetchone()["pid"], perf_counter() - started
    with ThreadPoolExecutor(3) as pool:
        holders = [pool.submit(hold, i) for i in range(2)]
        assert all(e.wait(5) for e in ready)
        third = pool.submit(queued)
        assert not third.done()
        release.set()
        pids = {h.result() for h in holders}
        pid, _ = third.result()
        assert len(pids) == 2 and pid in pids
    db_connect.close_pool()
    assert db_connect._pool_state is None
    with db_connect.db_cursor(read_only=True) as c:
        c.execute("SELECT pg_backend_pid() AS pid")
        assert c.fetchone()["pid"] not in pids
