import { useEffect, useMemo, useState } from 'react'
import { sortBoardPosts } from '../../utils/board'

/** 검색 초안과 확정 query를 분리하고, 정렬은 이미 받은 목록에서 처리한다. */
export function useBoardSearch(value, onSearch) {
  const [search, setSearch] = useState(value || '')

  useEffect(() => {
    setSearch(value || '')
  }, [value])

  /** 기본 폼 이동을 막고 공백을 다듬은 검색어만 상위 조회 함수에 전달한다. */
  function submitSearch(event) {
    event.preventDefault()
    onSearch(search.trim())
  }

  return { search, setSearch, submitSearch }
}

/** 서버가 latest만 지원하므로 오래된순도 같은 응답을 재사용한다. */
export function useSortedPosts(posts, sort) {
  return useMemo(() => sortBoardPosts(posts, sort), [posts, sort])
}
