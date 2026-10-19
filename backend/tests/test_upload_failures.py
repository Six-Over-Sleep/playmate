"""업로드 검증과 부분 파일·DB 실패 정리를 임시 디렉터리에서 확인한다."""

import asyncio
from io import BytesIO
from pathlib import Path

import pytest
from fastapi import HTTPException, UploadFile
from starlette.datastructures import Headers

from app.core import uploads
from app.services import board_service

PNG = b"\x89PNG\r\n\x1a\nexample"


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
    assert all(row["path"].read_bytes() == PNG for row in saved)
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
    uploads.remove_saved_images([{"path": outside}, {}])
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
    static = next(route.app for route in app.routes if route.path == "/uploads")
    directory = upload_root / "uploads"
    monkeypatch.setattr(static, "directory", str(directory))
    monkeypatch.setattr(static, "all_directories", [str(directory)])
    response = client.get("/uploads/" + saved[0]["stored_name"])
    assert response.status_code == 200
    assert response.content == PNG
    assert response.headers["content-type"] == "image/png"
