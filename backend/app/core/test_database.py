
from sqlalchemy import text
from backend.app.core.database import engine

with engine.connect() as conn:
    result = conn.execute(text("SELECT current_database(), current_user"))
    print("DB 연결 성공:", result.fetchone())

    tables = conn.execute(text("""
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
        ORDER BY table_name
    """))

    for table in tables:
        print(table[0])
