# 진행 기록

세션이 끝날 때마다 맨 위에 추가한다. 형식: 날짜 — 단계 / 한 일 / 결정 / 남은 일 / 다음 단계.

## 2026-11-05 — 1단계 후속: 설계 검토 반영 (클라우드 세션)

- 한 일:
  - 1단계 PR([#2](https://github.com/khy920723/upbit-autotrader/pull/2))은 외부 출처 대조 검토 반영분까지 자동 병합됐다. 그 뒤에 끝난 검토 2건(범위·문체 15건, 안전·논리 21건)을 근거와 대조해 반영하고 최신 main 위에서 새 PR로 올린다.
  - 범위·문체: 결정 로그 머리말에 "대기"와 "유효(초안)"의 기준을 적고 D-052(단일 인스턴스)·D-061(거절된 주문과 최소 주문 간격)을 대기로, D-055를 D-054 전제로 바꿨다. 규칙 인터페이스를 ADR-0007 가안으로 표시했다. 상태 줄·비유 표현·설정 숫자 형식·Gemini 429 연속 판정 기준을 정리하고, 앱 구성도와 상태 전이도를 Mermaid 10·11에서 렌더링되게 고쳤다.
  - 안전·논리: 첫 매수의 예산 하한 검사, exit_only 실보유분 감시, 정지·전량 매도 규칙을 대기 결정으로 올렸다. `duplicated_identifier` 처리, 최종 상태 유지, REST로 체결 복구, 코인별 주문 직렬화, 체결 1건 반영 = 한 트랜잭션, 숫자 파싱, JOB-02 완료 감시, 마이그레이션 외래 키, 인정일 분 상한을 문서에 넣었다. MSG-E014·E019, NTF-16·21·23, 이벤트 코드 4개, TS-84~TS-97을 추가했다.
  - 소스로 확인: Qt 6.12 QLockFile·QLocalServer(태그 소스), ccxt 4.5.92의 업비트 `create_order`가 `smp_type`을 요청에서 빼는 것, PyInstaller 6.22.3의 메타데이터 자동 수집, SQLite가 트랜잭션 안의 `PRAGMA foreign_keys` 변경을 무시하는 것(sqlite 3.53.1).
- 결정: [결정 로그](decision-log.md) D-066~D-071. 다른 세션이 D-062~D-065를 먼저 써서 이 세션의 새 결정은 D-066부터다.
  - 1단계 관련 사용자 결정 대기(안전·위험 관리에 영향): D-058(내부 오류 때 HALTED, 손절도 멈춤), D-061(거절된 주문과 최소 주문 간격), D-067(첫 매수의 예산 하한, 잔량 원가), D-068(exit_only 실보유분 감시, 보유 코인 선택 해제), D-069(정지·전량 매도 규칙), D-059(키 없는 paper의 주문 정보 추정값), D-060(core 정지 비상 알림), D-048(체크리스트 A 확인 방법), D-049(live-validate 일수)
  - 1단계 관련 사용자 결정 대기(기술·구성): D-038(업비트 클라이언트), D-039(매수 방식), D-040(GUI–asyncio), D-041(DB 접근), D-042(설정 파일 형식), D-043(주문 유형), D-044(실행 모드 저장 위치), D-045(시그널 유효 시간), D-051(공인 IP 확인), D-052(단일 인스턴스), D-054(Gemini 호출 API), D-057(평가 시각 정렬, ADR-0007과 함께), D-066(1단계에서 하지 않은 항목의 시점). D-021(규칙 조건)은 별도 세션.
  - 기술 기본값(유효(초안), 사용자가 확인하면 유효): D-046, D-047, D-053, D-055(D-054 승인 전제), D-056, D-070(주문·체결 처리 세부), D-071(운영 견고성).
- 확인하지 못한 것(확인 필요): 서브포켓 키로 `GET /v1/api_keys`를 부를 때 나오는 목록 범위, 서브포켓을 만드는 화면 위치, 배열 이름의 대괄호를 인코딩하지 않은 요청을 서버가 받는지(REST 안내와 공식 SDK가 다름), SMP가 포켓 사이에도 적용되는지, Interactions 응답의 `model`이 실제 응답 모델인지, ipify·checkip 이용 조건, Microsoft Learn `AllowSetForegroundWindow` 본문, Windows에서 monotonic 시계가 잠자기 시간을 포함하는지(D-071은 포함 여부와 상관없게 정함).
- 남은 일(사용자):
  - 대기 항목 결정. 특히 D-058은 "손절·청산은 막지 않는다" 원칙의 예외라 따로 확인한다.
  - CLAUDE.md "업비트 API 주의"의 `query_hash` 문구("실제 전송 문자열의 SHA512")를 "URL 인코딩 전 쿼리 문자열의 SHA512(전송할 때만 값을 인코딩)"로 고칠지 확인한다. 공식 인증 문서와 공식 SDK가 인코딩 전 문자열로 해시한다.
  - ADR-0007 규칙 조건 선택.

남은 일(1단계 범위 중 하지 않음, 시점 제안 D-066 대기):

| 항목 | 이번에 하지 않은 이유 | 제안 시점 |
|---|---|---|
| 추천 기본 모델 ID | 1단계 세션 요청 범위 밖. 모델 넘김 일정(2026-12-01 등)이 가까워 그때 다시 확인해야 한다 | 4단계 시작 전 |
| 지표 요약 항목 | 규칙 조건(ADR-0007)에 달려 있다 | ADR-0007 확정 뒤, 4단계 시작 전 |
| 프롬프트 첫 버전 | 지표 요약 항목에 달려 있다 | 4단계 시작 전 |
| `llm.max_output_tokens` 값 | 응답 스키마와 사고 수준을 정한 뒤 실제 응답 길이를 재야 한다 | 4단계 |
| RSS에서 티커가 일반 단어와 겹칠 때의 처리 | 1단계 세션 요청 범위 밖. 뉴스 수집 구현과 함께 정한다 | 4단계 시작 전 |
| 진단 묶음 범위 | 로그·감사 기록 정의서가 7단계 전에 정한다고 적었다 | 7단계 시작 전 |

- 다음 단계: 대기 결정 반영 뒤 3단계(업비트 연동). D-067~D-070은 3·5단계 구현 범위(주문 관리, 재조정, 저장)에 들어간다.

## 2026-11-05 — 2단계: 뼈대 + 빌드 검증 (클라우드 세션)

- 한 일: uv 프로젝트(`pyproject.toml`, `uv.lock`, `.python-version` 3.13, 런타임 `PySide6==6.12.0`·`keyring==25.7.0`), `src/autotrader/` 7개 하위 패키지와 `__main__.py`, 빈 메인 창, 런타임 경로(`%LOCALAPPDATA%\upbit-autotrader\` 아래 data·logs·backup)·KST 로그(10MB×10 회전)·SQLite(`data\autotrader.db`, 데이터 모델의 `schema_migrations` 표만 STRICT로, `PRAGMA user_version` 0, WAL) 초기화, `--self-test`(import, Qt offscreen, keyring, SQLite 3.37.0 이상·WAL, TLS, 설정 경로 → `self-test-report.txt`, 0/1 종료), `packaging/autotrader.spec`(onedir·windowed·UPX 끔, `packaging/launcher.py` 진입), [의존성 라이선스 목록](../07-security-legal/dependency-licenses.md)과 `uv.lock` 대조 스크립트, 번들 고지(exe 옆 `NOTICE.txt`, `_internal/licenses/`). 테스트 220개(구조 규칙, spec 계약, 고정 버전, 라이선스 표 포함). Linux에서 같은 spec으로 빌드해 frozen self-test 확인. [PR #1](https://github.com/khy920723/upbit-autotrader/pull/1)에서 ci·build-exe 통과(Windows self-test 6/6, WinVaultKeyring)
- 발견·조치: PySide6 메타 패키지가 Addons까지 설치하면 PyInstaller가 GPL-3.0 전용 Qt Virtual Keyboard 플러그인을 번들에 넣는다 → 사용자 훅으로 빼고, GPL 전용 Qt 바이너리가 남으면 빌드를 멈춘다. PyInstaller가 setuptools·packaging·typing_extensions(개발 전용)까지 넣던 것을 빼고, 런타임 의존성 밖 패키지가 들어가면 빌드를 멈춘다. `ruff format`이 Markdown 코드 블록도 고쳐서 ruff 대상에서 docs를 뺐다. 독립 검토(4개 관점) 지적을 반영했다. 1단계 PR 병합 뒤 DB 초기화를 데이터 모델(`schema_migrations`, `user_version`, STRICT)에 맞췄다
- 결정: [결정 로그](decision-log.md) D-062(GPL 전용 Qt 모듈 금지·빌드 차단), D-063(번들 고지와 개발 전용 패키지 제외), D-064(PySide6 메타 패키지 유지 또는 Essentials만, 대기), D-065(self-test 구현 규칙). 그 밖의 구현 선택: 빌드 백엔드 uv_build, 개발용 비Windows 경로(XDG, macOS Application Support)
- 후속(라이선스 검토 반영, 별도 PR): 번들에서 `opengl32sw.dll`(Mesa)과 QtNetwork 제외, Windows 빌드에서 Python·패키지 밖 DLL(PATH의 OpenSSL 등) 차단, PySide6·shiboken6의 Python 부분을 `.py`로 두어 교체 가능하게(LGPL 4(d)(1)), GPL 검사에 Qt Designer 추가·Qt 3D QML 플러그인 오탐 제거, NOTICE.txt에 앱 소스 위치, 라이선스 표 검사가 uv.lock fork를 거부
- 남은 일(사용자): Windows 10 PC에서 빈 앱 실행과 self-test 확인([설치 가이드](../09-operations/install-guide.md) "자가 점검"). 병합 전에는 Actions → build-exe → Run workflow에서 브랜치 `claude/stage-2-skeleton`을 골라야 zip이 생긴다. [CI 변경 제안](ci-proposals.md) 1번 반영, D-064(PySide6-Essentials 전환) 결정
- 남은 일(다음 단계): 마이그레이션 파일(`storage/migrations/0001_initial.sql`)과 적용 절차, `settings.json`(D-041·D-042 결정 뒤)
- 다음 단계: 3단계 업비트 연동(ADR-0006, D-038 결정 뒤)

## 2026-11-05 — 1단계: 설계 (클라우드 세션)

- 한 일:
  - ADR 3건을 "제안" 상태로 작성: [ADR-0006](../06-architecture/adr/0006-upbit-client.md) 업비트 클라이언트(httpx 기반 자체 클라이언트 추천), [ADR-0008](../06-architecture/adr/0008-buy-method.md) 매수 방식(기본 한 번에, 분할은 회차 금액이 예산 하한 이상일 때만), [ADR-0009](../06-architecture/adr/0009-gui-asyncio-bridge.md) GUI와 asyncio 연결(전용 스레드의 표준 asyncio 루프). ADR-0007(규칙 조건)은 별도 세션의 비교 리포트를 기다리며 만들지 않았다.
  - "1단계 보완" 문서를 채웠다: [매매 로직 명세](../03-functional/trading-logic.md)(시그널 유효 시간, 주문 유형, identifier·금액 규칙, 결과 불명 확인 일정, 업비트 state 대응표, 재조정, 손익 계산, 이유 코드), [데이터 모델](../04-data/data-model.md)(18개 테이블, 인덱스, 마이그레이션, 크기 추정), [시스템 구성도](../06-architecture/system-architecture.md)(스레드 모델, 인터페이스 시그니처, 오류 타입, 단일 인스턴스, 공인 IP), [설정 항목 정의서](../03-functional/settings.md)(JSON 형식 제안, `buy.*`, 실행 모드 DB 저장).
  - 공식 문서로 확인했다. 사용자가 업비트·Google 문서 도메인을 허용한 뒤 docs.upbit.com(141쪽, 각 쪽의 `.md`)과 aistudio.google.com 문서를 받아 읽었다: 업비트 키 만료일 API(`GET /v1/api_keys`의 `expire_at`), 포켓별 키 발급(메인포켓 10개·서브포켓 5개, 서브포켓 키 권한, 포켓별 키 정보는 포켓관리 권한이 있는 메인포켓 키만 조회), Gemini 429의 분당·일일 구분(Interactions API 오류 코드), upbit-sdk의 PyInstaller 호환 위험(휠 정적 분석). 그 밖에 업비트 요청 한도 그룹, 공식 오류 이름 목록, 주문 유형·SMP·identifier 규칙, 웹소켓 유지 규칙, 4시간봉 경계, google-genai 2.34.0 재시도 기본값, PySide6 6.12 QtAsyncio 미구현 범위, qasync 동작을 확인했다.
  - 연관 문서를 고쳤다: 업비트 API 연동 명세, LLM 시그널 명세, 기능 명세서(FR-02·FR-20·FR-21·FR-23, JOB-08), 상태 전이 정의서, 위험 관리 정책서(체크리스트 A 확인 방법, live-validate 일수), 메시지(MSG-E015~E018), 알림(NTF-21·NTF-22), 테스트 시나리오(TS-60~TS-83), 로그·감사 기록(이벤트 코드, 크기 추정), 리스크 대장(RSK-16 상태 오기 수정, RSK-23~RSK-26), 설치 가이드, 화면 정의서(SCR-08), 페이퍼 운영 평가 기준, 법·약관 검토, 기술 스택, ADR 목록, 로드맵 검증 사실표, 문서 지도.
- 결정: [결정 로그](decision-log.md) D-038~D-061.
  - 사용자 결정 대기: D-038(업비트 클라이언트), D-039(매수 방식), D-040(GUI–asyncio), D-041(DB 접근), D-042(설정 파일 형식), D-043(주문 유형), D-044(실행 모드 저장 위치), D-045(시그널 유효 시간), D-048(체크리스트 A 확인 방법), D-049(live-validate 일수), D-051(공인 IP 확인), D-054(Gemini 호출 API), D-057(평가 시각 정렬, ADR-0007과 함께), D-058(내부 오류 때 HALTED, 손절도 멈춤), D-059(키 없는 paper의 주문 정보 추정값), D-060(core 정지 비상 알림). D-021(규칙 조건)은 별도 세션.
  - 기술 기본값(유효(초안)): D-046(결과 불명 확인), D-047(state 대응표·SMP·identifier), D-052(단일 인스턴스), D-053(재조정), D-055(Gemini 429·재시도), D-056(손익 계산), D-061(거절된 주문과 최소 주문 간격). D-052·D-061은 후속 작업에서 대기로 바꿨다(위 기록). 사실 확인 반영(유효): D-050(키 만료일).
- 확인하지 못한 것(확인 필요): 서브포켓 키로 `GET /v1/api_keys`를 부를 때 나오는 목록 범위, 서브포켓을 만드는 화면 위치, Interactions 응답의 `model`이 실제 응답 모델인지, ipify·checkip 이용 조건, Microsoft Learn 문서 본문(이 세션 네트워크 정책에서 막힘. Python·Qt 문서는 태그 소스로 확인), Windows에서의 PyInstaller 빌드 결과.
- 남은 일(사용자): PR의 대기 항목 결정, ADR-0007 규칙 조건 선택, Gemini 추가 약관의 "소비자용 아님" 문장 확인, 공인 IP 조회 서비스 이용 조건 확인.
- 남은 일(1단계 범위 중 이번에 하지 않음): 추천 기본 모델 ID, 지표 요약 항목(ADR-0007과 함께), 프롬프트 첫 버전, `llm.max_output_tokens` 값, 진단 묶음 범위, RSS에서 티커가 일반 단어와 겹칠 때의 처리([뉴스 수집 명세](../05-integration/news-collection.md) 3장).
- 다음 단계: 결정 반영 후 2단계(뼈대 + 빌드 검증). 2단계 세션이 같은 시기에 설정·SQLite 초기화를 만들고 있으므로 D-041·D-042·D-044 결정과 맞춘다.

## 2026-11-03 — 기획 문서 작성 (로컬 세션)

- 한 일: `docs/`를 10개 분류 폴더로 재구성하고 기획 문서를 작성([문서 지도](../README.md)). 기존 SPEC·PLAN·PROGRESS·ci-proposals를 해당 폴더로 이동(요구사항 정의서, 로드맵, 진행 기록, CI 변경 제안). `LICENSE`(MIT) 추가, `CLAUDE.md`와 README 경로 갱신. 검토 에이전트 1회 검토(지적 38건)를 반영해 상태 정의(DEGRADED 추가, 상태 복원 규칙), 실전 전환 2단계 체크리스트, 주문 결과 불명 처리, 알림 문구 ID, 테스트 시나리오(59개)를 보강
- 결정: [결정 로그](decision-log.md) D-016~D-037 (D-032 실전 점검 3일 강제 확정, D-033 자동 로그인은 지금 계정 그대로 + 화면 잠금 필수)
- 남은 일(사용자): Claude GitHub App 설치, 클라우드 환경 생성(로드맵 "사용자 작업"), 집 IP 고정 여부 확인, 네이버 검색 API 약관 확인(4단계 전), 업비트 Open API 약관 확인(9단계 전)
- 다음 단계: 1단계 설계

## 2026-11-03 — 0단계: 준비 (로컬 세션)

- 한 일: 공개 저장소 생성, README·CLAUDE.md·SPEC·PLAN·PROGRESS 작성, CI 워크플로(`ci.yml`, `build-exe.yml`), 클라우드 세션 시작 훅
- 결정: 업비트 KRW 최대 3코인, Python 3.13 + PySide6 6.12, Gemini 무료 등급 시그널 + 규칙 확인, 네이버·RSS 뉴스, paper 기본
- 남은 일(사용자): Claude GitHub App 설치, 클라우드 환경 생성(당시 PLAN.md, 지금은 로드맵의 "사용자 작업"), 집 IP 고정 여부·PC 종류·자동 로그인 결정, 라이선스 결정
- 다음 단계: 1단계 설계
