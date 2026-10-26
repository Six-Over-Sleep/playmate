import { useEffect, useRef, useState } from 'react'

import {
  normalizeRegularDays,
  toDateTimeLocal,
  toTimeValue,
} from '../../utils/meetup'

import {
  createKakaoMap,
  loadKakaoMaps,
  moveKakaoMapToPlace,
  searchKakaoPlaces,
} from '../../utils/kakaoMap'

// 배열이 숫자 ID 또는 기술 객체 형태로 와도 기술 ID 배열로 통일함.
function normalizeSkillIds(value) {
  if (!Array.isArray(value)) {
    return []
  }

  return value
    .map((item) => {
      if (typeof item === 'number') {
        return item
      }

      if (typeof item === 'string' && item.trim() !== '') {
        return Number(item)
      }

      return Number(item?.skill_id ?? item?.id)
    })
    .filter((id) => Number.isInteger(id) && id > 0)
}

// datetime-local 값을 새 프로젝트·스터디 API의 Asia/Seoul ISO 형식으로 변환함.
// 기존 운동·게임·공동구매 일정 형식은 별도 변환하지 않아 기존 계약을 유지함.
function toSeoulIso(value) {
  if (!value) {
    return null
  }

  const text = String(value)

  // 이미 시간대가 포함되어 있으면 그대로 사용함.
  if (/[zZ]$|[+-]\d{2}:\d{2}$/.test(text)) {
    return text
  }

  if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(text)) {
    return `${text}:00+09:00`
  }

  if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$/.test(text)) {
    return `${text}+09:00`
  }

  return text
}

// 정기 일정의 첫 날짜와 시간을 프로젝트·스터디 전체 시작 시각으로 조합함.
function makeRegularStartsAt(date, time) {
  if (!date || !time) {
    return null
  }

  const normalizedTime =
    String(time).length === 5 ? `${time}:00` : String(time)

  return `${date}T${normalizedTime}+09:00`
}

// 기존 모임 정보를 폼 초기값으로 변환함.
function makeInitialForm(meetup) {
  const categoryDetail = meetup?.detail || {}
  const category = meetup?.category || 'study'
  const creatorApplication = meetup?.creator_application || null

  return {
    title: meetup?.title || '',
    body: meetup?.body || '',
    capacity: meetup?.capacity || 2,

    is_online: Boolean(meetup?.is_online),

    place: meetup?.place || '',
    place_latitude: meetup?.place_latitude ?? '',
    place_longitude: meetup?.place_longitude ?? '',

    meeting_start: toDateTimeLocal(meetup?.meeting_start),
    meeting_end: toDateTimeLocal(meetup?.meeting_end),

    regular_days: normalizeRegularDays(meetup?.regular_days),

    regular_time: toTimeValue(meetup?.regular_time),

    regular_start_date: meetup?.regular_start_date
      ? String(meetup.regular_start_date).slice(0, 10)
      : '',

    recruit_end: toDateTimeLocal(meetup?.deadline_at),

    recruit_mode:
      String(meetup?.recruit_mode || '').toLowerCase() === 'short'
        ? 'short'
        : 'regular',

    category,

    // 프로젝트·스터디 전체 운영 종료 시각.
    // 정기 모임은 반복 일정과 별도로 전체 종료 시점을 저장함.
    ends_at: toDateTimeLocal(meetup?.ends_at),

    // 프로젝트 필수 기술과 사용자 개설자의 담당 기술.
    required_skill_ids: normalizeSkillIds(
      meetup?.required_skill_ids ?? meetup?.required_skills,
    ),
    creator_skill_ids: normalizeSkillIds(creatorApplication?.skill_ids),

    // 사용자 개설자도 실제 확정 참여자이므로 팀장 역할 가능 여부를 신청 정보에 포함함.
    leader_volunteer: Boolean(creatorApplication?.leader_volunteer),

    sport_name: categoryDetail?.sport_name || '',

    game_name: categoryDetail?.game_name || '',

    study_topic: categoryDetail?.study_topic || '',

    study_period: categoryDetail?.study_period || '',

    study_method: categoryDetail?.study_method || '',

    study_type: categoryDetail?.study_type || 'TECHNOLOGY',

    difficulty:
      categoryDetail?.study_type === 'CERTIFICATE'
        ? ''
        : categoryDetail?.difficulty || 'BEGINNER',

    product_name: categoryDetail?.product_name || '',

    purchase_url: categoryDetail?.purchase_url || '',

    estimated_price_per_person:
      categoryDetail?.estimated_price_per_person ?? '',

    pickup_method: categoryDetail?.pickup_method || '',
  }
}

function getCoordinate(value) {
  if (value === '' || value == null) {
    return null
  }

  return Number(value)
}

// 모임 방식에 맞는 일정만 전송하고 나머지는 null로 처리함.
// 새 프로젝트·스터디의 datetime 필드는 시간대를 포함해 전송함.
function buildSchedulePayload(form, isGroupBuy, isProjectOrStudy) {
  const isRegular = !isGroupBuy && form.recruit_mode === 'regular'
  const isShort = !isGroupBuy && form.recruit_mode === 'short'

  return {
    regular_days: isRegular ? form.regular_days : null,

    regular_start_date: isRegular
      ? form.regular_start_date || null
      : null,

    regular_time: isRegular
      ? form.regular_time || null
      : null,

    meeting_start: isShort
      ? isProjectOrStudy
        ? toSeoulIso(form.meeting_start)
        : form.meeting_start || null
      : null,

    meeting_end: isShort
      ? isProjectOrStudy
        ? toSeoulIso(form.meeting_end)
        : form.meeting_end || null
      : null,
  }
}

// 프로젝트·스터디는 반복/단기 일정과 별도로 전체 운영 시작·종료 시각을 전송함.
function buildLifecycleSchedulePayload(form, isProjectOrStudy) {
  if (!isProjectOrStudy) {
    return {}
  }

  const startsAt =
    form.recruit_mode === 'regular'
      ? makeRegularStartsAt(form.regular_start_date, form.regular_time)
      : toSeoulIso(form.meeting_start)

  const endsAt =
    form.recruit_mode === 'regular'
      ? toSeoulIso(form.ends_at)
      : toSeoulIso(form.meeting_end)

  return {
    starts_at: startsAt,
    ends_at: endsAt,
  }
}

// 카테고리별 상세 정보를 전송할 형태로 구성함.
function buildCategoryPayload(form) {
  const isStudy = form.category === 'study'

  return {
    sport_name:
      form.category === 'sports' ? form.sport_name || null : null,

    game_name:
      form.category === 'game' ? form.game_name || null : null,

    study_topic: isStudy ? form.study_topic || null : null,

    study_period: isStudy ? form.study_period || null : null,

    study_method: isStudy ? form.study_method || null : null,

    study_type: isStudy ? form.study_type || null : null,

    difficulty:
      isStudy && form.study_type === 'TECHNOLOGY'
        ? form.difficulty || null
        : null,

    product_name:
      form.category === 'group_buy'
        ? form.product_name || null
        : null,

    purchase_url:
      form.category === 'group_buy'
        ? form.purchase_url || null
        : null,

    estimated_price_per_person:
      form.category === 'group_buy' &&
      form.estimated_price_per_person !== ''
        ? Number(form.estimated_price_per_person)
        : null,

    pickup_method:
      form.category === 'group_buy'
        ? form.pickup_method || null
        : null,
  }
}

// 사용자 생성 프로젝트의 개설자 신청 정보를 구성함.
// 커리어 실제 연동 전이므로 career_item_ids는 빈 배열만 전송함.
function buildCreatorApplication(form) {
  return {
    skill_ids: form.creator_skill_ids,
    career_item_ids: [],
    leader_volunteer: Boolean(form.leader_volunteer),
    direct_input: {
      skills: [],
      education: null,
      certificates: null,
      experience: null,
      awards: null,
      portfolio_url: null,
    },
  }
}

// 모임 작성·수정 폼과 장소 검색을 관리함.
export default function useMeetupEditor({ meetup, onSubmit }) {
  const isEdit = Boolean(meetup)

  const [form, setForm] = useState(() => makeInitialForm(meetup))

  const [placeResults, setPlaceResults] = useState([])

  const [placeSearchStatus, setPlaceSearchStatus] = useState('')

  const mapContainerRef = useRef(null)
  const mapRef = useRef(null)
  const markerRef = useRef(null)

  const isGroupBuy = form.category === 'group_buy'
  const isProject = form.category === 'project'
  const isStudy = form.category === 'study'
  const isProjectOrStudy = isProject || isStudy

  // 편집 대상이 바뀌면 폼과 장소 검색 상태를 초기화함.
  useEffect(() => {
    setForm(makeInitialForm(meetup))
    setPlaceResults([])
    setPlaceSearchStatus('')
  }, [meetup])

  // 오프라인 모임의 지도를 준비하고 저장된 위치가 있으면 마커를 표시함.
  useEffect(() => {
    if (form.is_online || !mapContainerRef.current) {
      return
    }

    let cancelled = false

    loadKakaoMaps()
      .then((kakao) => {
        if (cancelled || !mapContainerRef.current) {
          return
        }

        mapRef.current = createKakaoMap({
          kakao,
          container: mapContainerRef.current,
          latitude: form.place_latitude,
          longitude: form.place_longitude,
        })

        const hasSavedPosition =
          form.place_latitude !== '' &&
          form.place_longitude !== ''

        if (hasSavedPosition) {
          markerRef.current = moveKakaoMapToPlace({
            kakao,
            map: mapRef.current,
            marker: markerRef.current,
            latitude: form.place_latitude,
            longitude: form.place_longitude,
          })
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setPlaceSearchStatus(err.message)
        }
      })

    return () => {
      cancelled = true
    }
  }, [form.is_online])

  const change = (event) => {
    const { name, value, type, checked } = event.target
    const nextValue = type === 'checkbox' ? checked : value

    setForm((prev) => {
      const next = {
        ...prev,
        [name]: nextValue,
      }

      // 자격증 스터디에는 기술 난이도를 강제하지 않음.
      if (name === 'study_type') {
        next.difficulty =
          value === 'CERTIFICATE'
            ? ''
            : prev.difficulty || 'BEGINNER'
      }

      return next
    })
  }

  // 예상 가격에는 숫자만 입력되도록 처리함.
  const changePrice = (event) => {
    const onlyNumber = event.target.value.replace(/[^0-9]/g, '')

    setForm((prev) => ({
      ...prev,
      estimated_price_per_person: onlyNumber,
    }))
  }

  const setRecruitMode = (mode) => {
    setForm((prev) => ({
      ...prev,
      recruit_mode: mode,
    }))
  }

  const setCategory = (category) => {
    setForm((prev) => ({
      ...prev,
      category,

      // 프로젝트 전용 값이 다른 종류에 남아 전송되지 않도록 화면 상태도 정리함.
      ...(category !== 'project'
        ? {
            required_skill_ids: [],
            creator_skill_ids: [],
            leader_volunteer: false,
          }
        : {}),

      // 스터디로 처음 전환하면 기본 종류와 난이도를 준비함.
      ...(category === 'study'
        ? {
            study_type: prev.study_type || 'TECHNOLOGY',
            difficulty:
              prev.study_type === 'CERTIFICATE'
                ? ''
                : prev.difficulty || 'BEGINNER',
          }
        : {}),
    }))
  }

  // 프로젝트 필수 기술 선택/해제를 관리함.
  // 실제 기술 목록과 ID는 기술 사전 API에서 받아야 하며 여기서 하드코딩하지 않음.
  const toggleRequiredSkill = (skillId) => {
    const normalizedId = Number(skillId)

    if (!Number.isInteger(normalizedId) || normalizedId <= 0) {
      return
    }

    setForm((prev) => {
      const exists = prev.required_skill_ids.includes(normalizedId)

      const requiredSkillIds = exists
        ? prev.required_skill_ids.filter(
            (id) => id !== normalizedId,
          )
        : [...prev.required_skill_ids, normalizedId]

      return {
        ...prev,
        required_skill_ids: requiredSkillIds,

        // 필수 기술에서 해제된 기술은 개설자의 담당 기술에서도 함께 제거함.
        creator_skill_ids: prev.creator_skill_ids.filter((id) =>
          requiredSkillIds.includes(id),
        ),
      }
    })
  }

  // 사용자 개설자가 프로젝트에서 맡을 필수 기술을 선택/해제함.
  const toggleCreatorSkill = (skillId) => {
    const normalizedId = Number(skillId)

    if (
      !Number.isInteger(normalizedId) ||
      !form.required_skill_ids.includes(normalizedId)
    ) {
      return
    }

    setForm((prev) => ({
      ...prev,
      creator_skill_ids: prev.creator_skill_ids.includes(
        normalizedId,
      )
        ? prev.creator_skill_ids.filter(
            (id) => id !== normalizedId,
          )
        : [...prev.creator_skill_ids, normalizedId],
    }))
  }

  // 온라인으로 전환하면 오프라인 장소와 좌표를 비움.
  const setPlaceType = (isOnline) => {
    setForm((prev) => ({
      ...prev,
      is_online: isOnline,

      ...(isOnline
        ? {
            place: '',
            place_latitude: '',
            place_longitude: '',
          }
        : {}),
    }))

    setPlaceResults([])
    setPlaceSearchStatus('')
  }

  // 선택한 요일을 추가하거나 해제함.
  const toggleRegularDay = (day) => {
    setForm((prev) => ({
      ...prev,

      regular_days: prev.regular_days.includes(day)
        ? prev.regular_days.filter((item) => item !== day)
        : [...prev.regular_days, day],
    }))
  }

  // 카카오 장소 검색 결과를 최대 7개까지 표시함.
  const searchPlace = async () => {
    const keyword = form.place.trim()

    if (!keyword) {
      alert('검색할 장소를 입력해주세요.')
      return
    }

    setPlaceSearchStatus('장소를 검색하고 있어요.')

    setPlaceResults([])

    try {
      const data = await searchKakaoPlaces(keyword)

      setPlaceResults(data.slice(0, 7))

      setPlaceSearchStatus(
        data.length > 0
          ? '검색 결과에서 장소를 선택해주세요.'
          : '검색 결과가 없어요. 다른 검색어를 입력해주세요.',
      )
    } catch (err) {
      setPlaceResults([])
      setPlaceSearchStatus(err.message)
    }
  }

  // 선택한 장소를 폼에 저장하고 지도 마커를 이동함.
  const selectPlace = async (place) => {
    const latitude = place.y
    const longitude = place.x

    setForm((prev) => ({
      ...prev,

      place: place.place_name,
      place_latitude: latitude,
      place_longitude: longitude,
    }))

    setPlaceResults([])
    setPlaceSearchStatus('')

    try {
      const kakao = await loadKakaoMaps()

      markerRef.current = moveKakaoMapToPlace({
        kakao,
        map: mapRef.current,
        marker: markerRef.current,
        latitude,
        longitude,
      })
    } catch (err) {
      setPlaceSearchStatus(err.message)
    }
  }

  // 일정·장소·프로젝트·스터디 입력값을 화면 단계에서 먼저 검증함.
  // 신청 확정/대기, 권한, 팀장 선정 등 서버 업무 규칙은 프론트에서 계산하지 않음.
  const validate = () => {
    if (
      !isGroupBuy &&
      form.recruit_mode === 'regular' &&
      form.regular_days.length === 0
    ) {
      alert('정기 모임 요일을 하나 이상 선택해주세요.')
      return false
    }

    if (
      !isGroupBuy &&
      form.recruit_mode === 'regular' &&
      !form.regular_start_date
    ) {
      alert('정기 모임 시작 날짜를 선택해주세요.')
      return false
    }

    if (
      !isGroupBuy &&
      form.recruit_mode === 'regular' &&
      !form.regular_time
    ) {
      alert('정기 모임 시간을 선택해주세요.')
      return false
    }

    if (
      !isGroupBuy &&
      form.recruit_mode === 'short' &&
      !form.meeting_start
    ) {
      alert('모임 시작 일시를 선택해주세요.')
      return false
    }

    if (
      !isGroupBuy &&
      form.recruit_mode === 'short' &&
      !form.meeting_end
    ) {
      alert('모임 종료 일시를 선택해주세요.')
      return false
    }

    if (isProjectOrStudy) {
      const capacity = Number(form.capacity)

      if (
        !Number.isInteger(capacity) ||
        capacity < 2 ||
        capacity > 5
      ) {
        alert(
          '프로젝트·스터디 모집 인원은 2명 이상 5명 이하로 입력해주세요.',
        )
        return false
      }

      if (
        form.recruit_mode === 'regular' &&
        !form.ends_at
      ) {
        alert('전체 모임 종료 일시를 선택해주세요.')
        return false
      }

      const startsAt =
        form.recruit_mode === 'regular'
          ? makeRegularStartsAt(
              form.regular_start_date,
              form.regular_time,
            )
          : toSeoulIso(form.meeting_start)

      const endsAt =
        form.recruit_mode === 'regular'
          ? toSeoulIso(form.ends_at)
          : toSeoulIso(form.meeting_end)

      if (
        startsAt &&
        endsAt &&
        new Date(endsAt).getTime() <=
          new Date(startsAt).getTime()
      ) {
        alert('모임 종료 일시는 시작 일시보다 늦어야 해요.')
        return false
      }
    }

    if (isStudy) {
      if (!form.study_topic.trim()) {
        alert('스터디 주제를 입력해주세요.')
        return false
      }

      if (
        !['TECHNOLOGY', 'CERTIFICATE'].includes(
          form.study_type,
        )
      ) {
        alert('스터디 종류를 선택해주세요.')
        return false
      }

      if (
        form.study_type === 'TECHNOLOGY' &&
        !['BEGINNER', 'ADVANCED'].includes(
          form.difficulty,
        )
      ) {
        alert('기술 스터디 난이도를 선택해주세요.')
        return false
      }
    }

    if (isProject) {
      if (form.required_skill_ids.length === 0) {
        alert('프로젝트 필수 기술을 하나 이상 선택해주세요.')
        return false
      }

      if (!isEdit && form.creator_skill_ids.length === 0) {
        alert('개설자가 맡을 담당 기술을 하나 이상 선택해주세요.')
        return false
      }

      const hasInvalidCreatorSkill =
        form.creator_skill_ids.some(
          (id) => !form.required_skill_ids.includes(id),
        )

      if (hasInvalidCreatorSkill) {
        alert(
          '개설자 담당 기술은 프로젝트 필수 기술 중에서 선택해주세요.',
        )
        return false
      }
    }

    if (!form.is_online && !form.place.trim()) {
      alert('오프라인 모임 장소를 입력해주세요.')
      return false
    }

    return true
  }

  // 입력값을 API 요청 형태로 변환해 부모의 저장 함수에 전달함.
  const submit = (event) => {
    event.preventDefault()

    if (!validate()) {
      return
    }

    const schedulePayload = buildSchedulePayload(
      form,
      isGroupBuy,
      isProjectOrStudy,
    )

    const lifecycleSchedulePayload =
      buildLifecycleSchedulePayload(
        form,
        isProjectOrStudy,
      )

    const categoryPayload = buildCategoryPayload(form)

    const commonPayload = {
      title: form.title,
      body: form.body,
      capacity: Number(form.capacity),

      is_online: form.is_online,

      place: form.is_online ? null : form.place || null,

      place_latitude: form.is_online
        ? null
        : getCoordinate(form.place_latitude),

      place_longitude: form.is_online
        ? null
        : getCoordinate(form.place_longitude),

      deadline_at: isProjectOrStudy
        ? toSeoulIso(form.recruit_end)
        : form.recruit_end || null,

      ...schedulePayload,
      ...lifecycleSchedulePayload,
      ...categoryPayload,

      ...(isProject
        ? {
            required_skill_ids: form.required_skill_ids,
          }
        : {}),
    }

    if (isEdit) {
      // 프로젝트의 연장·예외 시작은 일반 PATCH가 아닌 전용 흐름이므로
      // 여기서는 기존 수정 폼에서 허용된 정보만 서버가 최종 검증함.
      onSubmit(commonPayload)
      return
    }

    onSubmit({
      ...commonPayload,

      recruit_mode: form.recruit_mode,

      category: form.category,

      meeting_datetime: null,

      contact_method: null,

      ...(isProject
        ? {
            creator_application:
              buildCreatorApplication(form),
          }
        : {}),
    })
  }

  return {
    form,
    isEdit,
    isGroupBuy,
    isProject,
    isStudy,
    isProjectOrStudy,

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
  }
}
