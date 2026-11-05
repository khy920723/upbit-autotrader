# 진행 기록

세션이 끝날 때마다 맨 위에 추가한다. 형식: 날짜 — 단계 / 한 일 / 결정 / 남은 일 / 다음 단계.

## 2026-11-05 — 2단계: 뼈대 + 빌드 검증 (클라우드 세션)

- 한 일: uv 프로젝트(`pyproject.toml`, `uv.lock`, `.python-version` 3.13, 런타임 `PySide6==6.12.0`·`keyring==25.7.0`), `src/autotrader/` 7개 하위 패키지와 `__main__.py`, 빈 메인 창, 런타임 경로(`%LOCALAPPDATA%\upbit-autotrader\` 아래 data·logs·backup)·KST 로그(10MB×10 회전)·SQLite(`data\autotrader.db`, 데이터 모델의 `schema_migrations` 표만 STRICT로, `PRAGMA user_version` 0, WAL) 초기화, `--self-test`(import, Qt offscreen, keyring, SQLite 3.37.0 이상·WAL, TLS, 설정 경로 → `self-test-report.txt`, 0/1 종료), `packaging/autotrader.spec`(onedir·windowed·UPX 끔, `packaging/launcher.py` 진입), [의존성 라이선스 목록](../07-security-legal/dependency-licenses.md)과 `uv.lock` 대조 스크립트, 번들 고지(exe 옆 `NOTICE.txt`, `_internal/licenses/`). 테스트 220개(구조 규칙, spec 계약, 고정 버전, 라이선스 표 포함). Linux에서 같은 spec으로 빌드해 frozen self-test 확인. [PR #1](https://github.com/khy920723/upbit-autotrader/pull/1)에서 ci·build-exe 통과(Windows self-test 6/6, WinVaultKeyring)
- 발견·조치: PySide6 메타 패키지가 Addons까지 설치하면 PyInstaller가 GPL-3.0 전용 Qt Virtual Keyboard 플러그인을 번들에 넣는다 → 사용자 훅으로 빼고, GPL 전용 Qt 바이너리가 남으면 빌드를 멈춘다. PyInstaller가 setuptools·packaging·typing_extensions(개발 전용)까지 넣던 것을 빼고, 런타임 의존성 밖 패키지가 들어가면 빌드를 멈춘다. `ruff format`이 Markdown 코드 블록도 고쳐서 ruff 대상에서 docs를 뺐다. 독립 검토(4개 관점) 지적을 반영했다. 1단계 PR 병합 뒤 DB 초기화를 데이터 모델(`schema_migrations`, `user_version`, STRICT)에 맞췄다
- 결정: [결정 로그](decision-log.md) D-062(GPL 전용 Qt 모듈 금지·빌드 차단), D-063(번들 고지와 개발 전용 패키지 제외), D-064(PySide6 메타 패키지 유지 또는 Essentials만, 대기), D-065(self-test 구현 규칙). 그 밖의 구현 선택: 빌드 백엔드 uv_build, 개발용 비Windows 경로(XDG, macOS Application Support)
- 남은 일(사용자): Windows 10 PC에서 빈 앱 실행과 self-test 확인([설치 가이드](../09-operations/install-guide.md) "자가 점검"). 병합 전에는 Actions → build-exe → Run workflow에서 브랜치 `claude/stage-2-skeleton`을 골라야 zip이 생긴다. [CI 변경 제안](ci-proposals.md) 1번 반영, D-064(PySide6-Essentials 전환) 결정
- 남은 일(다음 단계): 마이그레이션 파일(`storage/migrations/0001_initial.sql`)과 적용 절차, `settings.json`(D-041·D-042 결정 뒤)
- 다음 단계: 3단계 업비트 연동(ADR-0006, D-038 결정 뒤)

## 2026-11-05 — 1단계: 설계 (클라우드 세션)

- 한 일:
  - ADR 3건을 "제안" 상태로 작성: [ADR-0006](../06-architecture/adr/0006-upbit-client.md) 업비트 클라이언트(httpx 기반 자체 클라이언트 추천), [ADR-0008](../06-architecture/adr/0008-buy-method.md) 매수 방식(기본 한 번에, 분할은 회차 금액이 예산 하한 이상일 때만), [ADR-0009](../06-architecture/adr/0009-gui-asyncio-bridge.md) GUI와 asyncio 연결(전용 스레드의 표준 asyncio 루프). ADR-0007(규칙 조건)은 별도 세션의 비교 리포트를 기다리며 만들지 않았다.
  - "1단계 보완" 문서를 채웠다: [매매 로직 명세](../03-functional/trading-logic.md)(시그널 유효 시간, 주문 유형, identifier·금액 규칙, 결과 불명 확인 일정, 업비트 state 대응표, 재조정, 손익 계산, 이유 코드), [데이터 모델](../04-data/data-model.md)(18개 테이블, 인덱스, 마이그레이션, 크기 추정), [시스템 구성도](../06-architecture/system-architecture.md)(스레드 모델, 인터페이스 시그니처, 오류 타입, 단일 인스턴스, 공인 IP), [설정 항목 정의서](../03-functional/settings.md)(JSON 형식 제안, `buy.*`, 실행 모드 DB 저장).
  - 공식 문서로 확인했다. 사용자가 업비트·Google 문서 도메인을 허용한 뒤 docs.upbit.com(141쪽, 각 쪽의 `.md`)과 aistudio.google.com 문서를 받아 읽었다: 업비트 키 만료일 API(`GET /v1/api_keys`의 `expire_at`), 포켓별 키 발급(메인포켓 10개·서브포켓 5개, 서브포켓 키 권한, 포켓별 키 정보는 포켓관리 권한이 있는 메인포켓 키만 조회), Gemini 429의 분당·일일 구분(Interactions API 오류 코드), upbit-sdk의 PyInstaller 호환 위험(휠 정적 분석). 그 밖에 업비트 요청 한도 그룹, 공식 오류 이름 목록, 주문 유형·SMP·identifier 규칙, 웹소켓 유지 규칙, 4시간봉 경계, google-genai 2.34.0 재시도 기본값, PySide6 6.12 QtAsyncio 미구현 범위, qasync 동작을 확인했다.
  - 연관 문서를 고쳤다: 업비트 API 연동 명세, LLM 시그널 명세, 기능 명세서(FR-02·FR-20·FR-21·FR-23, JOB-08), 상태 전이 정의서, 위험 관리 정책서(체크리스트 A 확인 방법, live-validate 일수), 메시지(MSG-E015, MSG-E016), 테스트 시나리오(TS-60~TS-79), 로그·감사 기록(이벤트 코드, 크기 추정), 리스크 대장(RSK-16 상태 오기 수정, RSK-23~RSK-26), 설치 가이드, 화면 정의서(SCR-08), 페이퍼 운영 평가 기준, 법·약관 검토, 기술 스택, ADR 목록, 로드맵 검증 사실표, 문서 지도.
- 결정: [결정 로그](decision-log.md) D-038~D-057.
  - 사용자 결정 대기: D-038(업비트 클라이언트), D-039(매수 방식), D-040(GUI–asyncio), D-041(DB 접근), D-042(설정 파일 형식), D-043(주문 유형), D-044(실행 모드 저장 위치), D-045(시그널 유효 시간), D-048(체크리스트 A 확인 방법), D-049(live-validate 일수), D-051(공인 IP 확인), D-054(Gemini 호출 API), D-057(평가 시각 정렬, ADR-0007과 함께). D-021(규칙 조건)은 별도 세션.
  - 기술 기본값(유효(초안), PR 승인으로 확정): D-046(결과 불명 확인), D-047(state 대응표·SMP·identifier), D-052(단일 인스턴스), D-053(재조정), D-055(Gemini 429·재시도), D-056(손익 계산). 사실 확인 반영(유효): D-050(키 만료일).
- 확인하지 못한 것(확인 필요): 서브포켓 키로 `GET /v1/api_keys`를 부를 때 나오는 목록 범위, 서브포켓을 만드는 화면 위치, Interactions 응답의 `model`이 실제 응답 모델인지, ipify·checkip 이용 조건, Qt·Python·Microsoft 문서 본문(이 세션 네트워크 정책에서 막혀 검색 요약으로만 확인), Windows에서의 PyInstaller 빌드 결과.
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
