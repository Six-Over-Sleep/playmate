import { useMemo, useState } from "react";
import '../../styles/CareerPage.css'


// 취업 메인 카테고리 6개. 채용 인사이트는 게시판이 아닌 대시보드입니다.
const CATEGORIES = [
  { id: "insights", name: "채용 인사이트", icon: "chart", description: "채용 통계와 트렌드", menus: [] },
  { id: "reviews", name: "취준 도감", icon: "book", description: "전형별 합격·탈락 후기", menus: ["전체", "서류 도감", "코테·과제 도감", "면접 도감", "최종 결과", "취업 성공기"] },
  { id: "talk", name: "커리어 톡톡", icon: "chat", description: "취업과 이직 이야기", menus: ["전체", "취업 고민", "이직 고민", "진로 고민", "취준 일상", "취업 근황", "연봉·처우 고민"] },
  { id: "lounge", name: "현직자 라운지", icon: "users", description: "졸업생과 현직자 이야기", menus: ["전체", "현직자의 하루", "실무 기술", "회사 생활", "직무 Q&A", "주니어 생존기", "졸업생 인터뷰"] },
  { id: "lab", name: "커리어 연구소", icon: "light", description: "질문·토론·피드백", menus: ["전체", "취업 전략", "포트폴리오 피드백", "이력서·자소서", "기술면접 스터디", "자격증·스펙 전략", "직무 비교"] },
  { id: "briefing", name: "커리어 브리핑", icon: "news", description: "직무별 취업 뉴스", menus: ["전체", "개발·소프트웨어", "데이터·AI", "클라우드·인프라", "정보보안", "IT 산업·채용", "IT 기획·디자인·QA"] },
];

// API를 연결하기 전의 화면 확인용 예시 게시글입니다. 실제 데이터가 아닙니다.
const SAMPLE_POSTS = {
  reviews: [
    { id: 1, menu: "서류 도감", title: "[예시] 신입 백엔드 서류 지원 후기", summary: "서류 준비 과정과 포트폴리오를 정리하며 느낀 점을 공유해요.", author: "익명", date: "2026. 10. 22.", comments: 2, likes: 6 },
    { id: 2, menu: "면접 도감", title: "[예시] 데이터 분석 직무 면접 후기", summary: "면접 진행 방식과 준비했던 내용을 정리했어요.", author: "익명", date: "2026. 10. 21.", comments: 1, likes: 4 },
  ],
  talk: [
    { id: 3, menu: "취업 고민", title: "[예시] 첫 취업 준비, 어디서부터 시작할까요?", summary: "포트폴리오부터 만들지, 코딩 테스트를 먼저 준비할지 고민이에요.", author: "플레이메이트", date: "2026. 10. 22.", comments: 4, likes: 8 },
    { id: 4, menu: "진로 고민", title: "[예시] 백엔드와 데이터 엔지니어 중 고민입니다", summary: "관심 있는 두 직무의 실무 차이가 궁금해요.", author: "익명", date: "2026. 10. 21.", comments: 2, likes: 3 },
    { id: 5, menu: "취준 일상", title: "[예시] 이번 주 공부 목표 공유해요", summary: "함께 공부하면서 동기부여 받아요!", author: "플레이메이트", date: "2026. 10. 20.", comments: 3, likes: 5 },
  ],
  lounge: [
    { id: 6, menu: "현직자의 하루", title: "[예시] 신입 개발자의 하루", summary: "업무 흐름과 협업 방식을 간단히 소개합니다.", author: "졸업생", date: "2026. 10. 22.", comments: 1, likes: 5 },
    { id: 7, menu: "직무 Q&A", title: "[예시] 현직자에게 코드 리뷰 문화를 물어보세요", summary: "실무에서 궁금했던 점을 질문해 보세요.", author: "현직자", date: "2026. 10. 21.", comments: 2, likes: 3 },
  ],
  lab: [
    { id: 8, menu: "포트폴리오 피드백", title: "[예시] 백엔드 포트폴리오 피드백 부탁드립니다", summary: "프로젝트 소개와 기술 선택을 개선하고 싶어요.", author: "플레이메이트", date: "2026. 10. 22.", comments: 2, likes: 3 },
    { id: 9, menu: "기술면접 스터디", title: "[예시] 기술면접 스터디 같이 할 분?", summary: "CS 기초부터 차근차근 함께 공부해요.", author: "플레이메이트", date: "2026. 10. 21.", comments: 1, likes: 4 },
  ],
  briefing: [
    { id: 10, menu: "데이터·AI", title: "[예시] 데이터·AI 업계 뉴스", summary: "뉴스 수집 기능을 연결하면 실제 기사 제목과 출처가 표시됩니다.", author: "뉴스", date: "2026. 10. 22.", comments: 0, likes: 0 },
    { id: 11, menu: "개발·소프트웨어", title: "[예시] 소프트웨어 산업 소식", summary: "직무별 뉴스를 모아볼 공간입니다.", author: "뉴스", date: "2026. 10. 21.", comments: 0, likes: 0 },
  ],
};

function CategoryIcon({ type }) {
  const common = { fill: "none", stroke: "currentColor", strokeWidth: 1.9, strokeLinecap: "round", strokeLinejoin: "round" };
  return (
    <svg width="23" height="23" viewBox="0 0 24 24" aria-hidden="true" {...common}>
      {type === "chart" && <><path d="M4 19h16"/><path d="M6 15v-5M11 15V5M16 15v-7M21 15V3"/></>}
      {type === "book" && <><path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v17H6.5A2.5 2.5 0 0 1 4 17.5z"/><path d="M4 17.5A2.5 2.5 0 0 1 6.5 15H20M9 7h6"/></>}
      {type === "chat" && <><path d="M20 11.5c0 4.5-4 7.5-8 7.5-1.5 0-3-.3-4.3-1L3 20l1.2-4.2A7.1 7.1 0 0 1 4 11.5C4 7.1 7.6 4 12 4s8 3.1 8 7.5Z"/><path d="M8 11.5h8"/></>}
      {type === "users" && <><circle cx="9" cy="8" r="3"/><path d="M3 20v-2a6 6 0 0 1 12 0v2M16 5.5a3 3 0 0 1 0 5.5M17 14a5 5 0 0 1 4 5v1"/></>}
      {type === "light" && <><path d="M9 18h6M10 21h4M9 14.8a7 7 0 1 1 6 0l-.5 3h-5z"/><path d="M12 6v2M8 10h1M15 10h1"/></>}
      {type === "news" && <><path d="M6 4h14v15a2 2 0 0 1-2 2H6a3 3 0 0 1-3-3V6h3z"/><path d="M6 4v14a3 3 0 0 1-3 3M9 8h7M9 12h7M9 16h4"/></>}
    </svg>
  );
}

export default function CareerPage() {
  const [activeId, setActiveId] = useState("talk");
  const [activeMenu, setActiveMenu] = useState("전체");
  const [input, setInput] = useState("");
  const [keyword, setKeyword] = useState("");
  const [sort, setSort] = useState("latest");
  const active = CATEGORIES.find((item) => item.id === activeId);

  const posts = useMemo(() => {
    const filtered = (SAMPLE_POSTS[activeId] || []).filter((post) =>
      (activeMenu === "전체" || post.menu === activeMenu) &&
      `${post.title} ${post.summary} ${post.author} ${post.menu}`.toLowerCase().includes(keyword.trim().toLowerCase())
    );
    if (sort === "oldest") return [...filtered].reverse();
    if (sort === "title") return [...filtered].sort((a, b) => a.title.localeCompare(b.title, "ko"));
    return filtered;
  }, [activeId, activeMenu, keyword, sort]);

  function selectCategory(id) {
    setActiveId(id);
    setActiveMenu("전체");
    setInput("");
    setKeyword("");
    setSort("latest");
  }

  return (
    <main className="career-page">
      <div className="career-container">
        <div className="career-page-heading">
          <h1>취업</h1>
          <p>취업 준비부터 실무 이야기까지, 함께 나누는 커리어 공간</p>
        </div>

        {/* 카테고리는 왼쪽 사이드바가 아닌 상단 가로 카드로 표시합니다. */}
        <nav className="career-category-grid" aria-label="취업 카테고리">
          {CATEGORIES.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`career-category-card ${activeId === item.id ? "active" : ""}`}
              onClick={() => selectCategory(item.id)}
              aria-current={activeId === item.id ? "page" : undefined}
            >
              <span className="career-category-icon"><CategoryIcon type={item.icon} /></span>
              <span className="career-category-text"><strong>{item.name}</strong><small>{item.description}</small></span>
            </button>
          ))}
        </nav>

        <section className="career-board" aria-label={`${active.name} 콘텐츠`}>
          <div className="career-section-head">
            <div><span className="career-eyebrow">CAREER COMMUNITY</span><h2>{active.name}</h2></div>
            {activeId !== "insights" && activeId !== "briefing" && (
              <button type="button" className="career-write-btn" disabled title="게시글 작성 API 연동 후 활성화됩니다">+ 글쓰기</button>
            )}
          </div>

          {activeId === "insights" ? (
            <div className="career-dashboard-empty">
              <div className="career-dashboard-symbol"><CategoryIcon type="chart" /></div>
              <h3>채용 통계 대시보드</h3>
              <p>직무별 채용 공고와 기술 스택 트렌드를 한눈에 확인할 수 있는 공간입니다.</p>
              <div className="career-metric-placeholders">
                <span>직무별 공고 수</span><span>채용 증감 추이</span><span>기술 스택 랭킹</span>
              </div>
              <small>채용 데이터 연동 후 실제 통계가 표시됩니다.</small>
            </div>
          ) : (
            <>
              <div className="career-subnav" aria-label={`${active.name} 하위 게시판`}>
                {active.menus.map((menu) => (
                  <button
                    key={menu}
                    type="button"
                    className={activeMenu === menu ? "active" : ""}
                    onClick={() => { setActiveMenu(menu); setInput(""); setKeyword(""); }}
                    aria-pressed={activeMenu === menu}
                  >
                    {menu}
                  </button>
                ))}
              </div>

              <div className="career-board-toolbar">
                <form className="career-search" onSubmit={(event) => { event.preventDefault(); setKeyword(input); }}>
                  <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m16 16 4 4"/></svg>
                  <input value={input} onChange={(event) => setInput(event.target.value)} placeholder="게시글 검색" aria-label="게시글 검색" />
                  <button type="submit">검색</button>
                </form>
                <select value={sort} onChange={(event) => setSort(event.target.value)} aria-label="게시글 정렬">
                  <option value="latest">최신순</option><option value="oldest">오래된순</option><option value="title">제목순</option>
                </select>
              </div>

              <p className="career-sample-caption">* 화면 확인용 예시 게시글이며 실제 등록된 데이터가 아닙니다.</p>
              <div className="career-post-list" aria-live="polite">
                {posts.length ? posts.map((post) => (
                  <article className="career-post" key={post.id}>
                    <span className="career-post-tag">{post.menu}</span>
                    <h3>{post.title}</h3>
                    <p>{post.summary}</p>
                    <div className="career-post-footer"><strong>{post.author}</strong><span>{post.date}</span><span>♡ {post.likes}</span><span>♧ {post.comments}</span></div>
                  </article>
                )) : (
                  <div className="career-empty"><strong>표시할 게시글이 없어요.</strong><span>하위 메뉴나 검색어를 변경해 주세요.</span></div>
                )}
              </div>
            </>
          )}
        </section>
      </div>
    </main>
  );
}
