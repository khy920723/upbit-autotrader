"""tests/fixtures/upbit/docs_examples/: 업비트 공식 문서의 응답 예시(fakes-spec 2.7절).

비공개(Exchange) API는 클라우드 세션에서 부를 수 없으므로, FakeUpbitServer는 공식 문서
(docs.upbit.com/kr/reference/<문서>.md의 OpenAPI 정의)의 응답 예시를 바탕으로 응답을 만든다.
파일마다 출처와 받은 날짜가 있고, 키 값은 자리표시(CANARY-PLACEHOLDER)로 바꿔 두었다.
가짜는 실행 중에 이 자리표시를 카나리아 키로 바꾼다.

웹소켓 예시(`websocket-*.json`, 3b)는 FakeUpbitWs(tests/fakes/upbit_ws.py)의 바탕이다. REST 파일과
달리 method·path·status 대신 `endpoint`(또는 `endpoints`)와 `type`이 있다. 웹소켓 숫자는 JSON
숫자(지수 표기 포함)라서 숫자 토큰을 원문 그대로 저장했다(문서 블록과 토큰 단위로 같다).
"""

import json
import re
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

DOCS_EXAMPLES = Path(__file__).resolve().parents[2] / "fixtures" / "upbit" / "docs_examples"
PLACEHOLDER = "CANARY-PLACEHOLDER"

# 문서 이름 → (메서드, 경로, 성공 상태)
EXPECTED = {
    "get-balance": ("GET", "/v1/accounts", 200),
    "available-order-information": ("GET", "/v1/orders/chance", 200),
    "new-order": ("POST", "/v1/orders", 201),
    "order-test": ("POST", "/v1/orders/test", 201),
    "get-order": ("GET", "/v1/order", 200),
    "list-orders-by-ids": ("GET", "/v1/orders/uuids", 200),
    "list-open-orders": ("GET", "/v1/orders/open", 200),
    "list-closed-orders": ("GET", "/v1/orders/closed", 200),
    "cancel-order": ("DELETE", "/v1/order", 200),
    "list-api-keys": ("GET", "/v1/api_keys", 200),
    "batch-cancel-orders": ("DELETE", "/v1/orders/open", 200),
    "list-orderbook-instruments": ("GET", "/v1/orderbook/instruments", 200),
}
ORDER_DOCS = (
    "new-order",
    "order-test",
    "get-order",
    "list-orders-by-ids",
    "list-open-orders",
    "list-closed-orders",
    "cancel-order",
)
ORDER_STRING_FIELDS = (
    "price",
    "volume",
    "remaining_volume",
    "executed_volume",
    "reserved_fee",
    "remaining_fee",
    "paid_fee",
    "locked",
    "prevented_volume",
    "prevented_locked",
)
KEY_FIELDS = {"access_key", "secret_key"}
# 업비트 Access Key 모양(영문·숫자 40자 이상 연속). 문서 예시의 키가 남아 있으면 걸린다.
KEY_SHAPED = re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9]{40,}(?![A-Za-z0-9])")
JWT_SHAPED = re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")

# 웹소켓 문서 예시: 파일 이름 → 공식 문서 이름(구독 목록 조회만 이름이 다르다)
WS_DOCS = {
    "websocket-guide": "websocket-guide",
    "websocket-ticker": "websocket-ticker",
    "websocket-myorder": "websocket-myorder",
    "websocket-myasset": "websocket-myasset",
    "websocket-announcement": "websocket-announcement",
    "websocket-list-subscriptions": "list-subscriptions",
}
WS_TYPE_DOCS = {
    "websocket-ticker": ("ticker", "wss://api.upbit.com/websocket/v1"),
    "websocket-myorder": ("myOrder", "wss://api.upbit.com/websocket/v1/private"),
    "websocket-myasset": ("myAsset", "wss://api.upbit.com/websocket/v1/private"),
    "websocket-announcement": ("announcement", "wss://api.upbit.com/websocket/v1/private"),
}
WS_PUBLIC = "wss://api.upbit.com/websocket/v1"
WS_PRIVATE = "wss://api.upbit.com/websocket/v1/private"
WS_ERROR_NAMES = [
    "INVALID_AUTH",
    "WRONG_FORMAT",
    "NO_TICKET",
    "NO_TYPE",
    "NO_CODES",
    "INVALID_PARAM",
    "TOO_MANY_REQUEST",
]
ISO_UTC_MS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
KST_SECONDS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+09:00$")


def load(name: str) -> dict[str, Any]:
    return json.loads((DOCS_EXAMPLES / f"{name}.json").read_text(encoding="utf-8"))


def walk(value: Any, key: str | None = None):
    """(키, 값) 쌍을 모두 돈다."""
    if isinstance(value, dict):
        for k, v in value.items():
            yield k, v
            yield from walk(v, k)
    elif isinstance(value, list):
        for item in value:
            yield from walk(item, key)


def orders_in(doc: dict[str, Any]) -> list[dict[str, Any]]:
    examples = [doc["example"], *doc.get("other_examples", {}).values()]
    found: list[dict[str, Any]] = []
    for example in examples:
        found.extend(example if isinstance(example, list) else [example])
    return found


def test_exactly_the_expected_files_exist():
    assert {p.stem for p in DOCS_EXAMPLES.glob("*.json")} == set(EXPECTED) | set(WS_DOCS)
    assert [p.name for p in DOCS_EXAMPLES.iterdir() if p.suffix != ".json"] == []


@pytest.mark.parametrize("name", EXPECTED)
def test_each_file_records_its_source_and_date(name):
    doc = load(name)
    method, path, status = EXPECTED[name]

    assert doc["source"] == f"https://docs.upbit.com/kr/reference/{name}.md"
    assert doc["retrieved_at"] == "2026-11-05"
    assert (doc["method"], doc["path"], doc["status"]) == (method, path, status)
    assert doc["example"]


@pytest.mark.parametrize("name", EXPECTED)
def test_key_values_are_placeholders(name):
    text = (DOCS_EXAMPLES / f"{name}.json").read_text(encoding="utf-8")
    doc = json.loads(text)

    for key, value in walk(doc):
        if key in KEY_FIELDS:
            assert value == PLACEHOLDER, key
    assert KEY_SHAPED.findall(text) == []


def test_api_keys_example_uses_the_placeholder():
    doc = load("list-api-keys")

    assert [item["access_key"] for item in doc["example"]] == [PLACEHOLDER]
    assert doc["example"][0]["expire_at"].endswith("+09:00")


@pytest.mark.parametrize("name", ORDER_DOCS)
def test_order_numbers_are_strings(name):
    # 거래(Exchange) API는 숫자를 문자열로 준다(fakes-spec 2.2절).
    for order in orders_in(load(name)):
        for field in ORDER_STRING_FIELDS:
            if field in order:
                assert isinstance(order[field], str), (name, field)
        assert type(order["trades_count"]) is int
        for trade in order.get("trades", []):
            for field in ("price", "volume", "funds"):
                assert isinstance(trade[field], str), (name, field)


def test_balance_and_chance_numbers_are_strings():
    for account in load("get-balance")["example"]:
        for field in ("balance", "locked", "avg_buy_price"):
            assert isinstance(account[field], str)
    chance = load("available-order-information")["example"]
    for field in ("bid_fee", "ask_fee", "maker_bid_fee", "maker_ask_fee"):
        assert isinstance(chance[field], str)
    assert isinstance(chance["market"]["max_total"], str)
    assert isinstance(chance["market"]["bid"]["min_total"], str)


def test_exchange_error_names_are_strings_and_quotation_error_names_are_integers():
    # REST API 안내: 시세 API는 정수 name, 거래 API는 문자열 name.
    for name in EXPECTED:
        doc = load(name)
        for error in doc.get("error_examples", []):
            error_name = error["body"]["error"]["name"]
            if name == "list-orderbook-instruments":
                assert type(error_name) is int
                assert error_name == error["status"]
            else:
                assert isinstance(error_name, str)


def test_documented_order_errors_include_the_names_the_fake_rejects_with():
    names = {
        error["body"]["error"]["name"]: error["status"]
        for doc in ("new-order", "cancel-order", "get-order")
        for error in load(doc).get("error_examples", [])
    }

    assert names["insufficient_funds_bid"] == 400
    assert names["market_offline"] == 403
    assert names["order_not_found"] == 404
    assert names["QUERY_PARAMETER_NOT_SUPPORTED"] == 400


# ── 웹소켓 예시(3b) ──────────────────────────────────────


def raw_numbers(text: str) -> Any:
    """숫자 토큰을 ("num", 원문)으로 읽는다(`9.101e-05`처럼 표기를 그대로 비교할 때)."""
    return json.loads(text, parse_float=lambda s: ("num", s), parse_int=lambda s: ("num", s))


def ws_text(name: str) -> str:
    return (DOCS_EXAMPLES / f"{name}.json").read_text(encoding="utf-8")


def ws_raw(name: str) -> dict[str, Any]:
    return raw_numbers(ws_text(name))


def is_double(value: Any) -> bool:
    return isinstance(value, tuple) and value[0] == "num"


def is_long(value: Any) -> bool:
    return is_double(value) and re.fullmatch(r"[0-9]+", value[1]) is not None


@pytest.mark.parametrize("name", WS_DOCS)
def test_ws_file_records_its_source_and_date(name):
    doc = load(name)

    assert doc["source"] == f"https://docs.upbit.com/kr/reference/{WS_DOCS[name]}.md"
    assert doc["retrieved_at"] == "2026-11-05"
    assert ISO_UTC_MS.match(doc["doc_updated_at"]), doc["doc_updated_at"]
    assert doc["example_title"]
    assert doc["example"]
    assert "method" not in doc  # REST 전용 필드
    assert "status" not in doc


@pytest.mark.parametrize("name", WS_TYPE_DOCS)
def test_ws_type_files_name_their_endpoint_and_type(name):
    doc = load(name)
    data_type, endpoint = WS_TYPE_DOCS[name]

    assert (doc["type"], doc["endpoint"]) == (data_type, endpoint)
    assert doc["example"]["type"] == data_type


@pytest.mark.parametrize("name", WS_DOCS)
def test_ws_files_hold_no_keys_or_tokens(name):
    text = ws_text(name)

    assert KEY_SHAPED.findall(text) == []
    assert JWT_SHAPED.findall(text) == []
    for key, value in walk(json.loads(text)):
        if key in KEY_FIELDS:
            assert value == PLACEHOLDER, key


def test_ws_guide_auth_header_example_uses_the_placeholder():
    # 문서 원문은 `Authorization: Bearer eyJhb...d8sTw`(줄인 토큰)다.
    doc = load("websocket-guide")

    assert doc["auth_header_example"] == {
        "name": "Authorization",
        "value": f"Bearer {PLACEHOLDER}",
    }
    assert doc["replaced_with_placeholder"] == ["$.auth_header_example.value"]


def test_ws_guide_lists_the_endpoints_formats_and_status_message():
    doc = load("websocket-guide")

    # 앱은 public·private만 쓴다. info(지표)는 쓰지 않는다(FakeUpbitWs는 url 위반으로 본다).
    assert doc["endpoints"] == {
        "public": WS_PUBLIC,
        "private": WS_PRIVATE,
        "info": "wss://api.upbit.com/websocket/v1/info",
    }
    assert doc["formats"] == ["DEFAULT", "SIMPLE", "JSON_LIST", "SIMPLE_LIST"]
    assert doc["example"] == {"status": "UP"}


def test_ws_error_names_guide_has_six_and_type_docs_add_too_many_request():
    # fakes-spec 2.8절: 안내 문서 표는 6개, 타입별 문서는 TOO_MANY_REQUEST를 더해 7개다.
    assert load("websocket-guide")["error_names"] == WS_ERROR_NAMES[:6]
    for name in (*WS_TYPE_DOCS, "websocket-list-subscriptions"):
        assert load(name)["error_names"] == WS_ERROR_NAMES, name


def test_ws_error_examples_have_the_documented_shape():
    for name in WS_DOCS:
        for example in load(name)["error_examples"]:
            body = example["body"]
            assert list(body) == ["error"], name
            assert set(body["error"]) == {"name", "message"}, name
            assert isinstance(body["error"]["name"], str), name
    auth = load("websocket-guide")["error_examples"][1]
    assert auth["body"]["error"] == {
        "name": "INVALID_AUTH",
        "message": "인증 정보가 올바르지 않습니다.",
    }


def test_ws_rate_limits_are_five_per_second_and_one_hundred_per_minute():
    expected_policies = {
        "websocket-connect": "초당 최대 5회",
        "websocket-message": "초당 최대 5회, 분당 100회",
    }
    connect_units = {
        "websocket-ticker": "IP",
        "websocket-myorder": "포켓",
        "websocket-myasset": "포켓",
        "websocket-announcement": "포켓",
        "websocket-list-subscriptions": "Public - IP, Private - 포켓",
    }
    for name, unit in connect_units.items():
        limits = {row["group"]: row for row in load(name)["rate_limits"]}
        assert {g: row["policy"] for g, row in limits.items()} == expected_policies, name
        assert limits["websocket-connect"]["unit"] == unit, name
        assert limits["websocket-message"]["unit"] == "커넥션", name


def test_ws_ticker_numbers_are_json_numbers_with_exponent_notation():
    doc = ws_raw("websocket-ticker")
    btc = doc["example"]

    # 웹소켓 숫자는 JSON 숫자(Double)이고 지수 표기도 온다(fakes-spec 2.2절).
    assert btc["trade_volume"] == ("num", "9.101e-05")
    assert Decimal(btc["trade_volume"][1]) == Decimal("0.00009101")
    for field in (
        "opening_price",
        "high_price",
        "low_price",
        "trade_price",
        "prev_closing_price",
        "acc_trade_price",
        "change_price",
        "signed_change_price",
        "change_rate",
        "signed_change_rate",
        "trade_volume",
        "acc_trade_volume",
        "acc_trade_volume_24h",
        "acc_trade_price_24h",
        "acc_ask_volume",
        "acc_bid_volume",
        "highest_52_week_price",
        "lowest_52_week_price",
    ):
        assert is_double(btc[field]), field
    for field in ("trade_timestamp", "timestamp"):
        assert is_long(btc[field]), field
    for field in ("trade_date", "trade_time", "highest_52_week_date", "change", "ask_bid"):
        assert isinstance(btc[field], str), field


def test_ws_ticker_example_carries_market_state_and_deprecated_fields():
    doc = load("websocket-ticker")
    examples = [doc["example"], *doc["other_examples"].values()]

    assert [e["code"] for e in examples] == ["KRW-BTC", "KRW-ETH"]  # `market`이 아니라 `code`
    assert doc["market_states"] == ["PREVIEW", "ACTIVE", "DELISTED"]
    assert doc["deprecated_fields"] == ["is_trading_suspended", "market_warning"]
    for example in examples:
        assert example["market_state"] == "ACTIVE"
        assert "delisting_date" in example
        assert example["delisting_date"] is None
        assert example["stream_type"] == "SNAPSHOT"
        assert set(doc["deprecated_fields"]) <= set(example)  # 와도 앱은 읽지 않는다
    assert doc["request_examples"]["default"] == [
        {"ticket": "ticker-monitor"},
        {"type": "ticker", "codes": ["KRW-BTC", "KRW-ETH"]},
        {"format": "DEFAULT"},
    ]


def test_ws_myorder_example_uses_documented_names_and_numbers():
    doc = load("websocket-myorder")
    raw = ws_raw("websocket-myorder")["example"]
    example = doc["example"]

    assert doc["states"] == ["wait", "watch", "trade", "done", "cancel", "prevented"]
    assert example["state"] in doc["states"]
    # REST 주문 객체와 이름이 다르다: code·ask_bid(대문자)·order_type
    assert example["code"] == "KRW-BTC"
    assert example["ask_bid"] == "BID"
    assert example["order_type"] == "limit"
    assert {"market", "side", "ord_type"}.isdisjoint(example)
    assert example["time_in_force"] is None
    assert example["is_maker"] is True
    assert example["smp_type"] == "cancel_maker"
    for field in (
        "price",
        "avg_price",
        "volume",
        "remaining_volume",
        "executed_volume",
        "reserved_fee",
        "remaining_fee",
        "paid_fee",
        "locked",
        "executed_funds",
        "trade_fee",
        "prevented_volume",
        "prevented_locked",
    ):
        assert is_double(raw[field]), field
    for field in ("trades_count", "trade_timestamp", "order_timestamp", "timestamp"):
        assert is_long(raw[field]), field
    assert set(doc["request_examples"]) == {"all", "all_empty_codes", "krw_btc"}
    assert doc["request_examples"]["all_empty_codes"][1] == {"type": "myOrder", "codes": []}


def test_ws_myasset_balance_keeps_more_digits_than_a_float():
    raw = ws_raw("websocket-myasset")["example"]
    (asset,) = raw["assets"]

    assert asset["currency"] == "KRW"
    assert asset["balance"] == ("num", "1386929.37231066771348207123")
    assert asset["locked"] == ("num", "10329.670127489597585685")
    # float로 읽으면 자릿수가 사라진다. 앱은 Decimal로 읽어야 한다.
    assert Decimal(str(float(asset["balance"][1]))) != Decimal(asset["balance"][1])
    assert set(raw) == {
        "type",
        "asset_uuid",
        "assets",
        "asset_timestamp",
        "timestamp",
        "stream_type",
    }
    assert raw["stream_type"] == "REALTIME"
    assert load("websocket-myasset")["request_examples"]["default"][1] == {"type": "myAsset"}


def test_ws_announcement_example_fields_and_categories():
    doc = load("websocket-announcement")
    example = doc["example"]
    with_body = doc["other_examples"]["with_body"]

    assert doc["categories"] == [
        "notice",
        "trade",
        "wallet",
        "maintenance",
        "digital_asset",
        "nft",
        "service",
        "event",
    ]
    assert doc["event_types"] == ["CREATED", "UPDATED"]
    assert set(example) == {
        "type",
        "event_type",
        "uuid",
        "title",
        "category",
        "url",
        "first_listed_at",
        "listed_at",
        "timestamp",
        "stream_type",
    }
    assert set(with_body) == set(example) | {"body"}
    assert example["category"] in doc["categories"]
    assert example["event_type"] in doc["event_types"]
    assert example["uuid"].isdigit()  # 이름은 uuid지만 숫자 문자열이다
    assert example["uuid"] in example["url"]
    assert KST_SECONDS.match(example["first_listed_at"])
    assert KST_SECONDS.match(example["listed_at"])
    assert example["stream_type"] == "REALTIME"
    assert doc["request_examples"]["trade_only"][1] == {
        "type": "announcement",
        "categories": ["trade"],
        "include_body": False,
    }


def test_ws_guide_announcement_example_uses_a_category_the_announcement_doc_lacks():
    # 문서끼리 어긋난 점: 안내 문서 예시는 "trading"을 쓰지만 공지 문서의 카테고리 값은 "trade"다.
    # 공지 문서는 지원하지 않는 값이면 INVALID_PARAM이라고 한다. 앱은 공지 문서 값만 쓴다.
    guide = load("websocket-guide")["request_examples"]["announcement_categories_body"]
    categories = load("websocket-announcement")["categories"]

    assert guide[1]["categories"] == ["trading", "wallet"]
    assert "trading" not in categories


def test_ws_request_examples_follow_the_documented_message_shape():
    # 요청은 JSON 배열: 첫 요소 Ticket, 다음 Data Type(또는 method) 1개 이상, 마지막에 선택 Format.
    for name in WS_DOCS:
        for key, request in load(name).get("request_examples", {}).items():
            assert isinstance(request, list), (name, key)
            assert list(request[0]) == ["ticket"], (name, key)
            assert isinstance(request[0]["ticket"], str), (name, key)
            assert request[0]["ticket"], (name, key)
            body = request[1:]
            if body and list(body[-1]) == ["format"]:
                body = body[:-1]
            assert body, (name, key)
            for item in body:
                assert "type" in item or item == {"method": "LIST_SUBSCRIPTIONS"}, (name, key)


def test_ws_list_subscriptions_examples():
    doc = load("websocket-list-subscriptions")

    assert doc["endpoints"] == [WS_PUBLIC, WS_PRIVATE]
    assert doc["request_examples"]["default"][1] == {"method": "LIST_SUBSCRIPTIONS"}
    public, private = doc["example"], doc["other_examples"]["private"]
    for result in (public, private):
        assert list(result) == ["method", "result", "ticket"]
        assert result["method"] == "LIST_SUBSCRIPTIONS"
    assert public["result"][0] == {"type": "ticker", "codes": ["KRW-BTC", "KRW-ETH"]}
    assert private["result"] == [
        {"type": "myAsset"},
        {"type": "myOrder", "codes": ["KRW-BTC", "KRW-ETH"]},
    ]
