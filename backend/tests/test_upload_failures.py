"""업로드 검증과 부분 파일·DB 실패 정리를 임시 디렉터리에서 확인한다."""

import asyncio
import re
from io import BytesIO
from pathlib import Path

import pytest
from fastapi import HTTPException, UploadFile
from starlette.datastructures import Headers
from starlette.routing import Mount

from app.core import uploads
from app.services import board_service

PNG = b"\x89PNG\r\n\x1a\nexample"


def test_post_image_limits_match_frontend_and_schema():
    root = Path(__file__).resolve().parents[2]
    frontend = (root / "frontend/src/hooks/board/useBoardForms.js").read_text(encoding="utf-8")
    limits = frontend.split("export const postImageLimits = {", 1)[1].split("}", 1)[0]
    assert int(re.search(r"count:\s*(\d+)", limits)[1]) == uploads.MAX_POST_IMAGES
    assert int(re.search(r"sizeMb:\s*(\d+)", limits)[1]) * 1024**2 == uploads.MAX_IMAGE_SIZE
    assert set(re.findall(r"'(image/[^']+)'", limits)) == set(uploads.ALLOWED)

    sql = (root / "database/sql/001_board_mvp.sql").read_text(encoding="utf-8")
    schema = sql.split("CREATE TABLE IF NOT EXISTS post_images", 1)[1]
    assert int(re.search(r"file_size BETWEEN 1 AND (\d+)", schema)[1]) == uploads.MAX_IMAGE_SIZE
    assert int(re.search(r"display_order BETWEEN 0 AND (\d+)", schema)[1]) + 1 == uploads.MAX_POST_IMAGES


@pytest.fixture
def upload_root(tmp_path, monkeypatch):
    monkeypatch.setattr(uploads, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(uploads, "UPLOAD_DIR", tmp_path / "uploads" / "posts")
    return tmp_path


def image(data=PNG, content_type="image/png", filename="test.png"):
    return UploadFile(
        BytesIO(data),
        filename=filename,
        headers=Headers({"content-type": content_type}),
    )


def test_save_images_unique_names_and_metadata(upload_root):
    saved = asyncio.run(uploads.save_images([image(), image()]))
    assert saved[0]["stored_name"] != saved[1]["stored_name"]
    assert [row["original_name"] for row in saved] == ["test.png", "test.png"]
    assert all((upload_root / "uploads" / row["stored_name"]).read_bytes() == PNG for row in saved)
    assert all(row["stored_name"].startswith("posts/") for row in saved)
    uploads.remove_saved_images(saved)
    assert not list(uploads.UPLOAD_DIR.glob("*"))


@pytest.mark.parametrize(
    "files",
    [
        [image() for _ in range(4)],
        [image(b"fake")],
        [image(PNG, "text/plain")],
        [image(b"x" * (uploads.MAX_IMAGE_SIZE + 1))],
    ],
)
def test_bad_upload_returns_422(upload_root, files):
    with pytest.raises(HTTPException) as error:
        asyncio.run(uploads.save_images(files))
    assert error.value.status_code == 422
    assert not list(uploads.UPLOAD_DIR.glob("*"))


def test_later_validation_failure_cleans_previous_file(upload_root):
    with pytest.raises(HTTPException):
        asyncio.run(uploads.save_images([image(), image(b"invalid")]))
    assert not list(uploads.UPLOAD_DIR.glob("*"))


def test_partial_write_failure_cleans_file(upload_root, monkeypatch):
    original = Path.write_bytes

    def failing_write(path, data):
        original(path, data[:2])
        raise OSError("partial write")

    monkeypatch.setattr(Path, "write_bytes", failing_write)
    with pytest.raises(OSError):
        asyncio.run(uploads.save_images([image()]))
    assert not list(uploads.UPLOAD_DIR.glob("*"))


def test_cleanup_does_not_follow_outside_path(upload_root):
    outside = upload_root / "keep.png"
    outside.write_bytes(PNG)
    with pytest.raises(ValueError):
        uploads.post_image_storage.delete("../keep.png")
    assert outside.exists()


def test_http_upload_db_failure_cleans_file(client, upload_root, monkeypatch):
    def fail(*args):
        raise RuntimeError("database failed before commit")

    monkeypatch.setattr(board_service, "create_post", fail)
    response = client.post(
        "/api/boards/1/posts",
        data={"title": "제목", "body": "본문"},
        files={"images": ("test.png", PNG, "image/png")},
    )
    assert response.status_code == 503
    assert not list(uploads.UPLOAD_DIR.glob("*"))


def test_uploaded_image_static_url(client, upload_root, monkeypatch):
    """기존 /uploads/posts 경로가 저장한 이미지 바이트를 그대로 제공한다."""
    from app.main import app

    saved = asyncio.run(uploads.save_images([image()]))
    # FastAPI 버전별 포함 라우터 객체 구조와 무관하게 공개 Mount 타입으로 /uploads를 찾는다.
    static = next(
        route.app
        for route in app.routes
        if isinstance(route, Mount) and route.path == "/uploads"
    )
    directory = upload_root / "uploads"
    monkeypatch.setattr(static, "directory", str(directory))
    monkeypatch.setattr(static, "all_directories", [str(directory)])
    response = client.get("/uploads/" + saved[0]["stored_name"])
    assert response.status_code == 200
    assert response.content == PNG
    assert response.headers["content-type"] == "image/png"


# =========================================================
# 새 글 등록: 저장소 쓰기·정리를 워커 스레드에서 실행 (PR #125 후속)
# =========================================================

def _slow_storage(monkeypatch, delay):
    """저장소 쓰기를 지연시키는 대역. 실제 쓰기 횟수와 실행 스레드를 기록한다."""
    import threading
    import time

    real_save = uploads.post_image_storage.save
    calls = []

    def slow_save(key, data, content_type):
        calls.append(threading.current_thread() is threading.main_thread())
        time.sleep(delay)
        real_save(key, data, content_type)

    monkeypatch.setattr(uploads.post_image_storage, "save", slow_save)
    return calls


def test_create_post_storage_write_does_not_block_event_loop(upload_root, monkeypatch):
    """저장소 쓰기가 0.6초 걸려도 같은 이벤트 루프의 독립 요청은 바로 응답한다."""
    import time

    import httpx
    from app.core.auth import get_current_member_id
    from app.main import app

    calls = _slow_storage(monkeypatch, 0.6)
    monkeypatch.setattr(
        board_service, "create_post",
        lambda board_id, title, body, member_id, saved, is_anonymous: {
            "id": 1, "board_id": board_id, "title": title, "body": body,
            "author_id": member_id, "author_name": "작성자", "is_anonymous": is_anonymous,
            "created_at": "2026-11-15T00:00:00Z", "updated_at": "2026-11-15T00:00:00Z",
            "comment_count": 0, "is_owner": True, "like_count": 0, "liked_by_me": False,
            "scrapped_by_me": False,
            "images": [{"id": i + 1, "url": f"/uploads/{img['stored_name']}", "original_name": img["original_name"]}
                       for i, img in enumerate(saved)],
        },
    )
    app.dependency_overrides[get_current_member_id] = lambda: 1

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            upload = asyncio.create_task(client.post(
                "/api/boards/1/posts",
                data={"title": "제목", "body": "본문"},
                files=[("images", ("a.png", PNG, "image/png")), ("images", ("b.png", PNG, "image/png"))],
            ))
            await asyncio.sleep(0.15)  # 업로드가 저장소 쓰기에 들어간 뒤
            started = time.perf_counter()
            health = await client.get("/health")
            health_elapsed = time.perf_counter() - started
            return await upload, health, health_elapsed

    try:
        created, health, health_elapsed = asyncio.run(scenario())
    finally:
        app.dependency_overrides.pop(get_current_member_id, None)

    assert created.status_code == 201
    assert health.status_code == 200
    assert health_elapsed < 0.3, f"독립 요청이 {health_elapsed:.2f}초 기다림(이벤트 루프 차단)"
    assert calls == [False, False]  # 장마다 1회, 모두 워커 스레드에서 쓰기
    images = created.json()["images"]
    assert [image["original_name"] for image in images] == ["a.png", "b.png"]  # 표시 순서 유지
    assert len(list(uploads.UPLOAD_DIR.glob("*"))) == 2


def test_create_post_partial_write_failure_cleans_in_worker(client, upload_root, monkeypatch):
    """두 번째 파일 쓰기 실패 시 이번 요청의 파일(부분 파일 포함)을 모두 정리한다."""
    real_save = uploads.post_image_storage.save
    count = {"n": 0}

    def flaky_save(key, data, content_type):
        count["n"] += 1
        real_save(key, data[: len(data) // 2], content_type)  # 부분 쓰기
        if count["n"] == 2:
            raise OSError("disk full")

    monkeypatch.setattr(uploads.post_image_storage, "save", flaky_save)
    monkeypatch.setattr(board_service, "create_post", lambda *a: pytest.fail("DB까지 가면 안 됨"))
    with pytest.raises(OSError):
        client.post(
            "/api/boards/1/posts",
            data={"title": "제목", "body": "본문"},
            files=[("images", ("a.png", PNG, "image/png")), ("images", ("b.png", PNG, "image/png"))],
        )
    assert not list(uploads.UPLOAD_DIR.glob("*"))


def test_create_post_commit_outcome_unknown_keeps_files(client, upload_root, monkeypatch):
    """커밋 결과가 불명확하면 DB가 참조할 수 있으므로 파일을 지우지 않는다."""
    from app.core.db_connect import CommitOutcomeUnknownError

    removed = []
    monkeypatch.setattr(uploads.post_image_storage, "delete", lambda key: removed.append(key))

    def unknown(*args):
        raise CommitOutcomeUnknownError("commit response lost")

    monkeypatch.setattr(board_service, "create_post", unknown)
    response = client.post(
        "/api/boards/1/posts",
        data={"title": "제목", "body": "본문"},
        files={"images": ("test.png", PNG, "image/png")},
    )
    assert response.status_code >= 500
    assert removed == []
    assert len(list(uploads.UPLOAD_DIR.glob("*"))) == 1
