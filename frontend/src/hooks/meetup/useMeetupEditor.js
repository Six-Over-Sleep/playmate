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

function makeInitialForm(meetup) {
  const categoryDetail = meetup?.detail || {}

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

    category: meetup?.category || 'study',

    sport_name: categoryDetail?.sport_name || '',

    game_name: categoryDetail?.game_name || '',

    study_topic: categoryDetail?.study_topic || '',

    study_period: categoryDetail?.study_period || '',

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

function buildSchedulePayload(form, isGroupBuy) {
  return {
    regular_days:
      !isGroupBuy && form.recruit_mode === 'regular' ? form.regular_days : null,

    regular_start_date:
      !isGroupBuy && form.recruit_mode === 'regular'
        ? form.regular_start_date || null
        : null,

    regular_time:
      !isGroupBuy && form.recruit_mode === 'regular'
        ? form.regular_time || null
        : null,

    meeting_start:
      !isGroupBuy && form.recruit_mode === 'short'
        ? form.meeting_start || null
        : null,

    meeting_end:
      !isGroupBuy && form.recruit_mode === 'short'
        ? form.meeting_end || null
        : null,
  }
}

function buildCategoryPayload(form) {
  return {
    sport_name: form.category === 'sports' ? form.sport_name || null : null,

    game_name: form.category === 'game' ? form.game_name || null : null,

    study_topic: form.category === 'study' ? form.study_topic || null : null,

    study_period: form.category === 'study' ? form.study_period || null : null,

    product_name:
      form.category === 'group_buy' ? form.product_name || null : null,

    purchase_url:
      form.category === 'group_buy' ? form.purchase_url || null : null,

    estimated_price_per_person:
      form.category === 'group_buy' && form.estimated_price_per_person !== ''
        ? Number(form.estimated_price_per_person)
        : null,

    pickup_method:
      form.category === 'group_buy' ? form.pickup_method || null : null,
  }
}

export default function useMeetupEditor({ meetup, onSubmit }) {
  const isEdit = Boolean(meetup)

  const [form, setForm] = useState(() => makeInitialForm(meetup))

  const [placeResults, setPlaceResults] = useState([])

  const [placeSearchStatus, setPlaceSearchStatus] = useState('')

  const mapContainerRef = useRef(null)
  const mapRef = useRef(null)
  const markerRef = useRef(null)

  const isGroupBuy = form.category === 'group_buy'

  useEffect(() => {
    setForm(makeInitialForm(meetup))
    setPlaceResults([])
    setPlaceSearchStatus('')
  }, [meetup])

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
          form.place_latitude !== '' && form.place_longitude !== ''

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
    const { name, value } = event.target

    setForm((prev) => ({
      ...prev,
      [name]: value,
    }))
  }

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
    }))
  }

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

  const toggleRegularDay = (day) => {
    setForm((prev) => ({
      ...prev,

      regular_days: prev.regular_days.includes(day)
        ? prev.regular_days.filter((item) => item !== day)
        : [...prev.regular_days, day],
    }))
  }

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

    if (!form.is_online && !form.place.trim()) {
      alert('오프라인 모임 장소를 입력해주세요.')
      return false
    }

    return true
  }

  const submit = (event) => {
    event.preventDefault()

    if (!validate()) {
      return
    }

    const schedulePayload = buildSchedulePayload(form, isGroupBuy)

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

      deadline_at: form.recruit_end || null,

      ...schedulePayload,
      ...categoryPayload,
    }

    if (isEdit) {
      onSubmit(commonPayload)
      return
    }

    onSubmit({
      ...commonPayload,

      recruit_mode: form.recruit_mode,

      category: form.category,

      meeting_datetime: null,

      contact_method: null,
    })
  }

  return {
    form,
    isEdit,
    isGroupBuy,

    placeResults,
    placeSearchStatus,

    mapContainerRef,

    change,
    changePrice,

    setRecruitMode,
    setCategory,
    setPlaceType,

    toggleRegularDay,

    searchPlace,
    selectPlace,

    submit,
  }
}
