from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile

PROJECT_ROOT = Path(__file__).resolve().parents[3]
UPLOAD_DIR = PROJECT_ROOT / "uploads" / "posts"
MAX_IMAGE_SIZE = 5 * 1024 * 1024
ALLOWED = {"image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif", "image/webp": ".webp"}

def _valid_signature(content_type: str, data: bytes) -> bool:
    return {
        "image/jpeg": data.startswith(b"\xff\xd8\xff"),
        "image/png": data.startswith(b"\x89PNG\r\n\x1a\n"),
        "image/gif": data.startswith((b"GIF87a", b"GIF89a")),
        "image/webp": len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP",
    }.get(content_type, False)

async def save_images(files: list[UploadFile]) -> list[dict]:
    if len(files) > 3: raise HTTPException(status_code=422, detail="이미지는 최대 3장까지 첨부할 수 있습니다.")
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    saved = []
    try:
        for file in files:
            content_type = (file.content_type or "").lower()
            if content_type not in ALLOWED: raise HTTPException(status_code=422, detail="JPG, PNG, GIF, WEBP 이미지만 첨부할 수 있습니다.")
            data = await file.read(MAX_IMAGE_SIZE + 1)
            if len(data) > MAX_IMAGE_SIZE: raise HTTPException(status_code=422, detail="이미지 한 장은 5MB를 넘을 수 없습니다.")
            if not _valid_signature(content_type, data): raise HTTPException(status_code=422, detail="이미지 파일 내용과 형식이 일치하지 않습니다.")
            stored_name = f"posts/{uuid4().hex}{ALLOWED[content_type]}"
            path = PROJECT_ROOT / "uploads" / stored_name
            path.write_bytes(data)
            saved.append({"stored_name": stored_name.replace('\\','/'), "original_name": Path(file.filename or "image").name[:255], "content_type": content_type, "file_size": len(data), "path": path})
        return saved
    except Exception:
        remove_saved_images(saved)
        raise

def remove_saved_images(images: list[dict]) -> None:
    for image in images:
        image.get("path", Path("missing")).unlink(missing_ok=True)
