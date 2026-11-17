"""배포 ZIP 빌드 스크립트(build_package.py) 테스트 — 다운로드·설치·AWS 접근 없이 임시 폴더에서만 실행한다.

실행(저장소 루트): python -m unittest discover -s crawler/news_lambda/tests -v
"""

import importlib.util
import io
import json
import re
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


build = _load("build_package_under_test", HERE / "build_package.py")
DEP_PACKAGES = ("feedparser", "feedparser_sgmllib", "requests", "urllib3", "idna", "certifi", "charset_normalizer")


def fake_deps(root: Path, extra=()):
    """Linux wheel을 설치한 것처럼 보이는 최소 의존성 폴더(내용은 비어 있음)."""
    for package in DEP_PACKAGES:
        (root / package).mkdir(parents=True, exist_ok=True)
        (root / package / "__init__.py").write_text("", encoding="utf-8")
    (root / "certifi" / "cacert.pem").write_text("pem", encoding="utf-8")
    (root / "charset_normalizer" / "md.cpython-313-x86_64-linux-gnu.so").write_bytes(b"\x7fELF")
    (root / "requests" / "__pycache__").mkdir(exist_ok=True)
    (root / "requests" / "__pycache__" / "x.cpython-313.pyc").write_bytes(b"pyc")
    for name in extra:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
    return root


class _ModuleSnapshot:
    """압축을 푼 묶음에서 모듈을 불러온 뒤 sys.modules·sys.path를 원래대로 되돌린다."""

    def __enter__(self):
        self.modules = dict(sys.modules)
        self.path = list(sys.path)
        return self

    def __exit__(self, *exc):
        for name in list(sys.modules):
            if name not in self.modules:
                del sys.modules[name]
        sys.modules.update(self.modules)
        sys.path[:] = self.path
        return False


class BuildPackageTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_processor_zip_contents_and_reproducibility(self):
        first = self.tmp / "a" / "processor.zip"
        second = self.tmp / "b" / "processor.zip"
        names = build.build_zip("processor", first)
        build.build_zip("processor", second)
        self.assertEqual(names, ["collector_handler.py", "import_career_news.py", "processor_handler.py"])
        self.assertEqual(first.read_bytes(), second.read_bytes())  # 같은 입력 → 같은 ZIP
        with zipfile.ZipFile(first) as archive:
            for info in archive.infolist():
                self.assertNotIn("\\", info.filename)
                self.assertEqual(info.date_time, build.FIXED_TIME)
            original = (HERE.parents[1] / "database" / "scripts" / "import_career_news.py").read_bytes()
            self.assertEqual(archive.read("import_career_news.py"), original)  # 원본 그대로

    def test_processor_zip_runs_after_extraction(self):
        out = self.tmp / "processor.zip"
        build.build_zip("processor", out)
        task = self.tmp / "task"
        with zipfile.ZipFile(out) as archive:
            archive.extractall(task)
        with _ModuleSnapshot():
            for name in ("collector_handler", "import_career_news"):
                sys.modules.pop(name, None)
            handler = _load("zip_processor_handler", task / "processor_handler.py")
            self.assertTrue(Path(handler.importer.__file__).resolve().is_relative_to(task.resolve()))
            self.assertTrue(Path(handler.collector.__file__).resolve().is_relative_to(task.resolve()))
            event = {"Records": [{"eventSource": "aws:s3", "eventName": "ObjectCreated:Put",
                                  "s3": {"bucket": {"name": "b-test"}, "object": {"key": "processed/news/x.json"}}}]}
            result = handler.process_event(event, settings=handler.ProcessorSettings(), s3_client=None)
            self.assertEqual(result["results"][0]["reason"], "outside_raw_prefix")

    def test_collector_requires_linux_dependency_folder(self):
        with self.assertRaises(build.PackageError):
            build.build_zip("collector", self.tmp / "c.zip")
        deps = fake_deps(self.tmp / "deps")
        import shutil

        shutil.rmtree(deps / "feedparser_sgmllib")
        with self.assertRaises(build.PackageError) as caught:
            build.build_zip("collector", self.tmp / "c.zip", deps)
        self.assertIn("feedparser_sgmllib", str(caught.exception))
        self.assertFalse((self.tmp / "c.zip").exists())

    def test_collector_zip_with_dependencies(self):
        deps = fake_deps(self.tmp / "deps")
        out = self.tmp / "collector.zip"
        names = build.build_zip("collector", out, deps)
        for name in ("collector_handler.py", "collect_career_news.py", "import_career_news.py", "config.py",
                     "src/__init__.py", "src/rss_collector.py", "feedparser/__init__.py",
                     "feedparser_sgmllib/__init__.py",
                     "certifi/cacert.pem", "charset_normalizer/md.cpython-313-x86_64-linux-gnu.so"):
            self.assertIn(name, names)
        self.assertFalse(any("__pycache__" in name or name.endswith(".pyc") for name in names))

    def test_collector_zip_loads_crawler_from_extracted_bundle(self):
        out = self.tmp / "collector.zip"
        build.build_zip("collector", out, fake_deps(self.tmp / "deps"))
        task = self.tmp / "task"
        with zipfile.ZipFile(out) as archive:
            archive.extractall(task)
        # 이 테스트는 프로젝트 파일 배치를 확인한다. 내용이 빈 가짜 의존성 대신 설치된 실제 라이브러리를 쓰도록 지운다.
        import shutil

        for package in DEP_PACKAGES:
            shutil.rmtree(task / package)
        with _ModuleSnapshot():
            for name in ("config", "src", "src.rss_collector", "import_career_news", "collect_career_news"):
                sys.modules.pop(name, None)
            handler = _load("zip_collector_handler", task / "collector_handler.py")
            categories, collect = handler.load_crawler()
            self.assertEqual(len(categories), 8)
            self.assertTrue(Path(sys.modules["config"].__file__).resolve().is_relative_to(task.resolve()))
            self.assertEqual(collect.__name__, "collect_google_news")

    def test_windows_binaries_and_wrong_runtime_are_rejected(self):
        cases = {
            "charset_normalizer/md.cp313-win_amd64.pyd": "Windows 전용 파일",
            "somepkg/helper.dll": "Windows 전용 파일",
            "somepkg-1.0.dist-info/win32.txt": "Windows 전용 파일",
            "charset_normalizer/cd.cpython-312-x86_64-linux-gnu.so": "다른 Python 버전",
            "charset_normalizer/cd.cpython-313-aarch64-linux-gnu.so": "다른 Python 버전",
        }
        for extra, message in cases.items():
            with self.subTest(extra=extra):
                deps = fake_deps(self.tmp / extra.replace("/", "_"), extra=[extra])
                out = self.tmp / "bad.zip"
                with self.assertRaises(build.PackageError) as caught:
                    build.build_zip("collector", out, deps)
                self.assertIn(message, str(caught.exception))
                self.assertFalse(out.exists())

    def test_installer_byproducts_are_excluded_but_exe_elsewhere_rejected(self):
        """uv를 Windows에서 실행하면 bin/에 Windows 콘솔 실행 파일(.exe)과 .lock이 생긴다 → ZIP에서 뺀다."""
        deps = fake_deps(self.tmp / "deps", extra=["bin/normalizer.exe", "bin/idna.exe", ".lock"])
        out = self.tmp / "collector.zip"
        names = build.build_zip("collector", out, deps)
        self.assertFalse(any(name.startswith("bin/") or name == ".lock" for name in names))
        build.check_zip_structure("collector", out)
        bad = fake_deps(self.tmp / "bad", extra=["requests/helper.exe"])
        with self.assertRaises(build.PackageError):
            build.build_zip("collector", self.tmp / "bad.zip", bad)

    def test_arm64_build_accepts_aarch64_modules(self):
        deps = fake_deps(self.tmp / "deps")
        (deps / "charset_normalizer" / "md.cpython-313-x86_64-linux-gnu.so").unlink()
        (deps / "charset_normalizer" / "md.cpython-313-aarch64-linux-gnu.so").write_bytes(b"\x7fELF")
        names = build.build_zip("collector", self.tmp / "arm.zip", deps, arch="aarch64")
        self.assertIn("charset_normalizer/md.cpython-313-aarch64-linux-gnu.so", names)

    def test_dependency_must_not_shadow_project_files(self):
        deps = fake_deps(self.tmp / "deps", extra=["config.py"])
        with self.assertRaises(build.PackageError) as caught:
            build.build_zip("collector", self.tmp / "c.zip", deps)
        self.assertIn("config.py", str(caught.exception))

    def test_cli_reports_error_without_creating_zip(self):
        stderr = io.StringIO()
        out = self.tmp / "cli.zip"
        original = sys.stderr
        sys.stderr = stderr
        try:
            code = build.main(["collector", "--out", str(out)])
        finally:
            sys.stderr = original
        self.assertEqual(code, 1)
        self.assertFalse(out.exists())
        self.assertIn("deps-dir", stderr.getvalue())
        self.assertEqual(json.dumps(build.HANDLERS, sort_keys=True),
                         json.dumps({"collector": "collector_handler.lambda_handler",
                                     "processor": "processor_handler.lambda_handler"}, sort_keys=True))


class VerifyZipTests(unittest.TestCase):
    """빌드된 ZIP 검증: 구조·원본 일치·금지 파일, 그리고 site-packages 없는 별도 프로세스 import."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def rewrite(self, source: Path, target: Path, change):
        """ZIP을 다시 쓰며 change(name, data) → (name, data) 또는 None(삭제)을 적용하고, 추가 파일도 넣는다."""
        with zipfile.ZipFile(source) as src, zipfile.ZipFile(target, "w") as dst:
            for info in src.infolist():
                result = change(info.filename, src.read(info.filename))
                if result is not None:
                    dst.writestr(result[0], result[1])
            for name, data in getattr(change, "extra", {}).items():
                dst.writestr(name, data)
        return target

    def test_processor_zip_passes_isolated_import_check(self):
        out = self.tmp / "processor.zip"
        build.build_zip("processor", out)
        result = build.verify_zip("processor", out)
        self.assertEqual(result["import_check"], "passed")
        self.assertEqual(result["import_report"]["outside"], [])
        self.assertFalse(result["import_report"]["boto3_imported"])

    def test_tampered_processor_zips_are_rejected(self):
        good = self.tmp / "good.zip"
        build.build_zip("processor", good)

        def extra(files):
            change = lambda name, data: (name, data)  # noqa: E731
            change.extra = files
            return change

        cases = {
            "저장소 원본과 다릅니다": lambda n, d: (n, d + b"\n# changed") if n == "import_career_news.py" else (n, d),
            "핸들러 파일이 ZIP 최상위에 없습니다": lambda n, d: None if n == "processor_handler.py" else (n, d),
            "Windows 전용 파일": extra({"charset_normalizer/md.cp313-win_amd64.pyd": b"x"}),
            "캐시 파일": extra({"__pycache__/processor_handler.cpython-313.pyc": b"x"}),
            "불필요한 파일": extra({"requests/__init__.py": b""}),
            "잘못된 경로": extra({"../evil.py": b""}),
            "AWS SDK(boto3)": extra({"boto3/__init__.py": b""}),
        }
        for message, change in cases.items():
            with self.subTest(message=message):
                bad = self.rewrite(good, self.tmp / "bad.zip", change)
                with self.assertRaises(build.PackageError) as caught:
                    build.verify_zip("processor", bad, run_import=False)
                self.assertIn(message, str(caught.exception))

    def test_nested_handler_layout_is_rejected(self):
        """폴더째 압축하면(예: news_lambda/processor_handler.py) Lambda가 핸들러를 찾지 못한다."""
        good = self.tmp / "good.zip"
        build.build_zip("processor", good)
        bad = self.rewrite(good, self.tmp / "nested.zip", lambda n, d: (f"news_lambda/{n}", d))
        with self.assertRaises(build.PackageError) as caught:
            build.verify_zip("processor", bad, run_import=False)
        self.assertIn("핸들러 파일이 ZIP 최상위에 없습니다", str(caught.exception))

    def test_collector_structure_passes_but_empty_fake_deps_fail_import(self):
        out = self.tmp / "collector.zip"
        build.build_zip("collector", out, fake_deps(self.tmp / "deps"))
        self.assertEqual(build.verify_zip("collector", out, run_import=False)["import_check"], "skipped")
        # 내용이 빈 가짜 의존성은 격리 import에서 실패해야 한다(검사가 실제로 ZIP만 본다는 증거).
        with self.assertRaises(build.PackageError) as caught:
            build.verify_zip("collector", out)
        self.assertIn("import하지 못했습니다", str(caught.exception))

    def test_processor_does_not_accept_dependency_folder(self):
        with self.assertRaises(build.PackageError):
            build.build_zip("processor", self.tmp / "p.zip", fake_deps(self.tmp / "deps"))

    def test_cli_verify_mode(self):
        out = self.tmp / "processor.zip"
        build.build_zip("processor", out)
        stdout = io.StringIO()
        original = sys.stdout
        sys.stdout = stdout
        try:
            code = build.main(["processor", "--verify", str(out)])
        finally:
            sys.stdout = original
        self.assertEqual(code, 0)
        self.assertIn('"import_check": "passed"', stdout.getvalue())


def fake_sdk(root: Path, skip=()):
    """boto3·botocore·s3transfer·jmespath·dateutil·six가 설치된 것처럼 보이는 빈 모듈."""
    for module in build.SDK_MODULES:
        if module in skip:
            continue
        if module == "six":
            (root / "six.py").write_text("", encoding="utf-8")
        else:
            (root / module).mkdir(parents=True, exist_ok=True)
            (root / module / "__init__.py").write_text("", encoding="utf-8")
    return root


class AwsSdkPackagingTests(unittest.TestCase):
    """Collector에만, --with-aws-sdk로 명시했을 때만 AWS SDK를 넣는다."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_sdk_in_deps_requires_explicit_flag(self):
        deps = fake_sdk(fake_deps(self.tmp / "deps"))
        with self.assertRaises(build.PackageError) as caught:
            build.build_zip("collector", self.tmp / "c.zip", deps)
        self.assertIn("--with-aws-sdk", str(caught.exception))
        self.assertFalse((self.tmp / "c.zip").exists())

    def test_collector_with_sdk_flag(self):
        deps = fake_sdk(fake_deps(self.tmp / "deps"))
        out = self.tmp / "collector-sdk.zip"
        names = build.build_zip("collector", out, deps, include_sdk=True)
        for name in ("boto3/__init__.py", "botocore/__init__.py", "s3transfer/__init__.py",
                     "jmespath/__init__.py", "dateutil/__init__.py", "six.py", "urllib3/__init__.py"):
            self.assertIn(name, names)
        result = build.verify_zip("collector", out, run_import=False, include_sdk=True)
        self.assertEqual((result["aws_sdk"], result["warnings"]), (True, []))
        # 같은 ZIP을 SDK 없이 검증하면 거부(명시 없이 SDK가 섞인 것으로 본다)
        with self.assertRaises(build.PackageError):
            build.verify_zip("collector", out, run_import=False)

    def test_partial_sdk_is_rejected(self):
        deps = fake_sdk(fake_deps(self.tmp / "deps"), skip=("jmespath",))
        with self.assertRaises(build.PackageError) as caught:
            build.build_zip("collector", self.tmp / "c.zip", deps, include_sdk=True)
        self.assertIn("jmespath", str(caught.exception))
        # SDK 일부만 든 ZIP도 검증에서 거부
        good = self.tmp / "good.zip"
        build.build_zip("collector", good, fake_sdk(fake_deps(self.tmp / "deps2")), include_sdk=True)
        bad = self.tmp / "bad.zip"
        with zipfile.ZipFile(good) as src, zipfile.ZipFile(bad, "w") as dst:
            for info in src.infolist():
                if not info.filename.startswith("dateutil/"):
                    dst.writestr(info.filename, src.read(info.filename))
        with self.assertRaises(build.PackageError) as caught:
            build.verify_zip("collector", bad, run_import=False, include_sdk=True)
        self.assertIn("의존성 누락: dateutil", str(caught.exception))

    def test_sdk_never_allowed_for_processor(self):
        with self.assertRaises(build.PackageError):
            build.build_zip("processor", self.tmp / "p.zip", include_sdk=True)
        out = self.tmp / "p.zip"
        build.build_zip("processor", out)
        with self.assertRaises(build.PackageError):
            build.verify_zip("processor", out, run_import=False, include_sdk=True)

    def test_collector_without_sdk_reports_aws_doc_warning(self):
        out = self.tmp / "collector.zip"
        build.build_zip("collector", out, fake_deps(self.tmp / "deps"))
        result = build.verify_zip("collector", out, run_import=False)
        self.assertFalse(result["aws_sdk"])
        self.assertEqual(result["warnings"], [build.NO_SDK_WARNING])
        processor = self.tmp / "processor.zip"
        build.build_zip("processor", processor)
        self.assertEqual(build.verify_zip("processor", processor, run_import=False)["warnings"], [])


class RequirementsLockTests(unittest.TestCase):
    """requirements-collector.txt가 uv.lock과 같은 버전·해시이고, 의존성 전체를 빠짐없이 담는지 확인한다."""

    @staticmethod
    def requirements(path=None):
        pins = {}
        current = None
        for line in (path or build.REQUIREMENTS).read_text(encoding="utf-8").splitlines():
            line = line.strip().rstrip("\\").strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("--hash="):
                pins[current]["hashes"].add(line.split("=", 1)[1])
            else:
                name, version = line.split("==")
                current = name.strip()
                pins[current] = {"version": version.strip(), "hashes": set()}
        return pins

    @staticmethod
    def lock():
        import tomllib

        with open(HERE.parents[1] / "uv.lock", "rb") as handle:
            return {package["name"]: package for package in tomllib.load(handle)["package"]}

    def test_versions_and_hashes_match_uv_lock(self):
        lock = self.lock()
        for name, pin in self.requirements().items():
            with self.subTest(name=name):
                self.assertEqual(pin["version"], lock[name]["version"])
                lock_hashes = {wheel["hash"] for wheel in lock[name].get("wheels", [])}
                self.assertTrue(pin["hashes"])
                self.assertTrue(pin["hashes"] <= lock_hashes)

    def test_requirements_cover_full_dependency_closure(self):
        lock = self.lock()
        closure, stack = set(), ["feedparser", "requests"]
        while stack:
            name = stack.pop()
            if name not in closure:
                closure.add(name)
                stack.extend(dep["name"] for dep in lock[name].get("dependencies", []))
        self.assertEqual(set(self.requirements()), closure)
        self.assertEqual(set(build.COLLECTOR_DISTRIBUTIONS), closure)

    def test_aws_sdk_requirements_are_pinned_and_separate(self):
        """SDK 파일: 6개 모두 버전·해시 고정, 기존 7개와 겹치지 않음(urllib3 등은 기존 파일의 고정 버전을 그대로 씀)."""
        sdk = self.requirements(build.REQUIREMENTS_SDK)
        self.assertEqual(set(sdk), set(build.COLLECTOR_SDK_DISTRIBUTIONS))
        self.assertFalse(set(sdk) & set(self.requirements()))
        for name, pin in sdk.items():
            with self.subTest(name=name):
                self.assertRegex(pin["version"], r"^\d+(\.\d+)+(\.post\d+)?$")
                self.assertTrue(pin["hashes"])
                self.assertTrue(all(re.fullmatch(r"sha256:[0-9a-f]{64}", h) for h in pin["hashes"]))
        self.assertEqual(sdk["boto3"]["version"], sdk["botocore"]["version"])  # boto3·botocore는 같은 번호로 함께 배포

    def test_linux_x86_64_wheel_hash_is_pinned_for_binary_package(self):
        lock = self.lock()
        pinned = self.requirements()["charset-normalizer"]["hashes"]
        linux = {wheel["hash"] for wheel in lock["charset-normalizer"]["wheels"]
                 if "cp313-cp313-manylinux" in wheel["url"] and "x86_64" in wheel["url"]}
        windows = {wheel["hash"] for wheel in lock["charset-normalizer"]["wheels"] if "win" in wheel["url"]}
        self.assertTrue(linux & pinned)
        self.assertFalse(windows & pinned)  # Windows wheel은 해시 목록에 없다 → 설치 거부


if __name__ == "__main__":
    unittest.main()
