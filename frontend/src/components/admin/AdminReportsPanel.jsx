import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { adminApi } from '../../services/adminApi'
import '../../styles/adminReports.css'

const REASONS = {
  SPAM: '광고·도배',
  ABUSE: '욕설·괴롭힘',
  HATE: '혐오 표현',
  PRIVACY: '개인정보 노출',
  OTHER: '기타',
}

function timestamp(value) {
  if (!value) return '-'
  const date = new Date(value)
  return Number.isNaN(date.getTime())
    ? '-'
    : date.toLocaleString('ko-KR', { dateStyle: 'medium', timeStyle: 'short' })
}

/** 관리자 전용 신고 접수 게시글 목록. 일반 게시글은 이 화면에 나타나지 않습니다. */
export default function AdminReportsPanel() {
  const navigate = useNavigate()
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(true)
  const [busyPostId, setBusyPostId] = useState(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('all')

  const loadReports = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const results = await adminApi.reportedPosts()
      setRows(Array.isArray(results) ? results : [])
    } catch (err) {
      setRows([])
      setError(err.message || '신고 목록을 불러오지 못했습니다.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { loadReports() }, [loadReports])

  const filtered = useMemo(() => rows.filter((post) => {
    const matchesStatus = status === 'all' ||
      (status === 'hidden' ? post.post_status === 'HIDDEN' : post.post_status !== 'HIDDEN')
    const needle = search.trim().toLocaleLowerCase()
    const matchesText = !needle ||
      `${post.title || ''} ${post.board_name || ''} ${post.author_name || ''}`
        .toLocaleLowerCase().includes(needle)
    return matchesStatus && matchesText
  }), [rows, search, status])

  async function changeVisibility(post) {
    if (busyPostId != null) return
    const hidden = post.post_status !== 'HIDDEN'
    const verb = hidden ? '숨김' : '복구'
    if (!window.confirm(`‘${post.title}’ 게시글을 ${verb} 처리하시겠습니까?`)) return
    setBusyPostId(post.post_id)
    setError('')
    setNotice('')
    try {
      await adminApi.setVisibility(post.post_id, hidden)
      setNotice(`게시글을 ${verb} 처리했습니다.`)
      await loadReports()
    } catch (err) {
      setError(err.message || `${verb} 처리에 실패했습니다.`)
    } finally {
      setBusyPostId(null)
    }
  }

  return (
    <div className="admin-reports-panel">
      <div className="admin-section-title">
        <h2>신고 관리</h2>
        <span>신고가 접수된 게시글만 표시합니다.</span>
      </div>

      <div className="admin-reports-summary">
        <div><span>신고 접수 게시글</span><strong>{rows.length}</strong></div>
        <div><span>자동·수동 숨김</span><strong>{rows.filter((p) => p.post_status === 'HIDDEN').length}</strong></div>
        <div><span>누적 신고 건수</span><strong>{rows.reduce((sum, p) => sum + Number(p.report_count || 0), 0)}</strong></div>
      </div>

      <div className="admin-reports-toolbar">
        <input
          type="search"
          aria-label="신고 게시글 검색"
          placeholder="제목 · 게시판 · 작성자 검색"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <select aria-label="게시글 상태 필터" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="all">전체 상태</option>
          <option value="visible">공개</option>
          <option value="hidden">숨김</option>
        </select>
        <button type="button" onClick={loadReports} disabled={loading || busyPostId != null}>
          새로고침
        </button>
      </div>

      {error && <p className="admin-alert" role="alert">{error}</p>}
      {notice && <p className="admin-success" role="status">{notice}</p>}

      {loading ? <p className="admin-empty">신고 내역을 불러오는 중…</p>
        : filtered.length === 0 ? (
          <p className="admin-empty">
            {rows.length === 0 ? '접수된 게시글 신고가 없습니다.' : '조건에 맞는 신고 게시글이 없습니다.'}
          </p>
        ) : (
          <div className="admin-reports-list">
            {filtered.map((post) => (
              <article className="admin-report-card" key={post.post_id}>
                <div className="admin-report-card-head">
                  <div className="admin-report-title">
                    <h3>{post.title}</h3>
                    <p>{post.board_name} · 작성자 {post.author_name} · {timestamp(post.created_at)}</p>
                  </div>
                  <div className="admin-report-badges">
                    <span className="admin-report-count">신고 {post.report_count}건</span>
                    <span className={`admin-badge${post.post_status === 'HIDDEN' ? ' hidden' : ''}`}>
                      {post.post_status === 'HIDDEN' ? '숨김' : '공개'}
                    </span>
                  </div>
                </div>

                <div className="admin-report-history">
                  <h4>접수된 신고 사유</h4>
                  {post.reports.map((report) => (
                    <div className="admin-report-reason" key={report.report_id}>
                      <div className="admin-report-reason-meta">
                        <span className="admin-report-reason-tag">{REASONS[report.reason] || report.reason}</span>
                        <span>{report.reporter_name} · {timestamp(report.created_at)}</span>
                      </div>
                      {report.details && <p>{report.details}</p>}
                    </div>
                  ))}
                </div>

                <div className="admin-row-actions admin-report-actions">
                  {post.post_status !== 'HIDDEN' && (
                    <button type="button" disabled={busyPostId != null}
                      onClick={() => navigate(`/board/${post.board_id}/posts/${post.post_id}`)}>
                      게시글 보기
                    </button>
                  )}
                  <button
                    type="button"
                    className={post.post_status === 'HIDDEN' ? '' : 'danger'}
                    disabled={busyPostId != null}
                    onClick={() => changeVisibility(post)}
                  >
                    {busyPostId === post.post_id ? '처리 중…' : post.post_status === 'HIDDEN' ? '게시글 복구' : '게시글 숨김'}
                  </button>
                </div>
              </article>
            ))}
          </div>
        )}
      {rows.length === 200 && (
        <p className="admin-reports-limit">최근 신고가 접수된 게시글 200개까지만 조회합니다.</p>
      )}
    </div>
  )
}
