"""Actual PostgreSQL casts, privacy, vote and attachment isolation without views.

Only connection-local TEMP tables are created; no migration (especially 052) runs.
Requires an explicitly configured disposable local test database.
"""

from datetime import date
import json

import pytest
from app.repositories import career_repository as repo
from backend.tests.local_test_db import require_local_test_db_url


@pytest.fixture
def cursor(monkeypatch):
    url = require_local_test_db_url()
    import psycopg
    from psycopg.rows import dict_row

    monkeypatch.setattr(repo, "attach_post_reactions", lambda c, row, member: row)
    monkeypatch.setattr(repo, "attach_list_reactions", lambda c, rows: rows)
    with psycopg.connect(url, row_factory=dict_row) as conn:
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TEMP TABLE members(member_id bigint PRIMARY KEY, nickname text, member_status text);
                    CREATE TEMP TABLE posts(post_id bigint PRIMARY KEY, author_member_id bigint,
                        title text, body text, post_type text, is_anonymous boolean,
                        created_at timestamptz DEFAULT now(), updated_at timestamptz, deleted_at timestamptz);
                    CREATE TEMP TABLE career(post_id bigint PRIMARY KEY, category_code text,
                        subcategory_code text, details jsonb, poll_options jsonb DEFAULT '[]');
                    CREATE TEMP TABLE career_lab_poll_votes(post_id bigint, member_id bigint, option_id bigint,
                        PRIMARY KEY(post_id, member_id));
                    CREATE TEMP TABLE post_attachments(attachment_id bigserial PRIMARY KEY, post_id bigint,
                        attachment_scope text, original_filename text, stored_path text, attachment_type text,
                        content_type text, file_size_bytes bigint, display_order integer,
                        created_at timestamptz DEFAULT now());
                    INSERT INTO members VALUES (1, 'author', 'ACTIVE');
                """)
                details = [
                    {"company_name": "private", "is_company_private": True, "process_date": "2024-02-29"},
                    {"job_category_code": "DEV", "current_status": "JOB_SEEKING"},
                    {"experience_years": 3, "company_name": ""},
                    {"post_type": "DISCUSSION", "is_resolved": False, "guide_advice": ""},
                ]
                for post_id, (category, detail) in enumerate(zip(("reviews", "talk", "lounge", "lab"), details), 1):
                    cur.execute("INSERT INTO posts(post_id,author_member_id,title,body,post_type,is_anonymous) VALUES (%s,1,'title','body','CAREER',true)", (post_id,))
                    cur.execute("INSERT INTO career(post_id,category_code,subcategory_code,details) VALUES (%s,%s,'test',%s::jsonb)", (post_id, category, json.dumps(detail)))
                yield cur
        finally:
            conn.rollback()


def test_detail_types_privacy_and_search(cursor):
    own = repo.get_review(cursor, 1, 1)
    other = repo.get_review(cursor, 1, 2)
    assert own["process_date"] == date(2024, 2, 29)
    assert own["is_company_private"] is True and own["company_name"] == "private"
    assert other["company_name"] is None and other["author_name"] == "익명"
    assert repo.list_reviews(cursor, 2, q="private")["total"] == 0
    assert repo.list_reviews(cursor, 1, q="private")["total"] == 1
    assert repo.get_talk(cursor, 2, 1)["current_status"] == "JOB_SEEKING"
    lounge = repo.get_lounge(cursor, 3, 1)
    assert lounge["experience_years"] == 3 and lounge["company_name"] == ""
    cursor.execute("UPDATE career SET details = details || '{\"process_date\":null}' WHERE post_id=1")
    assert repo.get_review(cursor, 1, 1)["process_date"] is None


def test_votes_resolution_and_soft_delete(cursor):
    cursor.execute("UPDATE career SET poll_options = %s::jsonb WHERE post_id=4", (json.dumps([
        {"option_id": 10, "option_text": "A", "display_order": 1},
        {"option_id": 20, "option_text": "B", "display_order": 2},
    ]),))
    assert repo.get_lab_poll_for_update(cursor, 4)["post_type"] == "DISCUSSION"
    assert repo.lab_poll_option_exists(cursor, 4, 10)
    assert not repo.lab_poll_option_exists(cursor, 3, 10)
    assert repo.create_lab_vote(cursor, 4, 1, 10)
    assert not repo.create_lab_vote(cursor, 4, 1, 20)
    lab = repo.get_lab(cursor, 4, 1)
    assert lab["total_votes"] == 1 and lab["my_vote_option_id"] == 10
    assert lab["poll_options"][0] == {"option_id": 10, "option_text": "A", "display_order": 1, "vote_count": 1}
    assert not repo.update_lab_resolved(cursor, 4, True)
    cursor.execute("UPDATE career SET details = details || '{\"post_type\":\"QUESTION\"}' WHERE post_id=4")
    assert repo.update_lab_resolved(cursor, 4, True)
    assert repo.get_lab(cursor, 4, 1)["is_resolved"] is True
    assert not repo.delete_lab(cursor, 4, 2)
    assert repo.delete_lab(cursor, 4, 1)
    assert repo.get_lab(cursor, 4, 1) is None


def test_attachment_scope_isolation(cursor):
    cursor.execute("INSERT INTO post_attachments(post_id,attachment_scope,display_order) VALUES (2,'BOARD',1) RETURNING attachment_id")
    board_id = cursor.fetchone()["attachment_id"]
    assert repo.get_next_talk_attachment_order(cursor, 2) == 1
    assert repo.get_talk_attachment(cursor, 2, board_id) is None
    assert repo.delete_talk_attachment(cursor, 2, board_id) is None
    item = repo.create_talk_attachment(cursor, 2, "file.png", "stored", "IMAGE", "image/png", 10, 1)
    assert len(repo.list_talk_attachments(cursor, 2)) == 1
    assert repo.get_talk_attachment(cursor, 2, item["attachment_id"])["stored_path"] == "stored"
    assert repo.get_next_talk_attachment_order(cursor, 2) == 2
    assert repo.delete_talk_attachment(cursor, 2, item["attachment_id"])
    assert repo.list_talk_attachments(cursor, 2) == []
