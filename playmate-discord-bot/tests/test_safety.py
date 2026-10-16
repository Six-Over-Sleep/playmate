"""Verify deployment defaults without reading the local .env or contacting Discord."""
import ast
import os
from importlib.metadata import version
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
source = (ROOT / "config.py").read_text(encoding="utf-8")

for mode, expected_test, expected_interval in (
    (None, False, 86400),
    ("false", False, 86400),
    ("", False, 86400),
    ("true", True, 60),
    ("TRUE", True, 60),
):
    environment = {
        "DISCORD_BOT_TOKEN": "verification-only",
        "DISCORD_GUILD_ID": "1",
    }
    if mode is not None:
        environment["PLAYMATE_TEST_MODE"] = mode
    namespace = {"__file__": str(ROOT / "config.py")}
    with patch.dict(os.environ, environment, clear=True), patch("dotenv.load_dotenv"):
        exec(compile(source, "config.py", "exec"), namespace)
    assert namespace["TEST_MODE"] is expected_test
    assert namespace["CHECK_INTERVAL_SECONDS"] == expected_interval

pins = (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
assert pins == ["discord.py==2.7.1", "python-dotenv==1.2.4", "psycopg[binary]==3.3.6", "tzdata==2026.5"]
for pin in pins:
    package, expected = pin.split("==")
    package = package.split("[")[0]
    assert version(package) == expected
assert ".env" in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
assert "PLAYMATE_TEST_MODE=false" in (ROOT / ".env.example").read_text(encoding="utf-8")

tree = ast.parse((ROOT / "services" / "permissions.py").read_text(encoding="utf-8"))
host = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef)
            and node.name == "grant_host_permissions")
assert "manage_messages = 미설정(None)" in ast.get_docstring(host)
overwrite = next(node for node in ast.walk(host)
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                 and node.func.attr == "PermissionOverwrite")
assert all(keyword.arg != "manage_messages" for keyword in overwrite.keywords)
assert next(keyword.value.value for keyword in overwrite.keywords
            if keyword.arg == "manage_channels") is True

# ZIP inspection is conditional so configuration checks work after extraction too.
archive = ROOT / "outputs" / "PlayMate_Discord_Bot_refactored.zip"
if archive.exists():
    with ZipFile(archive) as package:
        assert package.testzip() is None
        names = package.namelist()
        assert all(Path(name).name != ".env" for name in names)
        assert "playmate-discord-bot/.env.example" in names
        assert b'"PLAYMATE_TEST_MODE", "false"' in package.read("playmate-discord-bot/config.py")
        assert package.read("playmate-discord-bot/requirements.txt").decode().splitlines() == pins
    print("PASS: archive has no .env; example, defaults and pins verified.")
print("PASS: 5 mode cases, installed dependency pins and HOST overwrite verified.")
