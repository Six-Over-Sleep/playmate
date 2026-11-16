import { useEffect, useMemo, useState } from 'react'
import '../../styles/auth.css'
import logo from '../../assets/playmate-logo.png'
import { getAuthUrl } from '../../config/api'
import { apiRequest } from '../../services/apiClient'

export default function SignupPage({ onBack, onComplete }) {
  const [form, setForm] = useState({
    discordId: '',
    nickname: '',
    institutionId: '',
    programId: '',
    cohortId: '',
  })
  const [options, setOptions] = useState([])
  const [discordStatus, setDiscordStatus] = useState('checking')
  const [optionsStatus, setOptionsStatus] = useState('idle')
  const [optionsError, setOptionsError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    let cancelled = false
    async function checkDiscordSession() {
      try {
        const data = await apiRequest('/me', {
          urlBuilder: getAuthUrl,
          credentials: 'include',
        })
        if (cancelled) return
        if (!data.signup_required) {
          onComplete?.()
          return
        }
        setForm((prev) => ({
          ...prev,
          discordId: data.discord_user?.username || data.discord_user?.discord_id || '',
        }))
        setDiscordStatus('verified')
      } catch (error) {
        if (cancelled) return
        if (error.status !== 401) console.error(error)
        setDiscordStatus('idle')
      }
    }
    checkDiscordSession()
    return () => { cancelled = true }
  }, [onComplete])

  useEffect(() => {
    if (discordStatus !== 'verified') return
    let cancelled = false
    async function loadEducationOptions() {
      setOptionsStatus('loading')
      setOptionsError('')
      try {
        const data = await apiRequest('/education-options', {
          urlBuilder: getAuthUrl,
          credentials: 'include',
        })
        if (cancelled) return
        setOptions(Array.isArray(data.cohorts) ? data.cohorts : [])
        setOptionsStatus('ready')
      } catch (error) {
        if (cancelled) return
        setOptionsError(error.message || '교육과정 목록을 가져오지 못했습니다.')
        setOptionsStatus('error')
      }
    }
    loadEducationOptions()
    return () => { cancelled = true }
  }, [discordStatus])

  const institutions = useMemo(() =>
    Array.from(new Map(options.map((item) => [item.institution_id, {
      id: item.institution_id,
      name: item.institution_name,
    }])).values()), [options])

  const programs = useMemo(() =>
    Array.from(new Map(options
      .filter((item) => String(item.institution_id) === form.institutionId)
      .map((item) => [item.program_id, {
        id: item.program_id,
        name: item.program_name,
      }])).values()), [options, form.institutionId])

  const cohorts = useMemo(() => options.filter((item) =>
    String(item.institution_id) === form.institutionId &&
    String(item.program_id) === form.programId
  ), [options, form.institutionId, form.programId])

  const handleDiscordAuth = () => {
    window.location.href = getAuthUrl('/discord/login')
  }

  const handleSubmit = async (event) => {
    event.preventDefault()
    if (discordStatus !== 'verified') {
      alert('Discord 인증을 먼저 진행해주세요.')
      return
    }
    if (optionsStatus !== 'ready') {
      alert('교육과정 목록을 불러오는 중입니다.')
      return
    }
    const cohort = cohorts.find((item) => String(item.cohort_id) === form.cohortId)
    if (!form.nickname.trim() || !cohort) {
      alert('닉네임과 교육기관·과정·기수를 확인해주세요.')
      return
    }

    setSubmitting(true)
    try {
      await apiRequest('/signup', {
        urlBuilder: getAuthUrl,
        method: 'POST',
        credentials: 'include',
        body: JSON.stringify({
          nickname: form.nickname.trim(),
          cohort_id: cohort.cohort_id,
        }),
      })
      alert('회원가입이 완료되었습니다.')
      onComplete?.()
    } catch (error) {
      if (error.status === 409 && error.data?.detail === '이미 가입된 회원입니다.') {
        alert(error.data.detail)
        onComplete?.()
        return
      }
      console.error(error)
      alert(error.message || '서버와 통신할 수 없습니다.')
    } finally {
      setSubmitting(false)
    }
  }

  const isVerified = discordStatus === 'verified'
  const isChecking = discordStatus === 'checking'

  return (
    <div className="auth-page">
      <main className="signup-main">
        <section className="signup-card">
          <button type="button" className="signup-back-button" onClick={onBack}>
            ← 이전으로
          </button>

          <div className="signup-logo">
            <img src={logo} alt="" aria-hidden="true" />
          </div>

          <div className="signup-heading">
            <div>
              <h1>회원가입</h1>
              <p>교육기관·교육과정·기수를 선택하면 바로 가입할 수 있습니다.</p>
            </div>
          </div>

          <form className="signup-form" onSubmit={handleSubmit}>
            <div className="signup-field">
              <span>Discord ID <b>*</b></span>
              {!isVerified ? (
                <>
                  <button
                    type="button"
                    className="discord-auth-button"
                    onClick={handleDiscordAuth}
                    disabled={isChecking}
                  >
                    <span className="discord-auth-icon">◉</span>
                    <span>{isChecking ? 'Discord 인증 확인 중...' : 'Discord 인증하기'}</span>
                  </button>
                  <small>Discord 인증 후 계정 정보가 자동으로 입력됩니다.</small>
                </>
              ) : (
                <>
                  <div className="signup-disabled-input discord-verified">
                    <input type="text" value={form.discordId} readOnly />
                    <span className="signup-status-icon">✓</span>
                  </div>
                  <small className="discord-success">Discord 인증이 완료되었습니다.</small>
                </>
              )}
            </div>

            <label className="signup-field">
              <span>닉네임 <b>*</b></span>
              <input
                type="text"
                value={form.nickname}
                onChange={(event) => setForm((prev) => ({
                  ...prev, nickname: event.target.value,
                }))}
                placeholder="커뮤니티에서 사용할 닉네임"
                minLength={2}
                maxLength={20}
                required
              />
            </label>

            <label className="signup-field">
              <span>교육기관 <b>*</b></span>
              <select
                value={form.institutionId}
                onChange={(event) => setForm((prev) => ({
                  ...prev,
                  institutionId: event.target.value,
                  programId: '',
                  cohortId: '',
                }))}
                disabled={!isVerified || optionsStatus !== 'ready'}
                required
              >
                <option value="">교육기관을 선택해주세요</option>
                {institutions.map((item) => (
                  <option key={item.id} value={String(item.id)}>{item.name}</option>
                ))}
              </select>
            </label>

            <label className="signup-field">
              <span>교육 과정 <b>*</b></span>
              <select
                value={form.programId}
                onChange={(event) => setForm((prev) => ({
                  ...prev, programId: event.target.value, cohortId: '',
                }))}
                disabled={!form.institutionId}
                required
              >
                <option value="">교육 과정을 선택해주세요</option>
                {programs.map((item) => (
                  <option key={item.id} value={String(item.id)}>{item.name}</option>
                ))}
              </select>
            </label>

            <label className="signup-field">
              <span>기수 <b>*</b></span>
              <select
                value={form.cohortId}
                onChange={(event) => setForm((prev) => ({
                  ...prev, cohortId: event.target.value,
                }))}
                disabled={!form.programId}
                required
              >
                <option value="">기수를 선택해주세요</option>
                {cohorts.map((item) => (
                  <option key={item.cohort_id} value={String(item.cohort_id)}>
                    {item.cohort_no}기{item.campus_name ? ` · ${item.campus_name}` : ''}
                  </option>
                ))}
              </select>
              {optionsStatus === 'loading' && <small>교육과정 목록을 불러오는 중입니다.</small>}
              {optionsStatus === 'error' && <small role="alert">{optionsError}</small>}
              {optionsStatus === 'ready' && options.length === 0 && (
                <small>등록된 교육과정이 없습니다. 운영진에게 문의해주세요.</small>
              )}
            </label>

            <button
              type="submit"
              className="signup-submit-button"
              disabled={!isVerified || optionsStatus !== 'ready' || submitting || !form.cohortId}
            >
              {submitting ? '가입 중...' : '가입하기'}
            </button>
          </form>
        </section>
      </main>
    </div>
  )
}
