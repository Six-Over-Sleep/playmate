import { EDITOR_CATEGORY_OPTIONS, WEEKDAYS } from '../../utils/meetup'

import useMeetupEditor from '../../hooks/meetup/useMeetupEditor'

// 모임 생성·수정 입력 화면
export default function MeetupEditorPage({
  meetup = null,
  busy,
  onBack,
  onSubmit,
}) {
  // 편집 훅의 폼 상태와 이벤트 연결
  const {
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
  } = useMeetupEditor({
    meetup,
    onSubmit,
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
      >
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
                disabled={isEdit}
                title={
                  isEdit
                    ? '모임 카테고리는 생성 후 변경할 수 없어요.'
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
              disabled={isEdit || isGroupBuy}
              title={
                isEdit ? '모임 형태는 생성 후 변경할 수 없어요.' : undefined
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
              disabled={isEdit || isGroupBuy}
              title={
                isEdit ? '모임 형태는 생성 후 변경할 수 없어요.' : undefined
              }
            >
              단기 모임
            </button>
          </div>

          {!isGroupBuy && (
            <p className="meetup-type-help">
              {isEdit
                ? '모임 형태는 생성 후 변경할 수 없어요.'
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

        {/* 오프라인 장소 검색과 지도 */}
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
                onKeyDown={(event) => {
                  if (event.key === 'Enter') {
                    event.preventDefault()
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
              <input
                className="meetup-regular-date"
                type="date"
                name="regular_start_date"
                value={form.regular_start_date}
                onChange={change}
                required
              />

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

        {/* 단기 모임 시작·종료 일시 입력 */}
        {!isGroupBuy && form.recruit_mode === 'short' && (
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

        {/* 선택한 카테고리별 추가 입력 항목 */}
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

                <div className="meetup-price-input">
                  <input
                    type="text"
                    name="estimated_price_per_person"
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
      </form>
    </main>
  )
}
