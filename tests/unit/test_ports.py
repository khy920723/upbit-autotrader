"""core 포트(ports.py): 업비트 시세·거래 인터페이스(시스템 구성도 6장).

어댑터(adapters/upbit/)와 가짜(tests/fakes/)가 같은 이름을 쓰도록 메서드 목록을 고정한다.
"""

import inspect
import typing

import pytest

from autotrader.core import ports

QUOTATION_METHODS = {
    "list_markets",
    "get_candles",
    "get_tickers",
    "get_orderbooks",
    "get_tick_sizes",
    "server_time",
}

EXCHANGE_METHODS = {
    "get_accounts",
    "get_order_chance",
    "create_order",
    "test_order",
    "get_order",
    "get_orders",
    "list_open_orders",
    "list_closed_orders",
    "cancel_order",
    "list_api_keys",
}

PROTOCOLS = [
    pytest.param(ports.QuotationApi, QUOTATION_METHODS, id="QuotationApi"),
    pytest.param(ports.ExchangeApi, EXCHANGE_METHODS, id="ExchangeApi"),
]


def keyword_only(func) -> set[str]:
    return {
        name
        for name, param in inspect.signature(func).parameters.items()
        if param.kind is inspect.Parameter.KEYWORD_ONLY
    }


@pytest.mark.parametrize(("protocol", "methods"), PROTOCOLS)
def test_ports_are_protocols(protocol, methods):
    assert typing.is_protocol(protocol)


@pytest.mark.parametrize(("protocol", "methods"), PROTOCOLS)
def test_ports_have_exactly_the_architecture_methods(protocol, methods):
    # 메서드가 늘거나 빠지면 시스템 구성도 6장과 가짜 구현 명세를 함께 고친다.
    assert typing.get_protocol_members(protocol) == methods


@pytest.mark.parametrize(("protocol", "methods"), PROTOCOLS)
def test_every_port_method_is_async(protocol, methods):
    for name in methods:
        assert inspect.iscoroutinefunction(getattr(protocol, name)), name


def test_exchange_api_has_no_bulk_cancel():
    # 정지 때 앱 주문만 하나씩 취소한다. 일괄 취소 API(DELETE /v1/orders/open)는 쓰지 않는다.
    members = typing.get_protocol_members(ports.ExchangeApi)

    assert not {name for name in members if "cancel" in name} - {"cancel_order"}


# ── 인자 모양(시스템 구성도 6장) ─────────────────────────


def test_get_candles_signature():
    params = inspect.signature(ports.QuotationApi.get_candles).parameters

    assert list(params)[:3] == ["self", "market", "unit"]
    assert keyword_only(ports.QuotationApi.get_candles) == {"count", "to"}
    assert params["count"].default == 200  # 요청당 최대 200개
    assert params["to"].default is None


@pytest.mark.parametrize("name", ["get_order", "cancel_order"])
def test_order_lookup_and_cancel_take_identifier_by_keyword(name):
    # uuid와 identifier를 헷갈리지 않도록 이름으로만 넘긴다.
    func = getattr(ports.ExchangeApi, name)

    assert keyword_only(func) == {"identifier"}
    assert list(inspect.signature(func).parameters) == ["self", "identifier"]


def test_get_orders_takes_identifiers_by_keyword():
    assert keyword_only(ports.ExchangeApi.get_orders) == {"identifiers"}


def test_list_closed_orders_takes_a_time_range_by_keyword():
    assert keyword_only(ports.ExchangeApi.list_closed_orders) == {"market", "start", "end"}


def test_list_open_orders_market_is_optional():
    params = inspect.signature(ports.ExchangeApi.list_open_orders).parameters

    assert params["market"].default is None


@pytest.mark.parametrize("name", ["create_order", "test_order"])
def test_order_submission_takes_one_request(name):
    # 주문 내용은 OrderRequest 하나로만 넘긴다(필드를 따로 받는 길을 만들지 않는다).
    params = list(inspect.signature(getattr(ports.ExchangeApi, name)).parameters.values())

    assert len(params) == 2
    assert params[1].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD


# ── CandleUnit ────────────────────────────────────────────


def test_candle_units():
    # `CandleUnit = Literal[...]`와 `type CandleUnit = Literal[...]`를 모두 받는다.
    alias = getattr(ports.CandleUnit, "__value__", ports.CandleUnit)
    units = typing.get_args(alias)

    assert len(units) == len(set(units))
    assert set(units) == {"m1", "m3", "m5", "m10", "m15", "m30", "m60", "m240", "d1"}
