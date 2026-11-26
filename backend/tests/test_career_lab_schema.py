
from pydantic import ValidationError
from app.schemas.career import CareerLabCreate


# 투표 선택지가 1개일 때 오류 발생 확인
try:
    CareerLabCreate(
        title="백엔드와 데이터 분석 중 어떤 직무가 좋을까요?",
        body="취업 준비 방향에 대한 의견이 궁금합니다.",
        subcategory_code="JOB_COMPARISON",
        post_type="DISCUSSION",
        poll_options=["백엔드"],
    )

except ValidationError:
    print("투표 최소 2개 제한 정상 작동")


# 투표 선택지가 2개일 때 정상 생성 확인
try:
    result = CareerLabCreate(
        title="백엔드와 데이터 분석 중 어떤 직무가 좋을까요?",
        body="취업 준비 방향에 대한 의견이 궁금합니다.",
        subcategory_code="JOB_COMPARISON",
        post_type="DISCUSSION",
        poll_options=["백엔드", "데이터 분석"],
    )

    print("투표 선택지 2개 정상 생성")
    print(result.poll_options)

except ValidationError as error:
    print("스키마 검증 실패:", error)
