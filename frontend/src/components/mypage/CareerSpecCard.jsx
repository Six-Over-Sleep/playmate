import { useEffect, useState } from 'react'
import {
  getMyCareerSpecs,
  saveMyCareerSpecs,
  updateCareerSpecVisibility,
} from '../../services/mypageApi'
import '../../styles/CareerSpecCard.css'

const EMPTY_SPEC = {
  desired_job: '',
  education: '',
  certifications: '',
  language_scores: '',
  tech_stack: '',
  projects: '',
  introduction: '',
}

const FIELDS = [
  { name: 'desired_job', label: '희망 직무', placeholder: '예: 데이터 분석가', short: true },
  { name: 'education', label: '학력', placeholder: '예: 대학교 졸업', short: true },
  { name: 'certifications', label: '자격증', placeholder: '예: SQLD, ADsP' },
  { name: 'language_scores', label: '어학', placeholder: '예: TOEIC 850점' },
  { name: 'tech_stack', label: '기술 스택', placeholder: '예: Python, SQL, FastAPI' },
  { name: 'projects', label: '프로젝트 경험', placeholder: '진행한 프로젝트와 담당 역할' },
  { name: 'introduction', label: '자기소개', placeholder: '본인의 강점과 경험' },
]

export default function CareerSpecCard() {
  const [form, setForm] = useState(EMPTY_SPEC)
  const [spec, setSpec] = useState(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [changingVisibility, setChangingVisibility] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true

    getMyCareerSpecs()
      .then((data) => {
        if (!active || !data) return

        const values = {}
        for (const key of Object.keys(EMPTY_SPEC)) {
          values[key] = data[key] ?? ''
        }
        setForm(values)
        setSpec(data)
      })
      .catch((err) => {
        if (active) setError(`스펙 조회 실패: ${err.message}`)
      })
      .finally(() => {
        if (active) setLoading(false)
      })

    return () => { active = false }
  }, [])

  function changeField(event) {
    const { name, value } = event.target
    setForm((current) => ({ ...current, [name]: value }))
    setDirty(true)
    setMessage('')
    setError('')
  }

  async function save(event) {
    event.preventDefault()
    if (saving || changingVisibility) return

    setSaving(true)
    setMessage('')
    setError('')

    try {
      const saved = await saveMyCareerSpecs(form)
      setSpec(saved)
      setDirty(false)
      setMessage('취업 스펙이 저장되었습니다.')
    } catch (err) {
      setError(`저장 실패: ${err.message}`)
    } finally {
      setSaving(false)
    }
  }

  async function changeVisibility() {
    if (!spec || saving || changingVisibility) return

    if (dirty) {
      setError('수정한 내용을 먼저 저장한 뒤 공개 여부를 변경해 주세요.')
      return
    }

    const nextPublic = !spec.is_public
    if (nextPublic) {
      const confirmed = window.confirm(
        '입력한 취업 스펙이 다른 회원에게 공개됩니다. 개인정보나 민감한 내용이 없는지 확인했나요?',
      )
      if (!confirmed) return
    }

    setChangingVisibility(true)
    setMessage('')
    setError('')

    try {
      const result = await updateCareerSpecVisibility(nextPublic)
      setSpec((current) => ({ ...current, ...result }))

      if (result.xp_awarded === 50) {
        setMessage('스펙 최초 공개 완료! 종합 경험치 50XP를 획득했습니다.')
      } else {
        setMessage(result.is_public ? '스펙을 공개했습니다.' : '스펙을 비공개로 변경했습니다.')
      }
    } catch (err) {
      setError(`공개 설정 실패: ${err.message}`)
    } finally {
      setChangingVisibility(false)
    }
  }

  if (loading) return <section className="mypage-career-spec"><p>취업 스펙 불러오는 중...</p></section>

  const busy = saving || changingVisibility

  return (
    <section className="mypage-career-spec">
      <div className="mypage-career-spec-header">
        <h2>내 취업 스펙</h2>
        <strong>{spec?.is_public ? '공개 중' : '비공개'}</strong>
      </div>

      <p>희망 직무와 경력을 정리해 보세요. 저장만 하면 공개되지 않습니다.</p>
      <p>공개하면 다른 회원에게 보일 수 있으니 연락처, 주소 등 개인정보는 입력하지 마세요.</p>

      <form onSubmit={save}>
        {FIELDS.map((field) => (
          <label className="mypage-career-spec-field" key={field.name}>
            <span>{field.label}</span>
            {field.short ? (
              <input
                name={field.name}
                type="text"
                value={form[field.name]}
                onChange={changeField}
                maxLength={field.name === 'desired_job' ? 100 : 200}
                placeholder={field.placeholder}
                disabled={busy}
              />
            ) : (
              <textarea
                name={field.name}
                value={form[field.name]}
                onChange={changeField}
                rows={3}
                placeholder={field.placeholder}
                disabled={busy}
              />
            )}
          </label>
        ))}

        {error && <p role="alert" className="mypage-career-spec-error">{error}</p>}
        {message && <p role="status" className="mypage-career-spec-success">{message}</p>}

        <div className="mypage-career-spec-actions">
          <button type="submit" disabled={busy}>
            {saving ? '저장 중...' : '스펙 저장'}
          </button>
          <button type="button" disabled={busy || !spec} onClick={changeVisibility}>
            {changingVisibility
              ? '변경 중...'
              : spec?.is_public ? '비공개 전환' : '스펙 공개'}
          </button>
        </div>
      </form>
    </section>
  )
}
