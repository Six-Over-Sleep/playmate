// Screenshot-based STATIC filter catalogue. These choices appear even when the DB is empty.
// Counts visible on Saramin are NOT copied: they are not Playmate statistics.
export const INSIGHT_FIELDS = `검색엔진|네트워크|데이터라벨링|데이터마이닝|데이터시각화|딥러닝|루비온레일즈|머신러닝|메타버스|모델링|모의해킹|미들웨어|반응형웹|방화벽|블록체인|빅데이터|빌링|솔루션|스크립트|신경망|아키텍처|악성코드|알고리즘|암호화폐|영상처리|웹표준·웹접근성|음성인식|이미지프로세싱|인터페이스|인프라|임베디드|자율주행|정보통신|챗봇|취약점진단|컴퓨터비전|크로스브라우징|크로스플랫폼|크롤링|클라우드|클라이언트|테스트마이닝|트러블슈팅|펌웨어|플러그인|핀테크|헬스케어|AI(인공지능)|API|APM|AR(증강현실)|Dapp|DBMS|DevOps|DID|DLP|DW|ERP|ETL|FPGA|GIS|H/W|HTTP|IDC|IIS|IoT|ISMS|MCU|MMORPG|Nginx|NLP(자연어처리)|NLU(자연어이해)|OCR|OLAP|RDBMS|RPA|RTOS|S/W|SAP|SDK|SOA|STT|TTS|UTM|VDI|VMware|VoIP|VPN|VR(가상현실)|WCF|Windows|3D`.split('|')

// All skills visible in the supplied skill-stack screenshot; extended with relevant
// engineering stack names to keep existing database values selectable in the MVP.
export const INSIGHT_SKILLS = `그누보드|라즈베리파이|쉘스크립트|스마트컨트랙트|아두이노|액션스크립트|어셈블리|와이어샤크|임베디드리눅스|파워빌더|풀스택|.NET|ABAP|AIX|Ajax|Android|Angular|Python|Java|JavaScript|TypeScript|SQL|MySQL|PostgreSQL|MongoDB|Redis|React|Vue|Next.js|Node.js|Spring|Django|FastAPI|Flask|Docker|Kubernetes|AWS|Azure|GCP|Git|Linux|TensorFlow|PyTorch|Spark|Airflow|Kafka|C++|C#|Go|Kotlin|Swift|PHP|Oracle|MariaDB|NoSQL|Elasticsearch|HTML|CSS|Nginx|Tableau|Power BI|Hadoop`.split('|')

const current = new Date()
export const QUARTER_OPTIONS = Array.from({ length: 4 }, (_, index) => {
  const number = current.getFullYear() * 4 + Math.floor(current.getMonth() / 3) - index
  const year = Math.floor(number / 4)
  const quarter = number % 4 + 1
  return { id: `${year}-Q${quarter}`, label: `${year}년 ${quarter}분기` }
})
