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
2. **`Remaining-Req`의 그룹 이름이 문서와 다르다.** 캔들 응답은 `group=candles`인데 [요청 수 제한 문서](https://docs.upbit.com/kr/reference/rate-limits)의 표는 `candle`이다. 폐기된 `min` 필드(`min=600`)도 아직 온다. 그룹 이름은 표로 하드코딩하지 말고 응답 값을 그대로 쓰고, `sec`만 읽는다.
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
