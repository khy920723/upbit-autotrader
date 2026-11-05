"""tests/fixtures/upbit/docs_examples/: 업비트 공식 문서의 응답 예시(fakes-spec 2.7절).

비공개(Exchange) API는 클라우드 세션에서 부를 수 없으므로, FakeUpbitServer는 공식 문서
(docs.upbit.com/kr/reference/<문서>.md의 OpenAPI 정의)의 응답 예시를 바탕으로 응답을 만든다.
파일마다 출처와 받은 날짜가 있고, 키 값은 자리표시(CANARY-PLACEHOLDER)로 바꿔 두었다.
가짜는 실행 중에 이 자리표시를 카나리아 키로 바꾼다.
"""

import json
import re
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
    assert {p.stem for p in DOCS_EXAMPLES.glob("*.json")} == set(EXPECTED)
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
