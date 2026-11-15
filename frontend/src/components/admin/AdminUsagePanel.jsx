import { useEffect, useState } from 'react'
import { apiRequest } from '../../services/apiClient'
import { downloadAdminUsageCsv } from '../../services/adminCsvApi'
import '../../styles/adminUsage.css'

// 서버는 이용 시간을 초 단위로 저장합니다. 화면에서는 분/시간으로 변환합니다.
function formatDuration(seconds) {
  const value = Number(seconds)
  const minutes = Number.isFinite(value)
    ? Math.max(0, Math.round(value / 60))
    : 0

  if (minutes < 60) return `${minutes.toLocaleString()}분`

  const hours = Math.floor(minutes / 60)
  const remain = minutes % 60

  return `${hours.toLocaleString()}시간 ${remain}분`
}

/** 관리자 전용 회원 활동 시간 통계를 표시합니다. */

function kstDate(offsetDays = 0) {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'Asia/Seoul',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(new Date())

  const number = (type) =>
    Number(parts.find((part) => part.type === type)?.value)

  const date = new Date(Date.UTC(
    number('year'),
    number('month') - 1,
    number('day') + offsetDays,
  ))

  return date.toISOString().slice(0, 10)
}

export default function AdminUsagePanel() {
  const [days, setDays] = useState(7)
  const [page, setPage] = useState(1)
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [downloadingKind, setDownloadingKind] = useState(null)
  const [exportStart, setExportStart] = useState(() => kstDate(-6))
  const [exportEnd, setExportEnd] = useState(() => kstDate(0))
  const [downloadError, setDownloadError] = useState('')

  useEffect(() => {
    const controller = new AbortController()

    const loadUsage = async () => {
      setLoading(true)
      setError('')
      setData(null)

      try {
        const result = await apiRequest(`/admin/usage?days=${days}&page=${page}`, {
          signal: controller.signal,
          credentials: 'include',
        })

        if (!controller.signal.aborted) {
          setData(result)
        }
      } catch (cause) {
        if (!controller.signal.aborted && cause.name !== 'AbortError') {
          setData(null)
          setError(cause.message || 'Request failed')
        }
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
    }

    loadUsage()

    return () => controller.abort()
  }, [days, page])


  const handleCsvDownload = async (kind) => {
    if (downloadingKind !== null) return

    setDownloadingKind(kind)
    setDownloadError('')

    try {
      await downloadAdminUsageCsv(days, kind, exportStart, exportEnd)
    } catch (cause) {
      setDownloadError(
        cause.message || 'CSV ????? ??????.',
      )
    } finally {
      setDownloadingKind(null)
    }
  }

  const maxSeconds = Math.max(
    1, ...(data?.daily || []).map((day) => Number(day.seconds) || 0),
  )
  const maxVisits = Math.max(
    1, ...(data?.top_boards || []).map((board) => Number(board.visits) || 0),
  )
  const totalPages = Math.max(1, Number(data?.members_total_pages) || 1)
  const currentPage = Math.min(
    totalPages, Math.max(1, Number(data?.members_page) || page),
  )

  return (
    <div className="admin-usage">
      <div className="admin-section-title">
        <h2>📈 이용 통계</h2>
        <span>실제 활동 시간 기준 · 한국 시간</span>
      </div>
      {/* 전체 기간 통계: 7일·30일 선택과 무관하게 고정 */}
      <section className="admin-usage-fixed-summary" aria-label="전체 이용 현황">
        <h3>전체 이용 현황</h3>

        <div className="admin-usage-fixed-grid">
          <article className="admin-usage-fixed-card">
            <span>전체 누적 이용 시간</span>
            <strong>
              {data?.total_seconds != null
                ? formatDuration(data.total_seconds)
                : '—'}
            </strong>
            <small>통계 수집을 시작한 이후의 누적 시간</small>
          </article>

          <article className="admin-usage-fixed-card">
            <span>전체 기간 하루 평균 이용 시간</span>
            <strong>
              {data?.all_time_daily_average_seconds != null
                ? formatDuration(data.all_time_daily_average_seconds)
                : data?.all_time_days > 0 && data?.total_seconds != null
                  ? formatDuration(data.total_seconds / data.all_time_days)
                  : '—'}
            </strong>
            <small>
              최초 활동 기록일부터 현재까지
              {data?.all_time_days ? ` · ${data.all_time_days}일 기준` : ''}
            </small>
          </article>
        
          {/* 전체 기간 기준 가장 많이 방문한 게시판 */}
          <article className="admin-usage-fixed-card">
            <span>전체 기간 최다 방문 게시판</span>
            <strong className="admin-usage-popular-name">
              {data?.most_visited_board?.name || '기록 없음'}
            </strong>
            <small>
              {data?.most_visited_board
                ? `${Number(data.most_visited_board.visits).toLocaleString()}회 방문 · 전체 누적 기준`
                : '게시판 방문 기록이 쌓이면 표시됩니다.'}
            </small>
          </article>
        </div>
      </section>


      <div className="admin-usage-period">
        <p>회원이 실제로 이용한 시간만 집계합니다.</p>
        <div className="admin-usage-buttons" aria-label="통계 조회 기간">
          {[7, 30].map((value) => (
            <button
              key={value}
              type="button"
              className={days === value ? 'active' : ''}
              aria-pressed={days === value}
              onClick={() => { setPage(1); setDays(value) }}
            >
              최근 {value}일
            </button>
          ))}
        </div>
      </div>


      <div className="admin-usage-export">
        <div className="admin-usage-export-range">
          <strong>{'CSV \ub2e4\uc6b4\ub85c\ub4dc \uae30\uac04'}</strong>
          <label>
            <span>{'\uc2dc\uc791\uc77c'}</span>
            <input
              type="date"
              aria-label="CSV start date"
              value={exportStart}
              max={kstDate(0)}
              disabled={downloadingKind !== null}
              onChange={(event) => setExportStart(event.target.value)}
            />
          </label>
          <label>
            <span>{'\uc885\ub8cc\uc77c'}</span>
            <input
              type="date"
              aria-label="CSV end date"
              value={exportEnd}
              max={kstDate(0)}
              disabled={downloadingKind !== null}
              onChange={(event) => setExportEnd(event.target.value)}
            />
          </label>
        </div>

        <div className="admin-usage-export-buttons">
          <button
            type="button"
            disabled={loading || downloadingKind !== null}
            onClick={() => handleCsvDownload('members')}
          >
            {downloadingKind === 'members'
              ? '\ub2e4\uc6b4\ub85c\ub4dc \uc911...'
              : '\ud68c\uc6d0\ubcc4 CSV'}
          </button>

          <button
            type="button"
            disabled={loading || downloadingKind !== null}
            onClick={() => handleCsvDownload('boards')}
          >
            {downloadingKind === 'boards'
              ? '\ub2e4\uc6b4\ub85c\ub4dc \uc911...'
              : '\uac8c\uc2dc\ud310\ubcc4 CSV'}
          </button>
        </div>
      </div>

      {downloadError && (
        <p className="admin-alert" role="alert">{downloadError}</p>
      )}

      {error && <p className="admin-alert" role="alert">{error}</p>}

      {loading ? (
        <p className="admin-empty">이용 통계를 불러오는 중입니다.</p>
      ) : !data ? (
        <p className="admin-empty">이용 통계를 불러올 수 없습니다.</p>
      ) : (
        <>
          <div className="admin-usage-stats">
            

            <article className="admin-usage-stat">
              <span>최근 {days}일 하루 평균</span>
              <strong>{formatDuration(data.daily_average_seconds)}</strong>
              <small>활동 없는 날짜도 평균에 포함</small>
            </article>

            <article className="admin-usage-stat">
              <span>1인당 활동일 평균</span>
              <strong>{formatDuration(data.per_active_user_day_seconds)}</strong>
              <small>회원이 활동한 날만 계산</small>
            </article>

            <article className="admin-usage-stat">
              <span>오늘 활동 회원</span>
              <strong>{data.today_users.toLocaleString()}명</strong>
              <small>최근 {days}일 활동 회원 {data.period_users}명</small>
            </article>
          </div>

          <section className="admin-usage-box">
            <h3>일별 이용 시간</h3>
            <div className="admin-usage-chart" role="list" aria-label="일별 이용 시간">
              {(data.daily || []).map((item) => (
                <div className="admin-usage-bar-row" key={item.date} role="listitem">
                  <span className="admin-usage-date">{item.date.slice(5)}</span>
                  <div className="admin-usage-bar-track">
                    <div
                      className="admin-usage-bar"
                      style={{ width: `${(item.seconds / maxSeconds) * 100}%` }}
                    />
                  </div>
                  <span className="admin-usage-bar-label">
                    {formatDuration(item.seconds)} · {item.users}명
                  </span>
                </div>
              ))}
            </div>
          </section>


          <section className="admin-usage-box">
            <div className="admin-usage-box-heading">
              <h3>{'게시판별 방문 TOP 10'}</h3>
              <span>{days} days</span>
            </div>

            {(data.top_boards || []).length === 0 ? (
              <p className="admin-empty">
                {'방문 기록이 없습니다.'}
              </p>
            ) : (
              <div className="admin-usage-chart" role="list">
                {data.top_boards.map((board, index) => (
                  <div
                    className="admin-usage-board-row"
                    key={board.board_key}
                    role="listitem"
                  >
                    <span className="admin-usage-board-name">
                      <b>{index + 1}.</b> {board.name}
                    </span>
                    <div className="admin-usage-bar-track">
                      <div
                        className="admin-usage-bar"
                        style={{
                          width: `${((Number(board.visits) || 0) / maxVisits) * 100}%`,
                        }}
                      />
                    </div>
                    <span className="admin-usage-bar-label">
                      {Number(board.visits || 0).toLocaleString()}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </section>

          <section className="admin-usage-box">
            <h3>회원별 이용 시간 (최근 {days}일)</h3>
            <div className="admin-table-wrap">
              <table className="admin-table">
                <thead>
                  <tr>
                    <th>회원</th>
                    <th>이용 시간</th>
                    <th>활동 일수</th>
                    <th>활동일 평균</th>
                  </tr>
                </thead>
                <tbody>
                  {(data.members || []).map((member) => (
                    <tr key={member.member_id}>
                      <td>{member.nickname} (#{member.member_id})</td>
                      <td>{formatDuration(member.seconds)}</td>
                      <td>{member.active_days}일</td>
                      <td>{formatDuration(member.active_days > 0 ? member.seconds / member.active_days : 0)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {(data.members || []).length === 0 && (
              <p className="admin-empty">아직 기록된 이용 시간이 없습니다.</p>
            )}

            <div
              className="admin-usage-pagination"
              aria-label={'회원 목록 페이지 이동'}
            >
              <button
                type="button"
                disabled={loading || currentPage <= 1}
                onClick={() => setPage(currentPage - 1)}
              >
                {'이전'}
              </button>

              <span aria-live="polite">
                {currentPage} / {totalPages}
                {' ('}{Number(data.members_total || 0).toLocaleString()}
                {'명)'}
              </span>

              <button
                type="button"
                disabled={loading || currentPage >= totalPages}
                onClick={() => setPage(currentPage + 1)}
              >
                {'다음'}
              </button>
            </div>

            <p className="admin-usage-note">
              {'회원별 이용 시간은 페이지당 10명씩 표시됩니다. 활동 시간은 추정치입니다.'}
            </p>
          </section>
        </>
      )}
    </div>
  )
}
