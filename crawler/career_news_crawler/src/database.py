"""기존 IT 뉴스 DB와 분리한 취업 뉴스 SQLite 저장소."""

import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "career_news.db"


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS news (
                news_id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                title TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT '',
                link TEXT NOT NULL,
                published TEXT,
                collected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (category, title, source)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_news_category_date ON news(category, published DESC)")


def replace_categories(category_articles: dict[str, list[dict]]) -> dict[str, int]:
    """기사가 1건 이상 수집된 분야만 새 결과로 교체; 빈 분야는 기존 데이터 유지."""
    saved = {}
    with get_connection() as conn:
        for category, articles in category_articles.items():
            if not articles:
                continue
            # 범주별 삭제와 삽입을 같은 트랜잭션 안에서 실행합니다.
            conn.execute("DELETE FROM news WHERE category = ?", (category,))
            conn.executemany(
                """INSERT OR IGNORE INTO news(category, title, source, link, published)
                   VALUES (?, ?, ?, ?, ?)""",
                [
                    (category, a["title"], a.get("source") or "", a["link"], a.get("published"))
                    for a in articles
                ],
            )
            saved[category] = conn.execute(
                "SELECT COUNT(*) FROM news WHERE category = ?", (category,)
            ).fetchone()[0]
    return saved


def get_news(category: str | None = None, limit: int = 300) -> list[dict]:
    limit = max(1, min(int(limit), 500))
    params = []
    sql = "SELECT news_id, category, title, source, link, published, collected_at FROM news"
    if category:
        sql += " WHERE category = ?"
        params.append(category)
    sql += " ORDER BY published DESC, news_id DESC LIMIT ?"
    params.append(limit)
    with get_connection() as conn:
        return [dict(row) for row in conn.execute(sql, params).fetchall()]
