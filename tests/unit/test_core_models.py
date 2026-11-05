"""core 값 객체(models.py).

- 모두 frozen·slots dataclass다. 만든 뒤 바꿀 수 없다.
- 금액·수량·가격·수수료는 Decimal이다(INV-14). float 필드가 없다.
- 종목 경고(TS-102): warning이 참이거나 caution 항목이 하나라도 참이면 경고 종목이다.
- Decimal 필드에 float·int·bool·str을 넣으면 만들 때 TypeError다.
- 비밀(UpbitCredentials)은 dataclass가 아니다. 복제·피클·asdict로 값이 나오지 않는다.
"""

import copy
import dataclasses
import pickle
import secrets
import string
from datetime import UTC, datetime
from decimal import Decimal
from types import MappingProxyType

import pytest
from hypothesis import given
from hypothesis import strategies as st

from autotrader.core import models

ALL_MODELS = (
    models.MarketInfo,
    models.Candle,
    models.Ticker,
    models.OrderbookUnit,
    models.Orderbook,
    models.OrderChance,
    models.Balance,
    models.OrderRequest,
    models.Trade,
    models.OrderSnapshot,
    models.ApiKeyInfo,
)

# 녹화 응답(tests/fixtures/upbit/README.md 11번)에서 본 caution 키 5개.
KNOWN_CAUTION_KEYS = (
    "PRICE_FLUCTUATIONS",
    "TRADING_VOLUME_SOARING",
    "DEPOSIT_AMOUNT_SOARING",
    "GLOBAL_PRICE_DIFFERENCES",
    "CONCENTRATION_OF_SMALL_ACCOUNTS",
)

# 모델별 Decimal이어야 하는 필드(값이 없을 수 있는 필드는 `Decimal | None`도 된다).
DECIMAL_FIELDS = {
    models.Candle: ("open", "high", "low", "close", "volume", "value"),
    models.Ticker: (
        "trade_price",
        "signed_change_rate",
        "acc_trade_price_24h",
        "acc_trade_volume_24h",
    ),
    models.OrderbookUnit: ("ask_price", "bid_price", "ask_size", "bid_size"),
    models.OrderChance: (
        "bid_fee",
        "ask_fee",
        "maker_bid_fee",
        "maker_ask_fee",
        "bid_min_total",
        "ask_min_total",
        "max_total",
    ),
    models.Balance: ("balance", "locked", "avg_buy_price"),
    models.OrderRequest: ("volume", "price"),
    models.Trade: ("price", "volume", "funds"),
    models.OrderSnapshot: (
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
    ),
}


# 설계 메모(stage3-design.md)의 필드 이름.
MODEL_FIELDS = {
    models.MarketInfo: ("market", "korean_name", "english_name", "warning", "caution"),
    models.Candle: (
        "market",
        "unit",
        "start_utc",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "value",
    ),
    models.Ticker: (
        "market",
        "trade_price",
        "signed_change_rate",
        "acc_trade_price_24h",
        "acc_trade_volume_24h",
        "timestamp_ms",
    ),
    models.OrderbookUnit: ("ask_price", "bid_price", "ask_size", "bid_size"),
    models.Orderbook: ("market", "units", "timestamp_ms"),
    models.OrderChance: (
        "market",
        "bid_fee",
        "ask_fee",
        "maker_bid_fee",
        "maker_ask_fee",
        "bid_min_total",
        "ask_min_total",
        "max_total",
        "state",
        "bid_types",
        "ask_types",
        "order_types",
        "order_sides",
    ),
    models.Balance: (
        "currency",
        "balance",
        "locked",
        "avg_buy_price",
        "avg_buy_price_modified",
        "unit_currency",
    ),
    models.OrderRequest: (
        "market",
        "side",
        "ord_type",
        "identifier",
        "volume",
        "price",
        "time_in_force",
        "smp_type",
    ),
    models.Trade: ("uuid", "market", "price", "volume", "funds", "side", "created_at"),
    models.OrderSnapshot: (
        "uuid",
        "identifier",
        "market",
        "side",
        "ord_type",
        "state",
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
        "trades_count",
        "created_at",
        "time_in_force",
        "smp_type",
        "trades",
    ),
    models.ApiKeyInfo: ("access_key_prefix", "is_current", "expire_at"),
}

# D-047 형식 `uat-{모드}-{UTC 시각 yyMMddHHmmss}-{임의 16진수 8자}`(매매 로직 명세 6장).
IDENTIFIER = "uat-p-261105000000-9f3a7c1e"


def fake_access_key() -> str:
    """실행 중에 만드는 가짜 값. 실제 키 형식 문자열을 소스에 적지 않는다."""
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(40))


def market(*, warning: bool = False, caution=None) -> models.MarketInfo:
    return models.MarketInfo(
        market="KRW-BTC",
        korean_name="비트코인",
        english_name="Bitcoin",
        warning=warning,
        caution=dict.fromkeys(KNOWN_CAUTION_KEYS, False) if caution is None else caution,
    )


def order_request(**overrides) -> models.OrderRequest:
    values = {
        "market": "KRW-BTC",
        "side": "bid",
        "ord_type": "price",
        "identifier": IDENTIFIER,
        "price": Decimal("10000"),
    }
    values.update(overrides)
    return models.OrderRequest(**values)


# ── 공통: frozen, slots, Decimal ──────────────────────────


@pytest.mark.parametrize("cls", ALL_MODELS, ids=lambda c: c.__name__)
def test_models_are_frozen_slotted_dataclasses(cls):
    assert dataclasses.is_dataclass(cls)
    assert cls.__dataclass_params__.frozen
    assert "__slots__" in cls.__dict__


@pytest.mark.parametrize(
    ("cls", "name"),
    [(cls, name) for cls, names in DECIMAL_FIELDS.items() for name in names],
    ids=lambda v: v if isinstance(v, str) else v.__name__,
)
def test_money_fields_are_decimal(cls, name):
    fields = {f.name: f for f in dataclasses.fields(cls)}
    assert name in fields, f"{cls.__name__}에 {name} 필드가 없다"

    # `from __future__ import annotations`를 써도 되도록 표기 문자열로 본다.
    annotation = str(fields[name].type)
    assert "Decimal" in annotation, f"{cls.__name__}.{name}: {annotation}"
    assert "float" not in annotation, f"{cls.__name__}.{name}: {annotation}"


@pytest.mark.parametrize("cls", ALL_MODELS, ids=lambda c: c.__name__)
def test_no_model_field_is_float(cls):
    # INV-14: core의 금액·수량 계산에 float가 없다. 시각과 비율도 float로 두지 않는다.
    for field in dataclasses.fields(cls):
        assert "float" not in str(field.type), f"{cls.__name__}.{field.name}: {field.type}"


def test_market_info_cannot_be_modified():
    info = market()

    with pytest.raises(dataclasses.FrozenInstanceError):
        info.warning = True  # type: ignore[misc]


def test_order_request_cannot_be_modified():
    req = order_request()

    with pytest.raises(dataclasses.FrozenInstanceError):
        req.identifier = "other"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        req.smp_type = "reduce"  # type: ignore[misc]


def api_key_info(**overrides) -> models.ApiKeyInfo:
    values = {
        "access_key_prefix": fake_access_key()[:4],
        "is_current": True,
        "expire_at": datetime(2027, 11, 5, tzinfo=UTC),
    }
    values.update(overrides)
    return models.ApiKeyInfo(**values)


def test_api_key_info_cannot_be_modified():
    info = api_key_info()

    with pytest.raises(dataclasses.FrozenInstanceError):
        info.expire_at = datetime(2030, 1, 1, tzinfo=UTC)  # type: ignore[misc]


# ── MarketInfo.is_warned (TS-102) ─────────────────────────


def test_normal_market_is_not_warned():
    assert market().is_warned is False


def test_market_without_caution_flags_is_not_warned():
    assert market(caution={}).is_warned is False


def test_warning_alone_is_warned():
    # 녹화 응답의 KRW 마켓에는 이 경우가 없었다(README 10번). 그래서 여기서 만든다.
    assert market(warning=True).is_warned is True


@pytest.mark.parametrize("key", KNOWN_CAUTION_KEYS)
def test_one_caution_flag_is_warned(key):
    caution = dict.fromkeys(KNOWN_CAUTION_KEYS, False)
    caution[key] = True

    assert market(caution=caution).is_warned is True


def test_unknown_caution_key_that_is_true_is_warned():
    # 업비트가 새 주의 항목을 추가해도 놓치지 않는다.
    caution = dict.fromkeys(KNOWN_CAUTION_KEYS, False)
    caution["SOMETHING_NEW_2027"] = True

    assert market(caution=caution).is_warned is True


def test_unknown_caution_key_that_is_false_is_not_warned():
    caution = dict.fromkeys(KNOWN_CAUTION_KEYS, False)
    caution["SOMETHING_NEW_2027"] = False

    assert market(caution=caution).is_warned is False


def test_is_warned_accepts_any_mapping():
    caution = MappingProxyType({"TRADING_VOLUME_SOARING": True})

    assert market(caution=caution).is_warned is True


@given(
    warning=st.booleans(),
    caution=st.dictionaries(st.text(min_size=1, max_size=40), st.booleans(), max_size=8),
)
def test_is_warned_is_warning_or_any_caution(warning, caution):
    assert market(warning=warning, caution=caution).is_warned is (warning or any(caution.values()))


# ── OrderRequest ──────────────────────────────────────────


def test_order_request_smp_type_defaults_to_cancel_maker():
    # CLAUDE.md: smp_type은 항상 명시한다. 기본값이 있어 빠뜨려도 cancel_maker가 실린다.
    assert order_request().smp_type == "cancel_maker"


def test_order_request_optional_fields_default_to_none():
    req = models.OrderRequest(
        market="KRW-BTC", side="ask", ord_type="market", identifier=IDENTIFIER
    )

    assert (req.volume, req.price, req.time_in_force) == (None, None, None)


@pytest.mark.parametrize("smp_type", ["reduce", "cancel_taker", "none", "", None])
def test_order_request_rejects_smp_types_other_than_cancel_maker(smp_type):
    # D-047: 모든 주문은 cancel_maker. cancel_taker는 손절 주문이 취소될 수 있어 쓰지 않는다.
    with pytest.raises(ValueError):  # noqa: PT011 (문구는 정하지 않는다)
        order_request(smp_type=smp_type)


def test_order_request_accepts_explicit_cancel_maker():
    assert order_request(smp_type="cancel_maker").smp_type == "cancel_maker"


def test_order_request_requires_identifier():
    # identifier를 DB에 먼저 저장하고 보낸다(INV-03). 없는 주문 요청은 만들 수 없다.
    with pytest.raises(TypeError):
        models.OrderRequest(market="KRW-BTC", side="bid", ord_type="price", price=Decimal("10000"))


# ── ApiKeyInfo ────────────────────────────────────────────


def test_api_key_info_holds_only_the_prefix_and_expiry():
    # 전체 access_key는 담지 않는다. 화면에는 앞 4자리만 보인다(INV-07). 현재 키인지는 어댑터가
    # 비교해 is_current로 넘긴다.
    key = fake_access_key()
    expire_at = datetime(2027, 11, 5, 9, 0, tzinfo=UTC)

    info = models.ApiKeyInfo(access_key_prefix=key[:4], is_current=True, expire_at=expire_at)

    assert (info.access_key_prefix, info.is_current, info.expire_at) == (key[:4], True, expire_at)
    assert not hasattr(info, "access_key")
    for text in (repr(info), str(info), repr(dataclasses.asdict(info))):
        for start in range(len(key) - 7):
            assert key[start : start + 8] not in text


@pytest.mark.parametrize("prefix", ["abcde", "x" * 40])
def test_api_key_info_rejects_more_than_four_chars(prefix):
    with pytest.raises(ValueError):  # noqa: PT011
        api_key_info(access_key_prefix=prefix)


def test_api_key_info_is_comparable():
    expire_at = datetime(2027, 11, 5, tzinfo=UTC)

    a = api_key_info(access_key_prefix="Ab12", expire_at=expire_at)

    assert a == api_key_info(access_key_prefix="Ab12", expire_at=expire_at)
    assert a != api_key_info(access_key_prefix="Ab12", expire_at=expire_at, is_current=False)


# ── UpbitCredentials: 비밀 ────────────────────────────────


def credentials() -> models.UpbitCredentials:
    return models.UpbitCredentials(access_key=fake_access_key(), secret_key=fake_access_key())


def test_credentials_hold_both_keys():
    access, secret = fake_access_key(), fake_access_key()

    creds = models.UpbitCredentials(access_key=access, secret_key=secret)

    assert (creds.access_key, creds.secret_key) == (access, secret)


def test_credentials_repr_and_str_hide_both_keys():
    creds = credentials()

    for text in (repr(creds), str(creds), f"{creds}", f"{creds!r}"):
        for value in (creds.access_key, creds.secret_key):
            for start in range(len(value) - 7):
                assert value[start : start + 8] not in text


def test_credentials_are_slotted_and_read_only():
    creds = credentials()

    assert "__slots__" in type(creds).__dict__
    assert not hasattr(creds, "__dict__")
    with pytest.raises(AttributeError):
        creds.access_key = "other"  # type: ignore[misc]
    with pytest.raises(AttributeError):
        creds.secret_key = "other"  # type: ignore[misc]
    with pytest.raises(AttributeError):
        creds.extra = "x"  # type: ignore[attr-defined]
    with pytest.raises(AttributeError):
        del creds.access_key  # type: ignore[misc]


def test_credentials_are_not_a_dataclass():
    # dataclasses.asdict·astuple이 비밀을 일반 dict로 꺼내지 못하게 한다.
    creds = credentials()

    assert not dataclasses.is_dataclass(creds)
    with pytest.raises(TypeError):
        dataclasses.asdict(creds)  # type: ignore[call-overload]
    with pytest.raises(TypeError):
        vars(creds)


@pytest.mark.parametrize(
    "dump",
    [
        pickle.dumps,
        lambda c: pickle.dumps(c, protocol=0),
        copy.copy,
        copy.deepcopy,
        lambda c: c.__reduce__(),
        lambda c: c.__reduce_ex__(2),
    ],
    ids=["pickle", "pickle0", "copy", "deepcopy", "reduce", "reduce_ex"],
)
def test_credentials_cannot_be_copied_or_pickled(dump):
    with pytest.raises(TypeError):
        dump(credentials())


def test_credentials_compare_by_value():
    access, secret = fake_access_key(), fake_access_key()
    creds = models.UpbitCredentials(access_key=access, secret_key=secret)

    assert creds == models.UpbitCredentials(access_key=access, secret_key=secret)
    assert creds != models.UpbitCredentials(access_key=access, secret_key=fake_access_key())
    assert creds != models.UpbitCredentials(access_key=fake_access_key(), secret_key=secret)
    assert creds != (access, secret)


def test_credentials_require_strings():
    with pytest.raises(TypeError):
        models.UpbitCredentials(access_key=None, secret_key="x" * 40)  # type: ignore[arg-type]


# ── MarketInfo.caution: 만든 뒤 바꿀 수 없음 ──────────────


def test_market_info_copies_caution():
    source = {"PRICE_FLUCTUATIONS": False}
    info = market(caution=source)

    source["PRICE_FLUCTUATIONS"] = True

    assert info.is_warned is False


def test_market_info_caution_is_read_only():
    info = market()

    with pytest.raises(TypeError):
        info.caution["PRICE_FLUCTUATIONS"] = True  # type: ignore[index]
    assert isinstance(info.caution, MappingProxyType)


def test_market_info_is_hashable_and_comparable():
    a, b = market(), market()

    assert a == b
    assert hash(a) == hash(b)
    assert {a, b} == {a}


# ── OrderSnapshot.trades ──────────────────────────────────


def snapshot(**overrides) -> models.OrderSnapshot:
    values = dict.fromkeys(MODEL_FIELDS[models.OrderSnapshot])
    values.update(
        uuid="00000000-0000-4000-8000-000000000000",
        identifier=IDENTIFIER,
        market="KRW-BTC",
        side="bid",
        ord_type="price",
        state="wait",
        trades_count=0,
        created_at=datetime(2026, 11, 5, tzinfo=UTC),
        trades=(),
    )
    values.update(overrides)
    return models.OrderSnapshot(**values)


def test_order_snapshot_trades_may_be_unknown():
    # 목록 조회 응답에는 trades가 없다. 빈 튜플(체결 없음)과 None(모름)을 구분한다.
    assert snapshot(trades=None).trades is None
    assert snapshot(trades=()).trades == ()


def test_order_snapshot_holds_trades():
    trade = models.Trade(
        uuid="t-1",
        market="KRW-BTC",
        price=Decimal("143250000"),
        volume=Decimal("0.00006981"),
        funds=Decimal("10000.2825"),
        side="bid",
        created_at=datetime(2026, 11, 5, tzinfo=UTC),
    )

    assert snapshot(trades=(trade,), trades_count=1).trades == (trade,)


# ── Decimal 강제(INV-14) ──────────────────────────────────


def valid_values(cls) -> dict:
    """모델마다 올바른 값 한 벌."""
    when = datetime(2026, 11, 5, tzinfo=UTC)
    one = Decimal(1)
    builders = {
        models.Candle: lambda: {
            "market": "KRW-BTC",
            "unit": "m240",
            "start_utc": when,
            "open": one,
            "high": one,
            "low": one,
            "close": one,
            "volume": one,
            "value": one,
        },
        models.Ticker: lambda: {
            "market": "KRW-BTC",
            "trade_price": one,
            "signed_change_rate": Decimal("-0.003"),
            "acc_trade_price_24h": one,
            "acc_trade_volume_24h": one,
            "timestamp_ms": 0,
        },
        models.OrderbookUnit: lambda: {
            "ask_price": one,
            "bid_price": one,
            "ask_size": one,
            "bid_size": one,
        },
        models.OrderChance: lambda: {
            "market": "KRW-BTC",
            "bid_fee": one,
            "ask_fee": one,
            "maker_bid_fee": one,
            "maker_ask_fee": one,
            "bid_min_total": one,
            "ask_min_total": one,
            "max_total": one,
            "state": "active",
            "bid_types": (),
            "ask_types": (),
            "order_types": (),
            "order_sides": (),
        },
        models.Balance: lambda: {
            "currency": "KRW",
            "balance": one,
            "locked": one,
            "avg_buy_price": one,
            "avg_buy_price_modified": False,
            "unit_currency": "KRW",
        },
        models.OrderRequest: lambda: {
            "market": "KRW-BTC",
            "side": "bid",
            "ord_type": "limit",
            "identifier": IDENTIFIER,
            "volume": one,
            "price": one,
            "time_in_force": "ioc",
        },
        models.Trade: lambda: {
            "uuid": "t",
            "market": "KRW-BTC",
            "price": one,
            "volume": one,
            "funds": one,
            "side": "bid",
            "created_at": when,
        },
        models.OrderSnapshot: lambda: (
            dict.fromkeys(DECIMAL_FIELDS[models.OrderSnapshot], one)
            | {
                "uuid": "u",
                "identifier": IDENTIFIER,
                "market": "KRW-BTC",
                "side": "bid",
                "ord_type": "limit",
                "state": "wait",
                "trades_count": 0,
                "created_at": when,
                "time_in_force": None,
                "smp_type": "cancel_maker",
                "trades": (),
            }
        ),
    }
    return builders[cls]()


DECIMAL_CASES = [(cls, name) for cls, names in DECIMAL_FIELDS.items() for name in names]
NOT_DECIMALS = [1.5, 1, True, "1.5"]


@pytest.mark.parametrize("cls", list(DECIMAL_FIELDS), ids=lambda c: c.__name__)
def test_valid_values_build(cls):
    cls(**valid_values(cls))


@pytest.mark.parametrize(("cls", "name"), DECIMAL_CASES, ids=lambda v: getattr(v, "__name__", v))
@pytest.mark.parametrize("bad", NOT_DECIMALS, ids=lambda v: type(v).__name__)
def test_decimal_fields_reject_other_types(cls, name, bad):
    values = valid_values(cls)
    values[name] = bad

    with pytest.raises(TypeError):
        cls(**values)


OPTIONAL_DECIMAL_CASES = [
    (models.OrderRequest, "volume"),
    (models.OrderRequest, "price"),
    *((models.OrderSnapshot, name) for name in DECIMAL_FIELDS[models.OrderSnapshot]),
]


@pytest.mark.parametrize(
    ("cls", "name"), OPTIONAL_DECIMAL_CASES, ids=lambda v: getattr(v, "__name__", v)
)
def test_optional_decimal_fields_accept_none(cls, name):
    values = valid_values(cls)
    values[name] = None

    assert getattr(cls(**values), name) is None


@pytest.mark.parametrize(
    ("cls", "name"),
    [case for case in DECIMAL_CASES if case not in OPTIONAL_DECIMAL_CASES],
    ids=lambda v: getattr(v, "__name__", v),
)
def test_required_decimal_fields_reject_none(cls, name):
    values = valid_values(cls)
    values[name] = None

    with pytest.raises(TypeError):
        cls(**values)


# ── 설계 메모의 필드 이름 ─────────────────────────────────


@pytest.mark.parametrize("cls", ALL_MODELS, ids=lambda c: c.__name__)
def test_models_have_the_designed_fields(cls):
    missing = set(MODEL_FIELDS[cls]) - {f.name for f in dataclasses.fields(cls)}

    assert not missing, f"{cls.__name__}: {sorted(missing)}"
