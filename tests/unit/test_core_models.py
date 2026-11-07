"""core 값 객체(models.py).

- 모두 frozen·slots dataclass다. 만든 뒤 바꿀 수 없다.
- 금액·수량·가격·수수료는 Decimal이다(INV-14). float 필드가 없다.
- 종목 경고(TS-102): warning이 참이거나 caution 항목이 하나라도 참이면 경고 종목이다.
- Decimal 필드에 float·int·bool·str을 넣으면 만들 때 TypeError다.
- 비밀(UpbitCredentials)은 dataclass가 아니다. 복제·피클·asdict로 값이 나오지 않는다.
"""

import ast
import copy
import dataclasses
import itertools
import pickle
import secrets
import string
import types
import typing
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
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
        "bid_balance",
        "bid_locked",
        "ask_balance",
        "ask_locked",
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
        "bid_balance",
        "bid_locked",
        "ask_balance",
        "ask_locked",
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
            "bid_balance": one,
            "bid_locked": one,
            "ask_balance": one,
            "ask_locked": one,
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


# ── R17-07: OrderChance.order_types는 폐기 예정 ───────────────
# 공식 주문 가능 정보 문서에서 market.order_types는 폐기 예정이다(대체: bid_types·ask_types).
# 필드는 남기되(응답에 있으면 읽는다) 설명에 "폐기 예정, 판단에 쓰지 않는다"를 적고, 앱 코드가
# 그 값을 읽지 않는지 구조로 본다.

SRC_DIR = Path(models.__file__).resolve().parents[1]  # src/autotrader


def attribute_docstrings(cls: type) -> dict[str, str]:
    """클래스 본문에서 필드 표기 바로 뒤의 문자열(속성 설명)을 필드 이름별로 모은다."""
    tree = ast.parse(Path(models.__file__).read_text(encoding="utf-8"))
    (node,) = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls.__name__]
    found: dict[str, str] = {}
    for before, after in itertools.pairwise(node.body):
        if (
            isinstance(before, ast.AnnAssign)
            and isinstance(before.target, ast.Name)
            and isinstance(after, ast.Expr)
            and isinstance(after.value, ast.Constant)
            and isinstance(after.value.value, str)
        ):
            found[before.target.id] = after.value.value
    return found


def test_order_types_is_documented_as_deprecated_and_not_for_decisions():
    doc = attribute_docstrings(models.OrderChance).get("order_types", "")

    assert "폐기 예정" in doc, doc
    assert "판단에 쓰지 않는다" in doc, doc
    # 판단은 대체 필드로 한다.
    assert "bid_types" in doc, doc
    assert "ask_types" in doc, doc


def test_order_types_stays_a_tuple_of_text():
    # 응답에서 빠질 수 있어 어댑터가 빈 튜플로 둔다(tests/unit/upbit/test_exchange.py R17-07).
    hints = typing.get_type_hints(models.OrderChance)

    assert hints["order_types"] == tuple[str, ...]
    assert hints["bid_types"] == tuple[str, ...]
    assert hints["ask_types"] == tuple[str, ...]


def test_no_app_code_reads_order_types():
    # 판단에 쓰지 않는다를 구조로 강제한다: 앱 코드 어디에서도 `.order_types`를 읽지 않는다.
    # 응답 키 "order_types"를 읽는 곳은 거래 어댑터의 변환 한 곳뿐이다.
    readers: list[str] = []
    response_keys: list[str] = []
    for path in sorted(SRC_DIR.rglob("*.py")):
        relative = path.relative_to(SRC_DIR).as_posix()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Attribute) and node.attr == "order_types":
                readers.append(f"{relative}:{node.lineno}")
            if isinstance(node, ast.Constant) and node.value == "order_types":
                response_keys.append(relative)

    assert readers == []
    assert response_keys == ["adapters/upbit/exchange.py"]


# ── OrderLookup(D-094 B): 개별 주문 조회 결과 ──────────────────
# 찾았으면 (snapshot, None), 없으면 (None, "order_not_found" | "unnamed"). 이름 없는 404도
# "없음"이지만 5단계가 경고 이벤트(UNNAMED_NOT_FOUND)를 남기도록 구별한다. 어긋난 조합은
# 만들 때 ValueError다(ApiKeyInfo·OrderRequest와 같은 관례).

NOT_FOUND_KINDS = ("order_not_found", "unnamed")


def literal_values(annotation) -> set:
    """Literal[...] | None 같은 표기에서 Literal 값과 None을 모은다."""
    origin = typing.get_origin(annotation)
    if origin is typing.Literal:
        return set(typing.get_args(annotation))
    if annotation is type(None):
        return {None}
    if origin in (typing.Union, types.UnionType):
        values: set = set()
        for arg in typing.get_args(annotation):
            values |= literal_values(arg)
        return values
    raise AssertionError(f"Literal이 아닌 표기: {annotation!r}")


def test_order_lookup_is_a_frozen_slotted_dataclass():
    cls = models.OrderLookup

    assert dataclasses.is_dataclass(cls)
    assert cls.__dataclass_params__.frozen
    assert "__slots__" in cls.__dict__
    assert [f.name for f in dataclasses.fields(cls)] == ["snapshot", "not_found"]


def test_order_lookup_field_types():
    hints = typing.get_type_hints(models.OrderLookup)

    assert hints["snapshot"] == models.OrderSnapshot | None
    assert literal_values(hints["not_found"]) == {*NOT_FOUND_KINDS, None}


def test_order_lookup_with_a_snapshot_has_no_not_found():
    found = models.OrderLookup(snapshot=snapshot(), not_found=None)

    assert found.snapshot == snapshot()
    assert found.not_found is None


@pytest.mark.parametrize("kind", NOT_FOUND_KINDS)
def test_order_lookup_without_a_snapshot_says_which_not_found(kind):
    found = models.OrderLookup(snapshot=None, not_found=kind)

    assert found.snapshot is None
    assert found.not_found == kind


def test_the_two_kinds_of_not_found_are_different_values():
    named = models.OrderLookup(snapshot=None, not_found="order_not_found")
    unnamed = models.OrderLookup(snapshot=None, not_found="unnamed")

    assert named != unnamed
    assert named == models.OrderLookup(snapshot=None, not_found="order_not_found")


def test_order_lookup_needs_a_snapshot_or_a_not_found():
    with pytest.raises(ValueError):  # noqa: PT011 - 문구는 구현이 정한다
        models.OrderLookup(snapshot=None, not_found=None)


@pytest.mark.parametrize("kind", NOT_FOUND_KINDS)
def test_order_lookup_with_a_snapshot_cannot_also_be_not_found(kind):
    with pytest.raises(ValueError):  # noqa: PT011
        models.OrderLookup(snapshot=snapshot(), not_found=kind)


@pytest.mark.parametrize("kind", ["", "UNNAMED", "Order_Not_Found", "not_found", "404"])
def test_order_lookup_rejects_other_not_found_values(kind):
    with pytest.raises(ValueError):  # noqa: PT011
        models.OrderLookup(snapshot=None, not_found=kind)


def test_order_lookup_cannot_be_modified():
    found = models.OrderLookup(snapshot=None, not_found="unnamed")

    with pytest.raises(dataclasses.FrozenInstanceError):
        found.not_found = "order_not_found"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        found.snapshot = snapshot()  # type: ignore[misc]
