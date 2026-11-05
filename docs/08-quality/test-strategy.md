# 테스트 전략

상태: 초안(2026-11-05 QA 검증 기반 추가) · 관련: [테스트 시나리오](test-scenarios.md), [요구사항 추적표](traceability.md), [불변식 명세](invariants.md), [가짜 구현 명세](fakes-spec.md), [Windows 10 수동 점검표](manual-checklist-windows10.md), [PR 검토 기준](review-checklist.md), [페이퍼 운영 평가 기준](paper-evaluation.md), [빌드·배포 절차](../09-operations/build-release.md)

## 1. 원칙

- 테스트를 먼저 쓴다.
- 외부 API는 가짜 구현이나 녹화 응답으로 테스트한다. 클라우드 세션과 CI에서는 실제 키나 실제 주문을 쓰지 않는다.
- 위험 관리와 주문 관리 경로는 반드시 테스트로 증명한다. 위험 한도를 넘는 주문이 나가지 않는다는 것이 가장 중요한 성질이다.

## 2. 테스트 수준

| 수준 | 대상 | 도구 | 실행 위치 |
|---|---|---|---|
| 단위 | JWT 서명·query_hash(알려진 값), 호가 단위 반올림, 위험 한도, 규칙 조건, LLM 출력 검증, 상태 전이, 비밀 가리기 | pytest | 클라우드 세션, ci.yml |
| 통합 | 가짜 거래소 + 주문 관리(타임아웃·재조정), 가짜 LLM, 가짜 뉴스, 가짜 시계 + 스케줄러, SQLite | pytest | 클라우드 세션, ci.yml |
| 속성 기반 | [불변식](invariants.md)(INV-01~INV-19): 임의 입력·임의 사건 순서에서 위험 한도, 주문 안전, 비밀 보호가 깨지지 않음 | hypothesis(dev 그룹 추가 필요) | 클라우드 세션, ci.yml |
| 화면 | 마법사 흐름, 대시보드 상태 표시, 버튼 동작 | pytest-qt(offscreen) | 클라우드 세션, ci.yml |
| 패키징 | exe 실행, `--self-test` | build-exe.yml | Windows 러너 |
| 규칙 백테스트 | 규칙·위험 관리 부분만(LLM 제외) | 백테스트 도구 | 클라우드 세션(api.upbit.com 시세) |
| 수동 | 설치, 자동 실행, 자동 로그인, 잠자기 복귀, 허용 IP 오류 | [수동 점검표](manual-checklist-windows10.md) | Windows 10 PC |
| 운영 검증 | 페이퍼 인정일 28일, 실전 점검 3일 | 앱 기록 | Windows 10 PC |

## 3. 가짜 구현

| 이름 | 흉내 내는 것 | 주입할 수 있는 것 |
|---|---|---|
| FakeExchange | 업비트 REST 응답 형식, 오류 이름, 주문 상태 | 타임아웃, 429, 418, 부분 체결, 허용 IP 오류, 키 만료 |
| FakeLLM | Gemini 응답 | 정해진 판정, 타임아웃, 429, 형식 오류, 거절, 다른 모델 이름 |
| FakeNews | 네이버·RSS 결과 | 빈 결과, 실패, 인젝션 문구가 섞인 제목 |
| FakeClock | monotonic 시간, 거래소 서버 시각 | 시간 건너뛰기, 시계 오차, 09:00 경계 |
| FakeNotifier | 텔레그램 전송 | 429, 실패 |

- 응답 형식, 오류 이름, 주입 기능, 엄격 모드 검사의 상세는 [가짜 구현 명세](fakes-spec.md)에 있다.

## 4. 녹화 응답

- 공개 API 응답(종목, 캔들, 시세)은 클라우드 세션에서 실제로 받아 `tests/fixtures/`에 저장할 수 있다. 업비트 공개 시세 녹화는 [`tests/fixtures/upbit/`](../../tests/fixtures/upbit/README.md)에 있다(2026-11-05).
- 비공개 API 응답은 업비트 문서 예시를 바탕으로 만든다(키가 없으므로).
- 녹화 파일에는 비밀이나 개인 정보를 넣지 않는다.

## 5. 기준

- `core` 패키지 줄 커버리지 80% 이상(초안). 위험 관리·주문 관리는 분기 커버리지 100%를 목표로 한다.
- 커버리지는 pytest-cov로 잰다. CI에 넣는 변경은 [CI 변경 제안](../10-management/ci-proposals.md)에 있고 2단계에서 반영한다.
- PR은 ci.yml이 통과해야 병합한다. 코드나 패키징이 바뀐 PR은 build-exe.yml도 통과해야 한다.
- 불변식(INV-01~INV-19)은 [불변식 명세](invariants.md)에 정한 방법(단위, 속성 기반, 통합, 구조 검사)으로 증명한다.
- 요구사항과 테스트의 연결은 [추적표](traceability.md)로 관리하고, PR은 [PR 검토 기준](review-checklist.md)으로 검토한다.

## 6. 테스트하지 않는 것

- 클라우드·CI에서 업비트 비공개 API와 실제 Gemini 호출. 이것들은 사용자 PC에서 마법사의 키 검증과 페이퍼 운영으로 확인한다.
- LLM 시그널의 과거 성과(look-ahead bias 때문에 의미가 없음).
