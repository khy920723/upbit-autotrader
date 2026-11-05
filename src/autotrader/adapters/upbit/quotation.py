"""업비트 시세 어댑터(QuotationApi 구현): 공개 REST, 키 없음, IP 단위 한도.

- list_markets: `/v1/market/all?is_details=true`의 KRW 마켓만. 경고는 `market_event`의
  `warning`·`caution`만 읽는다(폐기된 `market_warning`은 읽지 않는다, TS-102).
- get_candles: 요청당 최대 200개, 오래된 것부터 돌려준다.
  거래가 없던 구간은 캔들이 없다(채우지 않는다).
- get_tickers·get_tick_sizes: 묶은 요청에 없는 마켓이 하나라도 있으면 전체가 404다. 그때는
  마켓마다 1건씩 다시 부르고 없는 마켓은 뺀다(fakes-spec 2.8절, TS-104). 404가 아닌 오류는 그대로.
- server_time: 응답 Date 헤더(거래소 시각). PC 시계는 쓰지 않는다.
- 자동 재시도는 없다. 요청 한도는 UpbitHttp(RateLimiter)가 지킨다.
근거: docs/05-integration/upbit-api.md 2장, docs/06-architecture/system-architecture.md 6장.
"""

import logging
import re
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, TypeVar

from autotrader.adapters.upbit import convert
from autotrader.adapters.upbit.http import UpbitHttp, UpbitResponse
from autotrader.core.errors import UpbitNotFound, UpbitServerError
from autotrader.core.models import Candle, MarketInfo, Orderbook, OrderbookUnit, Ticker
from autotrader.core.ports import CandleUnit

logger = logging.getLogger(__name__)

T = TypeVar("T")

MAX_CANDLES = 200
CANDLE_PATHS: dict[str, str] = {
    **{f"m{n}": f"/v1/candles/minutes/{n}" for n in (1, 3, 5, 10, 15, 30, 60, 240)},
    "d1": "/v1/candles/days",
}
# 서버 시각을 잴 때 부르는 가벼운 공개 요청(응답이 작다). 문서에 정한 경로는 없다.
SERVER_TIME_MARKET = "KRW-BTC"

_MARKET = re.compile(r"[A-Z0-9]+-[A-Z0-9]+")


def _check_markets(markets: Sequence[str]) -> list[str]:
    """마켓 코드 목록을 순서대로, 중복 없이. 형식이 다르면 ValueError."""
    if isinstance(markets, str):
        raise TypeError("markets는 마켓 코드의 목록이다(문자열 하나가 아니다)")
    unique = list(dict.fromkeys(markets))
    for market in unique:
        if not isinstance(market, str) or _MARKET.fullmatch(market) is None:
            raise ValueError(f"마켓 코드 형식이 아니다: {market!r}")
    return unique


def _to_param(moment: datetime) -> str:
    """캔들 `to`: UTC ISO 8601(`Z`). 초 단위로 올린다(캔들 시작은 분 단위라 결과가 같다)."""
    utc = moment.astimezone(UTC)
    if utc.microsecond:
        utc = utc.replace(microsecond=0) + timedelta(seconds=1)
    return utc.strftime("%Y-%m-%dT%H:%M:%SZ")


def _market_info(item: Any) -> MarketInfo:
    event = item.get("market_event")
    if isinstance(event, dict):
        # 참·거짓이 아닌 값은 보수적으로 "경고"로 본다(신규 매수를 막는 쪽).
        warning = event.get("warning") is not False
        raw_caution = event.get("caution") or {}
        caution = {convert.text(k): v is not False for k, v in raw_caution.items()}
    else:
        # is_details=true인데 market_event가 없으면 경고 여부를 모른다 → 신규 매수를 막는다.
        warning = True
        caution = {}
    return MarketInfo(
        market=convert.text(item["market"]),
        korean_name=convert.text(item["korean_name"]),
        english_name=convert.text(item["english_name"]),
        warning=warning,
        caution=caution,
    )


def _candle(item: Any, unit: str) -> Candle:
    return Candle(
        market=convert.text(item["market"]),
        unit=unit,
        start_utc=convert.naive_utc(item["candle_date_time_utc"]),
        open=convert.dec(item["opening_price"]),
        high=convert.dec(item["high_price"]),
        low=convert.dec(item["low_price"]),
        close=convert.dec(item["trade_price"]),
        volume=convert.dec(item["candle_acc_trade_volume"]),
        value=convert.dec(item["candle_acc_trade_price"]),
    )


def _ticker(item: Any) -> Ticker:
    return Ticker(
        market=convert.text(item["market"]),
        trade_price=convert.dec(item["trade_price"]),
        signed_change_rate=convert.dec(item["signed_change_rate"]),
        acc_trade_price_24h=convert.dec(item["acc_trade_price_24h"]),
        acc_trade_volume_24h=convert.dec(item["acc_trade_volume_24h"]),
        timestamp_ms=convert.to_int(item["timestamp"]),
    )


def _orderbook(item: Any) -> Orderbook:
    units = tuple(
        OrderbookUnit(
            ask_price=convert.dec(u["ask_price"]),
            bid_price=convert.dec(u["bid_price"]),
            ask_size=convert.dec(u["ask_size"]),
            bid_size=convert.dec(u["bid_size"]),
        )
        for u in convert.items(item["orderbook_units"])
    )
    return Orderbook(
        market=convert.text(item["market"]),
        units=units,
        timestamp_ms=convert.to_int(item["timestamp"]),
    )


def _tick_size(item: Any) -> tuple[str, Decimal]:
    tick = convert.dec(item["tick_size"])
    if not tick.is_finite() or tick <= 0:
        raise convert.ResponseShapeError("tick_size는 0보다 커야 한다")
    return convert.text(item["market"]), tick


class UpbitQuotationApi:
    """QuotationApi 구현. 키 없이 부른다. 한 이벤트 루프에서만 쓴다."""

    def __init__(self, http: UpbitHttp) -> None:
        self._http = http

    def __repr__(self) -> str:
        return "UpbitQuotationApi()"

    async def list_markets(self) -> list[MarketInfo]:
        response = await self._http.get("/v1/market/all", [("is_details", "true")])
        with convert.response_shape(response, group="market"):
            markets = [_market_info(item) for item in convert.items(response.data)]
        return [m for m in markets if m.market.startswith("KRW-")]

    async def get_candles(
        self, market: str, unit: CandleUnit, *, count: int = MAX_CANDLES, to: datetime | None = None
    ) -> list[Candle]:
        path = CANDLE_PATHS.get(unit) if isinstance(unit, str) else None
        if path is None:
            raise ValueError(f"모르는 캔들 단위: {unit!r}")
        [market] = _check_markets([market])
        if isinstance(count, bool) or not isinstance(count, int):
            raise TypeError("count는 정수다")
        if not 1 <= count <= MAX_CANDLES:
            raise ValueError(f"count는 1~{MAX_CANDLES}이다: {count}")
        params = [("market", market)]
        if to is not None:
            if to.tzinfo is None or to.utcoffset() is None:
                raise ValueError("to는 시간대가 있는 datetime이어야 한다")
            params.append(("to", _to_param(to)))
        params.append(("count", str(count)))

        response = await self._http.get(path, params)
        with convert.response_shape(response, group="candles"):
            candles = [_candle(item, unit) for item in convert.items(response.data)]
        # 업비트는 최신부터 준다. 시간순(오래된 것부터)으로 돌려준다.
        candles.sort(key=lambda c: c.start_utc)
        return candles

    async def get_tickers(self, markets: Sequence[str]) -> list[Ticker]:
        return await self._by_markets("/v1/ticker", "ticker", markets, _ticker)

    async def get_orderbooks(self, markets: Sequence[str]) -> list[Orderbook]:
        wanted = _check_markets(markets)
        if not wanted:
            return []
        response = await self._http.get("/v1/orderbook", [("markets", ",".join(wanted))])
        with convert.response_shape(response, group="orderbook"):
            return [_orderbook(item) for item in convert.items(response.data)]

    async def get_tick_sizes(self, markets: Sequence[str]) -> dict[str, Decimal]:
        """instruments의 tick_size. 서버가 모르는 마켓은 결과에 없다(그때는 KRW 표를 쓴다)."""
        pairs = await self._by_markets(
            "/v1/orderbook/instruments", "orderbook", markets, _tick_size
        )
        return dict(pairs)

    async def server_time(self) -> datetime:
        """거래소 시각(응답 Date 헤더, 초 단위, UTC)."""
        response = await self._http.get("/v1/ticker", [("markets", SERVER_TIME_MARKET)])
        if response.server_date is None:
            raise UpbitServerError(
                http_status=response.status,
                message="응답에 Date 헤더가 없다",
                rate_group="ticker",
            )
        return response.server_date

    async def _by_markets(
        self, path: str, group: str, markets: Sequence[str], parse: Callable[[Any], T]
    ) -> list[T]:
        """markets를 묶어 한 번 부르고, 전체 404면 마켓마다 다시 불러 없는 마켓을 뺀다."""
        wanted = _check_markets(markets)
        if not wanted:
            return []
        try:
            response = await self._http.get(path, [("markets", ",".join(wanted))])
        except UpbitNotFound:
            if len(wanted) == 1:
                logger.info("업비트 %s: 없는 마켓 %s", path, wanted[0])
                return []
            logger.info(
                "업비트 %s: 묶은 요청이 404라 마켓마다 다시 부른다(%d개)", path, len(wanted)
            )
        else:
            return self._parse_list(response, group, parse)

        results: list[T] = []
        missing: list[str] = []
        for market in wanted:
            try:
                single = await self._http.get(path, [("markets", market)])
            except UpbitNotFound:
                missing.append(market)
                continue
            results.extend(self._parse_list(single, group, parse))
        if missing:
            logger.info("업비트 %s: 없는 마켓 %s", path, ",".join(missing))
        return results

    @staticmethod
    def _parse_list(response: UpbitResponse, group: str, parse: Callable[[Any], T]) -> list[T]:
        with convert.response_shape(response, group=group):
            return [parse(item) for item in convert.items(response.data)]


__all__ = ["CANDLE_PATHS", "MAX_CANDLES", "UpbitQuotationApi"]
