import { useEffect, useMemo, useState } from 'react'
import { fetchInsight } from '../../services/careerInsightsApi'
import { INSIGHT_FIELDS, INSIGHT_SKILLS, QUARTER_OPTIONS } from '../../data/insightOptions'
import { DEMO_INSIGHTS } from '../../data/insightDemo'
import '../../styles/CareerInsights.css'
import '../../styles/CareerInsightsPatch.css'
import '../../styles/CareerInsightsStatic.css'

const EMPTY = { quarter:'', field:'', skill:'' }
const number = n => Number(n || 0).toLocaleString('ko-KR')
const labelQuarter = id => QUARTER_OPTIONS.find(item=>item.id===id)?.label || (id ? id.replace('-Q','년 ')+'분기' : '전체 분기')

function TopFive({ items = [], emptyText = '수집된 데이터가 없습니다.' }) {
  const ranked = items.slice(0,5), max = Math.max(1,...ranked.map(x=>x.count))
  if (!ranked.length) return <p className="career-ci-empty">{emptyText}</p>
  return <div className="career-ci-ranking">{ranked.map((item,index)=><div className="career-ci-rank" key={item.name}>
    <span className="career-ci-rank-no">{index+1}</span>
    <div className="career-ci-rank-body"><div className="career-ci-rank-text"><span>{item.name}</span><strong>{number(item.count)}건</strong></div>
      <span className="career-ci-bar-track"><span style={{width:`${item.count/max*100}%`}}/></span></div>
  </div>)}</div>
}

function Trend({ points = [] }) {
  const max=Math.max(1,...points.map(p=>p.count)), length=Math.max(1,points.length-1)
  const coordinates=points.map((p,i)=>({...p,x:48+i*620/length,y:169-(p.count/max)*125}))
  return <svg className="career-ci-trend-graph" viewBox="0 0 720 215" role="img" aria-label="분기별 채용공고 건수">
    {[44,106,169].map(y=><line key={y} x1="40" x2="685" y1={y} y2={y} className="career-ci-gridline" />)}
    <polyline points={coordinates.map(p=>`${p.x},${p.y}`).join(' ')} className="career-ci-chart-line" fill="none" />
    {coordinates.map(p=><g key={p.id}><circle className="career-ci-dot active" r="5.5" cx={p.x} cy={p.y}/>
      <text className="career-ci-point-label" x={p.x} y={p.y-13} textAnchor="middle">{number(p.count)}</text>
      <text className="career-ci-axis-label" x={p.x} y="199" textAnchor="middle">{p.id.replace('-Q',' ').slice(2)}</text></g>)}
  </svg>
}

function Panel({ index, title, description, children, wide = false }) {
  return <section className={`career-ci-panel ${wide?'wide':''}`}><div className="career-ci-section-title"><div>
    <span>{String(index).padStart(2,'0')} / INSIGHTS</span><h3>{title}</h3><p>{description}</p>
  </div></div>{children}</section>
}

export default function CareerInsights() {
  // Filter choices intentionally remain available with zero DB rows.
  const [draft,setDraft] = useState(EMPTY)
  const [applied,setApplied] = useState(EMPTY)
  const [data,setData] = useState(null)
  const [hasRealData,setHasRealData] = useState(false)
  const [loading,setLoading] = useState(false)
  const [apiNotice,setApiNotice] = useState('')

  useEffect(()=>{
    let active=true
    setLoading(true)
    fetchInsight('summary',applied)
      .then(result=>{
        if(!active)return
        if(Number(result?.total)>0){setData(result);setHasRealData(true);setApiNotice('')}
        else {setData(DEMO_INSIGHTS);setHasRealData(false);setApiNotice('DB에 수집 공고가 없어 시연용 데이터를 표시합니다.')}
      })
      .catch(()=>{
        if(!active)return
        setData(DEMO_INSIGHTS);setHasRealData(false)
        setApiNotice('통계 API에 연결되지 않아 시연용 데이터를 표시합니다.')
      })
      .finally(()=>{if(active)setLoading(false)})
    return ()=>{active=false}
  },[applied])
  // 선택 중인 필터는 즉시 표시하되, 실제 통계 조회는 '조회' 버튼에서만 적용한다.
  const formatFilters = filters => [
    labelQuarter(filters.quarter), filters.field || '전체 분야', filters.skill || '전체 기술 스택'
  ].join(' · ')
  const chosen=useMemo(()=>formatFilters(draft),[draft])
  const appliedLabel=useMemo(()=>formatFilters(applied),[applied])
  const hasPendingChanges = draft.quarter !== applied.quarter || draft.field !== applied.field || draft.skill !== applied.skill
  const reset=()=>{setDraft({...EMPTY});setApplied({...EMPTY})}
  const submit=()=>setApplied({...draft})
  const shown=data || DEMO_INSIGHTS
  const visibleTrend=hasRealData ? shown.trend : DEMO_INSIGHTS.trend.map((p,i)=>({...p,id:QUARTER_OPTIONS.slice().reverse()[i]?.id || p.id}))

  return <div className="career-insights-v2">
    <header className="career-ci-intro"><div><span className="career-ci-intro-kicker">KEYWORD-BASED JOB MARKET ANALYSIS</span>
      <h3>IT 채용시장 키워드 분석</h3><p>분기·전문분야·기술 스택별 채용공고 통계를 확인합니다.</p></div>
      <span className="career-ci-demo-label">{hasRealData?'DB 데이터':'DEMO · 가상 데이터'}</span></header>
    <p className="career-ci-warning" role="status">{hasRealData
      ? '실제 적재된 공고를 기준으로 한 시험 분석입니다. 전체 채용시장 대표 통계는 아닙니다.'
      : `${apiNotice || '대시보드 시연용 가상 데이터입니다.'} 아래의 모든 수치는 화면 구성 예시이며 실제 채용 통계가 아닙니다.`}</p>
    <div className="career-ci-filters"><div className="career-ci-filters-heading"><strong>채용 인사이트 분석 조건</strong><button type="button" onClick={reset}>필터 초기화</button></div>
      <div className="career-ci-filter-grid">
        <label>분기<select value={draft.quarter} onChange={e=>setDraft(p=>({...p,quarter:e.target.value}))}>
          <option value="">전체 분기</option>{QUARTER_OPTIONS.map(v=><option key={v.id} value={v.id}>{v.label}</option>)}
        </select></label>
        <label>분야<select value={draft.field} onChange={e=>setDraft(p=>({...p,field:e.target.value}))}>
          <option value="">전체 분야</option>{INSIGHT_FIELDS.map(v=><option key={v} value={v}>{v}</option>)}
        </select></label>
        <label>기술 스택<select value={draft.skill} onChange={e=>setDraft(p=>({...p,skill:e.target.value}))}>
          <option value="">전체 기술 스택</option>{INSIGHT_SKILLS.map(v=><option key={v} value={v}>{v}</option>)}
        </select></label>
      </div>
      <div className="career-ci-filter-action"><p className="career-ci-filter-note">선택한 조건: {chosen}{hasPendingChanges && <><br />현재 통계 적용 조건: {appliedLabel} (조회 버튼을 누르면 반영)</>}</p><button className="career-ci-search-button" type="button" disabled={loading} onClick={submit}>{loading?'조회 중…':'조회'}</button></div>
    </div>
    {!hasRealData && <p className="career-ci-demo-hint">※ 데모에서는 필터 선택·조회 UI만 테스트할 수 있어. 필터에 따른 실제 집계는 DB 연동 후 적용돼.</p>}
    <div className="career-ci-kpis">
      {[['수집 공고 건수',shown.count,'선택한 조건에 해당하는 공고'],['전체 적재 공고',shown.total,'중복 제거 후 DB 공고'],
        ['분야 정보 확인',shown.coverage?.field,'전문분야가 추출된 공고'],['기술 스택 확인',shown.coverage?.skill,'기술 키워드가 추출된 공고']].map(([label,count,sub])=><div className="career-ci-kpi" key={label}><span>{label}</span><strong>{number(count)}<small>건</small></strong><p>{sub}</p></div>)}
    </div>
    <div className="career-ci-grid">
      <Panel index={1} title="분야별 채용 수요 TOP 5" description="분야 태그 기준, 한 공고는 여러 분야에 속할 수 있습니다."><TopFive items={shown.fields}/></Panel>
      <Panel index={2} title="기술 스택별 수요 TOP 5" description="채용공고에서 언급된 기술 스택 기준입니다."><TopFive items={shown.skills}/></Panel>
      <Panel index={3} title="최근 4개 분기 채용공고 추이" description="현재 분기 및 이전 3개 분기, 첫 수집 시점 기준 집계" wide><Trend points={visibleTrend}/></Panel>
      <Panel index={4} title="자격증 언급 순위" description="실제 공고에 언급된 자격증만 집계합니다."><TopFive items={shown.certifications}/></Panel>
      <Panel index={5} title="우대사항 키워드 순위" description="우대사항 본문에서 추출한 단어 기준입니다."><TopFive items={shown.preferences}/></Panel>
    </div>
    <p className="career-ci-warning">{hasRealData ? shown.note : '시연 화면: 수집 공고 수·순위·분기별 추이는 모두 가상 데이터입니다.'}</p>
  </div>
}
