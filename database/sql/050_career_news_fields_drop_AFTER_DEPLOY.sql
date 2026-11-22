-- *** 최종 정리 전용: 백엔드 + 뉴스 수집 코드 배포 및 검증 이전에는 절대 실행하지 마세요. ***
-- 049 적용 후 기존 코드가 더 이상 career_news_fields를 참조하지 않는지 확인하세요.
-- SELECT / INSERT 기능 테스트, 뉴스 재수집, 마이페이지 스크랩 테스트가 먼저 성공해야 합니다.
-- backup 테이블은 삭제하지 않습니다. DROP CASCADE는 사용하지 않습니다.

-- 첫 번째 차집합이 반드시 0행인지 확인하세요.
-- 두 번째 차집합은 새 코드 배포 후 추가 수집된 뉴스/분야가 있으면 0행이 아닐 수도 있습니다.
SELECT news_id, field_code FROM career_news_fields
EXCEPT
SELECT news_id, unnest(field_codes) FROM career_news;

SELECT news_id, unnest(field_codes) FROM career_news
EXCEPT
SELECT news_id, field_code FROM career_news_fields;

-- 실제 삭제는 별도 승인 후 아래 주석을 해제하여 **해당 구문만** 실행하세요.
-- DROP TABLE career_news_fields;
