# PR 검토 기준

상태: 초안 · 2026-11-05 · 관련: [CLAUDE.md](../../CLAUDE.md), [위험 관리 정책서](../03-functional/risk-policy.md), [업비트 API 연동 명세](../05-integration/upbit-api.md), [테스트 전략](test-strategy.md), [불변식 명세](invariants.md), [추적표](traceability.md)

QA가 PR을 검토할 때 쓰는 기준이다. PR 종류(문서, 인프라, 기능)에 따라 1장 공통 항목과 해당 장의 항목을 본다. 여러 종류가 섞인 PR은 해당하는 장을 모두 본다. 항목 ID(RC-A01 등)는 검토 결과에서 근거로 쓴다.

| PR 종류 | 판단 기준(바뀐 파일) | 볼 장 |
|---|---|---|
| 문서 | `docs/`, `README.md`, `CLAUDE.md`만 | 1, 2 |
| 인프라 | `pyproject.toml`, `uv.lock`, `.python-version`, `packaging/`, `scripts/`, `.claude/`, `.gitignore`, CI 변경 제안 | 1, 3, 5 |
| 기능 | `src/`, `tests/` | 1, 4, 5 |

## 1. 모든 PR

| ID | 확인 항목 | 근거 |
|---|---|---|
| RC-A01 | 실제 키·토큰·비밀번호가 코드, 테스트, 녹화 파일, 커밋 메시지, PR 설명에 없다. `.env`, `*.pem`, `*.key`, `credentials*.json` 같은 키 파일을 추가하지 않았다 | CLAUDE.md 절대 규칙 |
| RC-A02 | 개인 정보(잔고, 주문 내역, IP 주소, 계정 정보, 사용자 이름이 든 경로)가 없다. 첨부한 로그·화면 캡처도 같다 | CLAUDE.md 절대 규칙(공개 저장소) |
| RC-A03 | 클라우드 세션에서 업비트 비공개(Exchange) API, 주문 API, 주문 테스트 API를 부른 흔적(스크립트, 테스트, 녹화 파일)이 없다 | CLAUDE.md 절대 규칙 |
| RC-A04 | `.github/workflows/`를 바꾸지 않았다. 바꿔야 하면 `docs/10-management/ci-proposals.md`에 변경안이 있고 PR 설명에 알렸다. 태그를 만들지 않았다 | CLAUDE.md GitHub 제약 |
| RC-A05 | PR이 맡은 단계·세션의 파일만 바꿨다. 다른 세션이 동시에 고치는 영역을 바꿨다면 이유가 PR 설명에 있다 | 작업 방식 |
| RC-A06 | 결정이 생기거나 바뀌었으면 결정 로그에 먼저 기록했고, 관련 문서와 상태 표시(확정, 초안, 1단계 보완, 제안)를 고쳤다 | CLAUDE.md 작업 방식 |
| RC-A07 | 진행 기록 맨 위에 한 일, 결정, 남은 일, 다음 단계를 추가했다 | CLAUDE.md 작업 방식 |
| RC-A08 | 커밋 메시지가 Conventional Commits(feat, fix, docs, test, refactor, chore)에 한국어 설명이다 | CLAUDE.md 작업 방식 |
| RC-A09 | 문서와 화면 문구는 한국어, 코드 식별자는 영어다 | CLAUDE.md 작업 방식 |
| RC-A10 | 위험 관리 규칙을 우회하는 옵션이나 디버그 플래그를 만들지 않았다. 기본 실행 모드는 paper다 | CLAUDE.md 절대 규칙 |
| RC-A11 | 수익을 약속하거나 투자 조언으로 읽힐 문구가 없다. 면책 문구를 지우거나 약하게 바꾸지 않았다 | 프로젝트 개요서 8장, 법·약관 검토 9장 |
| RC-A12 | 요구사항, TS, INV가 바뀌었으면 추적표를 함께 고쳤다 | 추적표 7장 |
| RC-A13 | 다른 열린 PR과 ID(TS-, D-, RSK-, MSG-, NTF-, ADR-, INV-)가 겹치지 않는다. 겹치면 나중에 병합되는 쪽이 번호를 옮긴다 | 문서 지도 ID 규칙 |
| RC-A14 | 초안(draft) PR이 아니고, PR을 만들기 직전에 최신 `origin/main`을 병합해 충돌을 풀었다(자동 병합 규칙). 사용자 결정이 필요한 항목은 결정 로그에 "제안"·"대기"로만 적었다 | CLAUDE.md GitHub 제약 |

## 2. 문서 PR

| ID | 확인 항목 |
|---|---|
| RC-B01 | 새 ID는 정해진 접두어를 쓰고 번호를 이어 붙였으며 겹치지 않는다(문서 지도 ID 규칙). |
| RC-B02 | 상대 링크와 앵커가 실제 파일·제목을 가리킨다. |
| RC-B03 | 외부 사실(API 동작, 버전, 가격, 날짜)에 출처 주소와 확인 날짜가 있다. 확인하지 못한 것은 "확인 필요"로 표시했다. |
| RC-B04 | 같은 사실이 문서끼리 맞다: 상태 이름, 한도 수치, 기본값과 범위(위험 관리 정책서 ↔ 설정 항목 정의서), 오류 이름(업비트 API 연동 명세 ↔ 시스템 구성도 오류 타입), 메시지 ID. |
| RC-B05 | 위험 관리를 느슨하게 하는 변경(한도 완화, 예외 추가, 손절 조건 변경)에는 결정 로그 근거와 사용자 승인이 있다. |
| RC-B06 | 상태나 전이를 바꾸면 상태 전이 정의서의 그림과 표, 매매 로직 명세의 의사코드, 테스트 시나리오가 함께 바뀌었다. |
| RC-B07 | Mermaid 그림이 렌더링되고 표의 열 수가 맞다. |
| RC-B08 | 새 문서를 만들거나 상태가 바뀌면 문서 지도(docs/README.md)의 목록과 상태를 고쳤다. |
| RC-B09 | 사용자 PC 절차(설치 가이드, 런북, 수동 점검표)의 메뉴 이름과 명령이 Windows 10 22H2와 맞다. |
| RC-B10 | 테스트 시나리오를 바꾸면 기대 결과가 검사 가능한 문장이다("잘 동작" 같은 말 대신 상태, 횟수, 메시지 ID). |

## 3. 인프라 PR

| ID | 확인 항목 | 근거 |
|---|---|---|
| RC-C01 | `requires-python = ">=3.13,<3.14"`, `.python-version`이 3.13이다 | CLAUDE.md 고정 기술 기준 |
| RC-C02 | PySide6가 `>=6.12,<6.13`이다(6.13 이상 금지) | CLAUDE.md, RSK-11 |
| RC-C03 | 런타임 의존성은 정확한 버전(`==`)이다. 특히 google-genai와 업비트 클라이언트 관련 패키지 | CLAUDE.md |
| RC-C04 | dev 그룹에 pytest, pytest-qt, pytest-cov, ruff, pyinstaller가 있다. 새 dev 의존성(예: hypothesis)은 CLAUDE.md 목록 갱신과 함께 넣었다 | CLAUDE.md, 불변식 명세 2.2절 |
| RC-C05 | `uv.lock`을 커밋했고 `uv sync --locked`가 통과한다 | CLAUDE.md CI 계약 |
| RC-C06 | `pyupbit`, `google-generativeai`(구 SDK)가 의존성 트리에 없다 | CLAUDE.md, LLM 시그널 명세 3장 |
| RC-C07 | 새 의존성의 라이선스가 MIT 배포와 맞고 의존성 라이선스 목록을 고쳤다. Windows 휠이 있고 PyInstaller 호환(훅, hidden import)을 확인했다 | 법·약관 검토 8장 |
| RC-C08 | `packaging/autotrader.spec`이 onedir, windowed, UPX 끔이고 결과가 `dist/autotrader/autotrader.exe`다 | CLAUDE.md CI 계약 |
| RC-C09 | `--self-test`가 창을 띄우지 않고, 네트워크와 키를 쓰지 않으며, 현재 폴더에 `self-test-report.txt`를 쓰고 성공 0·실패 1로 끝난다 | CLAUDE.md CI 계약, TS-123 |
| RC-C10 | CI 명령 이름이 그대로다: `uv run ruff check .`, `QT_QPA_PLATFORM=offscreen uv run pytest -q` | CLAUDE.md CI 계약 |
| RC-C11 | pytest 설정(`--strict-markers` 등)을 지키고 새 마커를 등록했다 | `pyproject.toml` |
| RC-C12 | `.gitignore`가 런타임 데이터(`data/`, `logs/`, `*.db`), 비밀 파일, `.hypothesis/`를 막는다 | CLAUDE.md 구조 원칙 |
| RC-C13 | 스크립트와 SessionStart 훅이 비밀을 출력하지 않고, 허용된 도메인 밖으로 나가지 않는다 | 보안 정책 4장 |
| RC-C14 | Windows 10에서 달라질 수 있는 것(러너 라벨, Qt 플러그인, 한글이 든 사용자 경로)을 고려했다 | 기술 스택 2장 |

## 4. 기능 PR

### 4.1 구조

| ID | 확인 항목 | 근거 |
|---|---|---|
| RC-D01 | core가 Qt(PySide6, shiboken6)와 ui·app 계층을 import하지 않는다. Qt 시그널은 app 계층만 쓴다 | CLAUDE.md 구조 원칙, `tests/unit/test_architecture.py` |
| RC-D02 | 외부 연동(거래소, 시세, 뉴스, 시그널, 알림, 시계, 비밀 저장소)은 인터페이스 뒤에 있고 core가 어댑터 구현을 직접 import하지 않는다 | CLAUDE.md 구조 원칙 |
| RC-D03 | core가 `time.time`, `time.monotonic`, `datetime.now`, `asyncio.sleep`을 직접 부르지 않고 Clock을 쓴다 | INV-16 |
| RC-D04 | 런타임 데이터는 `%LOCALAPPDATA%\upbit-autotrader\` 아래에만 쓴다 | CLAUDE.md 구조 원칙 |
| RC-D05 | 금액·수량·가격은 Decimal이고 float가 없다. 위험 한도 비교는 반올림 전 Decimal로 하고, 정수 원 합계는 화면·알림·CSV에만 쓴다. JSON 숫자는 `parse_float=Decimal`로 읽는다 | INV-14, 데이터 모델 2장 |

### 4.2 위험 관리 정책

| ID | 확인 항목 | 근거 |
|---|---|---|
| RC-D06 | 모든 주문이 위험 관리 승인 객체를 거친다. 우회 인자, 플래그, 환경 변수가 없다 | 위험 관리 정책서 1장, INV-08 |
| RC-D07 | 한도, 수수료, `min_total`·`max_total`을 하드코딩하지 않는다(설정과 `/v1/orders/chance`). 키 없는 paper가 쓰는 공식 문서 값은 "추정값"으로 표시한다(D-059 대기) | 위험 관리 정책서 2장, 매매 로직 명세 7장 |
| RC-D08 | 상태별 허용 동작 표를 지키고, 보내기 직전에 상태를 다시 확인한다 | 상태 전이 정의서 2장, INV-02 |
| RC-D09 | 결과 불명·끝나지 않은 주문이 있는 코인에 새 주문을 만들지 않고, 같은 코인에 매수·매도를 함께 걸지 않는다 | INV-04, INV-05 |
| RC-D10 | 손절은 60초마다 점검하고, 일일 주문 수 상한·일일 손실 한도가 손절을 막지 않는다. 최소 주문 간격은 거래소가 접수한 주문만 세고, 손절·청산의 429 재시도는 간격을 기다리지 않는다(D-061) | 위험 관리 정책서 2장, INV-09 |
| RC-D11 | 모든 거부와 차단을 이유 코드와 함께 기록한다 | 위험 관리 정책서 1장 |
| RC-D12 | 한도를 느슨하게 바꾸면 확인(MSG-C006)을 받고 엄격하게 바꾸면 바로 적용한다. live에서 바뀌면 이벤트와 알림을 남긴다 | 위험 관리 정책서 8장 |
| RC-D13 | live-validate와 live는 실전 전환 게이트를 지나야만 켜지고, 설정 파일로 건너뛸 수 없다 | 위험 관리 정책서 6장, INV-19 |
| RC-D14 | 시세조종으로 오해받을 주문이 없다: 자기 주문끼리 체결 없음, 최소 주문 간격과 일일 주문 수 상한, 걸었다 취소하는 반복 없음 | CLAUDE.md 절대 규칙, INV-12 |

### 4.3 업비트 API 규칙

| ID | 확인 항목 | 근거 |
|---|---|---|
| RC-D15 | URL은 기본 URL `https://api.upbit.com`에 `/v1/...`를 붙인 것이고 끝 슬래시와 중복 슬래시가 없다(문자열 이어 붙이기 대신 경로 상수) | CLAUDE.md, 경로 형식 공지(2026-11-16) |
| RC-D16 | `Origin` 헤더가 없다. 같은 헤더를 두 번 보내지 않는다(라이브러리 기본 헤더 포함). POST는 JSON 본문과 `Content-Type` 하나, DELETE는 쿼리 파라미터만 | CLAUDE.md, 헤더 중복 공지(2026-07-31) |
| RC-D17 | JWT는 HS512, 요청마다 새 nonce(UUID), `query_hash`는 URL 인코딩 전 실제 쿼리 문자열의 SHA512(배열은 키 반복, POST는 JSON 본문을 `key=value&...`로), Secret Key는 Base64 디코딩 없이 쓴다 | CLAUDE.md, 인증 문서 |
| RC-D18 | 모든 주문에 `smp_type`을 명시한다(`cancel_maker`). `post_only`를 쓰지 않는다 | CLAUDE.md, SMP 공지(2026-11-09), INV-06 |
| RC-D19 | identifier를 DB에 먼저 커밋한 뒤 보낸다. 64자 이하이고 공백·`+`가 없으며 다시 쓰지 않는다. 주문 POST에 HTTP 클라이언트·SDK 자동 재시도가 없다. 타임아웃이면 같은 identifier로 조회해 확인한다 | CLAUDE.md, INV-03 |
| RC-D20 | 오류는 `error.name`으로 분기하고 `error.message`로 분기하지 않는다. `out_of_scope`는 401·403 모두 처리한다. 시세 API의 숫자 `name`을 처리한다. 모르는 이름은 HTTP 상태로 분류하고 원문을 기록한다 | CLAUDE.md, REST API 안내 |
| RC-D21 | `Remaining-Req`는 `sec`만 쓴다. 요청 한도 버킷은 업비트 API 연동 명세 4장의 경로별 표로 고르고, 응답의 group 값이 표와 다르면 경고만 남긴다(캔들 그룹은 `candles`). 그룹별 한도의 절반 이하다. 429: GET은 다음 초에 같은 요청, 주문 POST는 REJECTED 뒤 새 identifier로 위험 검사부터. 418: SUSPENDED + 알림 | CLAUDE.md, INV-13 |
| RC-D22 | 종목 경고는 `market_event.warning`과 `caution`의 모든 항목으로 판정한다. 폐기된 `market_warning`, 웹소켓의 `is_trading_suspended`·`market_warning`을 쓰지 않는다 | CLAUDE.md, 가짜 구현 명세 2.8절 |
| RC-D23 | 캔들은 요청당 200개 이하, 진행 중 캔들과 빈 구간을 정해진 대로 다룬다. 일봉 경계는 UTC 00:00이다 | CLAUDE.md |
| RC-D24 | 키·IP 오류(`no_authorization_ip`, `expired_access_key` 등)는 live 계열에서 HALTED + 알림, paper·signal-only에서 경고다 | 상태 전이 정의서 2장 |
| RC-D25 | 웹소켓은 30~60초마다 PING을 보내고, 재연결 뒤 REST로 대조하며, 바이너리 프레임을 처리한다 | 업비트 API 연동 명세 2장 |
| RC-D26 | 호가 단위 반올림 함수에 테스트가 있다 | CLAUDE.md |

### 4.4 Gemini 규칙

| ID | 확인 항목 | 근거 |
|---|---|---|
| RC-D27 | `google-genai`를 정확한 버전으로 쓰고(`from google import genai`), 모델 ID는 설정값이며 2.5 계열이 아니다 | CLAUDE.md Gemini 시그널 주의 |
| RC-D28 | 응답을 Pydantic으로 검증하고, 검증 실패·타임아웃·429·거절은 모두 neutral이며 예외가 밖으로 나가지 않는다. 403(`permission_denied`)은 다시 시도하지 않고 LLM 호출을 멈춘다(MSG-E018) | CLAUDE.md, INV-15 |
| RC-D29 | 프롬프트에 키, 잔고, 주문 내역, 계정 정보, IP가 없다. 뉴스 제목은 구분된 데이터 블록에 넣고 그 안의 지시를 무시하라고 적었으며 길이를 제한한다. 도구 호출을 쓰지 않는다 | CLAUDE.md, INV-07 |
| RC-D30 | 실제 응답 모델명과 입출력 원문을 DB에 기록한다. SDK 자동 재시도에서 429를 뺐고 호출 전체에 시간 상한이 있다 | CLAUDE.md, LLM 시그널 명세 3장 |
| RC-D31 | LLM 시그널 성과를 과거 데이터로 백테스트하지 않는다 | CLAUDE.md |

### 4.5 텔레그램·뉴스·기록·화면

| ID | 확인 항목 | 근거 |
|---|---|---|
| RC-D32 | 텔레그램 토큰이 든 URL이 로그·예외 메시지에 남지 않는다. 일반 텍스트, 4096자, 초당 1건, 429는 `retry_after` 뒤 다시. 전송이 실패해도 매매가 계속된다 | 텔레그램 연동 명세 |
| RC-D33 | 뉴스는 공식 API와 RSS만 쓰고, 제목·링크·출처·시각만 저장한다. 본문을 저장하거나 LLM에 보내지 않는다 | 뉴스 수집 명세 1장 |
| RC-D34 | 로그 가리기 필터를 지나고, events·order_events의 payload에 비밀이나 요청 헤더가 없다 | 로그·감사 기록 정의서 2장, INV-07 |
| RC-D35 | 화면 문구는 메시지 정의서의 ID를 쓰고 원인과 해결 방법이 있다. 상태는 색과 글자를 함께 쓰고, 키는 앞 4자리만 보인다 | 화면 정의서 공통 규칙 |
| RC-D36 | 네트워크·DB 작업이 GUI 스레드를 막지 않는다. 긴급 정지 두 버튼이 대시보드와 트레이 메뉴에 있다 | NFR-05, 위험 관리 정책서 3장 |

## 5. 테스트와 커버리지

| ID | 확인 항목 | 근거 |
|---|---|---|
| RC-E01 | 바뀐 동작의 테스트가 같은 PR에 있다. 정상 경로와 실패 경로를 모두 시험한다 | CLAUDE.md 작업 방식(테스트 먼저) |
| RC-E02 | 테스트 docstring 첫 줄에 시험하는 TS·INV ID가 있다 | 추적표 7장 |
| RC-E03 | 외부 API는 가짜 구현과 녹화 응답으로만 시험한다. 실제 네트워크에 나가지 않는다 | 테스트 전략 1장, 가짜 구현 명세 |
| RC-E04 | 키는 가짜 값(카나리아)만 쓰고, 실제 형식의 키 문자열을 소스에 상수로 적지 않는다 | CLAUDE.md, 가짜 구현 명세 7장 |
| RC-E05 | 녹화 파일(`tests/fixtures/upbit/`)을 고치지 않았다. 새로 녹화했으면 그 폴더의 README를 고쳤다 | 녹화 응답 README |
| RC-E06 | 실제 시간에 기대지 않는다(실제 `sleep` 없음, FakeClock 사용). 실행 순서·병렬에 따라 결과가 달라지지 않는다 | 가짜 구현 명세 1.2절 |
| RC-E07 | 위험 관리·주문 관리·상태 전이를 바꾸면 해당 불변식의 속성 기반 테스트가 있거나 고쳐졌다 | 불변식 명세 |
| RC-E08 | 안전 성질 테스트가 공허하지 않다(주문이 실제로 나가는 경우도 시험, INV-09) | 불변식 명세 2.2절 |
| RC-E09 | 커버리지: core 줄 80% 이상, 위험 관리·주문 관리 분기 100%(목표). PR 설명에 측정값이 있다 | 테스트 전략 5장 |
| RC-E10 | `uv run ruff check .`와 `QT_QPA_PLATFORM=offscreen uv run pytest -q`가 통과하고 ci.yml이 통과한다. 코드·패키징이 바뀌었으면 build-exe.yml도 통과한다 | CLAUDE.md CI 계약, 테스트 전략 5장 |
| RC-E11 | `skip`·`xfail`에는 이유가 있고, `xfail_strict`를 끄지 않았다 | `pyproject.toml`의 pytest 설정 |
| RC-E12 | 새 테스트 시나리오를 만들었으면 테스트 시나리오 문서와 추적표에 추가했다 | 추적표 7장 |

## 6. 검토 절차

`gh`는 REST만 쓴다(`gh pr`은 403). 아래에서 `N`은 PR 번호, `BRANCH`는 PR의 브랜치 이름, `SHA`는 1번에서 본 마지막 커밋 해시다.

1. PR 정보와 바뀐 파일을 본다.

```bash
gh api repos/khy920723/upbit-autotrader/pulls/N --jq '{title, head: .head.ref, sha: .head.sha, body}'
```

```bash
gh api repos/khy920723/upbit-autotrader/pulls/N/files --paginate --jq '.[] | "\(.status)\t+\(.additions)/-\(.deletions)\t\(.filename)"'
```

2. 브랜치를 받아 main과 비교한다.

```bash
git fetch origin BRANCH
```

```bash
git diff --stat origin/main...FETCH_HEAD
```

3. 자동으로 찾을 수 있는 것을 먼저 찾는다(결과는 사람이 판단한다).

```bash
git diff --name-only origin/main...FETCH_HEAD -- .github/workflows
```

```bash
git diff origin/main...FETCH_HEAD | grep -nE '^\+.*(eyJ[A-Za-z0-9_-]{10,}\.|Bearer [A-Za-z0-9]|api\.telegram\.org/bot[0-9]|[0-9]{8,10}:[A-Za-z0-9_-]{35}|AIza[0-9A-Za-z_-]{35}|([0-9]{1,3}\.){3}[0-9]{1,3})'
```

```bash
git diff origin/main...FETCH_HEAD | grep -nE '^\+.*(Origin|max_retries|retries=|parse_float|float\(|time\.time\(|datetime\.now\(|asyncio\.sleep\()'
```

4. CI 결과를 본다.

```bash
gh api repos/khy920723/upbit-autotrader/commits/SHA/check-runs --jq '.check_runs[] | "\(.name)\t\(.status)\t\(.conclusion)"'
```

5. 코드가 있는 PR은 브랜치에서 직접 돌린다.

```bash
uv sync --locked
```

```bash
uv run ruff check .
```

```bash
QT_QPA_PLATFORM=offscreen uv run pytest -q --cov --cov-branch --cov-report=term-missing
```

6. 1장과 PR 종류에 맞는 장의 항목을 하나씩 확인하고 7장 형식으로 결과를 쓴다.

## 7. 결과 작성 형식

담당 세션에 그대로 붙여 넣을 수 있게 쓴다. 고칠 점마다 항목 ID, 위치(파일:줄), 문제, 근거, 고칠 방법, 확인할 테스트를 적는다.

- **필수:** 병합하기 전에 고친다(절대 규칙, 위험 관리, 업비트 API 규칙 위반, 테스트 실패, 비밀·개인 정보). `claude/` 브랜치 PR은 검사를 통과하면 자동으로 병합되므로, 검토가 끝나기 전에 병합됐으면 최신 main에서 새 브랜치를 만들어 고친다(CLAUDE.md).
- **권장:** 이번 PR에서 고치면 좋지만 병합을 막지 않는다.
- **질문:** 의도를 확인해야 판단할 수 있다.

```text
[PR #N 검토 결과] 담당: <세션 이름> · 판정: 수정 필요 | 승인 가능
아래를 고쳐 주세요. PR이 열려 있으면 같은 브랜치에 push하고, 이미 병합됐으면 최신 main에서 새 브랜치를 만들어 새 PR을 여세요.

필수
1. [RC-D19] src/autotrader/adapters/upbit/client.py:120 — 주문 POST에 HTTP 클라이언트 자동 재시도가 켜져 있다.
   근거: CLAUDE.md "업비트 API 주의", 불변식 INV-03.
   고칠 방법: 주문 POST는 재시도하지 않고 타임아웃이면 UNKNOWN 절차로 넘긴다.
   확인할 테스트: FakeExchange timeout_after_accept에서 orders_received(identifier) == 1 (TS-103).

권장
2. [RC-E02] tests/unit/test_risk.py — 테스트 docstring에 TS·INV ID가 없다. 예: """TS-99, INV-01: ..."""

질문
3. [Q-01] 손절 매도에 최소 주문 간격을 적용한 이유가 있나? 정책서 1장 원칙 2와 맞는지 확인이 필요하다.

확인한 것: ruff 통과, pytest 통과(개수), 커버리지(core 줄 %, 위험 관리 분기 %), 비밀 검사 0건, 워크플로 변경 없음.
```
