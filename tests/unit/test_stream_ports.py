"""core 포트(ports.py): 업비트 웹소켓 스트림 인터페이스(시스템 구성도 6장, 3b).

- PublicStream.ticker(markets)
  -> AsyncIterator[StreamOpened | TickerEvent]
- PrivateStream.events()
  -> AsyncIterator[StreamOpened | MyOrderEvent | MyAssetEvent | AnnouncementEvent]

둘 다 async def가 아닌 일반 메서드다. 구현은 async generator 함수라 부르면
바로 이터레이터를 준다. 연결 하나 = 이터레이터 하나다. 끊기면
StreamClosed·StreamConnectFailed·StreamError 계열 오류로 끝나고 스스로 다시
연결하지 않는다(재연결은 StreamSupervisor 몫). 연결마다 구독 요청을 보낸
직후 StreamOpened를 가장 먼저 낸다.
"""

import collections.abc
import inspect
import typing

import pytest

from autotrader.core import models, ports

STREAM_PROTOCOLS = [
    pytest.param(ports.PublicStream, {"ticker"}, id="PublicStream"),
    pytest.param(ports.PrivateStream, {"events"}, id="PrivateStream"),
]


def yielded_types(func) -> set[type]:
    """`-> AsyncIterator[A | B]` 표기에서 {A, B}."""
    hint = typing.get_type_hints(func)["return"]
    assert typing.get_origin(hint) is collections.abc.AsyncIterator, hint
    (item,) = typing.get_args(hint)
    item = getattr(item, "__value__", item)
    return set(typing.get_args(item)) or {item}


@pytest.mark.parametrize(("protocol", "methods"), STREAM_PROTOCOLS)
def test_stream_ports_are_protocols(protocol, methods):
    assert typing.is_protocol(protocol)


@pytest.mark.parametrize(("protocol", "methods"), STREAM_PROTOCOLS)
def test_stream_ports_have_exactly_the_architecture_methods(protocol, methods):
    # 메서드가 늘거나 빠지면 시스템 구성도 6장과 가짜(tests/fakes/upbit_ws.py)를 함께 고친다.
    assert typing.get_protocol_members(protocol) == methods


@pytest.mark.parametrize(("protocol", "methods"), STREAM_PROTOCOLS)
def test_stream_methods_return_iterators_instead_of_coroutines(protocol, methods):
    # `async for event in stream.ticker(...)`로 바로 쓴다. await가 먼저 필요하면 안 된다.
    for name in methods:
        func = getattr(protocol, name)
        assert not inspect.iscoroutinefunction(func), name
        assert typing.get_origin(typing.get_type_hints(func)["return"]) is (
            collections.abc.AsyncIterator
        )


def test_public_ticker_signature():
    params = inspect.signature(ports.PublicStream.ticker).parameters

    assert list(params) == ["self", "markets"]
    assert params["markets"].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert params["markets"].default is inspect.Parameter.empty


def test_public_ticker_takes_a_sequence_of_markets():
    hint = typing.get_type_hints(ports.PublicStream.ticker)["markets"]

    assert typing.get_origin(hint) is collections.abc.Sequence
    assert typing.get_args(hint) == (str,)


def test_private_events_takes_no_arguments():
    # 연결 하나에서 myOrder·myAsset·announcement를 함께 구독한다(공식 문서: 비공개 연결은 적게).
    assert list(inspect.signature(ports.PrivateStream.events).parameters) == ["self"]


def test_public_ticker_yields_opened_marker_and_tickers():
    assert yielded_types(ports.PublicStream.ticker) == {models.StreamOpened, models.TickerEvent}


def test_private_events_yields_opened_marker_and_private_events():
    assert yielded_types(ports.PrivateStream.events) == {
        models.StreamOpened,
        models.MyOrderEvent,
        models.MyAssetEvent,
        models.AnnouncementEvent,
    }


def test_existing_rest_ports_are_unchanged():
    # 웹소켓 포트를 더하면서 REST 포트에 메서드가 섞이지 않는다.
    assert "ticker" not in typing.get_protocol_members(ports.QuotationApi)
    assert "events" not in typing.get_protocol_members(ports.ExchangeApi)
