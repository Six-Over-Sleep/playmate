
# 회원 정보, 권한, 계정 상태 및 Discord 알림 수신 동의 여부를 관리하는 모델
from sqlalchemy import Column, BigInteger, String, DateTime, Boolean
from backend.app.core.database import Base


class Member(Base):
    __tablename__ = "members"

    # member_id : 회원 고유 번호
    # primary_key=True : 기본키(PK) 설정
    # autoincrement=False : 자동 증가 사용 안 함
    member_id = Column(BigInteger, primary_key=True, autoincrement=False)

    # public_anonymous_id : 외부에 표시되는 익명 회원 식별자
    public_anonymous_id = Column(String)

    # role_code : 회원 권한 구분 (일반 회원, 관리자 등)
    role_code = Column(String)

    # member_status : 회원 계정 상태 (ACTIVE, SUSPENDED, WITHDRAWN)
    member_status = Column(String)

    # created_at : 회원 가입 시간
    # updated_at : 회원 정보 마지막 수정 시간
    created_at = Column(DateTime)
    updated_at = Column(DateTime)

    # student_verification_status : 부트캠프 학생 인증 상태
    # PENDING : 인증 대기 / VERIFIED : 인증 완료 / REJECTED : 인증 거절
    student_verification_status = Column(String)

    # verified_at : 학생 인증이 완료된 시간
    verified_at = Column(DateTime)

    # external_dm_opt_in : Discord 개인 DM 알림 수신 동의 여부
    # True : 수신 동의 / False : 수신 거부
    external_dm_opt_in = Column(Boolean)
