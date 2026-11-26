# IT 직군 필터 및 분류 개선 패치

Playmate 루트 기준 `crawler/saramin_crawler/` 파일만 덮어씁니다.

- `parser.py`: 직무 태그/제목 직무 매칭, 영어 별칭 및 띄어쓰기 지원, 회계·세무 태그에 편중된 공고 제외. **직무가 확인된 IT 공고만 반환**합니다.
- `crawler.py`: `--details` 경로에서 접근 가능한 상세 HTML 텍스트의 기술 스택/전문분야까지 추출해 기존 배열에 합칩니다.
- `config.py`: 기존 분류 사전 그대로 유지 (동일 파일 포함).
- `test/test_one_job.py`: 첫 번째 **분류가 확인된** IT 공고만 반환하고, `--details`에서 기술 스택 추가 추출.
- `test/test_parser_it.py`: 샘플 HTML 기반 회귀 테스트.

## 실행

```powershell
uv run python crawler/saramin_crawler/test/test_one_job.py
uv run python crawler/saramin_crawler/test/test_one_job.py --details
uv run python -m pytest crawler/saramin_crawler/test/test_parser_it.py
```

`pytest`가 없으면 `uv run --with pytest python -m pytest crawler/saramin_crawler/test/test_parser_it.py`.

`--details`는 사이트의 자동 상세수집 허용 범위를 확인한 경우에만 실행하세요.

## 왜 여전히 []가 나올 수 있나요?

- 직무(`job_roles`): 이제 직무 식별 불가 공고는 **결과에서 제외**합니다. 단, 제목만으로 추정된 직무도 있을 수 있어 `role_classification_source`를 확인하세요.
- 전문분야(`specialties`): 공고에서 전문분야를 명시하지 않으면 빈 배열로 둡니다.
- 기술 스택(`tech_stacks`): 목록에 기술명이 없으면 빈 배열이며, `tech_stack_status`에 사유가 표시됩니다. `--details`는 상세 HTML에 실제 명시된 기술만 추가합니다.
- 우대사항(`preferences`): 상세페이지에 텍스트로 노출되고 파싱되는 경우에만 저장합니다.

**빈 값을 억지로 채우면 대시보드의 채용 트렌드 통계가 왜곡됩니다.** 모든 항목이 비지 않도록 보장하는 코드는 아닙니다.

## 한계

기존 사람인 목록 URL은 IT 직군만을 서버 수준에서 보장하지 않을 수 있으므로 HTML에서 필터링합니다. 제목 기반 분류는 어디까지나 추정입니다. 실제 사이트 HTML 변경 시 선택자 점검이 필요합니다. 본 패치는 사이트 접속 및 실제 DB 쓰기 테스트를 수행하지 않았습니다.
