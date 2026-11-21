"""대댓글에 대한 답글(Issue #153) 저장·조회·알림 받는 사람을 실제 PostgreSQL에서 확인한다.

PLAYMATE_LOCAL_TEST_DB_URL에 로컬 일회용 테스트 DB(호스트 127.0.0.1/localhost, DB 이름에 test 포함)를 줄 때만 실행한다.
041_comment_reply_target.sql까지 적용된 DB가 필요하다(없으면 건너뜀). 공용 DB는 사용하지 않는다.
일반 게시판·취업 게시판·모임 세 댓글 경로를 같은 시나리오로 실행해 저장값과 알림이 같은지 본다.
알림은 notifications 행 저장까지만 확인한다(실제 Discord DM은 보내지 않음).
테스트가 만든 회원·게시판·게시글·댓글·알림 행은 끝날 때 지운다.
"""
import uuid
from urllib.parse import urlsplit

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core import db_connect
from app.core.db_connect import db_cursor
from app.services import board_service, career_reaction_service
from backend.app.schemas.recruit import RecruitCommentCreate, RecruitCommentUpdate
from backend.app.services import recruit_comment
from backend.app.services.notification_writer import save_comment_notification
from backend.app.core.database import get_db
from backend.tests.local_test_db import require_local_test_db_url, skip_unless_tables
from backend.tests.session_auth import session_headers

import backend.app.core.db_connect as backend_db_connect  # 알림 작성기가 쓰는 같은 모듈의 다른 import 경로

PATHS = ["board", "career", "meetup"]


@pytest.fixture
def env(monkeypatch):
    url = require_local_test_db_url()
    target = urlsplit(url)
    for pool_owner in (db_connect, backend_db_connect):
        pool_owner.close_pool()
    for key, value in {
        "DB_HOST": target.hostname, "DB_PORT": str(target.port or 5432),
        "DB_USER": target.username or "postgres", "DB_PASSWORD": target.password or "unused",
        "DB_NAME": target.path.lstrip("/"), "DB_SSLMODE": "disable", "APP_ENV": "test",
    }.items():
        monkeypatch.setenv(key, value)
    # XP는 별도 테스트가 있다. 알림 작성기는 실제로 실행해 받는 사람 계산을 확인한다.
    monkeypatch.setattr(board_service, "grant_xp", lambda *args: {"awarded": False})
    monkeypatch.setattr(career_reaction_service, "grant_xp", lambda *args: {"awarded": False})

    with db_cursor(commit=True) as cursor:
        skip_unless_tables(cursor, "members", "boards", "posts", "comments", "notifications",
                           "career_posts", "recruits")
        cursor.execute("""SELECT 1 FROM information_schema.columns
                          WHERE table_name = 'comments' AND column_name = 'reply_to_comment_id'""")
        if cursor.fetchone() is None:
            pytest.skip("041_comment_reply_target.sql이 적용되지 않은 테스트 DB")
        marker = f"t153-{uuid.uuid4().hex[:10]}"
        members = {}
        for key in ("writer", "root", "replier", "other", "anon", "gone"):
            cursor.execute("INSERT INTO members (nickname, discord_id) VALUES (%s, %s) RETURNING member_id",
                           (f"{key}-{marker}", f"{key}-{marker}"))
            members[key] = cursor.fetchone()["member_id"]
        cursor.execute("INSERT INTO boards (board_name, created_by) VALUES (%s, %s) RETURNING board_id",
                       (marker, members["writer"]))
        board_id = cursor.fetchone()["board_id"]

        def new_post(post_type, board=None):
            cursor.execute("""INSERT INTO posts (board_id, author_member_id, post_type, title, body, post_status)
                              VALUES (%s, %s, %s, %s, 'body', 'PUBLISHED') RETURNING post_id""",
                           (board, members["writer"], post_type, f"{post_type}-{marker}"))
            return cursor.fetchone()["post_id"]

        posts = {"board": new_post("BOARD", board_id), "board2": new_post("BOARD", board_id),
                 "career": new_post("CAREER"), "meetup": new_post("RECRUIT")}
        cursor.execute("""INSERT INTO career_posts (post_id, category_code, subcategory_code)
                          VALUES (%s, 'talk', 'general')""", (posts["career"],))
        # talk 글의 상세 행도 같은 트랜잭션에서 만든다. 취업 DB 통합(037~040) 이후에는 상세 없는 talk 글이
        # 커밋되지 않는다. develop 스키마(career_talks 테이블)와 통합 스키마(career_talks 뷰) 모두 같은 SQL로 동작한다.
        cursor.execute("""INSERT INTO career_talks (post_id, job_category_code, current_status)
                          VALUES (%s, 'DEV', 'PREPARING')""", (posts["career"],))
        cursor.execute("""INSERT INTO recruits (post_id, recruit_mode, category, capacity, state)
                          VALUES (%s, 'short', 'study', 5, 'OPEN') RETURNING recruit_id""", (posts["meetup"],))
        recruit_id = cursor.fetchone()["recruit_id"]

    engine = create_engine(url.replace("postgresql://", "postgresql+psycopg://", 1))
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    try:
        yield {"board_id": board_id, "posts": posts, "recruit_id": recruit_id, "members": members,
               "Session": Session, "marker": marker}
    finally:
        engine.dispose()
        with db_cursor(commit=True) as cursor:
            ids, post_ids = list(members.values()), list(posts.values())
            cursor.execute("DELETE FROM notifications WHERE receiver_member_id = ANY(%s) OR actor_member_id = ANY(%s)",
                           (ids, ids))
            # 답글 대상 FK(NO ACTION) 때문에 답글부터 지운다.
            cursor.execute("DELETE FROM comments WHERE post_id = ANY(%s) AND parent_comment_id IS NOT NULL", (post_ids,))
            cursor.execute("DELETE FROM comments WHERE post_id = ANY(%s)", (post_ids,))
            cursor.execute("DELETE FROM recruits WHERE recruit_id = %s", (recruit_id,))
            # 취업 분류·상세는 posts 삭제에 CASCADE로 함께 지워진다(develop: career_posts→career_talks,
            # 통합 스키마: career). 통합 후 career_posts는 직접 DELETE를 막는 뷰라 따로 지우지 않는다.
            cursor.execute("DELETE FROM posts WHERE post_id = ANY(%s)", (post_ids,))
            cursor.execute("DELETE FROM boards WHERE board_id = %s", (board_id,))
            cursor.execute("DELETE FROM members WHERE member_id = ANY(%s)", (ids,))
        for pool_owner in (db_connect, backend_db_connect):
            pool_owner.close_pool()


class Path:
    """세 댓글 경로를 같은 방식으로 호출하는 얇은 도우미. 응답은 게시판 키(id)로 맞춘다."""

    def __init__(self, env, name, post_key=None):
        self.env, self.name = env, name
        self.post_id = env["posts"][post_key or name]

    def write(self, member, body="댓글", parent=None, reply_to=None, anonymous=False):
        m = self.env["members"][member]
        if self.name == "board":
            return board_service.create_comment(self.env["board_id"], self.post_id, body, m, parent, anonymous, reply_to)
        if self.name == "career":
            return career_reaction_service.create_comment(self.post_id, body, m, parent, anonymous, reply_to)
        assert not anonymous, "모임 댓글은 익명 작성이 없다"
        with self.env["Session"]() as db:
            row = recruit_comment.create_comment(
                db, self.env["recruit_id"], m,
                RecruitCommentCreate(body=body, parent_comment_id=parent, reply_to_comment_id=reply_to))
        return {**row, "id": row["comment_id"]}

    def list(self, member="other"):
        m = self.env["members"][member]
        if self.name == "board":
            return board_service.list_comments(self.env["board_id"], self.post_id, m)
        if self.name == "career":
            return career_reaction_service.list_comments(self.post_id, m)
        with self.env["Session"]() as db:
            return [{**row, "id": row["comment_id"]} for row in recruit_comment.get_comments(db, self.env["recruit_id"], m)]

    def update(self, comment_id, member, body):
        m = self.env["members"][member]
        if self.name == "meetup":
            with self.env["Session"]() as db:
                row = recruit_comment.update_comment(db, self.env["recruit_id"], comment_id, m,
                                                     RecruitCommentUpdate(body=body))
            return {**row, "id": row["comment_id"]}
        # 취업 댓글도 게시판과 같은 공통 수정 서비스를 쓴다(board_id NULL 404 수정 후 우회 없음).
        return board_service.update_comment(comment_id, body, m)

    def delete(self, comment_id, member):
        m = self.env["members"][member]
        if self.name == "meetup":
            with self.env["Session"]() as db:
                recruit_comment.delete_comment(db, self.env["recruit_id"], comment_id, m)
        else:
            # 취업 댓글도 공통 삭제 서비스를 쓴다(board_id NULL 404 수정 후 우회 없음).
            board_service.delete_comment(comment_id, m)


def stored(comment_id):
    with db_cursor(read_only=True) as cursor:
        cursor.execute("SELECT parent_comment_id, reply_to_comment_id FROM comments WHERE comment_id = %s", (comment_id,))
        row = cursor.fetchone()
    return row["parent_comment_id"], row["reply_to_comment_id"]


def notifications(comment_id):
    """그 댓글로 저장된 알림 (받는 사람, 종류) 목록."""
    with db_cursor(read_only=True) as cursor:
        cursor.execute("""SELECT receiver_member_id, notification_type FROM notifications
                          WHERE comment_id = %s ORDER BY notification_id""", (comment_id,))
        return [(row["receiver_member_id"], row["notification_type"]) for row in cursor.fetchall()]


def counts(post_id):
    with db_cursor(read_only=True) as cursor:
        cursor.execute("""SELECT (SELECT COUNT(*) FROM comments WHERE post_id = %(p)s) AS comments,
                                 (SELECT COUNT(*) FROM notifications WHERE post_id = %(p)s) AS notifications""",
                       {"p": post_id})
        row = cursor.fetchone()
    return row["comments"], row["notifications"]


@pytest.mark.parametrize("path_name", PATHS)
def test_reply_chain_storage_and_receivers_match_on_every_path(env, path_name):
    """원댓글 → 기존 방식 대댓글 → 대댓글의 답글 → 답글의 답글 → 자기 답글. 세 경로 모두 같은 결과."""
    path, m = Path(env, path_name), env["members"]
    a = path.write("root", "원댓글")
    b = path.write("replier", "기존 방식 대댓글", parent=a["id"])           # reply_to NULL
    c = path.write("other", "대댓글에 답글", reply_to=b["id"])
    d = path.write("root", "답글의 답글", reply_to=c["id"])
    e = path.write("root", "자기 답글에 답글", reply_to=d["id"])
    f = path.write("replier", "두 필드 일치", parent=a["id"], reply_to=c["id"])

    # 저장값: 모두 원댓글 a 아래 2단계, 기존 방식은 답글 대상 NULL
    assert [stored(x["id"]) for x in (a, b, c, d, e, f)] == [
        (None, None), (a["id"], None), (a["id"], b["id"]), (a["id"], c["id"]), (a["id"], d["id"]), (a["id"], c["id"]),
    ]
    # 알림: 원댓글 → 글 작성자, 답글 → 직접 대상 작성자 한 명, 자기 답글 → 없음
    assert notifications(a["id"]) == [(m["writer"], "COMMENT")]
    assert notifications(b["id"]) == [(m["root"], "REPLY")]          # NULL → 원댓글 작성자
    assert notifications(c["id"]) == [(m["replier"], "REPLY")]       # 원댓글 작성자(root) 아님
    assert notifications(d["id"]) == [(m["other"], "REPLY")]
    assert notifications(e["id"]) == []                               # 자기 자신
    assert notifications(f["id"]) == [(m["other"], "REPLY")]

    # 작성 응답과 목록: 대상 ID·이름, 정렬(원댓글 → 작성 순 답글)
    assert (c["reply_to_comment_id"], c["reply_to_is_deleted"]) == (b["id"], False)
    assert c["reply_to_author_name"].startswith("replier-")
    rows = {row["id"]: row for row in path.list()}
    assert list(rows) == [a["id"], b["id"], c["id"], d["id"], e["id"], f["id"]]
    assert rows[a["id"]]["reply_to_comment_id"] is None
    assert rows[b["id"]]["reply_to_comment_id"] == a["id"]
    assert rows[b["id"]]["reply_to_author_name"].startswith("root-")
    assert rows[d["id"]]["reply_to_author_name"].startswith("other-")

    # 수정해도 관계 유지
    updated = path.update(d["id"], "root", "수정한 답글")
    assert updated["body"] == "수정한 답글" and stored(d["id"]) == (a["id"], c["id"])
    assert (updated["parent_comment_id"], updated["reply_to_comment_id"]) == (a["id"], c["id"])


@pytest.mark.parametrize("path_name", PATHS)
def test_invalid_targets_create_no_comment_and_no_notification(env, path_name):
    path = Path(env, path_name)
    other_path_root = Path(env, "board", "board2").write("root", "다른 글 댓글")
    a = path.write("root", "원댓글")
    b = path.write("replier", "대댓글", reply_to=a["id"])
    second = path.write("root", "두 번째 원댓글")

    before = counts(path.post_id)
    legacy_reply_status = 400 if path_name == "meetup" else 422    # 기존 경로별 오류 정책 유지
    for kwargs, status in [
        (dict(reply_to=other_path_root["id"]), 422),                 # 다른 게시글의 댓글
        (dict(reply_to=999_999_999), 404),                            # 없는 댓글
        (dict(parent=second["id"], reply_to=b["id"]), 422),          # 다른 스레드와 충돌
        (dict(parent=b["id"]), legacy_reply_status),                  # 기존 방식으로 대댓글 ID
    ]:
        with pytest.raises(HTTPException) as error:
            path.write("other", "거부", **kwargs)
        assert error.value.status_code == status, kwargs

    path.delete(b["id"], "replier")
    with pytest.raises(HTTPException) as error:
        path.write("other", "삭제된 대상", reply_to=b["id"])
    assert error.value.status_code == 404
    assert counts(path.post_id) == before


@pytest.mark.parametrize("path_name", PATHS)
def test_reply_to_live_reply_under_deleted_root(env, path_name):
    """원댓글이 삭제된 자리표시여도 살아 있는 대댓글에는 답글을 달 수 있고 스레드에 남는다."""
    path, m = Path(env, path_name), env["members"]
    a = path.write("root", "원댓글")
    b = path.write("replier", "대댓글", reply_to=a["id"])
    path.delete(a["id"], "root")
    c = path.write("other", "삭제된 원댓글 아래 답글", reply_to=b["id"])
    assert stored(c["id"]) == (a["id"], b["id"])
    assert notifications(c["id"]) == [(m["replier"], "REPLY")]
    rows = path.list()
    assert [row["id"] for row in rows] == [a["id"], b["id"], c["id"]]
    assert rows[0]["is_deleted"] is True and rows[0]["body"] == ""
    assert rows[1]["reply_to_is_deleted"] is True and rows[1]["reply_to_author_name"] is None


@pytest.mark.parametrize("path_name", ["board", "career"])
def test_anonymous_target_receives_without_identity_exposure(env, path_name):
    path, m = Path(env, path_name), env["members"]
    a = path.write("root", "원댓글")
    hidden = path.write("anon", "익명 대댓글", reply_to=a["id"], anonymous=True)
    reply = path.write("other", "익명에게 답글", reply_to=hidden["id"])
    assert notifications(reply["id"]) == [(m["anon"], "REPLY")]      # 내부에서는 실제 회원으로 찾음
    assert reply["reply_to_author_name"] == "익명"
    rows = path.list()
    assert all("anon-" not in str(value) for row in rows for value in row.values())   # 실제 닉네임 없음
    assert all(row["author_id"] != m["anon"] for row in rows)                         # 실제 회원 ID 없음
    assert {row["id"]: row for row in rows}[reply["id"]]["reply_to_author_name"] == "익명"


@pytest.mark.parametrize("path_name", PATHS)
def test_withdrawn_target_gets_no_notification(env, path_name):
    path, m = Path(env, path_name), env["members"]
    a = path.write("root", "원댓글")
    gone = path.write("gone", "곧 탈퇴할 회원의 대댓글", reply_to=a["id"])
    with db_cursor(commit=True) as cursor:
        cursor.execute("UPDATE members SET member_status = 'WITHDRAWN' WHERE member_id = %s", (m["gone"],))
    reply = path.write("other", "탈퇴 회원에게 답글", reply_to=gone["id"])
    assert stored(reply["id"]) == (a["id"], gone["id"])
    assert notifications(reply["id"]) == []
    assert reply["reply_to_author_name"] == "탈퇴한 사용자"


def test_writer_trusts_stored_relation_not_arguments(env):
    """인자가 저장된 댓글과 다르거나, 저장된 관계가 스레드 규칙을 어기면 알림을 만들지 않는다."""
    path, m = Path(env, "board"), env["members"]
    a = path.write("root", "원댓글")
    b = path.write("replier", "대댓글", reply_to=a["id"])
    other_root = path.write("other", "다른 원댓글")
    # 서비스를 거치지 않고 다른 스레드 댓글을 대상으로 가리키는 행을 직접 만든다(041 CHECK로는 막히지 않는 경우).
    with db_cursor(commit=True) as cursor:
        cursor.execute("""INSERT INTO comments (post_id, author_member_id, body, parent_comment_id, reply_to_comment_id)
                          VALUES (%s, %s, '변조', %s, %s) RETURNING comment_id""",
                       (path.post_id, m["writer"], a["id"], other_root["id"]))
        forged = cursor.fetchone()["comment_id"]
    assert save_comment_notification(path.post_id, forged, m["writer"], a["id"]) == 0
    assert notifications(forged) == []

    c = path.write("other", "정상 답글", reply_to=b["id"])
    assert notifications(c["id"]) == [(m["replier"], "REPLY")]
    # 잘못된 인자(원댓글·작성자 불일치)와 같은 댓글 재호출은 행을 늘리지 않는다.
    assert save_comment_notification(path.post_id, c["id"], m["other"], other_root["id"]) == 0
    assert save_comment_notification(path.post_id, c["id"], m["root"], a["id"]) == 0
    assert save_comment_notification(path.post_id, c["id"], m["other"], a["id"]) == 0   # 중복 방지
    assert notifications(c["id"]) == [(m["replier"], "REPLY")]


@pytest.mark.parametrize("path_name", PATHS)
def test_withdrawn_post_author_gets_no_comment_notification(env, path_name):
    """원댓글(COMMENT) 알림도 받는 사람(게시글 작성자)이 탈퇴 회원이면 만들지 않는다."""
    path, m = Path(env, path_name), env["members"]
    before = path.write("root", "탈퇴 전 원댓글")
    assert notifications(before["id"]) == [(m["writer"], "COMMENT")]      # 대조군: 기존 COMMENT 동작
    with db_cursor(commit=True) as cursor:
        cursor.execute("UPDATE members SET member_status = 'WITHDRAWN' WHERE member_id = %s", (m["writer"],))
    after = path.write("root", "탈퇴 후 원댓글")
    assert stored(after["id"]) == (None, None)
    assert notifications(after["id"]) == []


# ---------------------------------------------------------------------------
# 실제 HTTP API: 프론트엔드가 보내는 JSON 그대로, 실제 세션 쿠키 인증으로 요청한다.
# 모임 라우터의 DB 세션(get_db)만 이 테스트 DB 세션으로 바꾼다(앱 기본 엔진은 conftest의 차단 주소).
# ---------------------------------------------------------------------------
@pytest.fixture
def http(env):
    from app.main import app

    def test_db():
        db = env["Session"]()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = test_db
    client = TestClient(app)
    try:
        yield client
    finally:
        client.close()
        app.dependency_overrides.pop(get_db, None)


def comments_url(env, path_name):
    if path_name == "board":
        return f"/api/boards/{env['board_id']}/posts/{env['posts']['board']}/comments"
    if path_name == "career":
        return f"/api/career/posts/{env['posts']['career']}/comments"
    return f"/api/recruits/{env['recruit_id']}/comments"


def as_member(client, env, member):
    client.cookies.clear()  # 앞 응답의 세션 쿠키가 다른 회원 요청에 섞이지 않게
    return session_headers(env["members"][member], f"{member}-{env['marker']}")


def frontend_payload(path_name, body, reply_to=None):
    """frontend/src/services/*Api.js가 만드는 요청 본문과 같은 모양."""
    payload = {"body": body, "parent_comment_id": None}
    if path_name != "meetup":
        payload["is_anonymous"] = False
    if reply_to is not None:
        payload["reply_to_comment_id"] = reply_to
    return payload


def http_write(client, env, path_name, member, body, reply_to=None):
    response = client.post(comments_url(env, path_name), json=frontend_payload(path_name, body, reply_to),
                           headers=as_member(client, env, member))
    assert response.is_success, response.text
    data = response.json()
    return {**data, "id": data.get("id", data.get("comment_id"))}


@pytest.mark.parametrize("path_name", PATHS)
def test_http_reply_to_reply_is_saved_listed_and_notified(env, http, path_name):
    m = env["members"]
    a = http_write(http, env, path_name, "root", "원댓글")
    b = http_write(http, env, path_name, "replier", "원댓글에 답글", reply_to=a["id"])
    c = http_write(http, env, path_name, "other", "대댓글에 답글", reply_to=b["id"])

    # 저장: 원댓글은 서버가 계산, 원댓글에 바로 단 답글도 reply_to = 원댓글
    assert [stored(x["id"]) for x in (a, b, c)] == [(None, None), (a["id"], a["id"]), (a["id"], b["id"])]
    # 작성 응답
    assert (c["parent_comment_id"], c["reply_to_comment_id"], c["reply_to_is_deleted"]) == (a["id"], b["id"], False)
    assert c["reply_to_author_name"].startswith("replier-")
    assert c["body"] == "대댓글에 답글"                                   # 본문에 @이름을 붙이지 않음
    # 알림: 직접 대상 작성자에게만
    assert notifications(b["id"]) == [(m["root"], "REPLY")]
    assert notifications(c["id"]) == [(m["replier"], "REPLY")]

    # 목록 조회 응답도 같은 값
    listed = http.get(comments_url(env, path_name), headers=as_member(http, env, "other"))
    assert listed.status_code == 200, listed.text
    rows = {row.get("id", row.get("comment_id")): row for row in listed.json()}
    assert list(rows) == [a["id"], b["id"], c["id"]]
    assert rows[c["id"]]["reply_to_comment_id"] == b["id"]
    assert rows[c["id"]]["reply_to_author_name"] == c["reply_to_author_name"]
    assert rows[b["id"]]["reply_to_comment_id"] == a["id"]


@pytest.mark.parametrize("path_name", PATHS)
def test_http_invalid_target_and_relation_update_rejected(env, http, path_name):
    a = http_write(http, env, path_name, "root", "원댓글")
    b = http_write(http, env, path_name, "replier", "대댓글", reply_to=a["id"])
    elsewhere = Path(env, "board", "board2").write("root", "다른 글 댓글")
    before = counts(env["posts"][path_name])

    response = http.post(comments_url(env, path_name), json=frontend_payload(path_name, "거부", elsewhere["id"]),
                         headers=as_member(http, env, "other"))
    assert response.status_code == 422, response.text
    response = http.post(comments_url(env, path_name), json=frontend_payload(path_name, "거부", 999_999_999),
                         headers=as_member(http, env, "other"))
    assert response.status_code == 404, response.text
    assert counts(env["posts"][path_name]) == before

    # 수정 요청에 관계 필드를 넣으면 422, 저장된 관계는 그대로 (취업 댓글도 공통 PATCH를 씀)
    edit_url = (f"/api/recruits/{env['recruit_id']}/comments/{b['id']}" if path_name == "meetup"
                else f"/api/comments/{b['id']}")
    response = http.patch(edit_url, json={"body": "위치 변경 시도", "reply_to_comment_id": b["id"]},
                          headers=as_member(http, env, "replier"))
    assert response.status_code == 422, response.text
    assert stored(b["id"]) == (a["id"], a["id"])


def comment_url(env, path_name, comment_id):
    """수정·삭제 주소. 게시판·취업은 공통 /api/comments, 모임은 모임 경로."""
    if path_name == "meetup":
        return f"/api/recruits/{env['recruit_id']}/comments/{comment_id}"
    return f"/api/comments/{comment_id}"


def http_list(client, env, path_name, member):
    response = client.get(comments_url(env, path_name), headers=as_member(client, env, member))
    assert response.status_code == 200, response.text
    return {row.get("id", row.get("comment_id")): row for row in response.json()}


def deleted_at(comment_id):
    with db_cursor(read_only=True) as cursor:
        cursor.execute("SELECT deleted_at FROM comments WHERE comment_id = %s", (comment_id,))
        return cursor.fetchone()["deleted_at"]


@pytest.mark.parametrize("path_name", PATHS)
def test_http_author_edits_and_deletes_others_rejected(env, http, path_name):
    """실제 HTTP 수정·삭제: 작성자만 성공(취업 포함), 타인은 403, 삭제 후 목록·@표시·답글 규칙 유지."""
    a = http_write(http, env, path_name, "root", "원댓글")
    b = http_write(http, env, path_name, "replier", "대댓글", reply_to=a["id"])
    c = http_write(http, env, path_name, "other", "대댓글에 답글", reply_to=b["id"])

    # 버튼 노출 근거: 서버 is_owner는 본인 댓글에만 true
    as_replier = http_list(http, env, path_name, "replier")
    assert [as_replier[x]["is_owner"] for x in (a["id"], b["id"], c["id"])] == [False, True, False]

    # 타인 수정·삭제 → 403, 내용·삭제 상태 그대로
    response = http.patch(comment_url(env, path_name, b["id"]), json={"body": "남의 댓글 수정"},
                          headers=as_member(http, env, "other"))
    assert response.status_code == 403, response.text
    response = http.delete(comment_url(env, path_name, b["id"]), headers=as_member(http, env, "other"))
    assert response.status_code == 403, response.text
    assert deleted_at(b["id"]) is None

    # 작성자 수정 → 성공, 본문만 바뀌고 관계 유지
    response = http.patch(comment_url(env, path_name, b["id"]), json={"body": "수정한 대댓글"},
                          headers=as_member(http, env, "replier"))
    assert response.status_code == 200, response.text
    assert response.json()["body"] == "수정한 대댓글"
    assert stored(b["id"]) == (a["id"], a["id"])

    # 작성자 삭제 → 성공(논리 삭제)
    response = http.delete(comment_url(env, path_name, b["id"]), headers=as_member(http, env, "replier"))
    assert response.is_success, response.text
    assert deleted_at(b["id"]) is not None
    # 이미 삭제된 댓글을 다시 지우거나 고치면 404
    response = http.delete(comment_url(env, path_name, b["id"]), headers=as_member(http, env, "replier"))
    assert response.status_code == 404, response.text

    # 삭제 후 다시 조회(새로고침과 같음): 지운 대댓글은 빠지고, 그 댓글을 대상으로 한 답글은 '삭제된 대상'
    rows = http_list(http, env, path_name, "other")
    assert list(rows) == [a["id"], c["id"]]
    assert stored(c["id"]) == (a["id"], b["id"])                       # 남은 답글의 관계 유지
    assert (rows[c["id"]]["reply_to_comment_id"], rows[c["id"]]["reply_to_is_deleted"],
            rows[c["id"]]["reply_to_author_name"]) == (b["id"], True, None)

    # 삭제된 댓글에는 답글 불가 → 404, 댓글 수 변화 없음
    before = counts(env["posts"][path_name])
    response = http.post(comments_url(env, path_name), json=frontend_payload(path_name, "삭제된 댓글에 답글", b["id"]),
                         headers=as_member(http, env, "other"))
    assert response.status_code == 404, response.text
    assert counts(env["posts"][path_name]) == before

    # 원댓글 삭제 → 살아 있는 답글이 있으므로 자리표시로 남음
    response = http.delete(comment_url(env, path_name, a["id"]), headers=as_member(http, env, "root"))
    assert response.is_success, response.text
    rows = http_list(http, env, path_name, "root")
    assert list(rows) == [a["id"], c["id"]]
    assert rows[a["id"]]["is_deleted"] is True and rows[a["id"]]["is_owner"] is False


def test_common_comment_api_still_rejects_non_career_posts_without_board(env, http):
    """취업 글만 board_id NULL 예외다. 모임 댓글(board_id NULL)을 공통 API로 고치거나 지울 수는 없다(기존 404 유지)."""
    meetup = http_write(http, env, "meetup", "root", "모임 댓글")
    response = http.patch(f"/api/comments/{meetup['id']}", json={"body": "공통 API로 수정"},
                          headers=as_member(http, env, "root"))
    assert response.status_code == 404, response.text
    response = http.delete(f"/api/comments/{meetup['id']}", headers=as_member(http, env, "root"))
    assert response.status_code == 404, response.text
    assert deleted_at(meetup["id"]) is None
