# 업비트 API 연동 명세

상태: 확정(2026-11 기준 사실, 2026-11-05 공식 문서로 재확인. 체크리스트 A 확인 방법(D-048), 클라이언트 선택(D-038), 매수·매도 값 구분(D-067), 일괄 취소 미사용(D-069)은 대기) · 출처: https://docs.upbit.com/kr (각 쪽은 끝에 `.md`를 붙이면 본문과 OpenAPI 정의를 받을 수 있다) · 관련: [매매 로직 명세](../03-functional/trading-logic.md), [운영 런북](../09-operations/runbook.md), [ADR-0006 업비트 클라이언트](../06-architecture/adr/0006-upbit-client.md)

## 1. 키 정책

- 권한은 **자산조회, 주문조회, 주문하기**만 준다. 출금·입금·자산이전·포켓관리 권한은 주지 않는다.
- 발급 조건: 고객 확인(KYC)과 2채널 인증을 마친 뒤 **PC 웹**의 [마이페이지 > Open API 관리]에서만 발급한다. Secret Key는 발급 화면에서 한 번만 보인다.
- 발급 수: 메인포켓에서 최대 10개, 서브포켓마다 최대 5개.
- 허용 IP: 키마다 공인 IPv4를 최소 1개, 최대 10개 등록한다. IPv6는 안 된다. 업비트는 유동 IP 사용을 권장하지 않는다.
- 유효기간 1년, 연장 불가. 만료되거나 권한을 바꾸려면 삭제하고 새로 발급한다.
- **포켓:** 메인포켓 1개와 서브포켓 최대 5개. 서브포켓은 만든 뒤 이름 변경·삭제가 안 된다. 거래·자산 관리(Exchange) API 한도는 포켓 단위다(같은 포켓의 키는 한도를 공유).

| 권한 | 기능 | 메인포켓 | 서브포켓 |
|---|---|---|---|
| 포켓관리 | 모든 포켓의 자산 조회, 자산 이전 실행·내역 조회, 포켓 정보 조회 | 가능 | - |
| 자산이전 | 그 포켓 기준의 포켓 간 자산 이전·내역 조회 | - | 가능 |
| 자산조회 | 그 포켓의 보유 자산·잔고 조회 | 가능 | 가능 |
| 주문조회 | 그 포켓의 체결·미체결 주문 조회 | 가능 | 가능 |
| 주문하기 | 그 포켓의 매수·매도 주문과 취소 | 가능 | 가능 |
| 출금조회, 출금하기, 입금조회, 입금하기 | 입출금 | 가능 | - |

- **봇 키 발급 절차(서브포켓):** 봇 전용 서브포켓을 만든다 → PC 웹 Open API 관리(https://upbit.com/mypage/open_api_management)에서 그 서브포켓의 키를 발급한다(문서에 메인포켓용·서브포켓용 발급 화면이 따로 나온다) → 권한은 자산조회·주문조회·주문하기만 체크한다(자산이전은 체크하지 않는다) → 허용 IP를 넣는다 → 2채널 인증 → Access Key와 Secret Key를 받는다. 서브포켓 키는 출금·입금 권한을 가질 수 없다. 출처: [API Key 발급 받기](https://docs.upbit.com/kr/docs/api-key)(2026-07-07 갱신), [포켓(Pocket)](https://docs.upbit.com/kr/reference/pocket-overview)(2026-10-20 갱신).
- **확인 필요:** 서브포켓을 만드는 화면(앱 또는 웹 메뉴 위치)은 개발자 문서에 없다. 사용자가 업비트 화면에서 확인한다.
- **키 만료일 조회:** `GET /v1/api_keys`(API Key 목록 조회)가 있다. 계정의 모든 키 목록과 각 키의 `access_key`, `expire_at`(KST, `yyyy-MM-dd'T'HH:mm:ss+09:00`)을 준다. 인증만 필요하고 별도 권한은 필요 없다. default 그룹(포켓당 초당 30회). 앱은 자기 `access_key`의 `expire_at`만 저장하고 다른 키 정보는 버린다. 출처: [API Key 목록 조회](https://docs.upbit.com/kr/reference/list-api-keys)(2026-11-04 갱신).
- **포켓별 키 정보:** `GET /v1/pockets/api_keys`는 포켓별로 키의 `permissions`, `allowed_ips`, `created_at`, `expired_at`을 준다. 하지만 **메인포켓에서 발급하고 [포켓관리] 권한이 있는 키만** 부를 수 있다(아니면 `out_of_scope`). `GET /v1/pockets`(포켓 목록)도 같다. 봇의 서브포켓 키로는 자기 포켓·권한·허용 IP 목록을 API로 확인할 수 없다. 출처: [포켓별 API Key 목록 조회](https://docs.upbit.com/kr/reference/list-pocket-api-keys), [포켓 정보 조회](https://docs.upbit.com/kr/reference/list-pockets).
- 그래서 실전 전환 체크리스트 A의 "서브포켓 키인지", "권한이 3개뿐인지"는 사용자가 확인 표시하고, 앱은 자기가 확인할 수 있는 것(인증 호출 성공 = 현재 IP 허용, 잔고 조회·주문 조회·주문 검증 성공 = 권한 3개 동작)만 자동으로 확인한다(D-048 대기, [위험 관리 정책서](../03-functional/risk-policy.md) 6장).
- **확인 필요:** 서브포켓 키로 `GET /v1/api_keys`를 부르면 계정의 모든 키가 나오는지, 그 포켓의 키만 나오는지는 문서에 없다. 사용자 PC에서 처음 키를 검증할 때 자기 `access_key`가 목록에 있는지로 확인한다. 없거나 호출이 실패하면 사용자가 입력한 발급일 + 1년을 쓴다.

## 2. 사용하는 API

| 용도 | 메서드·경로 | 권한 | 한도 그룹 | 비고 |
|---|---|---|---|---|
| 종목 목록·경고 | GET /v1/market/all?is_details=true | 없음 | market(초당 10, IP) | `market_event.warning`, `market_event.caution`(5개 항목) 사용. `market_warning`은 폐기 |
| 분 캔들 | GET /v1/candles/minutes/{unit} | 없음 | candles(초당 10, IP. 한도표 표기는 candle) | unit 1, 3, 5, 10, 15, 30, 60, 240. count 최대 200. 체결이 없던 구간은 캔들이 없다 |
| 일 캔들 | GET /v1/candles/days | 없음 | candles | 경계는 UTC 00:00(KST 09:00) |
| 현재가 | GET /v1/ticker | 없음 | ticker(초당 10, IP) | 웹소켓 보조, DEGRADED 손절. 숫자는 JSON 숫자(double)로 온다 |
| 호가 | GET /v1/orderbook | 없음 | orderbook(초당 10, IP) | 페이퍼 체결 계산. 숫자는 JSON 숫자로 온다 |
| 호가 단위 | GET /v1/orderbook/instruments | 없음 | orderbook | `tick_size`(2025-07-31 추가) |
| 잔고(포켓 잔고) | GET /v1/accounts | 자산조회 | default(초당 30, 포켓) | 그 포켓의 잔고. 시작 점검, 대조, JOB-14 |
| 주문 가능 정보 | GET /v1/orders/chance | 주문조회 | default | `bid_fee`, `ask_fee`, `market.bid.min_total`(매수), `market.ask.min_total`(매도), `market.max_total`, `market.state`, `bid_types`·`ask_types`. 매수 판단은 bid 값, 매도 판단은 ask 값을 쓴다(D-067 대기). `bid_types`에 `best_fok`가 없으면 그 코인 매수 보류 |
| 주문 생성 | POST /v1/orders | 주문하기 | order(초당 12, 포켓) | JSON만, `smp_type` 항상 명시, 자동 재시도 금지 |
| 주문 검증 | POST /v1/orders/test | 주문하기 | order-test(초당 8, 포켓) | live-validate. 응답 UUID·identifier로 조회·취소 불가 |
| 주문 조회 | GET /v1/order | 주문조회 | default | uuid 또는 identifier. 없으면 404 `order_not_found` |
| id로 주문 목록 조회 | GET /v1/orders/uuids | 주문조회 | default | `uuids[]` 또는 `identifiers[]`(둘 중 하나), 최대 100개 |
| 미체결 목록 | GET /v1/orders/open | 주문조회 | default | `states[]` wait·watch, limit 최대 100, page |
| 종료 주문 | GET /v1/orders/closed | 주문조회 | default | 조회 구간 최대 7일, limit 최대 1,000 |
| 주문 취소 | DELETE /v1/order | 주문하기 | default | uuid 또는 identifier. 쿼리 파라미터만 |
| (쓰지 않음) 일괄 취소 | DELETE /v1/orders/open | 주문하기 | order-cancel-all(2초에 1회) | 최대 300건(기본 20), `pairs`로 코인 지정. identifier로 거를 수 없어 사용자가 직접 낸 주문까지 취소하므로 쓰지 않는다. 정지 때는 앱 주문만 `DELETE /v1/order?identifier=`로 하나씩 취소한다(D-069 대기) |
| 키 만료일 | GET /v1/api_keys | 인증만 | default | 1장 |

### 웹소켓

| 종류 | 주소 | 타입 | 인증 |
|---|---|---|---|
| 공개 | wss://api.upbit.com/websocket/v1 | ticker(`market_state`(PREVIEW·ACTIVE·DELISTED)와 `delisting_date`를 쓴다. `is_trading_suspended`·`market_warning`은 폐기 필드라 읽지 않는다), trade, orderbook, candle | 없음 |
| 비공개 | wss://api.upbit.com/websocket/v1/private | myOrder, myAsset(권한 필요), announcement(2026-08-31부터, 권한 불필요) | JWT(Authorization 헤더) |

- 한도: 연결 초당 5회(인증 없으면 IP, 있으면 포켓 단위), 메시지는 연결마다 초당 5회·분당 100회. 웹소켓은 남은 요청 수를 알려 주지 않으므로 앱이 센다.
- 120초 동안 주고받은 데이터가 없으면 서버가 연결을 끊는다. PING 프레임을 보내거나 "PING" 문자열을 보낸다(그러면 서버가 10초마다 `{"status":"UP"}`를 보낸다). 업비트 예제는 30초 간격 PING을 쓴다.
- 비공개 웹소켓은 연결을 많이 유지하면 새 연결이 거절될 수 있다. 연결 하나에서 필요한 타입을 함께 구독한다.
- myOrder는 주문·체결이 있을 때만 데이터가 온다. 상태값은 `wait`, `watch`, `trade`, `done`, `cancel`, `prevented`다([매매 로직 명세](../03-functional/trading-logic.md) 10장).
- 웹소켓 숫자는 JSON 숫자(Double)로 오고 지수 표기(`9.101e-05`)도 온다. 시세 REST(ticker, orderbook, candles)도 JSON 숫자다. 거래 REST만 문자열이다. 모두 `Decimal`로 파싱한다([데이터 모델](../04-data/data-model.md) 2장, D-071).
- 재연결 후에는 REST로 잔고·미체결·종목을 다시 대조한다(그동안 놓친 이벤트가 있을 수 있음). 공지(announcement)는 실시간 전용이라 놓친 공지는 다시 오지 않는다.

## 3. 인증

- JWT, `Authorization: Bearer <JWT>`. 서명 알고리즘은 HS512를 쓴다(업비트 권장). Secret Key는 Base64 디코딩 없이 그대로 쓴다.
- 페이로드: `access_key`, `nonce`(매 요청 새 UUID, 다시 쓰면 `nonce_used`), 파라미터나 본문이 있으면 `query_hash`(SHA512 16진수)와 `query_hash_alg`(SHA512).
- GET·DELETE: 전송할 쿼리 파라미터를 같은 순서로 이은 문자열을 URL 인코딩하기 전 상태로 해시한다. 예를 들어 `pairs=KRW-BTC,KRW-ETH`는 `,`를 그대로 둔 문자열로 해시하고, 전송 URL에서만 값을 인코딩한다. 인코딩한 문자열로 해시하면 `:`·`+`·`,`처럼 인코딩으로 바뀌는 문자가 든 요청에서 서버가 계산한 해시와 달라져 401 인증 오류(`invalid_query_payload` 등)가 날 수 있다. 배열은 `uuids[]=a&uuids[]=b`처럼 키를 반복한다. 쿼리 값은 URL 인코딩하되 배열 이름의 `[`, `]`는 인코딩하지 않는다(REST 안내). 공식 SDK 1.1.0은 대괄호를 `%5B%5D`로 인코딩해 보내므로 두 공식 출처가 다르다. 앱은 REST 안내를 따르고, 사용자 PC에서 첫 키 검증 때 배열 파라미터가 있는 읽기 전용 호출(`/v1/orders/uuids` 등)로 확인한다(확인 필요).
- identifier와 쿼리 값에는 공백·`+`를 넣지 않는다. 해시 문자열과 서버 해석이 어긋날 수 있다.
- POST: JSON 본문을 `key=value&...` 형태로 바꿔 해시한다.
- 페이로드에 시각이 없어서 PC 시계 오차가 인증에 영향을 주지 않는다.

## 4. 요청 한도 처리

- `Remaining-Req: group=...; min=...; sec=...`에서 `sec`만 쓴다(`min`은 폐기, 2026-08-21부터 분당 한도 없음).
- 그룹별 토큰 버킷으로 한도의 절반 이하만 쓴다.
- 버킷은 경로별 고정 표(`/v1/candles` → candles, `/v1/market` → market 등, 2장 표)로 고른다. 응답 헤더의 group 값은 표와 맞는지 확인하고 기록하는 데만 쓰고, 모르는 group 값이면 경고만 남긴다. 공식 한도표는 캔들 그룹을 `candle`로 적지만, 실제 헤더와 공식 예제는 `candles`다(2026-11-05 공개 시세 호출 `remaining-req: group=candles; min=600; sec=9`). 녹화 응답에는 실제 헤더 값을 넣는다.
- 429: 그 그룹 호출을 멈추고 다음 초 경계까지 기다린다. 조회(GET)는 다음 초에 같은 요청을 다시 보낸다. 주문 생성(POST)은 REJECTED(RATE_LIMIT_429)로 기록하고, 다시 주문할 때는 새 identifier로 위험 검사부터 한다(손절은 다음 초에 바로).
- 418: 429가 쌓여 일시 차단된 것이다(IP·포켓·연결 단위). 응답에 담긴 차단 시간이 지날 때까지 SUSPENDED로 두고 알린다. 반복되면 차단 시간이 길어진다.
- `Origin` 헤더를 보내지 않는다. 보내면 시세 REST와 웹소켓이 10초에 1회로 제한되고 `Remaining-Req`의 group이 `origin`으로 온다. 화면에 웹뷰를 쓰더라도 업비트 호출은 Python에서만 한다.

## 5. 오류 처리

오류는 `error.name`으로 분기한다. `error.message`는 바뀔 수 있다. 같은 `out_of_scope`가 401이나 403으로 올 수 있으므로 HTTP 상태만으로 분기하지 않는다. 시세(Quotation) API는 `error.name`이 숫자(예: 400)이고, 거래(Exchange) API는 문자열이다. 출처: [REST API 사용 및 에러 안내](https://docs.upbit.com/kr/reference/rest-api-guide)(2026-10-06 갱신)와 각 API의 응답 예시.

| error.name | HTTP | 의미 | 앱 동작 |
|---|---|---|---|
| no_authorization_ip | 401 | 허용되지 않은 IP(메시지에 IP 없음) | HALTED(live 계열), MSG-E001(현재 IP는 따로 확인) |
| expired_access_key | 401 | 키 만료 | HALTED(live 계열), MSG-E002 |
| jwt_verification, invalid_query_payload, nonce_used, no_authorization_token | 401 | 서명·페이로드·nonce·토큰 누락 오류 | HALTED(live 계열), MSG-E003. 버그일 가능성이 높으므로 로그에 상세(비밀 제외) |
| out_of_scope | 401 또는 403 | 권한 부족 | HALTED(live 계열), MSG-E003 |
| insufficient_funds_bid, insufficient_funds_ask | 400 | 잔고 부족 | 주문 거절, 잔고 재조회. live-validate 매도의 ask는 예상된 결과 |
| under_min_total_bid, under_min_total_ask | 400 | 최소 주문 금액 미만 | 거절, 사이징 오류로 기록 |
| over_krw_funds_bid | 400 | 최대 주문 금액 초과 | 거절, 사이징 오류로 기록 |
| invalid_parameter, validation_error, invalid_time_in_force, invalid_post_only, create_bid_error, create_ask_error | 400 | 파라미터·조합 오류 | 거절, 버그로 기록 |
| duplicated_identifier | 400 | 이미 쓴 identifier | 앱은 같은 identifier를 다시 보내지 않으므로, 같은 요청이 중간에서 한 번 더 전달돼 주문이 이미 있을 수 있다. REJECTED로 닫지 않고 UNKNOWN으로 두어 identifier 조회로 확인한다. 이번 주문이 아니면 REJECTED(DUPLICATED_IDENTIFIER) + 이벤트 IDENTIFIER_CONFLICT([매매 로직 명세](../03-functional/trading-logic.md) 8장, D-070) |
| notfoundmarket | 400 | 없는 마켓 | 거절, 종목 목록 갱신 |
| market_offline | 403 | 점검 등으로 주문 불가 | 해당 코인 매수 보류 |
| order_not_found | 404 | 주문 없음 | 조회 결과 "없음"(매매 로직 명세 9장) |
| HTTP 429 | 429 | 초당 한도 초과 | GET은 다음 초에 다시, 주문 POST는 REJECTED 후 새 identifier |
| HTTP 418 | 418 | 일시 차단 | SUSPENDED + 알림 |
| HTTP 5xx | 500 | 서버 오류·점검 | 주문 POST는 UNKNOWN, 조회는 1회 다시 |

- 이전 문서의 `invalid_access_key`는 현재 공식 오류 목록에 없다. 키가 틀리면 `jwt_verification` 등으로 온다고 보고, 목록에 없는 이름은 HTTP 상태로 분류한다.
- 웹소켓 오류: `INVALID_AUTH`, `WRONG_FORMAT`, `NO_TICKET`, `NO_TYPE`, `NO_CODES`, `INVALID_PARAM`, `TOO_MANY_REQUEST`.

## 6. 반드시 반영할 변경 사항

| 날짜 | 내용 | 대응 |
|---|---|---|
| 2024-11-20 | market/all의 market_warning 제거 → market_event | market_event만 읽음 |
| 2026-07-31 | 같은 헤더(Content-Type, User-Agent, Cache-Control 등)를 두 번 보내면 값이 합쳐지고 Content-Type 중복은 400 | 헤더는 한 번만, 보내는 헤더를 테스트로 확인 |
| 2026-08-21 | 주문 한도 초당 8 → 12, 분당 한도 폐지 | sec 기준 |
| 2026-08-31 | 비공개 웹소켓 announcement 추가 | 공지 감지에 사용 |
| 2026-09-01 | 포켓 API를 공식 SDK에서 지원(Python SDK 1.0.0) | 1장 |
| 2026-11-09 | `smp_type` 생략 시 기본값 cancel_maker, `none` 값 추가, 응답에 `smp_type` 항상 포함 | 항상 `cancel_maker` 명시 |
| 2026-11-16 | 슬래시 중복·끝 슬래시 경로는 오류, `error.name`으로 분기 권장 | URL은 `https://api.upbit.com` + `/v1/...` |
| (계속) | POST는 JSON만(`Content-Type: application/json; charset=utf-8`), TLS 1.2 이상, 한도는 포켓 단위 | |

## 7. 테스트

- 업비트에는 테스트넷이 없다. 개발은 가짜 거래소와 녹화 응답으로 한다.
- 실전 전 점검은 `/v1/orders/test`(형식·주문 가능 여부만 검증, 체결 없음)로 한다.
- 클라우드 세션에서는 공개 시세 API만 호출한다(키가 없고 허용 IP도 아님).
- 비공개 API 녹화 응답은 공식 문서의 OpenAPI 예시를 바탕으로 만든다.

## 8. 클라이언트 선택

[ADR-0006](../06-architecture/adr/0006-upbit-client.md)(제안, D-038 대기)을 따른다. 공식 `upbit-sdk`는 PyPI에 0.9.0(2026-04-14), 1.0.0(2026-09-01), 1.1.0(2026-10-20)이 있다. `pyupbit`는 2024-06 이후 유지보수가 멈춰 쓰지 않는다.
