import { MeetupNotice } from '../../components/meetup/MeetupFeedback'
import { useEffect, useState } from 'react'
import { meetupApi } from '../../services/meetupApi'
import { meetupErrorMessage } from '../../utils/meetupForm'
import { EDITOR_CATEGORY_OPTIONS, WEEKDAYS } from '../../utils/meetup'

import useMeetupEditor from '../../hooks/meetup/useMeetupEditor'

function getSkillId(skill) {
  return Number(skill?.skill_id ?? skill?.id ?? skill?.value)
}

function getSkillName(skill) {
  return (
    skill?.name ||
    skill?.skill_name ||
    skill?.label ||
    String(skill?.skill_id ?? skill?.id ?? '')
  )
}

// 모임 생성·수정 입력 화면
export default function MeetupEditorPage({
  meetup = null,
  initialCategory = 'study',
  isAdmin = false,
  busy,
  onBack,
  onSubmit,

}) {
  const today = new Date(Date.now() + 9 * 3600000).toISOString().slice(0, 10)
  const configurationLocked = Boolean(meetup) &&
    (meetup?.permissions?.can_edit_configuration ?? meetup?.can_edit_configuration) !== true
  const [skillOptions, setSkillOptions] = useState([])
  const [skillStatus, setSkillStatus] = useState('loading')
  const [skillAttempt, setSkillAttempt] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    setSkillStatus('loading')
    meetupApi.skills({ signal: controller.signal }).then((data) => {
      setSkillOptions(data)
      setSkillStatus(data.length ? '' : '등록된 기술이 없어요. 잠시 후 다시 시도해주세요.')
    }).catch((error) => {
      if (error.name !== 'AbortError') setSkillStatus(meetupErrorMessage(error, '기술 목록을 불러오지 못했어요.'))
    })
    return () => controller.abort()
  }, [skillAttempt])
  // 편집 훅의 폼 상태와 이벤트 연결
  const {
    form,
    formRef, fieldErrors, submitError, dismissSubmitError, isProgram, categoryChanged,
    isEdit,
    isGroupBuy,
    isProject,
    isStudy,

    placeResults,
    placeSearchStatus,

    mapContainerRef,

    change,
    changePrice,

    setRecruitMode,
    setCategory,
    setPlaceType,

    toggleRegularDay,
    toggleRequiredSkill,
    toggleCreatorSkill,

    searchPlace,
    selectPlace,

    submit,
  } = useMeetupEditor({
    meetup,
    initialCategory,
    onSubmit,
    isAdmin,
  })

  return (
    <main className="meetup-editor-page">
      <button
        className="meetup-back-button"
        onClick={onBack}
        type="button"
      >
        ← 돌아가기
      </button>

      <div className="meetup-editor-heading">
        <h1>{isEdit ? '모임 수정' : '모임 만들기'}</h1>
      </div>

      <form
        className="meetup-form-card"
        onSubmit={submit}
        ref={formRef}
        noValidate
      >
        {isEdit && isProgram && <p className="meetup-type-help">제목·소개·인원·전체 일정·필수 기술을 수정할 수 있어요. 다른 멤버가 신청한 뒤에는 인원·일정·기술 변경이 제한돼요.</p>}
        <MeetupNotice message={submitError} error onClose={dismissSubmitError} />
        {categoryChanged && (
          <p className="meetup-type-help">
            종류를 바꾸면 이전 종류의 기술 배정·커리큘럼·전용 입력 정보가 정리됩니다.
            새 종류에 필요한 정보를 입력해주세요. 댓글·좋아요·스크랩은 유지됩니다.
          </p>
        )}
        <fieldset disabled={busy} className="meetup-form-fields">
        <div className="meetup-form-section">
          <div className="meetup-field-title">
            모임 카테고리 <span>*</span>
          </div>

          <div className="meetup-category-buttons">
            {EDITOR_CATEGORY_OPTIONS.map((option) => (
              <button
                key={option.value}
                type="button"
                className={form.category === option.value ? 'active' : ''}
                onClick={() => setCategory(option.value)}
                disabled={configurationLocked}
                title={
                  configurationLocked
                    ? '다른 사람의 신청 이력이 없고 모집 마감 전일 때만 변경할 수 있어요.'
                    : undefined
                }
              >
                {option.label}
              </button>
            ))}
          </div>
        </div>

        <div className="meetup-form-section">
          <div className="meetup-field-title">
            모임 형태 <span>*</span>
          </div>

          <div className="meetup-segmented-control meetup-recruit-mode">
            <button
              type="button"
              className={
                !isGroupBuy && form.recruit_mode === 'regular' ? 'active' : ''
              }
              onClick={() => setRecruitMode('regular')}
              disabled={configurationLocked || isGroupBuy}
              title={
                configurationLocked ? '다른 사람의 신청 이력이 없고 모집 마감 전일 때만 변경할 수 있어요.' : undefined
              }
            >
              정기 모임
            </button>

            <button
              type="button"
              className={
                !isGroupBuy && form.recruit_mode === 'short' ? 'active' : ''
              }
              onClick={() => setRecruitMode('short')}
              disabled={configurationLocked || isGroupBuy}
              title={
                configurationLocked ? '다른 사람의 신청 이력이 없고 모집 마감 전일 때만 변경할 수 있어요.' : undefined
              }
            >
              단기 모임
            </button>
          </div>

          {!isGroupBuy && (
            <p className="meetup-type-help">
              {configurationLocked
                ? '다른 사람의 신청 이력이 없고 모집 마감 전일 때만 변경할 수 있어요.'
                : form.recruit_mode === 'regular'
                  ? '반복적으로 진행되는 모임이에요.'
                  : '특정 날짜에 진행되는 모임이에요.'}
            </p>
          )}
        </div>

        <div className="meetup-form-grid two">
          <label className="meetup-field">
            <span>
              모집 제목 <b>*</b>
            </span>

            <input
              name="title"
              aria-invalid={Boolean(fieldErrors.title)}
              aria-describedby={fieldErrors.title ? "error-title" : undefined}
              value={form.title}
              onChange={change}
              placeholder="예) 주말 요가 모임 같이 하실 분"
              required
            />
            {fieldErrors.title && <small className="meetup-field-error" id="error-title">{fieldErrors.title}</small>}
          </label>

          <label className="meetup-field">
            <span>
              모집 인원 <b>*</b>
            </span>

            <div className="meetup-capacity-input">
              <input
                type="number"
                name="capacity"
              aria-invalid={Boolean(fieldErrors.capacity)}
              aria-describedby={fieldErrors.capacity ? "error-capacity" : undefined}
                min={isProject || isStudy ? '2' : '1'}
                max={isProject || isStudy ? '5' : undefined}
                value={form.capacity}
                onChange={change}
                required
              />

              <em>명</em>
            </div>
            {fieldErrors.capacity && <small className="meetup-field-error" id="error-capacity">{fieldErrors.capacity}</small>}
          </label>
        </div>

        <label className="meetup-field">
          <span>
            모집 내용 <b>*</b>
          </span>

          <textarea
            name="body"
              aria-invalid={Boolean(fieldErrors.body)}
              aria-describedby={fieldErrors.body ? "error-body" : undefined}
            value={form.body}
            onChange={change}
            rows="4"
            placeholder="모임에 대해 자유롭게 소개해주세요."
            required
          />
            {fieldErrors.body && <small className="meetup-field-error" id="error-body">{fieldErrors.body}</small>}
        </label>

        <div className="meetup-form-grid two">
          <label className="meetup-field">
            <span>
              모집 마감 일시 <b>*</b>
            </span>

            <input
              type="datetime-local"
              min={!isEdit ? `${today}T00:00` : undefined}
              name="recruit_end"
              aria-invalid={Boolean(fieldErrors.recruit_end)}
              aria-describedby={fieldErrors.recruit_end ? "error-recruit_end" : undefined}
              title={isProgram ? "마감을 선택하면 시작 일시도 24시간 뒤로 함께 변경돼요." : undefined}
              value={form.recruit_end}
              onChange={change}
              required
            />
            {isProgram && <small className="meetup-type-help">마감을 선택하면 시작 일시도 24시간 뒤로 함께 변경돼요.</small>}
            {fieldErrors.recruit_end && <small className="meetup-field-error" id="error-recruit_end">{fieldErrors.recruit_end}</small>}
          </label>

          <div className="meetup-field">
            <span>
              진행 방식 <b>*</b>
            </span>

            <div className="meetup-segmented-control meetup-place-type">
              <button
                type="button"
                className={!form.is_online ? 'active' : ''}
                disabled={isEdit && isProgram && !categoryChanged}
                onClick={() => setPlaceType(false)}
              >
                오프라인
              </button>

              <button
                type="button"
                className={form.is_online ? 'active' : ''}
                disabled={isEdit && isProgram && !categoryChanged}
                onClick={() => setPlaceType(true)}
              >
                온라인
              </button>
            </div>
          </div>
        </div>

        {/* 오프라인 장소 검색과 지도 */}
        {!form.is_online && (
          <div className="meetup-field meetup-place-picker">
            <span>
              장소 <b>*</b>
            </span>

            <div className="meetup-place-search-row">
              <input
                name="place"
                aria-label="오프라인 모임 장소"
              disabled={isEdit && isProgram && !categoryChanged}
              aria-invalid={Boolean(fieldErrors.place)}
              aria-describedby={fieldErrors.place ? "error-place" : undefined}
                value={form.place}
                onChange={change}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') {
                    event.preventDefault()
                    searchPlace()
                  }
                }}
                placeholder="예) 강남역, 스터디룸 3호실"
                required
              />
            {fieldErrors.place && <small className="meetup-field-error" id="error-place">{fieldErrors.place}</small>}

              <button
                type="button"
                className="meetup-place-search-button"
                disabled={isEdit && isProgram && !categoryChanged}
                onClick={searchPlace}
              >
                장소 검색
              </button>
            </div>

            {placeSearchStatus && (
              <p className="meetup-place-search-status">{placeSearchStatus}</p>
            )}

            {placeResults.length > 0 && (
              <div className="meetup-place-results">
                {placeResults.map((place) => (
                  <button
                    key={place.id}
                    type="button"
                    className="meetup-place-result"
                    onClick={() => selectPlace(place)}
                  >
                    <strong>{place.place_name}</strong>

                    <span>
                      {place.road_address_name ||
                        place.address_name ||
                        '주소 정보 없음'}
                    </span>
                  </button>
                ))}
              </div>
            )}

            <div
              ref={mapContainerRef}
              className="meetup-kakao-map"
              aria-label="선택한 장소 지도"
            />

            {form.place_latitude !== '' && form.place_longitude !== '' && (
              <div className="meetup-selected-place">
                <span>선택한 장소</span>

                <strong>{form.place}</strong>
              </div>
            )}
          </div>
        )}

        {/* 정기 모임 시작일·요일·시간 입력 */}
        {!isGroupBuy && form.recruit_mode === 'regular' && (
          <div className="meetup-form-section regular-schedule-section">
            <div className="meetup-field-title">
              정기 일정 <span>*</span>
            </div>

            <div className="meetup-regular-inline">
              <div className="meetup-schedule-field">
              <input
                className="meetup-regular-date"
                type="date"
                min={!isEdit ? today : undefined}
                name="regular_start_date"
                aria-label="정기 모임 시작 날짜"
              aria-invalid={Boolean(fieldErrors.regular_start_date)}
              aria-describedby={fieldErrors.regular_start_date ? "error-regular_start_date" : undefined}
                value={form.regular_start_date}
                onChange={change}
                required
              />
            {fieldErrors.regular_start_date && <small className="meetup-field-error" id="error-regular_start_date">{fieldErrors.regular_start_date}</small>}
              </div>

              <div className="meetup-schedule-field">

              <div className="meetup-weekday-buttons" data-field="regular_days" aria-invalid={Boolean(fieldErrors.regular_days)} aria-describedby={fieldErrors.regular_days ? "error-regular_days" : undefined}>
                {WEEKDAYS.map((day) => (
                  <button
                    key={day}
                    type="button"
                    className={form.regular_days.includes(day) ? 'active' : ''}
                    disabled={configurationLocked && isProgram}
                    onClick={() => toggleRegularDay(day)}
                  >
                    {day}
                  </button>
                ))}
              </div>

              {fieldErrors.regular_days && <small id="error-regular_days" className="meetup-field-error">{fieldErrors.regular_days}</small>}
              </div>

              <div className="meetup-schedule-field">
              <input
                className="meetup-regular-time"
                type="time"
                name="regular_time"
                aria-label="정기 모임 시간"
              aria-invalid={Boolean(fieldErrors.regular_time)}
              aria-describedby={fieldErrors.regular_time ? "error-regular_time" : undefined}
                value={form.regular_time}
                onChange={change}
                required
              />
            {fieldErrors.regular_time && <small className="meetup-field-error" id="error-regular_time">{fieldErrors.regular_time}</small>}
              </div>
            </div>

            {(isProject || isStudy) && (
              <label className="meetup-field">
                <span>
                  전체 모임 종료 일시 <b>*</b>
                </span>

                <input
                  type="datetime-local"
              min={!isEdit ? `${today}T00:00` : undefined}
                  name="ends_at"
              aria-invalid={Boolean(fieldErrors.ends_at)}
              aria-describedby={fieldErrors.ends_at ? "error-ends_at" : undefined}
                  value={form.ends_at ?? ''}
                  onChange={change}
                  required
                />
            {fieldErrors.ends_at && <small className="meetup-field-error" id="error-ends_at">{fieldErrors.ends_at}</small>}

                <small className="meetup-type-help">
                  프로젝트·스터디는 반복 일정과 별도로 전체 운영 종료 시점을 저장해요.
                </small>
              </label>
            )}
          </div>
        )}

        {/* 단기 모임 시작·종료 일시 입력 */}
        {!isGroupBuy && form.recruit_mode === 'short' && (
          <div className="meetup-form-grid two">
            <label className="meetup-field">
              <span>
                모임 시작 일시 <b>*</b>
              </span>

              <input
                type="datetime-local"
              min={!isEdit ? `${today}T00:00` : undefined}
                name="meeting_start"
              aria-invalid={Boolean(fieldErrors.meeting_start)}
              aria-describedby={fieldErrors.meeting_start ? "error-meeting_start" : undefined}
                value={form.meeting_start}
                onChange={change}
                required
              />
            {fieldErrors.meeting_start && <small className="meetup-field-error" id="error-meeting_start">{fieldErrors.meeting_start}</small>}
            </label>

            <label className="meetup-field">
              <span>
                모임 종료 일시 <b>*</b>
              </span>

              <input
                type="datetime-local"
              min={!isEdit ? `${today}T00:00` : undefined}
                name="meeting_end"
              aria-invalid={Boolean(fieldErrors.meeting_end)}
              aria-describedby={fieldErrors.meeting_end ? "error-meeting_end" : undefined}
                value={form.meeting_end}
                onChange={change}
                required
              />
            {fieldErrors.meeting_end && <small className="meetup-field-error" id="error-meeting_end">{fieldErrors.meeting_end}</small>}
            </label>
          </div>
        )}

        {/* 선택한 카테고리별 추가 입력 항목 */}
        {isProject && (
          <div className="meetup-form-section compact">
            <div className="meetup-field-title">
              프로젝트 기술 구성 <span>*</span>
            </div>

            <div className="meetup-field">
              <span>
                필수 기술 <b>*</b>
              </span>

              {skillOptions.length > 0 ? (
                <div
                  className="meetup-skill-select-list"
                  data-field="required_skill_ids" aria-invalid={Boolean(fieldErrors.required_skill_ids)} aria-describedby={fieldErrors.required_skill_ids ? "error-required_skill_ids" : undefined}
                  aria-label="프로젝트 필수 기술 선택"
                >
                  {skillOptions.map((skill) => {
                    const skillId = getSkillId(skill)
                    const skillName = getSkillName(skill)
                    const selected =
                      form.required_skill_ids?.includes(skillId)

                    return (
                      <button
                        key={skillId}
                        type="button"
                        className={[
                          'meetup-skill-select-button',
                          selected ? 'active' : '',
                        ]
                          .filter(Boolean)
                          .join(' ')}
                        aria-pressed={selected}
                        onClick={() => toggleRequiredSkill(skillId)}
                      >
                        {skillName}
                      </button>
                    )
                  })}
                </div>
              ) : (
                <p className="meetup-type-help">
                  {skillStatus === 'loading' ? '기술 목록을 불러오고 있어요.' : skillStatus}
                  {skillStatus !== 'loading' && <button type="button" onClick={() => setSkillAttempt((n) => n + 1)}>다시 불러오기</button>}
                </p>
              )}
            </div>

            {fieldErrors.required_skill_ids && <small id="error-required_skill_ids" className="meetup-field-error">{fieldErrors.required_skill_ids}</small>}
            {isEdit && !categoryChanged && <p className="meetup-type-help">내가 맡은 기술: {skillOptions.filter((skill) => form.creator_skill_ids.includes(getSkillId(skill))).map(getSkillName).join(' · ') || '담당 정보 없음'}</p>}
            {(!isEdit || categoryChanged) && !isAdmin && (
              <>
                <div className="meetup-field">
                  <span>
                    내가 맡을 기술 <b>*</b>
                  </span>

                  {form.required_skill_ids?.length > 0 ? (
                    <div
                      className="meetup-skill-select-list"
                      data-field="creator_skill_ids" aria-invalid={Boolean(fieldErrors.creator_skill_ids)} aria-describedby={fieldErrors.creator_skill_ids ? "error-creator_skill_ids" : undefined}
                      aria-label="개설자 담당 기술 선택"
                    >
                      {skillOptions
                        .filter((skill) =>
                          form.required_skill_ids.includes(
                            getSkillId(skill),
                          ),
                        )
                        .map((skill) => {
                          const skillId = getSkillId(skill)
                          const skillName = getSkillName(skill)
                          const selected =
                            form.creator_skill_ids?.includes(skillId)

                          return (
                            <button
                              key={skillId}
                              type="button"
                              className={[
                                'meetup-skill-select-button',
                                'creator',
                                selected ? 'active' : '',
                              ]
                                .filter(Boolean)
                                .join(' ')}
                              aria-pressed={selected}
                              onClick={() => toggleCreatorSkill(skillId)}
                            >
                              {skillName}
                            </button>
                          )
                        })}
                    </div>
                  ) : (
                    <p className="meetup-type-help">
                      먼저 위에서 프로젝트 필수 기술을 하나 이상 선택해주세요.
                    </p>
                  )}
                </div>

                {fieldErrors.creator_skill_ids && <small id="error-creator_skill_ids" className="meetup-field-error">{fieldErrors.creator_skill_ids}</small>}
                <label className="meetup-leader-volunteer">
                  <input
                    type="checkbox"
                    name="leader_volunteer"
              aria-invalid={Boolean(fieldErrors.leader_volunteer)}
              aria-describedby={fieldErrors.leader_volunteer ? "error-leader_volunteer" : undefined}
                    checked={Boolean(form.leader_volunteer)}
                    onChange={change}
                  />
            {fieldErrors.leader_volunteer && <small className="meetup-field-error" id="error-leader_volunteer">{fieldErrors.leader_volunteer}</small>}

                  <span>
                    프로젝트 팀장을 맡을 수 있어요
                    <small>
                      시작 24시간 전 서버가 확정 참여자와 신청 순서를 기준으로 실제 팀장을 결정합니다.
                    </small>
                  </span>
                </label>
              </>
            )}

            <p className="meetup-type-help">
              프로젝트는 확정 참여자 최소 2명과 모든 필수 기술 담당자가 충족되어야 정상 시작할 수 있어요.
            </p>
          </div>
        )}

        {form.category === 'sports' && (
          <div className="meetup-form-section compact">
            <label className="meetup-field">
              <span>
                운동 종목 <b>*</b>
              </span>

              <input
                name="sport_name"
              aria-invalid={Boolean(fieldErrors.sport_name)}
              aria-describedby={fieldErrors.sport_name ? "error-sport_name" : undefined}
                value={form.sport_name}
                onChange={change}
                placeholder="예) 요가, 러닝, 배드민턴"
                required
              />
            {fieldErrors.sport_name && <small className="meetup-field-error" id="error-sport_name">{fieldErrors.sport_name}</small>}
            </label>
          </div>
        )}

        {form.category === 'game' && (
          <div className="meetup-form-section compact">
            <label className="meetup-field">
              <span>
                게임 이름 <b>*</b>
              </span>

              <input
                name="game_name"
              aria-invalid={Boolean(fieldErrors.game_name)}
              aria-describedby={fieldErrors.game_name ? "error-game_name" : undefined}
                value={form.game_name}
                onChange={change}
                placeholder="예) 리그 오브 레전드"
                required
              />
            {fieldErrors.game_name && <small className="meetup-field-error" id="error-game_name">{fieldErrors.game_name}</small>}
            </label>
          </div>
        )}

        {isStudy && (
          <div className="meetup-form-section compact">
            <div className="meetup-form-grid two">
              <label className="meetup-field">
                <span>
                  스터디 종류 <b>*</b>
                </span>

                <select
                  name="study_type"
              disabled={isEdit && isProgram && !categoryChanged}
              aria-invalid={Boolean(fieldErrors.study_type)}
              aria-describedby={fieldErrors.study_type ? "error-study_type" : undefined}
                  value={form.study_type ?? 'TECHNOLOGY'}
                  onChange={change}
                  required
                >
                  <option value="TECHNOLOGY">기술 공부</option>
                  <option value="CERTIFICATE">자격증</option>
                </select>
            {fieldErrors.study_type && <small className="meetup-field-error" id="error-study_type">{fieldErrors.study_type}</small>}
              </label>

              {(form.study_type ?? 'TECHNOLOGY') === 'TECHNOLOGY' ? (
                <label className="meetup-field">
                  <span>
                    난이도 <b>*</b>
                  </span>

                  <select
                    name="difficulty"
              disabled={isEdit && isProgram && !categoryChanged}
              aria-invalid={Boolean(fieldErrors.difficulty)}
              aria-describedby={fieldErrors.difficulty ? "error-difficulty" : undefined}
                    value={form.difficulty ?? 'BEGINNER'}
                    onChange={change}
                    required
                  >
                    <option value="BEGINNER">기초</option>
                    <option value="ADVANCED">심화</option>
                  </select>
            {fieldErrors.difficulty && <small className="meetup-field-error" id="error-difficulty">{fieldErrors.difficulty}</small>}
                </label>
              ) : (
                <div className="meetup-field">
                  <span>난이도</span>
                  <p className="meetup-type-help">
                    자격증 스터디는 별도의 기술 난이도를 사용하지 않아요.
                  </p>
                </div>
              )}
            </div>

            <div className="meetup-form-grid two">
              <label className="meetup-field">
                <span>
                  {(form.study_type ?? 'TECHNOLOGY') === 'CERTIFICATE'
                    ? '자격증명'
                    : '스터디 주제'}{' '}
                  <b>*</b>
                </span>

                <input
                  name="study_topic"
              disabled={isEdit && isProgram && !categoryChanged}
              aria-invalid={Boolean(fieldErrors.study_topic)}
              aria-describedby={fieldErrors.study_topic ? "error-study_topic" : undefined}
                  value={form.study_topic ?? ''}
                  onChange={change}
                  placeholder={
                    (form.study_type ?? 'TECHNOLOGY') === 'CERTIFICATE'
                      ? '예) SQLD'
                      : '예) React 상태 관리'
                  }
                  required
                />
            {fieldErrors.study_topic && <small className="meetup-field-error" id="error-study_topic">{fieldErrors.study_topic}</small>}
              </label>

              <label className="meetup-field">
                <span>진행 기간</span>

                <input
                  name="study_period"
              disabled={isEdit && isProgram && !categoryChanged}
              aria-invalid={Boolean(fieldErrors.study_period)}
              aria-describedby={fieldErrors.study_period ? "error-study_period" : undefined}
                  value={form.study_period ?? ''}
                  onChange={change}
                  placeholder="예) 4주"
                />
            {fieldErrors.study_period && <small className="meetup-field-error" id="error-study_period">{fieldErrors.study_period}</small>}
              </label>
            </div>

            <label className="meetup-field">
              <span>진행 방법</span>

              <input
                name="study_method"
              disabled={isEdit && isProgram && !categoryChanged}
              aria-invalid={Boolean(fieldErrors.study_method)}
              aria-describedby={fieldErrors.study_method ? "error-study_method" : undefined}
                value={form.study_method ?? ''}
                onChange={change}
                placeholder="예) 주 1회 온라인 모임 + 주간 과제"
              />
            {fieldErrors.study_method && <small className="meetup-field-error" id="error-study_method">{fieldErrors.study_method}</small>}
            </label>
          </div>
        )}

        {form.category === 'group_buy' && (
          <div className="meetup-form-section compact">
            <div className="meetup-form-grid two">
              <label className="meetup-field">
                <span>
                  상품명 <b>*</b>
                </span>

                <input
                  name="product_name"
              aria-invalid={Boolean(fieldErrors.product_name)}
              aria-describedby={fieldErrors.product_name ? "error-product_name" : undefined}
                  value={form.product_name}
                  onChange={change}
                  placeholder="예) 파이썬 교재"
                  required
                />
            {fieldErrors.product_name && <small className="meetup-field-error" id="error-product_name">{fieldErrors.product_name}</small>}
              </label>

              <label className="meetup-field">
                <span>
                  1인 예상 가격 <b>*</b>
                </span>

                <div className="meetup-price-input">
                  <input
                    type="text"
                    name="estimated_price_per_person"
              aria-invalid={Boolean(fieldErrors.estimated_price_per_person)}
              aria-describedby={fieldErrors.estimated_price_per_person ? "error-estimated_price_per_person" : undefined}
                    value={
                      form.estimated_price_per_person
                        ? Number(
                            form.estimated_price_per_person,
                          ).toLocaleString('ko-KR')
                        : ''
                    }
                    onChange={changePrice}
                    placeholder="예) 15,000"
                    inputMode="numeric"
                    required
                  />
            {fieldErrors.estimated_price_per_person && <small className="meetup-field-error" id="error-estimated_price_per_person">{fieldErrors.estimated_price_per_person}</small>}
                </div>
              </label>
            </div>

            <div className="meetup-form-grid two">
              <label className="meetup-field">
                <span>
                  수령 방법 <b>*</b>
                </span>

                <input
                  name="pickup_method"
              aria-invalid={Boolean(fieldErrors.pickup_method)}
              aria-describedby={fieldErrors.pickup_method ? "error-pickup_method" : undefined}
                  value={form.pickup_method}
                  onChange={change}
                  placeholder="예) 오프라인 전달"
                  required
                />
            {fieldErrors.pickup_method && <small className="meetup-field-error" id="error-pickup_method">{fieldErrors.pickup_method}</small>}
              </label>

              <label className="meetup-field">
                <span>구매 링크</span>

                <input
                  name="purchase_url"
              aria-invalid={Boolean(fieldErrors.purchase_url)}
              aria-describedby={fieldErrors.purchase_url ? "error-purchase_url" : undefined}
                  value={form.purchase_url}
                  onChange={change}
                  placeholder="https://..."
                />
            {fieldErrors.purchase_url && <small className="meetup-field-error" id="error-purchase_url">{fieldErrors.purchase_url}</small>}
              </label>
            </div>
          </div>
        )}

        {/* 저장 상태에 따른 제출 버튼 표시 */}
        <div className="meetup-form-footer">
          <div className="meetup-form-actions">
            <button
              type="button"
              className="secondary"
              onClick={onBack}
            >
              취소
            </button>

            <button
              type="submit"
              className="primary"
              disabled={busy}
            >
              {busy ? '저장 중...' : isEdit ? '수정 완료' : '등록하기'}
            </button>
          </div>
        </div>
        </fieldset>
      </form>
    </main>
  )
}
