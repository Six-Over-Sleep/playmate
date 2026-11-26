"""게시판 계약은 프론트와 공유하고, 선정 기준 변경은 별도 제품 결정이다."""
import json
from pathlib import Path

CONTRACT = json.loads((Path(__file__).resolve().parents[3] / "shared" / "boardPolicy.json").read_text(encoding="utf-8"))
NOTICE_BOARD_NAME = CONTRACT["noticeBoardName"]
FREE_BOARD_NAME = CONTRACT["freeBoardName"]
REPORT_HIDE_COUNT = 3
HOT_DAYS = 7
HOT_MIN_LIKES = 10
HALL_MIN_LIKES = 100
FEATURED_LIMIT = CONTRACT["featuredLimit"]
PAGE_SIZE = CONTRACT["pageSize"]
MAX_PAGE_SIZE = CONTRACT["maxPageSize"]
LIST_BODY_LENGTH = CONTRACT["listBodyLength"]
TITLE_MAX_LENGTH = CONTRACT["titleMaxLength"]
BODY_MAX_LENGTH = CONTRACT["bodyMaxLength"]
SEARCH_MAX_LENGTH = CONTRACT["searchMaxLength"]
