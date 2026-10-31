import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { adminApi } from '../../services/adminApi'
import AdminUsagePanel from '../../components/admin/AdminUsagePanel'
import '../../styles/admin.css'

const TABS = [
  { key: 'notices', label: '공지사항 관리', icon: '📢' },
  { key: 'posts', label: '게시글 관리', icon: '📝' },
  { key: 'members', label: '회원 조회', icon: '👥' },
  { key: 'usage', label: '이용 통계', icon: '📈' },
]

function date(value) {
  if (!value) return '-'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? '-' : parsed.toLocaleDateString('ko-KR')
}

export default function AdminPage() {
  const navigate = useNavigate()
  const [tab, setTab] = useState('notices')
  const [stats, setStats] = useState(null)
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [forbidden, setForbidden] = useState(false)
  const [search, setSearch] = useState('')
  const [appliedSearch, setAppliedSearch] = useState('')
  const [editing, setEditing] = useState(null)
  const [title, setTitle] = useState('')
  const [body, setBody] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [summary, records] = await Promise.all([
        adminApi.dashboard(),
        tab === 'notices' ? adminApi.notices()
          : tab === 'posts' ? adminApi.posts(appliedSearch)
          : tab === 'usage' ? [] : adminApi.members(),
      ])
      setStats(summary)
      setRows(records)
      setForbidden(false)
    } catch (err) {
      setRows([])
      if (err.status === 403 || err.status === 401) {
        setForbidden(true)
      }
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [tab, appliedSearch])

  useEffect(() => { load() }, [load])

  const changeTab = (next) => {
    setTab(next)
    setError('')
    setMessage('')
    setEditing(null)
    setTitle('')
    setBody('')
  }

  const writeNotice = async (event) => {
    event.preventDefault()
    if (!title.trim() || !body.trim() || busy) return
    setBusy(true)
    setError('')
    try {
      const data = { title: title.trim(), body: body.trim() }
      if (editing) await adminApi.updateNotice(editing.id, data)
      else await adminApi.createNotice(data)
      setMessage(editing ? '공지사항을 수정했습니다.' : '공지사항을 등록했습니다.')
      setEditing(null)
      setTitle('')
      setBody('')
      await load()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const removeNotice = async (item) => {
    if (busy || !window.confirm(`‘${item.title}’ 공지를 삭제할까요?`)) return
    setBusy(true)
    setError('')
    try {
      await adminApi.deleteNotice(item.id)
      setMessage('공지사항을 삭제했습니다.')
      if (editing?.id === item.id) {
        setEditing(null)
        setTitle('')
        setBody('')
      }
      await load()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const toggleVisibility = async (item) => {
    const hidden = !item.hidden
    if (busy || !window.confirm(`이 게시글을 ${hidden ? '숨김' : '공개'} 처리할까요?`)) return
    setBusy(true)
    setError('')
    try {
      await adminApi.setVisibility(item.id, hidden)
      setMessage(`게시글을 ${hidden ? '숨김' : '공개'} 처리했습니다.`)
      await load()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  if (forbidden) {
    return (
      <main className="admin-denied">
        <h1>접근 권한이 없습니다.</h1>
        <p>관리자 계정으로 로그인해야 사용할 수 있습니다.</p>
        <button onClick={() => navigate('/board')}>게시판으로 돌아가기</button>
      </main>
    )
  }

  return (
    <main className="admin-shell">
      <div className="admin-heading">
        <div>
          <span className="admin-eyebrow">PLAYMATE ADMIN</span>
          <h1>관리자 센터</h1>
          <p>운영에 필요한 공지사항과 게시글을 관리합니다.</p>
        </div>
        <button className="admin-reload" onClick={load} disabled={busy || loading}>새로고침</button>
      </div>

      <section className="admin-stats" aria-label="운영 현황">
        {[
          ['전체 회원', stats?.members],
          ['전체 게시글', stats?.posts],
          ['모임', stats?.recruits],
          ['공지사항', stats?.notices],
        ].map(([label, value]) => (
          <div className="admin-stat" key={label}>
            <span>{label}</span><strong>{value ?? '—'}</strong>
          </div>
        ))}
      </section>

      <div className="admin-layout">
        <aside className="admin-side" aria-label="관리자 메뉴">
          {TABS.map((item) => (
            <button key={item.key} className={tab === item.key ? 'active' : ''}
              onClick={() => changeTab(item.key)} disabled={busy}>
              <span aria-hidden="true">{item.icon}</span> {item.label}
            </button>
          ))}
        </aside>
        <section className="admin-content">
          {error && <p className="admin-alert" role="alert">{error}</p>}
          {message && <p className="admin-success" role="status">{message}</p>}

          {tab === 'notices' && (
            <>
              <div className="admin-section-title">
                <h2>공지사항 관리</h2><span>관리자 전용 · 작성 / 수정 / 삭제</span>
              </div>
              <form className="admin-form" onSubmit={writeNotice}>
                <label htmlFor="admin-notice-title">제목</label>
                <input id="admin-notice-title" maxLength={100} required value={title}
                  onChange={(e) => setTitle(e.target.value)} placeholder="공지 제목을 입력해주세요." />
                <label htmlFor="admin-notice-body">내용</label>
                <textarea id="admin-notice-body" maxLength={20000} required rows={5} value={body}
                  onChange={(e) => setBody(e.target.value)} placeholder="안내 내용을 입력해주세요." />
                <div className="admin-form-actions">
                  {editing && (
                    <button type="button" className="admin-ghost" disabled={busy}
                      onClick={() => { setEditing(null); setTitle(''); setBody('') }}>수정 취소</button>
                  )}
                  <button type="submit" className="admin-primary" disabled={busy}>
                    {editing ? '공지 수정' : '공지 등록'}
                  </button>
                </div>
              </form>
              <h3>등록된 공지 ({rows.length})</h3>
              {loading ? <p className="admin-empty">불러오는 중…</p>
                : rows.length === 0 ? <p className="admin-empty">등록된 공지사항이 없습니다.</p>
                  : <div className="admin-list">
                    {rows.map(item => (
                      <article key={item.id} className="admin-row">
                        <div className="admin-row-main">
                          <strong>{item.title}</strong>
                          <small>{item.author_name} · {date(item.created_at)}</small>
                        </div>
                        <div className="admin-row-actions">
                          <button disabled={busy} onClick={() => {
                            setEditing(item); setTitle(item.title); setBody(item.body)
                            window.scrollTo({ top: 0, behavior: 'smooth' })
                          }}>수정</button>
                          <button disabled={busy} className="danger" onClick={() => removeNotice(item)}>삭제</button>
                        </div>
                      </article>
                    ))}
                  </div>}
            </>
          )}

          {tab === 'posts' && (
            <>
              <div className="admin-section-title">
                <h2>게시글 관리</h2><span>일반 게시판 게시글 숨김 / 복구</span>
              </div>
              <form className="admin-search" onSubmit={(event) => {
                event.preventDefault(); setAppliedSearch(search.trim())
                if (search.trim() === appliedSearch) load()
              }}>
                <input value={search} maxLength={100} onChange={e => setSearch(e.target.value)} placeholder="게시글 제목 검색" />
                <button type="submit" disabled={busy}>검색</button>
              </form>
              {loading ? <p className="admin-empty">불러오는 중…</p>
                : rows.length === 0 ? <p className="admin-empty">조회된 게시글이 없습니다.</p>
                  : <div className="admin-list">
                    {rows.map(item => (
                      <article key={item.id} className="admin-row">
                        <div className="admin-row-main">
                          <div className="admin-inline">
                            <strong>{item.title}</strong>
                            <span className={item.hidden ? 'admin-badge hidden' : 'admin-badge'}>
                              {item.hidden ? '숨김' : '공개'}
                            </span>
                          </div>
                          <small>{item.board_name} · {item.author_name} · {date(item.created_at)}</small>
                        </div>
                        <div className="admin-row-actions">
                          {!item.hidden && <button disabled={busy} onClick={() => navigate(`/board/${item.board_id}/posts/${item.id}`)}>보기</button>}
                          <button disabled={busy} className={item.hidden ? '' : 'danger'} onClick={() => toggleVisibility(item)}>
                            {item.hidden ? '복구' : '숨김'}
                          </button>
                        </div>
                      </article>
                    ))}
                  </div>}
            </>
          )}

          {tab === 'usage' && <AdminUsagePanel />}

          {tab === 'members' && (
            <>
              <div className="admin-section-title"><h2>회원 조회</h2><span>권한 변경은 지원하지 않습니다.</span></div>
              {loading ? <p className="admin-empty">불러오는 중…</p>
                : rows.length === 0 ? <p className="admin-empty">조회된 회원이 없습니다.</p>
                  : <div className="admin-table-wrap">
                    <table className="admin-table">
                      <thead><tr><th>ID</th><th>닉네임</th><th>권한</th><th>상태</th><th>가입일</th></tr></thead>
                      <tbody>{rows.map(item => (
                        <tr key={item.member_id}>
                          <td>{item.member_id}</td>
                          <td>{item.nickname || '-'}</td>
                          <td><span className="admin-badge">{item.role_code || 'USER'}</span></td>
                          <td>{item.member_status || '-'}</td>
                          <td>{date(item.created_at)}</td>
                        </tr>
                      ))}</tbody>
                    </table>
                  </div>}
            </>
          )}
        </section>
      </div>
    </main>
  )
}
