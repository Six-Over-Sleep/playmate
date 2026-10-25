import { useMemo, useState } from 'react'
import {
    CAREER_POSTINGS_DEMO,
    CAREER_QUARTERS,
    FIELD_DICTIONARY,
    KEYWORD_DICTIONARY,
    ROLE_DICTIONARY,
} from '../../data/careerInsightsDemo'
import '../../styles/CareerInsights.css'

const ALL = '전체'
const number = (value) => value.toLocaleString('ko-KR')
const percent = (value) => `${value.toFixed(1)}%`

// 한 공고에 키워드가 여러 번 있어도 공고당 최대 한 번만 집계합니다.
function rankBy(rows, key) {
    const counts = new Map()
    rows.forEach((row) => {
        const values = Array.isArray(row[key]) ? [...new Set(row[key])] : [row[key]]
        values.filter(Boolean).forEach((value) => {
            counts.set(value, (counts.get(value) || 0) + 1)
        })
    })
    return [...counts].map(([name, count]) => ({ name, count }))
        .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name, 'ko'))
}

function salaryStatistics(rows) {
    // 비교 가능한 연봉 범위가 모두 있는 공고만 평균 산정에 포함합니다.
    const reported = rows.filter((row) => (
        row.salary_period === 'YEAR' &&
        Number.isFinite(row.salary_min_krw) &&
        Number.isFinite(row.salary_max_krw)
    ))
    const average = reported.length
        ? reported.reduce((sum, row) => sum + (row.salary_min_krw + row.salary_max_krw) / 2, 0) / reported.length
        : null
    return { average, count: reported.length }
}

function changeRate(current, previous) {
    return previous > 0 ? (current - previous) / previous * 100 : null
}

function withPreviousQuarter(items, previousRows, key, hasPreviousQuarter) {
    const previousCounts = new Map(rankBy(previousRows, key).map((item) => [item.name, item.count]))
    return items.map((item) => ({
        ...item,
        growth: hasPreviousQuarter ? changeRate(item.count, previousCounts.get(item.name) || 0) : null,
        newEntry: hasPreviousQuarter && !previousCounts.has(item.name),
    }))
}

function formatRate(rate) {
    if (rate === null) return '비교 불가'
    return `${rate > 0 ? '+' : ''}${percent(rate)}`
}

function formatSalary(value) {
    return value === null ? '데이터 없음' : `${number(Math.round(value / 10000))}만원`
}

function SectionTitle({ eyebrow, title, description, extra }) {
    return (
        <div className="career-ci-section-title">
            <div>
                <span>{eyebrow}</span>
                <h3>{title}</h3>
                <p>{description}</p>
            </div>
            {extra && <div className="career-ci-section-extra">{extra}</div>}
        </div>
    )
}

function Ranking({ items, limit = 8, maxLabel = '건', onSelect, selected }) {
    const top = items.slice(0, limit)
    const max = Math.max(1, ...top.map((item) => item.count))

    if (!top.length) {
        return <p className="career-ci-empty">해당 조건에서 집계된 키워드가 없어요.</p>
    }

    return (
        <div className="career-ci-ranking">
            {top.map((item, index) => {
                const content = (
                    <>
                        <span className="career-ci-rank-no">{index + 1}</span>
                        <span className="career-ci-rank-body">
                            <span className="career-ci-rank-text">
                                <span>{item.name}</span>
                                <strong>{number(item.count)}{maxLabel}</strong>
                            </span>
                            <span className="career-ci-bar-track" aria-hidden="true">
                                <span style={{ width: `${item.count / max * 100}%` }} />
                            </span>
                            {Object.hasOwn(item, 'growth') && (
                                <span className={`career-ci-rank-growth ${item.growth !== null && item.growth >= 0 ? 'up' : ''}`}>
                                    전 분기 대비 {item.newEntry ? '신규 등장' : formatRate(item.growth)}
                                </span>
                            )}
                        </span>
                    </>
                )
                return onSelect ? (
                    <button
                        key={item.name}
                        type="button"
                        className={`career-ci-rank career-ci-rank-button ${selected === item.name ? 'selected' : ''}`}
                        onClick={() => onSelect(item.name)}
                        aria-pressed={selected === item.name}
                        title={`${item.name} 필터 적용`}
                    >
                        {content}
                    </button>
                ) : (
                    <div className="career-ci-rank" key={item.name}>{content}</div>
                )
            })}
        </div>
    )
}

function QuarterTrend({ data, currentQuarter, onSelectQuarter }) {
    const max = Math.max(1, ...data.map((item) => item.count))
    const width = 720
    const height = 190
    const padX = 40
    const padY = 23
    const plotHeight = 138
    const plotWidth = width - padX * 2
    const point = (item, index) => ({
        x: padX + (data.length === 1 ? 0 : (index / (data.length - 1)) * plotWidth),
        y: height - padY - (item.count / max) * plotHeight,
    })
    const points = data.map(point)
    const line = points.map(({ x, y }) => `${x},${y}`).join(' ')

    return (
        <div className="career-ci-trend-wrap">
            <svg
                className="career-ci-trend-graph"
                viewBox={`0 0 ${width} ${height}`}
                role="img"
                aria-label={data.map((item) => `${item.label}: ${item.count}건`).join(', ')}
            >
                {[0, 0.5, 1].map((fraction) => {
                    const y = height - padY - fraction * plotHeight
                    return (
                        <g key={fraction}>
                            <line x1={padX} y1={y} x2={width - padX} y2={y} className="career-ci-gridline" />
                            <text x={padX - 9} y={y + 4} textAnchor="end" className="career-ci-axis-label">
                                {Math.round(max * fraction)}
                            </text>
                        </g>
                    )
                })}
                <polyline points={line} fill="none" className="career-ci-chart-line" />
                {points.map(({ x, y }, index) => (
                    <g key={data[index].id}>
                        <circle cx={x} cy={y} r={data[index].id === currentQuarter ? 6 : 4.2} className={data[index].id === currentQuarter ? 'career-ci-dot active' : 'career-ci-dot'} />
                        <text x={x} y={Math.max(14, y - 13)} textAnchor="middle" className="career-ci-point-label">
                            {data[index].count}
                        </text>
                        <text x={x} y={height - 1} textAnchor="middle" className="career-ci-axis-label">
                            {data[index].shortLabel}
                        </text>
                    </g>
                ))}
            </svg>
            <div className="career-ci-quarter-buttons" aria-label="분기 선택">
                {data.map((item) => (
                    <button
                        type="button"
                        key={item.id}
                        className={item.id === currentQuarter ? 'active' : ''}
                        onClick={() => onSelectQuarter(item.id)}
                        aria-pressed={item.id === currentQuarter}
                    >
                        {item.shortLabel}
                    </button>
                ))}
            </div>
        </div>
    )
}

function SalaryRanking({ items }) {
    const available = items.filter((item) => item.average !== null).slice(0, 8)
    const max = Math.max(1, ...available.map((item) => item.average))

    if (!available.length) {
        return <p className="career-ci-empty">연봉이 공개된 공고가 없습니다.</p>
    }

    return (
        <div className="career-ci-salary-list">
            {available.map((item) => (
                <div className="career-ci-salary-item" key={item.name}>
                    <div className="career-ci-salary-label">
                        <span>{item.name}</span>
                        <strong>{formatSalary(item.average)}</strong>
                    </div>
                    <div className="career-ci-bar-track salary" aria-hidden="true">
                        <span style={{ width: `${item.average / max * 100}%` }} />
                    </div>
                    <small>급여 공개 공고 {number(item.count)}건</small>
                </div>
            ))}
        </div>
    )
}

/**
 * 분기별 채용 인사이트 — 키워드 기반 분석 화면.
 * CareerPage에서 <CareerInsights />를 그대로 사용합니다.
 */
export default function CareerInsights() {
    const [quarterId, setQuarterId] = useState(CAREER_QUARTERS[CAREER_QUARTERS.length - 1].id)
    const [field, setField] = useState(ALL)
    const [role, setRole] = useState(ALL)
    const [treeRole, setTreeRole] = useState(ALL)

    const roles = useMemo(() => (
        field === ALL
            ? FIELD_DICTIONARY.flatMap((item) => item.roles)
            : FIELD_DICTIONARY.find((item) => item.name === field)?.roles || []
    ), [field])

    const selectedRows = useMemo(() => CAREER_POSTINGS_DEMO.filter((row) => (
        row.quarter === quarterId &&
        (field === ALL || row.field === field) &&
        (role === ALL || row.role === role)
    )), [quarterId, field, role])

    const selectedIndex = CAREER_QUARTERS.findIndex((item) => item.id === quarterId)
    const previousQuarter = selectedIndex > 0 ? CAREER_QUARTERS[selectedIndex - 1] : null

    const priorRows = useMemo(() => CAREER_POSTINGS_DEMO.filter((row) => (
        row.quarter === previousQuarter?.id &&
        (field === ALL || row.field === field) &&
        (role === ALL || row.role === role)
    )), [previousQuarter?.id, field, role])

    const fieldRanking = useMemo(() => rankBy(selectedRows, 'field'), [selectedRows])
    const roleRanking = useMemo(() => rankBy(selectedRows, 'role'), [selectedRows])
    const fieldDemand = useMemo(() => withPreviousQuarter(fieldRanking, priorRows, 'field', Boolean(previousQuarter)), [fieldRanking, priorRows, previousQuarter?.id])
    const roleDemand = useMemo(() => withPreviousQuarter(roleRanking, priorRows, 'role', Boolean(previousQuarter)), [roleRanking, priorRows, previousQuarter?.id])
    const certRanking = useMemo(() => rankBy(selectedRows, 'certifications'), [selectedRows])
    const preferenceRanking = useMemo(() => rankBy(selectedRows, 'preferences'), [selectedRows])
    const skillRanking = useMemo(() => rankBy(selectedRows, 'skills'), [selectedRows])
    const salary = useMemo(() => salaryStatistics(selectedRows), [selectedRows])

    const trend = useMemo(() => CAREER_QUARTERS.map((quarter) => ({
        id: quarter.id,
        label: quarter.label,
        shortLabel: `${String(quarter.year).slice(2)}년 ${quarter.quarter}Q`,
        count: CAREER_POSTINGS_DEMO.filter((row) => (
            row.quarter === quarter.id &&
            (field === ALL || row.field === field) &&
            (role === ALL || row.role === role)
        )).length,
    })), [field, role])

    const salaryByRole = useMemo(() => {
        const counts = rankBy(selectedRows, 'role')
        return counts.map(({ name }) => ({
            name,
            ...salaryStatistics(selectedRows.filter((row) => row.role === name)),
        })).sort((a, b) => (
            (b.average ?? -1) - (a.average ?? -1)
        ))
    }, [selectedRows])

    const focusField = field === ALL ? (fieldRanking[0]?.name || FIELD_DICTIONARY[0].name) : field
    const fieldRoles = FIELD_DICTIONARY.find((item) => item.name === focusField)?.roles || []
    const focusCandidates = selectedRows.filter((row) => row.field === focusField)
    const automaticRole = rankBy(focusCandidates, 'role')[0]?.name || fieldRoles[0]
    const focusRole = fieldRoles.includes(treeRole) ? treeRole : automaticRole
    const knowledgeRows = focusCandidates.filter((row) => row.role === focusRole)
    const knowledgeSkills = rankBy(knowledgeRows, 'skills')
    const knowledgeCets = rankBy(knowledgeRows, 'certifications')
    const salaryCoverage = selectedRows.length ? salary.count / selectedRows.length * 100 : 0
    const variation = changeRate(selectedRows.length, priorRows.length)
    const absentDate = CAREER_POSTINGS_DEMO.filter((row) => row.posted_at === null).length
    const qLabel = CAREER_QUARTERS.find((item) => item.id === quarterId)?.label || quarterId

    const selectField = (value) => {
        setField(value)
        setRole(ALL)
        setTreeRole(ALL)
    }

    const resetFilters = () => {
        setQuarterId(CAREER_QUARTERS[CAREER_QUARTERS.length - 1].id)
        setField(ALL)
        setRole(ALL)
        setTreeRole(ALL)
    }

    return (
        <div className="career-insights-v2">
            <div className="career-ci-intro">
                <div>
                    <span className="career-ci-intro-kicker">KEYWORD-BASED JOB MARKET ANALYSIS</span>
                    <h3>IT 채용시장 키워드 분석</h3>
                    <p>어떤 분야와 직무의 채용이 늘고, 기업은 어떤 기술·자격증·경험을 요구할까요?</p>
                </div>
                <span className="career-ci-demo-label">DEMO · 가상 데이터</span>
            </div>

            <p className="career-ci-warning" role="note">
                이 대시보드의 공고 수·급여·순위는 모두 화면 개발용 가상 데이터이며 실제 채용시장 통계가 아닙니다.
                현재는 등록일 기준 완료 분기인 2026년 3분기까지의 데모만 제공합니다.
            </p>

            <div className="career-ci-filters">
                <div className="career-ci-filters-heading">
                    <strong>분기별 분석 조건</strong>
                    <button type="button" onClick={resetFilters}>필터 초기화</button>
                </div>
                <div className="career-ci-filter-grid">
                    <label>
                        분석 분기
                        <select value={quarterId} onChange={(event) => setQuarterId(event.target.value)}>
                            {CAREER_QUARTERS.map((item) => (
                                <option key={item.id} value={item.id}>{item.label}</option>
                            ))}
                        </select>
                    </label>
                    <label>
                        분야 (대분류)
                        <select value={field} onChange={(event) => selectField(event.target.value)}>
                            <option value={ALL}>전체 분야</option>
                            {FIELD_DICTIONARY.map((item) => (
                                <option key={item.name} value={item.name}>{item.name}</option>
                            ))}
                        </select>
                    </label>
                    <label>
                        직무 (소분류)
                        <select value={role} onChange={(event) => setRole(event.target.value)}>
                            <option value={ALL}>전체 직무</option>
                            {roles.map((item) => <option value={item} key={item}>{item}</option>)}
                        </select>
                    </label>
                </div>
                <p className="career-ci-filter-note">{qLabel} · {field === ALL ? '전체 분야' : field} · {role === ALL ? '전체 직무' : role}</p>
            </div>

            <div className="career-ci-kpis" aria-label="주요 채용 지표">
                <div className="career-ci-kpi">
                    <span>해당 분기 등록 공고 수</span>
                    <strong>{number(selectedRows.length)}<small>건</small></strong>
                    <p>등록일 기준 해당 분기</p>
                </div>
                <div className="career-ci-kpi">
                    <span>전 분기 대비</span>
                    <strong className={variation === null ? '' : variation >= 0 ? 'positive' : 'negative'}>{formatRate(variation)}</strong>
                    <p>이전 분기 {previousQuarter ? number(priorRows.length) + '건' : '없음'}</p>
                </div>
                <div className="career-ci-kpi">
                    <span>평균 연봉</span>
                    <strong>{formatSalary(salary.average)}</strong>
                    <p>급여 공개 공고 {number(salary.count)}건만 산정</p>
                </div>
                <div className="career-ci-kpi">
                    <span>급여 정보 공개율</span>
                    <strong>{percent(salaryCoverage)}</strong>
                    <p>연봉 비교 가능한 공고 비율</p>
                </div>
            </div>

            <div className="career-ci-grid">
                <section className="career-ci-panel">
                    <SectionTitle eyebrow="01 / FIELDS" title="분야별 채용 수요" description="공고 수 기준으로 분야별 수요를 비교합니다." />
                    <Ranking items={fieldDemand} onSelect={selectField} selected={field} />
                </section>
                <section className="career-ci-panel">
                    <SectionTitle eyebrow="02 / ROLES" title="인기 직무 TOP 10" description="분야를 선택하면 해당 분야의 직무만 표시됩니다." />
                    <Ranking items={roleDemand} limit={10} onSelect={setRole} selected={role} />
                </section>
                <section className="career-ci-panel wide">
                    <SectionTitle
                        eyebrow="03 / DEMAND"
                        title="분기별 채용 수요 변화"
                        description="등록일이 확인되는 공고만 집계합니다. 하단 분기를 눌러 비교해 보세요."
                        extra={<span className="career-ci-mini-badge">전 분기 증감 {formatRate(variation)}</span>}
                    />
                    <QuarterTrend data={trend} currentQuarter={quarterId} onSelectQuarter={setQuarterId} />
                </section>
                <section className="career-ci-panel">
                    <SectionTitle eyebrow="04 / CERTIFICATIONS" title="자격증 언급 순위" description="같은 공고에서 동일 자격증은 1회만 집계합니다." />
                    <Ranking items={certRanking} limit={10} />
                </section>
                <section className="career-ci-panel">
                    <SectionTitle eyebrow="05 / PREFERENCES" title="우대사항 키워드 순위" description="사전에 등록된 표현을 표준 키워드로 묶어 집계합니다." />
                    <Ranking items={preferenceRanking} limit={10} />
                </section>
                <section className="career-ci-panel wide">
                    <SectionTitle
                        eyebrow="06 / KNOWLEDGE TREE"
                        title="직무별 자격요건 · 지식트리"
                        description="분야 → 직무 → 자격요건 기술 키워드를 탐색합니다. 기술 순위는 자격요건 원문만 사용합니다."
                    />
                    <div className="career-ci-tree">
                        <div className="career-ci-tree-nav">
                            <span className="career-ci-tree-caption">분야</span>
                            <strong>{focusField}</strong>
                            <span className="career-ci-tree-caption">직무 선택</span>
                            {fieldRoles.map((item) => (
                                <button
                                    type="button"
                                    key={item}
                                    className={focusRole === item ? 'active' : ''}
                                    onClick={() => setTreeRole(item)}
                                    aria-pressed={focusRole === item}
                                >
                                    {item}
                                </button>
                            ))}
                        </div>
                        <div className="career-ci-tree-detail">
                            <div className="career-ci-tree-breadcrumb">{focusField} <span>›</span> {focusRole}</div>
                            <h4>요구 기술 스택</h4>
                            <p>{focusRole} 관련 공고 {number(knowledgeRows.length)}건의 자격요건 원문 기준</p>
                            <Ranking items={knowledgeSkills} limit={8} />
                            <h4 className="career-ci-tree-subtitle">함께 언급된 자격증</h4>
                            {knowledgeCets.length ? (
                                <div className="career-ci-keyword-chips">
                                    {knowledgeCets.slice(0, 6).map((item) => (
                                        <span key={item.name}>{item.name} <b>{item.count}</b></span>
                                    ))}
                                </div>
                            ) : <p className="career-ci-muted">언급된 자격증이 없습니다.</p>}
                        </div>
                    </div>
                </section>
                <section className="career-ci-panel wide">
                    <SectionTitle eyebrow="07 / SALARY" title="직무별 평균 연봉 비교" description="공개된 연봉 하한·상한의 중간값을 공고별로 산정한 후 평균을 계산합니다." />
                    <SalaryRanking items={salaryByRole} />
                    <p className="career-ci-smallprint">급여 미공개 공고는 평균에서 제외되며, 공개된 공고만의 평균이므로 전체 직무의 실제 평균 연봉으로 해석할 수 없습니다.</p>
                </section>
            </div>

            <div className="career-ci-data-footer">
                <div>
                    <strong>키워드 사전 기반 분석</strong>
                    <p>
                        분야 {FIELD_DICTIONARY.length}개 · 직무 {ROLE_DICTIONARY.length}개 · 기술 {KEYWORD_DICTIONARY.skill.length}개 ·
                        자격증 {KEYWORD_DICTIONARY.certification.length}개 · 우대사항 {KEYWORD_DICTIONARY.preference.length}개
                    </p>
                </div>
                <div>
                    <strong>데이터 품질 원칙</strong>
                    <p>원문에서 추출되지 않은 키워드·급여는 추측하지 않습니다. 등록일 미기재 가상 공고 {number(absentDate)}건은 분기별 통계에서 제외합니다.</p>
                </div>
            </div>
        </div>
    )
}
