"""배포 전 필수 스키마·XP 정책 검사 (테스트 아님, 읽기 전용).

새 버전을 띄우기 전에 대상 DB(.env 또는 환경변수의 DB_*)에 대해 실행한다.
누락이 있으면 필요한 SQL 파일이나 정책 행을 출력하고 종료 코드 1로 끝난다.

사용: 프로젝트 루트에서  python -m backend.scripts.check_deploy_schema
"""

import sys


def main() -> int:
    from backend.app.core.schema_check import run_check

    report = run_check()
    for line in report.lines():
        print(line)
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
