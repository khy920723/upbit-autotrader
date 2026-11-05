# 진행 기록

세션이 끝날 때마다 맨 위에 추가한다. 형식: 날짜 — 단계 / 한 일 / 결정 / 남은 일 / 다음 단계.

## 2026-11-05 — QA: 검증 기반 (클라우드 세션)

- 한 일:
  - [요구사항 추적표](../08-quality/traceability.md): FR-01~FR-26, NFR-01~NFR-12를 설계 문서, 테스트 시나리오, 불변식, 로드맵 단계와 연결했다. 보완 전 판정은 충분 5개, 빠짐 6개(FR-09, FR-18, FR-24, FR-26, NFR-07, NFR-11), 나머지는 일부. 요구사항 문장이 없는 테스트 7개(TS-15, TS-16, TS-73, TS-74, TS-75, TS-77, TS-102)를 찾았고, 명세 공백 13개(Q-01~Q-13)를 정리했다.
  - [테스트 시나리오](../08-quality/test-scenarios.md)에 빈 곳을 메우는 TS-84~TS-131(48개)을 추가했다. TS-60~TS-79는 [1단계 설계 PR](https://github.com/khy920723/upbit-autotrader/pull/2)이 쓰고 있어 TS-84부터 붙였다.
  - [불변식 명세](../08-quality/invariants.md): INV-01~INV-19(위험 한도 초과 주문 0건, STOPPED·SUSPENDED·HALTED에서 주문 0건, identifier 재전송 없음, 결과 불명 중 같은 코인 새 주문 없음, 같은 코인 매수·매도 동시 주문 없음, 비밀 없음 등)와 각각을 단위·속성 기반(hypothesis)·통합·구조 검사 중 어떤 테스트로 증명할지 정했다.
  - [가짜 구현 명세](../08-quality/fakes-spec.md): FakeExchange, FakeLLM, FakeNews, FakeClock, FakeNotifier의 응답 형식, 오류 이름, 주입 기능, 엄격 모드 검사, 비밀 검사(카나리아)를 정했다. 업비트 개발자 센터 35쪽과 Gemini API 문서 8쪽을 받아 대조했다. 텔레그램·네이버 문서는 네트워크 정책으로 막혀 검색 요약으로만 확인했다.
  - [녹화 응답](../../tests/fixtures/upbit/README.md): 업비트 공개 시세 API로 market/all(875개 중 8개 항목), 240분봉·일봉 5개, ticker 3개, orderbook, 오류 2개를 받아 저장했다(초당 1회, Origin 없음, 끝 슬래시 없음, 키 없음).
  - [Windows 10 수동 점검표](../08-quality/manual-checklist-windows10.md)(M-01~M-35), [PR 검토 기준](../08-quality/review-checklist.md)(공통·문서·인프라·기능·테스트, 결과 작성 형식), [테스트 전략](../08-quality/test-strategy.md)에 새 문서 연결과 속성 기반 테스트 수준을 추가했다.
- 확인한 사실(공식 문서와 녹화): 캔들 응답의 `Remaining-Req` 그룹은 `candles`다(문서 표는 `candle`). ticker에 없는 마켓이 하나라도 섞이면 있는 마켓까지 전체가 404다. 웹소켓 오류 이름에 `TOO_MANY_REQUEST`가 없다. 웹소켓 ticker의 `is_trading_suspended`, `market_warning`은 폐기다. 취소 API 예시에 `QUERY_PARAMETER_NOT_SUPPORTED`, `bad_request`가 있다. 418·429 본문 형식과 2026-11-16 경로 오류 형식은 문서에 없다. 시세 REST 숫자 표기가 섞여 있어 Decimal로 읽어야 한다.
- 결정: 없음(결정 로그를 바꾸지 않았다). 제안: NFR-13(외부 API 계약 준수)·NFR-14(데이터 정확성·보존) 추가(Q-11), dev 그룹에 hypothesis 추가.
- 남은 일(기획·문서 세션): 문서 지도에 새 문서 5개와 INV- 접두어 추가, Q-01~Q-13 결정, 업비트 API 연동 명세에 확인한 사실 반영, 사용자 승인 뒤 NFR-13·NFR-14 추가, CLAUDE.md dev 그룹 목록에 hypothesis 추가.
- 남은 일(인프라 세션): dev 그룹에 hypothesis 추가, `.gitignore`에 `.hypothesis/` 추가, 느린 테스트 마커 등록.
- 남은 일(개발 세션, 3~7단계): 가짜 구현 명세대로 가짜 구현, 테스트 docstring에 TS·INV ID 적기.
- 남은 일(사용자): 2단계 빌드 뒤 수동 점검표 0~2절 실행, Q-11 승인 여부 결정.
- 참고: 테스트 시나리오 끝과 이 진행 기록 맨 위는 1단계 설계 PR도 고친다. 병합할 때 두 내용을 모두 남긴다.
- 다음 단계: 열린 PR(2단계 뼈대, 1단계 설계)을 PR 검토 기준으로 검토.

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
