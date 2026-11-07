"""core 포트: 업비트 시세(QuotationApi)·거래(ExchangeApi) REST와 웹소켓 스트림 인터페이스.

어댑터(adapters/upbit/)와 가짜(tests/fakes/)가 같은 메서드 이름을 쓴다.
ExchangeApi에는 일괄 취소가 없다(정지 때 앱 주문만 하나씩 취소). 자동 재시도도 없다.
웹소켓 스트림(PublicStream·PrivateStream)은 스스로 다시 연결하지 않는다(StreamSupervisor 몫).
근거: docs/06-architecture/system-architecture.md 6장.
"""

from collections.abc import AsyncIterator, Sequence
from datetime import datetime
from decimal import Decimal
from typing import Literal, Protocol

from autotrader.core.models import (
    AnnouncementEvent,
    ApiKeyInfo,
    Balance,
    Candle,
    MarketInfo,
    MyAssetEvent,
    MyOrderEvent,
    Orderbook,
    OrderChance,
    OrderLookup,
    OrderRequest,
    OrderSnapshot,
    StreamOpened,
    Ticker,
    TickerEvent,
)

CandleUnit = Literal["m1", "m3", "m5", "m10", "m15", "m30", "m60", "m240", "d1"]


class QuotationApi(Protocol):
    """공개 REST(키 없음, IP 단위 한도)."""

    async def list_markets(self) -> list[MarketInfo]: ...

    async def get_candles(
        self, market: str, unit: CandleUnit, *, count: int = 200, to: datetime | None = None
    ) -> list[Candle]: ...

    async def get_tickers(self, markets: Sequence[str]) -> list[Ticker]: ...

    async def get_orderbooks(self, markets: Sequence[str]) -> list[Orderbook]: ...

    async def get_tick_sizes(self, markets: Sequence[str]) -> dict[str, Decimal]: ...

    async def server_time(self) -> datetime: ...


class ExchangeApi(Protocol):
    """비공개 REST(키 필요). 자동 재시도 없음.

    목록 조회(get_orders·list_open_orders·list_closed_orders)의 404는 이름과 상관없이 오류다
    ("없음"·빈 목록이 아니다). 이름 없는 404를 "없음"으로 보는 D-094 B는 개별 조회에만 쓴다.
    """

    async def get_accounts(self) -> list[Balance]: ...

    async def get_order_chance(self, market: str) -> OrderChance: ...

    async def create_order(self, req: OrderRequest) -> OrderSnapshot: ...

    async def test_order(self, req: OrderRequest) -> OrderSnapshot: ...

    async def get_order(self, *, identifier: str) -> OrderSnapshot | None:
        """identifier로 개별 조회. 두 "없음"(order_not_found·이름 없는 404)을 합쳐 None이다.

        UNKNOWN 확인·재조정에는 lookup_order를 쓴다(D-094 B, 이름 없는 404 경고).
        """
        ...

    async def lookup_order(self, *, identifier: str) -> OrderLookup:
        """get_order와 같은 개별 조회. 두 "없음"(order_not_found·이름 없는 404)을 구별한다.

        D-094 B. get_order는 이 결과의 snapshot이다(두 "없음" 모두 None).
        """
        ...

    async def get_orders(self, *, identifiers: Sequence[str]) -> list[OrderSnapshot]: ...

    async def list_open_orders(self, market: str | None = None) -> list[OrderSnapshot]: ...

    async def list_closed_orders(
        self, *, market: str | None, start: datetime, end: datetime
    ) -> list[OrderSnapshot]: ...

    async def cancel_order(self, *, identifier: str) -> OrderSnapshot: ...

    async def list_api_keys(self) -> list[ApiKeyInfo]: ...


PublicStreamItem = StreamOpened | TickerEvent
PrivateStreamItem = StreamOpened | MyOrderEvent | MyAssetEvent | AnnouncementEvent


class PublicStream(Protocol):
    """공개 시세 웹소켓(키 없음).

    연결 하나 = 이터레이터 하나. 구현은 async generator 함수라 부르면 바로 이터레이터를 준다.
    구독 요청을 보낸 직후 StreamOpened를 가장 먼저 낸다. 끊기면 StreamClosed·StreamConnectFailed·
    StreamError 계열 오류로 끝나고 스스로 다시 연결하지 않는다.

    어댑터 계약(StreamSupervisor가 기대한다):
    - 이터레이터는 한 태스크에서만 소비된다. 첫 anext부터 aclose까지 같은 태스크다(감시가 연결마다
      만든 태스크). 그래서 yield를 넘어 TaskGroup·asyncio.timeout·contextvars를 써도 된다.
      감시는 앞 항목을 다 처리한 뒤에만 다음 anext를 부른다.
    - 끝날 때는 core 오류 하나로 끝난다(NetworkError·StreamError 계열. ExceptionGroup이나
      라이브러리 예외로 감싸지 않는다). 그 밖의 예외는 버그로 보고 감시가 run() 밖으로 올린다.
    - 닫기(aclose·취소)에서 난 오류도 core 오류로 바꾼다. core 밖 예외는 원래 결과를 덮지 않고
      기록만 된다. 두 번째 취소가 오면 닫기를 서둘러 끝낸다(예외를 삼키고 버티지 않는다).
    - PING은 연결이 가진 별도 태스크가 Clock으로 보낸다. 그 태스크는 연결을 닫을 때(finally)
      정리한다. 그 태스크가 실패하면 연결을 끊고 이터레이터를 core 오류로 끝낸다.
    - PONG 상한(반쯤 열린 연결, R22-01): PING을 보낸 시각부터 pong_timeout(Clock) 안에 그 PING의
      PONG이 오지 않으면 연결을 닫고 StreamClosed(reason "pong_timeout")로 끝낸다. 감시는 이것을
      다른 끊김처럼 다시 연다. 비공개 스트림은 무수신 감시가 없어 이것이 끊김을 알아채는 길이다.
    - StreamOpened까지 걸리는 시간에 상한(open_timeout)을 둔다. 감시는 StreamOpened 전에는
      무수신을 재지 않는다.
    """

    def ticker(self, markets: Sequence[str]) -> AsyncIterator[PublicStreamItem]: ...


class PrivateStream(Protocol):
    """비공개 웹소켓(연결마다 새 JWT). 연결 하나에서 myOrder·myAsset·announcement를 함께 구독한다.

    이터레이터 규칙과 어댑터 계약은 PublicStream과 같다(데이터가 몇 시간 없을 수 있어 감시는
    무수신으로 끊지 않는다).
    """

    def events(self) -> AsyncIterator[PrivateStreamItem]: ...
