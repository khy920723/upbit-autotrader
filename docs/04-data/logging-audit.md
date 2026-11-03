# 로그·감사 기록 정의서

상태: 초안 · 관련: [데이터 모델](data-model.md), [보안 정책](../07-security-legal/security-policy.md)

## 1. 로그 파일

- 위치: `%LOCALAPPDATA%\upbit-autotrader\logs\app.log`
- 회전: 크기 기준(초안 10MB x 10개)과 보관 기간 90일 중 먼저 닿는 쪽.
- 수준: 기본 INFO. 설정의 고급 탭에서 DEBUG로 바꿀 수 있다.
- 형식: 시각(KST) | 수준 | 모듈 | 이벤트 코드 | 내용.

## 2. 남기지 않는 것

- API 키, Secret, JWT, `Authorization` 헤더, 텔레그램 토큰이 들어간 URL, 네이버 Client Secret.
- 로그 기록기에 비밀 가리기 필터를 넣고, 비밀이 섞인 로그 줄이 실제로 가려지는지 테스트한다.
- 계정 식별 정보(이메일, 계좌 정보)는 받지도 저장하지도 않는다.

## 3. 감사 기록 (DB)

| 대상 | 내용 | 테이블 |
|---|---|---|
| 주문 | 생성, 전송, 상태 변화, 체결, 오류 이름 | orders, order_events, fills |
| 판단 | 매수·매도·보류·차단과 이유 코드 | decisions |
| 시그널 | 지표 요약, 뉴스 제목, 원문 응답, 응답 모델 | signals, signal_news |
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

## 5. 보관과 공유

- DB는 기간 제한 없이 보관한다(연간 수 MB 예상). 하루 1회 백업하고 7개를 남긴다.
- 공개 저장소에 이슈를 올릴 때 로그나 DB를 그대로 첨부하지 않는다. 금액, IP, 주문 ID를 가린 진단 묶음을 만드는 기능을 7단계에서 만든다(1단계에서 범위 결정).
