"""취업 통계 SQL. 연결·커밋·롤백은 호출자가 관리한다."""

from psycopg2.extras import Json, execute_values

from app.services.job_trends_catalog import FIELDS, ROLES, KEYWORDS


def seed_catalog(cursor):
    execute_values(cursor, """
        INSERT INTO job_insights.fields (field_code, field_name) VALUES %s
        ON CONFLICT (field_code) DO UPDATE SET field_name = EXCLUDED.field_name
        """, FIELDS)
    execute_values(cursor, """
        INSERT INTO job_insights.roles (field_id, role_code, role_name)
        SELECT f.field_id, v.code, v.name
        FROM (VALUES %s) AS v(field, code, name)
        JOIN job_insights.fields AS f ON f.field_code = v.field
        ON CONFLICT (role_code) DO UPDATE
        SET field_id = EXCLUDED.field_id, role_name = EXCLUDED.role_name
        """, ROLES)
    execute_values(cursor, """
        INSERT INTO job_insights.keywords (keyword_code, keyword_name, keyword_type)
        VALUES %s ON CONFLICT (keyword_code) DO NOTHING
        """, KEYWORDS)
    cursor.execute("""
        INSERT INTO job_insights.keyword_aliases (keyword_id, alias_text)
        SELECT keyword_id, keyword_name FROM job_insights.keywords
        WHERE keyword_code IN ('python', 'java')
        ON CONFLICT (keyword_id, alias_text) DO NOTHING
        """)


def save_postings(cursor, rows):
    from app.services.job_trends_service import classify_roles, keyword_mentions

    # 키 목록은 공통 정규화기가 생성하며 외부 JSON의 키를 SQL로 사용하지 않는다.
    columns = tuple(rows[0])
    from psycopg2 import sql
    query = sql.SQL("""
        INSERT INTO job_insights.postings ({columns}) VALUES %s
        ON CONFLICT (source, source_job_id) DO UPDATE SET {updates},
            collected_at = CURRENT_TIMESTAMP
        RETURNING posting_id, source_job_id, (xmax = 0) AS inserted
        """).format(
            columns=sql.SQL(', ').join(map(sql.Identifier, columns)),
            updates=sql.SQL(', ').join(
                sql.SQL('{0} = EXCLUDED.{0}').format(sql.Identifier(key))
                for key in columns if key not in {'source', 'source_job_id'}
            ),
        ).as_string(cursor)
    values = [tuple(Json(row[key]) if key == 'raw_payload' else row[key] for key in columns) for row in rows]
    saved = execute_values(cursor, query, values, fetch=True)
    ids = {row['source_job_id']: row['posting_id'] for row in saved}
    cursor.execute("SELECT role_code, role_id FROM job_insights.roles")
    roles = {row['role_code']: row['role_id'] for row in cursor.fetchall()}
    cursor.execute("""
        SELECT k.keyword_code, k.keyword_id, a.alias_text
        FROM job_insights.keywords AS k
        JOIN job_insights.keyword_aliases AS a USING (keyword_id)
        """)
    keywords = list(cursor.fetchall())
    keyword_ids = {row['keyword_code']: row['keyword_id'] for row in keywords}
    aliases = [(row['keyword_code'], row['alias_text']) for row in keywords]
    # 이 모듈이 도출한 관계만 교체한다. 수동 대표 직무는 보존한다.
    role_values = []
    keyword_values = []
    for row in rows:
        posting_id = ids[row['source_job_id']]
        role_values.extend((posting_id, roles[code], False) for code in classify_roles(row))
        keyword_values.extend((posting_id, keyword_ids[code], source) for code, source in keyword_mentions(row, aliases))
    cursor.execute("""
        DELETE FROM job_insights.posting_roles
        WHERE posting_id = ANY(%s) AND assignment_source = 'title' AND NOT is_primary
        """, (list(ids.values()),))
    if role_values:
        execute_values(cursor, """
            INSERT INTO job_insights.posting_roles (posting_id, role_id, is_primary, assignment_source)
            SELECT v.posting_id, v.role_id, v.is_primary, 'title'
            FROM (VALUES %s) AS v(posting_id, role_id, is_primary)
            ON CONFLICT (posting_id, role_id) DO NOTHING
            """, role_values)
    cursor.execute("""
        DELETE FROM job_insights.posting_keywords
        WHERE posting_id = ANY(%s) AND mention_source IN ('title', 'api_keyword')
        """, (list(ids.values()),))
    if keyword_values:
        execute_values(cursor, """
            INSERT INTO job_insights.posting_keywords (posting_id, keyword_id, mention_source)
            VALUES %s ON CONFLICT DO NOTHING
            """, keyword_values)
    inserted = sum(row['inserted'] for row in saved)
    return inserted, len(saved) - inserted
