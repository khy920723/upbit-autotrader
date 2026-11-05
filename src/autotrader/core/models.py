"""core 값 객체: 시세, 주문, 계정 모델.

모두 frozen·slots dataclass이고 금액·수량·가격은 Decimal이다(INV-14, float 금지).
응답에 없는 선택 필드는 None(모름)으로 둔다. 비밀(키)은 repr/str에 나오지 않는다(INV-07).
근거: docs/06-architecture/system-architecture.md 6장, docs/08-quality/fakes-spec.md 2.2절.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Literal


@dataclass(frozen=True, slots=True)
class MarketInfo:
    market: str
    korean_name: str
    english_name: str
    warning: bool
    caution: Mapping[str, bool]

    @property
    def is_warned(self) -> bool:
        """유의 종목이거나 주의 항목이 하나라도 참이면 신규 매수를 막는다(처음 보는 키 포함)."""
        return self.warning or any(self.caution.values())


@dataclass(frozen=True, slots=True)
class Candle:
    market: str
    unit: str
    start_utc: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    value: Decimal


@dataclass(frozen=True, slots=True)
class Ticker:
    market: str
    trade_price: Decimal
    change_rate: Decimal
    acc_trade_price_24h: Decimal
    acc_trade_volume_24h: Decimal
    timestamp_ms: int


@dataclass(frozen=True, slots=True)
class OrderbookUnit:
    ask_price: Decimal
    bid_price: Decimal
    ask_size: Decimal
    bid_size: Decimal


@dataclass(frozen=True, slots=True)
class Orderbook:
    market: str
    units: tuple[OrderbookUnit, ...]
    timestamp_ms: int


@dataclass(frozen=True, slots=True)
class OrderChance:
    market: str
    bid_fee: Decimal
    ask_fee: Decimal
    maker_bid_fee: Decimal
    maker_ask_fee: Decimal
    bid_min_total: Decimal
    ask_min_total: Decimal
    max_total: Decimal
    state: str
    bid_types: tuple[str, ...]
    ask_types: tuple[str, ...]
    order_types: tuple[str, ...]
    order_sides: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Balance:
    currency: str
    balance: Decimal
    locked: Decimal
    avg_buy_price: Decimal
    avg_buy_price_modified: bool
    unit_currency: str


@dataclass(frozen=True, slots=True)
class OrderRequest:
    market: str
    side: Literal["bid", "ask"]
    ord_type: Literal["limit", "price", "market", "best"]
    identifier: str
    volume: Decimal | None = None
    price: Decimal | None = None
    time_in_force: str | None = None
    smp_type: str = "cancel_maker"


@dataclass(frozen=True, slots=True)
class Trade:
    uuid: str
    market: str
    price: Decimal
    volume: Decimal
    funds: Decimal
    side: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class OrderSnapshot:
    uuid: str
    identifier: str | None
    market: str
    side: str
    ord_type: str
    state: str
    price: Decimal | None
    volume: Decimal | None
    remaining_volume: Decimal | None
    executed_volume: Decimal | None
    reserved_fee: Decimal | None
    remaining_fee: Decimal | None
    paid_fee: Decimal | None
    locked: Decimal | None
    prevented_volume: Decimal | None
    prevented_locked: Decimal | None
    trades_count: int
    created_at: datetime
    time_in_force: str | None
    smp_type: str | None
    trades: tuple[Trade, ...]


@dataclass(frozen=True, slots=True)
class ApiKeyInfo:
    access_key: str = field(repr=False)
    expire_at: datetime


@dataclass(frozen=True, slots=True)
class UpbitCredentials:
    access_key: str = field(repr=False)
    secret_key: str = field(repr=False)
