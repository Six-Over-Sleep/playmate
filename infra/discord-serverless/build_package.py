"""Discord Worker Lambda 배포 패키지를 만든다 (sam build 전에 실행).

playmate-discord-bot 폴더 전체(bot.py, tests, .venv 등)를 올리지 않으려고, Worker에 필요한 모듈만 복사한다.
  python infra/discord-serverless/build_package.py            -> infra/discord-serverless/.build/career_worker/
  python infra/discord-serverless/build_package.py --out DIR  -> DIR (테스트용)

포함: career_share의 발송 경로 모듈, discord_rest core(reuse.py 제외), secret_bootstrap.py, 빈 requirements.txt
제외: DB 경로(db_lambda, repository, service, settings, state), discord.py·config·psycopg를 import하는 모든 것
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

# 기능별 Worker 패키지. HOT·DM을 추가할 때 같은 형식으로 늘린다.
PACKAGES = {
    "career_worker": {
        "career_share": ["__init__.py", "contract.py", "messages.py", "policy.py", "queues.py", "worker.py", "worker_lambda.py"],
        "discord_rest": ["__init__.py", "client.py", "errors.py", "inactivity.py", "permissions.py", "transport.py"],
    },
}
FORBIDDEN_IMPORTS = ("discord", "config", "psycopg", "psycopg2", "repositories", "services", "career_share.repository",
                     "career_share.db_lambda", "career_share.service", "career_share.settings", "discord_rest.reuse")
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
    parser.add_argument("--package", default="career_worker", choices=sorted(PACKAGES))
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    out = args.out or HERE / ".build" / args.package
    copied = build(args.package, out)
    print(f"{args.package}: {len(copied)} files -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
