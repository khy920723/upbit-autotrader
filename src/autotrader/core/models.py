"""core 값 객체: 시세, 주문, 계정 모델.

값 객체는 frozen·slots dataclass이고 금액·수량·가격은 Decimal이다(INV-14, float 금지).
Decimal 필드에 float·int·bool·str이 오면 만들 때 TypeError다(`Decimal | None` 필드는 None 허용).
응답에 없는 선택 필드는 None(모름)으로 둔다.
비밀(UpbitCredentials)은 dataclass가 아니다. repr/str에 값이 없고 복제·피클이 안 된다(INV-07).
웹소켓 이벤트(3b)는 파일 끝에 있다. 공식 문서 필드 이름을 앱 이름으로 바꾸는 일은 어댑터가 한다.
근거: docs/06-architecture/system-architecture.md 6장, docs/08-quality/fakes-spec.md 2.2절.
"""

import dataclasses
import hmac
import types
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from functools import cache
from typing import Literal, NoReturn


@cache
def _decimal_fields(cls: type) -> tuple[tuple[str, bool], ...]:
    """cls의 Decimal 필드 (이름, None 허용 여부). 표기는 실제 타입 객체로 본다."""
    found: list[tuple[str, bool]] = []
    for f in dataclasses.fields(cls):
        if f.type is Decimal:
            found.append((f.name, False))
        elif isinstance(f.type, types.UnionType) and Decimal in f.type.__args__:
            found.append((f.name, type(None) in f.type.__args__))
    return tuple(found)


def _check_decimals(obj: object) -> None:
    """Decimal 필드에 Decimal이 아닌 값이 오면 TypeError(INV-14). 모든 값 객체의 __post_init__."""
    for name, optional in _decimal_fields(type(obj)):
        value = getattr(obj, name)
        if value is None and optional:
            continue
        if not isinstance(value, Decimal):
            raise TypeError(
                f"{type(obj).__name__}.{name}는 Decimal이어야 한다: {type(value).__name__}"
            )


@dataclass(frozen=True, slots=True)
class MarketInfo:
    market: str
    korean_name: str
    english_name: str
    warning: bool
    caution: Mapping[str, bool] = field(hash=False)
    """만들 때 읽기 전용 사본(MappingProxyType)으로 바꾼다. 해시에서 뺀다(비교에는 쓴다)."""

    def __post_init__(self) -> None:
        object.__setattr__(self, "caution", types.MappingProxyType(dict(self.caution)))

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

    __post_init__ = _check_decimals


@dataclass(frozen=True, slots=True)
class Ticker:
    market: str
    trade_price: Decimal
    signed_change_rate: Decimal
    """부호 있는 전일 대비 변화율(업비트 ticker의 signed_change_rate)."""
    acc_trade_price_24h: Decimal
    acc_trade_volume_24h: Decimal
    timestamp_ms: int

    __post_init__ = _check_decimals


@dataclass(frozen=True, slots=True)
class OrderbookUnit:
    ask_price: Decimal
    bid_price: Decimal
    ask_size: Decimal
    bid_size: Decimal

    __post_init__ = _check_decimals


@dataclass(frozen=True, slots=True)
class Orderbook:
    market: str
    units: tuple[OrderbookUnit, ...]
    timestamp_ms: int

    __post_init__ = _check_decimals


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
    bid_balance: Decimal
    """bid_account.balance: 주문 가능 호가 자산(KRW 마켓이면 원화). live의 주문 가능 원화."""
    bid_locked: Decimal
    """bid_account.locked: 주문 등에 묶인 호가 자산."""
    ask_balance: Decimal
    """ask_account.balance: 주문 가능 기준 자산(코인 수량)."""
    ask_locked: Decimal
    """ask_account.locked: 주문 등에 묶인 기준 자산."""

    __post_init__ = _check_decimals


@dataclass(frozen=True, slots=True)
class Balance:
    currency: str
    balance: Decimal
    locked: Decimal
    avg_buy_price: Decimal
    avg_buy_price_modified: bool
    unit_currency: str

    __post_init__ = _check_decimals


@dataclass(frozen=True, slots=True)
class OrderRequest:
    market: str
    side: Literal["bid", "ask"]
    ord_type: Literal["limit", "price", "market", "best"]
    identifier: str
    volume: Decimal | None = None
    price: Decimal | None = None
    time_in_force: str | None = None
    smp_type: Literal["cancel_maker"] = "cancel_maker"
    """D-047: 모든 주문은 cancel_maker. 다른 값은 만들 때 ValueError."""

    def __post_init__(self) -> None:
        _check_decimals(self)
        if self.smp_type != "cancel_maker":
            raise ValueError(f"smp_type은 cancel_maker만 쓴다(D-047): {self.smp_type!r}")


@dataclass(frozen=True, slots=True)
class Trade:
    uuid: str
    market: str
    price: Decimal
    volume: Decimal
    funds: Decimal
    side: str
    created_at: datetime

    __post_init__ = _check_decimals


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
    trades: tuple[Trade, ...] | None
    """체결 목록. 응답에 없으면 None(모름), 체결이 없으면 빈 튜플."""

    __post_init__ = _check_decimals


ACCESS_KEY_PREFIX_LENGTH = 4
"""화면에 보여도 되는 access_key 앞부분 길이(INV-07)."""


@dataclass(frozen=True, slots=True)
class ApiKeyInfo:
    """API 키 목록(GET /v1/api_keys)의 한 줄. 전체 access_key는 담지 않는다.

    현재 쓰는 키인지는 어댑터가 전체 값으로 비교해 is_current로 넘긴다.
    """

    access_key_prefix: str
    is_current: bool
    expire_at: datetime

    def __post_init__(self) -> None:
        if len(self.access_key_prefix) > ACCESS_KEY_PREFIX_LENGTH:
            raise ValueError(f"access_key_prefix는 {ACCESS_KEY_PREFIX_LENGTH}자 이하다")


def _refuse_copy(*_: object) -> NoReturn:
    raise TypeError("UpbitCredentials는 복제·직렬화할 수 없다(INV-07)")


class UpbitCredentials:
    """업비트 Access·Secret Key. 읽기 전용이고 repr/str에 값이 없다.

    dataclass가 아니어서 dataclasses.asdict로 꺼낼 수 없고, copy·deepcopy·pickle은 TypeError다.
    비교는 상수 시간(hmac.compare_digest)으로 한다. 해시하지 않는다.
    """

    __slots__ = ("_access_key", "_secret_key")

    def __init__(self, access_key: str, secret_key: str) -> None:
        if not isinstance(access_key, str) or not isinstance(secret_key, str):
            raise TypeError("access_key와 secret_key는 문자열이어야 한다")
        object.__setattr__(self, "_access_key", access_key)
        object.__setattr__(self, "_secret_key", secret_key)

    @property
    def access_key(self) -> str:
        return self._access_key

    @property
    def secret_key(self) -> str:
        return self._secret_key

    def __setattr__(self, name: str, value: object) -> NoReturn:
        raise AttributeError("UpbitCredentials는 바꿀 수 없다")

    def __delattr__(self, name: str) -> NoReturn:
        raise AttributeError("UpbitCredentials는 바꿀 수 없다")

    def __repr__(self) -> str:
        return "UpbitCredentials(access_key=<hidden>, secret_key=<hidden>)"

    __str__ = __repr__

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, UpbitCredentials):
            return NotImplemented
        same_access = hmac.compare_digest(
            self._access_key.encode("utf-8"), other._access_key.encode("utf-8")
        )
        same_secret = hmac.compare_digest(
            self._secret_key.encode("utf-8"), other._secret_key.encode("utf-8")
        )
        return same_access and same_secret

    __hash__ = None  # type: ignore[assignment]

    __reduce__ = _refuse_copy
    __reduce_ex__ = _refuse_copy
    __copy__ = _refuse_copy
    __deepcopy__ = _refuse_copy
    __getstate__ = _refuse_copy


# ── 웹소켓 이벤트(3단계 3b) ───────────────────────────────
# 근거: 공식 문서 websocket-ticker·myorder·myasset·announcement(2026-11-05 확인),
# docs/06-architecture/system-architecture.md 6장. 정한 필드는 tests/unit/test_core_stream_models.py.

StreamName = Literal["public", "private"]
"""스트림 이름. public은 시세(ticker), private는 내 주문·자산·공지."""

StreamStatusKind = Literal["CONNECTING", "OPEN", "RECONNECTING", "DEGRADED", "BROKEN", "AUTH_CHECK"]


def _check_aware(obj: object, *names: str) -> None:
    """시각 필드가 시간대 없는(naive, utcoffset()이 None) datetime이면 ValueError."""
    for name in names:
        value = getattr(obj, name)
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{type(obj).__name__}.{name}는 시간대가 있는 시각이어야 한다")


@dataclass(frozen=True, slots=True)
class StreamOpened:
    """어댑터가 구독 요청을 보낸 직후 가장 먼저 내는 표시(문서 필드 아님).

    감시(StreamSupervisor)는 이것으로 "열림·다시 열림"을 안다. connection_no는 1부터.
    """

    stream: StreamName
    connection_no: int


@dataclass(frozen=True, slots=True)
class TickerEvent:
    """시세 웹소켓 ticker. market←code, timestamp_ms←timestamp.

    폐기 필드 is_trading_suspended·market_warning은 읽지 않는다.
    market_state(PREVIEW·ACTIVE·DELISTED)·delisting_date는 없으면 None(모름).
    """

    market: str
    trade_price: Decimal
    signed_change_rate: Decimal
    acc_trade_price_24h: Decimal
    acc_trade_volume_24h: Decimal
    market_state: str | None
    delisting_date: date | None
    timestamp_ms: int
    stream_type: Literal["SNAPSHOT", "REALTIME"]

    __post_init__ = _check_decimals


@dataclass(frozen=True, slots=True)
class MyOrderEvent:
    """비공개 웹소켓 myOrder. market←code, side←ask_bid(소문자 bid·ask), ord_type←order_type.

    문서에 trade_price·trade_volume이 없다. state=trade면 price·volume이 체결 가격·체결량이다.
    체결이 아닌 이벤트는 trade_* 필드와 is_maker가 None이다. 앱 밖 주문은 identifier가 None이다.
    """

    market: str
    uuid: str
    identifier: str | None
    side: str
    ord_type: str
    state: str
    """wait·watch·trade·done·cancel·prevented."""
    price: Decimal | None
    avg_price: Decimal | None
    volume: Decimal | None
    remaining_volume: Decimal | None
    executed_volume: Decimal
    executed_funds: Decimal
    trade_uuid: str | None
    trade_fee: Decimal | None
    is_maker: bool | None
    smp_type: str | None
    prevented_volume: Decimal | None
    order_timestamp_ms: int
    trade_timestamp_ms: int | None
    timestamp_ms: int

    __post_init__ = _check_decimals


@dataclass(frozen=True, slots=True)
class AssetBalance:
    currency: str
    balance: Decimal
    locked: Decimal

    __post_init__ = _check_decimals


@dataclass(frozen=True, slots=True)
class MyAssetEvent:
    """비공개 웹소켓 myAsset. asset_uuid로 중복 이벤트를 거른다.

    assets는 만들 때 튜플로 바꾼다(해시·비교가 되게).
    """

    asset_uuid: str
    assets: tuple[AssetBalance, ...]
    asset_timestamp_ms: int
    timestamp_ms: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "assets", tuple(self.assets))


@dataclass(frozen=True, slots=True)
class AnnouncementEvent:
    """비공개 웹소켓 announcement(공지). 종목 코드 필드가 없어 글자로만 판단한다(core/notices.py).

    listed_at·first_listed_at은 문서에서 KST 문자열이다. 시간대 없는 시각은 ValueError.
    body는 요청했을 때만 오고 크면 None이다.
    """

    uuid: str
    title: str
    category: str
    url: str
    event_type: Literal["CREATED", "UPDATED"]
    listed_at: datetime
    first_listed_at: datetime
    body: str | None
    timestamp_ms: int

    def __post_init__(self) -> None:
        _check_aware(self, "listed_at", "first_listed_at")


@dataclass(frozen=True, slots=True)
class StreamStatus:
    """감시(StreamSupervisor)가 알리는 스트림 상태.

    error_name은 서버 오류 이름(error.name), 재연결 훅 실패면 예외 클래스 이름, 없으면 None.
    retry_in은 다시 열기 전에 기다릴 초(RECONNECTING), 없으면 None.
    """

    stream: StreamName
    kind: StreamStatusKind
    reason: str
    error_name: str | None
    retry_in: float | None
