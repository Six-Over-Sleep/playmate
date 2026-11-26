"""운영 기본값을 .env를 읽거나 Discord에 연결하지 않고 확인한다 (설정, 의존성, 권한 정책)."""
import ast
import os
from importlib.metadata import version
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
source = (ROOT / "config.py").read_text(encoding="utf-8")

for mode, expected_test, expected_interval in (
    (None, False, 3600),
    ("false", False, 3600),
    ("", False, 3600),
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

# 채널 권한 정책 (확정): HOST도 일반 참여자와 같다. 채널을 관리하는 권한은 누구에게도 주지 않는다.
# HOST가 채널을 지우거나 옮기면 Bot의 활동 감지와 삭제 대상 추적이 어긋날 수 있기 때문이다.
for module in ("permissions.py", "meeting_space.py"):
    module_source = (ROOT / "services" / module).read_text(encoding="utf-8")
    tree = ast.parse(module_source)
    assert not any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and "host" in node.name.lower()
                   for node in ast.walk(tree)), f"{module}에 HOST 전용 함수가 남아 있다"
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "PermissionOverwrite":
            assert all(keyword.arg not in {"manage_channels", "manage_messages", "manage_permissions"}
                       for keyword in node.keywords), f"{module}: 관리 권한을 주는 overwrite가 있다"

# 참여자 권한은 보기/읽기/쓰기뿐이다 (음성 채널이 없으므로 connect/speak도 없다).
import sys
sys.path.insert(0, str(ROOT))
with patch.dict(os.environ, {"DISCORD_BOT_TOKEN": "verification-only", "DISCORD_GUILD_ID": "1"}),         patch("dotenv.load_dotenv"):
    from services.meeting_space import PARTICIPANT_PERMISSIONS
assert PARTICIPANT_PERMISSIONS == {
    "view_channel": True, "read_message_history": True, "send_messages": True,
}

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
print("PASS: 5 mode cases, installed dependency pins and channel permission policy verified.")
