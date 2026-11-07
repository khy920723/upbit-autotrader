"""업비트 거래 어댑터(ExchangeApi 구현): 비공개 REST, 키 필요, 포켓 단위 한도.

이 어댑터는 OrderRequest를 와이어로 옮기고 응답을 값 객체로 바꿀 뿐이다. 주문 정책(금액 계산,
주문 유형 선택, 분할 매수)은 만들지 않는다. 그 정책(D-043·D-082~D-086)은 5단계 주문 관리가 맡는다.
결과 불명 처리도 상위 계층 몫이다.

- 자동 재시도 없음(INV-03): 어떤 실패도 예외로 올리고 다시 보내지 않는다.
- smp_type은 항상 보낸다(INV-06, D-047). 가격·수량은 지수 표기 없는 문자열로 보낸다(D-071).
  문자열은 Decimal 정밀도(문맥)와 무관하게 값 그대로 만든다(몰래 반올림하지 않는다). 정수부와
  소수부를 합쳐 40자리를 넘으면 ValueError다.
- 보내기 전에 주문 유형별 필수값, time_in_force, identifier 형식, 마켓 코드 형식, 값 범위를
  검사하고 어기면 ValueError다(요청을 보내지 않는다). 반올림은 정책 몫이라 고치지 않고 거부한다.
- 일괄 취소(DELETE /v1/orders/open)는 없다(D-069). 취소는 identifier로 하나씩.
- 개별 주문 조회(GET /v1/order)의 404는 error.name이 order_not_found이든 없든(본문 없음, error
  객체·name 없음, null, 빈 문자열) "없음"이다(D-094 B). lookup_order는 둘을 OrderLookup.not_found
  ("order_not_found"·"unnamed")로 구별하고 get_order는 둘 다 None이다. 다른 이름의 404는
  UpbitNotFound다. 주문 취소의 404는 이름이 없어도 UpbitNotFound다(B는 개별 조회에만).
- 응답의 선택 필드는 키째 빠질 수 있다 → None(모름). 주문 객체에서 꼭 있어야 하는 필드는
  업비트 Order 스키마의 required 가운데 식별에 쓰는 것(uuid, market, side, ord_type, state,
  created_at, trades_count)뿐이다. 시각은 UTC로 바꾼다.
- UpbitServerError는 5xx만이 아니다. 2xx인데 응답 모양이 다를 때(201 주문 생성 포함)와 목록이
  잘렸을 수 있을 때(종료 주문 1,000개, 미체결 100쪽)도 낸다. 상위 계층은 http_status가 아니라
  예외 타입으로 나눈다(주문 생성에서 UpbitServerError면 결과 불명).
- 전체 Access Key는 결과·로그·예외·traceback(지역 변수, `__context__` 포함) 어디에도 남기지
  않는다(INV-07). 키 목록은 앞 4자만.
근거: docs/05-integration/upbit-api.md 2·5장, docs/06-architecture/system-architecture.md 6장,
docs/03-functional/trading-logic.md 6·7·9·10·11장.
"""

import functools
import hmac
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from autotrader.adapters.upbit import convert
from autotrader.adapters.upbit.http import UpbitHttp
from autotrader.core.errors import UpbitNotFound, UpbitServerError
from autotrader.core.models import (
    ACCESS_KEY_PREFIX_LENGTH,
    ApiKeyInfo,
    Balance,
    OrderChance,
    OrderLookup,
    OrderRequest,
    OrderSnapshot,
    Trade,
    UpbitCredentials,
)

MAX_IDENTIFIER_LENGTH = 64
MAX_IDS_PER_LOOKUP = 100
MAX_VOLUME_DECIMALS = 8
MAX_NUMBER_DIGITS = 40
CLOSED_WINDOW = timedelta(days=7)
OPEN_PAGE_LIMIT = 100
MAX_OPEN_PAGES = 100
CLOSED_LIMIT = 1000
ORDER_SIDES = frozenset({"bid", "ask"})
ORDER_TYPES = frozenset({"limit", "price", "market", "best"})
IMMEDIATE_TIF = frozenset({"ioc", "fok"})
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


# ── 보내기 전 검사 ─────────────────────────────────────────


def check_identifier(identifier: object) -> str:
    """identifier: 1~64자, 출력 가능한 ASCII, 공백·`+` 없음(TS-116). 아니면 ValueError."""
    if not isinstance(identifier, str):
        raise ValueError("identifier는 문자열이어야 한다")
    if not 1 <= len(identifier) <= MAX_IDENTIFIER_LENGTH:
        raise ValueError(f"identifier는 1~{MAX_IDENTIFIER_LENGTH}자다: {len(identifier)}자")
    if any(not ("!" <= ch <= "~") or ch == "+" for ch in identifier):
        raise ValueError("identifier에 공백·제어 문자·`+`·ASCII 밖 문자를 쓸 수 없다")
    return identifier


def _plain_digits(value: Decimal) -> tuple[str, int]:
    """0보다 큰 유한 Decimal → (지수 표기·부호 없는 문자열, 소수 자릿수). 뒤의 0은 뗀다.

    문맥 정밀도를 쓰는 연산(normalize·quantize 등)을 하지 않으므로 반올림이 없다.
    자릿수가 MAX_NUMBER_DIGITS를 넘으면 문자열을 만들기 전에 ValueError다.
    """
    _, digits, exponent = value.as_tuple()
    assert isinstance(exponent, int)  # 유한값
    significant = len(digits)
    while significant > 1 and digits[significant - 1] == 0:
        significant -= 1
        exponent += 1
    places = max(-exponent, 0)
    whole = max(significant + exponent, 1)  # 정수부 자릿수(0.xxx면 "0" 한 자리)
    if whole + places > MAX_NUMBER_DIGITS:
        raise ValueError(f"숫자는 정수부와 소수부를 합쳐 {MAX_NUMBER_DIGITS}자리까지다")
    textual = format(value, "f")  # 정밀도를 주지 않으면 값 그대로(반올림 없음)
    if "." in textual:
        textual = textual.rstrip("0").rstrip(".")
    return textual, places


def plain_number(value: Decimal, name: str) -> str:
    """0보다 큰 유한 Decimal → 지수 표기·부호 없는 문자열(뒤의 0은 뗀다). 값을 바꾸지 않는다."""
    return _plain_digits(_check_amount(value, name))[0]


def _check_amount(value: object, name: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise ValueError(f"{name}는 Decimal이어야 한다")
    if not value.is_finite() or value <= 0:
        raise ValueError(f"{name}는 0보다 큰 유한값이어야 한다: {value}")
    return value


def _check_volume(volume: Decimal) -> str:
    textual, places = _plain_digits(_check_amount(volume, "volume"))
    if places > MAX_VOLUME_DECIMALS:
        raise ValueError(
            f"volume은 소수 {MAX_VOLUME_DECIMALS}자리까지다(반올림은 정책 몫): {textual}"
        )
    return textual


def order_body(req: OrderRequest) -> dict[str, str]:
    """OrderRequest → POST /v1/orders 본문. 주문 유형에 맞지 않으면 ValueError(보내지 않는다).

    주문 유형별 필수값(주문 생성 문서):
    - limit: price·volume, time_in_force는 없음·ioc·fok
    - price(시장가 매수): side=bid, price(총액)만, time_in_force 없음
    - market(시장가 매도): side=ask, volume만, time_in_force 없음
    - best(최유리): time_in_force ioc·fok 필수, 매수는 price(총액)만, 매도는 volume만
    post_only는 smp_type과 함께 쓸 수 없어 쓰지 않는다(매매 로직 명세 6장).
    """
    if req.side not in ORDER_SIDES:
        raise ValueError(f"side는 bid·ask다: {req.side!r}")
    if req.ord_type not in ORDER_TYPES:
        raise ValueError(f"ord_type은 limit·price·market·best다: {req.ord_type!r}")
    market = convert.check_market(req.market)
    identifier = check_identifier(req.identifier)
    if req.smp_type != "cancel_maker":
        raise ValueError("smp_type은 cancel_maker만 쓴다(D-047)")
    tif = req.time_in_force
    if tif is not None and tif not in IMMEDIATE_TIF:
        raise ValueError(f"time_in_force는 ioc·fok만 쓴다(post_only 안 씀): {tif!r}")

    has_price, has_volume = req.price is not None, req.volume is not None
    if req.ord_type == "limit":
        ok = has_price and has_volume
    elif req.ord_type == "price":
        ok = req.side == "bid" and has_price and not has_volume and tif is None
    elif req.ord_type == "market":
        ok = req.side == "ask" and has_volume and not has_price and tif is None
    else:  # best
        wants_price = req.side == "bid"
        ok = tif is not None and has_price == wants_price and has_volume != wants_price
    if not ok:
        raise ValueError(f"{req.ord_type}/{req.side} 주문의 필수값·조합이 맞지 않는다")

    body: dict[str, str] = {"market": market, "side": req.side, "ord_type": req.ord_type}
    if req.price is not None:
        body["price"] = plain_number(req.price, "price")
    if req.volume is not None:
        body["volume"] = _check_volume(req.volume)
    if tif is not None:
        body["time_in_force"] = tif
    body["identifier"] = identifier
    body["smp_type"] = req.smp_type  # 항상 명시(INV-06)
    return body


def _ms(moment: datetime) -> str:
    return str((moment - _EPOCH) // timedelta(milliseconds=1))


# ── 응답 변환 ─────────────────────────────────────────────


def _balance(item: Any) -> Balance:
    return Balance(
        currency=convert.text(item["currency"]),
        balance=convert.dec(item["balance"]),
        locked=convert.dec(item["locked"]),
        avg_buy_price=convert.dec(item["avg_buy_price"]),
        avg_buy_price_modified=convert.flag(item["avg_buy_price_modified"]),
        unit_currency=convert.text(item["unit_currency"]),
    )


def _types(value: Any) -> tuple[str, ...]:
    # 목록이 없으면 빈 튜플(그 유형을 지원한다고 보지 않는다. 예: best_fok가 없으면 매수 보류).
    return tuple(convert.text(v) for v in convert.items(value)) if value is not None else ()


def _chance(data: Any) -> OrderChance:
    # bid_account·ask_account와 그 balance·locked는 문서 스키마의 required다(없으면 모양 오류).
    info, bid_account, ask_account = data["market"], data["bid_account"], data["ask_account"]
    return OrderChance(
        market=convert.text(info["id"]),
        bid_fee=convert.dec(data["bid_fee"]),
        ask_fee=convert.dec(data["ask_fee"]),
        maker_bid_fee=convert.dec(data["maker_bid_fee"]),
        maker_ask_fee=convert.dec(data["maker_ask_fee"]),
        bid_min_total=convert.dec(info["bid"]["min_total"]),
        ask_min_total=convert.dec(info["ask"]["min_total"]),
        max_total=convert.dec(info["max_total"]),
        state=convert.text(info["state"]),
        bid_types=_types(info.get("bid_types")),
        ask_types=_types(info.get("ask_types")),
        order_types=_types(info.get("order_types")),
        order_sides=_types(info.get("order_sides")),
        bid_balance=convert.dec(bid_account["balance"]),
        bid_locked=convert.dec(bid_account["locked"]),
        ask_balance=convert.dec(ask_account["balance"]),
        ask_locked=convert.dec(ask_account["locked"]),
    )


def _trade(item: Any) -> Trade:
    return Trade(
        uuid=convert.text(item["uuid"]),
        market=convert.text(item["market"]),
        price=convert.dec(item["price"]),
        volume=convert.dec(item["volume"]),
        funds=convert.dec(item["funds"]),
        side=convert.text(item["side"]),
        created_at=convert.aware_utc(item["created_at"]),
    )


def _snapshot(data: Any) -> OrderSnapshot:
    """주문 객체 → OrderSnapshot. trades 키가 없으면(생성·취소·목록 응답) None."""
    raw_trades = data.get("trades")
    trades = None if raw_trades is None else tuple(_trade(t) for t in convert.items(raw_trades))
    return OrderSnapshot(
        uuid=convert.text(data["uuid"]),
        identifier=convert.opt_text(data.get("identifier")),
        market=convert.text(data["market"]),
        side=convert.text(data["side"]),
        ord_type=convert.text(data["ord_type"]),
        state=convert.text(data["state"]),
        price=convert.opt_dec(data.get("price")),
        volume=convert.opt_dec(data.get("volume")),
        remaining_volume=convert.opt_dec(data.get("remaining_volume")),
        executed_volume=convert.opt_dec(data.get("executed_volume")),
        reserved_fee=convert.opt_dec(data.get("reserved_fee")),
        remaining_fee=convert.opt_dec(data.get("remaining_fee")),
        paid_fee=convert.opt_dec(data.get("paid_fee")),
        locked=convert.opt_dec(data.get("locked")),
        prevented_volume=convert.opt_dec(data.get("prevented_volume")),
        prevented_locked=convert.opt_dec(data.get("prevented_locked")),
        trades_count=convert.to_int(data["trades_count"]),
        created_at=convert.aware_utc(data["created_at"]),
        time_in_force=convert.opt_text(data.get("time_in_force")),
        smp_type=convert.opt_text(data.get("smp_type")),
        trades=trades,
    )


def _api_keys(data: Any, own: UpbitCredentials | None) -> list[ApiKeyInfo]:
    """키 목록 응답 → ApiKeyInfo 목록. 전체 값은 이 프레임 안에서 비교에만 쓴다.

    실패는 convert.try_parse가 이 함수 밖으로 내보내지 않는다(이 프레임의 지역 변수에 전체
    Access Key가 있으므로 traceback으로 나가면 안 된다).
    """
    own_key = own.access_key.encode("utf-8") if own is not None else None
    result: list[ApiKeyInfo] = []
    for item in convert.items(data):
        listed = convert.text(item["access_key"])
        current = own_key is not None and hmac.compare_digest(listed.encode("utf-8"), own_key)
        result.append(
            ApiKeyInfo(
                access_key_prefix=listed[:ACCESS_KEY_PREFIX_LENGTH],
                is_current=current,
                expire_at=convert.aware_utc(item["expire_at"]),
            )
        )
    return result


class UpbitExchangeApi:
    """ExchangeApi 구현. 한 이벤트 루프에서만 쓴다.

    credentials는 UpbitHttp에 준 것과 같은 키 제공 함수다. list_api_keys가 목록에서 자기 키를
    찾을 때만 쓴다(전체 값은 비교에만 쓰고 남기지 않는다).
    """

    def __init__(
        self,
        http: UpbitHttp,
        *,
        credentials: Callable[[], UpbitCredentials | None] | None = None,
    ) -> None:
        self._http = http
        self._credentials = credentials

    def __repr__(self) -> str:
        return "UpbitExchangeApi()"

    # ── 잔고·주문 가능 정보 ──

    async def get_accounts(self) -> list[Balance]:
        response = await self._http.get("/v1/accounts", auth=True)
        return convert.parse_list(response, "default", _balance)

    async def get_order_chance(self, market: str) -> OrderChance:
        """수수료·최소·최대 주문 금액·주문 가능 잔고(bid_account·ask_account)."""
        params = [("market", convert.check_market(market))]
        response = await self._http.get("/v1/orders/chance", params, auth=True)
        return convert.parse_response(response, "default", _chance)

    # ── 주문 생성·검증 ──

    async def create_order(self, req: OrderRequest) -> OrderSnapshot:
        """POST /v1/orders 1회. 실패는 그대로 올린다(재시도 없음, 결과 불명 판단은 상위 계층)."""
        body = order_body(req)
        response = await self._http.post("/v1/orders", body)
        return convert.parse_response(response, "order", _snapshot)

    async def test_order(self, req: OrderRequest) -> OrderSnapshot:
        """POST /v1/orders/test(주문 검증). 실제 주문을 만들지 않고, 응답 uuid로 조회할 수 없다."""
        body = order_body(req)
        response = await self._http.post("/v1/orders/test", body)
        return convert.parse_response(response, "order-test", _snapshot)

    # ── 조회 ──

    async def lookup_order(self, *, identifier: str) -> OrderLookup:
        """identifier로 개별 조회(trades 포함) 1회. 두 "없음"을 구별한다(D-094 B).

        404 order_not_found → (None, "order_not_found"), 이름 없는 404(error.name이 없음·null·빈
        문자열, 본문 없음 포함) → (None, "unnamed"). 다른 이름의 404는 UpbitNotFound, 404가 아닌
        오류는 상태대로 낸다. 다시 보내지 않는다(INV-03).
        """
        params = [("identifier", check_identifier(identifier))]
        try:
            response = await self._http.get("/v1/order", params, auth=True)
        except UpbitNotFound as exc:
            if exc.error_name == "order_not_found":
                return OrderLookup(snapshot=None, not_found="order_not_found")
            if exc.http_status == 404 and not exc.error_name:
                return OrderLookup(snapshot=None, not_found="unnamed")
            raise
        snapshot = convert.parse_response(response, "default", _snapshot)
        return OrderLookup(snapshot=snapshot, not_found=None)

    async def get_order(self, *, identifier: str) -> OrderSnapshot | None:
        """lookup_order의 snapshot(호환). 두 "없음" 모두 None이다."""
        return (await self.lookup_order(identifier=identifier)).snapshot

    async def get_orders(self, *, identifiers: Sequence[str]) -> list[OrderSnapshot]:
        """identifier 목록으로 조회(최대 100개, trades 없음). 없는 identifier는 결과에 없다."""
        if isinstance(identifiers, str):
            raise TypeError("identifiers는 identifier의 목록이다")
        wanted = [check_identifier(i) for i in identifiers]
        if len(wanted) > MAX_IDS_PER_LOOKUP:
            raise ValueError(f"identifiers는 한 번에 {MAX_IDS_PER_LOOKUP}개까지다: {len(wanted)}개")
        if not wanted:
            return []
        params = [("identifiers[]", i) for i in wanted]
        response = await self._http.get("/v1/orders/uuids", params, auth=True)
        return convert.parse_list(response, "default", _snapshot)

    async def list_open_orders(self, market: str | None = None) -> list[OrderSnapshot]:
        """미체결(states[]=wait·watch). 오래된 것부터(order_by=asc) 쪽마다 100개씩 받는다.

        덜 찬 쪽이 오면 끝이다. 쪽 사이에 목록이 바뀌어 같은 주문이 두 번 오면 uuid로 한 번만
        담는다(쪽 사이에 끝난 주문 때문에 놓친 주문은 다음 대조에서 잡는다). 100쪽(1만 개)을
        넘으면 일부만 돌려주지 않고 UpbitServerError다.
        """
        base: list[tuple[str, str]] = []
        if market is not None:
            base.append(("market", convert.check_market(market)))
        base += [("states[]", "wait"), ("states[]", "watch")]
        orders: dict[str, OrderSnapshot] = {}
        for page in range(1, MAX_OPEN_PAGES + 1):
            params = [
                *base,
                ("page", str(page)),
                ("limit", str(OPEN_PAGE_LIMIT)),
                ("order_by", "asc"),
            ]
            response = await self._http.get("/v1/orders/open", params, auth=True)
            batch = convert.parse_list(response, "default", _snapshot)
            for order in batch:
                orders.setdefault(order.uuid, order)
            if len(batch) < OPEN_PAGE_LIMIT:
                return list(orders.values())
        # 끝없는 쪽 넘김을 막는다. 일부만 돌려주면 대조가 주문을 놓치므로 실패로 알린다.
        raise UpbitServerError(
            message=f"미체결 주문이 {MAX_OPEN_PAGES * OPEN_PAGE_LIMIT}개를 넘는다",
            rate_group="default",
        )

    async def list_closed_orders(
        self, *, market: str | None, start: datetime, end: datetime
    ) -> list[OrderSnapshot]:
        """종료 주문(done·cancel). 구간은 7일 이하, 밀리초 타임스탬프로 보낸다(trades 없음).

        오래된 것부터(order_by=asc) 한 번에 최대 1,000개를 받는다. 1,000개가 꽉 차면 잘렸을 수
        있으므로 일부를 돌려주지 않고 UpbitServerError다(호출하는 쪽이 구간을 나눠 다시 부른다).
        """
        convert.check_aware(start, "start")
        convert.check_aware(end, "end")
        if end < start:
            raise ValueError("end가 start보다 앞이다")
        if end - start > CLOSED_WINDOW:
            raise ValueError("종료 주문 조회 구간은 7일 이하다")
        params: list[tuple[str, str]] = []
        if market is not None:
            params.append(("market", convert.check_market(market)))
        params += [
            ("start_time", _ms(start)),
            ("end_time", _ms(end)),
            ("limit", str(CLOSED_LIMIT)),
            ("order_by", "asc"),
        ]
        response = await self._http.get("/v1/orders/closed", params, auth=True)
        orders = convert.parse_list(response, "default", _snapshot)
        if len(orders) >= CLOSED_LIMIT:
            raise UpbitServerError(
                http_status=response.status,
                message=(
                    f"종료 주문이 한 번 조회 한도({CLOSED_LIMIT}개)만큼 와서 잘렸을 수 있다. "
                    "구간을 나눠 다시 조회해야 한다"
                ),
                rate_group="default",
            )
        return orders

    # ── 취소 ──

    async def cancel_order(self, *, identifier: str) -> OrderSnapshot:
        """identifier로 하나 취소(쿼리만, 본문 없음). 대상이 없으면 이름이 없어도 UpbitNotFound."""
        params = [("identifier", check_identifier(identifier))]
        response = await self._http.delete("/v1/order", params)
        return convert.parse_response(response, "default", _snapshot)

    # ── 키 ──

    async def list_api_keys(self) -> list[ApiKeyInfo]:
        """키 목록(만료 시각 UTC). 전체 Access Key는 담지 않고 앞 4자와 현재 키 여부만.

        credentials가 없으면(None) 어느 키도 현재 키로 표시하지 않는다. 응답 모양이 다르면
        UpbitServerError인데, 그 traceback(지역 변수)과 `__context__`에 키가 남지 않게 읽기는
        _api_keys 안에서 끝내고, 응답을 지운 뒤 except 블록 밖에서 새 예외를 낸다.
        """
        own = self._credentials() if self._credentials is not None else None
        response = await self._http.get("/v1/api_keys", auth=True)
        status = response.status
        outcome = convert.try_parse(functools.partial(_api_keys, own=own), response.data)
        del response, own
        if isinstance(outcome, convert.ShapeFailure):
            raise convert.shape_error(status, "default", outcome)
        return outcome


__all__ = ["UpbitExchangeApi", "check_identifier", "order_body", "plain_number"]
