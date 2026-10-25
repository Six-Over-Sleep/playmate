import { useCallback, useEffect, useRef, useState } from 'react'
import { boardApi } from '../../services/boardApi'

/**
 * 게시판의 조회·화면 전환·변경 흐름을 관리한다.
 * 목록은 이 인스턴스의 현재 검색 결과만 재사용하고 변경 후 무효화한다.
 * 요청 순번으로 늦은 응답을 무시하고 전환 조회는 언마운트 시 취소한다.
 * 초기 조회는 effect의 구독만 해제해 StrictMode의 재구독에서도 응답을 재사용한다.
 */
export function useBoard(resetVersion) {
  const [boards, setBoards] = useState([])
  const [board, setBoard] = useState(null)
  const [posts, setPosts] = useState([])
  const [post, setPost] = useState(null)
  const [comments, setComments] = useState([])
  const [view, setView] = useState('list')
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(true)
  const [detailLoading, setDetailLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [modal, setModal] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [initialized, setInitialized] = useState(false)
  const initialRequest = useRef(null)
  const mounted = useRef(false)
  const mutationLock = useRef(false)
  const listRequest = useRef({ id: 0, controller: null })
  const detailRequest = useRef({ id: 0, controller: null })
  const currentList = useRef(null)
  const dirty = useRef(false)
  const notificationTimer = useRef(null)
  const previousReset = useRef(resetVersion)

  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
      listRequest.current.controller?.abort()
      detailRequest.current.controller?.abort()
      clearTimeout(notificationTimer.current)
    }
  }, [])

  useEffect(() => {
    let active = true
    // StrictMode의 setup/cleanup/setup은 같은 진행 중 초기 조회를 구독한다.
    // 전역 캐시가 아니므로 실제 재진입·다른 로그인 사용자의 데이터는 공유하지 않는다.
    if (!initialRequest.current) {
      initialRequest.current = boardApi.boards()
    }
    initialRequest.current.then((items) => {
      if (!active) return
      const firstBoard = items[0] || null
      // 게시판은 도착 즉시 표시한다. 글 조회는 공통 흐름에 맡겨 전환·저장 시 취소한다.
      setBoards(items)
      setBoard(firstBoard)
      setInitialized(true)
      if (firstBoard) loadPosts(firstBoard)
      else setLoading(false)
    }).catch((cause) => {
      if (active) {
        setError(cause.message)
        setPosts(null)
        setLoading(false)
        setInitialized(true)
      }
    })
    return () => { active = false }
  }, [])

  /** 새 검색은 이전 조회를 취소하고 응답·오류·로딩 모두 최신 요청만 반영한다. */
  const loadPosts = useCallback(async function loadPostList(target, search = '') {
    if (!target) return
    const pending = listRequest.current
    // 같은 목록을 기다리는 동안 메뉴·검색을 반복해도 요청을 추가하지 않는다.
    if (pending.pending && pending.boardId === target.id && pending.query === search) return
    listRequest.current.controller?.abort()
    const controller = new AbortController()
    const id = listRequest.current.id + 1
    listRequest.current = { id, controller, boardId: target.id, query: search, pending: true }
    setLoading(true)
    setError('')
    try {
      const items = await boardApi.posts(target.id, search, { signal: controller.signal })
      if (!mounted.current || id !== listRequest.current.id) return
      setPosts(items)
      currentList.current = { boardId: target.id, query: search, items }
      dirty.current = false
    } catch (cause) {
      if (mounted.current && id === listRequest.current.id && cause.name !== 'AbortError') {
        setPosts(null)
        currentList.current = null
        setError(cause.message)
      }
    } finally {
      if (mounted.current && id === listRequest.current.id) {
        listRequest.current.pending = false
        setLoading(false)
      }
    }
  }, [])

  /** 다른 화면으로 이동하면 이전 상세 조회가 나중에 화면을 되돌리지 못하게 한다. */
  function cancelDetail() {
    detailRequest.current.controller?.abort()
    detailRequest.current.id += 1
    setDetailLoading(false)
  }

  /** 저장 전 목록 응답이 변경 후의 무효화 상태를 되돌리지 못하게 취소·순번을 갱신한다. */
  function cancelList() {
    listRequest.current.controller?.abort()
    listRequest.current = { id: listRequest.current.id + 1, controller: null }
    setLoading(false)
  }

  /** 목록으로 돌아가며 저장·조회 실패로 기존 목록이 무효할 때만 현재 검색을 재조회한다. */
  function backToList() {
    if (mutationLock.current) return
    cancelDetail()
    setView('list')
    if (dirty.current || posts === null) loadPosts(board, query)
  }

  useEffect(() => {
    if (previousReset.current === resetVersion) return
    previousReset.current = resetVersion
    backToList()
  }, [resetVersion])

  /** 같은 게시판의 정상 목록은 재사용하고, 실패·검색·변경 상태에서는 다시 조회한다. */
  function selectBoard(target) {
    if (mutationLock.current) return
    cancelDetail()
    setBoard(target)
    setQuery('')
    setPost(null)
    setComments([])
    setView('list')
    setError('')
    const cached = currentList.current
    if (cached?.boardId === target.id && cached.query === '' && !dirty.current) {
      cancelList()
      setPosts(cached.items)
      setLoading(false)
      return
    }
    setPosts([])
    loadPosts(target)
  }

  /** 검색어를 확정하고 같은 정상 결과는 재사용한다. 다른 검색은 최신 요청으로 교체한다. */
  function searchPosts(value) {
    if (mutationLock.current) return
    // 상세 로딩 중에도 검색할 수 있으므로 검색 역시 상세 화면 전환을 무효화한다.
    cancelDetail()
    setError('')
    const search = value.trim()
    const cached = currentList.current
    setQuery(search)
    if (cached?.boardId === board?.id && cached.query === search && !dirty.current) {
      cancelList()
      setPosts(cached.items)
      setLoading(false)
      return
    }
    loadPosts(board, search)
  }

  /** 상세와 댓글은 병렬 조회하되 선택이 바뀌면 이전 결과를 폐기한다. */
  async function openPost(item) {
    if (mutationLock.current) return
    cancelDetail()
    const controller = new AbortController()
    const id = detailRequest.current.id
    detailRequest.current.controller = controller
    setDetailLoading(true)
    setError('')
    try {
      const [detail, replies] = await Promise.all([
        boardApi.post(board.id, item.id, { signal: controller.signal }),
        boardApi.comments(board.id, item.id, { signal: controller.signal }),
      ])
      if (!mounted.current || id !== detailRequest.current.id) return
      setPost(detail)
      setComments(replies)
      setView('detail')
    } catch (cause) {
      if (mounted.current && id === detailRequest.current.id && cause.name !== 'AbortError') {
        setError(cause.message)
      }
    } finally {
      if (mounted.current && id === detailRequest.current.id) setDetailLoading(false)
    }
  }

  /** 성공 메시지를 일정 시간 표시한다. 이전 타이머를 정리해 새 메시지가 일찍 지워지지 않게 한다. */
  function notify(message) {
    clearTimeout(notificationTimer.current)
    setSuccess(message)
    notificationTimer.current = setTimeout(() => {
      if (mounted.current) setSuccess('')
    }, 2500)
  }

  /**
   * 동기 ref 잠금으로 같은 렌더 사이의 연속 제출도 막는다.
   * 성공 객체/true와 실패 null을 반환해 폼이 성공한 경우에만 입력을 지우게 한다.
   * 변경 성공 후에는 GET을 하지 않고 응답을 반영해 재시도로 인한 중복 생성을 피한다.
   */
  async function mutate(task, applyResult) {
    if (mutationLock.current) return null
    mutationLock.current = true
    setBusy(true)
    setError('')
    try {
      const result = await task()
      if (mounted.current) applyResult(result)
      return result ?? true
    } catch (cause) {
      if (mounted.current) setError(cause.message)
      return null
    } finally {
      mutationLock.current = false
      if (mounted.current) setBusy(false)
    }
  }

  /** 생성 입력을 전송하고 반환된 게시판을 선택한다. 성공 응답 또는 실패 null을 폼에 돌려준다. */
  function createBoard(payload) {
    // 게시판 목록 수신까지만 기다린다. 진행 중인 글 조회는 생성 성공 시 취소한다.
    if (!initialized) return null
    return mutate(() => boardApi.createBoard(payload), (created) => {
      // 모달을 열기 전에 시작한 검색이 새 게시판의 빈 목록을 덮지 않게 한다.
      cancelList()
      setBoards((items) => [...items, created])
      setBoard(created)
      setQuery('')
      setPosts([])
      setPost(null)
      setComments([])
      setView('list')
      setModal(false)
      currentList.current = { boardId: created.id, query: '', items: [] }
      dirty.current = false
      notify('게시판을 만들었습니다.')
    })
  }

  /** 작성·수정을 현재 post 유무로 구분한다. 성공 시 상세를 표시하고 목록은 복귀 때 갱신한다. */
  function savePost(payload) {
    const editing = Boolean(post)
    return mutate(
      () => editing
        ? boardApi.updatePost(board.id, post.id, payload)
        : boardApi.createPost(board.id, payload),
      (saved) => {
        cancelList()
        setPost(saved)
        if (!editing) setComments([])
        dirty.current = true
        setView('detail')
        notify(editing ? '게시글을 수정했습니다.' : '게시글을 등록했습니다.')
      },
    )
  }

  /** 확인 후 현재 글을 삭제하고 목록에서 제거한다. 취소·실패 시 기존 상세를 유지한다. */
  function deletePost() {
    if (mutationLock.current || !window.confirm('이 글을 삭제할까요?')) return null
    return mutate(() => boardApi.deletePost(board.id, post.id), () => {
      setPosts((items) => Array.isArray(items) ? items.filter((item) => item.id !== post.id) : items)
      if (currentList.current) {
        currentList.current.items = currentList.current.items.filter((item) => item.id !== post.id)
      }
      setPost(null)
      setComments([])
      setView('list')
      // 이전 작성·수정으로 검색 결과가 달라졌을 때만 목록을 새로 가져온다.
      if (dirty.current || posts === null) loadPosts(board, query)
    })
  }

  /**
   * 좋아요 상태에 맞춰 등록·취소를 보내고 서버가 돌려준 개수·여부로 상세를 갱신한다.
   * 목록 카드도 like_count를 표시하므로 댓글 수처럼 목록 상태를 함께 맞춘다.
   */
  function toggleLike() {
    return mutate(
      () => post.liked_by_me
        ? boardApi.unlikePost(board.id, post.id)
        : boardApi.likePost(board.id, post.id),
      (result) => {
        const changes = { like_count: result.like_count, liked_by_me: result.liked_by_me }
        setPost((current) => ({ ...current, ...changes }))
        setPosts((current) => Array.isArray(current)
          ? current.map((item) => item.id === post.id ? { ...item, ...changes } : item)
          : current)
        if (currentList.current) {
          currentList.current.items = currentList.current.items.map((item) => (
            item.id === post.id ? { ...item, ...changes } : item
          ))
        }
      },
    )
  }

  /** 스크랩 상태에 맞춰 등록·취소를 보내고 서버가 돌려준 여부로 상세를 갱신한다. */
  function toggleScrap() {
    return mutate(
      () => post.scrapped_by_me
        ? boardApi.unscrapPost(board.id, post.id)
        : boardApi.scrapPost(board.id, post.id),
      (result) => setPost((current) => ({ ...current, scrapped_by_me: result.scrapped_by_me })),
    )
  }

  /**
   * 댓글 변경 응답으로 상세와 목록의 개수를 함께 갱신해 상세/댓글 재조회를 없앤다.
   * 삭제된 부모 자리표시(is_deleted)는 서버 comment_count처럼 개수에서 뺀다.
   */
  function applyComments(items) {
    const count = items.filter((item) => !item.is_deleted).length
    setComments(items)
    setPost((current) => ({ ...current, comment_count: count }))
    setPosts((current) => Array.isArray(current)
      ? current.map((item) => item.id === post.id ? { ...item, comment_count: count } : item)
      : current)
    if (currentList.current) {
      currentList.current.items = currentList.current.items.map((item) => (
        item.id === post.id ? { ...item, comment_count: count } : item
      ))
    }
  }

  /**
   * 댓글 본문을 전송하고 성공 응답을 목록에 추가한다. 실패 시 폼이 초안을 유지하게 한다.
   * 일반 댓글은 목록 끝에, 대댓글은 같은 부모의 마지막 대댓글 뒤에 넣어 서버 순서와 맞춘다.
   */
  function addComment(body, parentCommentId = null) {
    return mutate(
      () => boardApi.createComment(board.id, post.id, body, parentCommentId),
      (created) => {
        if (!created.parent_comment_id) {
          applyComments([...comments, created])
          return
        }
        const lastIndex = comments.findLastIndex((item) => (
          item.id === created.parent_comment_id
          || item.parent_comment_id === created.parent_comment_id
        ))
        applyComments([
          ...comments.slice(0, lastIndex + 1),
          created,
          ...comments.slice(lastIndex + 1),
        ])
      },
    )
  }

  /** id가 일치하는 댓글만 서버 응답으로 교체한다. 실패 null이면 편집 화면은 닫지 않는다. */
  function editComment(id, body) {
    return mutate(
      () => boardApi.updateComment(id, body),
      (saved) => applyComments(comments.map((item) => item.id === id ? saved : item)),
    )
  }

  /**
   * 확인 후 해당 댓글만 제거한다. 204의 빈 응답은 mutate가 성공 true로 변환한다.
   * 서버 목록 규칙과 같게, 대댓글이 남은 부모는 자리표시로 바꾸고
   * 삭제된 부모의 마지막 대댓글을 지우면 그 자리표시도 함께 뺀다.
   */
  function deleteComment(id) {
    if (mutationLock.current || !window.confirm('이 댓글을 삭제할까요?')) return null
    return mutate(
      () => boardApi.deleteComment(id),
      () => {
        const target = comments.find((item) => item.id === id)
        const hasReplies = comments.some((item) => item.parent_comment_id === id)
        let next = hasReplies
          ? comments.map((item) => item.id === id
            ? { ...item, body: '', author_id: null, author_name: '', is_owner: false, is_deleted: true }
            : item)
          : comments.filter((item) => item.id !== id)
        const parentId = target?.parent_comment_id
        if (parentId && !next.some((item) => item.parent_comment_id === parentId)) {
          next = next.filter((item) => !(item.id === parentId && item.is_deleted))
        }
        applyComments(next)
      },
    )
  }

  /** 진행 중 상세 전환을 취소하고 새 글 폼을 연다. 변경 요청 중에는 화면을 바꾸지 않는다. */
  function openEditor() {
    if (mutationLock.current) return
    cancelDetail()
    setPost(null)
    setView('editor')
  }

  /** 현재 글을 유지한 채 수정 폼을 연다. 서버 권한 검증은 기존 API가 담당한다. */
  function editPost() {
    if (mutationLock.current) return
    setView('editor')
  }

  /** 편집을 취소하면 기존 글은 상세로, 새 글은 목록으로 돌아간다. */
  function cancelEditor() {
    if (mutationLock.current) return
    setView(post ? 'detail' : 'list')
  }

  /** 초기화 완료 후 생성 모달을 연다. 이전 상세 응답의 뒤늦은 화면 전환도 차단한다. */
  function openModal() {
    if (!initialized || mutationLock.current) return
    cancelDetail()
    setModal(true)
  }

  /** 저장 도중 닫기를 막아 성공·실패 처리의 대상 화면을 유지한다. */
  function closeModal() {
    if (mutationLock.current) return
    setModal(false)
  }

  return {
    boards, board, posts, post, comments, view, query, loading, detailLoading,
    busy, modal, error, success, initialized,
    selectBoard, searchPosts, openPost, backToList, createBoard, savePost,
    deletePost, addComment, editComment, deleteComment, openEditor,
    editPost, cancelEditor, openModal, closeModal, toggleLike, toggleScrap,
  }
}
