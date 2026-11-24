"""Read-only source preflight for 052. Never connects to a database.

Run from the repository root:
    python -m backend.scripts.check_compat_view_references
This scans application sources, not historical SQL migrations or tests.
Deployment operators must also audit older workers, bots and external clients.
"""

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
COMPAT_VIEWS = (
    "career_posts", "career_reviews", "career_talks", "career_lounges",
    "career_labs", "career_lab_poll_options", "career_talk_attachments",
    "recruit_sports_details", "recruit_game_details", "recruit_study_details",
    "recruit_group_buy_details", "recruit_curricula",
)


def find_references():
    pattern = re.compile(r"\b(?:" + "|".join(COMPAT_VIEWS) + r")\b")
    matches = []
    for root in (ROOT / "backend/app", ROOT / "frontend/src", ROOT / "playmate-discord-bot"):
        for path in sorted(root.rglob("*")):
            if "tests" in path.relative_to(root).parts:
                continue
            if path.suffix not in {".py", ".js", ".jsx", ".ts", ".tsx"}:
                continue
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if pattern.search(line):
                    matches.append(f"{path.relative_to(ROOT)}:{number}: {line.strip()}")
    return matches


if __name__ == "__main__":
    references = find_references()
    print("\n".join(references) if references else "PASS: no compatibility view references")
    raise SystemExit(bool(references))
