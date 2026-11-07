# 로그·감사 기록 정의서

상태: 초안 · 관련: [데이터 모델](data-model.md), [보안 정책](../07-security-legal/security-policy.md)

## 1. 로그 파일

- 위치: `%LOCALAPPDATA%\upbit-autotrader\logs\app.log`
- 회전: 크기 기준(초안 10MB x 10개)과 보관 기간 90일 중 먼저 닿는 쪽.
- 수준: 기본 INFO. 설정의 고급 탭에서 DEBUG로 바꿀 수 있다.
- 형식: 시각(KST) | 수준 | 모듈 | 이벤트 코드 | 내용.

## 2. 남기지 않는 것

- API 키, Secret, JWT, `Authorization` 헤더, 디스코드 웹후크 주소(토큰 포함).
- 로그 기록기에 비밀 가리기 필터를 넣고, 비밀이 섞인 로그 줄이 실제로 가려지는지 테스트한다.
- 계정 식별 정보(이메일, 계좌 정보)는 받지도 저장하지도 않는다.
- `GET /v1/api_keys` 응답에 들어 있는 다른 키의 Access Key는 로그와 DB에 남기지 않는다(자기 키의 만료일만 쓴다).

## 3. 감사 기록 (DB)

| 대상 | 내용 | 테이블 |
|---|---|---|
| 주문 | 생성, 전송, 상태 변화, 체결, 오류 이름 | orders, order_events, fills |
| 판단 | 매수·매도·보류·차단과 이유 코드 | decisions |
| 시그널 | 지표 요약, 원문 응답, 응답 모델 | signals |
| 설정 변경 | 항목, 이전 값 → 이후 값(비밀 제외) | events |
| 모드·상태 전환 | 이전 → 이후, 원인 | events |
| 긴급 정지 | 버튼 종류, 취소·매도 결과 | events |
| 시작·종료·점검 | 시작 점검 항목별 결과 | events |
| 알림 | 보낸 알림과 성공 여부 | notifications |

## 4. 이벤트 코드 (초안)

| 코드 | 의미 |
|---|---|
| APP_START, APP_STOP | 앱 시작·종료 |
| CHECK_PASS, CHECK_FAIL | 시작 점검 결과 |
| STATE_CHANGE, MODE_CHANGE | 상태·모드 전환 |
| SIGNAL_OK, SIGNAL_FAIL | 시그널 평가 |
| DECISION | 판단 결과 |
| ORDER_SUBMIT, ORDER_UNKNOWN, ORDER_RECONCILED, ORDER_FILLED, ORDER_REJECTED | 주문 |
| RISK_BLOCK | 위험 한도 거부 |
| MARKET_WARNING | 종목 경고 감지 |
| KILL_STOP, KILL_LIQUIDATE | 긴급 정지 |
| SETTING_CHANGE | 설정 변경 |
| RATE_LIMIT_429, RATE_LIMIT_418 | 요청 한도 |
| ORDER_IMPORTED | 재조정 중 거래소에만 있던 앱 주문(`uat-`)을 들여옴 |
| SMP_PREVENTED | 자전거래 방지로 주문 수량 일부가 취소됨 |
| SETTING_EXTERNAL_CHANGE | 설정 파일이 앱 밖에서 바뀐 것을 감지 |
| SCHEMA_MIGRATED | DB·설정 파일 마이그레이션 적용 |
| CORE_UNRESPONSIVE | core 스레드 heartbeat 끊김, 또는 위험 점검(JOB-02)이 180초 넘게 끝나지 않음(MSG-E016) |
| MANUAL_ORDER_DETECTED | 같은 포켓에서 앱이 만들지 않은 주문(`uat-` 접두어 없음, 예약 주문 포함)을 발견 |
| BALANCE_RECONCILED | 대조로 보유 수량·평균 단가를 거래소 값으로 고침(MSG-W010) |
| UNMANAGED_HOLDING | 선택하지 않은 코인의 보유분을 처음 발견 |
| DUST_RECORDED | 팔 수 없는 잔량을 기록 |
| INTERNAL_ERROR | 불변식 위반, 위험 점검·주문 관리 예외 3회 연속(MSG-E017) |
| IDENTIFIER_CONFLICT | `duplicated_identifier`를 받고 조회한 주문이 이번 주문과 다름(버그) |
| UNNAMED_NOT_FOUND | 결과 불명 확인에서 개별 주문 조회가 `error.name` 없는 404를 줘서 "없음"으로 셈(D-094, 경고) |
| POSITION_RECALCULATED | 시작 점검에서 fills로 다시 계산한 포지션이 저장된 값과 달라 고침 |
| ORDER_TYPE_UNSUPPORTED | 주문 가능 정보의 `bid_types`에 `best_fok`가 없어 그 코인 매수를 보류 |
| EXIT_ONLY_BLOCKED | paper에서 exit_only 실보유분의 주문을 키·IP 오류로 낼 수 없음(MSG-E019) |

## 5. 보관과 공유

- DB는 기간 제한 없이 보관한다. 시그널 입출력 원문 때문에 연 40~50MB를 예상한다([데이터 모델](data-model.md) 7장). 하루 1회 백업하고 7개를 남긴다.
- 공개 저장소에 이슈를 올릴 때 로그나 DB를 그대로 첨부하지 않는다. 금액, IP, 주문 ID를 가린 진단 묶음을 만드는 기능을 7단계에서 만든다(범위는 아직 정하지 않았다. 7단계 시작 전에 정한다, D-066 대기).
