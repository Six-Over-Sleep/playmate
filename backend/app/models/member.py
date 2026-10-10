# Discord 회원 정보를 Python에서 조회하고 관리하는 모델
from sqlalchemy import Column, BigInteger, String, DateTime, Boolean
from backend.app.core.database import Base

# 회원 정보를 표현하는 Python 클래스
class Member(Base):
    __tablename__ = "members" # 연결할 DB 테이블 이름

    # Column() : DB 컬럼 정의
    # primary_key=True : 기본키 설정
    member_id = Column(BigInteger, primary_key=True, autoincrement=False)
    public_anonymous_id = Column(String)
    role_code = Column(String)
    member_status = Column(String)
    created_at = Column(DateTime)
    updated_at = Column(DateTime)
    student_verification_status = Column(String)
    verified_at = Column(DateTime)
    external_dm_opt_in = Column(Boolean)
