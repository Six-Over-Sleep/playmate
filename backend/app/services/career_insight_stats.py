"""Common aggregation for a validated Saramin preview or database rows."""
from collections import Counter
import json
from pathlib import Path

PREVIEW_PATH = Path(__file__).resolve().parents[3] / 'saramin_insights_preview.json'
FIELDS = ('job_roles', 'specialties', 'tech_stacks', 'certifications', 'preferences')


def validate_rows(value):
    if not isinstance(value, list):
        raise ValueError('공고 목록 형식이 아닙니다.')
    rows, seen = [], set()
    for row in value:
        if not isinstance(row, dict) or not row.get('source_id'):
            raise ValueError('공고 식별자가 없습니다.')
        key = (row.get('source', 'saramin_web'), str(row['source_id']))
        if key in seen:
            continue
        seen.add(key)
        normalized = dict(row)
        for field in FIELDS:
            items = row.get(field) or []
            if not isinstance(items, list) or any(not isinstance(item, str) for item in items):
                raise ValueError(f'{field} 형식이 올바르지 않습니다.')
            normalized[field] = list(dict.fromkeys(item.strip() for item in items if item.strip()))
        year, quarter = row.get('collection_year'), row.get('collection_quarter')
        if not isinstance(year, int) or quarter not in (1, 2, 3, 4):
            raise ValueError('수집 분기가 올바르지 않습니다.')
        rows.append(normalized)
    return rows


def load_preview(path=PREVIEW_PATH):
    return validate_rows(json.loads(Path(path).read_text(encoding='utf-8')))


def options(rows):
    return {
        'quarters': sorted({f"{r['collection_year']}-Q{r['collection_quarter']}" for r in rows}, reverse=True),
        'fields': sorted({item for r in rows for item in r['specialties']}),
        'skills': sorted({item for r in rows for item in r['tech_stacks']}),
        'total': len(rows),
    }


def ranked(rows, field):
    counts = Counter(item for row in rows for item in row[field])
    return [{'name': name, 'count': count} for name, count in sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))]


def summarize(rows, quarter=None, field=None, skill=None, source='preview'):
    selected = [r for r in rows if
                (not quarter or f"{r['collection_year']}-Q{r['collection_quarter']}" == quarter)
                and (not field or field in r['specialties'])
                and (not skill or skill in r['tech_stacks'])]
    trend_basis = [r for r in rows if (not field or field in r['specialties'])
                   and (not skill or skill in r['tech_stacks'])]
    trend_counts = Counter(f"{r['collection_year']}-Q{r['collection_quarter']}" for r in trend_basis)
    observed = options(rows)['quarters']
    times = [str(r['collected_at']) for r in rows if r.get('collected_at')]
    return {
        'source': source, 'count': len(selected), 'total': len(rows),
        'filters': {'quarter': quarter, 'field': field, 'skill': skill},
        'roles': ranked(selected, 'job_roles'), 'fields': ranked(selected, 'specialties'),
        'skills': ranked(selected, 'tech_stacks'),
        'certifications': ranked(selected, 'certifications'),
        'preferences': ranked(selected, 'preferences'),
        'coverage': {name: sum(bool(r[key]) for r in selected) for name, key in
                     [('field', 'specialties'), ('skill', 'tech_stacks'),
                      ('certification', 'certifications'), ('preference', 'preferences')]},
        'trend': [{'id': q, 'count': trend_counts[q]} for q in reversed(observed)],
        'collected_from': min(times) if times else None,
        'collected_to': max(times) if times else None,
    }
