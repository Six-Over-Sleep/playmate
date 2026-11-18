import { useEffect, useState } from 'react'
import { fetchInsight } from '../../services/careerInsightsApi'

const EMPTY = { quarter: '', field: '', skill: '' }
const format = value => Number(value || 0).toLocaleString('ko-KR')
const quarterLabel = value => String(value || '').replace('-Q', '년 ') + '분기'

function RoleRanking({ items = [] }) {
  const top = items.slice(0, 5)
  const maximum = Math.max(1, ...top.map(item => Number(item.count) || 0))

  return <section className="career-ci-panel career-ci-featured-panel" aria-label="직무별 채용 공고 상위 순위">
    <div className="career-ci-section-title">
      <div><span className="career-ci-panel-eyebrow">JOB RANKING</span><h3>직무별 공고 TOP 5</h3>
        {top.length > 0 && <small className="career-ci-top-caption">최다 직무 · {top[0].name} ({format(top[0].count)}건)</small>}
      </div>
      <span>TOP 5</span>
    </div>
    {top.length ? <div className="career-ci-ranking career-ci-role-ranking">
      {top.map((item, index) => <div className="career-ci-rank" key={`${item.name}-${index}`}>
        <span className="career-ci-rank-no">{String(index + 1).padStart(2, '0')}</span>
        <div className="career-ci-rank-body">
          <div className="career-ci-rank-text">
            <span>{item.name}</span>
            <strong>{format(item.count)}건</strong>
          </div>
          <span className="career-ci-bar-track">
            <span style={{ width: `${Math.max(0, Number(item.count) || 0) / maximum * 100}%` }} />
          </span>
        </div>
      </div>)}
    </div> : <p className="career-ci-empty">선택한 조건에서 확인된 직무 정보가 없습니다.</p>}
  </section>
}

function FieldRanking({ items = [] }) {
  const top = items.slice(0, 5)
  return <section className="career-ci-panel career-ci-field-panel" aria-label="분야별 채용 공고 상위 순위">
    <div className="career-ci-section-title">
      <div><span className="career-ci-panel-eyebrow">FIELD RANKING</span><h3>분야 랭킹</h3>
        {top.length > 0 && <small className="career-ci-top-caption">최다 분야 · {top[0].name} ({format(top[0].count)}건)</small>}
      </div>
      <span>TOP 5</span>
    </div>
    {top.length ? <ol className="career-ci-field-list">
      {top.map((item, index) => <li key={`${item.name}-${index}`}>
        <span className="career-ci-field-rank">{String(index + 1).padStart(2, '0')}</span>
        <span className="career-ci-field-name">{item.name}</span>
        <strong>{format(item.count)}건</strong>
      </li>)}
    </ol> : <p className="career-ci-empty">선택한 조건에서 확인된 분야 정보가 없습니다.</p>}
  </section>
}

function SkillTags({ items = [] }) {
  const top = items.slice(0, 5)
  return <section className="career-ci-panel career-ci-skill-panel" aria-label="기술 스택 상위 순위">
    <div className="career-ci-section-title">
      <div><span className="career-ci-panel-eyebrow">TECH STACK</span><h3>기술 스택 TOP 5</h3>
        {top.length > 0 && <small className="career-ci-top-caption">최다 기술 · {top[0].name} ({format(top[0].count)}건)</small>}
      </div>
      <span>TOP 5</span>
    </div>
    {top.length ? <div className="career-ci-skill-tags">
      {top.map((item, index) => <span className="career-ci-skill-tag" key={`${item.name}-${index}`}>
        <span>{item.name}</span>
        <strong>{format(item.count)}건</strong>
      </span>)}
    </div> : <p className="career-ci-empty">현재 수집된 공고에서 확인된 기술 스택 정보가 부족합니다. 데이터가 추가되면 분석 결과를 확인할 수 있습니다.</p>}
    <p className="career-ci-skill-hint">선택한 조건에서 확인된 기술 스택만 표시합니다.</p>
  </section>
}

function OverviewStat({ label, count, detail, accent = false, percentage = null }) {
  return <div className={`career-ci-overview-stat${accent ? ' career-ci-overview-stat--accent' : ''}`}>
    <span className="career-ci-overview-label">{label}</span>
    <strong className="career-ci-overview-number">{format(count)}<small>건</small></strong>
    <p>{detail}{percentage !== null && <span className="career-ci-overview-percent">{percentage}%</span>}</p>
  </div>
}

export default function CareerInsights() {
  const [draft, setDraft] = useState(EMPTY)
  const [applied, setApplied] = useState(EMPTY)
  const [options, setOptions] = useState(null)
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setError('')
    Promise.all([
      fetchInsight('filters', {}, controller.signal),
      fetchInsight('summary', applied, controller.signal),
    ]).then(([choices, summary]) => {
      setOptions(choices)
      setData(summary)
    }).catch(err => {
      if (err.name !== 'AbortError') {
        setData(null)
        setError('수집 데이터 조회에 실패했습니다. 서버와 JSON 파일 상태를 확인해 주세요.')
      }
    }).finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [applied, retry])

  const reset = () => { setDraft({ ...EMPTY }); setApplied({ ...EMPTY }); setRetry(value => value + 1) }
  const submit = event => { event.preventDefault(); setApplied({ ...draft }); setRetry(value => value + 1) }
  const pending = Object.keys(EMPTY).some(key => draft[key] !== applied[key])
  const coverage = data?.coverage || {}
  const percentage = data?.count ? Math.round((coverage.skill || 0) / data.count * 100) : 0

  return <div className="career-insights-v2">
    <header className="career-ci-intro">
      <div>
        <span className="career-ci-intro-kicker">PLAYMATE CAREER INSIGHTS</span>
        <h3>채용 인사이트</h3>
        <p>수집된 IT 채용공고의 직무, 분야, 기술 스택을 한눈에 살펴보세요.</p>
      </div>
      <span className="career-ci-demo-label">실제 수집 데이터 <em>· JSON 미리보기</em></span>
    </header>
    <div className="career-ci-source">
      <span>출처 <strong>사람인 공개 채용공고</strong></span>
      <span>수집 <strong>{data?.collected_from?.slice(0, 10) || '확인 중'}</strong></span>
      <span>고유 공고 <strong>{options ? `${format(options.total)}건` : '확인 중'}</strong></span>
    </div>
    <form className="career-ci-filters" onSubmit={submit}>
      <div className="career-ci-filters-heading">
        <div><strong>분석 조건</strong><p>조건을 함께 선택하면 모두 충족하는 공고를 조회합니다.</p></div>
        <button type="button" onClick={reset}>필터 초기화</button>
      </div>
      <div className="career-ci-filter-grid">
        <label>수집 분기<select value={draft.quarter} onChange={e => setDraft(prev => ({ ...prev, quarter: e.target.value }))}>
          <option value="">전체 분기</option>{options?.quarters.map(item => <option key={item} value={item}>{quarterLabel(item)}</option>)}
        </select></label>
        <label>분야<select value={draft.field} onChange={e => setDraft(prev => ({ ...prev, field: e.target.value }))}>
          <option value="">전체 분야</option>{options?.fields.map(item => <option key={item} value={item}>{item}</option>)}
        </select></label>
        <label>기술 스택<select value={draft.skill} onChange={e => setDraft(prev => ({ ...prev, skill: e.target.value }))}>
          <option value="">전체 기술 스택</option>{options?.skills.map(item => <option key={item} value={item}>{item}</option>)}
        </select></label>
      </div>
      <div className="career-ci-filter-action">
        <p className="career-ci-filter-note">수집 데이터에서 확인된 항목만 표시합니다.{pending && ' 변경한 조건은 조회 후 적용됩니다.'}</p>
        <button className="career-ci-search-button" disabled={loading} type="submit">{loading ? '조회 중…' : '조회'}</button>
      </div>
    </form>

    {loading && <p className="career-ci-warning" role="status">수집 데이터를 불러오는 중입니다.</p>}
    {error && <div className="career-ci-warning" role="alert">{error} <button type="button" onClick={() => setRetry(value => value + 1)}>다시 시도</button></div>}
    {!loading && !error && data && <>
      {data.count === 0 && <p className="career-ci-warning" role="status">선택한 조건에 해당하는 공고가 없습니다. 조건을 바꾸거나 초기화해 주세요.</p>}

      <div className="career-ci-overview" aria-label="수집 및 조회 공고 현황">
        <OverviewStat label="전체 수집 공고" count={data.total} detail="수집한 전체 공고 기준" accent />
        <OverviewStat label="조회 공고" count={data.count} detail="현재 적용된 조회 조건 기준" accent />
        <OverviewStat label="분야 확인 공고" count={coverage.field} detail="조회 결과에서 분야 확인" />
        <OverviewStat label="기술 스택 확인 공고" count={coverage.skill} detail="조회 결과 중 확인 비율" percentage={percentage} />
      </div>

      <div className="career-ci-a-dashboard">
        <RoleRanking items={data.roles || []} />
        <div className="career-ci-a-secondary">
          <FieldRanking items={data.fields || []} />
          <div className="career-ci-side-stack">
            <SkillTags items={data.skills || []} />
            <section className="career-ci-quarter-summary" aria-label="수집 분기 현황">
              <div className="career-ci-quarter-head">
                <div><strong>수집 분기별 현황</strong><span>수집된 데이터 기준</span></div>
                <div className="career-ci-quarter-values">
                  {(data.trend || []).length ? data.trend.map(point => <span className="career-ci-quarter-item" key={point.id}>
                    {quarterLabel(point.id)} <strong>{format(point.count)}건</strong>
                  </span>) : <span>수집 분기 정보 없음</span>}
                </div>
              </div>
              {(data.trend || []).length < 2 && <p>한 분기의 수집 데이터만 있어 추이는 표시하지 않습니다. 과거 미수집 기간은 0건으로 해석하지 않습니다.</p>}
            </section>
          </div>
        </div>
      </div>

      <div className="career-ci-availability">
        <strong>아직 확인되지 않은 정보</strong>
        <p>자격증 {format(coverage.certification)}건 · 우대사항 {format(coverage.preference)}건 확인. 현재 표본에는 집계할 내용이 없어 순위를 표시하지 않습니다.</p>
      </div>
      <p className="career-ci-footnote">이 결과는 수집 표본에 한정됩니다. 전체 채용시장 통계로 해석하지 마세요.</p>
    </>}
  </div>
}
