# 업비트 API 연동 명세

상태: 확정(2026-11 기준) · 출처: https://docs.upbit.com/kr · 관련: [매매 로직 명세](../03-functional/trading-logic.md), [운영 런북](../09-operations/runbook.md)

## 1. 키 정책

- 권한은 **자산조회, 주문조회, 주문하기**만 준다. 출금·입금 권한은 주지 않는다.
- 발급 조건: 본인 인증(KYC)과 2채널 인증을 마친 뒤 PC 웹에서만 발급. Secret Key는 발급 화면에서 한 번만 보인다.
- 허용 IP: 공인 IPv4를 최소 1개, 최대 10개 등록해야 한다. 업비트는 유동 IP를 권장하지 않는다.
- 유효기간 1년, 연장 불가. 만료되면 삭제하고 새로 발급한다.
- 서브 포켓 키는 자산조회, 주문조회, 주문하기, 자산이전만 가능하다. 봇은 봇 전용 서브 포켓에서 발급한 키를 쓴다. 기본 포켓 키를 쓰면 계정 전체 잔고가 노출 범위가 된다. 포켓별 발급 절차는 1단계에서 문서로 확인한다.
- 키 목록·만료일을 돌려주는 API가 있는지 1단계에서 확인한다. 있으면 사용자가 입력한 발급일보다 우선한다.

## 2. 사용하는 API

| 용도 | 메서드·경로 | 인증 | 한도 그룹 | 비고 |
|---|---|---|---|---|
| 종목 목록·경고 | GET /v1/market/all?is_details=true | 없음 | market(초당 10, IP) | market_event 사용, market_warning은 폐기됨 |
| 분 캔들 | GET /v1/candles/minutes/{unit} | 없음 | candle | unit 1, 3, 5, 10, 15, 30, 60, 240. count 최대 200 |
| 일 캔들 | GET /v1/candles/days | 없음 | candle | 경계는 UTC 00:00(KST 09:00) |
| 현재가 | GET /v1/ticker | 없음 | ticker | 웹소켓 보조 |
| 잔고 | GET /v1/accounts | 키 | default(초당 30, 포켓) | 시작 점검, 대조, 10분 정기 점검(JOB-14) |
| 주문 가능 정보 | GET /v1/orders/chance | 키 | default | 수수료, min_total, max_total |
| 주문 생성 | POST /v1/orders | 주문하기 | order(초당 12, 포켓) | JSON만, smp_type 항상 명시 |
| 주문 검증 | POST /v1/orders/test | 주문하기 | order-test(초당 8) | live-validate. 응답 ID로 조회·취소 불가 |
| 주문 조회 | GET /v1/order | 키 | default | uuid 또는 identifier |
| 미체결 목록 | GET /v1/orders/open | 키 | default | 대조 |
| 종료 주문 | GET /v1/orders/closed | 키 | default | 조회 범위 최대 7일 |
| 주문 취소 | DELETE /v1/order | 키 | 1단계에서 확인 | 정지 시 |
| 일괄 취소 | DELETE /v1/orders/open | 키 | 2초에 1회 | 최대 300건 |

### 웹소켓

| 종류 | 주소 | 타입 | 인증 |
|---|---|---|---|
| 공개 | wss://api.upbit.com/websocket/v1 | ticker(market_state, delisting_date 포함), trade, orderbook, candle | 없음 |
| 비공개 | wss://api.upbit.com/websocket/v1/private | myOrder, myAsset, announcement(2026-08-31부터) | JWT(Authorization 헤더) |

- 연결 초당 5회, 연결당 메시지 초당 5회·분당 100회.
- 120초 동안 데이터가 없으면 끊긴다. 30~60초마다 PING을 보낸다. 서버는 10초마다 `{"status":"UP"}`를 보낸다.
- 재연결 후에는 REST로 잔고·미체결·종목을 다시 대조한다(그동안 놓친 이벤트가 있을 수 있음). 공지(announcement)는 실시간 전용이라 놓친 공지는 다시 오지 않는다.

## 3. 인증

- JWT HS512, `Authorization: Bearer <JWT>`. Secret Key는 Base64 디코딩 없이 그대로 쓴다.
- 페이로드: `access_key`, `nonce`(매 요청 새 UUID), 파라미터나 본문이 있으면 `query_hash`(SHA512 16진수)와 `query_hash_alg`(기본 SHA512).
- GET·DELETE: 실제 전송하는 쿼리 문자열을 URL 인코딩 전, 순서 그대로 해시한다. 배열은 `uuids[]=a&uuids[]=b`처럼 키를 반복한다.
- POST: JSON 본문을 `key=value&...` 형태로 바꿔 해시한다.
- 페이로드에 시각이 없어서 PC 시계 오차가 인증에 영향을 주지 않는다.

## 4. 요청 한도 처리

- `Remaining-Req: group=...; min=...; sec=...`에서 `sec`만 쓴다(`min`은 폐기, 분당 한도는 2026-08-21에 없어짐).
- 그룹별 토큰 버킷으로 한도의 절반 이하만 쓴다.
- 429: 조회(GET)는 다음 초에 같은 요청을 다시 보낸다. 주문 생성(POST)은 REJECTED(RATE_LIMIT_429)로 기록하고, 다시 주문할 때는 새 identifier로 위험 검사부터 한다(손절은 다음 초에 바로).
- 418: 응답에 담긴 차단 시간 동안 SUSPENDED로 두고 알린다. 반복 위반이면 차단 시간이 길어진다.
- `Origin` 헤더를 보내지 않는다. 보내면 시세 REST와 웹소켓이 10초에 1회로 제한된다. 화면에 웹뷰를 쓰더라도 업비트 호출은 Python에서만 한다.

## 5. 오류 처리

오류는 `error.name`으로 분기한다. `error.message`는 바뀔 수 있다.

| error.name | 의미 | 앱 동작 |
|---|---|---|
| no_authorization_ip | 허용되지 않은 IP | HALTED, MSG-E001 |
| expired_access_key | 키 만료 | HALTED, MSG-E002 |
| invalid_access_key, jwt_verification (이름은 1단계에서 문서와 대조) | 키·서명 오류 | HALTED, MSG-E003 |
| insufficient_funds_bid, insufficient_funds_ask | 잔고 부족 | 주문 거절, 잔고 재조회 |
| under_min_total_bid, under_min_total_ask (이름은 1단계에서 대조) | 최소 주문 금액 미만 | 거절, 사이징 오류로 기록 |
| invalid_parameter | 파라미터 오류 | 거절, 버그로 기록 |
| market_offline | 거래할 수 없는 상태 | 해당 코인 매수 차단 |
| HTTP 429 | 초당 한도 초과 | GET은 다음 초에 다시, 주문 POST는 REJECTED 후 새 identifier |
| HTTP 418 | 일시 차단 | SUSPENDED + 알림 |

## 6. 반드시 반영할 변경 사항

| 날짜 | 내용 | 대응 |
|---|---|---|
| 2024-11-20 | market/all의 market_warning 제거 → market_event | market_event만 읽음 |
| 2026-07-31 | 같은 헤더를 두 번 보내면 400 | Content-Type은 한 번만, 보내는 헤더를 테스트로 확인 |
| 2026-08-21 | 주문 한도 초당 8 → 12, 분당 한도 폐지 | sec 기준 |
| 2026-08-31 | 비공개 웹소켓 announcement 추가 | 공지 감지에 사용 |
| 2026-11-09 | smp_type 생략 시 기본값 cancel_maker | 항상 명시 |
| 2026-11-16 | 슬래시 중복·끝 슬래시 경로 오류, error.name으로 분기 권장 | URL은 `https://api.upbit.com` + `/v1/...` |
| (계속) | POST는 JSON만, 한도는 포켓 단위 | |

## 7. 테스트

- 업비트에는 테스트넷이 없다. 개발은 가짜 거래소와 녹화 응답으로 한다.
- 실전 전 점검은 `/v1/orders/test`(형식·주문 가능 여부만 검증, 체결 없음)로 한다.
- 클라우드 세션에서는 공개 시세 API만 호출한다(키가 없고 허용 IP도 아님).

## 8. 클라이언트 선택 (1단계, ADR-0006)

| 후보 | 장점 | 단점 |
|---|---|---|
| 공식 `upbit-sdk`(v1.1.0, 2026-10-20) | 업비트가 관리, REST·웹소켓 지원 | 2026-09 출시로 이력이 짧음. PyInstaller 호환은 직접 확인 필요 |
| httpx 기반 자체 클라이언트 | 동작을 완전히 통제, 테스트 쉬움 | 직접 구현·유지보수 |
| ccxt | 여러 거래소 지원 | 무겁고 업비트 최신 한도·기능 반영이 늦음 |
| pyupbit | - | 2024-06 이후 유지보수 중단. 사용 안 함 |
