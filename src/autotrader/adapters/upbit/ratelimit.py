"""업비트 요청 한도 장치: 경로 표(한도 그룹·인증 여부), 한도의 절반, Remaining-Req, 429, 418.

- 그룹과 인증 여부는 경로별 고정 표로 고른다. 응답 헤더의 group 값은 표와 맞는지 확인하는 데만
  쓴다. 일괄 취소(DELETE /v1/orders/open)는 쓰지 않으므로(D-069) 표에 없다.
- 한도의 절반만 쓴다(INV-13): 그룹마다 최근 `절반`건의 송신 허가 시각(monotonic)을 기억하는
  슬라이딩 창이다. 길이 1초인 어느 구간에도 절반을 넘지 않으므로 거래소의 초 경계가 어디든
  한도를 넘지 않는다(정수 초 창 [k, k+1) 조건은 그 특수한 경우).
  초당 1건이 안 되는 그룹(order-cancel-all)은 앞 요청에서 최소 간격을 둔다.
- Remaining-Req는 sec만 읽는다(min은 폐기). sec=0이거나 429면 그 그룹만
  `max(floor(now)+1, now+1)`까지(최소 1초) 멈춘다.
- 418(D-078, D-088 제안): 모든 요청을 멈춘다. Retry-After가 있으면 그 시간,
  없으면 5·10·20·40·60분. 차단 중에 도착한 418(함께 나갔던 요청)은 단계를 올리지 않는다.
- 418 만기 뒤 반개방: 성공 응답을 받기 전까지는 처리 중인 확인 요청을 1건만 허용하고,
  그동안 다른 요청은 네트워크 없이 UpbitBlocked다. 확인 요청이 성공(2xx)이면 단계를 처음으로
  돌리고, 418이면 다음 단계로 차단하며, 그 밖의 결과(다른 오류, 타임아웃, 연결 오류, 취소)면
  확인 자리만 푼다. 차단 중에 도착한 성공은 단계를 돌리지 않는다.
- 시간은 Clock의 monotonic만 쓴다. PC 시계를 믿지 않는다.
- 418은 IP 단위이므로 시세·거래 어댑터가 RateLimiter 하나를 함께 쓴다.
근거: docs/05-integration/upbit-api.md 2·4·9장, docs/08-quality/invariants.md INV-13.
"""

import logging
import math
from collections import deque
from dataclasses import dataclass, field
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

# 업비트 API 연동 명세 2장의 경로별 (한도 그룹, 인증 필요). 표에 없는 경로는 보내지 않는다.
# 일괄 취소 DELETE /v1/orders/open은 쓰지 않는다(D-069). order-cancel-all 한도 값만 위에 남긴다.
_ROUTES: MappingProxyType[tuple[str, str], tuple[str, bool]] = MappingProxyType(
    {
        ("GET", "/v1/market/all"): ("market", False),
        **{("GET", f"/v1/candles/minutes/{unit}"): ("candles", False) for unit in _CANDLE_MINUTES},
        ("GET", "/v1/candles/days"): ("candles", False),
        ("GET", "/v1/ticker"): ("ticker", False),
        ("GET", "/v1/orderbook"): ("orderbook", False),
        ("GET", "/v1/orderbook/instruments"): ("orderbook", False),
        ("GET", "/v1/accounts"): ("default", True),
        ("GET", "/v1/orders/chance"): ("default", True),
        ("POST", "/v1/orders"): ("order", True),
        ("POST", "/v1/orders/test"): ("order-test", True),
        ("GET", "/v1/order"): ("default", True),
        ("GET", "/v1/orders/uuids"): ("default", True),
        ("GET", "/v1/orders/open"): ("default", True),
        ("GET", "/v1/orders/closed"): ("default", True),
        ("DELETE", "/v1/order"): ("default", True),
        ("GET", "/v1/api_keys"): ("default", True),
    }
)

FIRST_BLOCK_WAIT = 300.0  # 5분
MAX_STEP_WAIT = 3600.0  # 단계표의 상한 60분(Retry-After에는 적용하지 않는다)
_MAX_STEP_EXPONENT = 4  # 300 * 2**4 = 4800 > 60분. 그보다 큰 지수는 쓰지 않는다(오버플로 방지)
_MAX_SEC_DIGITS = 6  # Remaining-Req sec 값의 길이 상한. 더 길면 읽지 않는다
_PAUSE = 1.0  # 429·sec=0 멈춤의 최소 길이(초)
_WINDOW = 1.0  # 슬라이딩 창 길이(초)
_MIN_SLEEP = 1e-6  # 부동소수 반올림으로 대기가 0 이하로 계산될 때 쓰는 최소 대기


def _route(method: str, path: str) -> tuple[str, bool]:
    try:
        return _ROUTES[(method.upper(), path)]
    except KeyError:
        raise ValueError(f"경로 표에 없는 업비트 경로다: {method} {path}") from None


def group_for(method: str, path: str) -> str:
    """메서드·경로의 한도 그룹. 표에 없으면 ValueError."""
    return _route(method, path)[0]


def requires_auth(method: str, path: str) -> bool:
    """메서드·경로가 인증(JWT)을 요구하는지. 표에 없으면 ValueError."""
    return _route(method, path)[1]


def parse_remaining_req(value: str | None) -> tuple[str | None, int | None]:
    """`group=...; min=...; sec=...`에서 (group, sec)를 읽는다. 읽을 수 없는 값은 None.

    sec는 6자리 이하의 ASCII 숫자만 읽는다(아주 긴 값의 int 변환 오류를 막는다).
    """
    if not value:
        return None, None
    fields: dict[str, str] = {}
    for part in value.split(";"):
        key, separator, item = part.partition("=")
        if separator:
            fields.setdefault(key.strip().lower(), item.strip())
    group = fields.get("group") or None
    sec_text = fields.get("sec", "")
    readable = sec_text.isascii() and sec_text.isdigit() and len(sec_text) <= _MAX_SEC_DIGITS
    return group, int(sec_text) if readable else None


@dataclass
class _Bucket:
    """한 그룹의 슬라이딩 창(또는 최소 간격)."""

    allowance: int  # 길이 1초인 구간 하나에 보낼 수 있는 수
    interval: float  # 0이면 1초 슬라이딩 창, 아니면 요청 사이 최소 간격(초)
    sent: deque[float] = field(default_factory=deque)  # 최근 allowance건의 송신 허가 시각
    paused_until: float = -math.inf

    def wait_time(self, now: float) -> float:
        if now < self.paused_until:
            return self.paused_until - now
        if not self.sent:
            return 0.0
        if self.interval:
            earliest = self.sent[-1] + self.interval
        elif len(self.sent) < self.allowance:
            return 0.0
        else:
            # 가장 오래된 송신이 창을 벗어나야 한 자리가 빈다: oldest <= now - 1초.
            oldest = self.sent[0]
            if oldest <= now - _WINDOW:
                return 0.0
            earliest = oldest + _WINDOW
        if earliest <= now:
            return 0.0 if self.interval else _MIN_SLEEP
        return earliest - now

    def record(self, now: float) -> None:
        self.sent.append(now)
        while len(self.sent) > self.allowance:
            self.sent.popleft()


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
        # 418 차단 만기. 만기가 지나도 성공 응답을 받기 전까지는 남겨 두고 반개방으로 본다.
        self._blocked_until: float | None = None
        self._block_steps = 0
        self._probe_in_flight = False

    def _bucket(self, group: str) -> _Bucket:
        try:
            return self._buckets[group]
        except KeyError:
            raise ValueError(f"모르는 한도 그룹이다: {group}") from None

    async def acquire(self, group: str) -> None:
        """그 그룹의 최근 1초 몫이 남을 때까지 기다린 뒤 한 건을 센다."""
        bucket = self._bucket(group)
        while True:
            now = self._clock.monotonic()
            wait = bucket.wait_time(now)
            if wait <= 0:
                bucket.record(now)
                return
            await self._clock.sleep(wait)

    def _pause_group(self, group: str) -> None:
        """그 그룹을 다음 초 경계까지, 그리고 적어도 1초 멈춘다."""
        bucket = self._bucket(group)
        now = self._clock.monotonic()
        resume = max(math.floor(now) + 1.0, now + _PAUSE)
        bucket.paused_until = max(bucket.paused_until, resume)

    def observe(self, group: str, remaining_req: str | None) -> None:
        """응답의 Remaining-Req를 반영한다. sec=0이면 그 그룹을 멈춘다(최소 1초)."""
        header_group, sec = parse_remaining_req(remaining_req)
        if header_group is not None and header_group != group:
            logger.warning(
                "Remaining-Req의 group이 경로 표와 다르다: 표=%s, 헤더=%s", group, header_group
            )
        if sec == 0:
            self._pause_group(group)

    def on_rate_limited(self, group: str) -> None:
        """429를 받았다. 그 그룹만 멈춘다(최소 1초)."""
        self._pause_group(group)

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
            exponent = min(self._block_steps, _MAX_STEP_EXPONENT)
            wait = min(FIRST_BLOCK_WAIT * 2**exponent, MAX_STEP_WAIT)
        else:
            wait = retry_after  # 거래소 지시가 우선이므로 상한을 두지 않는다
        self._block_steps = min(self._block_steps + 1, _MAX_STEP_EXPONENT)
        self._blocked_until = now + wait
        logger.warning("업비트 418 차단: %.0f초 동안 모든 요청을 멈춘다", wait)

    def blocked_until(self) -> float | None:
        """차단이 풀리는 monotonic 시각. 차단 중이 아니면 None."""
        if self._blocked_until is None or self._clock.monotonic() >= self._blocked_until:
            return None
        return self._blocked_until

    def check_not_blocked(self) -> None:
        """차단 중이거나 만기 뒤 확인 요청이 처리 중이면 네트워크 없이 UpbitBlocked를 던진다."""
        until = self.blocked_until()
        if until is not None:
            raise UpbitBlocked(
                http_status=418,
                error_name=None,
                message="418 차단 중이라 요청을 보내지 않았다",
                retry_after=until - self._clock.monotonic(),
                raw_body="",
            )
        if self._probe_in_flight:
            raise UpbitBlocked(
                http_status=418,
                error_name=None,
                message="418 차단이 풀렸는지 확인하는 요청이 처리 중이라 보내지 않았다",
                retry_after=None,
                raw_body="",
            )

    def start_send(self) -> bool:
        """전송 직전에 부른다. 보내도 되면 이 요청이 확인 요청인지 돌려준다.

        차단 중이거나 다른 확인 요청이 처리 중이면 UpbitBlocked. 418 만기 뒤 아직 성공 응답이
        없으면 이 요청을 확인 요청으로 잡고 True다. 결과와 상관없이 end_send를 꼭 부른다
        (try/finally).
        """
        self.check_not_blocked()
        if self._blocked_until is None:
            return False
        self._probe_in_flight = True
        return True

    def end_send(self, probe: bool) -> None:
        """start_send로 시작한 전송이 끝났다(성공·오류·타임아웃·취소 모두). 확인 자리를 푼다."""
        if probe:
            self._probe_in_flight = False

    def on_success_after_block(self) -> None:
        """성공 응답을 받았다. 차단 기록을 지우고 418 대기 단계를 처음(5분)으로 돌린다.

        차단 중에 도착한 성공(차단 전에 나갔던 요청의 응답)은 차단이 풀렸다는 뜻이 아니므로
        무시한다.
        """
        if self.blocked_until() is None:
            self._block_steps = 0
            self._blocked_until = None
