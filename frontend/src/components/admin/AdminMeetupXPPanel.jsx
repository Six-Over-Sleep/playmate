import { useCallback, useEffect, useState } from 'react'
import { adminApi } from '../../services/adminApi'

const REWARD_LABELS = {
  PARTICIPATION: '모임 참여 인증',
  STUDY_WEEKLY: '스터디 주간 인증',
  PROJECT_INTERIM: '프로젝트 중간 결과물',
  STUDY_COMPLETE: '스터디 완료',
  PROJECT_COMPLETE: '프로젝트 완료',
  REVIEW: '모임 후기',
  PROJECT_LEADER: '프로젝트 팀장',
}

const ACTIVITY_LABELS = {
  PARTICIPATION_PROOF: '참여 인증',
  WEEKLY_CHECK: '주간 인증',
  OUTPUT: '결과물',
  REVIEW: '후기',
}

// 활동 기록 종류별로 승인할 수 있는 보상. 최종 판단은 서버가 다시 검증합니다.
function rewardOptions(activity) {
  if (activity.activity_type === 'PARTICIPATION_PROOF') return ['PARTICIPATION']
  if (activity.activity_type === 'WEEKLY_CHECK') return ['STUDY_WEEKLY', 'PARTICIPATION', 'STUDY_COMPLETE']
  if (activity.activity_type === 'OUTPUT') {
    return activity.submission_stage === 'FINAL'
      ? ['PROJECT_COMPLETE', 'PROJECT_LEADER', 'PARTICIPATION']
      : ['PROJECT_INTERIM', 'PARTICIPATION']
  }
  if (activity.activity_type === 'REVIEW') return ['REVIEW']
  return []
}

function timestamp(value) {
  if (!value) return '-'
  const date = new Date(value)
  return Number.isNaN(date.getTime())
    ? '-'
    : date.toLocaleString('ko-KR', { dateStyle: 'medium', timeStyle: 'short' })
}

/** 관리자 전용 모임 활동 증빙 검토와 개인 XP 승인·회수 화면입니다. */
export default function AdminMeetupXPPanel() {
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(true)
  const [busyId, setBusyId] = useState(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [selected, setSelected] = useState({})

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const result = await adminApi.meetupXPActivities()
      setRows(Array.isArray(result) ? result : [])
    } catch (err) {
      setRows([])
      setError(err.message || '모임 활동 기록을 불러오지 못했습니다.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const rewardFor = (activity) => selected[activity.activity_id] || rewardOptions(activity)[0]

  async function approve(activity) {
    if (busyId != null) return
    const reward = rewardFor(activity)
    setBusyId(activity.activity_id)
    setError('')
    setNotice('')
    try {
      const result = await adminApi.approveMeetupXP(activity.recruit_id, {
        activity_id: activity.activity_id,
        member_id: activity.member_id,
        reward_type: reward,
        ...(reward === 'STUDY_WEEKLY' ? { week: activity.week } : {}),
      })
      setNotice(result?.awarded
        ? `${activity.nickname}님에게 ${REWARD_LABELS[reward]} ${result.earned_xp}XP를 지급했습니다.`
        : `이미 처리된 보상입니다. (${result?.reason === 'REVOKED' ? '회수됨' : '중복'})`)
    } catch (err) {
      setError(err.message || 'XP를 승인하지 못했습니다.')
    } finally {
      setBusyId(null)
    }
  }

  async function revoke(activity) {
    if (busyId != null) return
    const reward = rewardFor(activity)
    const reason = window.prompt(`${activity.nickname}님의 ${REWARD_LABELS[reward]} XP를 회수하는 사유를 입력해주세요.`)
    if (!reason || !reason.trim()) return
    setBusyId(activity.activity_id)
    setError('')
    setNotice('')
    try {
      const result = await adminApi.revokeMeetupXP(activity.recruit_id, {
        member_id: activity.member_id,
        reward_type: reward,
        reason: reason.trim(),
        ...(reward === 'STUDY_WEEKLY' ? { week: activity.week } : {}),
      })
      setNotice(result?.revoked
        ? `${activity.nickname}님의 ${REWARD_LABELS[reward]} XP ${Math.abs(result.xp_change)}XP를 회수했습니다.`
        : '이미 회수된 보상입니다.')
    } catch (err) {
      setError(err.message || 'XP를 회수하지 못했습니다.')
    } finally {
      setBusyId(null)
    }
  }

  return (
    <div className="admin-reports-panel">
      <div className="admin-section-title">
        <h2>모임 XP 검토</h2>
        <span>활동 증빙을 확인한 뒤 회원별 보상을 승인합니다. 지급량은 XP 정책을 따릅니다.</span>
      </div>

      {error && <p className="admin-alert" role="alert">{error}</p>}
      {notice && <p className="admin-success" role="status">{notice}</p>}

      {loading ? (
        <p className="admin-empty">불러오는 중…</p>
      ) : rows.length === 0 ? (
        <p className="admin-empty">검토할 모임 활동 기록이 없습니다.</p>
      ) : (
        <div className="admin-reports-list">
          {rows.map((activity) => {
            const options = rewardOptions(activity)
            const busy = busyId === activity.activity_id
            return (
              <article className="admin-report-card" key={activity.activity_id}>
                <div className="admin-report-card-head">
                  <div>
                    <h3 className="admin-report-title">{activity.recruit_title}</h3>
                    <p className="admin-report-reason-meta">
                      {activity.nickname} · {ACTIVITY_LABELS[activity.activity_type] || activity.activity_type}
                      {activity.week ? ` ${activity.week}주차` : ''}
                      {activity.submission_stage ? ` (${activity.submission_stage === 'FINAL' ? '최종' : '중간'})` : ''}
                      {' · '}{timestamp(activity.created_at)}
                    </p>
                  </div>
                </div>
                <p>{activity.body}</p>
                {activity.links?.length > 0 && (
                  <ul>
                    {activity.links.map((link) => (
                      <li key={link}><a href={link} target="_blank" rel="noreferrer">{link}</a></li>
                    ))}
                  </ul>
                )}
                <div className="admin-row-actions admin-report-actions">
                  <select
                    aria-label="승인할 보상"
                    value={rewardFor(activity) || ''}
                    disabled={busy || options.length === 0}
                    onChange={(event) => setSelected((current) => ({
                      ...current, [activity.activity_id]: event.target.value,
                    }))}
                  >
                    {options.map((reward) => (
                      <option key={reward} value={reward}>{REWARD_LABELS[reward]}</option>
                    ))}
                  </select>
                  <button type="button" onClick={() => approve(activity)} disabled={busy || options.length === 0}>
                    승인
                  </button>
                  <button type="button" onClick={() => revoke(activity)} disabled={busy || options.length === 0}>
                    회수
                  </button>
                </div>
              </article>
            )
          })}
        </div>
      )}
    </div>
  )
}
