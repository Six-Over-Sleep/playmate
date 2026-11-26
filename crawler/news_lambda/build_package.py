"""뉴스 Lambda 배포 ZIP을 로컬에서 만들고 검증한다 (Issue #133). 다운로드·설치·AWS 접근을 하지 않는다.

    # Processor: 외부 패키지 없음 → 빌드 후 자동 검증
    python crawler/news_lambda/build_package.py processor --out crawler/news_lambda/dist/processor.zip

    # Collector(권장): requirements-collector.txt + requirements-collector-aws-sdk.txt로 Linux용 wheel을 미리 설치한
    # 폴더를 넘기고 AWS SDK를 함께 넣는다(DEPLOYMENT.md 7장)
    python crawler/news_lambda/build_package.py collector --with-aws-sdk \
        --deps-dir crawler/news_lambda/dist/collector-deps-sdk --out crawler/news_lambda/dist/collector.zip

    # Collector(SDK 없이): 런타임 boto3를 쓴다. AWS 문서가 경고하는 구성이라 검증 결과에 경고가 붙는다.
    python crawler/news_lambda/build_package.py collector --deps-dir crawler/news_lambda/dist/collector-deps \
        --out crawler/news_lambda/dist/collector-no-sdk.zip

    # 이미 만든 ZIP만 검증
    python crawler/news_lambda/build_package.py processor --verify crawler/news_lambda/dist/processor.zip

- 저장소의 원본 파일을 수정하지 않고 그대로 ZIP 최상위에 넣는다(경로 구분자는 항상 '/').
- 의존성 폴더에 Windows 전용 바이너리(.pyd/.dll/.exe, win32·win_amd64 이름)가 있거나, 다른 Python 버전·CPU용
  확장 모듈(.so)이 있으면 ZIP을 만들지 않는다.
- 같은 입력이면 같은 ZIP이 되도록 파일 순서·시각·권한을 고정한다.
- 검증: 구조(핸들러·원본 일치·의존성·금지 파일)를 검사하고, 압축을 푼 폴더만 보이는 별도 Python
  프로세스(-I -S: 환경변수·site-packages 무시)에서 핸들러를 import해 ZIP이 스스로 완결되는지 확인한다.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
CRAWLER = REPO_ROOT / "crawler" / "career_news_crawler"
SCRIPTS = REPO_ROOT / "database" / "scripts"
REQUIREMENTS = HERE / "requirements-collector.txt"

# ZIP 안 경로 → 저장소 원본 파일
SOURCES = {
    "collector": {
        "collector_handler.py": HERE / "collector_handler.py",
        "collect_career_news.py": SCRIPTS / "collect_career_news.py",
        "import_career_news.py": SCRIPTS / "import_career_news.py",
        "config.py": CRAWLER / "config.py",
        "src/__init__.py": CRAWLER / "src" / "__init__.py",
        "src/rss_collector.py": CRAWLER / "src" / "rss_collector.py",
    },
    "processor": {
        "processor_handler.py": HERE / "processor_handler.py",
        "collector_handler.py": HERE / "collector_handler.py",
        "import_career_news.py": SCRIPTS / "import_career_news.py",
    },
}
HANDLERS = {"collector": "collector_handler.lambda_handler", "processor": "processor_handler.lambda_handler"}
# requirements-collector.txt의 배포 이름 → import 이름. uv.lock의 feedparser 6.0.14·requests 2.34.2와 그 의존성.
# feedparser 6.0.14는 sgmllib이 아니라 feedparser_sgmllib 패키지를 불러온다(feedparser/sgml.py).
COLLECTOR_DISTRIBUTIONS = {
    "feedparser": "feedparser",
    "feedparser-sgmllib": "feedparser_sgmllib",
    "requests": "requests",
    "urllib3": "urllib3",
    "idna": "idna",
    "certifi": "certifi",
    "charset-normalizer": "charset_normalizer",
}
REQUIRED_DEPS = {"collector": tuple(COLLECTOR_DISTRIBUTIONS.values()), "processor": ()}
# Collector에만 --with-aws-sdk로 명시했을 때 넣는 AWS SDK와 그 의존성(requirements-collector-aws-sdk.txt).
# 배포 이름 → import 이름. python-dateutil은 dateutil, six는 six.py 모듈이다.
REQUIREMENTS_SDK = HERE / "requirements-collector-aws-sdk.txt"
COLLECTOR_SDK_DISTRIBUTIONS = {
    "boto3": "boto3",
    "botocore": "botocore",
    "s3transfer": "s3transfer",
    "jmespath": "jmespath",
    "python-dateutil": "dateutil",
    "six": "six",
}
SDK_MODULES = tuple(COLLECTOR_SDK_DISTRIBUTIONS.values())
# 이 중 하나라도 있으면 "SDK가 들어 있다"고 본다(jmespath·dateutil·six는 다른 패키지도 쓰는 범용 모듈이라 제외).
SDK_MARKERS = frozenset({"boto3", "botocore", "s3transfer"})
# AWS 문서: 배포 패키지에 SDK 의존성(urllib3 등)만 넣고 boto3를 넣지 않으면 런타임 SDK와 버전이 어긋날 수 있다.
NO_SDK_WARNING = ("urllib3가 들어 있지만 boto3/botocore는 런타임 것을 씁니다. Lambda는 ZIP(/var/task)을 먼저 찾으므로 "
                  "런타임 botocore가 ZIP의 urllib3를 쓰게 됩니다. AWS 문서 권장대로 --with-aws-sdk로 SDK를 함께 넣으세요.")
WINDOWS_BINARY = re.compile(r"(\.pyd|\.dll|\.exe)$|win32|win_amd64|win_arm64", re.IGNORECASE)
EXCLUDED_PARTS = {"__pycache__"}
# 의존성 폴더 최상위에서 ZIP에 넣지 않는 항목: 설치 도구가 만드는 콘솔 실행 파일(bin/, Windows에서 설치하면
# idna.exe·normalizer.exe 같은 Windows 실행 파일이 생김. Lambda는 쓰지 않음)과 uv의 작업용 잠금 파일(.lock).
EXCLUDED_DEP_TOP_LEVEL = {"bin", ".lock"}
FIXED_TIME = (1980, 1, 1, 0, 0, 0)
DEFAULT_PYTHON_TAG = "313"
DEFAULT_ARCH = "x86_64"


class PackageError(ValueError):
    """ZIP을 만들 수 없거나 검증에 실패한 구성이다."""


def _module_present(deps_dir: Path, name: str) -> bool:
    return (deps_dir / name / "__init__.py").is_file() or (deps_dir / f"{name}.py").is_file()


def file_problem(name: str, python_tag: str, arch: str) -> str | None:
    """ZIP에 넣으면 안 되는 파일이면 사유, 아니면 None. 빌드와 검증이 같은 규칙을 쓴다."""
    path = PurePosixPath(name)
    if WINDOWS_BINARY.search(name):
        return f"Windows 전용 파일: {name}"
    if path.suffix == ".so" and "cpython-" in path.name and (
            f"cpython-{python_tag}" not in path.name or arch not in path.name):
        return f"다른 Python 버전·CPU용 확장 모듈: {name}"
    if EXCLUDED_PARTS & set(path.parts) or path.suffix == ".pyc":
        return f"캐시 파일: {name}"
    return None


def dependency_files(deps_dir: Path, python_tag: str, arch: str) -> list[tuple[str, Path]]:
    """의존성 폴더의 파일 목록(ZIP 경로, 원본). Windows 바이너리·다른 버전 확장 모듈이면 PackageError."""
    problems = []
    files = []
    for path in sorted(p for p in deps_dir.rglob("*") if p.is_file()):
        relative = path.relative_to(deps_dir)
        if relative.parts[0] in EXCLUDED_DEP_TOP_LEVEL:
            continue  # 콘솔 실행 파일·설치 도구 잠금 파일(라이브러리 import와 무관)
        if EXCLUDED_PARTS & set(relative.parts) or path.suffix == ".pyc":
            continue  # 빌드 때는 캐시 파일을 조용히 뺀다
        name = relative.as_posix()
        problem = file_problem(name, python_tag, arch)
        if problem:
            problems.append(problem)
        files.append((name, path))
    if problems:
        raise PackageError("의존성 폴더를 ZIP에 넣을 수 없습니다:\n  " + "\n  ".join(problems))
    return files


def collect_entries(target: str, deps_dir: Path | None, python_tag: str = DEFAULT_PYTHON_TAG,
                    arch: str = DEFAULT_ARCH, include_sdk: bool = False) -> list[tuple[str, Path]]:
    """ZIP에 넣을 (ZIP 경로, 원본 파일) 목록. 소스와 의존성 경로가 겹치면 오류."""
    if target not in SOURCES:
        raise PackageError(f"알 수 없는 대상: {target}")
    if include_sdk and target != "collector":
        raise PackageError("AWS SDK 포함(--with-aws-sdk)은 Collector에만 허용합니다.")
    entries = {}
    for name, path in SOURCES[target].items():
        if not path.is_file():
            raise PackageError(f"원본 파일이 없습니다: {path}")
        entries[name] = path
    required = REQUIRED_DEPS[target] + (SDK_MODULES if include_sdk else ())
    if required:
        if deps_dir is None or not deps_dir.is_dir():
            raise PackageError(f"{target}에는 --deps-dir(Linux용으로 미리 설치한 의존성 폴더)가 필요합니다.")
        missing = [name for name in required if not _module_present(deps_dir, name)]
        if missing:
            raise PackageError(f"의존성 폴더에 없는 모듈: {', '.join(missing)}")
        present_sdk = sorted(name for name in SDK_MARKERS if _module_present(deps_dir, name))
        if present_sdk and not include_sdk:
            raise PackageError(f"의존성 폴더에 AWS SDK({', '.join(present_sdk)})가 있습니다. "
                               "넣으려면 --with-aws-sdk로 명시하고, 아니면 SDK 없는 폴더를 쓰세요.")
    elif deps_dir is not None:
        raise PackageError(f"{target}에는 외부 의존성이 없습니다. --deps-dir를 쓰지 않습니다.")
    if deps_dir is not None:
        for name, path in dependency_files(deps_dir, python_tag, arch):
            if name in entries:
                raise PackageError(f"의존성 폴더의 파일이 배포 소스와 겹칩니다: {name}")
            entries[name] = path
    return sorted(entries.items())


def build_zip(target: str, out: Path, deps_dir: Path | None = None, python_tag: str = DEFAULT_PYTHON_TAG,
              arch: str = DEFAULT_ARCH, include_sdk: bool = False) -> list[str]:
    """ZIP을 만들고 들어간 경로 목록을 돌려준다. 구성 오류면 파일을 만들지 않는다."""
    entries = collect_entries(target, deps_dir, python_tag, arch, include_sdk)
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, path in entries:
            info = zipfile.ZipInfo(name, date_time=FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, path.read_bytes())
    return [name for name, _ in entries]


# -- 검증 -------------------------------------------------------------------------
# 압축을 푼 폴더만 보이는 별도 프로세스에서 실행한다. 네트워크·S3 호출은 하지 않는다(import와 설정 로드만).
_IMPORT_CHECK = r"""
import io, json, pathlib, socket, sys


def _blocked(*args, **kwargs):
    raise OSError("패키지 검사 중 네트워크 차단")


# 이 프로세스는 어떤 외부 연결도 하지 않는다. 시도하면 예외로 드러난다.
socket.socket.connect = socket.create_connection = socket.getaddrinfo = _blocked


class _Raw:
    # botocore AWSResponse.raw 대역: stream()(일반 응답)·read()(GetObject 본문)
    def __init__(self, data):
        self._buffer = io.BytesIO(data)

    def stream(self, **kwargs):
        yield self._buffer.read()

    def read(self, amt=None):
        return self._buffer.read() if amt is None else self._buffer.read(amt)


def _s3_request_check(handler, boto3):
    # ZIP의 boto3/botocore로 S3 클라이언트를 만들고, 전송 직전(before-send)에 요청을 가로채 가짜 응답을 돌려준다.
    # 실제 직렬화된 헤더와, 실제 botocore ClientError(412·409)를 Collector가 어떻게 구분하는지 확인한다.
    from botocore.awsrequest import AWSResponse

    session = boto3.session.Session(aws_access_key_id="package-check", aws_secret_access_key="package-check",
                                    region_name="ap-northeast-2")
    client = session.client("s3")
    handler.ensure_conditional_write_supported(client)
    run_id = "20261117T090000Z-scheduled"
    key = "raw/news/2026/11/17/" + run_id + ".json"
    existing = json.dumps({"schema_version": handler.SCHEMA_VERSION, "run_id": run_id,
                           "collection_summary": {"status": "ok"}}).encode()
    state = {"put_status": 200, "puts": [], "gets": 0}

    def error_xml(code):
        return ("<?xml version='1.0' encoding='UTF-8'?><Error><Code>" + code
                + "</Code><Message>package check</Message><RequestId>check</RequestId></Error>").encode()

    def on_put(request, **kwargs):
        # botocore는 일부 헤더 값을 bytes로 둔다(서명 등). 기록용으로 문자열로 바꾼다.
        headers = {name: value.decode("latin-1") if isinstance(value, bytes) else str(value)
                   for name, value in request.headers.items()}
        state["puts"].append({"url": request.url, "headers": headers})
        status = state["put_status"]
        if status == 200:
            return AWSResponse(request.url, 200, {"ETag": '"check"'}, _Raw(b""))
        code = "PreconditionFailed" if status == 412 else "ConditionalRequestConflict"
        return AWSResponse(request.url, status, {"Content-Type": "application/xml"}, _Raw(error_xml(code)))

    def on_get(request, **kwargs):
        state["gets"] += 1
        return AWSResponse(request.url, 200, {"Content-Length": str(len(existing)), "ETag": '"old"'},
                           _Raw(existing))

    client.meta.events.register("before-send.s3.PutObject", on_put)
    client.meta.events.register("before-send.s3.GetObject", on_get)
    body = json.dumps({"run_id": run_id}, ensure_ascii=False).encode("utf-8")
    result = {}

    outcome, _ = handler.upload_raw(client, "playmate-package-check", key, body, run_id)
    sent = state["puts"][-1]
    headers = {name.lower(): value for name, value in sent["headers"].items()}
    result["200"] = {"outcome": outcome, "if_none_match": headers.get("if-none-match"),
                     "content_type": headers.get("content-type"),
                     "signed": str(headers.get("authorization", "")).startswith("AWS4-HMAC-SHA256"),
                     "url": sent["url"]}

    state["put_status"], state["puts"] = 412, []
    outcome, summary = handler.upload_raw(client, "playmate-package-check", key, body, run_id)
    result["412"] = {"outcome": outcome, "existing_status": summary["status"], "get_calls": state["gets"],
                     "put_attempts": len(state["puts"])}

    state["put_status"], state["puts"] = 409, []
    try:
        handler.upload_raw(client, "playmate-package-check", key, body, run_id)
        result["409"] = {"error": None}
    except handler.RawUploadError as error:
        cause = error.__cause__
        result["409"] = {"error": type(error).__name__, "cause": type(cause).__name__,
                         "code": getattr(cause, "response", {}).get("Error", {}).get("Code"),
                         "put_attempts": len(state["puts"])}
    return result


root = pathlib.Path(sys.argv[1]).resolve()
target = sys.argv[2]
with_sdk = sys.argv[3] == "sdk"
sys.path.insert(0, str(root))
report = {}
if target == "collector":
    import collector_handler as handler
    categories, collect = handler.load_crawler()
    import feedparser, feedparser_sgmllib, requests, urllib3, idna, certifi, charset_normalizer
    modules = ["collector_handler", "import_career_news", "config", "src.rss_collector", "feedparser",
               "feedparser_sgmllib", "requests", "urllib3", "idna", "certifi", "charset_normalizer"]
    report["categories"] = len(categories)
    report["collect"] = collect.__name__
    report["versions"] = {"requests": requests.__version__, "urllib3": urllib3.__version__}
    if with_sdk:
        # 클라이언트를 만들지 않고 ZIP 안 botocore의 서비스 모델 파일만 읽는다(네트워크·자격증명 불필요).
        import types
        import boto3, botocore, botocore.session, s3transfer, jmespath, dateutil, six
        modules += ["boto3", "botocore", "s3transfer", "jmespath", "dateutil", "six"]
        model = botocore.session.get_session().get_service_model("s3")
        handler.ensure_conditional_write_supported(types.SimpleNamespace(meta=types.SimpleNamespace(service_model=model)))
        report["if_none_match"] = "IfNoneMatch" in model.operation_model("PutObject").input_shape.members
        report["versions"].update(boto3=boto3.__version__, botocore=botocore.__version__,
                                  s3transfer=s3transfer.__version__)
        report["s3_requests"] = _s3_request_check(handler, boto3)
    files = {name: sys.modules[name].__file__ for name in modules}
    files["collect_career_news"] = handler._collect_module().__file__
else:
    import processor_handler as handler
    files = {"processor_handler": handler.__file__, "collector_handler": handler.collector.__file__,
             "import_career_news": handler.importer.__file__}
report["handler_callable"] = callable(handler.lambda_handler)
report["outside"] = sorted(n for n, f in files.items() if not pathlib.Path(f).resolve().is_relative_to(root))
report["boto3_imported"] = "boto3" in sys.modules
print(json.dumps(report))
"""


def check_zip_structure(target: str, zip_path: Path, python_tag: str = DEFAULT_PYTHON_TAG,
                        arch: str = DEFAULT_ARCH, include_sdk: bool = False) -> list[str]:
    """ZIP 구조를 검사한다. 문제가 있으면 PackageError(사유 목록). 통과하면 ZIP 안 경로 목록."""
    if target not in SOURCES:
        raise PackageError(f"알 수 없는 대상: {target}")
    if include_sdk and target != "collector":
        raise PackageError("AWS SDK 포함(--with-aws-sdk)은 Collector에만 허용합니다.")
    problems = []
    with zipfile.ZipFile(zip_path) as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        for name in names:
            path = PurePosixPath(name)
            if "\\" in name or path.is_absolute() or ".." in path.parts:
                problems.append(f"잘못된 경로: {name}")
                continue
            problem = file_problem(name, python_tag, arch)
            if problem:
                problems.append(problem)
        handler_file = HANDLERS[target].split(".")[0] + ".py"
        if handler_file not in names:
            problems.append(f"핸들러 파일이 ZIP 최상위에 없습니다: {handler_file}")
        for name, source in SOURCES[target].items():
            if name not in names:
                problems.append(f"배포 소스 누락: {name}")
            elif archive.read(name) != source.read_bytes():
                problems.append(f"저장소 원본과 다릅니다(다시 빌드 필요): {name}")
        top_level = {PurePosixPath(name).parts[0] for name in names}
        for excluded in sorted(EXCLUDED_DEP_TOP_LEVEL & top_level):
            problems.append(f"넣지 않아야 할 설치 부산물: {excluded}")
        for module in REQUIRED_DEPS[target] + (SDK_MODULES if include_sdk else ()):
            if f"{module}/__init__.py" not in names and f"{module}.py" not in names:
                problems.append(f"의존성 누락: {module}")
        if target == "processor":
            extra = sorted(set(names) - set(SOURCES["processor"]))
            if extra:
                problems.append(f"Processor에 불필요한 파일: {', '.join(extra[:10])}")
        present_sdk = sorted(SDK_MARKERS & top_level)
        if present_sdk and not include_sdk:
            problems.append(f"AWS SDK({', '.join(present_sdk)})가 들어 있습니다. Collector는 --with-aws-sdk로 "
                            "명시했을 때만 허용하고, Processor는 넣지 않습니다(런타임 SDK 사용).")
    if problems:
        raise PackageError("ZIP 검증 실패:\n  " + "\n  ".join(problems))
    return names


def import_check(target: str, zip_path: Path, timeout: int = 120, include_sdk: bool = False) -> dict:
    """압축을 풀고 site-packages 없이 핸들러를 import한다. 실패하면 PackageError."""
    with tempfile.TemporaryDirectory() as tmp:
        task = Path(tmp) / "task"
        with zipfile.ZipFile(zip_path) as archive:
            archive.extractall(task)
        # 사용자 AWS 자격증명·설정(AWS_*·~/.aws)이 검사 프로세스에 들어가지 않게 한다.
        env = {name: value for name, value in os.environ.items() if not name.upper().startswith("AWS_")}
        env.update(AWS_CONFIG_FILE=str(task / "no-aws-config"), AWS_SHARED_CREDENTIALS_FILE=str(task / "no-aws-credentials"),
                   AWS_EC2_METADATA_DISABLED="true")
        completed = subprocess.run(
            [sys.executable, "-I", "-S", "-B", "-c", _IMPORT_CHECK, str(task), target,
             "sdk" if include_sdk else "no-sdk"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, env=env,
        )
    if completed.returncode != 0:
        tail = (completed.stderr or "").strip().splitlines()[-3:]
        raise PackageError("ZIP만으로 import하지 못했습니다:\n  " + "\n  ".join(tail))
    report = json.loads(completed.stdout.strip().splitlines()[-1])
    # SDK를 넣지 않은 ZIP은 boto3를 불러오면 안 되고, 넣은 ZIP은 boto3가 ZIP 안에서 로드돼야 한다(outside로 검사).
    if report["outside"] or not report["handler_callable"] or (report["boto3_imported"] and not include_sdk):
        raise PackageError(f"ZIP 밖의 모듈을 쓰거나 핸들러가 없습니다: {report}")
    if include_sdk and not report.get("if_none_match"):
        raise PackageError(f"ZIP의 botocore가 PutObject.IfNoneMatch를 지원하지 않습니다: {report}")
    if include_sdk:
        checks = report.get("s3_requests") or {}
        expected = (
            checks.get("200", {}).get("outcome") == "created"
            and checks.get("200", {}).get("if_none_match") == "*"
            and checks.get("200", {}).get("signed")
            and checks.get("412", {}).get("outcome") == "already_exists"
            and checks.get("409", {}).get("error") == "RawWriteConflictError"
        )
        if not expected:
            raise PackageError(f"ZIP의 boto3로 만든 S3 요청·오류 처리 결과가 예상과 다릅니다: {checks}")
    return report


def verify_zip(target: str, zip_path: Path, python_tag: str = DEFAULT_PYTHON_TAG, arch: str = DEFAULT_ARCH,
               run_import: bool = True, include_sdk: bool = False) -> dict:
    """구조 검사 + (가능하면) 격리 import 검사. 호스트 Python 버전이 다르면 import 검사는 건너뛴다."""
    names = check_zip_structure(target, zip_path, python_tag, arch, include_sdk)
    result = {"target": target, "handler": HANDLERS[target], "files": len(names), "aws_sdk": include_sdk,
              "warnings": [], "import_check": "skipped"}
    if target == "collector" and not include_sdk and any(name.startswith("urllib3/") for name in names):
        result["warnings"].append(NO_SDK_WARNING)
    host = f"{sys.version_info.major}{sys.version_info.minor}"
    if not run_import:
        return result
    if host != python_tag:
        result["import_check"] = f"skipped (호스트 Python {host} ≠ 대상 {python_tag})"
        return result
    result["import_check"] = "passed"
    result["import_report"] = import_check(target, zip_path, include_sdk=include_sdk)
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="뉴스 Lambda 배포 ZIP 만들기·검증 (설치·다운로드 없음)")
    parser.add_argument("target", choices=sorted(SOURCES))
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--out", type=Path, help="만들 ZIP 경로(만든 뒤 검증)")
    action.add_argument("--verify", type=Path, help="이미 만든 ZIP을 검증만 한다")
    parser.add_argument("--deps-dir", type=Path, default=None,
                        help="Linux용 wheel로 미리 설치한 의존성 폴더 (collector 필수)")
    parser.add_argument("--python-tag", default=DEFAULT_PYTHON_TAG, help="Lambda Python 버전 태그 (기본 313)")
    parser.add_argument("--arch", default=DEFAULT_ARCH, choices=("x86_64", "aarch64"), help="Lambda CPU 구조")
    parser.add_argument("--no-import-check", action="store_true", help="격리 import 검사를 건너뛴다")
    parser.add_argument("--with-aws-sdk", action="store_true",
                        help="Collector에 boto3·botocore 등(requirements-collector-aws-sdk.txt)을 함께 넣는다")
    args = parser.parse_args(argv)
    zip_path = args.out or args.verify
    try:
        if args.out:
            names = build_zip(args.target, args.out, args.deps_dir, args.python_tag, args.arch, args.with_aws_sdk)
            print(f"{args.out} 생성: 파일 {len(names)}개, 핸들러 {HANDLERS[args.target]}")
        result = verify_zip(args.target, zip_path, args.python_tag, args.arch, not args.no_import_check,
                            args.with_aws_sdk)
    except PackageError as error:
        print(f"실패: {error}", file=sys.stderr)
        return 1
    for warning in result["warnings"]:
        print(f"경고: {warning}", file=sys.stderr)
    print("검증 통과: " + json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
