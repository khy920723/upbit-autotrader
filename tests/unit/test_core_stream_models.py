"""core 웹소켓 이벤트 모델(models.py, 3단계 3b).

- 모두 frozen·slots dataclass다. 만든 뒤 바꿀 수 없다.
- 금액·수량·가격·수수료·비율은 Decimal이다(INV-14). Decimal 필드에
  float·int·bool·str을 넣으면 만들 때 TypeError다(`Decimal | None` 필드는
  None 허용). 기존 `_check_decimals` 방식.
- 시각(datetime)은 시간대가 있어야 한다. naive이거나 utcoffset()이 None이면
  ValueError다.
- 타임스탬프(ms)는 int다. float 필드는 StreamStatus.retry_in(초,
  Clock.sleep에 넘기는 대기 시간)뿐이다.
- 비밀(키, 토큰, JWT, Authorization)을 담는 필드가 없다(INV-07).

정한 필드. 근거는 공식 문서 docs.upbit.com/kr/reference/의 websocket-ticker,
websocket-myorder, websocket-myasset, websocket-announcement(2026-11-05 확인).
앱 공통 이름으로 바꾼 것은 화살표로 적는다. 바꾸는 일은 어댑터가 한다.

- StreamOpened(stream, connection_no): 어댑터가 구독 요청을 보낸 직후 가장
  먼저 내는 표시(문서 필드 아님). stream은 "public"·"private".
- TickerEvent: market(←code), trade_price, signed_change_rate,
  acc_trade_price_24h, acc_trade_volume_24h(REST Ticker와 맞춘다),
  market_state(PREVIEW·ACTIVE·DELISTED, 없으면 None),
  delisting_date(date | None), timestamp_ms(←timestamp),
  stream_type(SNAPSHOT·REALTIME).
  폐기 필드 is_trading_suspended·market_warning은 두지 않는다.
- MyOrderEvent: market(←code), uuid, identifier(없으면 None),
  side(←ask_bid. 문서 값 BID·ASK를 REST OrderSnapshot처럼 소문자 bid·ask로),
  ord_type(←order_type), state(wait·watch·trade·done·cancel·prevented),
  price, avg_price, volume, remaining_volume, executed_volume,
  executed_funds, trade_uuid, trade_fee, is_maker, smp_type,
  prevented_volume, order_timestamp_ms(←order_timestamp),
  trade_timestamp_ms(←trade_timestamp, 없으면 None), timestamp_ms(←timestamp).
  - 공식 문서에는 trade_price·trade_volume 필드가 없다. state=trade면
    price·volume이 체결 가격·체결량이다. 그래서 설계 메모의
    trade_price·trade_volume은 두지 않는다.
  - 필수 Decimal: executed_volume, executed_funds. 나머지 Decimal(price,
    avg_price, volume, remaining_volume, trade_fee, prevented_volume)은
    시장가 주문이나 체결 전이면 null일 수 있어 None을 허용한다.
- AssetBalance(currency, balance, locked)
- MyAssetEvent(asset_uuid, assets: tuple[AssetBalance, ...],
  asset_timestamp_ms(←asset_timestamp), timestamp_ms(←timestamp)).
  asset_uuid는 중복 이벤트를 거를 때 쓴다.
- AnnouncementEvent(uuid, title, category, url, event_type(CREATED·UPDATED),
  listed_at, first_listed_at, body, timestamp_ms(←timestamp)).
  listed_at·first_listed_at은 문서에서 KST ISO 8601 문자열이다. 시간대 있는
  datetime으로 둔다. body는 요청했을 때만 오고 크면 null(None)이다.
- StreamStatus(stream, kind, reason, error_name, retry_in).
  kind는 CONNECTING·OPEN·RECONNECTING·DEGRADED·BROKEN·AUTH_CHECK.
  error_name·retry_in(초)은 없으면 None.
"""

import dataclasses
import typing
from datetime import UTC, date, datetime, timedelta, timezone, tzinfo
from decimal import Decimal

import pytest

from autotrader.core import models

KST = timezone(timedelta(hours=9))

STREAM_MODELS = (
    models.StreamOpened,
    models.TickerEvent,
    models.MyOrderEvent,
    models.AssetBalance,
    models.MyAssetEvent,
    models.AnnouncementEvent,
    models.StreamStatus,
)

MODEL_FIELDS = {
    models.StreamOpened: ("stream", "connection_no"),
    models.TickerEvent: (
        "market",
        "trade_price",
        "signed_change_rate",
        "acc_trade_price_24h",
        "acc_trade_volume_24h",
        "market_state",
        "delisting_date",
        "timestamp_ms",
        "stream_type",
    ),
    models.MyOrderEvent: (
        "market",
        "uuid",
        "identifier",
        "side",
        "ord_type",
        "state",
        "price",
        "avg_price",
        "volume",
        "remaining_volume",
        "executed_volume",
        "executed_funds",
        "trade_uuid",
        "trade_fee",
        "is_maker",
        "smp_type",
        "prevented_volume",
        "order_timestamp_ms",
        "trade_timestamp_ms",
        "timestamp_ms",
    ),
    models.AssetBalance: ("currency", "balance", "locked"),
    models.MyAssetEvent: ("asset_uuid", "assets", "asset_timestamp_ms", "timestamp_ms"),
    models.AnnouncementEvent: (
        "uuid",
        "title",
        "category",
        "url",
        "event_type",
        "listed_at",
        "first_listed_at",
        "body",
        "timestamp_ms",
    ),
    models.StreamStatus: ("stream", "kind", "reason", "error_name", "retry_in"),
}

REQUIRED_DECIMALS = {
    models.TickerEvent: (
        "trade_price",
        "signed_change_rate",
        "acc_trade_price_24h",
        "acc_trade_volume_24h",
    ),
    models.MyOrderEvent: ("executed_volume", "executed_funds"),
    models.AssetBalance: ("balance", "locked"),
}
OPTIONAL_DECIMALS = {
    models.MyOrderEvent: (
        "price",
        "avg_price",
        "volume",
        "remaining_volume",
        "trade_fee",
        "prevented_volume",
    ),
}
DECIMAL_CASES = [
    (cls, name)
    for table in (REQUIRED_DECIMALS, OPTIONAL_DECIMALS)
    for cls, names in table.items()
    for name in names
]
REQUIRED_DECIMAL_CASES = [(cls, name) for cls, names in REQUIRED_DECIMALS.items() for name in names]
OPTIONAL_DECIMAL_CASES = [(cls, name) for cls, names in OPTIONAL_DECIMALS.items() for name in names]
NOT_DECIMALS = [1.5, 1, True, "1.5"]

TIMESTAMP_FIELDS = [
    (models.TickerEvent, "timestamp_ms"),
    (models.MyOrderEvent, "order_timestamp_ms"),
    (models.MyOrderEvent, "trade_timestamp_ms"),
    (models.MyOrderEvent, "timestamp_ms"),
    (models.MyAssetEvent, "asset_timestamp_ms"),
    (models.MyAssetEvent, "timestamp_ms"),
    (models.AnnouncementEvent, "timestamp_ms"),
]
AWARE_FIELDS = [
    (models.AnnouncementEvent, "listed_at"),
    (models.AnnouncementEvent, "first_listed_at"),
]

# 공식 문서 예시(websocket-myorder.md "수신 메시지 예제")의 값. identifier만 앱 형식이 아니다.
DOC_MY_ORDER = {
    "market": "KRW-BTC",
    "uuid": "ac2dc2a3-fce9-40a2-a4f6-5987c25c438f",
    "identifier": "test-1",
    "side": "bid",
    "ord_type": "limit",
    "state": "trade",
    "price": Decimal("0.001453"),
    "avg_price": Decimal("0.00145372"),
    "volume": Decimal("30925891.29839369"),
    "remaining_volume": Decimal("29968038.09235948"),
    "executed_volume": Decimal("30925891.29839369"),
    "executed_funds": Decimal("44935.32005656603"),
    "trade_uuid": "68315169-fba4-4175-ade3-aff14a616657",
    "trade_fee": Decimal("22.467660028283017"),
    "is_maker": True,
    "smp_type": "cancel_maker",
    "prevented_volume": Decimal("1.174291929"),
    "order_timestamp_ms": 1710751590000,
    "trade_timestamp_ms": 1710751590421,
    "timestamp_ms": 1710751597500,
}


def valid_values(cls) -> dict:
    """모델마다 올바른 값 한 벌(공식 문서 예시에서 가져온 값)."""
    builders = {
        models.StreamOpened: lambda: {"stream": "public", "connection_no": 1},
        models.TickerEvent: lambda: {
            "market": "KRW-BTC",
            "trade_price": Decimal("109868000.0"),
            "signed_change_rate": Decimal("0.006439793"),
            "acc_trade_price_24h": Decimal("198189163442.74924"),
            "acc_trade_volume_24h": Decimal("1807.38027625"),
            "market_state": "ACTIVE",
            "delisting_date": None,
            "timestamp_ms": 1787729042606,
            "stream_type": "SNAPSHOT",
        },
        models.MyOrderEvent: lambda: dict(DOC_MY_ORDER),
        models.AssetBalance: lambda: {
            "currency": "KRW",
            "balance": Decimal("1386929.37231066771348207123"),
            "locked": Decimal("10329.670127489597585685"),
        },
        models.MyAssetEvent: lambda: {
            "asset_uuid": "e635f223-1609-4969-8fb6-4376937baad6",
            "assets": (
                models.AssetBalance(
                    currency="KRW",
                    balance=Decimal("1386929.37231066771348207123"),
                    locked=Decimal("10329.670127489597585685"),
                ),
            ),
            "asset_timestamp_ms": 1710146517259,
            "timestamp_ms": 1710146517267,
        },
        models.AnnouncementEvent: lambda: {
            "uuid": "562593104",
            "title": "[거래] 신규 거래 지원 안내 ...",
            "category": "trade",
            "url": "https://www.upbit.com/service_center/notice?id=562593104&view=share",
            "event_type": "CREATED",
            "listed_at": datetime(2026, 7, 14, 16, 36, 34, tzinfo=KST),
            "first_listed_at": datetime(2026, 7, 14, 16, 36, 34, tzinfo=KST),
            "body": None,
            "timestamp_ms": 1752566400123,
        },
        models.StreamStatus: lambda: {
            "stream": "public",
            "kind": "RECONNECTING",
            "reason": "closed",
            "error_name": None,
            "retry_in": 1.0,
        },
    }
    return builders[cls]()


def literal_args(cls, name: str) -> set:
    """필드 표기의 Literal 값. `type X = Literal[...]` 별칭도 받는다."""
    hint = typing.get_type_hints(cls)[name]
    hint = getattr(hint, "__value__", hint)
    return set(typing.get_args(hint))


class _NoOffset(tzinfo):
    """tzinfo는 있지만 utcoffset()이 None인 시간대(naive와 같다)."""

    def utcoffset(self, dt):
        return None

    def dst(self, dt):
        return None

    def tzname(self, dt):
        return "none"


# ── 공통: frozen, slots, 필드 ─────────────────────────────


@pytest.mark.parametrize("cls", STREAM_MODELS, ids=lambda c: c.__name__)
def test_stream_models_are_frozen_slotted_dataclasses(cls):
    assert dataclasses.is_dataclass(cls)
    assert cls.__dataclass_params__.frozen
    assert "__slots__" in cls.__dict__


@pytest.mark.parametrize("cls", STREAM_MODELS, ids=lambda c: c.__name__)
def test_stream_models_have_exactly_the_decided_fields(cls):
    # 필드가 늘거나 빠지면 이 파일의 docstring(정한 필드 목록)과 어댑터 변환을 함께 고친다.
    assert tuple(f.name for f in dataclasses.fields(cls)) == MODEL_FIELDS[cls]


@pytest.mark.parametrize("cls", STREAM_MODELS, ids=lambda c: c.__name__)
def test_valid_values_build(cls):
    obj = cls(**valid_values(cls))

    assert obj == cls(**valid_values(cls))


@pytest.mark.parametrize("cls", STREAM_MODELS, ids=lambda c: c.__name__)
def test_stream_models_cannot_be_modified(cls):
    obj = cls(**valid_values(cls))
    name = MODEL_FIELDS[cls][0]

    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(obj, name, "other")


@pytest.mark.parametrize("cls", STREAM_MODELS, ids=lambda c: c.__name__)
def test_stream_models_have_no_secret_fields(cls):
    # INV-07: 비공개 스트림 연결의 JWT나 키가 이벤트·상태에 실려 로그·DB로 가면 안 된다.
    words = ("key", "token", "secret", "jwt", "auth", "nonce", "header", "password")
    for name in MODEL_FIELDS[cls]:
        assert not any(word in name.lower() for word in words), f"{cls.__name__}.{name}"


# ── Decimal 강제(INV-14) ──────────────────────────────────


@pytest.mark.parametrize(("cls", "name"), DECIMAL_CASES, ids=lambda v: getattr(v, "__name__", v))
def test_money_fields_are_annotated_decimal(cls, name):
    fields = {f.name: f for f in dataclasses.fields(cls)}
    annotation = str(fields[name].type)

    assert "Decimal" in annotation, f"{cls.__name__}.{name}: {annotation}"
    assert "float" not in annotation, f"{cls.__name__}.{name}: {annotation}"


@pytest.mark.parametrize(("cls", "name"), DECIMAL_CASES, ids=lambda v: getattr(v, "__name__", v))
@pytest.mark.parametrize("bad", NOT_DECIMALS, ids=lambda v: type(v).__name__)
def test_decimal_fields_reject_other_types(cls, name, bad):
    # 웹소켓 숫자는 JSON Double이라 기본 json.loads면 float가 된다. 그 실수를 만들 때 잡는다.
    values = valid_values(cls)
    values[name] = bad

    with pytest.raises(TypeError):
        cls(**values)


@pytest.mark.parametrize(
    ("cls", "name"), OPTIONAL_DECIMAL_CASES, ids=lambda v: getattr(v, "__name__", v)
)
def test_optional_decimal_fields_accept_none(cls, name):
    values = valid_values(cls)
    values[name] = None

    assert getattr(cls(**values), name) is None


@pytest.mark.parametrize(
    ("cls", "name"), REQUIRED_DECIMAL_CASES, ids=lambda v: getattr(v, "__name__", v)
)
def test_required_decimal_fields_reject_none(cls, name):
    values = valid_values(cls)
    values[name] = None

    with pytest.raises(TypeError):
        cls(**values)


def test_decimal_values_keep_every_digit():
    # 문서 예시의 긴 자릿수(myAsset balance)가 그대로 남는다.
    event = models.MyAssetEvent(**valid_values(models.MyAssetEvent))

    assert str(event.assets[0].balance) == "1386929.37231066771348207123"


@pytest.mark.parametrize("cls", STREAM_MODELS, ids=lambda c: c.__name__)
def test_only_float_field_is_retry_in(cls):
    # INV-14: 금액·수량·비율·시각은 float로 두지 않는다. 대기 시간(초)만 Clock.sleep과 같은 float다.
    floats = {f.name for f in dataclasses.fields(cls) if "float" in str(f.type)}

    assert floats == ({"retry_in"} if cls is models.StreamStatus else set())


@pytest.mark.parametrize(("cls", "name"), TIMESTAMP_FIELDS, ids=lambda v: getattr(v, "__name__", v))
def test_millisecond_timestamps_are_int(cls, name):
    annotation = str({f.name: f for f in dataclasses.fields(cls)}[name].type)

    assert "int" in annotation, f"{cls.__name__}.{name}: {annotation}"
    assert "float" not in annotation
    assert "Decimal" not in annotation


# ── 시각은 시간대가 있어야 한다 ───────────────────────────


@pytest.mark.parametrize(("cls", "name"), AWARE_FIELDS, ids=lambda v: getattr(v, "__name__", v))
@pytest.mark.parametrize(
    "naive",
    [datetime(2026, 7, 14, 16, 36, 34), datetime(2026, 7, 14, 16, 36, 34, tzinfo=_NoOffset())],
    ids=["no-tzinfo", "utcoffset-none"],
)
def test_announcement_times_must_be_aware(cls, name, naive):
    # 문서의 listed_at은 KST 문자열이다. 시간대를 잃고 UTC로 읽으면 9시간 어긋난다.
    values = valid_values(cls)
    values[name] = naive

    with pytest.raises(ValueError):  # noqa: PT011 (문구는 정하지 않는다)
        cls(**values)


def test_announcement_times_keep_the_instant():
    event = models.AnnouncementEvent(**valid_values(models.AnnouncementEvent))

    assert event.listed_at == datetime(2026, 7, 14, 7, 36, 34, tzinfo=UTC)
    assert event.first_listed_at.utcoffset() is not None


# ── Literal 값 ────────────────────────────────────────────


@pytest.mark.parametrize(
    "cls", [models.StreamOpened, models.StreamStatus], ids=lambda c: c.__name__
)
def test_stream_names(cls):
    assert literal_args(cls, "stream") == {"public", "private"}


def test_stream_status_kinds():
    assert literal_args(models.StreamStatus, "kind") == {
        "CONNECTING",
        "OPEN",
        "RECONNECTING",
        "DEGRADED",
        "BROKEN",
        "AUTH_CHECK",
    }


def test_ticker_stream_types():
    assert literal_args(models.TickerEvent, "stream_type") == {"SNAPSHOT", "REALTIME"}


def test_announcement_event_types():
    assert literal_args(models.AnnouncementEvent, "event_type") == {"CREATED", "UPDATED"}


# ── 모델별 ────────────────────────────────────────────────


def test_ticker_event_reads_no_deprecated_fields():
    # 공식 문서: is_trading_suspended·market_warning은 Deprecated(참조하지 않는 것을 권장).
    names = set(MODEL_FIELDS[models.TickerEvent])

    assert not names & {"is_trading_suspended", "market_warning"}


def test_ticker_event_market_state_and_delisting_date_may_be_unknown():
    values = valid_values(models.TickerEvent) | {"market_state": None, "delisting_date": None}

    event = models.TickerEvent(**values)

    assert (event.market_state, event.delisting_date) == (None, None)


def test_ticker_event_holds_a_delisting_date():
    values = valid_values(models.TickerEvent) | {"delisting_date": date(2026, 11, 20)}

    assert models.TickerEvent(**values).delisting_date == date(2026, 11, 20)


def test_my_order_event_from_doc_example():
    event = models.MyOrderEvent(**valid_values(models.MyOrderEvent))

    assert (event.side, event.ord_type, event.state) == ("bid", "limit", "trade")
    assert event.trade_uuid == "68315169-fba4-4175-ade3-aff14a616657"
    assert event.is_maker is True
    assert event.trade_fee == Decimal("22.467660028283017")


def test_my_order_event_without_trade_fields():
    # 체결이 아닌 이벤트(wait·cancel 등): trade_uuid·trade_fee·is_maker·trade_timestamp는 null이다.
    # 사용자가 직접 낸 주문은 identifier가 없고, smp_type이 없는 주문도 있다.
    values = valid_values(models.MyOrderEvent) | {
        "state": "wait",
        "identifier": None,
        "trade_uuid": None,
        "trade_fee": None,
        "is_maker": None,
        "smp_type": None,
        "prevented_volume": None,
        "trade_timestamp_ms": None,
    }

    event = models.MyOrderEvent(**values)

    assert (event.identifier, event.trade_uuid, event.is_maker) == (None, None, None)
    assert event.trade_timestamp_ms is None


@pytest.mark.parametrize("state", ["wait", "watch", "trade", "done", "cancel", "prevented"])
def test_my_order_event_accepts_every_documented_state(state):
    values = valid_values(models.MyOrderEvent) | {"state": state}

    assert models.MyOrderEvent(**values).state == state


def test_my_asset_event_holds_balances_as_a_tuple():
    event = models.MyAssetEvent(**valid_values(models.MyAssetEvent))

    assert isinstance(event.assets, tuple)
    assert event.assets[0].currency == "KRW"
    assert hash(event) == hash(models.MyAssetEvent(**valid_values(models.MyAssetEvent)))


def test_my_asset_event_may_be_empty():
    values = valid_values(models.MyAssetEvent) | {"assets": ()}

    assert models.MyAssetEvent(**values).assets == ()


def test_announcement_body_may_be_missing_or_present():
    values = valid_values(models.AnnouncementEvent)

    assert models.AnnouncementEvent(**values).body is None
    assert models.AnnouncementEvent(**(values | {"body": "본문"})).body == "본문"


def test_stream_status_optional_parts():
    status = models.StreamStatus(
        stream="private", kind="OPEN", reason="opened", error_name=None, retry_in=None
    )

    assert (status.error_name, status.retry_in) == (None, None)


def test_stream_status_compares_by_value():
    a = models.StreamStatus(**valid_values(models.StreamStatus))
    b = models.StreamStatus(**valid_values(models.StreamStatus))

    assert a == b
    assert a != models.StreamStatus(**(valid_values(models.StreamStatus) | {"retry_in": 2.0}))
