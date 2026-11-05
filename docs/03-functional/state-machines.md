# 상태 전이 정의서

상태: 초안(1단계에서 주문 상태 대응 보완) · 관련: [위험 관리 정책서](risk-policy.md), [매매 로직 명세](trading-logic.md)

상태는 네 종류다: 실행 모드, 매매 상태, 주문 상태, 코인 상태. "live 계열"은 live-validate와 live를 뜻한다.

## 1. 실행 모드

```mermaid
stateDiagram-v2
    [*] --> PAPER
    PAPER --> SIGNAL_ONLY: 사용자 선택
    SIGNAL_ONLY --> PAPER: 사용자 선택
    PAPER --> LIVE_VALIDATE: 인정일 28일 + 체크리스트 A
    LIVE_VALIDATE --> LIVE: 실전 점검 3일 + 매수 검증 오류 0건 + 체크리스트 B + 확인 문구
    LIVE_VALIDATE --> PAPER: 사용자 선택
    LIVE --> PAPER: 사용자 선택(실보유분 처리 확인)
```

- backtest는 실행 모드가 아니라 개발용 도구다.
- 체크리스트 A·B와 인정일 규칙은 [위험 관리 정책서](risk-policy.md) 6장.
- live에서 paper로 바꿀 때 실제 보유 코인이 있으면 MSG-C008로 처리 방법을 고른다. 실제 보유분을 관리 없이 남기지 않는다.
- 모드가 바뀌면 이벤트로 기록하고 알린다(NTF-14).

## 2. 매매 상태

```mermaid
stateDiagram-v2
    [*] --> STARTING
    STARTING --> CHECKING
    CHECKING --> RUNNING: 통과(처음, 직전 RUNNING, 또는 시작 버튼)
    CHECKING --> PAUSED: 통과(직전 PAUSED)
    CHECKING --> BUY_BLOCKED: 통과(오늘 한도 도달 상태)
    CHECKING --> STOPPED: 통과(직전 STOPPED)
    CHECKING --> SUSPENDED: 네트워크 문제
    CHECKING --> DEGRADED: 시계 오차
    CHECKING --> HALTED: 키·IP 문제(live 계열) 또는 키 저장소 문제
    RUNNING --> PAUSED: 일시정지
    PAUSED --> RUNNING: 재개
    RUNNING --> BUY_BLOCKED: 일일 손실 한도·주문 수 상한
    BUY_BLOCKED --> RUNNING: 09시 KST 리셋
    RUNNING --> DEGRADED: 시세 끊김·시계 오차
    PAUSED --> DEGRADED: 시세 끊김·시계 오차
    BUY_BLOCKED --> DEGRADED: 시세 끊김·시계 오차
    DEGRADED --> CHECKING: 원인 해소(자동)
    RUNNING --> SUSPENDED: 연결 끊김·418
    PAUSED --> SUSPENDED: 연결 끊김·418
    BUY_BLOCKED --> SUSPENDED: 연결 끊김·418
    DEGRADED --> SUSPENDED: 연결 끊김·418
    SUSPENDED --> CHECKING: 원인 해소(자동)
    RUNNING --> HALTED: 허용 IP·키 오류(live 계열)
    PAUSED --> HALTED: 허용 IP·키 오류(live 계열)
    BUY_BLOCKED --> HALTED: 허용 IP·키 오류(live 계열)
    DEGRADED --> HALTED: 허용 IP·키 오류(live 계열)
    RUNNING --> HALTED: 내부 오류(모든 모드)
    PAUSED --> HALTED: 내부 오류(모든 모드)
    BUY_BLOCKED --> HALTED: 내부 오류(모든 모드)
    DEGRADED --> HALTED: 내부 오류(모든 모드)
    HALTED --> CHECKING: 사용자 조치 후 다시 점검
    RUNNING --> STOPPED: 정지
    PAUSED --> STOPPED: 정지
    BUY_BLOCKED --> STOPPED: 정지
    DEGRADED --> STOPPED: 정지
    SUSPENDED --> STOPPED: 정지
    HALTED --> STOPPED: 정지
    RUNNING --> LIQUIDATING: 정지 후 전량 매도
    PAUSED --> LIQUIDATING: 정지 후 전량 매도
    BUY_BLOCKED --> LIQUIDATING: 정지 후 전량 매도
    DEGRADED --> LIQUIDATING: 정지 후 전량 매도
    LIQUIDATING --> STOPPED: 매도 완료·실패 보고
    STOPPED --> CHECKING: 시작 버튼
```

| 상태 | 신규 매수 | 손절·청산 매도 | 시그널 평가 | 비고 |
|---|---|---|---|---|
| RUNNING | 가능 | 가능 | 평가·매매 | 정상 |
| PAUSED | 불가 | 가능 | 평가·기록(LLM 부정 매도는 옵션이 켜져 있으면 실행) | 사용자 일시정지 |
| BUY_BLOCKED | 불가 | 가능 | PAUSED와 같음 | 09:00 KST에 자동 해제 |
| DEGRADED | 불가 | 가능(REST 현재가로 점검) | 기록만 | 데이터 의심(시세 웹소켓 끊김, 시계 오차). 해소되면 자동 재점검 |
| SUSPENDED | 불가 | 불가(통신 불가) | 중지 | 네트워크 끊김, 418 차단. 해소되면 자동 재점검 |
| HALTED | 불가 | 불가 | 중지 | 사람 조치 필요, 긴급 알림 |
| STOPPED | 불가 | 불가(손절선 도달 시 알림만, NTF-17) | 중지 | 사용자 정지. 시작 버튼으로만 나감 |
| LIQUIDATING | 불가 | 전량 매도만 | 중지 | 끝나면 STOPPED |

- BUY_BLOCKED에는 RUNNING에서만 들어간다. PAUSED 중에 한도에 닿으면 PAUSED를 유지하고 "오늘 매수 차단"만 표시한다. 그날 09:00 KST 전에 재개하면 BUY_BLOCKED로 간다.
- 앱을 다시 시작하거나 SUSPENDED·DEGRADED·HALTED가 풀리면, CHECKING을 거쳐 직전 상태(RUNNING, PAUSED, BUY_BLOCKED, STOPPED)로 돌아간다. BUY_BLOCKED는 09:00 KST가 지났으면 RUNNING으로 돌아간다.
- paper와 signal-only에서는 업비트 키·IP 문제로 HALTED가 되지 않는다. 경고로만 남긴다(키 저장소 문제는 모든 모드에서 HALTED).
- 내부 오류(위험 관리·상태 불변식 위반, 위험 점검(JOB-02)이나 주문 관리의 예외 3회 연속)는 모든 모드에서 HALTED로 간다. 이때 손절도 멈춘다. 버그가 있을 수 있는 상태에서 자동 주문을 계속 내는 것보다 사람이 확인할 때까지 멈추는 쪽을 제안한다(D-058 대기, [시스템 구성도](../06-architecture/system-architecture.md) 7장). 알림은 NTF-03(MSG-E017).

## 3. 주문 상태

```mermaid
stateDiagram-v2
    [*] --> CREATED: identifier 생성·저장
    CREATED --> SUBMITTED: 전송
    SUBMITTED --> OPEN: 접수(wait, 체결 없음)
    SUBMITTED --> PARTIAL: 접수와 함께 일부 체결
    SUBMITTED --> FILLED: 즉시 전량 체결(done)
    SUBMITTED --> CANCELLED: 즉시 종료(cancel, FOK 미체결 포함)
    SUBMITTED --> REJECTED: 거절 응답(429 포함)
    SUBMITTED --> UNKNOWN: 타임아웃·연결 끊김·5xx
    CREATED --> UNKNOWN: 전송 전후 앱 종료 뒤 재시작
    UNKNOWN --> OPEN: 조회로 확인
    UNKNOWN --> FILLED: 조회로 확인
    UNKNOWN --> PARTIAL: 조회로 확인
    UNKNOWN --> CANCELLED: 조회로 확인
    UNKNOWN --> REJECTED: 60초 동안 반복 조회해도 없음
    REJECTED --> FILLED: 24시간 안에 늦게 나타남(NOT_FOUND_AFTER_UNKNOWN만)
    OPEN --> PARTIAL: 일부 체결
    OPEN --> FILLED: 전량 체결
    PARTIAL --> FILLED: 전량 체결
    OPEN --> CANCELLED: 취소
    PARTIAL --> CANCELLED: 잔량 취소·시장가 잔량 종료
    FILLED --> [*]
    CANCELLED --> [*]
    REJECTED --> [*]
```

- UNKNOWN은 identifier 조회를 1·2·4·8·15·30·45·60초에 반복하고, 60초가 지난 뒤 "없음"을 3회 이상 받고 목록 조회에도 없을 때만 REJECTED로 확정한다([매매 로직 명세](trading-logic.md) 9장, D-046). 그 뒤 24시간 안에 늦게 나타난 주문도 실제 상태로 반영한다.
- 허용하는 전이는 [매매 로직 명세](trading-logic.md) 10장 표와 같다. 그림은 줄여서 그렸다. `NOT_FOUND_AFTER_UNKNOWN`으로 닫은 REJECTED는 늦게 나타나면 실제 상태(OPEN, PARTIAL, FILLED, CANCELLED)로 다시 연다.
- UNKNOWN 절차는 live의 실제 주문 생성에만 쓴다. live-validate 주문 검증의 타임아웃·재시작은 REJECTED(VALIDATE_TIMEOUT), paper 재시작 때 남은 주문은 REJECTED(PAPER_RESTART)로 닫는다.
- UNKNOWN이 풀리기 전에는 같은 코인에 새 주문을 만들지 않는다. 5분 넘게 풀리지 않으면 긴급 알림(NTF-16).
- 주문 생성이 429를 받으면 REJECTED(reason RATE_LIMIT_429)로 기록한다. 다시 주문하려면 새 identifier로 위험 검사부터 한다.
- 상태 변화는 모두 order_events에 기록한다.
- 업비트 응답의 state(REST: wait, watch, done, cancel / myOrder: trade, prevented 추가)를 이 상태로 바꾸는 표는 [매매 로직 명세](trading-logic.md) 10장(D-047)이다. 시장가 매수는 잔량이 남으면 `cancel`로 끝날 수 있어, 코인 상태는 주문 상태가 아니라 체결 합계로 정한다.

## 4. 코인 상태

```mermaid
stateDiagram-v2
    [*] --> FLAT
    FLAT --> ENTERING: 매수 주문
    ENTERING --> HOLDING: 체결
    ENTERING --> FLAT: 취소·거절
    HOLDING --> EXITING: 매도 주문
    EXITING --> FLAT: 전량 체결
    EXITING --> HOLDING: 일부만 체결
    EXITING --> COOLDOWN: 손절 체결 + 재진입 제한 옵션
    COOLDOWN --> FLAT: 시간 경과·09시·재진입 허용 버튼
    FLAT --> BLOCKED: 경고 종목·거래지원 종료 예정
    BLOCKED --> FLAT: 경고 해제
```

- 보유 중에 경고가 뜨면 HOLDING을 유지하되 매수만 막고 알린다(MSG-W001, W002).
- 분할 매수의 추가 회차를 사는 동안에는 HOLDING을 유지한다(ENTERING으로 가지 않음). 추가 회차가 체결되지 않아도 HOLDING이다. 손절 점검 대상에서 빠지지 않는다(ADR-0008).
- 매도 뒤 남은 수량이 팔 수 없는 금액(매도 `min_total` 미만)이면 잔량으로 따로 기록하고 FLAT으로 간다([매매 로직 명세](trading-logic.md) 10장 잔량 규칙).
- "직접 풀 때까지 금지" 옵션의 COOLDOWN은 대시보드 코인 카드의 [재진입 허용] 버튼(MSG-C010)으로만 풀린다.
