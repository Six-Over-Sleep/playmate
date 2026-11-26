"""Flask 뉴스 목록 페이지 및 대시보드 연동용 JSON API."""

from flask import Flask, jsonify, render_template, request

from config import CATEGORIES
from src.database import get_news, init_db

app = Flask(__name__)


@app.route("/")
def index():
    init_db()
    category = request.args.get("category", "")
    if category not in CATEGORIES:
        category = ""
    return render_template(
        "index.html",
        news=get_news(category=category or None),
        categories=list(CATEGORIES),
        selected_category=category,
    )


@app.route("/api/news")
def api_news():
    init_db()
    category = request.args.get("category", "").strip()
    if category and category not in CATEGORIES:
        return jsonify({"error": "알 수 없는 분야입니다.", "categories": list(CATEGORIES)}), 400
    raw_limit = request.args.get("limit", "30")
    try:
        limit = int(raw_limit)
        if limit < 1 or limit > 500:
            raise ValueError
    except ValueError:
        return jsonify({"error": "limit은 1~500 사이의 정수여야 합니다."}), 400
    news = get_news(category=category or None, limit=limit)
    for article in news:
        article["field_code"] = CATEGORIES[article["category"]]["code"]
    return jsonify({"category": category or None, "count": len(news), "news": news})


if __name__ == "__main__":
    init_db()
    app.run(host="127.0.0.1", port=5000, debug=True)
