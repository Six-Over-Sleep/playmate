import { useEffect, useMemo } from 'react'

function getSkillId(skill) {
  return Number(skill?.skill_id ?? skill?.id ?? skill)
}

function getSkillName(skill) {
  return (
    skill?.name ??
    skill?.skill_name ??
    skill?.label ??
    String(skill?.skill_id ?? skill?.id ?? skill ?? '')
  )
}

// useMeetupApplication 훅이 상태·검증·제출을 담당하고,
// 이 컴포넌트는 프로젝트 신청 화면과 이벤트 연결만 담당함.
export default function MeetupApplicationModal({
  meetup,
  application,
}) {
  const {
    open = false,
    step = 1,
    form,
    error = '',
    result = null,
    busy = false,

    closeModal,
    toggleSkill,
    setLeaderVolunteer,
    changeDirectInput,
    goNext,
    goBack,
    submit,
  } = application || {}

  const requiredSkills = useMemo(
    () =>
      Array.isArray(meetup?.required_skills)
        ? meetup.required_skills
        : [],
    [meetup],
  )

  const selectedSkillIds = form?.selectedSkillIds ?? []
  const leaderVolunteer = Boolean(form?.leaderVolunteer)
  const directInput = form?.directInput ?? {
    skills: '',
    education: '',
    certificates: '',
    experience: '',
    awards: '',
    portfolio_url: '',
  }

  const selectedSkills = useMemo(
    () =>
      requiredSkills.filter((skill) =>
        selectedSkillIds.includes(getSkillId(skill)),
      ),
    [requiredSkills, selectedSkillIds],
  )

  // ESC 닫기와 배경 스크롤 방지는 화면 컴포넌트 책임으로 유지함.
  useEffect(() => {
    if (!open) {
      return undefined
    }

    const previousOverflow = document.body.style.overflow

    const handleKeyDown = (event) => {
      if (event.key === 'Escape' && !busy) {
        closeModal?.()
      }
    }

    document.body.style.overflow = 'hidden'
    window.addEventListener('keydown', handleKeyDown)

    return () => {
      document.body.style.overflow = previousOverflow
      window.removeEventListener('keydown', handleKeyDown)
    }
  }, [open, busy, closeModal])

  if (!open || !form) {
    return null
  }

  const applicationStatus = String(
    result?.application_status ?? '',
  ).toUpperCase()

  const hasCompletedResult = ['ACCEPTED', 'WAITING'].includes(
    applicationStatus,
  )

  const resultTitle =
    applicationStatus === 'ACCEPTED'
      ? '참여가 확정되었습니다.'
      : applicationStatus === 'WAITING'
        ? '대기 신청이 접수되었습니다.'
        : ''

  const resultDescription =
    applicationStatus === 'ACCEPTED'
      ? '프로젝트 확정 참여자로 등록되었습니다. 최신 참여 구성은 상세 화면에서 다시 확인할 수 있어요.'
      : applicationStatus === 'WAITING'
        ? '정상적으로 접수된 상태입니다. 빈자리와 필수 기술 구성을 서버가 다시 확인해 승격 여부를 결정합니다.'
        : ''

  return (
    <div
      className="meetup-application-overlay"
      role="presentation"
      onMouseDown={(event) => {
        if (
          event.target === event.currentTarget &&
          !busy
        ) {
          closeModal?.()
        }
      }}
    >
      <section
        className="meetup-application-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="meetup-application-title"
      >
        <header className="meetup-application-header">
          <div>
            <span className="meetup-application-eyebrow">
              프로젝트 참여 신청
            </span>

            <h2 id="meetup-application-title">
              {meetup?.title || '프로젝트'}
            </h2>
          </div>

          <button
            type="button"
            className="meetup-application-close"
            onClick={closeModal}
            disabled={busy}
            aria-label="신청 창 닫기"
          >
            ×
          </button>
        </header>

        {!hasCompletedResult && (
          <div
            className="meetup-application-steps"
            aria-label="신청 단계"
          >
          {[
            [1, '담당 기술'],
            [2, '신청 정보'],
            [3, '최종 확인'],
          ].map(([number, label]) => (
            <div
              key={number}
              className={[
                'meetup-application-step',
                step === number ? 'active' : '',
                step > number ? 'done' : '',
              ]
                .filter(Boolean)
                .join(' ')}
            >
              <span>{number}</span>
              <strong>{label}</strong>
            </div>
          ))}
          </div>
        )}

        <div className="meetup-application-body">
          {hasCompletedResult ? (
            <div className="meetup-application-result-view">
              <div
                className={[
                  'meetup-application-result-icon',
                  applicationStatus === 'WAITING' ? 'waiting' : 'accepted',
                ].join(' ')}
                aria-hidden="true"
              >
                {applicationStatus === 'WAITING' ? '⌛' : '✓'}
              </div>

              <h3>{resultTitle}</h3>
              <p>{resultDescription}</p>

              {result?.message && (
                <div className="meetup-application-server-message">
                  {result.message}
                </div>
              )}

              {result?.reason_code && (
                <span className="meetup-application-reason-code">
                  {result.reason_code}
                </span>
              )}
            </div>
          ) : (
            <>
          {step === 1 && (
            <div className="meetup-application-section">
              <div className="meetup-application-section-heading">
                <h3>담당할 필수 기술을 선택해주세요.</h3>

                <p>
                  한 사람이 여러 기술을 맡을 수 있어요. 신청 확정·대기는
                  서버가 현재 인원과 기술 구성을 다시 확인해 결정합니다.
                </p>
              </div>

              {requiredSkills.length > 0 ? (
                <div className="meetup-application-skill-list">
                  {requiredSkills.map((skill) => {
                    const skillId = getSkillId(skill)
                    const selected =
                      selectedSkillIds.includes(skillId)

                    return (
                      <button
                        key={skillId}
                        type="button"
                        className={[
                          'meetup-application-skill',
                          selected ? 'active' : '',
                        ]
                          .filter(Boolean)
                          .join(' ')}
                        aria-pressed={selected}
                        onClick={() =>
                          toggleSkill?.(skillId)
                        }
                        disabled={busy}
                      >
                        <span>{getSkillName(skill)}</span>

                        <small>
                          {skill?.confirmed_member_count != null
                            ? `현재 담당 ${skill.confirmed_member_count}명`
                            : '담당 가능'}
                        </small>
                      </button>
                    )
                  })}
                </div>
              ) : (
                <div className="meetup-application-empty">
                  프로젝트 필수 기술 정보를 불러오지 못했어요.
                </div>
              )}

              {String(meetup?.creator_type ?? '').toUpperCase() ===
              'ADMIN' ? (
                <div className="meetup-application-policy">
                  관리자 생성 프로젝트는 팀장 희망 여부와 관계없이 모집
                  마감 시점의 확정 참여자 중 신청 순서가 가장 빠른 사람을
                  팀장으로 선정합니다.
                </div>
              ) : (
                <label className="meetup-application-leader">
                  <input
                    type="checkbox"
                    checked={leaderVolunteer}
                    onChange={(event) =>
                      setLeaderVolunteer?.(
                        event.target.checked,
                      )
                    }
                    disabled={busy}
                  />

                  <span>
                    <strong>
                      프로젝트 팀장을 맡을 수 있어요
                    </strong>

                    <small>
                      모집 마감 시 확정 참여자 중 팀장 희망자를 우선하고,
                      같은 조건에서는 신청 순서가 빠른 사람을 팀장으로
                      선정합니다.
                    </small>
                  </span>
                </label>
              )}
            </div>
          )}

          {step === 2 && (
            <div className="meetup-application-section">
              <div className="meetup-application-section-heading">
                <h3>관련 경험을 자유롭게 입력해주세요.</h3>

                <p>
                  모두 선택 입력이에요. 직접 입력한 내용은 이번 프로젝트
                  신청서에만 저장됩니다.
                </p>
              </div>

              <div className="meetup-career-disabled">
                <div>
                  <strong>
                    마이페이지 커리어 불러오기
                  </strong>
                  <span>
                    다음 연동 단계에서 사용할 예정이에요.
                  </span>
                </div>

                <button
                  type="button"
                  disabled
                >
                  불러오기 준비 중
                </button>
              </div>

              <div className="meetup-application-form-grid">
                <label className="meetup-application-field full">
                  <span>추가 보유 기술</span>

                  <input
                    name="skills"
                    value={directInput.skills}
                    onChange={changeDirectInput}
                    placeholder="예) TypeScript, FastAPI, Docker"
                    disabled={busy}
                  />

                  <small>
                    여러 개면 쉼표로 구분해주세요.
                  </small>
                </label>

                <label className="meetup-application-field">
                  <span>관련 전공·교육</span>

                  <textarea
                    name="education"
                    value={directInput.education}
                    onChange={changeDirectInput}
                    placeholder="관련 전공이나 교육 수강 내용을 입력해주세요."
                    rows="4"
                    disabled={busy}
                  />
                </label>

                <label className="meetup-application-field">
                  <span>자격증</span>

                  <textarea
                    name="certificates"
                    value={directInput.certificates}
                    onChange={changeDirectInput}
                    placeholder="관련 자격증이 있다면 입력해주세요."
                    rows="4"
                    disabled={busy}
                  />
                </label>

                <label className="meetup-application-field">
                  <span>관련 경험·역할</span>

                  <textarea
                    name="experience"
                    value={directInput.experience}
                    onChange={changeDirectInput}
                    placeholder="프로젝트 경험이나 맡았던 역할을 입력해주세요."
                    rows="4"
                    disabled={busy}
                  />
                </label>

                <label className="meetup-application-field">
                  <span>수상 내역</span>

                  <textarea
                    name="awards"
                    value={directInput.awards}
                    onChange={changeDirectInput}
                    placeholder="관련 수상 내역이 있다면 입력해주세요."
                    rows="4"
                    disabled={busy}
                  />
                </label>

                <label className="meetup-application-field full">
                  <span>포트폴리오 링크</span>

                  <input
                    type="url"
                    name="portfolio_url"
                    value={directInput.portfolio_url}
                    onChange={changeDirectInput}
                    placeholder="https://..."
                    disabled={busy}
                  />
                </label>
              </div>
            </div>
          )}

          {step === 3 && (
            <div className="meetup-application-section">
              <div className="meetup-application-section-heading">
                <h3>신청 내용을 확인해주세요.</h3>

                <p>
                  제출 후 서버 결과에 따라 참여 확정 또는 대기 상태로
                  접수됩니다.
                </p>
              </div>

              <div className="meetup-application-review">
                <div className="meetup-application-review-item">
                  <span>담당 기술</span>

                  <div className="meetup-application-review-chips">
                    {selectedSkills.map((skill) => (
                      <strong key={getSkillId(skill)}>
                        {getSkillName(skill)}
                      </strong>
                    ))}
                  </div>
                </div>

                <div className="meetup-application-review-item">
                  <span>팀장 선정</span>

                  <strong>
                    {String(meetup?.creator_type ?? '').toUpperCase() ===
                    'ADMIN'
                      ? '신청 순서 기준 자동 선정'
                      : leaderVolunteer
                        ? '팀장 역할 가능'
                        : '희망하지 않음'}
                  </strong>
                </div>

                <div className="meetup-application-review-item full">
                  <span>직접 입력 정보</span>

                  <dl className="meetup-application-review-list">
                    <div>
                      <dt>추가 기술</dt>
                      <dd>
                        {directInput.skills.trim() ||
                          '미입력'}
                      </dd>
                    </div>

                    <div>
                      <dt>전공·교육</dt>
                      <dd>
                        {directInput.education.trim() ||
                          '미입력'}
                      </dd>
                    </div>

                    <div>
                      <dt>자격증</dt>
                      <dd>
                        {directInput.certificates.trim() ||
                          '미입력'}
                      </dd>
                    </div>

                    <div>
                      <dt>경험·역할</dt>
                      <dd>
                        {directInput.experience.trim() ||
                          '미입력'}
                      </dd>
                    </div>

                    <div>
                      <dt>수상</dt>
                      <dd>
                        {directInput.awards.trim() ||
                          '미입력'}
                      </dd>
                    </div>

                    <div>
                      <dt>포트폴리오</dt>
                      <dd>
                        {directInput.portfolio_url.trim() ||
                          '미입력'}
                      </dd>
                    </div>
                  </dl>
                </div>
              </div>

              <div className="meetup-application-policy">
                모임 시작 후 중도이탈이 누적 3회 이상이면 이후 모든 종류의
                모임에 새로 신청할 수 없습니다. 시작 전 신청 취소는
                집계하지 않으며, 제한 전에 접수된 유효 신청은 유지됩니다.
              </div>
            </div>
          )}

            </>
          )}

          {error && !hasCompletedResult && (
            <div
              className="meetup-application-error"
              role="alert"
            >
              {error}
            </div>
          )}
        </div>

        <footer className="meetup-application-footer">
          {hasCompletedResult ? (
            <button
              type="button"
              className="primary"
              onClick={closeModal}
            >
              확인
            </button>
          ) : (
            <>
              <button
                type="button"
                className="secondary"
                disabled={busy}
                onClick={() => {
                  if (step === 1) {
                    closeModal?.()
                    return
                  }

                  goBack?.()
                }}
              >
                {step === 1 ? '취소' : '이전'}
              </button>

          {step < 3 ? (
            <button
              type="button"
              className="primary"
              disabled={
                busy ||
                (step === 1 &&
                  requiredSkills.length === 0)
              }
              onClick={goNext}
            >
              {step === 1
                ? '다음'
                : '신청 내용 확인'}
            </button>
          ) : (
            <button
              type="button"
              className="primary"
              disabled={busy}
              onClick={submit}
            >
              {busy ? '신청 중...' : '신청하기'}
            </button>
          )}
            </>
          )}
        </footer>
      </section>
    </div>
  )
}
