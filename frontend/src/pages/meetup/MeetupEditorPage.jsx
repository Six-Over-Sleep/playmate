import { useEffect, useRef, useState } from 'react'

const CATEGORY_OPTIONS = [
  { value: 'study', label: '📖 스터디' },
  { value: 'game', label: '🎮 게임' },
  { value: 'sports', label: '🏃 운동' },
  { value: 'group_buy', label: '🛒 공동구매' },
]

const WEEKDAYS = ['월', '화', '수', '목', '금', '토', '일']


function normalizeRegularDays(value) {
  if (Array.isArray(value)) return value

  if (typeof value === 'string') {
    try {
      const parsed = JSON.parse(value)
      if (Array.isArray(parsed)) return parsed
    } catch {
      return value
        .split(',')
        .map((item) => item.trim())
        .filter(Boolean)
    }
  }

  return []
}

function toDateTimeLocal(value) {
  if (!value) return ''
  return String(value).slice(0, 16)
}

function toTimeValue(value) {
  if (!value) return ''
  return String(value).slice(0, 5)
}

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
    study_method: categoryDetail?.study_method || '',

    product_name: categoryDetail?.product_name || '',
    purchase_url: categoryDetail?.purchase_url || '',
    estimated_price_per_person:
      categoryDetail?.estimated_price_per_person ?? '',
    pickup_method: categoryDetail?.pickup_method || '',
  }
}

export default function MeetupEditorPage({
  meetup = null,
  busy,
  onBack,
  onSubmit,
}) {
  const isEdit = Boolean(meetup)

  const [form, setForm] = useState(() => makeInitialForm(meetup))
  const [placeResults, setPlaceResults] = useState([])
  const [placeSearchStatus, setPlaceSearchStatus] = useState('')
  const mapContainerRef = useRef(null)
  const mapRef = useRef(null)
  const markerRef = useRef(null)

  useEffect(() => {
    setForm(makeInitialForm(meetup))
    setPlaceResults([])
    setPlaceSearchStatus('')
  }, [meetup])

  const loadKakaoMaps = () =>
    new Promise((resolve, reject) => {
      const appKey = import.meta.env.VITE_KAKAO_MAP_KEY

      if (!appKey) {
        reject(new Error('VITE_KAKAO_MAP_KEY가 설정되지 않았어요.'))
        return
      }

      if (window.kakao?.maps?.services) {
        resolve(window.kakao)
        return
      }

      const finishLoad = () => {
        if (!window.kakao?.maps) {
          reject(new Error('카카오맵 SDK를 불러오지 못했어요.'))
          return
        }

        window.kakao.maps.load(() => resolve(window.kakao))
      }

      const existingScript = document.querySelector(
        'script[data-kakao-map-sdk="true"]',
      )

      if (existingScript) {
        if (window.kakao?.maps) {
          finishLoad()
        } else {
          existingScript.addEventListener('load', finishLoad, { once: true })
          existingScript.addEventListener(
            'error',
            () => reject(new Error('카카오맵 SDK를 불러오지 못했어요.')),
            { once: true },
          )
        }
        return
      }

      const script = document.createElement('script')
      script.dataset.kakaoMapSdk = 'true'
      script.async = true
      script.src =
        `https://dapi.kakao.com/v2/maps/sdk.js?appkey=${appKey}` +
        '&autoload=false&libraries=services'

      script.addEventListener('load', finishLoad, { once: true })
      script.addEventListener(
        'error',
        () => reject(new Error('카카오맵 SDK를 불러오지 못했어요.')),
        { once: true },
      )

      document.head.appendChild(script)
    })

  const moveMapToPlace = (kakao, latitude, longitude) => {
    if (!mapRef.current) return

    const position = new kakao.maps.LatLng(
      Number(latitude),
      Number(longitude),
    )

    mapRef.current.setCenter(position)
    mapRef.current.setLevel(3)

    if (markerRef.current) {
      markerRef.current.setMap(null)
    }

    markerRef.current = new kakao.maps.Marker({
      map: mapRef.current,
      position,
    })
  }

  useEffect(() => {
    if (form.is_online || !mapContainerRef.current) return

    let cancelled = false

    loadKakaoMaps()
      .then((kakao) => {
        if (cancelled || !mapContainerRef.current) return

        const hasSavedPosition =
          form.place_latitude !== '' && form.place_longitude !== ''

        const center = hasSavedPosition
          ? new kakao.maps.LatLng(
              Number(form.place_latitude),
              Number(form.place_longitude),
            )
          : new kakao.maps.LatLng(37.5665, 126.978)

        mapRef.current = new kakao.maps.Map(mapContainerRef.current, {
          center,
          level: hasSavedPosition ? 3 : 7,
        })

        if (hasSavedPosition) {
          moveMapToPlace(
            kakao,
            form.place_latitude,
            form.place_longitude,
          )
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


  const change = (e) => {
    const { name, value } = e.target

    setForm((prev) => ({
      ...prev,
      [name]: value,
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
    }))

    setPlaceResults([])
    setPlaceSearchStatus('')
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
      const kakao = await loadKakaoMaps()
      const places = new kakao.maps.services.Places()

      places.keywordSearch(keyword, (data, status) => {
        if (status === kakao.maps.services.Status.OK) {
          setPlaceResults(data.slice(0, 7))
          setPlaceSearchStatus(
            data.length > 0 ? '검색 결과에서 장소를 선택해주세요.' : '',
          )
          return
        }

        if (status === kakao.maps.services.Status.ZERO_RESULT) {
          setPlaceResults([])
          setPlaceSearchStatus('검색 결과가 없어요. 다른 검색어를 입력해주세요.')
          return
        }

        setPlaceResults([])
        setPlaceSearchStatus('장소 검색 중 오류가 발생했어요.')
      })
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
      moveMapToPlace(kakao, latitude, longitude)
    } catch (err) {
      setPlaceSearchStatus(err.message)
    }
  }

  const toggleRegularDay = (day) => {
    setForm((prev) => ({
      ...prev,
      regular_days: prev.regular_days.includes(day)
        ? prev.regular_days.filter((item) => item !== day)
        : [...prev.regular_days, day],
    }))
  }

  const submit = (e) => {
    e.preventDefault()

    if (form.recruit_mode === 'regular' && form.regular_days.length === 0) {
      alert('정기 모임 요일을 하나 이상 선택해주세요.')
      return
    }

    if (!form.is_online && !form.place.trim()) {
      alert('오프라인 모임 장소를 입력해주세요.')
      return
    }

    const deadlineAt = form.recruit_end || null

    if (isEdit) {
      onSubmit({
        title: form.title,
        body: form.body,
        capacity: Number(form.capacity),
        is_online: form.is_online,
        place: form.is_online ? null : form.place || null,
        deadline_at: deadlineAt,

        // 아래 일정 필드는 백엔드 필드 추가 후 그대로 저장 가능
        regular_days:
          form.recruit_mode === 'regular' ? form.regular_days : null,
        regular_time:
          form.recruit_mode === 'regular' ? form.regular_time || null : null,
        meeting_start:
          form.recruit_mode === 'short' ? form.meeting_start || null : null,
        meeting_end:
          form.recruit_mode === 'short' ? form.meeting_end || null : null,

        sport_name:
          form.category === 'sports' ? form.sport_name || null : null,
        game_name:
          form.category === 'game' ? form.game_name || null : null,
        study_topic:
          form.category === 'study' ? form.study_topic || null : null,
        study_period:
          form.category === 'study' ? form.study_period || null : null,
        study_method:
          form.category === 'study' ? form.study_method || null : null,
        product_name:
          form.category === 'group_buy' ? form.product_name || null : null,
        purchase_url:
          form.category === 'group_buy' ? form.purchase_url || null : null,
        estimated_price_per_person:
          form.category === 'group_buy' &&
          form.estimated_price_per_person !== ''
            ? Number(form.estimated_price_per_person)
            : null,
        pickup_method:
          form.category === 'group_buy' ? form.pickup_method || null : null,
      })

      return
    }

    onSubmit({
      title: form.title,
      body: form.body,
      recruit_mode: form.recruit_mode,
      category: form.category,
      capacity: Number(form.capacity),

      // 기존 meeting_datetime은 사용하지 않고 정기/단기 일정 필드로 분리
      meeting_datetime: null,
      regular_days:
        form.recruit_mode === 'regular' ? form.regular_days : null,
      regular_time:
        form.recruit_mode === 'regular' ? form.regular_time || null : null,
      meeting_start:
        form.recruit_mode === 'short' ? form.meeting_start || null : null,
      meeting_end:
        form.recruit_mode === 'short' ? form.meeting_end || null : null,
      place: form.is_online ? null : form.place || null,
      is_online: form.is_online,
      contact_method: null,
      deadline_at: deadlineAt,

      sport_name:
        form.category === 'sports' ? form.sport_name || null : null,
      game_name:
        form.category === 'game' ? form.game_name || null : null,
      study_topic:
        form.category === 'study' ? form.study_topic || null : null,
      study_period:
        form.category === 'study' ? form.study_period || null : null,
      study_method:
        form.category === 'study' ? form.study_method || null : null,
      product_name:
        form.category === 'group_buy' ? form.product_name || null : null,
      purchase_url:
        form.category === 'group_buy' ? form.purchase_url || null : null,
      estimated_price_per_person:
        form.category === 'group_buy' &&
        form.estimated_price_per_person !== ''
          ? Number(form.estimated_price_per_person)
          : null,
      pickup_method:
        form.category === 'group_buy' ? form.pickup_method || null : null,
    })
  }

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

        <p className="meetup-editor-description">
          {isEdit
            ? '모임 정보를 수정해보세요.'
            : '함께할 사람을 모집해보세요.'}
        </p>
      </div>

      <form className="meetup-form-card" onSubmit={submit}>
        <>
          <div className="meetup-form-section">
              <div className="meetup-field-title">
                모임 형태 <span>*</span>
              </div>

              <div className="meetup-segmented-control meetup-recruit-mode">
                <button
                  type="button"
                  className={form.recruit_mode === 'regular' ? 'active' : ''}
                  onClick={() => setRecruitMode('regular')}
                  disabled={isEdit}
                  title={isEdit ? '모임 형태는 생성 후 변경할 수 없어요.' : undefined}
                >
                  정기 모임
                </button>

                <button
                  type="button"
                  className={form.recruit_mode === 'short' ? 'active' : ''}
                  onClick={() => setRecruitMode('short')}
                  disabled={isEdit}
                  title={isEdit ? '모임 형태는 생성 후 변경할 수 없어요.' : undefined}
                >
                  단기 모임
                </button>
              </div>

              <p className="meetup-type-help">
                {isEdit
                  ? '모임 형태는 생성 후 변경할 수 없어요.'
                  : form.recruit_mode === 'regular'
                    ? '반복적으로 진행되는 모임이에요.'
                    : '특정 날짜에 진행되는 모임이에요.'}
              </p>
            </div>

            <div className="meetup-form-section">
              <div className="meetup-field-title">
                모임 카테고리 <span>*</span>
              </div>

              <div className="meetup-category-buttons">
                {CATEGORY_OPTIONS.map((option) => (
                  <button
                    key={option.value}
                    type="button"
                    className={form.category === option.value ? 'active' : ''}
                    onClick={() => setCategory(option.value)}
                    disabled={isEdit}
                    title={isEdit ? '모임 카테고리는 생성 후 변경할 수 없어요.' : undefined}
                  >
                    {option.label}
                  </button>
                ))}
              </div>
          </div>
        </>

        <div className="meetup-form-grid two">
          <label className="meetup-field">
            <span>
              모집 제목 <b>*</b>
            </span>
            <input
              name="title"
              value={form.title}
              onChange={change}
              placeholder="예) 주말 요가 모임 같이 하실 분"
              required
            />
          </label>

          <label className="meetup-field">
            <span>
              모집 인원 <b>*</b>
            </span>
            <div className="meetup-capacity-input">
              <input
                type="number"
                name="capacity"
                min="1"
                value={form.capacity}
                onChange={change}
                required
              />
              <em>명</em>
            </div>
          </label>
        </div>

        <label className="meetup-field">
          <span>
            모집 내용 <b>*</b>
          </span>
          <textarea
            name="body"
            value={form.body}
            onChange={change}
            rows="4"
            placeholder="모임에 대해 자유롭게 소개해주세요."
            required
          />
        </label>

        <div className="meetup-form-grid two">
          <label className="meetup-field">
            <span>
              모집 마감 일시 <b>*</b>
            </span>
            <input
              type="datetime-local"
              name="recruit_end"
              value={form.recruit_end}
              onChange={change}
              required
            />
          </label>

          <div className="meetup-field">
            <span>
              진행 방식 <b>*</b>
            </span>

            <div className="meetup-segmented-control meetup-place-type">
              <button
                type="button"
                className={!form.is_online ? 'active' : ''}
                onClick={() => setPlaceType(false)}
              >
                오프라인
              </button>

              <button
                type="button"
                className={form.is_online ? 'active' : ''}
                onClick={() => setPlaceType(true)}
              >
                온라인
              </button>
            </div>
          </div>
        </div>

        {!form.is_online && (
          <div className="meetup-field meetup-place-picker">
            <span>
              장소 <b>*</b>
            </span>

            <div className="meetup-place-search-row">
              <input
                name="place"
                value={form.place}
                onChange={change}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault()
                    searchPlace()
                  }
                }}
                placeholder="예) 강남역, 스터디룸 3호실"
                required
              />

              <button
                type="button"
                className="meetup-place-search-button"
                onClick={searchPlace}
              >
                장소 검색
              </button>
            </div>

            {placeSearchStatus && (
              <p className="meetup-place-search-status">
                {placeSearchStatus}
              </p>
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

            {form.place_latitude !== '' &&
              form.place_longitude !== '' && (
                <div className="meetup-selected-place">
                  <span>선택한 장소</span>
                  <strong>{form.place}</strong>
                </div>
              )}
          </div>
        )}

        {form.recruit_mode === 'regular' && (
          <div className="meetup-form-section regular-schedule-section">
            <div className="meetup-field-title">
              정기 일정 <span>*</span>
            </div>

            <div className="meetup-regular-inline">
              <div className="meetup-weekday-buttons">
                {WEEKDAYS.map((day) => (
                  <button
                    key={day}
                    type="button"
                    className={form.regular_days.includes(day) ? 'active' : ''}
                    onClick={() => toggleRegularDay(day)}
                  >
                    {day}
                  </button>
                ))}
              </div>

              <input
                className="meetup-regular-time"
                type="time"
                name="regular_time"
                value={form.regular_time}
                onChange={change}
                required
              />
            </div>
          </div>
        )}

        {form.recruit_mode === 'short' && (
          <div className="meetup-form-grid two">
            <label className="meetup-field">
              <span>
                모임 시작 일시 <b>*</b>
              </span>
              <input
                type="datetime-local"
                name="meeting_start"
                value={form.meeting_start}
                onChange={change}
                required
              />
            </label>

            <label className="meetup-field">
              <span>
                모임 종료 일시 <b>*</b>
              </span>
              <input
                type="datetime-local"
                name="meeting_end"
                value={form.meeting_end}
                onChange={change}
                required
              />
            </label>
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
                value={form.sport_name}
                onChange={change}
                placeholder="예) 요가, 러닝, 배드민턴"
                required
              />
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
                value={form.game_name}
                onChange={change}
                placeholder="예) 리그 오브 레전드"
                required
              />
            </label>
          </div>
        )}

        {form.category === 'study' && (
          <div className="meetup-form-section compact">

            <div className="meetup-form-grid two">
              <label className="meetup-field">
                <span>
                  스터디 주제 <b>*</b>
                </span>
                <input
                  name="study_topic"
                  value={form.study_topic}
                  onChange={change}
                  placeholder="예) SQLD"
                  required
                />
              </label>

              <label className="meetup-field">
                <span>진행 기간</span>
                <input
                  name="study_period"
                  value={form.study_period}
                  onChange={change}
                  placeholder="예) 4주"
                />
              </label>
            </div>

            <label className="meetup-field">
              <span>진행 방식</span>
              <input
                name="study_method"
                value={form.study_method}
                onChange={change}
                placeholder="예) 주 2회 오프라인 문제 풀이"
              />
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
                  value={form.product_name}
                  onChange={change}
                  placeholder="예) 파이썬 교재"
                  required
                />
              </label>

              <label className="meetup-field">
                <span>
                  1인 예상 가격 <b>*</b>
                </span>
                <input
                  type="number"
                  name="estimated_price_per_person"
                  value={form.estimated_price_per_person}
                  onChange={change}
                  placeholder="예) 15000"
                  min="0"
                  required
                />
              </label>
            </div>

            <div className="meetup-form-grid two">
              <label className="meetup-field">
                <span>
                  수령 방법 <b>*</b>
                </span>
                <input
                  name="pickup_method"
                  value={form.pickup_method}
                  onChange={change}
                  placeholder="예) 오프라인 전달"
                  required
                />
              </label>

              <label className="meetup-field">
                <span>구매 링크</span>
                <input
                  name="purchase_url"
                  value={form.purchase_url}
                  onChange={change}
                  placeholder="https://..."
                />
              </label>
            </div>
          </div>
        )}

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
              {busy
                ? '저장 중...'
                : isEdit
                  ? '수정 완료'
                  : '등록하기'}
            </button>
          </div>
        </div>
      </form>
    </main>
  )
}
