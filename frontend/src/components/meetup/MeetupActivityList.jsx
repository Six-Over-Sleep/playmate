import { useEffect, useState } from 'react'
import { meetupApi } from '../../services/meetupApi'

const TYPE_LABELS = {
  PARTICIPATION_PROOF: '참여 인증',
  WEEKLY_CHECK: '주간 인증',
  OUTPUT: '결과물',
  REVIEW: '후기',
}

function formatTime(value) {
  if (!value) return ''
  const date = new Date(value)
  return Number.isNaN(date.getTime())
    ? ''
    : date.toLocaleString('ko-KR', { dateStyle: 'medium', timeStyle: 'short' })
}

/**
 * 프로젝트·스터디의 활동 기록(인증·결과물·후기)을 최신순으로 보여줍니다.
 * reloadKey가 바뀌면(활동 등록 후 상세 갱신 등) 다시 조회합니다.
 */
export default function MeetupActivityList({ recruitId, members = [], reloadKey }) {
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!recruitId) return undefined
    const controller = new AbortController()
    setLoading(true)
    setError('')
    meetupApi.activities(recruitId, { signal: controller.signal })
      .then((result) => {
        const list = Array.isArray(result) ? [...result] : []
        list.sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)))
        setItems(list)
      })
      .catch((err) => {
        if (err.name !== 'AbortError') setError(err.message || '활동 기록을 불러오지 못했습니다.')
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })
    return () => controller.abort()
  }, [recruitId, reloadKey])

  const nameOf = (memberId) =>
    members.find((member) => member.member_id === memberId)?.display_name || `회원 #${memberId}`

  return (
    <section className="meetup-extra-section meetup-activity-list">
      <h2>활동 기록 ({items.length})</h2>
      {loading ? (
        <p>활동 기록을 불러오는 중...</p>
      ) : error ? (
        <p role="alert">{error}</p>
      ) : items.length === 0 ? (
        <p>아직 등록된 활동 기록이 없습니다.</p>
      ) : (
        <ul>
          {items.map((item) => (
            <li key={item.activity_id}>
              <strong>{item.title}</strong>
              <span>
                {' '}· {TYPE_LABELS[item.activity_type] || item.activity_type}
                {item.week ? ` ${item.week}주차` : ''}
                {item.submission_stage ? ` (${item.submission_stage === 'FINAL' ? '최종' : '중간'})` : ''}
                {' '}· {nameOf(item.author_member_id)} · {formatTime(item.created_at)}
              </span>
              <p>{item.body}</p>
              {item.links?.length > 0 && (
                <ul>
                  {item.links.map((link) => (
                    <li key={link}>
                      <a href={link} target="_blank" rel="noreferrer">{link}</a>
                    </li>
                  ))}
                </ul>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
