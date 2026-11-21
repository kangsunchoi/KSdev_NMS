# CLAUDE.md — NetVision OT 작업 규칙

## 보고 / 소통
- 답변과 작업 보고는 한국어. 결론 먼저, 표와 체크리스트로 짧게.
- 확인한 사실, 제안, 미검증 항목을 구분한다. 실행하지 않은 것을 "완료"라고 쓰지 않는다.
- 진행 체크리스트는 GitHub 이슈 #1(PM 트래킹)에 갱신한다.

## 작업 방식
- 작업 단위 = GitHub 이슈 1개 = 브랜치 1개 = PR 1개. `main`에 직접 push하지 않는다.
- 브랜치 이름: `sprintN/<짧은-설명>` 또는 `fix/<이슈번호>-<설명>`.
- PR 병합 조건: CI 통과 + 리뷰 에이전트 검수 통과. 사용자 실사용 확인이 필요한 항목은 PR에 체크리스트로 남긴다.
- 변경 범위를 작게. 리팩터링과 기능 변경을 한 PR에 섞지 않는다.

## 실행 / 검증 명령
```bash
cd backend && pip install -r requirements-dev.txt
ruff check .          # 린트
pytest -q             # 테스트 (인메모리 DB로 서버 자동 기동)
cd ../frontend && corepack enable && yarn install && CI=false yarn build
```
- 백엔드 변경 시 `ruff check .`와 `pytest -q` 통과 필수. 버그 수정에는 재현 테스트를 함께 추가한다.
- 프론트 변경 시 `yarn build` 통과 필수.

## 코드 규칙
- 수집(Node-RED → `/api/ingest` 등)과 화면 로직을 직접 결합하지 않는다. 화면은 API만 소비한다.
- 시뮬레이션 모드(`SIMULATION_MODE=true`)와 실데이터 모드 양쪽에서 동작을 확인한다.
- 신규 기능은 `.env` 토글로 넣고 기본값은 기존 동작을 유지한다.
- 추가 패키지는 꼭 필요할 때만. 런타임은 `requirements.txt`, 테스트·도구는 `requirements-dev.txt`.
- 비밀값(토큰, 웹훅, 비밀번호, 실제 community 값)은 저장소에 넣지 않는다. 저장소는 public이다.

## 금지 / 확인 필요
- MongoDB 데이터 삭제(`mock/reset`, `delete_many` 등)를 운영 DB 대상으로 실행하지 않는다.
- 운영 VM(`192.168.108.129`) 설정 변경은 사용자 확인 후.
- `docs/`의 이관 문서는 근거 자료다. 수정 시 출처와 날짜를 남긴다.
