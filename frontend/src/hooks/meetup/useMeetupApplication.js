import { useCallback, useMemo, useRef, useState } from 'react'

import {
  EMPTY_APPLICATION_FORM,
  buildApplicationPayload,
  validateApplicationStep,
} from '../../utils/meetupApplication'

function cloneInitialForm() {
  return {
    selectedSkillIds: [],
    leaderVolunteer: false,
    directInput: {
      ...EMPTY_APPLICATION_FORM.directInput,
    },
  }
}

// 프로젝트 참여 신청 모달의 입력·단계·제출 상태를 관리함.
// 실제 API 호출 함수는 submitApplication으로 주입받아 서비스 계층과 분리함.
export default function useMeetupApplication({
  submitApplication,
  onSuccess,
}) {
  const [open, setOpen] = useState(false)
  const [step, setStep] = useState(1)
  const [form, setForm] = useState(cloneInitialForm)
  const [error, setError] = useState('')
  const [result, setResult] = useState(null)
  const [busy, setBusy] = useState(false)

  // 버튼 연타나 같은 제출 흐름의 중복 실행을 방지함.
  const submittingRef = useRef(false)

  const reset = useCallback(() => {
    setStep(1)
    setForm(cloneInitialForm())
    setError('')
    setResult(null)
    setBusy(false)
    submittingRef.current = false
  }, [])

  const openModal = useCallback(() => {
    reset()
    setOpen(true)
  }, [reset])

  const closeModal = useCallback(() => {
    if (submittingRef.current) {
      return
    }

    setOpen(false)
    reset()
  }, [reset])

  const toggleSkill = useCallback((skillId) => {
    const normalizedId = Number(skillId)

    if (!Number.isInteger(normalizedId) || normalizedId <= 0) {
      return
    }

    setForm((prev) => ({
      ...prev,
      selectedSkillIds: prev.selectedSkillIds.includes(normalizedId)
        ? prev.selectedSkillIds.filter((id) => id !== normalizedId)
        : [...prev.selectedSkillIds, normalizedId],
    }))

    setError('')
  }, [])

  const setLeaderVolunteer = useCallback((value) => {
    setForm((prev) => ({
      ...prev,
      leaderVolunteer: Boolean(value),
    }))

    setError('')
  }, [])

  const changeDirectInput = useCallback((event) => {
    const { name, value } = event.target

    setForm((prev) => ({
      ...prev,
      directInput: {
        ...prev.directInput,
        [name]: value,
      },
    }))

    setError('')
  }, [])

  const goNext = useCallback(() => {
    const validationError = validateApplicationStep(step, form)

    if (validationError) {
      setError(validationError)
      return false
    }

    setError('')
    setStep((prev) => Math.min(prev + 1, 3))
    return true
  }, [form, step])

  const goBack = useCallback(() => {
    setError('')
    setStep((prev) => Math.max(prev - 1, 1))
  }, [])

  const payload = useMemo(
    () => buildApplicationPayload(form),
    [form],
  )

  const submit = useCallback(async () => {
    if (submittingRef.current) {
      return null
    }

    const validationError = validateApplicationStep(3, form)

    if (validationError) {
      setError(validationError)
      return null
    }

    if (typeof submitApplication !== 'function') {
      setError('신청 API가 아직 연결되지 않았습니다.')
      return null
    }

    submittingRef.current = true
    setBusy(true)
    setError('')

    try {
      const response = await submitApplication(
        buildApplicationPayload(form),
      )

      setResult(response ?? null)

      await onSuccess?.(response ?? null)

      return response ?? null
    } catch (err) {
      setError(
        err?.message ||
          '신청을 처리하지 못했습니다. 입력 내용을 확인해주세요.',
      )

      return null
    } finally {
      submittingRef.current = false
      setBusy(false)
    }
  }, [form, onSuccess, submitApplication])

  return {
    open,
    step,
    form,
    error,
    result,
    busy,
    payload,

    openModal,
    closeModal,
    reset,

    toggleSkill,
    setLeaderVolunteer,
    changeDirectInput,

    goNext,
    goBack,
    submit,

    setError,
    setStep,
  }
}
