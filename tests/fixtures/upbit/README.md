# 업비트 공개 시세 API 녹화 응답

업비트 공개 시세(Quotation) API에서 실제로 받은 응답의 작은 샘플이다. 응답 형식과 파싱을 확인하는 테스트, 그리고 [가짜 구현 명세](../../../docs/08-quality/fakes-spec.md)의 FakeExchange(HTTP 층)에 쓴다.

## 받은 시각과 방법

- **받은 시각:** 2026-11-05 02:02:00 ~ 02:02:10 UTC (11:02 KST). `ticker_error_mixed_markets.json`만 02:36:42 UTC(11:36 KST)에 받았다. 요청마다 정확한 시각은 `manifest.json`의 `requested_at_utc`와 응답 `Date` 헤더에 있다.
- **받은 곳:** Claude 클라우드 세션(QA 세션). 키 없이 공개 시세 API만 호출했다.
- **방법:**
  - 기본 URL `https://api.upbit.com`에 `/v1/...`를 붙였다. 끝 슬래시와 중복 슬래시는 없다.
  - GET만 보냈다. 보낸 헤더는 `Accept: application/json`, `User-Agent: qa-fixture-recorder`뿐이다. `Origin` 헤더는 보내지 않았다(보내면 시세 API가 10초에 1회로 제한된다).
  - 요청 사이에 1초를 쉬었다(초당 1회). 업비트 시세 그룹 한도(IP당 초당 10회)와 이 세션의 규칙(초당 5회 이하)보다 낮다.
  - 응답 본문은 토큰(숫자 표기 포함)을 바꾸지 않고 줄바꿈과 들여쓰기만 넣었다. 저장 뒤 원본과 토큰 순서가 같은지, `Decimal`로 읽은 값이 같은지 확인했다.
  - `market/all`은 응답 875개 중 8개만 골라 원래 순서대로 저장했다. 항목 안의 값은 바꾸지 않았다.
  - 응답 헤더는 `Date`, `Content-Type`, `Remaining-Req` 세 개만 `manifest.json`에 남겼다. 나머지 헤더는 저장하지 않았다.

다시 받을 때는 같은 규칙을 지킨다. 예:

```bash
curl -sS -H 'Accept: application/json' 'https://api.upbit.com/v1/ticker?markets=KRW-BTC,KRW-ETH,KRW-XRP'
```

여러 개를 받을 때는 요청 사이에 `sleep 1`을 넣는다. 다시 받으면 이 README의 시각과 "관찰한 사실"을 고친다.

## 파일

| 파일 | 요청 | 상태 | 내용 |
|---|---|---|---|
| `market_all_details.json` | `GET /v1/market/all?is_details=true` | 200 | 8개 항목(아래 표) |
| `candles_minutes_240_krw_btc.json` | `GET /v1/candles/minutes/240?market=KRW-BTC&count=5` | 200 | 240분봉 5개, 최신순 |
| `candles_days_krw_btc.json` | `GET /v1/candles/days?market=KRW-BTC&count=5` | 200 | 일봉 5개, 최신순 |
| `ticker_krw_btc_eth_xrp.json` | `GET /v1/ticker?markets=KRW-BTC,KRW-ETH,KRW-XRP` | 200 | 현재가 3개 |
| `orderbook_krw_btc.json` | `GET /v1/orderbook?markets=KRW-BTC` | 200 | 호가 30단계 |
| `ticker_error_unknown_market.json` | `GET /v1/ticker?markets=KRW-NOTEXIST` | 404 | 시세 API 오류 형식 |
| `ticker_error_mixed_markets.json` | `GET /v1/ticker?markets=KRW-BTC,KRW-NOTEXIST` | 404 | 있는 마켓과 없는 마켓을 함께 요청하면 전체가 404 |
| `manifest.json` | - | - | 파일별 요청 경로, 상태, 응답 헤더 3개, 받은 시각 |

### market_all_details.json에 고른 항목

| 마켓 | warning | caution에서 참인 항목 | 고른 이유 |
|---|---|---|---|
| KRW-BTC, KRW-ETH, KRW-XRP | false | 없음 | 정상 종목 |
| KRW-ZIL | true | GLOBAL_PRICE_DIFFERENCES | 유의 + 주의 |
| KRW-ELSA | false | PRICE_FLUCTUATIONS, TRADING_VOLUME_SOARING, DEPOSIT_AMOUNT_SOARING | 주의 플래그 여러 개 |
| KRW-QKC | false | TRADING_VOLUME_SOARING | 주의 플래그 하나 |
| BTC-HBD | true | 없음 | KRW가 아닌 마켓(걸러져야 함). "warning만 참" 모양의 참고용 |
| USDT-BTC | false | 없음 | KRW가 아닌 마켓(걸러져야 함) |

## 관찰한 사실 (테스트와 가짜 구현이 알아야 할 것)

1. **숫자 표기가 섞여 있다.** 같은 응답 안에 `0.01270000`과 `0.0127`, `108328000.00000000`과 `108659000`이 함께 온다. ticker의 `acc_trade_price`는 `15639124215.8082700000000000`처럼 자릿수가 길어 float로 읽으면 값이 달라진다. 테스트는 `json.loads(text, parse_float=Decimal)`로 읽는다.
2. **`Remaining-Req`의 그룹 이름이 문서와 다르다.** 캔들 응답은 `group=candles`인데 [요청 수 제한 문서](https://docs.upbit.com/kr/reference/rate-limits)의 표는 `candle`이다. 폐기된 `min` 필드(`min=600`)도 아직 온다. 앱은 [업비트 API 연동 명세](../../../docs/05-integration/upbit-api.md) 4장대로 경로별 표로 요청 한도 버킷을 고르고, 응답의 group 값은 표와 맞는지 확인·기록하는 데만 쓴다. 표의 캔들 그룹은 `candles`여야 한다. 남은 수는 `sec`만 읽는다.
3. **`Content-Type` 표기가 다르다.** 성공 응답은 `application/json;charset=UTF-8`, 오류 응답은 `application/json; charset=utf-8`이다. 문자열을 그대로 비교하지 않는다.
4. **시세 API 오류의 `error.name`은 숫자다.** 없는 마켓은 `404`, `{"error": {"name": 404, "message": "Code not found"}}`. 거래(Exchange) API의 `error.name`은 문자열이다.
5. **여러 마켓을 한 번에 요청할 때 하나라도 없으면 전체가 404다.** `KRW-BTC,KRW-NOTEXIST`를 요청하면 KRW-BTC 값도 오지 않는다. 선택한 코인 하나가 거래지원 종료로 목록에서 빠지면, 여러 코인을 묶은 REST 현재가 조회(DEGRADED 때 손절에 쓰는 값)가 모두 실패할 수 있다.
6. **캔들은 최신순이고 첫 항목은 진행 중인 캔들이다.** 02:02 UTC에 받은 240분봉의 첫 항목은 00:00 UTC에 시작한 캔들이다. 240분봉 시작 시각은 UTC 00·04·08·12·16·20시다. 일봉 경계는 UTC 00:00(KST 09:00)이다.
7. **캔들 종류마다 필드가 다르다.** 분봉에는 `unit`, 일봉에는 `prev_closing_price`, `change_price`, `change_rate`가 있다.
8. **호가는 기본 30단계다.** `orderbook_units`가 30개이고 `level: 0`이 붙는다.
9. **REST ticker에는 `market_state`, `delisting_date`가 없다.** 이 둘은 웹소켓 ticker에만 온다.
10. **받은 시점의 종목 경고 분포:** KRW 마켓 299개 중 유의(`warning=true`) 5개, 주의 플래그가 하나라도 참인 것 13개(겹침 있음). KRW 마켓에는 "warning만 참이고 caution은 모두 거짓"인 예가 없었다. 그 경우는 가짜 구현에서 만들어 쓴다([가짜 구현 명세](../../../docs/08-quality/fakes-spec.md)).
11. **`caution`의 키는 5개다:** `PRICE_FLUCTUATIONS`, `TRADING_VOLUME_SOARING`, `DEPOSIT_AMOUNT_SOARING`, `GLOBAL_PRICE_DIFFERENCES`, `CONCENTRATION_OF_SMALL_ACCOUNTS`.

## 쓰는 규칙

- 형식·파싱·경계 테스트에만 쓴다. 가격이나 등락으로 매매 판단이 맞는지 보는 테스트에 쓰지 않는다.
- 녹화 파일을 고치지 않는다. 다른 경우가 필요하면 테스트 안에서 복사본을 바꾸거나 가짜 구현이 만든다.
- 비밀과 개인 정보는 없다. 공개 시세 API를 키 없이 불렀고, IP가 드러날 수 있는 헤더는 남기지 않았다. 새 녹화를 넣을 때도 이 조건을 확인한다.
- 비공개(Exchange) API 응답은 녹화할 수 없다(클라우드 세션은 비공개 API를 부르지 않는다). 공식 문서의 응답 예시로 만든다.

## 문서 예시(`docs_examples/`)

비공개(Exchange) API의 응답은 녹화 대신 공식 문서의 응답 예시를 옮겨 둔다. 2026-11-05에 `https://docs.upbit.com/kr/reference/<문서>.md`(OpenAPI 정의와 예시)를 1초 간격으로 받았다. 업비트 API는 부르지 않았다.

| 파일 | 요청 |
|---|---|
| `get-balance.json` | GET /v1/accounts |
| `available-order-information.json` | GET /v1/orders/chance |
| `new-order.json` | POST /v1/orders |
| `order-test.json` | POST /v1/orders/test |
| `get-order.json` | GET /v1/order |
| `list-orders-by-ids.json` | GET /v1/orders/uuids |
| `list-open-orders.json` | GET /v1/orders/open |
| `list-closed-orders.json` | GET /v1/orders/closed |
| `cancel-order.json` | DELETE /v1/order |
| `batch-cancel-orders.json` | DELETE /v1/orders/open(앱은 쓰지 않음, D-069) |
| `list-api-keys.json` | GET /v1/api_keys |
| `list-orderbook-instruments.json` | GET /v1/orderbook/instruments(공개 API지만 녹화가 없어 문서 예시를 둔다) |
| `websocket-guide.json` | 웹소켓 안내: 주소 3개, 요청 예시, 오류 형식·`INVALID_AUTH` 예시, `{"status":"UP"}` |
| `websocket-ticker.json` | 공개 웹소켓 ticker(KRW-BTC, KRW-ETH 수신 예시) |
| `websocket-myorder.json` | 비공개 웹소켓 myOrder |
| `websocket-myasset.json` | 비공개 웹소켓 myAsset |
| `websocket-announcement.json` | 비공개 웹소켓 announcement(본문 포함 예시, 카테고리 8개) |
| `websocket-list-subscriptions.json` | LIST_SUBSCRIPTIONS(문서 이름은 `list-subscriptions`) |

- **형식:** `{source, retrieved_at, doc_updated_at, method, path, status, example_title, example}`. 문서에 있으면 `other_examples`, `request_examples`, `error_examples`, `replaced_with_placeholder`도 넣었다. 숫자 토큰은 원문 그대로다.
- **키 자리표시:** `list-api-keys.json`의 `access_key`는 `CANARY-PLACEHOLDER`로 바꿨다(`replaced_with_placeholder`에 기록). 테스트는 실행 중에 카나리아 값으로 채운다.
- **문서와 다른 점:** 주문 예시에는 `identifier`·`smp_type`·`time_in_force`가 없다(가짜가 붙인다). 시장가 매도 예시에는 `price` 키가 없다. 체결(`trades`)의 `created_at`에는 마이크로초가 있다.
- **웹소켓 파일(3b):** `method`·`path`·`status` 대신 `endpoint`(안내·구독 목록은 `endpoints`)와 `type`이 있고, 문서에 있으면 `error_names`, `rate_limits`, `market_states`, `deprecated_fields`, `states`, `categories`, `event_types`, `formats`도 넣었다. 웹소켓 숫자는 JSON 숫자라 토큰을 원문 그대로 두었다(`9.101e-05`, `1386929.37231066771348207123`). 안내 문서의 `Authorization: Bearer eyJhb...d8sTw`는 `auth_header_example`에 자리표시로 바꿔 두었다. 같은 내용의 수신 예시가 두 번 나오는 문서(myOrder, announcement trade)는 한 번만 넣었다.
- **웹소켓 문서끼리 어긋난 점:** 안내 문서의 공지 구독 예시는 `categories: ["trading", "wallet"]`인데 공지 문서의 값은 `trade`다(지원하지 않는 값은 `INVALID_PARAM`). 안내 문서의 오류 표는 6개이고 타입별 문서는 `TOO_MANY_REQUEST`를 더해 7개다. 구독 목록 문서의 두 번째 예시(myAsset·myOrder)는 소제목이 "Public WebSocket"이지만 비공개 예시다. 공지의 `uuid`는 숫자 문자열(`562593104`)이다.
- `tests/unit/fakes/test_upbit_docs_examples.py`가 형식, 출처, 키 자리표시, 문자열 숫자, 오류 이름 타입을 검사한다.

## 공개 시세 웹소켓 녹화(`ws_public_recording.json`)

2026-11-05 12:32 UTC에 Claude 클라우드 세션(3단계 3b)이 `wss://api.upbit.com/websocket/v1`에 키 없이 연결해 받은 프레임이다. 연결 3번, 연결 사이 1.5초, 연결마다 요청 메시지 1개만 보냈다(연결 한도 초당 5회, 메시지 초당 5회보다 낮다). `Origin` 헤더는 보내지 않았고 라이브러리 PING은 껐다. 프레임 원문(숫자 표기 포함)을 UTF-8로 풀어 그대로 저장했다.

| 세션 | 보낸 것 | 받은 것 |
|---|---|---|
| `ticker_snapshot_btc_eth` | ticker 구독(KRW-BTC, KRW-ETH) | 마켓마다 스냅숏 1개(`stream_type: SNAPSHOT`) |
| `error_no_codes` | `codes` 없는 ticker 구독 | `{"error":{"name":"NO_CODES",...}}` 뒤 서버가 close code 1000으로 끊음 |
| `ping_text_status_up` | 문자열 `PING` | `{"status":"UP"}` |

관찰한 사실:

1. 서버가 보내는 프레임은 모두 바이너리(UTF-8 JSON)다. ticker, 오류, `status` 모두 같다.
2. 요청 형식 오류 메시지를 보낸 뒤 서버가 바로 연결을 정상 종료(1000)했다. 문서에는 오류 뒤 연결을 끊는지가 없었다(업비트 API 연동 명세 2장).
3. ticker에는 `market_state`(`ACTIVE`), `delisting_date`(`null`)가 오고, 폐기 필드 `market_warning`·`is_trading_suspended`도 아직 온다. 앱은 폐기 필드를 읽지 않는다.
4. 숫자는 JSON 숫자이고 `108328000.00000000`처럼 뒤 0이 붙은 표기가 섞인다.
5. 응답 헤더에 `permessage-deflate`가 있다.
