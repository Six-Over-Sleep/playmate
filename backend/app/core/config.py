
import os
from pathlib import Path
from dotenv import load_dotenv

# 1. 프로젝트 최상위 폴더 경로 찾기
BASE_DIR = Path(__file__).resolve().parents[3]

# 2. .env 파일 불러오기
load_dotenv(BASE_DIR / ".env")

# 3. Discord OAuth2 설정값 가져오기
DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET")
DISCORD_REDIRECT_URI = os.getenv("DISCORD_REDIRECT_URI")

SESSION_SECRET_KEY = os.getenv("SESSION_SECRET_KEY")

DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_NAME = os.getenv("DB_NAME")
DB_SSLMODE = os.getenv("DB_SSLMODE", "require")

# 4. 필수 설정값 확인
if not all([
    DISCORD_CLIENT_ID,
    DISCORD_CLIENT_SECRET,
    DISCORD_REDIRECT_URI,
    SESSION_SECRET_KEY,
]):
    raise ValueError("Discord OAuth2 또는 세션 환경변수가 설정되지 않았습니다.")

if not all([
    DB_HOST,
    DB_PORT,
    DB_USER,
    DB_PASSWORD,
    DB_NAME,
]):
    raise ValueError("DB연결 환경 변수가 설정되지 않았습니다")
