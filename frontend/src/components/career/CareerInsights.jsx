import { useEffect, useState } from 'react'
import { fetchInsight } from '../../services/careerInsightsApi'
import '../../styles/CareerInsights.css'

const EMPTY = { quarter: '', field: '', skill: '' }
const format = value => Number(value || 0).toLocaleString('ko-KR')
const quarterLabel = value => value.replace('-Q', '년 ') + '분기'

function Ranking({ title, items = [], emptyText = '확인된 정보가 없습니다.' }) {
  const top = items.slice(0, 5)
  const maximum = Math.max(1, ...top.map(item => item.count))
  return <section className="career-ci-panel">
    <div className="career-ci-section-title"><h3>{title}</h3><span>TOP 5</span></div>
    {top.length ? <div className="career-ci-ranking">{top.map((item, index) =>
      <div className="career-ci-rank" key={item.name}>
        <span className="career-ci-rank-no">{String(index + 1).padStart(2, '0')}</span>
        <div className="career-ci-rank-body"><div className="career-ci-rank-text"><span>{item.name}</span><strong>{format(item.count)}건</strong></div>
          <span className="career-ci-bar-track"><span style={{ width: `${item.count / maximum * 100}%` }} /></span></div>
      </div>)}</div> : <p className="career-ci-empty">{emptyText}</p>}
  </section>
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
    <header className="career-ci-intro"><div><span className="career-ci-intro-kicker">PLAYMATE CAREER INSIGHTS</span>
      <h3>채용 인사이트</h3><p>수집된 IT 채용공고의 직무, 분야, 기술 스택을 한눈에 살펴보세요.</p></div>
      <span className="career-ci-demo-label">실제 수집 데이터 <em>· JSON 미리보기</em></span></header>
    <div className="career-ci-source"><span>출처 <strong>사람인 공개 채용공고</strong></span><span>수집 <strong>{data?.collected_from?.slice(0, 10) || '확인 중'}</strong></span><span>고유 공고 <strong>{options ? `${format(options.total)}건` : '확인 중'}</strong></span></div>
    <form className="career-ci-filters" onSubmit={submit}>
      <div className="career-ci-filters-heading"><div><strong>분석 조건</strong><p>조건을 함께 선택하면 모두 충족하는 공고를 조회합니다.</p></div><button type="button" onClick={reset}>필터 초기화</button></div>
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
      <div className="career-ci-filter-action"><p className="career-ci-filter-note">수집 데이터에서 확인된 항목만 표시합니다.{pending && ' 변경한 조건은 조회 후 적용됩니다.'}</p>
        <button className="career-ci-search-button" disabled={loading} type="submit">{loading ? '조회 중…' : '조회'}</button></div>
    </form>
    {loading && <p className="career-ci-warning" role="status">수집 데이터를 불러오는 중입니다.</p>}
    {error && <div className="career-ci-warning" role="alert">{error} <button type="button" onClick={() => setRetry(value => value + 1)}>다시 시도</button></div>}
    {!loading && !error && data && <>
      {data.count === 0 && <p className="career-ci-warning" role="status">선택한 조건에 해당하는 공고가 없습니다. 조건을 바꾸거나 초기화해 주세요.</p>}
      <div className="career-ci-kpis">
        {[
          ['조회 공고', data.count, '선택한 조건에 해당하는 공고'],
          ['전체 수집 공고', data.total, '중복 제거한 전체 공고'],
          ['분야 확인 공고', coverage.field, '현재 결과에서 분야 확인'],
          ['기술 스택 확인 공고', coverage.skill, `확인율 ${percentage}% · 미확인 ${format(data.count - coverage.skill)}건`],
        ].map(([label, value, detail]) => <div className="career-ci-kpi" key={label}><span>{label}</span><strong>{format(value)}<small>건</small></strong><p>{detail}</p></div>)}
      </div>
      <div className="career-ci-grid">
        <Ranking title="직무별 공고" items={data.roles} />
        <Ranking title="분야 TOP 5" items={data.fields} />
        <Ranking title="기술 스택 TOP 5" items={data.skills} emptyText="현재 수집된 공고에서 확인된 기술 스택 정보가 부족합니다. 데이터가 추가되면 분석 결과를 확인할 수 있습니다." />
        <section className="career-ci-panel"><div className="career-ci-section-title"><h3>수집 분기별 현황</h3><span>COLLECTION</span></div>
          {data.trend.length ? data.trend.map(point => <p className="career-ci-quarter-row" key={point.id}><span>{quarterLabel(point.id)}</span><strong>{format(point.count)}건</strong></p>) : <p className="career-ci-empty">확인된 수집 분기가 없습니다.</p>}
          {data.trend.length < 2 && <p className="career-ci-muted">한 분기의 수집 데이터만 있어 추이는 표시하지 않습니다. 과거 미수집 기간은 0건으로 해석하지 않습니다.</p>}
        </section>
      </div>
      <div className="career-ci-availability"><strong>아직 확인되지 않은 정보</strong><p>자격증 {format(coverage.certification)}건 · 우대사항 {format(coverage.preference)}건 확인. 현재 표본에는 집계할 내용이 없어 순위를 표시하지 않습니다.</p></div>
      <p className="career-ci-footnote">이 결과는 수집 표본에 한정됩니다. 전체 채용시장 통계로 해석하지 마세요.</p>
    </>}
  </div>
}
