"""사람인 IT개발·데이터 화면에 표시되는 분류명(2026-11 첨부 스크린샷)."""
SPECIALTIES = '''검색엔진 네트워크 데이터라벨링 데이터마이닝 데이터시각화 딥러닝 루비온레일즈 머신러닝 메타버스 모델링 모의해킹 미들웨어 반응형웹 방화벽 블록체인 빅데이터 빌링 솔루션 스크립트 신경망 아키텍처 악성코드 알고리즘 암호화폐 영상처리 웹표준·웹접근성 음성인식 이미지프로세싱 인터페이스 인프라 임베디드 자율주행 정보통신 챗봇 취약점진단 컴퓨터비전 크로스브라우징 크로스플랫폼 크롤링 클라우드 클라이언트 테스트마이닝 트러블슈팅 펌웨어 플러그인 핀테크 헬스케어 AI(인공지능) API APM AR(증강현실) Dapp DBMS DevOps DID DLP DW ERP ETL FPGA GIS H/W HTTP IDC IIS IoT ISMS MCU MMORPG Nginx NLP(자연어처리) NLU(자연어이해) OCR OLAP RDBMS RPA RTOS S/W SAP WCF Windows 3D'''.split()
JOB_ROLES = '''개발PM 게임개발 기술지원 데이터사이언티스트 데이터분석가 데이터엔지니어 백엔드/서버개발 보안관제 보안컨설팅 앱개발 웹개발 웹마스터 유지보수 정보보안 퍼블리셔 프론트엔드 BI엔지니어 CISO CPO DBA FAE GM(게임운영) ICT컨설팅 IT컨설팅 QA/테스터 SE(시스템엔지니어) SI개발 SQA'''.split()
# 분류어와 별도로 식별할 기술 스택. 단어 경계 확인을 통해 SQL이 MySQL에 중복 매칭되지 않게 한다.
TECH_STACKS = [
    'Python','Java','JavaScript','TypeScript','C++','C#','Go','Kotlin','Swift','PHP',
    'React','Vue','Angular','Next.js','Node.js','Spring','Spring Boot','Django','FastAPI','Flask',
    'PostgreSQL','MySQL','MariaDB','MongoDB','Redis','Oracle','SQL','NoSQL','Kafka',
    'Docker','Kubernetes','AWS','Azure','GCP','Git','Linux','TensorFlow','PyTorch',
    'Spark','Hadoop','Airflow','Tableau','Power BI','Elasticsearch','HTML','CSS',
]
CATEGORY_URL = 'https://www.saramin.co.kr/zf_user/jobs/list/job-category'
CATEGORY_PARAMS = {'cat_mcls': '2'}  # IT개발·데이터 카테고리 공식 웹페이지의 공개 URL
