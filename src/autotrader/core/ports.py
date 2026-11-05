"""core 포트: 업비트 시세(QuotationApi)와 거래(ExchangeApi) 인터페이스.

어댑터(adapters/upbit/)와 가짜(tests/fakes/)가 같은 메서드 이름을 쓴다.
ExchangeApi에는 일괄 취소가 없다(정지 때 앱 주문만 하나씩 취소). 자동 재시도도 없다.
근거: docs/06-architecture/system-architecture.md 6장.
"""

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Literal, Protocol

from autotrader.core.models import (
    ApiKeyInfo,
    Balance,
    Candle,
    MarketInfo,
    Orderbook,
    OrderChance,
    OrderRequest,
    OrderSnapshot,
    Ticker,
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
    """비공개 REST(키 필요). 자동 재시도 없음."""

    async def get_accounts(self) -> list[Balance]: ...

    async def get_order_chance(self, market: str) -> OrderChance: ...

    async def create_order(self, req: OrderRequest) -> OrderSnapshot: ...

    async def test_order(self, req: OrderRequest) -> OrderSnapshot: ...

    async def get_order(self, *, identifier: str) -> OrderSnapshot | None: ...

    async def get_orders(self, *, identifiers: Sequence[str]) -> list[OrderSnapshot]: ...

    async def list_open_orders(self, market: str | None = None) -> list[OrderSnapshot]: ...

    async def list_closed_orders(
        self, *, market: str | None, start: datetime, end: datetime
    ) -> list[OrderSnapshot]: ...

    async def cancel_order(self, *, identifier: str) -> OrderSnapshot: ...

    async def list_api_keys(self) -> list[ApiKeyInfo]: ...
