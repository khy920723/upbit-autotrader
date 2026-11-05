"""업비트 요청 한도 장치: 경로별 한도 그룹, 한도의 절반, Remaining-Req, 429, 418.

- 그룹은 경로별 고정 표로 고른다. 응답 헤더의 group 값은 표와 맞는지 확인하는 데만 쓴다.
- 한도의 절반만 쓴다(INV-13): 정수 초 창 [k, k+1)마다 요청 수를 세는 고정 창 계수기다.
  창이 거래소의 초 경계와 어긋나도 임의의 1초 구간에는 많아야 두 창이 걸치므로
  실제 한도를 넘지 않는다.
  초당 1건이 안 되는 그룹(order-cancel-all)은 앞 요청에서 최소 간격을 둔다.
- Remaining-Req는 sec만 읽는다(min은 폐기). sec=0이거나 429면 그 그룹만 다음 초 경계까지 멈춘다.
- 418(D-078, D-088 제안): 모든 요청을 멈춘다. Retry-After가 있으면 그 시간,
  없으면 5·10·20·40·60분. 차단 중에 도착한 418(함께 나갔던 요청)은 단계를 올리지 않는다.
  성공 응답이면 단계를 처음으로 돌린다.
- 시간은 Clock의 monotonic만 쓴다. PC 시계를 믿지 않는다.
근거: docs/05-integration/upbit-api.md 2·4·9장, docs/08-quality/invariants.md INV-13.
"""

import logging
import math
from dataclasses import dataclass
from fractions import Fraction
from types import MappingProxyType

from autotrader.core.clock import Clock
from autotrader.core.errors import UpbitBlocked

logger = logging.getLogger(__name__)

# 업비트 요청 한도(초당 요청 수). order-cancel-all은 2초에 1회다. 앱은 이 값의 절반만 쓴다.
# 공식 한도표는 캔들 그룹을 candle로 적지만 실제 헤더와 공식 예제는 candles다.
# trade는 /v1/trades/ticks용이고 지금은 쓰지 않는다(group_for 표에 없음).
GROUP_LIMITS: MappingProxyType[str, int | Fraction] = MappingProxyType(
    {
        "market": 10,
        "candles": 10,
        "ticker": 10,
        "orderbook": 10,
        "trade": 10,
        "default": 30,
        "order": 12,
        "order-test": 8,
        "order-cancel-all": Fraction(1, 2),
    }
)

_CANDLE_MINUTES = (1, 3, 5, 10, 15, 30, 60, 240)

# 업비트 API 연동 명세 2장의 경로별 한도 그룹. 표에 없는 경로는 보내지 않는다.
_PATH_GROUPS: MappingProxyType[tuple[str, str], str] = MappingProxyType(
    {
        ("GET", "/v1/market/all"): "market",
        **{("GET", f"/v1/candles/minutes/{unit}"): "candles" for unit in _CANDLE_MINUTES},
        ("GET", "/v1/candles/days"): "candles",
        ("GET", "/v1/ticker"): "ticker",
        ("GET", "/v1/orderbook"): "orderbook",
        ("GET", "/v1/orderbook/instruments"): "orderbook",
        ("GET", "/v1/accounts"): "default",
        ("GET", "/v1/orders/chance"): "default",
        ("POST", "/v1/orders"): "order",
        ("POST", "/v1/orders/test"): "order-test",
        ("GET", "/v1/order"): "default",
        ("GET", "/v1/orders/uuids"): "default",
        ("GET", "/v1/orders/open"): "default",
        ("GET", "/v1/orders/closed"): "default",
        ("DELETE", "/v1/order"): "default",
        ("DELETE", "/v1/orders/open"): "order-cancel-all",
        ("GET", "/v1/api_keys"): "default",
    }
)

FIRST_BLOCK_WAIT = 300.0  # 5분
MAX_STEP_WAIT = 3600.0  # 단계표의 상한 60분(Retry-After에는 적용하지 않는다)


def group_for(method: str, path: str) -> str:
    """메서드·경로의 한도 그룹. 표에 없으면 ValueError."""
    try:
        return _PATH_GROUPS[(method.upper(), path)]
    except KeyError:
        raise ValueError(f"한도 그룹 표에 없는 업비트 경로다: {method} {path}") from None


def parse_remaining_req(value: str | None) -> tuple[str | None, int | None]:
    """`group=...; min=...; sec=...`에서 (group, sec)를 읽는다. 읽을 수 없는 값은 None."""
    if not value:
        return None, None
    fields: dict[str, str] = {}
    for part in value.split(";"):
        key, separator, item = part.partition("=")
        if separator:
            fields.setdefault(key.strip().lower(), item.strip())
    group = fields.get("group") or None
    sec_text = fields.get("sec", "")
    sec = int(sec_text) if sec_text.isascii() and sec_text.isdigit() else None
    return group, sec


@dataclass
class _Bucket:
    """한 그룹의 고정 창 계수기(또는 최소 간격)."""

    allowance: int  # 창 하나에 보낼 수 있는 수
    interval: float  # 0이면 1초 창, 아니면 요청 사이 최소 간격(초)
    window: int | None = None
    count: int = 0
    last_sent: float | None = None
    paused_until: float = -math.inf

    def wait_time(self, now: float) -> float:
        if now < self.paused_until:
            return self.paused_until - now
        if self.interval:
            if self.last_sent is None:
                return 0.0
            return max(0.0, self.last_sent + self.interval - now)
        window = math.floor(now)
        if window != self.window or self.count < self.allowance:
            return 0.0
        return (window + 1) - now

    def record(self, now: float) -> None:
        self.last_sent = now
        window = math.floor(now)
        if window != self.window:
            self.window = window
            self.count = 0
        self.count += 1


def _make_bucket(limit: int | Fraction) -> _Bucket:
    half = Fraction(limit) / 2
    if half >= 1:
        return _Bucket(allowance=math.floor(half), interval=0.0)
    return _Bucket(allowance=1, interval=float(1 / half))


class RateLimiter:
    """그룹별 요청 한도와 418 차단을 관리한다. 한 이벤트 루프에서만 쓴다."""

    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._buckets = {group: _make_bucket(limit) for group, limit in GROUP_LIMITS.items()}
        self._blocked_until: float | None = None
        self._block_steps = 0

    def _bucket(self, group: str) -> _Bucket:
        try:
            return self._buckets[group]
        except KeyError:
            raise ValueError(f"모르는 한도 그룹이다: {group}") from None

    async def acquire(self, group: str) -> None:
        """그 그룹의 이번 창 몫이 남을 때까지 기다린 뒤 한 건을 센다."""
        bucket = self._bucket(group)
        while True:
            now = self._clock.monotonic()
            wait = bucket.wait_time(now)
            if wait <= 0:
                bucket.record(now)
                return
            await self._clock.sleep(wait)

    def _pause_until_next_second(self, group: str) -> None:
        bucket = self._bucket(group)
        boundary = math.floor(self._clock.monotonic()) + 1.0
        bucket.paused_until = max(bucket.paused_until, boundary)

    def observe(self, group: str, remaining_req: str | None) -> None:
        """응답의 Remaining-Req를 반영한다. sec=0이면 그 그룹을 다음 초 경계까지 멈춘다."""
        header_group, sec = parse_remaining_req(remaining_req)
        if header_group is not None and header_group != group:
            logger.warning(
                "Remaining-Req의 group이 경로 표와 다르다: 표=%s, 헤더=%s", group, header_group
            )
        if sec == 0:
            self._pause_until_next_second(group)

    def on_rate_limited(self, group: str) -> None:
        """429를 받았다. 그 그룹만 다음 초 경계까지 멈춘다."""
        self._pause_until_next_second(group)

    def on_blocked(self, retry_after: float | None) -> None:
        """418을 받았다. 모든 요청을 차단 시간 동안 멈춘다(D-078, D-088 제안)."""
        if retry_after is not None and not (math.isfinite(retry_after) and retry_after > 0):
            retry_after = None
        now = self._clock.monotonic()
        if self._blocked_until is not None and now < self._blocked_until:
            # 차단 전에 함께 나갔던 요청의 418이다. 단계는 그대로 두고 더 늦은 만기만 따른다.
            if retry_after is not None:
                self._blocked_until = max(self._blocked_until, now + retry_after)
            return
        if retry_after is None:
            wait = min(FIRST_BLOCK_WAIT * 2**self._block_steps, MAX_STEP_WAIT)
        else:
            wait = retry_after  # 거래소 지시가 우선이므로 상한을 두지 않는다
        self._block_steps += 1
        self._blocked_until = now + wait
        logger.warning("업비트 418 차단: %.0f초 동안 모든 요청을 멈춘다", wait)

    def blocked_until(self) -> float | None:
        """차단이 풀리는 monotonic 시각. 차단 중이 아니면 None."""
        if self._blocked_until is None or self._clock.monotonic() >= self._blocked_until:
            return None
        return self._blocked_until

    def check_not_blocked(self) -> None:
        """차단 중이면 네트워크 없이 UpbitBlocked를 던진다."""
        until = self.blocked_until()
        if until is None:
            return
        raise UpbitBlocked(
            http_status=418,
            error_name=None,
            message="418 차단 중이라 요청을 보내지 않았다",
            retry_after=until - self._clock.monotonic(),
            raw_body="",
        )

    def on_success_after_block(self) -> None:
        """성공 응답을 받았다. 418 대기 단계를 처음(5분)으로 돌린다.

        차단 중에 도착한 성공(차단 전에 나갔던 요청의 응답)은 차단이 풀렸다는 뜻이 아니므로
        무시한다.
        """
        if self.blocked_until() is None:
            self._block_steps = 0
