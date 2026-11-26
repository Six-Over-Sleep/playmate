from pathlib import Path

from app.core.uploads import _valid_signature

ROOT = Path(__file__).resolve().parents[2]

def test_migration_is_additive_and_default_board_is_idempotent():
    sql = (ROOT / "database" / "sql" / "001_board_mvp.sql").read_text(encoding="utf-8").upper()
    assert "WHERE NOT EXISTS" in sql
    assert "CREATE TABLE IF NOT EXISTS" in sql
    assert "DROP " not in sql
    assert "TRUNCATE " not in sql

def test_supported_image_signatures():
    assert _valid_signature("image/jpeg", b"\xff\xd8\xffrest")
    assert _valid_signature("image/png", b"\x89PNG\r\n\x1a\nrest")
    assert _valid_signature("image/gif", b"GIF89arest")
    assert _valid_signature("image/webp", b"RIFF0000WEBPrest")

def test_extension_spoof_is_rejected():
    assert not _valid_signature("image/png", b"not-an-image")
