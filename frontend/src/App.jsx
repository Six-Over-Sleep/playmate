import { useCallback, useEffect, useRef, useState } from 'react'
import LoginPage from './pages/auth/LoginPage'
import SignupPage from './pages/auth/SignupPage'
import BoardCreateModal from './components/board/BoardCreateModal'
import BoardPage from './pages/board/BoardPage'
import PostDetailPage from './pages/board/PostDetailPage'
import PostEditorPage from './pages/board/PostEditorPage'
import MeetupPage from './pages/meetup/MeetupPage'
import MeetupDetailPage from './pages/meetup/MeetupDetailPage'
import MeetupEditorPage from './pages/meetup/MeetupEditorPage'
import { boardApi } from './services/boardApi'
import { meetupApi } from './services/meetupApi'
import Header from './components/layout/Header'

const API_BASE_URL = 'http://localhost:8000'

export default function App() {
  const [authView, setAuthView] = useState('checking')
  const [section, setSection] = useState('board')
  const [boardKey, setBoardKey] = useState(0)

  const enterService = useCallback(() => {
    setSection('board')
    setAuthView('board')
  }, [])

  const checkAuth = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/auth/me`, {
        credentials: 'include',
      })

      if (response.status === 401) {
        setAuthView('login')
        return
      }

      const data = await response.json()

      if (!response.ok) {
        throw new Error(data.detail || '로그인 상태를 확인하지 못했습니다.')
      }

      if (data.signup_required) {
        setAuthView('signup')
        return
      }

      enterService()
    } catch (error) {
      console.error(error)
      setAuthView('login')
    } finally {
      const url = new URL(window.location.href)

      if (url.searchParams.has('auth') || url.searchParams.has('signup')) {
        url.searchParams.delete('auth')
        url.searchParams.delete('signup')
        window.history.replaceState({}, '', `${url.pathname}${url.search}${url.hash}`)
      }
    }
  }, [enterService])

  useEffect(() => {
    checkAuth()
  }, [checkAuth])

  const handleNavigate = (nextSection) => {
    setSection(nextSection)

    // 게시판 메뉴를 누르면 게시판 내부 화면을 목록으로 초기화
    if (nextSection === 'board') {
      setBoardKey((prev) => prev + 1)
    }
  }

  if (authView === 'checking') {
    return (
      <main className="service-error">
        <p>로그인 상태를 확인하는 중...</p>
      </main>
    )
  }

  if (authView === 'signup') {
    return (
      <SignupPage
        onBack={() => setAuthView('login')}
        onComplete={enterService}
      />
    )
  }

  if (authView === 'board') {
    return (
      <>
        <Header
          activeSection={section}
          onNavigate={handleNavigate}
        />

        {section === 'board' && (
          <BoardSection key={boardKey} />
        )}

        {section === 'meetup' && (
          <MeetupSection />
        )}
      </>
    )
  }

  return (
    <LoginPage
      onSignup={() => setAuthView('signup')}
      onDevEnter={enterService}
    />
  )
}

function BoardSection() {
  const [boards, setBoards] = useState([])
  const [board, setBoard] = useState(null)
  const [posts, setPosts] = useState([])
  const [post, setPost] = useState(null)
  const [comments, setComments] = useState([])
  const [view, setView] = useState('list')
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [modal, setModal] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [initialized, setInitialized] = useState(false)
  const postsRequestId = useRef(0)

  const run = useCallback(async (task) => {
    try {
      setError('')
      return await task()
    } catch (err) {
      setError(err.message)
      throw err
    }
  }, [])

  const loadPosts = useCallback(async (target, search = '') => {
    if (!target) return

    const requestId = ++postsRequestId.current
    setLoading(true)

    try {
      const items = await run(() => boardApi.posts(target.id, search))

      if (requestId === postsRequestId.current) {
        setPosts(items)
      }
    } catch {
      if (requestId === postsRequestId.current) {
        setPosts([])
      }
    } finally {
      if (requestId === postsRequestId.current) {
        setLoading(false)
      }
    }
  }, [run])

  useEffect(() => {
    run(boardApi.boards)
      .then((items) => {
        setBoards(items)

        if (items[0]) {
          setBoard(items[0])
          loadPosts(items[0])
        } else {
          setLoading(false)
        }
      })
      .catch(() => setLoading(false))
      .finally(() => setInitialized(true))
  }, [loadPosts, run])

  const selectBoard = (target) => {
    setBoard(target)
    setPosts([])
    setQuery('')
    setView('list')
    setError('')
    loadPosts(target)
  }

  const openPost = async (item) => {
    try {
      const [detail, replies] = await Promise.all([
        run(() => boardApi.post(board.id, item.id)),
        run(() => boardApi.comments(board.id, item.id)),
      ])
      setPost(detail)
      setComments(replies)
      setView('detail')
    } catch {}
  }

  const refreshDetail = async () => {
    setPost(await run(() => boardApi.post(board.id, post.id)))
    setComments(await run(() => boardApi.comments(board.id, post.id)))
  }

  const notify = (message) => {
    setSuccess(message)
    setTimeout(() => setSuccess(''), 2500)
  }

  const mutate = async (task, after) => {
    setBusy(true)
    try {
      const result = await run(task)
      await after(result)
      return result
    } catch {
      return null
    } finally {
      setBusy(false)
    }
  }

  const createBoard = (payload) => mutate(() => boardApi.createBoard(payload), async (created) => {
    const items = await boardApi.boards()
    setBoards(items)
    setModal(false)
    selectBoard(created)
    notify('게시판을 만들었습니다.')
  })

  const savePost = (payload) => mutate(
    () => post
      ? boardApi.updatePost(board.id, post.id, payload)
      : boardApi.createPost(board.id, payload),
    async (saved) => {
      setPost(saved)
      setComments(post ? comments : [])
      setView('detail')
      notify(post ? '게시글을 수정했습니다.' : '게시글을 등록했습니다.')
    },
  )

  const deletePost = () => {
    if (confirm('이 글을 삭제할까요?')) {
      const deletedPostId = post.id

      mutate(() => boardApi.deletePost(board.id, deletedPostId), async () => {
        setPosts((prev) =>
          Array.isArray(prev)
            ? prev.filter((item) => item.id !== deletedPostId)
            : prev
        )

        setPost(null)
        setView('list')

        await loadPosts(board, query)
      })
    }
  }

  const addComment = (body) => mutate(() => boardApi.createComment(board.id, post.id, body), refreshDetail)
  const editComment = (id, body) => mutate(() => boardApi.updateComment(id, body), refreshDetail)
  const deleteComment = (id) => {
    if (confirm('이 댓글을 삭제할까요?')) return mutate(() => boardApi.deleteComment(id), refreshDetail)
  }

  const unavailable = initialized && !board && error
  return (
    <>
      {error && <div className="error-banner" role="alert">{error}</div>}
      {success && <div className="success-toast" role="status">{success}</div>}
      {unavailable ? (
        <main className="service-error">
          <h1>게시판을 불러오지 못했어요</h1>
          <p>{error}</p>
          <button className="button purple" onClick={() => location.reload()}>다시 시도</button>
        </main>
      ) : (
        <>
          {view === 'list' && (
            <BoardPage
              boards={boards} board={board} posts={posts} query={query} loading={loading}
              onSelectBoard={selectBoard} onCreateBoard={() => setModal(true)}
              onSearch={(value) => {
                setQuery(value)
                loadPosts(board, value)
              }}
              onWrite={() => { setPost(null); setView('editor') }} onPost={openPost}
            />
          )}
          {view === 'editor' && board && (
            <PostEditorPage
              board={board} post={post} busy={busy}
              onBack={() => setView(post ? 'detail' : 'list')} onSubmit={savePost}
            />
          )}
          {view === 'detail' && post && (
            <PostDetailPage
              boards={boards} board={board} post={post} comments={comments} busy={busy}
              onSelectBoard={selectBoard} onCreateBoard={() => setModal(true)}
              onBack={() => { setView('list'); loadPosts(board, query) }}
              onEdit={() => setView('editor')} onDelete={deletePost} onComment={addComment}
              onEditComment={editComment} onDeleteComment={deleteComment}
            />
          )}
        </>
      )}
      <BoardCreateModal open={modal} busy={busy} onClose={() => setModal(false)} onCreate={createBoard} />
    </>
  )
}

function MeetupSection() {
  const [meetups, setMeetups] = useState([])
  const [selectedMeetup, setSelectedMeetup] = useState(null)
  const [view, setView] = useState('list')
  const [loading, setLoading] = useState(true)
  const [detailLoading, setDetailLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [members, setMembers] = useState([])
  const [memberCount, setMemberCount] = useState(0)
  const [joined, setJoined] = useState(false)
  const [error, setError] = useState('')

  const normalizeCount = (data) => {
    if (typeof data === 'number') return data
    return Number(data?.current_members ?? data?.count ?? data?.member_count ?? data?.current_count ?? data?.participant_count ?? 0)
  }

  const loadMeetups = async () => {
    setLoading(true)
    try {
      const data = await meetupApi.list()
      const withCounts = await Promise.all(data.map(async (meetup) => {
        try {
          return { ...meetup, participant_count: normalizeCount(await meetupApi.count(meetup.recruit_id)) }
        } catch (err) {
          console.error(err)
          return { ...meetup, participant_count: 0 }
        }
      }))
      setMeetups(withCounts)
    } catch (err) {
      console.error(err)
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { loadMeetups() }, [])

  const loadParticipation = async (recruitId) => {
    const [memberData, countData] = await Promise.all([meetupApi.members(recruitId), meetupApi.count(recruitId)])
    const memberList = Array.isArray(memberData) ? memberData : memberData?.members || []
    setMembers(memberList)
    setMemberCount(normalizeCount(countData))
    setJoined(memberList.some((member) => Number(member?.member_id ?? member?.id) === -1))
  }

  const openMeetup = async (meetup) => {
    setDetailLoading(true)
    setError('')
    try {
      const detail = await meetupApi.detail(meetup.recruit_id)
      setSelectedMeetup(detail)
      await loadParticipation(meetup.recruit_id)
      setView('detail')
    } catch (err) {
      console.error(err)
      setError(err.message)
    } finally {
      setDetailLoading(false)
    }
  }

  const goBack = () => {
    setSelectedMeetup(null)
    setMembers([])
    setMemberCount(0)
    setJoined(false)
    setView('list')
    setError('')
  }

  const openWrite = () => {
    setSelectedMeetup(null)
    setError('')
    setView('editor')
  }

  const openEdit = async () => {
    if (!selectedMeetup?.recruit_id) return
    setDetailLoading(true)
    setError('')
    try {
      setSelectedMeetup(await meetupApi.detail(selectedMeetup.recruit_id))
      setView('editor')
    } catch (err) {
      console.error(err)
      setError(err.message)
    } finally {
      setDetailLoading(false)
    }
  }

  const createMeetup = async (payload) => {
    setBusy(true)
    setError('')
    try {
      const created = await meetupApi.create(payload)
      await loadMeetups()
      if (created?.recruit_id) {
        setSelectedMeetup(await meetupApi.detail(created.recruit_id))
        await loadParticipation(created.recruit_id)
        setView('detail')
      } else {
        setView('list')
      }
    } catch (err) {
      console.error(err)
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const updateMeetup = async (payload) => {
    if (!selectedMeetup) return
    setBusy(true)
    setError('')
    try {
      await meetupApi.update(selectedMeetup.recruit_id, payload)
      setSelectedMeetup(await meetupApi.detail(selectedMeetup.recruit_id))
      await loadParticipation(selectedMeetup.recruit_id)
      await loadMeetups()
      setView('detail')
    } catch (err) {
      console.error(err)
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const deleteMeetup = async () => {
    if (!selectedMeetup || !window.confirm('이 모임을 삭제할까요?')) return
    setBusy(true)
    setError('')
    try {
      await meetupApi.remove(selectedMeetup.recruit_id)
      setSelectedMeetup(null)
      setMembers([])
      setMemberCount(0)
      setJoined(false)
      await loadMeetups()
      setView('list')
    } catch (err) {
      console.error(err)
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const changeParticipation = async (join) => {
    if (!selectedMeetup || busy) return
    setBusy(true)
    setError('')
    try {
      if (join) await meetupApi.join(selectedMeetup.recruit_id)
      else await meetupApi.cancelJoin(selectedMeetup.recruit_id)
      setJoined(join)
      await loadParticipation(selectedMeetup.recruit_id)
      setSelectedMeetup(await meetupApi.detail(selectedMeetup.recruit_id))
      await loadMeetups()
    } catch (err) {
      console.error(err)
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      {error && <div className="error-banner" role="alert">{error}</div>}
      {detailLoading && <main className="meetup-page"><p>모임 정보를 불러오는 중...</p></main>}
      {!detailLoading && view === 'list' && <MeetupPage meetups={meetups} loading={loading} onMeetup={openMeetup} onWrite={openWrite} />}
      {!detailLoading && view === 'detail' && selectedMeetup && (
        <MeetupDetailPage
          meetup={selectedMeetup} members={members} memberCount={memberCount} joined={joined} busy={busy}
          onBack={goBack} onEdit={openEdit} onDelete={deleteMeetup}
          onJoin={() => changeParticipation(true)} onCancelJoin={() => changeParticipation(false)}
        />
      )}
      {!detailLoading && view === 'editor' && (
        <MeetupEditorPage
          key={selectedMeetup?.recruit_id ?? 'new'} meetup={selectedMeetup} busy={busy}
          onBack={selectedMeetup ? () => setView('detail') : goBack}
          onSubmit={selectedMeetup ? updateMeetup : createMeetup}
        />
      )}
    </>
  )
}
