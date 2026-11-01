import { useEffect, useState } from 'react'
import { apiRequest } from '../../services/apiClient'
import '../../styles/adminUsage.css'

// 서버에 저장된 초 단위를 화면용 시간/분으로 변환합니다.
function formatDuration(seconds) {
  const minutes = Math.round(Number(seconds || 0) / 60)

  if (minutes < 60) return `${minutes.toLocaleString()}분`

  const hours = Math.floor(minutes / 60)
  const remain = minutes % 60

  return `${hours.toLocaleString()}시간 ${remain}분`
}

/** 관리자 전용 이용 시간 및 게시판 방문 통계 화면입니다. */
export default function AdminUsagePanel() {
  const [days, setDays] = useState(7)
  const [page, setPage] = useState(1)
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    const controller = new AbortController()

    const loadUsage = async () => {
      setLoading(true)
      setError('')

      try {
        const result = await apiRequest(
          `/admin/usage?days=${days}&page=${page}`,
          {
            signal: controller.signal,
            credentials: 'include',
          },
        )

        if (!controller.signal.aborted) setData(result)
      } catch (cause) {
        if (!controller.signal.aborted && cause.name !== 'AbortError') {
          setData(null)
          setError(cause.message)
        }
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
    }

    loadUsage()

    return () => controller.abort()
  }, [days, page])

  const changeDays = (value) => {
    if (days === value) return
    setPage(1)
    setDays(value)
  }

  const maxSeconds = Math.max(
    1,
    ...(data?.daily || []).map((item) => Number(item.seconds)),
  )
  const maxVisits = Math.max(
    1,
    ...(data?.top_boards || []).map((item) => Number(item.visits)),
  )

  return (
    <div className="admin-usage">
      <div className="admin-section-title">
        <h2>📈 이용 통계</h2>
        <span>실제 활동 시간 기준 · 한국 시간</span>
      </div>

      {error && (
        <p className="admin-alert" role="alert">
          {error}
        </p>
      )}

      {loading ? (
        <p className="admin-empty">이용 통계를 불러오는 중입니다.</p>
      ) : !data ? (
        <p className="admin-empty">이용 통계를 불러올 수 없습니다.</p>
      ) : (
        <>
          {/* 기간 선택과 무관한 전체 누적 통계 */}
          <section className="admin-usage-overall" aria-label="전체 누적 통계">
            <h3>전체 이용 현황</h3>

            <div className="admin-usage-stats">
              <article className="admin-usage-stat">
                <span>전체 누적 이용 시간</span>
                <strong>{formatDuration(data.total_seconds)}</strong>
                <small>통계 수집 시작일부터 현재까지 합산</small>
              </article>

              <article className="admin-usage-stat">
                <span>전체 기간 1일 평균 이용 시간</span>
                <strong>{formatDuration(data.all_time_daily_average_seconds)}</strong>
                <small>
                  최초 활동 기록일부터 {data.all_time_days}일 기준
                  (활동이 없는 날 포함)
                </small>
              </article>
            </div>
          </section>

          {/* 선택한 7일 또는 30일에만 적용되는 통계 */}
          <div className="admin-usage-period">
            <p>기간별 이용 현황을 확인할 수 있습니다.</p>

            <div className="admin-usage-buttons" aria-label="통계 조회 기간">
              {[7, 30].map((value) => (
                <button
                  key={value}
                  type="button"
                  className={days === value ? 'active' : ''}
                  aria-pressed={days === value}
                  onClick={() => changeDays(value)}
                >
                  최근 {value}일
                </button>
              ))}
            </div>
          </div>

          <div className="admin-usage-stats">
            <article className="admin-usage-stat">
              <span>최근 {days}일 하루 평균</span>
              <strong>{formatDuration(data.daily_average_seconds)}</strong>
              <small>활동이 없는 날짜도 평균에 포함</small>
            </article>

            <article className="admin-usage-stat">
              <span>1인당 활동일 평균</span>
              <strong>{formatDuration(data.per_active_user_day_seconds)}</strong>
              <small>회원이 실제로 활동한 날만 계산</small>
            </article>

            <article className="admin-usage-stat">
              <span>기간 내 총 이용 시간</span>
              <strong>{formatDuration(data.period_seconds)}</strong>
              <small>최근 {days}일 동안 누적된 시간</small>
            </article>

            <article className="admin-usage-stat">
              <span>오늘 활동 회원</span>
              <strong>{Number(data.today_users).toLocaleString()}명</strong>
              <small>최근 {days}일 활동 회원 {data.period_users}명</small>
            </article>
          </div>

          {/* 날짜별 이용 시간 그래프 */}
          <section className="admin-usage-box">
            <h3>일별 이용 시간</h3>

            <div className="admin-usage-chart" role="list" aria-label="일별 이용 시간">
              {data.daily.map((item) => (
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

          {/* 가장 많이 방문한 게시판 */}
          <section className="admin-usage-box">
            <div className="admin-usage-box-heading">
              <h3>많이 방문한 게시판 TOP 10</h3>
              <span>최근 {days}일 · 방문 횟수 기준</span>
            </div>

            {data.top_boards.length === 0 ? (
              <p className="admin-empty">
                아직 기록된 게시판 방문이 없습니다.
              </p>
            ) : (
              <div className="admin-usage-chart" role="list" aria-label="게시판 방문 순위">
                {data.top_boards.map((item, index) => (
                  <div className="admin-usage-board-row" key={item.board_key} role="listitem">
                    <span className="admin-usage-board-name">
                      <b>{index + 1}.</b> {item.name}
                    </span>

                    <div className="admin-usage-bar-track">
                      <div
                        className="admin-usage-bar"
                        style={{ width: `${(Number(item.visits) / maxVisits) * 100}%` }}
                      />
                    </div>

                    <span className="admin-usage-bar-label">
                      {Number(item.visits).toLocaleString()}회
                    </span>
                  </div>
                ))}
              </div>
            )}

            <p className="admin-usage-note">
              게시판을 선택해 진입한 횟수를 집계합니다.
              게시글 조회수나 실제 체류 시간 순위와는 다릅니다.
            </p>
          </section>

          {/* 회원별 이용 시간 및 10명 단위 페이지 */}
          <section className="admin-usage-box">
            <div className="admin-usage-box-heading">
              <h3>회원별 이용 시간 (최근 {days}일)</h3>
              <span>총 {data.members_total}명 · 10명씩 보기</span>
            </div>

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
                  {data.members.map((member) => (
                    <tr key={member.member_id}>
                      <td>{member.nickname} (#{member.member_id})</td>
                      <td>{formatDuration(member.seconds)}</td>
                      <td>{member.active_days}일</td>
                      <td>
                        {formatDuration(
                          member.active_days
                            ? member.seconds / member.active_days
                            : 0,
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {data.members.length === 0 && (
              <p className="admin-empty">아직 기록된 이용 시간이 없습니다.</p>
            )}

            <div className="admin-usage-pagination" aria-label="회원 목록 페이지 이동">
              <button
                type="button"
                disabled={data.members_page <= 1}
                onClick={() => setPage(data.members_page - 1)}
              >
                이전
              </button>

              <span>
                {data.members_page} / {data.members_total_pages} 페이지
              </span>

              <button
                type="button"
                disabled={data.members_page >= data.members_total_pages}
                onClick={() => setPage(data.members_page + 1)}
              >
                다음
              </button>
            </div>

            <p className="admin-usage-note">
              활성 탭에서 기록한 추정 시간입니다.
              통계는 활동 기록 기능 설치 후부터 누적됩니다.
            </p>
          </section>
        </>
      )}
    </div>
  )
}
