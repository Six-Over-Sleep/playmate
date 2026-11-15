from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool

PROJECT_ROOT = Path(__file__).resolve().parents[3]
UPLOAD_DIR = PROJECT_ROOT / "uploads" / "posts"
MAX_POST_IMAGES = 3
MAX_IMAGE_SIZE = 5 * 1024 * 1024
ALLOWED = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
}


class LocalPostImageStorage:
    def _path(self, key: str) -> Path:
        path = (PROJECT_ROOT / "uploads" / key).resolve()
        root = UPLOAD_DIR.resolve()
        if path == root or not path.is_relative_to(root):
            raise ValueError("Invalid post image key")
        return path

    def save(self, key: str, data: bytes, content_type: str) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def public_url(self, key: str) -> str:
        return f"/uploads/{key}"

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)


post_image_storage = LocalPostImageStorage()


def _valid_signature(content_type: str, data: bytes) -> bool:
    """허용 MIME 유형의 기본 파일 시그니처 일치 여부를 반환한다."""
    return {
        "image/jpeg": data.startswith(b"\xff\xd8\xff"),
        "image/png": data.startswith(b"\x89PNG\r\n\x1a\n"),
        "image/gif": data.startswith((b"GIF87a", b"GIF89a")),
        "image/webp": len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP",
    }.get(content_type, False)


async def validate_images(files: list[UploadFile]) -> list[tuple[dict, bytes]]:
    """첨부를 읽고 검증한 뒤 저장용 메타데이터와 바이트를 반환한다."""
    if len(files) > MAX_POST_IMAGES:
        raise HTTPException(422, f"이미지는 최대 {MAX_POST_IMAGES}장까지 첨부할 수 있습니다.")

    validated = []
    for file in files:
        content_type = (file.content_type or "").lower()
        if content_type not in ALLOWED:
            raise HTTPException(422, "JPG, PNG, GIF, WEBP 이미지만 첨부할 수 있습니다.")
        data = await file.read(MAX_IMAGE_SIZE + 1)
        if len(data) > MAX_IMAGE_SIZE:
            raise HTTPException(422, "이미지 한 장은 5MB를 넘을 수 없습니다.")
        if not _valid_signature(content_type, data):
            raise HTTPException(422, "이미지 파일 내용과 형식이 일치하지 않습니다.")
        validated.append((
            {
                "stored_name": f"posts/{uuid4().hex}{ALLOWED[content_type]}",
                "original_name": Path(file.filename or "image").name[:255],
                "content_type": content_type,
                "file_size": len(data),
            },
            data,
        ))
    return validated


def store_validated_images(images: list[tuple[dict, bytes]]) -> list[dict]:
    saved = []
    try:
        for image, data in images:
            saved.append(image)
            post_image_storage.save(image["stored_name"], data, image["content_type"])
    except Exception:
        remove_saved_images(saved)
        raise
    return saved


async def save_images(files: list[UploadFile]) -> list[dict]:
    """검증은 이벤트 루프에서, 저장소 쓰기는 워커 스레드에서 실행한다."""
    return await run_in_threadpool(store_validated_images, await validate_images(files))


def remove_saved_images(images: list[dict]) -> None:
    """이번 요청에서 생성한 이미지 키를 정리한다."""
    for image in images:
        post_image_storage.delete(image["stored_name"])


# 프로필 이미지 업로드
async def save_profile_image(file: UploadFile) -> dict:
    content_type = (file.content_type or "").lower()

    # 이미지 형식 검사
    if content_type not in ("image/jpeg", "image/png", "image/webp"):
        raise HTTPException(
            status_code=422,
            detail="프로필 이미지는 JPG, PNG, WEBP만 가능합니다."
        )

    # 이미지 용량 검사
    data = await file.read(MAX_IMAGE_SIZE + 1)

    if not data or len(data) > MAX_IMAGE_SIZE:
        raise HTTPException(
            status_code=422,
            detail="프로필 이미지는 1바이트 이상 5MB 이하여야 합니다."
        )

    # 실제 파일 형식 검사
    if not _valid_signature(content_type, data):
        raise HTTPException(
            status_code=422,
            detail="이미지 파일 형식이 올바르지 않습니다."
        )

    # 프로필 전용 저장 폴더
    profile_dir = PROJECT_ROOT / "uploads" / "profiles"
    profile_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{uuid4().hex}{ALLOWED[content_type]}"
    path = profile_dir / filename

    try:
        path.write_bytes(data)
    except Exception:
        path.unlink(missing_ok=True)
        raise

    return {
        "stored_name": f"profiles/{filename}",
        "path": path
    }
