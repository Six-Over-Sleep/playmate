"""CloudFormation 변경 세트에서 SQS 큐 삭제·교체를 찾아 실행 전에 멈춘다 (AWS를 호출하지 않는다. JSON 파일만 읽는다).

사용 (DEPLOY.md 15.9):
  sam deploy ... --no-execute-changeset                      # 변경 세트만 만든다
  aws cloudformation describe-change-set --stack-name <스택> --change-set-name <이름> --output json > changeset.json
  python infra/discord-serverless/check_changeset.py changeset.json
종료 코드 0 = 큐 삭제·교체 없음, 1 = 있음 (목록 출력). 1이면 변경 세트를 실행하지 않는다.
"""
import json
import sys
from pathlib import Path

QUEUE_TYPE = "AWS::SQS::Queue"


def risky_changes(change_set: dict) -> list[str]:
    """큐를 지우거나(Remove) 새로 만드는(Replacement True/Conditional) 변경 목록."""
    found = []
    for change in change_set.get("Changes") or []:
        resource = change.get("ResourceChange") or {}
        if resource.get("ResourceType") != QUEUE_TYPE:
            continue
        action = resource.get("Action")
        replacement = resource.get("Replacement")
        logical = resource.get("LogicalResourceId", "?")
        if action == "Remove":
            found.append(f"{logical}: Remove (큐와 메시지 삭제. DeletionPolicy Retain이면 스택에서만 빠지고 남는다)")
        elif action == "Modify" and replacement in ("True", "Conditional"):
            found.append(f"{logical}: Replacement={replacement} (새 큐 생성. 이름이 고정이라 실패하거나 기존 메시지와 분리된다)")
    return found


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("사용: python check_changeset.py <describe-change-set 출력 JSON>")
        return 2
    data = json.loads(Path(args[0]).read_text(encoding="utf-8-sig"))
    found = risky_changes(data)
    if found:
        print("SQS 큐 삭제·교체가 포함되어 있습니다. 변경 세트를 실행하지 마세요:")
        for line in found:
            print(f"  - {line}")
        return 1
    print("SQS 큐 삭제·교체 없음")
    return 0


if __name__ == "__main__":
    sys.exit(main())
