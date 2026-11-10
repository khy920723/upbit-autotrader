# D-108 정리 목록 (Gemini 언급 위치)

상태: 진행 중 · 2026-11-09 작성 · 관련: [결정 로그](decision-log.md) D-108, [분석 보고서 세션 제안서](../03-functional/analysis-report-session.md) 5·6·9장, [진행 기록](progress.md)

D-108(2026-11-09)로 LLM 시그널은 Gemini가 아니라 매매 PC의 Claude Code CLI 세션이 낸다. 사용자는 "최신 문서 다시 확인"을 "저장소 문서 정리"라고 답했다. 이 문서는 저장소에서 Gemini·google-genai·AI Studio를 언급하는 위치를 모으고, 무엇을 언제 고칠지 나눈다.

- 기준: 이 목록을 만든 브랜치의 작업 트리(2026-11-09). 줄 번호는 이후 수정으로 바뀔 수 있다.
- 찾은 말: `gemini`, `google-genai`, `google.genai`, `genai`, `aistudio`, `AI Studio`(대소문자 무시). 모두 213곳, 37개 파일. 이 문서는 세지 않았다.

## 1. 분류별 위치

### 기록(고치지 않음) (124곳)

| 파일 | 줄 |
|---|---|
| `docs/10-management/progress.md` | 31, 35, 41, 50, 62, 65, 71, 88, 91, 92, 97, 103, 111, 122, 125, 154, 160, 171, 230, 248, 253, 261, 263, 779, 795, 800, 836, 839, 840, 842, 856 |
| `docs/10-management/decision-log.md` | 17, 67, 68, 106, 108, 111, 115, 116, 121 |
| `docs/03-functional/stage4-decisions.md` | 5, 13, 22, 49, 69, 75, 114, 129, 156, 163, 171, 173, 175, 179, 180, 181, 182, 186, 190, 191, 192, 193, 194, 197, 198, 199, 200, 202, 204, 207, 210, 215, 219, 225, 227, 232, 242, 243, 244, 247, 251, 253, 255, 257, 315, 397, 399, 416, 417, 418, 419, 420, 421, 422 |
| `docs/10-management/roadmap.md` | 71, 92, 103, 174, 190, 191, 192, 195, 196, 200, 201, 218, 219, 220, 221, 222, 223 |
| `docs/05-integration/news-collection.md` | 9, 12, 55 |
| `docs/06-architecture/adr/0005-news-sources.md` | 14, 38 |
| `docs/03-functional/analysis-report-session.md` | 19, 612, 726 |
| `docs/README.md` | 41, 65 |
| `docs/06-architecture/adr/README.md` | 23 |
| `docs/01-planning/requirements.md` | 13 |
| `README.md` | 37 |

### 상단 표시만 함(본문은 제안서 답 뒤 다시 씀) (47곳)

| 파일 | 줄 |
|---|---|
| `docs/05-integration/llm-signal.md` | 3, 5, 15, 23, 24, 25, 26, 27, 32, 34, 35, 37, 38, 89, 100, 101, 104, 106, 110, 112, 114, 116, 133, 143, 149 |
| `docs/06-architecture/adr/0002-gemini-free-tier-signal.md` | 1, 5, 9, 10, 11, 15, 21 |
| `docs/08-quality/fakes-spec.md` | 5, 204, 211, 221, 245, 354, 396, 408, 422 |
| `docs/07-security-legal/legal-compliance.md` | 26, 28, 33, 34, 42, 51 |

### 제안서 답 뒤 고칠 곳 (38곳)

| 파일 | 줄 |
|---|---|
| `docs/02-ux/screen-flow.md` | 51, 59 |
| `docs/02-ux/screen-spec.md` | 20 |
| `docs/02-ux/messages.md` | 19, 31 |
| `docs/03-functional/settings.md` | 63, 80 |
| `docs/03-functional/notifications.md` | 38 |
| `docs/03-functional/feature-spec.md` | 26 |
| `docs/01-planning/user-scenarios.md` | 20 |
| `docs/06-architecture/system-architecture.md` | 16, 41, 88, 133 |
| `docs/06-architecture/tech-stack.md` | 9, 13, 15, 33 |
| `docs/06-architecture/adr/0006-upbit-client.md` | 60 |
| `docs/06-architecture/adr/0009-gui-asyncio-bridge.md` | 8 |
| `docs/07-security-legal/security-policy.md` | 10, 35 |
| `docs/07-security-legal/risk-register.md` | 10, 29 |
| `docs/08-quality/test-scenarios.md` | 34 |
| `docs/08-quality/test-strategy.md` | 29, 52 |
| `docs/08-quality/invariants.md` | 116 |
| `docs/08-quality/traceability.md` | 89, 111 |
| `docs/08-quality/review-checklist.md` | 53, 109, 113 |
| `docs/09-operations/install-guide.md` | 49, 51, 52 |
| `docs/09-operations/runbook.md` | 20, 21 |

### 이 세션이 고치지 않음(코드, CLAUDE.md) (4곳)

| 파일 | 줄 |
|---|---|
| `CLAUDE.md` | 29, 62, 64 |
| `src/autotrader/adapters/__init__.py` | 1 |

## 2. 이번 PR에서 고친 것

- 결정 로그: D-004·D-054·D-055·D-098·D-102·D-103을 대체됨(D-108)으로 바꿨다. D-099·D-100·D-104는 Claude Code 기준으로 다시 묻는다고 표시했다.
- 결정 묶음: Gemini 결정(4장)에 대체 표시를 하고, 1장 남은 대기에서 뺐다.
- 로드맵 4단계 이름과 범위, 외부 사실 표의 Gemini 행 주석, 요구사항(U5·NFR-07), 프로젝트 개요서, 용어 정의서(보고서 세션, Claude Code CLI), 문서 지도, 루트 README.
- Gemini 전용 명세의 상단 표시: LLM 시그널 명세, ADR-0002(대체됨), 가짜 구현 명세 3장(FakeLLM), 법·약관 검토 4장.

## 3. 제안서 답 뒤에 다시 쓸 것

[분석 보고서 세션 제안서](../03-functional/analysis-report-session.md) 12장 질문에 답을 받은 뒤 아래를 고친다. 순서는 위에서 아래다.

- 2026-11-10: D-112(시그널 웹 검색)와 D-114(매수 근거 = 예상 결과 보고서)로 다시 쓸 범위가 넓어졌다. 함께 고칠 곳은 [진행 기록](progress.md) 2026-11-10 항목의 "남은 일"에 있다.

| 대상 | 고칠 내용 |
|---|---|
| 새 시그널 ADR | ADR-0002를 대신할 ADR(Claude Code CLI 시그널)과 ADR-0007(규칙 조건) |
| LLM 시그널 명세 | 모델·호출(`claude -p` 옵션)·응답 검증·기록(모델명, CLI 버전)·사용량 한도·약관 판단으로 본문을 다시 쓴다. 429 구분(D-055)과 SDK 재시도 절은 지운다 |
| 가짜 구현 명세 3장 | FakeLLM 와이어 가짜를 Claude Code CLI 출력(JSON, `structured_output`, 오류 결과, 종료 코드, 사용량 한도 메시지) 흉내로 바꾼다 |
| 화면 흐름·화면 정의서 | 마법사 W3(Gemini 키·모델)를 Claude Code 확인 단계(설치·로그인 상태 확인, 모델 설정)로 바꾼다 |
| 설정 항목 정의서 | `gemini.api_key`를 빼고 `llm.*`를 Claude Code 기준(모델, 시간 제한, 실행 방식)으로 다시 정의한다 |
| 데이터 모델 | `signals`의 모델·토큰 열을 Claude Code 메타데이터 기준으로 맞추고 CLI 버전 열을 정한다 |
| 메시지·알림 정의서 | Gemini 일일 한도(MSG-E006)·프로젝트 확인(MSG-E018) 같은 문구를 Claude 사용량 한도·로그인 만료 기준으로 바꾼다 |
| 기능 명세서, 사용자 시나리오 | FR-08·UC-12의 Gemini 한도·모델 폐기 흐름을 바꾼다 |
| 시스템 구성도, 기술 스택, ADR-0006·0009 | Gemini 어댑터와 google-genai를 Claude Code CLI 호출 어댑터로 바꾼다 |
| 보안 정책, 리스크 관리 대장, 법·약관 검토 | Gemini 키 항목을 빼고, Claude 계정·로그인·약관 판단과 RSK-04(무료 한도)를 고친다 |
| 테스트 시나리오·전략, 불변식, 추적표, 리뷰 점검표 | Gemini 전용 시나리오(429 구분, Interactions 형식)를 Claude Code 기준으로 바꾼다 |
| 설치 가이드, 운영 런북 | Gemini 키 발급 단계를 Claude Code 설치·로그인 단계로 바꾼다 |
| 코드(프론트/백엔드 몫) | `src/autotrader/adapters/__init__.py`의 docstring("Gemini, 뉴스, 텔레그램") |
| CLAUDE.md(지휘 세션 몫) | "Gemini 시그널 주의" 절과 고정 기술 기준의 google-genai 문장. 문안은 진행 기록의 2026-11-09 제안 |
