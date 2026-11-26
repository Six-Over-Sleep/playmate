
# 회원 정보, 권한, 계정 상태 및 Discord 알림 수신 동의 여부를 관리하는 모델
from sqlalchemy import Column, BigInteger, String, DateTime, Boolean
from backend.app.core.database import Base


class Member(Base):
    __tablename__ = "members"

    # member_id : 회원 고유 번호
    # primary_key=True : 기본키(PK) 설정
    # autoincrement=False : 자동 증가 사용 안 함
    member_id = Column(BigInteger, primary_key=True, autoincrement=False)

    # role_code : 회원 권한 구분 (일반 회원, 관리자 등)
    role_code = Column(String(20))

    # member_status : 회원 계정 상태 (ACTIVE, SUSPENDED, WITHDRAWN)
    member_status = Column(String(20), nullable=False)

    # created_at : 회원 가입 시간
    # updated_at : 회원 정보 마지막 수정 시간
    created_at = Column(DateTime)
    updated_at = Column(DateTime)

    # external_dm_opt_in : Discord 개인 DM 알림 수신 동의 여부
    # True : 수신 동의 / False : 회원이 /알림설정으로 끔 / NULL : 선택 안 함 (기본 ON으로 처리)
    # 신규 가입은 True로 저장함. (member_service.register_member, database/sql/012)
    external_dm_opt_in = Column(Boolean)
    # 댓글 작성자 이름 표시에 사용함. (members 테이블의 실제 컬럼)
    nickname = Column(String(50))

    # Discord OAuth login syncs this existing members column.
    profile_image_url = Column(String(500))
