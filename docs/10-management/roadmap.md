# 로드맵

상태: 확정 · 2026-11-03 작성, 2026-11-05 세션 운영 방식 갱신(D-073~D-075, D-077) · 클라우드 세션은 역할 4개로 운영하고, 단계는 그 역할 세션에 이어서 지시한다(아래 "진행 방법").

## 진행 방법

### 세션 역할 (D-073)

클라우드 세션은 아래 역할 4개만 운영한다. 세션은 역할마다 하나(최대 4개)다. 단계가 바뀌어도 새 세션을 만들지 않고, 그 일을 맡은 역할 세션에 이어서 지시한다.

| 세션 | 맡는 일 | 로드맵 단계 |
|---|---|---|
| 기획/문서 | 설계·ADR, 결정 로그, 문서 갱신, 리서치(규칙 비교 같은 분석) | 1단계, 이후 문서 전반 |
| 인프라 | 프로젝트 뼈대, 의존성·버전 고정, PyInstaller 패키징, self-test, CI 변경 제안, 릴리스 절차 | 2단계, 이후 빌드·배포 전반 |
| 프론트/백엔드 | 앱 기능 코드: 업비트 연동, LLM 시그널, 매매 엔진, 화면, 앱 내 운영 기능 | 3~7단계 |
| QA | PR 검토, 테스트 시나리오 대조와 보강, 위험 관리 규칙 검증, Windows 수동 점검표, 페이퍼 운영 평가 | 단계마다, 8단계 |

- 규칙 조건 비교 리포트를 만든 분석 세션은 그 PR이 병합되면 보관한다. 규칙 관련 후속 작업(ADR-0007 등)은 기획/문서 세션이 맡는다.

### 단계 시작

단계를 시작할 때는 그 단계를 맡은 역할 세션에 이렇게 보낸다.

```text
docs/10-management/roadmap.md의 N단계(이름)를 진행해줘.
먼저 CLAUDE.md, docs/01-planning/requirements.md, docs/10-management/progress.md와 그 단계 관련 문서를 읽고 계획부터 보여줘.
테스트를 먼저 쓰고, 실제 키나 실제 주문은 쓰지 마.
끝나면 docs/10-management/progress.md를 갱신하고 PR을 만들어줘.
```

- 이어서 지시하는 세션은 시작한 뒤에 CLAUDE.md가 바뀌었을 수 있으므로 맨 앞에 "CLAUDE.md를 다시 읽고"를 붙인다.

### PR과 병합 (D-074)

- PR은 `claude/` 브랜치에서 초안이 아닌 상태로 연다. 필수 검사(`test`, `windows`)를 통과하면 자동으로 squash 병합된다.
- 세션은 PR을 만들기 직전에 최신 main을 병합해 충돌을 푼다. 이미 병합된 PR에 이어서 할 일은 최신 main에서 새 브랜치를 만들어 새 PR로 올린다.
- 자동 병합은 사용자 확인이 아니다. 사용자가 정할 항목은 결정 로그에 "대기"로 남기고, 사용자가 확인한 뒤 바꾼다.
- PR 열림·새 커밋·병합과 ci·build-exe 결과는 디스코드 채널로 알림이 간다(D-075). 이 알림은 필수 검사가 아니라서 실패해도 자동 병합을 막지 않는다.

PR이 생기면 Changes 카드에서 PR의 ⋮ 메뉴를 열어 Auto-fix를 켠다. 테스트나 빌드가 실패하면 Claude가 원인을 찾아 고친다. 빌드 설정 파일 자체는 고치지 못한다.

### 프론트/백엔드 하위 에이전트 (D-077)

프론트/백엔드 세션은 작업마다 하위 에이전트를 이 순서로 쓴다: 테스터(테스트 먼저) → 워커(구현) → 리뷰어(최종 검증). 리뷰는 1회, 수정은 1회다.

- 워커는 코드 작성 토큰을 아끼려고 작업 난이도에 따라 모델과 노력을 고른다. Agent 도구나 Workflow `agent()`의 model·effort 값으로 지정한다.
- 아래 표의 값은 지휘 세션의 제안이며, 사용자가 바꿀 수 있다.

| 난이도 | 예 | model | effort |
|---|---|---|---|
| 쉬움 | 정해진 패턴 반복, 이름·상수·설정 추가, 픽스처 데이터, 린트 수정 | haiku | low |
| 보통 | 명세가 분명한 단일 모듈(순수 함수, 데이터 모델, 파서, 화면 배치) | sonnet | medium |
| 어려움 | 여러 모듈에 걸친 설계, 상태 기계·동시성, 원인 불명 버그 | opus | high |

- 위험 관리, 주문, 인증 서명, 키, 재시도 코드는 크기와 상관없이 "어려움"이다.
- 난이도가 애매하면 한 단계 위로 고른다.
- 테스트 실패나 리뷰 지적을 고치는 수정 회차는 한 단계 올린다(최고 opus·high).
- 테스터와 리뷰어는 낮추지 않고 세션 모델을 쓴다.
- PR 설명에 작업별로 실제로 쓴 모델과 노력을 적는다.

## 단계

### 0단계: 준비 (완료)

- 저장소, CI 설정, 기획 문서 일체([문서 지도](../README.md)), LICENSE(MIT)

### 1단계: 설계 (Plan 모드)

- 결정(ADR 0006~0009): 업비트 클라이언트, 규칙 조건(후보와 장단점을 정리해 사용자가 선택), 매수 방식, GUI와 asyncio 연결
- 그 밖의 결정: 설정 파일 형식, DB 접근 방식, 공인 IP 확인 방법, 단일 인스턴스 방법, 기본 모델 ID, 지표 요약 항목, 프롬프트 첫 버전, 4시간 평가 시각 정렬, 규칙상 청산 조건
- 확인할 것: 업비트 키 목록·만료일 조회 API, 포켓별 키 발급 방식, 잔고 대조 규칙 세부, 결과 불명 주문 조회 간격, Gemini 429 오류 구분 방법
- 문서의 "1단계 보완" 부분 채우기: 매매 로직 명세, 데이터 모델, 시스템 구성도, 설정 항목(rules, buy, exit)
- 2026-11-05 세션에서 정하지 않은 기본 모델 ID, 지표 요약 항목, 프롬프트 첫 버전은 4단계 시작 전으로 옮기자고 제안했다(D-066 대기). 규칙 조건과 규칙상 청산 조건은 별도 세션의 비교 리포트를 기다린다(D-021)
- 완료 기준: 문서 PR 승인

### 2단계: 뼈대 + 빌드 검증

- uv 프로젝트, 빈 창 앱, 설정·로그·SQLite 초기화, `--self-test`, `packaging/autotrader.spec`, 의존성 라이선스 목록
- 완료 기준: CI와 Windows 빌드 통과. 사용자가 Windows 10 PC에서 빈 앱 실행과 self-test 통과를 확인

### 3단계: 업비트 연동 (완료)

- 시작 전에 정할 것: 업비트 클라이언트(D-038, [ADR-0006](../06-architecture/adr/0006-upbit-client.md))와 GUI–asyncio 연결(D-040, [ADR-0009](../06-architecture/adr/0009-gui-asyncio-bridge.md)). 둘 다 2026-11-05 사용자 결정으로 정했다(추천안 A)
- JWT 서명(알려진 값 테스트), 요청 한도, 오류 매핑, `/v1/orders/chance`, 호가 단위, 종목 목록과 경고, 시세·비공개 웹소켓(재연결 후 REST로 대조), 가짜 거래소
- 완료 기준: 가짜 거래소로 테스트 통과
- 완료(QA 확인 2026-11-06, [PR #24](https://github.com/khy920723/upbit-autotrader/pull/24)): 3a(REST 클라이언트·서명·요청 한도·오류 매핑·주문 가능 정보·호가 단위·종목 경고·REST 가짜 거래소) [PR #17](https://github.com/khy920723/upbit-autotrader/pull/17) 병합(2026-11-05). 3b(시세·비공개 웹소켓, 재연결 감시와 재연결 뒤 대조 자리, 웹소켓 가짜, TLS 설정 통일, 테스트 중 네트워크 차단) [PR #22](https://github.com/khy920723/upbit-autotrader/pull/22) 병합(2026-11-06). QA 권장 지적(R17·R22)은 프론트/백엔드 정리 PR에서 고친다

### 4단계: LLM 시그널(Claude Code CLI, 웹 검색)

- 이름과 범위를 바꿨다.
  - 2026-11-07: 뉴스를 뺐다(D-097).
  - 2026-11-09: 시그널 출처를 Gemini에서 매매 PC의 Claude Code CLI 세션으로 바꿨다(D-108).
  - 2026-11-10: 시그널에 Claude 웹 검색을 쓴다(D-112). 매수 근거는 예상 결과 보고서 전체다(D-114).
  - 이전 이름은 "뉴스 + LLM 시그널", "LLM 시그널(뉴스 없음)", "LLM 시그널(Claude Code CLI, 뉴스 없음)"이다.
- 정한 것(2026-11-07):
  - 네이버 검색 API를 뺐다(D-095). 스크래핑·구글 검색 대체도 쓰지 않는다.
  - Cointelegraph를 뺐다(D-096).
  - 뉴스 없이 지표만 쓴다(D-097). "LLM 입력은 시세·지표 요약만" 부분은 D-112로 대체됐다.
  - RSS 티커 겹침(D-101)은 대체됐다.
- 정한 것(2026-11-09):
  - 규칙상 청산 없음(D-105).
  - 방향만 정한 것: 캔들 단위는 사용자 입력(D-106), 시그널은 Claude Code CLI(D-108). 규칙 조건을 보고서로 고르는 방식(D-107)은 D-114로 대체됐다.
  - Gemini 결정(D-004·D-054·D-055·D-098·D-102·D-103)은 대체됐다.
- 정한 것(2026-11-10):
  - 보고서 세션 보안(D-109): 앱과 같은 계정 + 권한 규칙, 앱이 내보낸 파일만, 네트워크 도구 없음, 동작 지표만 내보냄.
  - Claude 접속은 개인 요금제 로그인(D-110, 사용자 판단).
  - 시그널 호출 격리는 보고서 세션과 같게(D-111).
  - 장 열림·마감은 하루 경계 KST 09:00(D-113).
  - 방향만 정한 것: 시그널에 웹 검색(D-112), 매수 근거는 예상 결과 보고서(D-114). D-006은 대체됐다.
  - 기반 결정 D-041·D-042·D-044는 유효가 됐다.
- 시작 전에 정할 것([결정 묶음](../03-functional/stage4-decisions.md) 1장):
  - [분석 보고서 세션 제안서](../03-functional/analysis-report-session.md) 12장 질문 28개(안전 S1~S8, 규칙 R1~R12, 기술 T1~T8).
  - 그 뒤 D-057·D-045·D-099(대체 후보)와 D-100(지시문).
- `llm.max_output_tokens` 값은 이 단계에서 실제 응답 길이를 재서 정한다(D-066). D-108로 Claude Code의 `CLAUDE_CODE_MAX_OUTPUT_TOKENS` 기준으로 본다(제안서 9.1절).
- 범위(제안서 11장 선택지 T8로 정한다):
  - Claude Code CLI 시그널 실행(웹 검색, 스키마 검증, 실패·시간 초과·사용량 한도는 neutral).
  - 선택에 따라 예상·결과 보고서 순환(내보내기, 보고서 실행, 판정 검증, 결과 채점).
  - 입출력 원문·응답 모델명·CLI 버전 기록, 가짜 LLM(Claude Code CLI 출력 흉내).
  - 앱이 뉴스를 모으지 않는 것을 유지할지는 제안서 S7로 정한다.
- 완료 기준: signal-only 모드 동작

### 5단계: 규칙·위험·주문 관리 + 페이퍼

- 정한 것(2026-11-05): 분할 매수·매도(D-082~D-085, [분할 매수·매도 설계](../03-functional/split-trading.md))와 주문 유형(D-043). 2단계 하락률 기본값은 2%(D-086, 2026-11-06)
- 규칙 조건, 위험 관리(분할 매수 최대 2단계, 익절 최대 2단계 포함), 주문 관리(identifier 먼저 저장, 조회로 확인), 페이퍼 체결(수수료·슬리피지), 일정(LLM 4시간, 손절 1분), 재진입 옵션, LLM 부정 매도 옵션, 규칙 부분 백테스트
- 2026-11-10: D-114로 "규칙 조건"은 예상 결과 보고서 판정으로, "LLM 4시간" 일정은 순환 시각(결과 KST 09:00, 예상은 사용자 시간값)으로 바뀐다. 범위는 제안서 답(R1·R2·T8) 뒤에 고친다
- 완료 기준: 장애 시나리오(타임아웃, 429/418, 연결 끊김, 재시작) 테스트 통과

### 6단계: 화면

- 첫 실행 마법사, 코인 선택, 메인 창, 시그널·거래 기록, 설정, 트레이, 긴급 정지 2종, 실전 전환 화면, 시작 앱 등록, 중복 실행 방지
- 완료 기준: pytest-qt 테스트 통과

### 7단계: 운영 기능

- 디스코드 알림(D-081), 절전 방지, 잠자기 복귀·재시작 후 재동기화, 시계 오차 점검, 키 만료 알림, 데이터 끊김 감시, CSV 내보내기, 로그 회전, DB 백업, 가린 진단 묶음(범위는 시작 전에 정함, D-066 대기)
- 완료 기준: 재시작 시나리오 테스트 통과

### 8단계: v0.1 페이퍼 실사용

- Windows 10 PC에서 28일 이상 paper로 운영한다. 버그 수정은 프론트/백엔드 세션에 이어서 지시한다(D-073)
- 완료 기준: [페이퍼 운영 평가 기준](../08-quality/paper-evaluation.md)의 기록 확보

### 9단계: 실전 전환

- 실전 전에 업비트 Open API 약관 확인(사용자)
- live-validate로 며칠 운영 → 서브 포켓에 소액을 넣고 live
- 완료 기준: 사용자 판단

## 사용자 작업

### 클라우드 세션 준비

1. Claude GitHub App을 이 저장소에 설치한다. Auto-fix에 필요하다.
2. 클라우드 환경을 새로 만든다.
   - Network access: Custom. Allowed domains에 `api.upbit.com`을 넣고 "Also include default list of common package managers"를 체크한다.
   - 환경 변수와 비밀값은 넣지 않는다.
   - Setup script:

```bash
#!/bin/bash
apt-get update -qq || true
apt-get install -y -qq --no-install-recommends libgl1 libegl1 libdbus-1-3 libxkbcommon0 libfontconfig1 || true
exit 0
```

### 빌드, 설치, 계정, Windows 설정

- 빌드 받기: [빌드·배포 절차](../09-operations/build-release.md)
- 계정·키 준비, Windows 설정, 설치: [설치·초기 설정 가이드](../09-operations/install-guide.md)

## 검증된 외부 사실 (2026-11-03 기준, 2026-11-05 1단계에서 추가, 2026-11-07 4단계 전 확인 추가)

> Gemini·google-genai 행은 D-108(2026-11-09)로 쓰지 않는 기록이다. Claude Code CLI와 Anthropic 약관 사실은 [분석 보고서 세션 제안서](../03-functional/analysis-report-session.md) 15장 출처에 있다.

| 주제 | 내용 | 출처 |
|---|---|---|
| 클라우드 세션 | `.github/workflows` push 불가(GitHub App에 workflow 권한 없음), 태그 push 불가, gh는 REST만 | code.claude.com/docs/en/claude-code-on-the-web, /cloud-environments; anthropics/claude-code-action FAQ |
| 클라우드 VM | Ubuntu 24.04 x86_64, 약 4 vCPU·16GB·30GB, Python·uv·pytest·ruff 포함, 유휴 시 일시정지 | code.claude.com/docs/en/cloud-environments |
| 클라우드 네트워크 | Trusted 목록에 업비트 없음 → Custom으로 api.upbit.com 추가 | 같은 문서 |
| Qt | 6.12가 Windows 10(1809+)을 지원하는 마지막 버전, 6.12는 LTS | doc.qt.io/qt-6/supported-platforms.html |
| Python | 3.13·3.14는 Windows 10 지원, 3.12는 Windows 바이너리 배포 종료 | docs.python.org/3/using/windows.html |
| PyInstaller | 6.22.x, Python 3.8~3.15, onedir 먼저 권장, UPX 비권장 | pyinstaller.org |
| GitHub Actions | windows-latest = Server 2025, ubuntu-latest는 2026-11에 26.04로 이동 → 라벨 고정 | github.com/actions/runner-images |
| 업비트 키 | 고정 공인 IPv4 필수(최대 10개), 1년 유효·연장 불가, KYC·2채널 인증 후 PC 웹에서만 발급 | docs.upbit.com/kr/docs/api-key |
| 업비트 요청 한도 | 시세 그룹별 초당 10회(IP), 주문 초당 12회(포켓), 반복 위반 시 418 차단. 캔들 그룹 이름은 한도표에 `candle`, 실제 `Remaining-Req` 헤더와 공식 예제에는 `candles`(2026-11-05 공개 시세 호출로 확인) | docs.upbit.com/kr/reference/rate-limits, /docs/first-quotation-api-call, /docs/rest-api-best-practice |
| 업비트 변경 | 헤더 중복 400(2026-07-31), smp_type 기본값 변경(2026-11-09), 경로 형식 오류 처리(2026-11-16) | docs.upbit.com/kr/changelog |
| 업비트 테스트 | 테스트넷 없음, `/v1/orders/test`는 주문 형식만 검증 | docs.upbit.com/kr/reference/order-test |
| 업비트 공지 | 비공개 웹소켓 `announcement`(2026-08-31부터), upbit.com 수집은 robots.txt로 금지 | docs.upbit.com/kr/reference/websocket-announcement |
| Gemini | 무료 등급 한국 이용 가능, 한도는 AI Studio에서만 표시·프로젝트 단위·보장 없음, 무료 등급 입력은 사람 검토 가능 | aistudio.google.com/docs/rate-limits, /docs/terms |
| Gemini SDK | google-genai(Python 3.11+), 구 SDK 지원 종료, gemini-2.5-pro·2.5-flash 폐기(2026-11-02) | pypi.org/project/google-genai, aistudio.google.com/docs/changelog |
| 검색 연동 | Gemini 3 이상은 무료 등급에서 Google 검색 연동 불가 | aistudio.google.com/docs/pricing |
| 뉴스 | 네이버 검색 API 하루 25,000회 무료, CryptoPanic 무료 플랜 없음, Google 뉴스 RSS는 개인 리더 용도로 제한 | developers.naver.com, cryptopanic.com |
| 뉴스 약관 | 네이버 검색 API 특약 2.3: 데이터를 AI에 입력·학습·평가 등에 쓰는 행위와 2.4 범위(기기 24시간 또는 새 질의까지, 서버 이력 조회 21일)를 넘는 저장 금지. 개발자센터 검색 API 신규 신청은 2026-07-30 종료, 기존 이용자는 2027-06-30까지, 그 뒤 NAVER API HUB. Cointelegraph 약관 3절: 서면 동의 없는 AI·LLM 이용(학습, 운영 등) 금지. CoinDesk 약관은 자동 접근 검사 화면 때문에 읽지 못함(2026-11-07 확인) | developers.naver.com/products/terms(2026-10-07 개정), cointelegraph.com/terms-and-privacy |
| 뉴스 대안(2026-11-07, 지휘 세션 확인) | 네이버 서비스 이용약관(2026-10-01 시행)은 허락 없는 봇 검색을 금지하고 search·news.naver.com의 robots.txt가 봇과 AI 목적 접근을 막는다. google.com/robots.txt는 /search를 막고, Custom Search JSON API는 신규 고객을 받지 않으며(기존 고객 2027-01-01까지 이전), Google 뉴스 RSS는 개인 피드 리더 표시 외 용도를 금지한다. Gemini 검색 그라운딩은 무료 등급 불가(이 세션도 확인). 결과는 D-095·D-097 | policy.naver.com, search.naver.com/robots.txt, google.com/robots.txt, policies.google.com/terms, developers.google.com/custom-search, support.google.com/programmable-search, news.google.com/robots.txt, aistudio.google.com/docs/pricing |
| Gemini SDK 3.0 | google-genai 3.0.0(2026-11-06): HTTP 전송 기본값이 httpx2로 바뀌어 httpx2가 필수 의존성, httpx는 선택 extra. Python 3.11 이상. 기본 API 버전 v1(2.34.0은 v1beta), Interactions 재시도 = attempts − 1(2.34.0은 attempts = 재시도 횟수), httpx2 전송은 Windows에서 truststore로 인증서 검증(2.34.0은 certifi)(2026-11-07 소스로 확인) | pypi.org/project/google-genai, 3.0.0 sdist |
| 법 | 가상자산이용자보호법 불공정거래 처벌, API 고빈도 반복 주문을 시세조종으로 수사 의뢰한 사례(2025-11-05) | fsc.go.kr |
| Windows 10 | 지원 종료 2025-10-14, 개인용 ESU는 2027-10-12까지 | microsoft.com/windows/extended-security-updates |
| 백테스트 | LLM 감성 시그널에는 look-ahead bias가 있음 | arxiv.org/abs/2309.17322 |
| Gemini 모델·한도 | 무료 등급 모델 gemini-3.8-flash, 3.6-flash, 3.5-flash-lite, 3.1-flash-lite, 3-flash-preview. 2.5 계열은 2026-12-01부터 다른 모델로 넘겨짐. 일일 한도는 태평양 시간 자정에 초기화, 한도는 프로젝트 단위 | aistudio.google.com/docs/rate-limits, /docs/pricing, /docs/changelog |
| Gemini 가격 | 이 사용량(월 540회)이면 유료로 바꿔도 월 1~4달러. 3.8·3.6 Flash는 2027-01-01 인상 예정(교차 검증 전) | aistudio.google.com/docs/pricing |
| 업비트 기본 한도 | Exchange default 그룹 초당 30회(주문 조회·개별 취소·잔고·주문 가능 정보·키 목록 포함), order 12회, order-test 8회, 일괄 취소 2초에 1회, 모두 포켓 단위. 시세 그룹은 IP 단위 초당 10회. 웹소켓 연결 초당 5회, 메시지는 연결마다 초당 5회·분당 100회(2026-11-05 재확인) | docs.upbit.com/kr/reference/rate-limits(2026-10-07 갱신) |
| Defender 정의 업데이트 | Windows 10에서 2028-10까지 제공(교차 검증 전) | Microsoft Windows 10 ESU 안내 |
| GitHub Actions 버전 | checkout v7, upload-artifact v7, setup-uv v10.3.3(주 버전 태그 없음) | 2026-11-03 GitHub API로 확인 |
| 업비트 키 만료일 API | `GET /v1/api_keys`가 계정의 키 목록과 `expire_at`(KST)을 준다. 인증만 필요하고 별도 권한은 없다. 서브포켓 키로 불렀을 때 목록 범위는 문서에 없음(확인 필요) | docs.upbit.com/kr/reference/list-api-keys(2026-11-04 갱신) |
| 업비트 포켓 키 | 메인포켓 키 최대 10개, 서브포켓마다 5개. 서브포켓 키 권한은 자산조회·주문조회·주문하기·자산이전만(출금·입금·포켓관리 불가). 포켓별 키 정보(`GET /v1/pockets/api_keys`: 권한, 허용 IP, 만료일)와 포켓 목록은 포켓관리 권한이 있는 메인포켓 키만 조회 가능. 키당 허용 IP 최대 10개, IPv4만, 1년 유효·연장 불가 | docs.upbit.com/kr/docs/api-key, /kr/reference/pocket-overview, /kr/reference/list-pocket-api-keys, /kr/reference/auth, /kr/changelog/order-rate-limit-update |
| 업비트 오류 이름 | 400: create_ask/bid_error, insufficient_funds_ask/bid, under_min_total_ask/bid, validation_error, invalid_parameter, invalid_post_only, duplicated_identifier(그 밖에 응답 예시의 invalid_time_in_force, over_krw_funds_bid, notfoundmarket). 401: invalid_query_payload, jwt_verification, expired_access_key, nonce_used, no_authorization_ip, no_authorization_token. 403: out_of_scope(401로도 옴), market_offline. 404: order_not_found. `invalid_access_key`는 목록에 없음. 시세 API의 `error.name`은 숫자 | docs.upbit.com/kr/reference/rest-api-guide(2026-10-06 갱신), 각 API 응답 예시 |
| 업비트 주문 | ord_type: limit, price(시장가 매수 총액), market(시장가 매도 수량), best(최유리, ioc·fok 필수). post_only는 limit 전용이며 smp_type의 cancel_maker·cancel_taker·reduce와 함께 못 씀(2026-11-09부터 none은 함께 쓸 수 있고, post_only에서 smp_type을 빼면 none). identifier는 계정 전체에서 고유, 재사용 불가, 최대 64자. 시장가 매수는 잔량이 남으면 cancel 상태로 끝날 수 있음. 주문 검증 응답의 UUID로는 조회·취소 불가 | docs.upbit.com/kr/reference/new-order, /list-closed-orders, /order-test |
| 업비트 SMP | 테이커 주문의 설정으로 동작, 체결 시점에 판정. 2026-11-09부터 생략 시 cancel_maker, `none` 추가, 응답에 항상 포함. myOrder state `prevented` | docs.upbit.com/kr/docs/smp, /kr/changelog/add-smp-type-default |
| 업비트 웹소켓 | 120초 무송수신 시 종료. PING 프레임 또는 "PING" 메시지(서버가 10초마다 `{"status":"UP"}`). myOrder state: wait, watch, trade, done, cancel, prevented. 숫자 필드는 JSON 숫자 | docs.upbit.com/kr/reference/websocket-guide, /websocket-myorder(2026-10-13 갱신) |
| 업비트 캔들·시각 | 4시간봉은 UTC 00·04·08·12·16·20시(KST 09·13·17·21·01·05시) 시작, 응답의 가장 최근 캔들은 진행 중인 캔들, 일봉 경계 UTC 00:00. 응답에 `Date` 헤더(초 단위) | api.upbit.com 공개 시세 호출(2026-11-05 01:41 UTC) |
| 업비트 공식 SDK | upbit-sdk 0.9.0(2026-04-14), 1.0.0(2026-09-01, 포켓 API), 1.1.0(2026-10-20). Apache-2.0, Python ≥3.9, websockets<16 상한(최신 17.4) | pypi.org/project/upbit-sdk, github.com/upbit-official/upbit-sdk-python |
| 업비트 문서 접근 | 각 문서 주소 끝에 `.md`를 붙이면 본문과 OpenAPI 정의를 마크다운으로 받는다. 목록은 docs.upbit.com/kr/llms.txt | docs.upbit.com/kr/llms.txt |
| PySide6 QtAsyncio | PySide6 6.12.0의 QtAsyncio(PySide6_Addons 휠)는 create_connection, getaddrinfo, sock_*, start_tls, subprocess 등이 미구현(NotImplementedError) | pyside6_addons-6.12.0 휠 소스 |
| qasync | 0.28.0(2025-08-28), 분류자 Python 3.13까지, Windows에서 자체 IOCP 프로액터 사용, 코루틴(asyncSlot) 안에서 띄우는 모달 창은 asyncWrap으로 감싸라고 안내 | pypi.org/project/qasync, 저장소 소스 |
| Python 표준 라이브러리 | tomllib는 읽기 전용(load, loads). Python 3.13 Windows·macOS 설치본은 SQLite 3.49.1로 갱신(gh-129917, 2025-03) | Python 3.13.18 표준 라이브러리, mail.python.org python-checkins |
| Qt 단일 인스턴스 | QLockFile은 파일의 PID로 남은 잠금을 감지(기본 30초, 오래 잡으면 setStaleLockTime(0) 권장), Windows에서 PC 이름이 ASCII 밖이면 감지 문제. QLocalServer는 Windows에서 같은 이름으로 둘이 listen 가능, removeServer는 Windows에서 동작 없음 | doc.qt.io qlockfile·qlocalserver(검색 요약, 본문 미열람) |
| Gemini 429 구분 | Interactions API 오류 코드: `quota_exceeded`(일일), `rate_limit_exceeded`(분당·초당 요청·토큰), `too_many_requests`(단기 과다). generateContent(legacy)는 `429 RESOURCE_EXHAUSTED`만 문서화(분당·일일 구분 필드 없음, 비공식으로 QuotaFailure.quotaId 사용) | aistudio.google.com/docs/api-errors, /docs/troubleshooting, /docs/rate-limits |
| Gemini 호출 API | Interactions API가 신규 개발 기본 권장(2026-06 GA), generateContent는 legacy지만 완전 지원·폐지 공지 없음. Interactions와 구조화 출력·thinking·system instruction은 안정판 v1에서 지원. SDK 기본은 v1beta라서 `api_version="v1"`로 고정해야 함 | aistudio.google.com/llms.txt, /docs/interactions-overview, /docs/deprecations, /api-reference/api-versions, python-genai v2.34.0 `_api_client.py` |
| google-genai 재시도 | 2.34.0 Interactions 경로는 기본 재시도 켜짐(408·409·429·5xx, 최대 3회, Retry-After 그대로 대기), models 경로는 기본 꺼짐. 공식 문서의 "Python SDK 최대 4회 자동 재시도" 설명과 다름. 타임아웃 기본값 없음(클라이언트는 ms, interactions.create는 초) | python-genai v2.34.0 소스 |
| Gemini thinking | gemini-3.8-flash는 thinking_level low·medium·high만(minimal 오류), 3.6-flash·3.5-flash-lite는 minimal 가능. max_output_tokens는 사고 토큰 포함 | aistudio.google.com/docs/thinking |
| Gemini 모델 넘김 | 2.5-pro → 3.8-flash, 2.5-flash → 3.5-flash-lite(2026-12-01부터), 3.7-flash → 3.8-flash, 3.5-flash → 3.6-flash(2026-10-08부터), 3.1-flash-lite는 2027-05-07 이후 종료 가능 | aistudio.google.com/docs/deprecations, /docs/changelog |
| Gemini 데이터 | Interactions 기본 store=true(무료 1일 보존), 정책 위반 감시 기록 55일, 무료 등급 입출력은 사람이 검토 가능, 약관에 "전문·업무 목적, 소비자용 아님" 문장 | aistudio.google.com/docs/interactions-overview, /docs/usage-policies, /docs/terms |
| 업비트 개발자 SDK 라이센스 | 두나무가 공개하는 소프트웨어·소스코드와 "이에 포함된 문서 일체"에 적용, 오픈소스 아님, 개인 목적만, 수정·재배포는 전체 소스 공개 조건, 사업 목적 금지. 공식 Python SDK 저장소 표기는 Apache-2.0(관계 불분명) | docs.upbit.com/kr/page/upbit_developer_sdk_license(2026-01-07 갱신) |
| upbit-sdk 동작 | 기본 max_retries=2로 POST 포함 자동 재시도(418 제외), HS256 서명, 배열 대괄호를 %5B%5D로 인코딩, 기본 헤더 X-Upbit-Client-*(X-Stainless 플랫폼 헤더는 안 보냄), 웹소켓 재연결 1초 고정·5회·정상 종료 시 재연결 안 함, Remaining-Req 해석 없음 | upbit-sdk 1.1.0 휠 소스 |
