import { usePostForm } from '../../hooks/board/useBoardForms'

/** 입력 화면만 구성한다. 업로드 검증·미리보기 수명·제출 잠금은 hook이 담당한다. */
export default function PostForm({ initial, busy, onCancel, onSubmit }) {
  const form = usePostForm(initial, busy, onSubmit)

  return (
    <form className="editor-card" onSubmit={form.submit}>
      <label>
        제목 *
        <input
          maxLength={100}
          value={form.title}
          disabled={busy}
          onChange={(event) => form.setTitle(event.target.value)}
          placeholder="이야기의 제목을 입력하세요"
        />
      </label>
      <label>
        내용 *
        <textarea
          maxLength={20000}
          rows={9}
          value={form.body}
          disabled={busy}
          onChange={(event) => form.setBody(event.target.value)}
          placeholder="실명이나 개인 연락처를 포함하지 않고 작성해 주세요."
        />
      </label>
      {!initial && (
        <label>
          사진 (선택)
          <span className="upload-box">
            ▧<strong>사진 추가 · 최대 3장, 각 5MB</strong>
            <input
              type="file"
              accept="image/jpeg,image/png,image/gif,image/webp"
              multiple
              disabled={busy}
              onChange={form.chooseImages}
            />
          </span>
        </label>
      )}
      {!!form.previews.length && (
        <div className="image-previews">
          {form.previews.map((item, index) => (
            <figure key={item.url}>
              <img src={item.url} alt="업로드 미리보기" />
              <button
                type="button"
                aria-label={`${item.file.name} 제거`}
                disabled={busy}
                onClick={() => form.removeImage(index)}
              >
                ×
              </button>
            </figure>
          ))}
        </div>
      )}
      {/* 익명·닉네임 정책은 이번 리팩터링에서 바꾸지 않는다. 담당자 확인이 필요하다. */}
      <p className="privacy-note">
        다른 회원에게는 공개용 익명 ID만 보여요. 작성자 기수·반이나 로그인 계정 정보는 공개하지 않아요.
      </p>
      <div className="form-actions">
        <button type="button" className="button ghost" disabled={busy} onClick={onCancel}>
          취소
        </button>
        <button className="button purple" disabled={busy || !form.title.trim() || !form.body.trim()}>
          {busy ? '등록 중…' : '글 등록'}
        </button>
      </div>
    </form>
  )
}
