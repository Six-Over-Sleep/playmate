"""채용 인사이트 CSV 적재 스크립트의 DB 없는 검증 (CSV 검증·URL 정규화·충돌 분류·dry-run·실행 기록)."""
import csv
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "import_career_insight_csv", ROOT / "database" / "scripts" / "import_career_insight_csv.py"
)
importer = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = importer  # dataclass가 모듈을 조회할 수 있게 등록
SPEC.loader.exec_module(importer)

SARAMIN_URL = "https://www.saramin.co.kr/zf_user/jobs/relay/view?view_type=list&rec_idx=55437229"
ITCH_ID = "68b4237c-fe01-43ea-b130-c2af7b3c54ed"


def row(**overrides):
    base = {
        "source_id": "55437229", "source": "saramin_web", "title": "백엔드 개발자", "company": "",
        "url": SARAMIN_URL, "job_roles": json.dumps(["백엔드"]), "specialties": "[]",
        "tech_stacks": json.dumps(["Java"]), "certifications": "[]", "preferences": "[]",
        "raw_tags": json.dumps(["백엔드/서버개발"]), "role_classification_source": "tag",
        "detail_status": "not_requested", "collected_at": "2026-11-20T15:45:46+09:00",
        "collection_year": "2026", "collection_quarter": "4",
    }
    base.update(overrides)
    return base


def itch_row(**overrides):
    values = dict(source="itchaeyong", source_id=ITCH_ID, url=f"https://itchaeyong.com/jobs/{ITCH_ID}",
                  raw_tags=json.dumps(["백엔드 · 경력 · 서울 · 정규직"]))
    return row(**(values | overrides))


def write_csv(tmp_path, rows):
    path = tmp_path / "load.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return path


def parsed(tmp_path, *rows):
    return importer.read_rows(write_csv(tmp_path, list(rows)))


# -- CSV 검증 --------------------------------------------------------------------------------------------------
def test_ids_are_stored_as_original_without_prefix(tmp_path):
    saramin, itch = parsed(tmp_path, row(), itch_row())
    assert (saramin["source"], saramin["source_id"]) == ("saramin_web", "55437229")
    assert (itch["source"], itch["source_id"]) == ("itchaeyong", ITCH_ID)
    assert itch["raw_tags"] == ["백엔드 · 경력 · 서울 · 정규직"]           # JSONB로 보낼 파이썬 값
    assert "certifications" not in saramin and "preferences" not in saramin
    assert importer.table() == "public.job_postings"


@pytest.mark.parametrize("overrides, message", [
    ({"source": "unknown"}, "허용되지 않은 출처"),
    ({"source": "saramin"}, "허용되지 않은 출처"),                          # CSV 출처 코드는 saramin_web만
    ({"source_id": "itchaeyong:abc", "source": "itchaeyong"}, "접두어"),
    ({"source_id": "abc"}, "숫자"),
    ({"url": SARAMIN_URL.replace("55437229", "1")}, "rec_idx"),
    ({"title": " "}, "제목"),
    ({"url": "ftp://x"}, "URL"),
    ({"job_roles": "[]"}, "직무"),
    ({"tech_stacks": "Java"}, "JSON 배열"),
    ({"tech_stacks": json.dumps(["", "Java"])}, "문자열 배열"),
    ({"raw_tags": "{bad"}, "raw_tags"),
    ({"raw_tags": json.dumps({"a": 1})}, "raw_tags"),
    ({"certifications": json.dumps(["SQLD"])}, "정보 손실"),
    ({"preferences": json.dumps(["우대"])}, "정보 손실"),
    ({"collected_at": "2026-11-20T15:45:46"}, "시간대"),
    ({"collection_quarter": "3"}, "분기"),
])
def test_invalid_rows_are_rejected(tmp_path, overrides, message):
    with pytest.raises(ValueError, match=message):
        parsed(tmp_path, row(**overrides))


def test_itchaeyong_url_must_match_id(tmp_path):
    with pytest.raises(ValueError, match="IT 채용 레이더 URL"):
        parsed(tmp_path, itch_row(url="https://itchaeyong.com/jobs/other"))


@pytest.mark.parametrize("second, label", [
    (row(), r"\(source, source_id\)"),
    (row(source_id="55437230", url=SARAMIN_URL.replace("55437229", "55437230")), None),   # 정상: 다른 공고
    (itch_row(), None),
])
def test_csv_internal_duplicates(tmp_path, second, label):
    if label:
        with pytest.raises(ValueError, match=label):
            parsed(tmp_path, row(), second)
    else:
        assert len(parsed(tmp_path, row(), second)) == 2


def test_arrays_are_trimmed_and_deduplicated(tmp_path):
    [r] = parsed(tmp_path, row(tech_stacks=json.dumps(["Java", " Java ", "Go"])))
    assert r["tech_stacks"] == ["Java", "Go"]


# -- URL 정규화 (충돌 감지 전용, 저장값은 그대로) ----------------------------------------------------------------
def test_normalized_url_ignores_saramin_tracking_parameters():
    tracked = SARAMIN_URL + "&adsCategoryItem=effect_bold&"
    assert importer.normalized_url(tracked) == importer.normalized_url(SARAMIN_URL) == "saramin:rec_idx=55437229"
    assert importer.normalized_url("https://saramin.co.kr/zf_user/jobs/view?rec_idx=55437229") == "saramin:rec_idx=55437229"


def test_normalized_url_for_other_sources():
    base = f"https://itchaeyong.com/jobs/{ITCH_ID}"
    assert importer.normalized_url(base + "/?utm_source=x#top") == importer.normalized_url(base)
    assert importer.normalized_url(base + "?page=2") != importer.normalized_url(base)   # 의미 있는 파라미터는 유지


# -- 충돌 분류 (DB 조회 결과를 넣는 순수 함수) -------------------------------------------------------------------
def test_classify_every_case(tmp_path):
    rows = parsed(
        tmp_path,
        row(),                                                                                   # 1 신규
        row(source_id="2", url=SARAMIN_URL.replace("55437229", "2")),                            # 2 기존 PK
        row(source_id="3", url=SARAMIN_URL.replace("55437229", "3")),                            # 3 같은 URL 다른 PK
        row(source_id="4", url=SARAMIN_URL.replace("55437229", "4")),                            # 4 saramin <-> saramin_web
        row(source_id="5", url=SARAMIN_URL.replace("55437229", "5") + "&adsCategoryItem=x"),      # 5 추적 파라미터만 다름
    )
    existing = [
        ("saramin_web", "2", "https://www.saramin.co.kr/zf_user/jobs/relay/view?rec_idx=2&view_type=list"),
        ("itchaeyong", "zzz", SARAMIN_URL.replace("55437229", "3")),
        ("saramin", "4", "https://www.saramin.co.kr/zf_user/jobs/view?rec_idx=4"),
        ("saramin_web", "999", SARAMIN_URL.replace("55437229", "5")),
    ]
    plan = importer.classify(rows, existing, table_rows_before=10)
    assert [r["source_id"] for r in plan.new_rows] == ["55437229"]
    assert plan.existing_pk == [("saramin_web", "2")]
    assert [k for k, _ in plan.url_conflicts] == [("saramin_web", "3")]
    assert plan.source_mismatch == [(("saramin_web", "4"), ("saramin", "4"))]
    assert plan.normalized_conflicts == [(("saramin_web", "5"), ("saramin_web", "999"))]
    assert (plan.blocked, plan.expected_total) == (3, 11)


def test_classify_empty_table_all_new(tmp_path):
    plan = importer.classify(parsed(tmp_path, row(), itch_row()), [], table_rows_before=0)
    assert (plan.new, plan.blocked, len(plan.existing_pk), plan.expected_total) == (2, 0, 0, 2)


# -- CLI: dry-run·안전 장치 -------------------------------------------------------------------------------------
def forbidden_factory(commit):
    raise AssertionError("DB에 접근하면 안 됩니다")


def test_default_run_is_dry_run_without_db(tmp_path, monkeypatch, capsys):
    import app.core.db_connect as db_connect

    def forbidden(*args, **kwargs):
        raise AssertionError("dry-run에서 DB에 연결하면 안 됩니다")

    monkeypatch.setattr(db_connect, "db_cursor", forbidden)
    monkeypatch.setattr(db_connect, "get_connection", forbidden)
    assert importer.main([str(write_csv(tmp_path, [row(), itch_row()]))]) == 0
    out = capsys.readouterr().out
    assert "DB에 연결하지 않았습니다" in out and "public.job_postings" in out


def test_apply_requires_expected_rows(tmp_path):
    with pytest.raises(SystemExit):
        importer.main([str(write_csv(tmp_path, [row()])), "--apply"])


def test_invalid_csv_stops_before_db(tmp_path):
    path = write_csv(tmp_path, [row(source="bad")])
    assert importer.main([str(path), "--apply", "--expected-rows", "1"], cursor_factory=forbidden_factory) == 2


def test_only_one_target_allowed(tmp_path):
    path = write_csv(tmp_path, [row()])
    for argv in ([str(path), "--rollback-manifest", str(path)], ["--rollback-manifest", "a", "--reconcile-manifest", "b"], []):
        with pytest.raises(SystemExit):
            importer.main(argv)


# -- 실행 기록 -------------------------------------------------------------------------------------------------
def manifest_data(status="committed", table="public.job_postings", **over):
    from datetime import datetime, timezone
    data = {
        "manifest_version": 2, "run_id": "r1", "table": table, "status": status,
        "created_at": datetime.now(timezone.utc).isoformat(), "transaction_time": "2026-11-20T12:00:00.123456+00:00",
        "inserted": 2, "inserted_keys": [["itchaeyong", ITCH_ID, "123456"], ["saramin_web", "55437229", "123456"]],
    }
    data.update(over)
    return data


def manifest(tmp_path, status="committed", table="public.job_postings", **over):
    path = tmp_path / "run.json"
    path.write_text(json.dumps(manifest_data(status, table, **over)), encoding="utf-8")
    return path


@pytest.mark.parametrize("over, message", [
    ({"manifest_version": 1}, "버전"),
    ({"inserted_keys": [["itchaeyong", ITCH_ID], ["saramin_web", "55437229"]]}, "키 형식"),        # xmin 없음 (구 형식)
    ({"inserted_keys": [["itchaeyong", ITCH_ID, "abc"], ["saramin_web", "55437229", "123456"]]}, "키 형식"),
    ({"inserted": 3}, "기록 불완전"),                                                                 # 일부 키 누락
    ({"inserted_keys": [["itchaeyong", ITCH_ID, "1"], ["itchaeyong", ITCH_ID, "1"]]}, "중복"),
    ({"inserted_keys": [["itchaeyong", ITCH_ID, "1"], ["saramin_web", "55437229", "2"]]}, "xmin이 서로"),
    ({"created_at": "2026-11-20T12:00:00"}, "시간대"),
    ({"transaction_time": "어제"}, "시각 형식"),
])
def test_damaged_or_incomplete_manifest_is_refused(tmp_path, over, message):
    path = manifest(tmp_path, **over)
    with pytest.raises(ValueError, match=message):
        importer.load_manifest(path)
    assert importer.main(["--rollback-manifest", str(path), "--apply", "--expected-rows", "2"],
                         cursor_factory=forbidden_factory) == 2


@pytest.mark.parametrize("content", ["{not json", "[]", ""])
def test_corrupted_manifest_file_stops_safely(tmp_path, content):
    path = tmp_path / "broken.json"
    path.write_text(content, encoding="utf-8")
    for flag in ("--rollback-manifest", "--reconcile-manifest"):
        assert importer.main([flag, str(path), "--apply", "--expected-rows", "1"], cursor_factory=forbidden_factory) == 2


def test_missing_manifest_file_stops_safely(tmp_path):
    assert importer.main(["--rollback-manifest", str(tmp_path / "none.json"), "--apply", "--expected-rows", "1"],
                         cursor_factory=forbidden_factory) == 2


@pytest.mark.parametrize("days", [8, -1])
def test_old_or_future_manifest_is_not_rolled_back_automatically(tmp_path, capsys, days):
    from datetime import datetime, timedelta, timezone
    created = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    path = manifest(tmp_path, created_at=created)
    assert importer.main(["--rollback-manifest", str(path), "--apply", "--expected-rows", "2"],
                         cursor_factory=forbidden_factory) == 2
    assert "자동 롤백하지 않습니다" in capsys.readouterr().out


@pytest.mark.parametrize("flag", ["--rollback-manifest", "--reconcile-manifest"])
@pytest.mark.parametrize("status", ["committed", "commit_unknown", "pending"])
def test_manifest_modes_default_to_dry_run(tmp_path, capsys, flag, status):
    assert importer.main([flag, str(manifest(tmp_path, status))], cursor_factory=forbidden_factory) == 0
    assert "DB에 연결하지 않았습니다" in capsys.readouterr().out


@pytest.mark.parametrize("status", ["rolled_back", "reverted", "not_committed"])
def test_finished_manifests_are_refused(tmp_path, status):
    path = manifest(tmp_path, status)
    assert importer.main(["--rollback-manifest", str(path), "--apply", "--expected-rows", "2"],
                         cursor_factory=forbidden_factory) == 2


def test_manifest_for_old_table_is_refused(tmp_path):
    path = manifest(tmp_path, table="saramin_insight_jobs")
    assert importer.main(["--rollback-manifest", str(path), "--preview-db"], cursor_factory=forbidden_factory) == 2


def test_rollback_apply_requires_expected_rows(tmp_path):
    with pytest.raises(SystemExit):
        importer.main(["--rollback-manifest", str(manifest(tmp_path)), "--apply"])


def test_reconcile_verdicts():
    rc = importer.Reconcile
    assert rc(manifest_rows=2, matching=[1, 2]).verdict == "committed"
    assert rc(manifest_rows=2, matching=[1], changed=[2]).verdict == "committed"      # 일치 행이 있어 커밋 증명
    assert rc(manifest_rows=2, matching=[1], missing=[2]).verdict == "mixed"
    assert rc(manifest_rows=2, missing=[1, 2]).verdict == "not_committed"
    assert rc(manifest_rows=2, changed=[1], missing=[2]).verdict == "unknown", "남은 행이 모두 바뀜: 커밋 증명 불가 -> 보류"
    assert rc(manifest_rows=2, changed=[1, 2]).verdict == "unknown"
    assert rc(manifest_rows=0).verdict == "empty"


def test_new_manifest_records_xmin_and_version():
    from datetime import datetime, timezone
    plan = importer.Plan(total=2, transaction_time=datetime(2026, 11, 20, tzinfo=timezone.utc),
                         inserted_keys=[("saramin_web", "1", "777"), ("itchaeyong", "a", "777")])
    data = importer.new_manifest(Path("x.csv"), "d" * 64, plan)
    assert (data["manifest_version"], data["inserted"], data["status"]) == (2, 2, "pending")
    assert data["inserted_keys"] == [["saramin_web", "1", "777"], ["itchaeyong", "a", "777"]]
    assert data["ownership"] == ["source", "source_id", "updated_at", "xmin"]


# -- 대시보드 API 오류 처리 (라우터는 이번 작업에서 수정하지 않음) --------------------------------------------------
def test_db_api_failure_returns_503_for_dashboard_error_ui(client, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@127.0.0.1:1/none?connect_timeout=1")
    for path in ("/api/career/insights/db/summary", "/api/career/insights/db/filters"):
        response = client.get(path)
        assert response.status_code == 503 and "불러올 수 없습니다" in response.json()["detail"]
