"""core 값 객체(models.py).

- 모두 frozen·slots dataclass다. 만든 뒤 바꿀 수 없다.
- 금액·수량·가격·수수료는 Decimal이다(INV-14). float 필드가 없다.
- 종목 경고(TS-102): warning이 참이거나 caution 항목이 하나라도 참이면 경고 종목이다.
"""

import dataclasses
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
    models.Ticker: ("trade_price", "change_rate", "acc_trade_price_24h", "acc_trade_volume_24h"),
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
        "change_rate",
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
    models.ApiKeyInfo: ("access_key", "expire_at"),
}


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
        "identifier": "L-20261105-0001",
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


def test_api_key_info_cannot_be_modified():
    info = models.ApiKeyInfo(
        access_key=fake_access_key(), expire_at=datetime(2027, 11, 5, tzinfo=UTC)
    )

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
    req = models.OrderRequest(market="KRW-BTC", side="ask", ord_type="market", identifier="L-1")

    assert (req.volume, req.price, req.time_in_force) == (None, None, None)


def test_order_request_smp_type_can_be_set():
    assert order_request(smp_type="reduce").smp_type == "reduce"


def test_order_request_requires_identifier():
    # identifier를 DB에 먼저 저장하고 보낸다(INV-03). 없는 주문 요청은 만들 수 없다.
    with pytest.raises(TypeError):
        models.OrderRequest(market="KRW-BTC", side="bid", ord_type="price", price=Decimal("10000"))


# ── ApiKeyInfo ────────────────────────────────────────────


def test_api_key_info_repr_and_str_hide_the_access_key():
    key = fake_access_key()
    info = models.ApiKeyInfo(access_key=key, expire_at=datetime(2027, 11, 5, tzinfo=UTC))

    for text in (repr(info), str(info)):
        assert key not in text
        # 앞 4자리 정도는 보여도 되지만(INV-07, 화면 표시) 8자 이상 이어진 조각은 없어야 한다.
        for start in range(len(key) - 7):
            assert key[start : start + 8] not in text


def test_api_key_info_still_holds_the_access_key():
    key = fake_access_key()
    expire_at = datetime(2027, 11, 5, 9, 0, tzinfo=UTC)

    info = models.ApiKeyInfo(access_key=key, expire_at=expire_at)

    assert info.access_key == key
    assert info.expire_at == expire_at
    assert info == models.ApiKeyInfo(access_key=key, expire_at=expire_at)


# ── 설계 메모의 필드 이름 ─────────────────────────────────


@pytest.mark.parametrize("cls", ALL_MODELS, ids=lambda c: c.__name__)
def test_models_have_the_designed_fields(cls):
    missing = set(MODEL_FIELDS[cls]) - {f.name for f in dataclasses.fields(cls)}

    assert not missing, f"{cls.__name__}: {sorted(missing)}"
