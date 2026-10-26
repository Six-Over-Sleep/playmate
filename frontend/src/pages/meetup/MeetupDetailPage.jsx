import MeetupApplicationModal from '../../components/meetup/MeetupApplicationModal'
import MeetupCommentList from '../../components/meetup/MeetupCommentList'
import MeetupExtensionModal from '../../components/meetup/MeetupExtensionModal'
import MeetupMemberList from '../../components/meetup/MeetupMemberList'
import useMeetupApplication from '../../hooks/meetup/useMeetupApplication'
import useMeetupExtension from '../../hooks/meetup/useMeetupExtension'
import {
  formatDateOnly,
  formatDateTime,
  getCategoryMeta,
  getMeetingSchedule,
  getMeetingType,
  getMeetupStatus,
  getLifecycleStatus,
  getPlace,
  getRequiredSkills,
  isMissingSkill,
  normalizeCategory,
} from '../../utils/meetup'

function getApplicationLabel(status) {
  switch (String(status ?? '').toUpperCase()) {
    case 'ACCEPTED':
      return '참여 확정'
    case 'WAITING':
      return '대기 중'
    case 'CANCELED':
      return '신청 취소'
    case 'LEFT':
      return '중도이탈'
    default:
      return ''
  }
}

function getStudyTypeLabel(value) {
  switch (String(value ?? '').toUpperCase()) {
    case 'TECHNOLOGY':
      return '기술 공부'
    case 'CERTIFICATE':
      return '자격증'
    default:
      return value || ''
  }
}

function getDifficultyLabel(value) {
  switch (String(value ?? '').toUpperCase()) {
    case 'BEGINNER':
      return '기초'
    case 'ADVANCED':
      return '심화'
    default:
      return value || ''
  }
}

function getLifecycleDescription(meetup) {
  switch (getLifecycleStatus(meetup)) {
    case 'RECRUITING':
      return '모집 중입니다. 시작 조건 충족 여부는 서버의 최신 참여 구성으로 판단합니다.'
    case 'READY':
      return '시작 조건을 충족했지만 아직 예정 시작 시각 전입니다.'
    case 'IN_PROGRESS':
      return '예정 시작 시각이 지나 현재 모임이 진행 중입니다.'
    case 'COMPLETED':
      return '예정 운영이 정상 완료된 상태입니다.'
    case 'ABORTED':
      return '진행 중 중도 종료된 모임입니다. 정상 완료와 구분됩니다.'
    case 'CANCELED':
    case 'CANCELLED':
      return '취소된 모임입니다. 기존 참여·신청 이력은 별도로 유지됩니다.'
    default:
      return ''
  }
}

function getJoinRestrictionMessage(meetup, canJoin, hasActiveApplication) {
  if (canJoin || hasActiveApplication) return ''

  const eligibility = meetup?.my_eligibility || {}
  const permissions = meetup?.permissions || {}

  if (
    eligibility.is_restricted === true ||
    eligibility.reason_code === 'THREE_WITHDRAWALS'
  ) {
    return '모임 시작 후 중도이탈이 누적 3회 이상이면 이후 모든 종류의 모임에 새로 신청할 수 없습니다. 시작 전 신청 취소는 집계하지 않으며, 제한 전에 접수된 유효 신청은 유지됩니다.'
  }

  return (
    permissions.join_restriction_reason ??
    permissions.join_block_reason ??
    meetup?.join_restriction_reason ??
    meetup?.application_restriction_reason ??
    meetup?.restriction_reason ??
    '현재 서버 기준으로 이 모임에 새로 신청할 수 없습니다.'
  )
}

// 모임 상세 정보와 참여·관리·좋아요·스크랩 버튼, 댓글 표시
export default function MeetupDetailPage({
  meetup,
  members = [],
  memberCount,
  joined = false,
  busy = false,
  actionMessage = '',
  onBack,
  onEdit,
  onDelete,
  onJoin,
  onCancelJoin,
  onExtendProject,
  onChooseExceptionStart,
  onCancelProject,
  onEndEarly,
  onLike,
  onScrap,
  comments = [],
  onAddComment,
  onEditComment,
  onDeleteComment,
}) {
  const application = useMeetupApplication({
    submitApplication: async (payload) => {
      if (typeof onJoin !== 'function') {
        throw new Error('프로젝트 신청 기능이 연결되지 않았습니다.')
      }

      return onJoin(payload)
    },
  })

  const extension = useMeetupExtension({
    meetup,
    submitExtension: onExtendProject,
  })

  if (!meetup) {
    return (
      <main className="meetup-detail-page">
        <div className="meetup-detail-loading">
          모임 정보를 불러오는 중이에요.
        </div>
      </main>
    )
  }

  const category = getCategoryMeta(meetup.category)
  const normalizedCategory = normalizeCategory(meetup.category)
  const detail = meetup?.detail || {}

  const isProject = normalizedCategory === 'project'
  const isStudy = normalizedCategory === 'study'
  const isProjectOrStudy = isProject || isStudy

  // 상세 응답의 participant_count를 우선 사용함.
  // 아직 이전 API를 사용하는 화면을 위해 memberCount와 기존 필드도 보조로 유지함.
  const currentCount =
    meetup.participant_count ??
    memberCount ??
    meetup.member_count ??
    meetup.current_count ??
    meetup.joined_count ??
    members.length ??
    0

  const capacity = meetup.capacity ?? '-'
  const status = getMeetupStatus(meetup, currentCount)
  const lifecycleDescription = getLifecycleDescription(meetup)

  const ownerId =
    meetup.creator_member_id ??
    meetup.owner_id ??
    meetup.member_id ??
    meetup.created_by ??
    meetup.writer_id

  const permissions = meetup?.permissions || {}
  const hasPermissionContract =
    meetup?.permissions != null &&
    typeof meetup.permissions === 'object'
  const myApplication = meetup?.my_application || null

  const applicationStatus = String(
    myApplication?.application_status ?? '',
  ).toUpperCase()

  const applicationLabel = getApplicationLabel(applicationStatus)

  // 새 계약에서는 서버가 my_application과 permissions로 최종 상태를 결정함.
  // joined는 기존 API와의 호환을 위해 my_application이 없을 때만 보조로 사용함.
  const isAccepted =
    applicationStatus === 'ACCEPTED' ||
    (!myApplication && joined)

  const isWaiting = applicationStatus === 'WAITING'

  const hasActiveApplication = isAccepted || isWaiting

  const supportsWaiting = isProjectOrStudy

  const legacyCanJoin =
    !myApplication &&
    !joined &&
    (
      status.className === 'open' ||
      (supportsWaiting && ['full', 'ready'].includes(status.className))
    )

  const canJoin = hasPermissionContract
    ? permissions.can_join === true
    : legacyCanJoin

  const canWithdraw =
    permissions.can_withdraw === true

  const canCancelJoin = hasPermissionContract
    ? (
        permissions.can_cancel_join === true ||
        canWithdraw
      )
    : hasActiveApplication

  const canEdit = hasPermissionContract
    ? permissions.can_edit === true
    : Boolean(onEdit)

  // 기존 onDelete는 게시글 논리 삭제용이다.
  // 프로젝트 운영 취소는 permissions.can_cancel_project + 전용 POST /cancel을 사용한다.
  const canDelete = Boolean(onDelete)

  // 팀장 전용 작업은 서버 permissions가 true인 경우에만 표시한다.
  const canExtendProject =
    permissions.can_extend === true

  const canChooseExceptionStart =
    permissions.can_choose_exception_start === true

  const canCancelProject =
    permissions.can_cancel_project === true

  const canEndEarly =
    permissions.can_end_early === true

  const requiredSkills = isProject
    ? getRequiredSkills(meetup)
    : []

  const minimumParticipants =
    meetup.minimum_participants ??
    (isProjectOrStudy ? 2 : null)

  const waitingCount = Number(meetup.waiting_count ?? 0)

  const creatorType = String(
    meetup.creator_type ?? '',
  ).toUpperCase()

  const creatorTypeLabel =
    creatorType === 'ADMIN'
      ? '관리자 생성'
      : creatorType === 'USER'
        ? '사용자 생성'
        : ''

  const teamLeader =
    meetup.team_leader ??
    meetup.leader ??
    null

  const teamLeaderId =
    meetup.leader_member_id ??
    meetup.team_leader_id ??
    teamLeader?.member_id ??
    teamLeader?.id ??
    null

  const teamLeaderName =
    teamLeader?.display_name ??
    teamLeader?.nickname ??
    teamLeader?.name ??
    ''

  const teamLeaderDisplay =
    teamLeaderName ||
    (teamLeaderId != null
      ? `회원 #${teamLeaderId}`
      : '아직 미정')

  const joinRestrictionMessage = getJoinRestrictionMessage(
    meetup,
    canJoin,
    hasActiveApplication,
  )

  const isSingleParticipantInProgress =
    isProject &&
    getLifecycleStatus(meetup) === 'IN_PROGRESS' &&
    Number(currentCount) === 1

  const joinButtonLabel = (() => {
    if (busy) {
      return '처리 중...'
    }

    if (!canJoin) {
      return status.label
    }

    if (
      supportsWaiting &&
      Number(capacity) > 0 &&
      Number(currentCount) >= Number(capacity)
    ) {
      return '대기 신청'
    }

    return '참여하기'
  })()

  const handleJoinClick = () => {
    if (!canJoin || busy) {
      return
    }

    if (isProject) {
      application.openModal()
      return
    }

    onJoin?.()
  }

  return (
    <main className="meetup-detail-page">
      <button
        type="button"
        className="meetup-back-button"
        onClick={onBack}
      >
        ← 목록으로
      </button>

      <article className="meetup-detail-card">
        <div className="meetup-detail-top">
          <div className="meetup-detail-badges">
            <span className="meetup-category-badge">
              {category.icon} {category.label}
            </span>

            <span className="meetup-mode-badge">
              {getMeetingType(meetup)}
            </span>

            {meetup.deadline_at && (
              <span className="meetup-deadline-text">
                · {formatDateTime(meetup.deadline_at)} 모집 마감
              </span>
            )}
          </div>

          <span className={`meetup-status ${status.className}`}>
            {status.label}
          </span>
        </div>

        <h1>{meetup.title || '제목 없는 모임'}</h1>

        {lifecycleDescription && (
          <div className="meetup-lifecycle-note">
            <strong>{status.label}</strong>
            <span>{lifecycleDescription}</span>
          </div>
        )}

        <div className="meetup-summary-grid">
          <div className="meetup-summary-item">
            <span>일시</span>
            <strong>{getMeetingSchedule(meetup)}</strong>
          </div>

          <div className="meetup-summary-item">
            <span>장소</span>
            <strong>{getPlace(meetup)}</strong>
          </div>

          <div className="meetup-summary-item">
            <span>확정 인원</span>
            <strong className="meetup-capacity-value">
              {currentCount} / {capacity}명
            </strong>
          </div>
        </div>

        <div className="meetup-detail-body">
          {meetup.body || '등록된 모임 설명이 없습니다.'}
        </div>

        {/* 좋아요 수·여부와 스크랩 여부는 서버 응답 값을 그대로 표시함. */}
        <div className="meetup-action-buttons meetup-reaction-buttons">
          <button
            type="button"
            className={
              meetup.liked_by_me
                ? 'meetup-join-button'
                : 'meetup-cancel-button'
            }
            aria-pressed={Boolean(meetup.liked_by_me)}
            onClick={onLike}
            disabled={busy}
          >
            {meetup.liked_by_me ? '♥' : '♡'} 좋아요{' '}
            {meetup.like_count ?? 0}
          </button>

          <button
            type="button"
            className={
              meetup.scrapped_by_me
                ? 'meetup-join-button'
                : 'meetup-cancel-button'
            }
            aria-pressed={Boolean(meetup.scrapped_by_me)}
            onClick={onScrap}
            disabled={busy}
          >
            {meetup.scrapped_by_me ? '스크랩됨' : '스크랩'}
          </button>
        </div>

        {/* 프로젝트·스터디 전체 운영 정보 */}
        {isProjectOrStudy && (
          <section className="meetup-extra-section">
            <h2>운영 정보</h2>

            <div className="meetup-extra-grid">
              <div className="meetup-extra-item">
                <span className="meetup-extra-label">
                  전체 시작
                </span>
                <span className="meetup-extra-value">
                  {meetup.starts_at
                    ? formatDateTime(meetup.starts_at)
                    : '미입력'}
                </span>
              </div>

              <div className="meetup-extra-item">
                <span className="meetup-extra-label">
                  전체 종료
                </span>
                <span className="meetup-extra-value">
                  {meetup.ends_at
                    ? formatDateTime(meetup.ends_at)
                    : '미입력'}
                </span>
              </div>

              {minimumParticipants != null && (
                <div className="meetup-extra-item">
                  <span className="meetup-extra-label">
                    시작 최소 인원
                  </span>
                  <span className="meetup-extra-value">
                    {minimumParticipants}명
                  </span>
                </div>
              )}

              <div className="meetup-extra-item">
                <span className="meetup-extra-label">
                  대기 인원
                </span>
                <span className="meetup-extra-value">
                  {waitingCount}명
                </span>
              </div>

              {creatorTypeLabel && (
                <div className="meetup-extra-item">
                  <span className="meetup-extra-label">
                    개설 유형
                  </span>
                  <span className="meetup-extra-value">
                    {creatorTypeLabel}
                  </span>
                </div>
              )}

              {isProject && (
                <div className="meetup-extra-item">
                  <span className="meetup-extra-label">
                    프로젝트 팀장
                  </span>
                  <span className="meetup-extra-value">
                    {teamLeaderDisplay}
                  </span>
                </div>
              )}
            </div>
          </section>
        )}

        {/* 프로젝트 필수 기술 구성 */}
        {isProject && (
          <section className="meetup-extra-section">
            <h2>프로젝트 참여 구성</h2>

            {requiredSkills.length > 0 ? (
              <div className="meetup-card-skills">
                {requiredSkills.map((skill) => {
                  const skillId =
                    skill?.skill_id ??
                    skill?.id ??
                    skill

                  const skillName =
                    skill?.name ??
                    skill?.skill_name ??
                    String(skill)

                  const missing = isMissingSkill(
                    meetup,
                    skill,
                  )

                  return (
                    <span
                      key={skillId}
                      className={[
                        'meetup-skill-chip',
                        missing
                          ? 'meetup-skill-missing'
                          : 'meetup-skill-filled',
                      ]
                        .filter(Boolean)
                        .join(' ')}
                    >
                      {skillName} ·{' '}
                      {missing
                        ? '모집 중'
                        : `충족${
                            skill?.confirmed_member_count != null
                              ? ` ${skill.confirmed_member_count}명`
                              : ''
                          }`}
                    </span>
                  )
                })}
              </div>
            ) : (
              <div className="meetup-member-empty">
                등록된 필수 기술 정보가 없습니다.
              </div>
            )}

            <p className="meetup-type-help">
              프로젝트는 확정 참여자 최소 {minimumParticipants ?? 2}명과
              필수 기술 구성이 모두 충족되어야 정상 시작할 수 있어요.
              최종 확정·대기 판단은 서버 결과를 따릅니다.
            </p>
          </section>
        )}

        {isProject && (
          <section className="meetup-extra-section">
            <h2>프로젝트 운영 안내</h2>

            <div className="meetup-project-policy">
              <p>
                모집은 예정 시작 24시간 전에 마감됩니다.
              </p>
              <p>
                조건이 부족하면 팀장이 최대 2회 연장할 수 있고, 매번
                변경 전 시작일 다음 날부터 14일 이내의 날짜를 선택합니다.
              </p>
              <p>
                2회 연장 후 마지막 모집이 마감돼도 필수 기술이 부족한 경우,
                최소 2명의 확정 참여자가 있으면 팀장이 현재 구성으로
                시작하거나 프로젝트를 취소할 수 있습니다.
              </p>
              <p>
                시작 시각까지 정상 시작 조건을 충족하지 못하고 유효한
                예외 시작 결정도 없으면 프로젝트는 자동 취소됩니다.
              </p>
            </div>

            {(canExtendProject ||
              canChooseExceptionStart ||
              canCancelProject ||
              canEndEarly) && (
              <div className="meetup-project-action-panel">
                <div>
                  <strong>팀장 운영 메뉴</strong>
                  <span>
                    서버가 허용한 작업만 표시합니다. 날짜·권한·최종 상태는
                    서버가 다시 검증합니다.
                  </span>
                </div>

                <div className="meetup-project-action-buttons">
                  {canExtendProject && (
                    <button
                      type="button"
                      onClick={extension.openModal}
                      disabled={busy}
                    >
                      일정 연장
                    </button>
                  )}

                  {canChooseExceptionStart && (
                    <button
                      type="button"
                      onClick={onChooseExceptionStart}
                      disabled={busy}
                    >
                      현재 구성으로 시작
                    </button>
                  )}

                  {canCancelProject && (
                    <button
                      type="button"
                      className="danger"
                      onClick={onCancelProject}
                      disabled={busy}
                    >
                      프로젝트 취소
                    </button>
                  )}
                </div>
              </div>
            )}

            {isSingleParticipantInProgress && canEndEarly && (
              <div className="meetup-solo-action-panel">
                <div>
                  <strong>현재 확정 참여자가 1명 남았습니다.</strong>
                  <span>
                    별도 조작 없이 혼자 계속 진행할 수 있습니다.
                    종료하려면 아래 중도 종료를 선택해주세요.
                    중도 종료는 정상 완료와 구분됩니다.
                  </span>
                </div>

                <div className="meetup-project-action-buttons">
                  <button
                    type="button"
                    className="danger"
                    onClick={onEndEarly}
                    disabled={busy}
                  >
                    모임 중도 종료
                  </button>
                </div>
              </div>
            )}
          </section>
        )}

        {/* 시작일과 기존 카테고리별 상세 정보 */}
        <section className="meetup-extra-section">
          <h2>모임 상세 정보</h2>

          <div className="meetup-extra-grid">
            <div className="meetup-extra-item">
              <span className="meetup-extra-label">시작일</span>
              <span className="meetup-extra-value">
                {String(
                  meetup.recruit_mode ?? '',
                ).toLowerCase() === 'short'
                  ? meetup.meeting_start
                    ? formatDateTime(meetup.meeting_start)
                    : '미입력'
                  : meetup.regular_start_date
                    ? formatDateOnly(meetup.regular_start_date)
                    : '미입력'}
              </span>
            </div>

            {['sports', 'sport', 'exercise'].includes(
              String(meetup.category ?? '').toLowerCase(),
            ) &&
              detail.sport_name && (
                <div className="meetup-extra-item">
                  <span className="meetup-extra-label">
                    종목
                  </span>
                  <span className="meetup-extra-value">
                    {detail.sport_name}
                  </span>
                </div>
              )}

            {['game', 'gaming'].includes(
              String(meetup.category ?? '').toLowerCase(),
            ) &&
              detail.game_name && (
                <div className="meetup-extra-item">
                  <span className="meetup-extra-label">
                    게임명
                  </span>
                  <span className="meetup-extra-value">
                    {detail.game_name}
                  </span>
                </div>
              )}

            {isStudy && (
              <>
                <div className="meetup-extra-item">
                  <span className="meetup-extra-label">
                    스터디 종류
                  </span>
                  <span className="meetup-extra-value">
                    {getStudyTypeLabel(detail.study_type) ||
                      '미입력'}
                  </span>
                </div>

                {detail.study_type !== 'CERTIFICATE' && (
                  <div className="meetup-extra-item">
                    <span className="meetup-extra-label">
                      난이도
                    </span>
                    <span className="meetup-extra-value">
                      {getDifficultyLabel(detail.difficulty) ||
                        '미입력'}
                    </span>
                  </div>
                )}

                <div className="meetup-extra-item">
                  <span className="meetup-extra-label">
                    스터디 기간
                  </span>
                  <span className="meetup-extra-value">
                    {detail.study_period?.trim() || '미입력'}
                  </span>
                </div>

                {detail.study_topic && (
                  <div className="meetup-extra-item">
                    <span className="meetup-extra-label">
                      스터디 주제
                    </span>
                    <span className="meetup-extra-value">
                      {detail.study_topic}
                    </span>
                  </div>
                )}

                {detail.study_method && (
                  <div className="meetup-extra-item full">
                    <span className="meetup-extra-label">
                      진행 방법
                    </span>
                    <span className="meetup-extra-value">
                      {detail.study_method}
                    </span>
                  </div>
                )}
              </>
            )}

            {['group_buy', 'groupbuy', 'purchase'].includes(
              String(meetup.category ?? '').toLowerCase(),
            ) && (
              <>
                {detail.product_name && (
                  <div className="meetup-extra-item">
                    <span className="meetup-extra-label">
                      상품명
                    </span>
                    <span className="meetup-extra-value">
                      {detail.product_name}
                    </span>
                  </div>
                )}

                {detail.estimated_price_per_person != null && (
                  <div className="meetup-extra-item">
                    <span className="meetup-extra-label">
                      예상 1인 가격
                    </span>
                    <span className="meetup-extra-value">
                      {Number(
                        detail.estimated_price_per_person,
                      ).toLocaleString()}
                      원
                    </span>
                  </div>
                )}

                {detail.pickup_method && (
                  <div className="meetup-extra-item">
                    <span className="meetup-extra-label">
                      수령 방법
                    </span>
                    <span className="meetup-extra-value">
                      {detail.pickup_method}
                    </span>
                  </div>
                )}

                {detail.purchase_url && (
                  <div className="meetup-extra-item">
                    <span className="meetup-extra-label">
                      구매 링크
                    </span>
                    <span className="meetup-extra-value">
                      <a
                        href={detail.purchase_url}
                        target="_blank"
                        rel="noreferrer"
                        onClick={(event) =>
                          event.stopPropagation()
                        }
                      >
                        {detail.purchase_url}
                      </a>
                    </span>
                  </div>
                )}
              </>
            )}
          </div>
        </section>

        {/* 본인의 프로젝트·스터디 신청 상태 */}
        {isProjectOrStudy && myApplication && (
          <section className="meetup-extra-section">
            <h2>내 신청 상태</h2>

            <div className="meetup-extra-grid">
              <div className="meetup-extra-item">
                <span className="meetup-extra-label">
                  신청 상태
                </span>
                <span className="meetup-extra-value">
                  {applicationLabel || applicationStatus}
                </span>
              </div>

              {Array.isArray(myApplication.skill_ids) &&
                myApplication.skill_ids.length > 0 && (
                  <div className="meetup-extra-item">
                    <span className="meetup-extra-label">
                      담당 기술 수
                    </span>
                    <span className="meetup-extra-value">
                      {myApplication.skill_ids.length}개
                    </span>
                  </div>
                )}

              {isWaiting && (
                <div className="meetup-extra-item full">
                  <span className="meetup-extra-label">
                    대기 안내
                  </span>
                  <span className="meetup-extra-value">
                    신청은 정상 접수되었습니다. 확정 여부와
                    승격 결과는 서버의 최신 신청 상태를 기준으로
                    표시합니다.
                  </span>
                </div>
              )}
            </div>
          </section>
        )}

        {joinRestrictionMessage && !myApplication && (
          <section className="meetup-extra-section">
            <h2>신청 안내</h2>

            <div className="meetup-join-restriction">
              <strong>신규 신청이 제한되어 있습니다.</strong>
              <span>{joinRestrictionMessage}</span>
              <small>
                프론트는 중도이탈 횟수나 제한 여부를 직접 계산하지 않고
                서버의 신청 가능 상태를 따릅니다.
              </small>
            </div>
          </section>
        )}

        {/* 참여 멤버 목록에는 확정 참여자만 전달함. 대기자는 서버 배열에 섞지 않음. */}
        <MeetupMemberList
          members={members}
          currentCount={currentCount}
          ownerId={ownerId}
          teamLeaderId={teamLeaderId}
          requiredSkills={requiredSkills}
        />

        {actionMessage && (
          <div className="meetup-action-message">
            {actionMessage}
          </div>
        )}

        {/* 수정·모임 취소 및 신청·신청 취소 */}
        <footer className="meetup-detail-footer">
          {(canEdit || canDelete) && (
            <div className="meetup-owner-actions">
              {canEdit && onEdit && (
                <button
                  type="button"
                  onClick={onEdit}
                >
                  수정
                </button>
              )}

              {canDelete && (
                <button
                  type="button"
                  className="delete"
                  onClick={onDelete}
                >
                  삭제
                </button>
              )}
            </div>
          )}

          {/* 모임장은 생성 시 이미 참여 중이므로 참여·취소 대신 모임장 표시 */}
          <div className="meetup-action-buttons">
            {meetup.is_host ? (
              <span className="meetup-host-badge">모임장</span>
            ) : hasActiveApplication ? (
              <button
                type="button"
                className="meetup-cancel-button"
                onClick={onCancelJoin}
                disabled={busy || !canCancelJoin}
              >
                {busy
                  ? '처리 중...'
                  : isWaiting
                    ? '대기 신청 취소'
                    : canWithdraw
                      ? '중도이탈'
                      : '참여 취소'}
              </button>
            ) : (
              <button
                type="button"
                className="meetup-join-button"
                onClick={handleJoinClick}
                disabled={busy || !canJoin}
              >
                {joinButtonLabel}
              </button>
            )}
          </div>
        </footer>

        {/* 댓글·대댓글 목록과 입력창 */}
        <MeetupCommentList
          comments={comments}
          busy={busy}
          onAdd={onAddComment}
          onEdit={onEditComment}
          onDelete={onDeleteComment}
        />
      </article>

      {isProject && (
        <>
          <MeetupApplicationModal
            meetup={meetup}
            application={application}
          />

          <MeetupExtensionModal
            meetup={meetup}
            extension={extension}
          />
        </>
      )}
    </main>
  )
}
