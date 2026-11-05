"""업비트 와이어 가짜의 주문 상태 모형(docs/08-quality/fakes-spec.md 2.4절).

체결 모형:
- 예약(FillPlan)이 있으면 그것을 쓴다. 없으면 가짜 호가로 계산한다.
- 최유리 FOK 매수: 최우선 매도호가 한 단계에서 총액 전부를 살 수 있을 때만 체결.
- 시장가 매수: 매도호가를 위에서부터 소진. 남은 금액이 다음 단계에서 최소 수량(1e-8)도
  못 사면 다 쓴 것으로 본다(done). 호가가 바닥나면 cancel(체결분 있음).
- 시장가 매도: 매수호가를 위에서부터 소진. 수량이 남으면 cancel.
- 지정가: 바로 맞는 호가만 체결하고 나머지는 wait(ioc는 cancel, fok는 전량 아니면 cancel,
  post_only는 바로 맞으면 cancel).
- 금액·수량은 Decimal. 체결 금액은 가격×수량 그대로, 수수료는 체결 금액×수수료율 그대로다.
"""

import uuid as uuid_module
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import ROUND_DOWN, Decimal
from typing import Any

from fakes.upbit_json import fmt_decimal

KST = timezone(timedelta(hours=9))
VOLUME_STEP = Decimal("0.00000001")
ZERO = Decimal(0)
OPEN_STATES = ("wait", "watch")
CLOSED_STATES = ("done", "cancel")
OPTIONAL_FIELDS = ("time_in_force", "identifier", "smp_type")


def kst_text(moment: datetime, *, micro: bool = False) -> str:
    """거래 API 시각 표기. 주문은 초 단위, 체결은 마이크로초(문서 예시)."""
    local = moment.astimezone(KST)
    if micro:
        return local.isoformat(timespec="microseconds")
    return local.replace(microsecond=0).isoformat()


def floor_volume(value: Decimal) -> Decimal:
    return value.quantize(VOLUME_STEP, rounding=ROUND_DOWN)


@dataclass(frozen=True)
class Level:
    """호가 한 단계(한쪽 방향)."""

    price: Decimal
    size: Decimal


@dataclass(frozen=True)
class FillPlan:
    """테스트가 예약한 체결 결과."""

    ratio: Decimal
    price: Decimal | None = None
    trades: int = 1
    state: str | None = None


@dataclass(frozen=True)
class FakeTrade:
    uuid: str
    price: Decimal
    volume: Decimal
    created_at: datetime

    @property
    def funds(self) -> Decimal:
        return self.price * self.volume


@dataclass
class FakeOrder:
    uuid: str
    identifier: str | None
    market: str
    side: str
    ord_type: str
    price_text: str | None
    volume_text: str | None
    time_in_force: str | None
    smp_type: str | None
    fee_rate: Decimal
    created_at: datetime
    state: str = "wait"
    trades: list[FakeTrade] = field(default_factory=list)
    seq: int = 0

    @property
    def price(self) -> Decimal | None:
        return None if self.price_text is None else Decimal(self.price_text)

    @property
    def volume(self) -> Decimal | None:
        return None if self.volume_text is None else Decimal(self.volume_text)

    @property
    def price_based(self) -> bool:
        """매수 총액으로 정하는 주문(시장가 매수, 최유리 매수)."""
        return self.side == "bid" and self.ord_type in ("price", "best")

    @property
    def is_open(self) -> bool:
        return self.state in OPEN_STATES

    def snapshot(
        self,
        *,
        at_creation: bool = False,
        include_trades: bool = False,
        omit_optional: bool = False,
    ) -> dict[str, Any]:
        """주문 객체(fakes-spec 2.2절). at_creation이면 접수 직후 모습(wait, 체결 0)."""
        trades = [] if at_creation else self.trades
        state = "wait" if at_creation else self.state
        is_open = state in OPEN_STATES
        executed = sum((t.volume for t in trades), ZERO)
        funds = sum((t.funds for t in trades), ZERO)
        paid_fee = funds * self.fee_rate
        price, volume = self.price, self.volume
        remaining_volume = None if volume is None else volume - executed

        if self.side == "bid":
            if self.price_based:
                assert price is not None
                reserved_fee = price * self.fee_rate
                remaining_funds = price - funds
            else:
                assert price is not None and volume is not None and remaining_volume is not None
                reserved_fee = price * volume * self.fee_rate
                remaining_funds = price * remaining_volume
            remaining_fee = remaining_funds * self.fee_rate if is_open else ZERO
            locked = remaining_funds + remaining_fee if is_open else ZERO
        else:
            reserved_fee = ZERO
            remaining_fee = ZERO
            locked = (remaining_volume or ZERO) if is_open else ZERO

        data: dict[str, Any] = {
            "uuid": self.uuid,
            "side": self.side,
            "ord_type": self.ord_type,
            "price": self.price_text,
            "state": state,
            "market": self.market,
            "created_at": kst_text(self.created_at),
            "volume": self.volume_text,
            "remaining_volume": None
            if remaining_volume is None
            else fmt_decimal(remaining_volume),
            "reserved_fee": fmt_decimal(reserved_fee),
            "remaining_fee": fmt_decimal(remaining_fee),
            "paid_fee": fmt_decimal(paid_fee),
            "locked": fmt_decimal(locked),
            "executed_volume": fmt_decimal(executed),
            "prevented_volume": "0",
            "prevented_locked": "0",
            "trades_count": len(trades),
        }
        if self.time_in_force is not None:
            data["time_in_force"] = self.time_in_force
        if self.identifier is not None:
            data["identifier"] = self.identifier
        if self.smp_type is not None:
            data["smp_type"] = self.smp_type
        if omit_optional:
            for key in OPTIONAL_FIELDS:
                data.pop(key, None)
        if include_trades:
            data["trades"] = [
                {
                    "market": self.market,
                    "uuid": t.uuid,
                    "price": fmt_decimal(t.price),
                    "volume": fmt_decimal(t.volume),
                    "funds": fmt_decimal(t.funds),
                    "trend": "up" if self.side == "bid" else "down",
                    "created_at": kst_text(t.created_at, micro=True),
                    "side": self.side,
                }
                for t in trades
            ]
        return data


Fills = list[tuple[Decimal, Decimal]]  # (가격, 수량)


def _walk_funds(levels: Sequence[Level], total: Decimal) -> tuple[Fills, bool]:
    remaining = total
    fills: Fills = []
    for level in levels:
        if remaining <= 0:
            break
        if level.size <= 0:
            continue
        affordable = floor_volume(remaining / level.price)
        if affordable <= 0:
            return fills, True  # 남은 금액으로는 최소 수량도 못 산다 → 다 쓴 것
        volume = min(level.size, affordable)
        fills.append((level.price, volume))
        remaining -= level.price * volume
    return fills, remaining <= 0


def _walk_volume(levels: Sequence[Level], total: Decimal) -> tuple[Fills, bool]:
    remaining = total
    fills: Fills = []
    for level in levels:
        if remaining <= 0:
            break
        if level.size <= 0:
            continue
        volume = min(level.size, remaining)
        fills.append((level.price, volume))
        remaining -= volume
    return fills, remaining <= 0


def match_book(order: FakeOrder, asks: Sequence[Level], bids: Sequence[Level]) -> tuple[Fills, str]:
    """예약이 없을 때 호가로 체결을 계산한다. (체결 목록, 끝 상태)."""
    levels = asks if order.side == "bid" else bids
    price, volume, tif = order.price, order.volume, order.time_in_force

    if order.ord_type == "price":
        assert price is not None
        fills, complete = _walk_funds(levels, price)
        return fills, "done" if complete else "cancel"
    if order.ord_type == "market":
        assert volume is not None
        fills, complete = _walk_volume(levels, volume)
        return fills, "done" if complete else "cancel"
    if order.ord_type == "best":
        top = list(levels[:1])
        if order.side == "bid":
            assert price is not None
            if tif == "fok" and not (top and top[0].price * top[0].size >= price):
                return [], "cancel"
            fills, complete = _walk_funds(top, price)
        else:
            assert volume is not None
            if tif == "fok" and not (top and top[0].size >= volume):
                return [], "cancel"
            fills, complete = _walk_volume(top, volume)
        return fills, "done" if complete else "cancel"

    # 지정가
    assert price is not None and volume is not None
    eligible: list[Level] = []
    for level in levels:
        crosses = level.price <= price if order.side == "bid" else level.price >= price
        if not crosses:
            break
        eligible.append(level)
    if tif == "post_only":
        return [], "cancel" if eligible else "wait"
    if tif == "fok" and sum((lv.size for lv in eligible), ZERO) < volume:
        return [], "cancel"
    fills, complete = _walk_volume(eligible, volume)
    if complete:
        return fills, "done"
    return fills, "cancel" if tif in ("ioc", "fok") else "wait"


def plan_fills(order: FakeOrder, plan: FillPlan, best_price: Decimal | None) -> tuple[Fills, str]:
    """예약대로 체결한다. 가격은 예약 값 → 지정가 → 최우선 호가 순으로 정한다."""
    price = plan.price
    if price is None and order.ord_type == "limit":
        price = order.price
    if price is None:
        price = best_price
    state = plan.state or ("done" if plan.ratio >= 1 else "cancel")
    if price is None:
        if plan.ratio == 0:
            return [], state
        raise ValueError("예약 체결 가격을 정할 수 없다(호가가 비어 있다). fill(price=...)를 준다")
    if order.price_based:
        assert order.price is not None
        total_volume = floor_volume(order.price * plan.ratio / price)
    else:
        assert order.volume is not None
        total_volume = floor_volume(order.volume * plan.ratio)
    if total_volume <= 0:
        return [], state
    count = max(1, plan.trades)
    per = floor_volume(total_volume / count)
    if per <= 0:
        return [(price, total_volume)], state
    volumes = [per] * (count - 1) + [total_volume - per * (count - 1)]
    return [(price, v) for v in volumes], state


def apply_fills(
    order: FakeOrder,
    fills: Fills,
    state: str,
    *,
    now: datetime,
    new_uuid: Callable[[], str],
) -> None:
    order.trades = [
        FakeTrade(uuid=new_uuid(), price=p, volume=v, created_at=now + timedelta(microseconds=i))
        for i, (p, v) in enumerate(fills)
    ]
    order.state = state


def seeded_uuid_factory(rng: Any) -> Callable[[], str]:
    """시드로 정해지는 UUID4 문자열."""

    def make() -> str:
        return str(uuid_module.UUID(int=rng.getrandbits(128), version=4))

    return make
