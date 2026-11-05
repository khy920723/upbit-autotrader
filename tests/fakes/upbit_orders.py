"""업비트 와이어 가짜의 주문 상태 모형(docs/08-quality/fakes-spec.md 2.4절).

체결 모형(끝 상태는 `match_book` 끝의 한 곳에서 정한다):
- 예약(FillPlan)이 있으면 그것을 쓴다. 없으면 가짜 호가로 계산한다.
- 최유리 FOK 매수: 최우선 매도호가 한 단계의 잔량 × 가격이 총액 이상일 때만 체결하고, 체결되면
  done이다(살 수 없는 잔돈이 남아도. fakes-spec 2.4 "체결되면 done"). 아니면 cancel(체결 0).
- 시장가 매수: 매도호가를 위에서부터 소진. 돈을 다 쓰면 done, 최소 수량(1e-8)도 못 사는 잔돈이
  남거나 호가가 바닥나면 호가 깊이와 상관없이 cancel(체결분 있음, TS-64, 매매 로직 명세 10장).
- 시장가 매도: 매수호가를 위에서부터 소진. 수량을 다 팔면 done, 남으면 cancel.
- 지정가: 바로 맞는 호가만 체결하고 나머지는 wait(ioc는 cancel, fok는 전량 아니면 cancel,
  post_only는 바로 맞으면 cancel).
- 체결이 0건이면 done이 아니다(지정가는 wait, 나머지는 cancel).
- 금액·수량은 Decimal이고 계산은 지역 Context(DECIMAL_CONTEXT)로 한다. 체결 금액은 가격×수량
  그대로, 수수료는 체결 금액×수수료율 그대로다.
"""

import uuid as uuid_module
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import ROUND_DOWN, Decimal, localcontext
from typing import Any

from fakes.upbit_json import DECIMAL_CONTEXT, fmt_decimal

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
    return value.quantize(VOLUME_STEP, rounding=ROUND_DOWN, context=DECIMAL_CONTEXT)


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
        return DECIMAL_CONTEXT.multiply(self.price, self.volume)


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

    @property
    def executed_volume(self) -> Decimal:
        with localcontext(DECIMAL_CONTEXT):
            return sum((t.volume for t in self.trades), ZERO)

    def snapshot(
        self,
        *,
        at_creation: bool = False,
        include_trades: bool = False,
        omit_optional: bool = False,
    ) -> dict[str, Any]:
        """주문 객체(fakes-spec 2.2절). at_creation이면 접수 직후 모습(wait, 체결 0).

        값이 없는 price·volume·remaining_volume은 키를 뺀다(문서 예시와 같다).
        """
        with localcontext(DECIMAL_CONTEXT):
            data = self._snapshot(at_creation=at_creation)
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
                for t in ([] if at_creation else self.trades)
            ]
        return data

    def _snapshot(self, *, at_creation: bool) -> dict[str, Any]:
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
                assert price is not None
                assert volume is not None
                assert remaining_volume is not None
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
            "remaining_volume": None if remaining_volume is None else fmt_decimal(remaining_volume),
            "reserved_fee": fmt_decimal(reserved_fee),
            "remaining_fee": fmt_decimal(remaining_fee),
            "paid_fee": fmt_decimal(paid_fee),
            "locked": fmt_decimal(locked),
            "executed_volume": fmt_decimal(executed),
            "prevented_volume": "0",
            "prevented_locked": "0",
            "trades_count": len(trades),
            "time_in_force": self.time_in_force,
            "identifier": self.identifier,
            "smp_type": self.smp_type,
        }
        return {key: value for key, value in data.items() if value is not None}


Fills = list[tuple[Decimal, Decimal]]  # (가격, 수량)


def _walk_funds(levels: Sequence[Level], total: Decimal) -> tuple[Fills, Decimal]:
    """총액으로 호가를 위에서부터 산다. (체결 목록, 남은 금액)."""
    remaining = total
    fills: Fills = []
    for level in levels:
        if remaining <= 0:
            break
        if level.size <= 0:
            continue
        affordable = floor_volume(remaining / level.price)
        if affordable <= 0:
            break  # 잔돈: 매도호가는 위로 갈수록 비싸므로 다음 단계에서도 못 산다
        volume = min(level.size, affordable)
        fills.append((level.price, volume))
        remaining -= level.price * volume
    return fills, remaining


def _walk_volume(levels: Sequence[Level], total: Decimal) -> tuple[Fills, Decimal]:
    """수량만큼 호가를 위에서부터 소진한다. (체결 목록, 남은 수량)."""
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
    return fills, remaining


def match_book(order: FakeOrder, asks: Sequence[Level], bids: Sequence[Level]) -> tuple[Fills, str]:
    """예약이 없을 때 호가로 체결을 계산한다. (체결 목록, 끝 상태)."""
    with localcontext(DECIMAL_CONTEXT):
        fills, left, unfilled = _match(order, asks, bids)
    # 끝 상태는 여기 한 곳에서 정한다: 다 채웠고 체결이 있으면 done, 아니면 unfilled.
    return fills, "done" if fills and left <= 0 else unfilled


def _match(
    order: FakeOrder, asks: Sequence[Level], bids: Sequence[Level]
) -> tuple[Fills, Decimal, str]:
    """(체결 목록, 못 채운 금액·수량, 다 못 채웠을 때의 끝 상태)."""
    levels = asks if order.side == "bid" else bids
    price, volume, tif = order.price, order.volume, order.time_in_force

    if order.ord_type == "price":
        assert price is not None
        fills, left = _walk_funds(levels, price)
        return fills, left, "cancel"
    if order.ord_type == "market":
        assert volume is not None
        fills, left = _walk_volume(levels, volume)
        return fills, left, "cancel"
    if order.ord_type == "best":
        top = list(levels[:1])
        if order.side == "bid":
            assert price is not None
            if tif != "fok":
                fills, left = _walk_funds(top, price)
                return fills, left, "cancel"
            if not (top and top[0].price * top[0].size >= price):
                return [], price, "cancel"
            # FOK가 사전 검사를 통과하면 전량 체결로 본다(못 사는 잔돈은 남은 금액으로 치지 않는다).
            fills, _ = _walk_funds(top, price)
            return fills, ZERO, "cancel"
        assert volume is not None
        if tif == "fok" and not (top and top[0].size >= volume):
            return [], volume, "cancel"
        fills, left = _walk_volume(top, volume)
        return fills, left, "cancel"

    # 지정가
    assert price is not None
    assert volume is not None
    eligible: list[Level] = []
    for level in levels:
        crosses = level.price <= price if order.side == "bid" else level.price >= price
        if not crosses:
            break
        eligible.append(level)
    if tif == "post_only":
        return [], volume, "cancel" if eligible else "wait"
    if tif == "fok" and sum((lv.size for lv in eligible), ZERO) < volume:
        return [], volume, "cancel"
    fills, left = _walk_volume(eligible, volume)
    return fills, left, "cancel" if tif in ("ioc", "fok") else "wait"


def plan_fills(
    order: FakeOrder,
    plan: FillPlan,
    best_price: Decimal | None,
    *,
    partial_state: str = "cancel",
) -> tuple[Fills, str]:
    """예약대로 더할 체결을 정한다. 가격은 예약 값 → 지정가 → 최우선 호가 순으로 정한다.

    ratio는 주문 전체 대비 누적 체결 비율이다(이미 체결된 양은 빼고 더한다). 끝 상태는 예약한
    state, 없으면 ratio ≥ 1이고 체결이 있으면 done, 아니면 partial_state(새 주문은 cancel,
    대기 중인 주문은 그대로)다. 가격을 정할 수 없으면 ValueError.
    """
    with localcontext(DECIMAL_CONTEXT):
        price = plan.price
        if price is None and order.ord_type == "limit":
            price = order.price
        if price is None:
            price = best_price
        if order.price_based:
            assert order.price is not None
            if plan.ratio == 0:
                target = ZERO
            elif price is None:
                raise ValueError(_NO_PRICE)
            else:
                target = floor_volume(order.price * plan.ratio / price)
        else:
            assert order.volume is not None
            target = floor_volume(order.volume * plan.ratio)
        more = target - order.executed_volume
        if more < 0:
            raise ValueError(f"이미 체결된 양({order.executed_volume})보다 적게 예약했다")
        if plan.state is not None:
            state = plan.state
        elif plan.ratio >= 1 and (order.trades or more > 0):
            state = "done"
        else:
            state = partial_state
        if more == 0:
            return [], state
        if price is None:
            raise ValueError(_NO_PRICE)
        count = max(1, plan.trades)
        per = floor_volume(more / count)
        if per <= 0:
            return [(price, more)], state
        volumes = [per] * (count - 1) + [more - per * (count - 1)]
        return [(price, v) for v in volumes], state


_NO_PRICE = "예약 체결 가격을 정할 수 없다(호가가 비어 있다). fill(price=...)를 준다"


def apply_fills(
    order: FakeOrder,
    fills: Fills,
    state: str,
    *,
    now: datetime,
    new_uuid: Callable[[], str],
) -> None:
    """체결을 주문에 더하고 상태를 바꾼다(이미 있는 체결은 그대로 둔다)."""
    order.trades.extend(
        FakeTrade(uuid=new_uuid(), price=p, volume=v, created_at=now + timedelta(microseconds=i))
        for i, (p, v) in enumerate(fills)
    )
    order.state = state


def seeded_uuid_factory(rng: Any) -> Callable[[], str]:
    """시드로 정해지는 UUID4 문자열."""

    def make() -> str:
        return str(uuid_module.UUID(int=rng.getrandbits(128), version=4))

    return make
