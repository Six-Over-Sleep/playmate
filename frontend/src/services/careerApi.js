// 취준 도감 Backend API 호출을 관리하는 파일
// 기존 게시판 API와 분리하여 취업 기능을 독립적으로 관리한다.

const BASE_URL = "/api/career/reviews";


// 공통 API 요청 함수
async function request(url, options = {}) {
    const headers = {
        Accept: "application/json",
        ...options.headers,
    };

    // 개발 환경에서 사용할 회원 ID
    // .env에 VITE_DEV_MEMBER_ID가 설정된 경우에만 전송
    if (import.meta.env.DEV && import.meta.env.VITE_DEV_MEMBER_ID) {
        headers["X-Dev-Member-ID"] = import.meta.env.VITE_DEV_MEMBER_ID;
    }

    const response = await fetch(url, {
        ...options,
        headers,
        credentials: "include",
    });

    // API 오류 처리
    if (!response.ok) {
        const error = await response.json().catch(() => ({}));

        throw new Error(
            typeof error.detail === "string"
                ? error.detail
                : `API 요청 실패 (${response.status})`
        );
    }

    // DELETE 성공 시 응답 본문 없음
    if (response.status === 204) {
        return null;
    }

    return response.json();
}


// 1. 후기 목록 조회
export async function getCareerReviews(params = {}) {
    const query = new URLSearchParams();

    Object.entries(params).forEach(([key, value]) => {
        if (value !== undefined && value !== null && value !== "") {
            query.append(key, String(value));
        }
    });

    const url = query.toString()
        ? `${BASE_URL}?${query.toString()}`
        : BASE_URL;

    return request(url);
}


// 2. 후기 상세 조회
export async function getCareerReview(postId) {
    return request(`${BASE_URL}/${postId}`);
}


// 3. 후기 등록
export async function createCareerReview(data) {
    return request(BASE_URL, {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
        },
        body: JSON.stringify(data),
    });
}


// 4. 후기 수정
export async function updateCareerReview(postId, data) {
    return request(`${BASE_URL}/${postId}`, {
        method: "PATCH",
        headers: {
            "Content-Type": "application/json",
        },
        body: JSON.stringify(data),
    });
}


// 5. 후기 삭제
export async function deleteCareerReview(postId) {
    return request(`${BASE_URL}/${postId}`, {
        method: "DELETE",
    });
}