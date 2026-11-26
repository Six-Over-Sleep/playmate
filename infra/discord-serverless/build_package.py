"""Discord Worker Lambda 배포 패키지를 만든다 (sam build 전에 실행).

playmate-discord-bot 폴더 전체(bot.py, tests, .venv 등)를 올리지 않으려고, Worker에 필요한 모듈만 복사한다.
  python infra/discord-serverless/build_package.py                    -> .build/career_worker, hot_worker, dm_worker
  python infra/discord-serverless/build_package.py --package dm_worker -> .build/dm_worker 하나만
  python infra/discord-serverless/build_package.py --package dm_worker --out DIR  (테스트용)

포함: 각 기능의 발송 경로 모듈(worker_lambda 등), career_share 공통 Worker, discord_rest core(reuse.py 제외),
      secret_bootstrap.py, 빈 requirements.txt. DM은 순수 모듈 dm_share/units.py와 services/notification_policy.py도 넣는다.
제외: DB 경로(db_lambda, repository, service, settings, state), discord.py·config·psycopg, Gateway 진입점(bot.py)
복사한 모듈이 금지된 모듈을 import하면 실패한다 (Worker가 DB·Gateway 코드에 의존하지 않게).
"""
import argparse
import ast
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
BOT = REPO / "playmate-discord-bot"

# 공통: 모든 Worker가 쓰는 career_share 발송 경로(CareerShareWorker, handle_records, contract, SqsPublisher)와 discord_rest core
_CAREER_CORE = ["__init__.py", "contract.py", "messages.py", "policy.py", "queues.py", "worker.py", "worker_lambda.py"]
_DISCORD_REST = ["__init__.py", "client.py", "errors.py", "inactivity.py", "permissions.py", "transport.py"]

# 기능별 Worker 패키지 (파일 단위 허용 목록)
PACKAGES = {
    "career_worker": {
        "career_share": _CAREER_CORE,
        "discord_rest": _DISCORD_REST,
    },
    "hot_worker": {
        "career_share": _CAREER_CORE,
        "hot_share": ["__init__.py", "messages.py", "policy.py", "worker_lambda.py"],
        "discord_rest": _DISCORD_REST,
    },
    "dm_worker": {
        "career_share": _CAREER_CORE,
        "dm_share": ["__init__.py", "units.py", "worker_lambda.py"],
        "services": ["__init__.py", "notification_policy.py"],   # 순수 규칙 모듈 (typing만 import). 그 밖의 services는 넣지 않는다
        "discord_rest": _DISCORD_REST,
    },
}
FORBIDDEN_IMPORTS = ("discord", "config", "psycopg", "psycopg2", "repositories", "services", "career_share.repository",
                     "career_share.db_lambda", "career_share.service", "career_share.settings", "career_share.state",
                     "hot_share.repository", "hot_share.db_lambda", "hot_share.service", "hot_share.settings",
                     "dm_share.db_lambda", "dm_share.service", "dm_share.settings", "dm_share.messages",
                     "discord_rest.reuse", "bot")
# 금지 접두어 안에서 이름 그대로 허용하는 순수 모듈 (DB·discord.py·config를 import하지 않음을 위 검사가 다시 확인한다)
ALLOWED_EXACT = ("services.notification_policy",)
REQUIREMENTS = ("# Worker는 표준 라이브러리 + 이 패키지의 모듈만 쓴다. boto3는 Lambda Python 런타임에 포함되어 있다.\n"
                "# 외부 패키지를 추가하지 않는다 (discord.py, psycopg 금지).\n")


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
    return names


def forbidden_in(path: Path) -> list[str]:
    bad = []
    for name in imported_modules(path):
        if name in ALLOWED_EXACT:
            continue
        for forbidden in FORBIDDEN_IMPORTS:
            if name == forbidden or name.startswith(forbidden + "."):
                bad.append(name)
    return sorted(set(bad))


def build(name: str, out: Path) -> list[str]:
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    copied = []
    for package, files in PACKAGES[name].items():
        (out / package).mkdir()
        for file in files:
            source = BOT / package / file
            if not source.is_file():
                raise SystemExit(f"필요한 파일이 없습니다: {source.relative_to(REPO)}")
            shutil.copy2(source, out / package / file)
            copied.append(f"{package}/{file}")
    shutil.copy2(HERE / "src" / "secret_bootstrap.py", out / "secret_bootstrap.py")
    copied.append("secret_bootstrap.py")
    (out / "requirements.txt").write_text(REQUIREMENTS, encoding="utf-8")
    problems = {rel: bad for rel in copied if (bad := forbidden_in(out / rel))}
    if problems:
        shutil.rmtree(out)
        raise SystemExit(f"Worker 패키지에 금지된 import가 있습니다: {problems}")
    return copied


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--package", default="all", choices=["all", *sorted(PACKAGES)])
    parser.add_argument("--out", type=Path, default=None, help="--package 하나를 고른 경우에만 쓴다")
    args = parser.parse_args(argv)
    names = sorted(PACKAGES) if args.package == "all" else [args.package]
    if args.out is not None and len(names) != 1:
        parser.error("--out은 --package와 함께 하나만 지정한다")
    for name in names:
        out = args.out or HERE / ".build" / name
        copied = build(name, out)
        print(f"{name}: {len(copied)} files -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
