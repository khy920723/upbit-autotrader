# CLAUDE.md

업비트 KRW 마켓 개인용 자동매매 Windows 데스크톱 앱. 문서 지도는 docs/README.md다. 요구사항은 docs/01-planning/requirements.md, 단계 계획과 검증된 외부 사실은 docs/10-management/roadmap.md, 진행 기록은 docs/10-management/progress.md, 결정은 docs/10-management/decision-log.md에 있다.

## 절대 규칙

- 실제 API 키·토큰·비밀번호를 코드, 테스트, 로그, 커밋, PR, 대화에 쓰지 않는다. `.env`나 키 파일을 만들거나 커밋하지 않는다. 테스트에는 가짜 값만 쓴다.
- **공개 저장소다.** 잔고, 주문 내역, IP 주소, 계정 정보 같은 개인 정보도 커밋하지 않는다.
- 클라우드 세션에서는 업비트 비공개(Exchange) API, 주문 API, 주문 테스트 API를 호출하지 않는다. 호출해도 되는 외부 API는 업비트 공개 시세(Quotation) API뿐이다.
- 기본 실행 모드는 `paper`다. 실전(`live`)은 사용자가 화면에서 명시적으로 켤 때만 동작한다.
- docs/03-functional/risk-policy.md의 위험 관리 규칙은 전략·LLM 결과와 상관없이 항상 강제한다. 우회하는 옵션이나 디버그 플래그를 만들지 않는다.
- 시세조종으로 오해받을 주문을 만들지 않는다: 자기 주문끼리 체결 금지, 최소 주문 간격과 일일 주문 수 상한 유지, 고빈도 소액 반복 주문 금지.

## GitHub 제약

- `.github/workflows/`는 수정하지 않는다. 클라우드 세션의 push가 거부된다. 바꿔야 하면 docs/10-management/ci-proposals.md에 변경안을 적고 PR 설명에 알린다. 사용자가 로컬에서 반영한다.
- 태그를 push하지 않는다(프록시가 거부한다). 릴리스와 빌드 실행은 사용자가 한다.
- `claude/` 브랜치에서 연 PR은 필수 검사(`test`, `windows`)를 통과하면 자동으로 squash 병합된다. 그래서:
  - PR을 만들기 직전에 최신 `origin/main`을 병합해 충돌을 해결한다. 충돌이 있으면 자동 병합되지 않는다.
  - PR은 초안(draft)으로 만들지 않는다.
  - 사용자 결정이 필요한 항목은 결정 로그에 "제안"이나 "대기"로만 기록하고 확정하지 않는다.
  - PR이 이미 병합된 뒤 추가 작업이 생기면 최신 `main`에서 새 브랜치를 만들어 새 PR을 연다.
- `gh`는 REST만 동작한다: `gh api repos/khy920723/upbit-autotrader/...`. `gh pr`, `gh issue`, `gh run view` 같은 GraphQL 기반 명령은 403이다. Actions 로그는 `gh api repos/khy920723/upbit-autotrader/actions/runs/{id}/logs`로 읽는다.

## 고정 기술 기준

- Python 3.13 (`requires-python = ">=3.13,<3.14"`), 패키지 관리는 uv, `uv.lock`을 항상 커밋한다.
- PySide6는 `>=6.12,<6.13`. Qt 6.12가 Windows 10을 지원하는 마지막 버전이라 6.13 이상으로 올리지 않는다.
- 런타임 의존성은 정확한 버전으로 고정한다(특히 google-genai와 업비트 클라이언트).
- 개발 의존성(dev 그룹): pytest, pytest-qt, pytest-cov, ruff, pyinstaller, hypothesis.
- 업비트 클라이언트: 공식 `upbit-sdk` 또는 httpx 기반 자체 클라이언트. 1단계에서 정해 ADR(docs/06-architecture/adr/)로 기록한다. `pyupbit`는 쓰지 않는다(2024-06 이후 유지보수 중단).
- 키 저장: `keyring`(Windows 자격 증명 관리자).

## CI 계약 (워크플로가 이 이름과 동작을 기대한다)

- `uv sync --locked`가 통과해야 한다.
- 린트는 `uv run ruff check .`, 테스트는 `QT_QPA_PLATFORM=offscreen uv run pytest -q`.
- PyInstaller 설정은 `packaging/autotrader.spec`: 폴더형(onedir), 창 모드(windowed), UPX 끔. 결과는 `dist/autotrader/autotrader.exe`.
- `autotrader.exe --self-test`: 창을 띄우지 않고 import, Qt(offscreen) 초기화, keyring 백엔드(Windows에서는 WinVaultKeyring), SQLite, TLS 인증서, 설정 경로를 점검한다. 결과를 현재 폴더의 `self-test-report.txt`에 쓰고 성공 0, 실패 1로 종료한다. 네트워크와 키는 쓰지 않는다.
- 워크플로는 `pyproject.toml`과 `packaging/autotrader.spec`이 생기기 전까지 해당 단계를 건너뛴다.

## 구조 원칙

- 매매 핵심 로직은 Qt에 의존하지 않는 `src/autotrader/core/`에 둔다. 화면(`ui/`)은 얇게 유지하고, 화면과 핵심 사이의 Qt 시그널은 앱 계층(`app/`)만 쓴다.
- 외부 연동은 인터페이스 뒤에 둔다: 거래소, 시세, 시그널(LLM), 알림, 시계. 테스트는 가짜 구현과 `tests/fixtures/`의 녹화 응답으로 한다.
- 일정은 monotonic 시간과 거래소 서버 시각으로 계산한다. PC 시계를 믿지 않는다.
- 런타임 데이터(DB, 로그, 캔들 캐시)는 `%LOCALAPPDATA%\upbit-autotrader\` 아래에 둔다. 저장소의 `data/`, `logs/`는 커밋하지 않는다.

## 업비트 API 주의 (2026-11 기준, https://docs.upbit.com/kr)

- 기본 URL `https://api.upbit.com`에 `/v1/...`를 붙인다. 슬래시 중복이나 끝 슬래시는 2026-11-16부터 오류다.
- 오류는 `error.name`으로 분기한다. `error.message`는 바뀔 수 있다.
- `Content-Type` 헤더는 한 번만 보낸다(중복이면 400). POST 본문은 JSON만 된다.
- 인증: JWT HS512, `nonce`는 매 요청 새 UUID, `query_hash`는 실제 전송 문자열의 SHA512. 페이로드에 시각이 없어서 PC 시계 오차는 인증에 영향이 없다.
- 주문: `identifier`를 DB에 먼저 저장하고 전송한다. 타임아웃이면 같은 `identifier`로 조회해 확인하고, 재전송하지 않는다(재사용 불가). `smp_type`은 항상 명시한다(2026-11-09부터 생략하면 cancel_maker).
- 수수료와 최소·최대 주문 금액은 `/v1/orders/chance`에서 읽는다. 하드코딩하지 않는다. 호가 단위 반올림 함수에는 테스트를 붙인다.
- 요청 한도: `Remaining-Req`의 `sec` 값을 쓴다(`min`은 폐기됨). 429면 다음 초까지 기다리고, 418이면 매매를 멈추고 알린다. `Origin` 헤더를 보내지 않는다(보내면 10초에 1회로 제한된다).
- 캔들: 요청당 최대 200개. 일봉 경계는 UTC 00:00(KST 09:00). 거래가 없던 구간은 캔들이 없다.
- 종목 경고: `/v1/market/all?is_details=true`의 `market_event.warning`(유의 종목)이나 `market_event.caution` 플래그가 하나라도 참이면 신규 매수를 막는다. 시세 웹소켓의 `market_state`·`delisting_date`와 비공개 웹소켓의 `announcement`도 반영한다.
- 키는 등록된 고정 공인 IP에서만 동작하고 1년 뒤 만료된다. 관련 오류(`no_authorization_ip`, `expired_access_key`)가 오면 매매를 멈추고 알린다.

## Gemini 시그널 주의

- SDK는 `google-genai`(`from google import genai`). 모델 ID는 설정값으로 둔다. 2.5 계열은 쓰지 않는다.
- 응답 스키마: `signal`(positive/negative/neutral), `confidence`, `reason`. Pydantic으로 검증한다. 검증 실패, 타임아웃, 429, 거절은 모두 `neutral`(매수 안 함)로 처리한다.
- 프롬프트에 키, 잔고, 주문 내역, 계정 정보를 넣지 않는다. 무료 등급 입력은 사람이 검토할 수 있다.
- 입력(시세·지표 요약)은 구분된 데이터 블록에 넣고, 그 안의 지시는 무시하라고 명시한다. 도구 호출은 쓰지 않는다. 뉴스는 수집하지 않는다(D-097). 모델은 검색 없이 받은 데이터만 근거로 답하고, 최근 뉴스나 사건을 아는 것처럼 말하지 않게 한다.
- 실제로 응답한 모델명과 입출력 원문을 DB에 기록한다.
- LLM 시그널의 성과를 과거 데이터로 백테스트하지 않는다(look-ahead bias). 백테스트는 규칙과 위험 관리 부분만 한다.

## 작업 방식

- 세션을 시작하면 이 파일, docs/01-planning/requirements.md, docs/10-management/roadmap.md의 해당 단계, docs/10-management/progress.md, 그 단계와 관련된 docs 문서를 읽고 계획부터 제시한다.
- 테스트를 먼저 쓴다. 외부 API는 가짜 구현이나 녹화 응답으로 테스트한다.
- 프론트/백엔드 세션은 하위 에이전트를 테스터 → 워커 → 리뷰어 순서로 쓰고, 워커의 모델·노력은 docs/10-management/roadmap.md "진행 방법"의 표를 따른다(D-077).
- 결정이 새로 생기거나 바뀌면 docs/10-management/decision-log.md에 먼저 기록하고 관련 문서를 고친다. 문서의 상태 표시("1단계 보완" 등)도 갱신한다.
- 세션을 마칠 때 docs/10-management/progress.md 맨 위에 기록(한 일, 결정, 남은 일, 다음 단계)을 추가하고 PR을 만든다.
- 화면 문구와 문서는 한국어, 코드 식별자는 영어로 쓴다.
- 커밋 메시지는 Conventional Commits 형식(feat, fix, docs, test, refactor, chore)에 한국어 설명을 붙인다.

## 명령

- 의존성 설치: `uv sync`
- 테스트: `QT_QPA_PLATFORM=offscreen uv run pytest -q`
- 린트: `uv run ruff check .`
