"""FakeUpbitServer: 업비트 REST 와이어 가짜(docs/08-quality/fakes-spec.md 2장).

`httpx.MockTransport`로 동작한다. 앱 클라이언트에 `transport=server.transport`를 넣으면
업비트 서버처럼 상태 코드·헤더·JSON 본문을 돌려준다. 네트워크는 쓰지 않는다.

- 공개 시세 응답은 tests/fixtures/upbit/의 녹화(숫자 토큰 원문 그대로), 비공개 API 응답의
  바탕은 tests/fixtures/upbit/docs_examples/(공식 문서 예시)다.
- 엄격 검사(2.3절): 어긴 요청은 `FakeProtocolViolation`(AssertionError 하위, `.rule`)을 던지고
  `violations`에도 남긴다. 실제 한도를 넘은 요청만 예외 없이 위반을 남기고 429로 답한다.
  테스트 끝에는 `assert_clean()`(공용 픽스처 `make_fake_upbit`·`fake_upbit`가 정리 단계에서 부른다).
- 순서: 경로·헤더·쿼리 → 멈춤(429·sec=0·418 뒤) → 요청 한도 → 본문 → 인증 → 주문 검사를 먼저
  하고, 그다음에 주입된 응답(실제 한도 429, 418, 429, 인증 오류)이나 정상 응답을 준다.
  같은 identifier의 POST /v1/orders 두 번째는 이보다 먼저, 전송 계층에서 잡는다.
- 서명은 앱 코드를 쓰지 않고 여기서 따로 검증한다(PyJWT 디코드 + SHA512 재계산).
  그래야 앱 서명 버그를 가짜가 잡는다.
- 서버 시각(Date 헤더, created_at) = `clock.true_utc_now()` + server_time_offset.
  PC 시계(FakeClock.set_pc_offset)를 따르지 않는다.
- 계약 요약은 tests/unit/fakes/test_fake_upbit_http.py 맨 위 docstring에 있다.
"""

import copy
import hashlib
import json
import math
import random
import re
import warnings
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from email.utils import format_datetime
from pathlib import Path
from typing import Any, NoReturn
from urllib.parse import unquote

import httpx
import jwt
from jwt.warnings import InsecureKeyLengthWarning

from autotrader.core.models import UpbitCredentials
from fakes.clock import FakeClock
from fakes.upbit_json import dumps, fmt_decimal, loads_raw, to_decimal
from fakes.upbit_orders import (
    CLOSED_STATES,
    OPEN_STATES,
    FakeOrder,
    FillPlan,
    Level,
    apply_fills,
    kst_text,
    match_book,
    plan_fills,
    seeded_uuid_factory,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "upbit"
DOCS_EXAMPLES = FIXTURES / "docs_examples"
HOST = "api.upbit.com"
SUCCESS_CONTENT_TYPE = "application/json;charset=UTF-8"  # 녹화: 성공 응답 표기
ERROR_CONTENT_TYPE = "application/json; charset=utf-8"  # 녹화: 오류 응답 표기

# 요청 한도: 그룹 → (창 초, 창 안 최대 요청 수). 업비트 API 연동 명세 2장, fakes-spec 2.3절.
REAL_LIMITS: dict[str, tuple[int, int]] = {
    "market": (1, 10),
    "candles": (1, 10),
    "ticker": (1, 10),
    "orderbook": (1, 10),
    "trade": (1, 10),
    "default": (1, 30),
    "order": (1, 12),
    "order-test": (1, 8),
    "order-cancel-all": (2, 1),
}


def _half(seconds: int, count: int) -> tuple[int, int]:
    """한도의 절반. 1회짜리 창(일괄 취소 2초에 1회)은 창을 두 배로(4초에 1회)."""
    return (seconds, count // 2) if count % 2 == 0 else (seconds * 2, count)


HALF_LIMITS: dict[str, tuple[int, int]] = {g: _half(*limit) for g, limit in REAL_LIMITS.items()}
QUOTATION_GROUPS = frozenset({"market", "candles", "ticker", "orderbook", "trade"})
# Remaining-Req의 min(폐기된 값). 녹화는 시세 그룹 600이다. 앱은 읽지 않는다.
MIN_FIELD = {"default": 1800, "order": 720, "order-test": 480, "order-cancel-all": 30}

# 418 뒤 Retry-After가 없을 때 앱이 확인 조회 전에 기다리는 시간(D-078, 5분).
UNKNOWN_BLOCK_WAIT = 300

APP_SMP_TYPE = "cancel_maker"  # 앱 정책(D-047)
DOCUMENTED_SMP_TYPES = frozenset({"cancel_maker", "cancel_taker", "reduce", "none"})
NUMBER_TEXT = re.compile(r"[0-9]+(?:\.[0-9]+)?")
VOLUME_DECIMALS = 8
UUID_TEXT = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE
)
ENCODED_BRACKET = re.compile(r"%5[bd]", re.IGNORECASE)
SEC_FIELD = re.compile(r"sec=(\d+)")
IDENTIFIER_KEYS = frozenset({"identifier", "identifiers[]"})
ORDER_KEYS = frozenset(
    {"market", "side", "volume", "price", "ord_type", "identifier", "time_in_force", "smp_type"}
)
JWT_KEYS = frozenset({"access_key", "nonce", "query_hash", "query_hash_alg"})
CANDLE_MINUTES = frozenset({1, 3, 5, 10, 15, 30, 60, 240})
CHANCE_TOP_FIELDS = frozenset({"bid_fee", "ask_fee", "maker_bid_fee", "maker_ask_fee"})
CHANCE_MARKET_FIELDS = frozenset(
    {"max_total", "state", "bid_types", "ask_types", "order_types", "order_sides"}
)
SEVEN_DAYS = timedelta(days=7)

# 문서 예시와 오류 안내의 기본 문구. random_message면 문구만 바뀐다.
ERROR_MESSAGES = {
    "no_authorization_ip": "This is not a verified IP.",
    "expired_access_key": "API 키가 만료되었습니다.",
    "jwt_verification": "Failed to verify Jwt token.",
    "invalid_query_payload": "Failed to verify the query of Jwt.",
    "nonce_used": "This nonce was already used.",
    "no_authorization_token": "Authorization token is missing.",
    "out_of_scope": "권한이 부족합니다.",
    "insufficient_funds_bid": "주문 가능한 금액(KRW)이 부족합니다.",
    "insufficient_funds_ask": "주문 가능한 수량이 부족합니다.",
    "under_min_total_bid": "최소 주문 금액 이상으로 주문해 주세요.",
    "under_min_total_ask": "최소 주문 금액 이상으로 주문해 주세요.",
    "over_krw_funds_bid": "최대 주문 가능 금액 1000000000 KRW 보다 작은 주문을 입력해 주세요.",
    "invalid_parameter": "잘못된 파라미터",
    "validation_error": "잘못된 파라미터",
    "invalid_time_in_force": "주문조건을 다시 확인해 주세요.",
    "invalid_post_only": "post_only 주문 조건을 확인해 주세요.",
    "create_bid_error": "주문 요청 정보가 올바르지 않습니다.",
    "create_ask_error": "주문 요청 정보가 올바르지 않습니다.",
    "duplicated_identifier": "이미 사용된 identifier입니다.",
    "bad_request": "잘못된 요청",
    "market_offline": "시스템 점검 중입니다. 점검이 완료된 후에 다시 시도해주세요.",
    "order_not_found": "주문을 찾지 못했습니다.",
    "server_error": "서버 오류",
    "too_many_requests": "Too many API requests.",
}
QUOTATION_MESSAGES = {
    400: "Invalid parameter. Check the given value!",
    404: "Code not found",
}
REJECT_STATUS = {"market_offline": 403}


class FakeProtocolViolation(AssertionError):
    """업비트 규칙을 어긴 요청. `rule`은 규칙 이름이다(테스트 파일 docstring 목록)."""

    def __init__(self, rule: str, detail: str) -> None:
        super().__init__(f"[{rule}] {detail}")
        self.rule = rule
        self.detail = detail


@dataclass(frozen=True, repr=False)
class RecordedRequest:
    """전송 계층에서 받은 요청 그대로(위반·주입 실패 요청 포함).

    repr은 Authorization 값을 가린다(필드 `headers`에는 그대로 있다).
    """

    method: str
    path: str  # 원래 경로(쿼리 제외, 인코딩 그대로)
    query: str  # 보낸 그대로의 인코딩된 쿼리 문자열
    headers: tuple[tuple[str, str], ...]  # 같은 이름 여러 개를 그대로
    body: bytes
    monotonic: float  # FakeClock 시각
    group: str | None  # 요청 한도 그룹(경로를 모르면 None)

    def __repr__(self) -> str:
        headers = tuple(
            (name, "<가림>" if name.lower() == "authorization" else value)
            for name, value in self.headers
        )
        return (
            f"RecordedRequest(method={self.method!r}, path={self.path!r}, query={self.query!r}, "
            f"headers={headers!r}, body={self.body!r}, monotonic={self.monotonic!r}, "
            f"group={self.group!r})"
        )


@dataclass(frozen=True)
class _Route:
    name: str
    group: str
    auth: bool
    unit: str | None = None
    keys: frozenset[str] = frozenset()  # 허용 쿼리 키(배열은 `[]`까지)


@dataclass
class _Ctx:
    request: httpx.Request
    route: _Route
    params: list[tuple[str, str]]
    body: dict[str, Any] | None
    remaining: str | None
    identifier: str | None = None


@dataclass(frozen=True)
class _OrderInjection:
    kind: (
        str  # timeout_before_send · timeout_after_accept · connection_reset · server_error · reject
    )
    created: bool = False
    status: int = 0
    name: str = ""


def _keys(*names: str) -> frozenset[str]:
    return frozenset(names)


# 허용 쿼리 키는 각 API 문서의 요청 파라미터다. 모르는 키(오타, `[]` 없는 배열 키)는 위반.
_MINUTE_CANDLE_KEYS = _keys("market", "to", "count")
_ORDER_ID_KEYS = _keys("uuid", "identifier")
_GET_ROUTES = {
    "/v1/market/all": _Route("market_all", "market", False, keys=_keys("is_details")),
    "/v1/candles/days": _Route(
        "candles", "candles", False, "d1", _MINUTE_CANDLE_KEYS | {"converting_price_unit"}
    ),
    "/v1/ticker": _Route("ticker", "ticker", False, keys=_keys("markets")),
    "/v1/orderbook": _Route("orderbook", "orderbook", False, keys=_keys("markets", "level")),
    "/v1/orderbook/instruments": _Route("instruments", "orderbook", False, keys=_keys("markets")),
    "/v1/accounts": _Route("accounts", "default", True),
    "/v1/orders/chance": _Route("chance", "default", True, keys=_keys("market")),
    "/v1/order": _Route("get_order", "default", True, keys=_ORDER_ID_KEYS),
    "/v1/orders/uuids": _Route(
        "orders_by_ids",
        "default",
        True,
        keys=_keys("market", "uuids[]", "identifiers[]", "order_by"),
    ),
    "/v1/orders/open": _Route(
        "open_orders",
        "default",
        True,
        keys=_keys("market", "state", "states[]", "page", "limit", "order_by"),
    ),
    "/v1/orders/closed": _Route(
        "closed_orders",
        "default",
        True,
        keys=_keys("market", "state", "states[]", "start_time", "end_time", "limit", "order_by"),
    ),
    "/v1/api_keys": _Route("api_keys", "default", True),
}
_POST_ROUTES = {
    "/v1/orders": _Route("create_order", "order", True),
    "/v1/orders/test": _Route("test_order", "order-test", True),
}
_DELETE_ROUTES = {
    "/v1/order": _Route("cancel_order", "default", True, keys=_ORDER_ID_KEYS),
    "/v1/orders/open": _Route(
        "batch_cancel",
        "order-cancel-all",
        True,
        keys=_keys(
            "quote_currencies", "cancel_side", "count", "order_by", "pairs", "excluded_pairs"
        ),
    ),
}
_MINUTE_CANDLES = re.compile(r"/v1/candles/minutes/(\d+)")


def _route_for(method: str, path: str) -> _Route | None:
    if method == "GET":
        match = _MINUTE_CANDLES.fullmatch(path)
        if match:
            minutes = int(match[1])
            if minutes not in CANDLE_MINUTES:
                return None
            return _Route("candles", "candles", False, f"m{minutes}", _MINUTE_CANDLE_KEYS)
        return _GET_ROUTES.get(path)
    if method == "POST":
        return _POST_ROUTES.get(path)
    if method == "DELETE":
        return _DELETE_ROUTES.get(path)
    return None


def _parse_query(query: str) -> list[tuple[str, str]]:
    """보낸 쿼리를 (키, 값) 순서대로 디코딩한다. `+`는 글자 그대로 둔다."""
    pairs: list[tuple[str, str]] = []
    for part in query.split("&"):
        if part:
            key, _, value = part.partition("=")
            pairs.append((unquote(key), unquote(value)))
    return pairs


def _first(params: Sequence[tuple[str, str]], key: str) -> str | None:
    return next((v for k, v in params if k == key), None)


def _all(params: Sequence[tuple[str, str]], key: str) -> list[str]:
    return [v for k, v in params if k == key]


def _split(value: str | None) -> list[str]:
    return [item for item in (value or "").split(",") if item]


def _plain(value: Any) -> str:
    """RawNumber 같은 str 하위 값을 보통 문자열로(거래 API는 숫자를 문자열로 준다)."""
    return str.__str__(value) if isinstance(value, str) else dumps(value)


def _parse_time(text: str) -> datetime:
    """ISO 8601(시간대 없으면 UTC) 또는 밀리초 타임스탬프."""
    if text.isdigit():
        return datetime.fromtimestamp(int(text) / 1000, tz=UTC)
    moment = datetime.fromisoformat(text.replace(" ", "T"))
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment


def _sha512(text: str) -> str:
    return hashlib.sha512(text.encode("utf-8")).hexdigest()


def _load(path: Path) -> Any:
    return loads_raw(path.read_text(encoding="utf-8"))


class FakeUpbitServer:
    """업비트 REST 서버 흉내. 상태(주문장·호가·종목)는 인스턴스마다 따로다."""

    def __init__(
        self,
        clock: FakeClock,
        credentials: UpbitCredentials,
        *,
        forbid_batch_cancel: bool = True,
        omit_optional_fields: bool = False,
        random_message: bool = False,
        seed: int | None = None,
        identifier_saved: Callable[[str], bool] | None = None,
        order_test_reserves_identifier: bool = False,
        forbid_encoded_brackets: bool = True,
    ) -> None:
        """forbid_encoded_brackets: 배열 키의 `[]`를 `%5B%5D`로 보내면 위반으로 본다(앱은 REST
        안내대로 인코딩하지 않는다, 업비트 API 연동 명세 3장). 실제 서버 동작은 확인 전이다."""
        self._clock = clock
        self._creds = credentials
        self._forbid_batch_cancel = forbid_batch_cancel
        self._omit_optional = omit_optional_fields
        self._random_message = random_message
        self._identifier_saved = identifier_saved
        self._order_test_reserves = order_test_reserves_identifier
        self._forbid_encoded_brackets = forbid_encoded_brackets
        self._message_rng = random.Random(seed if seed is not None else 0)
        self._new_uuid = seeded_uuid_factory(random.Random(f"uuid:{seed}"))
        self._server_offset = 0.0

        # 검사 API
        self.requests: list[RecordedRequest] = []
        self.violations: list[FakeProtocolViolation] = []
        self.jwt_payloads: list[dict[str, Any]] = []
        self._received: Counter[str] = Counter()
        self.transport = httpx.MockTransport(self._handle)

        # 시세 상태(녹화)
        self._markets: list[dict[str, Any]] = _load(FIXTURES / "market_all_details.json")
        self._removed: set[str] = set()
        tickers = _load(FIXTURES / "ticker_krw_btc_eth_xrp.json")
        self._tickers: dict[str, dict[str, Any]] = {t["market"]: t for t in tickers}
        self._ticker_template = tickers[0]
        books = _load(FIXTURES / "orderbook_krw_btc.json")
        self._orderbooks: dict[str, dict[str, Any]] = {b["market"]: b for b in books}
        self._candles: dict[tuple[str, str], list[dict[str, Any]]] = {
            ("KRW-BTC", "m240"): _load(FIXTURES / "candles_minutes_240_krw_btc.json"),
            ("KRW-BTC", "d1"): _load(FIXTURES / "candles_days_krw_btc.json"),
        }

        # 비공개 상태(문서 예시)
        instruments = _load(DOCS_EXAMPLES / "list-orderbook-instruments.json")["example"]
        self._instruments = {item["market"]: item for item in instruments}
        self._chance_template = _load(DOCS_EXAMPLES / "available-order-information.json")["example"]
        self._chance_overrides: dict[str, dict[str, Any]] = {}
        self._accounts: list[dict[str, Any]] = _load(DOCS_EXAMPLES / "get-balance.json")["example"]
        self._api_keys_result = "present"
        self._api_keys_status = 500
        # 문서 예시의 만료일(2026-06-25)은 이미 지났으므로 기본은 "가짜를 만든 때 + 1년"이다.
        self._api_keys_expire = kst_text(self._server_now() + timedelta(days=365))

        # 주문 상태
        self._orders: dict[str, FakeOrder] = {}
        self._by_identifier: dict[str, FakeOrder] = {}
        self._attempts: dict[str, str] = {}  # identifier → answered·unsent·no_response
        self._reserved: set[str] = set()  # 주문 검증이 남긴 identifier(옵션)
        self._fill_plans: dict[str, FillPlan] = {}
        self._hidden: dict[str, int] = {}
        self._seq = 0

        # 주입
        self._order_injections: list[_OrderInjection] = []
        self._validate_injections: list[tuple[int, str]] = []
        self._auth_injections: list[tuple[int, str]] = []
        self._rate_limited: dict[str, list[str]] = {}
        self._blocked: tuple[float, str, bool] | None = None
        self._remaining: dict[str, list[Any]] = {}
        self._nonces: set[str] = set()

        # 멈춤 검사: 이 시각(monotonic) 전에 온 요청은 위반
        self._pause_until: dict[str, float] = {}  # 그룹별(429, sec=0 뒤)
        self._block_pause_until: float | None = None  # 모든 그룹(418 뒤)

    # ── 검사 API ─────────────────────────────────────────

    @property
    def clock(self) -> FakeClock:
        return self._clock

    @property
    def credentials(self) -> UpbitCredentials:
        """이 가짜가 서명을 검증하는 가짜 키(카나리아)."""
        return self._creds

    def assert_clean(self) -> None:
        """엄격 검사 위반이 0건이 아니면 위반 목록을 보여 주며 AssertionError."""
        if self.violations:
            lines = "\n".join(f"- {violation}" for violation in self.violations)
            raise AssertionError(
                f"FakeUpbitServer 엄격 검사 위반 {len(self.violations)}건:\n{lines}"
            )

    def orders_received(self, identifier: str) -> int:
        """그 identifier로 받은 POST /v1/orders 수(전송 계층 기준)."""
        return self._received[identifier]

    def requests_per_window(self, group: str, seconds: float) -> dict[float, int]:
        """{창 시작 monotonic: 요청 수}. 창은 `[floor(t / s) * s, +s)`."""
        counts: dict[float, int] = {}
        for record in self.requests:
            if record.group == group:
                start = math.floor(record.monotonic / seconds) * seconds
                counts[start] = counts.get(start, 0) + 1
        return counts

    def open_orders(self, market: str | None = None) -> list[dict[str, Any]]:
        """지금 거래소에 대기 중인 주문(주문 객체 모양)."""
        return [
            order.snapshot()
            for order in self._sorted(self._orders.values(), "asc")
            if order.is_open and market in (None, order.market)
        ]

    # ── 주입: 통신·거절(다음 POST /v1/orders 1건) ─────────

    def timeout_before_send(self) -> None:
        self._order_injections.append(_OrderInjection("timeout_before_send"))

    def timeout_after_accept(self) -> None:
        self._order_injections.append(_OrderInjection("timeout_after_accept", created=True))

    def connection_reset(self, *, accepted: bool) -> None:
        self._order_injections.append(_OrderInjection("connection_reset", created=accepted))

    def server_error(self, *, status: int = 500, created: bool = False) -> None:
        self._order_injections.append(_OrderInjection("server_error", created, status))

    def reject(self, name: str, *, status: int | None = None) -> None:
        code = status or REJECT_STATUS.get(name, 400)
        self._order_injections.append(_OrderInjection("reject", status=code, name=name))

    def validate(self, name: str, *, status: int | None = None) -> None:
        """다음 POST /v1/orders/test 1건을 그 이름으로 거절한다."""
        self._validate_injections.append((status or REJECT_STATUS.get(name, 400), name))

    # ── 주입: 한도 ────────────────────────────────────────

    def rate_limited(self, group: str, *, times: int = 1, body: str = "json") -> None:
        """그 그룹의 다음 요청 times건에 429. body: json·empty·text."""
        if body not in ("json", "empty", "text"):
            raise ValueError(body)
        self._rate_limited.setdefault(group, []).extend([body] * times)

    def blocked(self, seconds: float, *, body: str = "time", retry_after: bool = True) -> None:
        """지금부터 seconds 동안 모든 요청에 418. body: time·empty·text."""
        if body not in ("time", "empty", "text"):
            raise ValueError(body)
        self._blocked = (self._clock.monotonic() + seconds, body, retry_after)

    def remaining(
        self,
        group: str,
        *,
        sec: int,
        header_group: str | None = None,
        times: int | None = None,
    ) -> None:
        """그 그룹 응답의 Remaining-Req sec(와 group 표기)를 정한다. times=None이면 계속."""
        self._remaining[group] = [sec, header_group or group, times]

    # ── 주입: 인증·권한(다음 인증 요청) ──────────────────

    def auth_error(self, name: str, *, times: int = 1, status: int = 401) -> None:
        self._auth_injections.extend([(status, name)] * times)

    def out_of_scope(self, status: int = 401) -> None:
        self._auth_injections.append((status, "out_of_scope"))

    def unknown_error(self, name: str, status: int) -> None:
        self._auth_injections.append((status, name))

    # ── 주입: 주문 진행 ──────────────────────────────────

    def not_found_for(self, identifier: str, *, times: int) -> None:
        """그 identifier 조회(GET /v1/order, /v1/orders/uuids)에 times번 없음으로 답한다."""
        self._hidden[identifier] = times

    def fill(
        self,
        identifier: str,
        *,
        ratio: Decimal,
        price: Decimal | None = None,
        trades: int = 1,
        state: str | None = None,
    ) -> None:
        """그 identifier 주문의 체결을 정한다. ratio는 주문 전체 대비 누적 체결 비율(0~1).

        - 아직 없는 주문: 받을 때 쓸 예약이다. ratio<1이면 기본 끝 상태는 cancel. 가격을 주지
          않았는데 그때 호가가 비어 있으면 그 POST 처리에서 ValueError(시장·방향을 아직 모른다).
        - 이미 있는 주문: 그 자리에서 체결을 더한다(대기 중인 지정가). 기본 끝 상태는 ratio ≥ 1이면
          done, 아니면 그대로(wait). 끝난 주문이거나 가격을 정할 수 없으면 여기서 ValueError.
        """
        plan = FillPlan(to_decimal(ratio), price, trades, state)
        if not 0 <= plan.ratio <= 1:
            raise ValueError(f"ratio는 0~1이다: {ratio}")
        order = self._by_identifier.get(identifier)
        if order is None:
            self._fill_plans[identifier] = plan
            return
        if not order.is_open:
            raise ValueError(f"이미 끝난 주문({order.state})에는 체결을 더할 수 없다: {identifier}")
        fills, new_state = plan_fills(
            order, plan, self._best_price(order), partial_state=order.state
        )
        apply_fills(order, fills, new_state, now=self._server_now(), new_uuid=self._new_uuid)

    # ── 주입: 시장 정보 ──────────────────────────────────

    def orderbook(self, market: str, units: Iterable[Mapping[str, Decimal]]) -> None:
        """호가를 바꾼다. units: ask_price·ask_size·bid_price·bid_size(Decimal) 목록."""
        rows = [
            {
                "ask_price": to_decimal(u["ask_price"]),
                "bid_price": to_decimal(u["bid_price"]),
                "ask_size": to_decimal(u["ask_size"]),
                "bid_size": to_decimal(u["bid_size"]),
            }
            for u in units
        ]
        self._orderbooks[market] = self._book(market, rows)

    def candles(self, market: str, unit: str, series: Iterable[Mapping[str, Any]]) -> None:
        """캔들 열을 바꾼다. unit은 "m240"·"d1" 같은 값, series는 업비트 응답 모양의 dict."""
        allowed = {f"m{m}" for m in CANDLE_MINUTES} | {"d1"}
        if unit not in allowed:
            raise ValueError(unit)
        items = [dict(item) for item in series]
        items.sort(key=lambda c: str(c["candle_date_time_utc"]), reverse=True)
        self._candles[(market, unit)] = items

    def market_event(
        self,
        market: str,
        *,
        warning: bool | None = None,
        caution: Mapping[str, bool] | None = None,
    ) -> None:
        """종목 경고를 바꾼다. caution은 기존 키에 합친다(모르는 키도 더한다)."""
        item = self._market_item(market)
        event = item.setdefault("market_event", {"warning": False, "caution": {}})
        if warning is not None:
            event["warning"] = warning
        if caution:
            event.setdefault("caution", {}).update(caution)

    def market_removed(self, market: str) -> None:
        """종목 목록과 시세 API에서 그 마켓을 뺀다."""
        self._market_item(market)
        self._removed.add(market)

    def chance(self, market: str, **fields: Any) -> None:
        """주문 가능 정보를 바꾼다. 키: bid_fee·ask_fee·maker_bid_fee·maker_ask_fee·
        bid_min_total·ask_min_total·max_total·state·bid_types·ask_types·order_types·order_sides."""
        allowed = CHANCE_TOP_FIELDS | CHANCE_MARKET_FIELDS | {"bid_min_total", "ask_min_total"}
        unknown = set(fields) - allowed
        if unknown:
            raise TypeError(f"모르는 chance 필드: {sorted(unknown)}")
        self._chance_overrides.setdefault(market, {}).update(fields)

    def server_time_offset(self, seconds: float) -> None:
        """거래소 시각 = 실제 UTC + seconds(절대값)."""
        self._server_offset = seconds

    def api_keys(
        self,
        result: str,
        *,
        expire_at: str | None = None,
        status: int = 500,
    ) -> None:
        """result: present(자기 키 있음)·absent(없음)·error(status로 실패)."""
        if result not in ("present", "absent", "error"):
            raise ValueError(result)
        self._api_keys_result = result
        self._api_keys_status = status
        if expire_at is not None:
            self._api_keys_expire = expire_at

    def set_accounts(self, accounts: Iterable[Mapping[str, Any]]) -> None:
        """잔고 목록을 바꾼다(문자열 숫자, 업비트 응답 모양)."""
        self._accounts = [dict(item) for item in accounts]

    # ── 전송 계층 ────────────────────────────────────────

    def _handle(self, request: httpx.Request) -> httpx.Response:
        raw_target = request.url.raw_path.decode("ascii")
        raw_path = raw_target.partition("?")[0]
        normalized = re.sub(r"/+", "/", raw_path)
        if len(normalized) > 1:
            normalized = normalized.rstrip("/")
        route = _route_for(request.method, unquote(normalized))
        body = request.content
        now = self._clock.monotonic()
        self.requests.append(
            RecordedRequest(
                method=request.method,
                path=raw_path,
                query=request.url.query.decode("ascii"),
                headers=tuple(
                    (k.decode("latin-1"), v.decode("latin-1")) for k, v in request.headers.raw
                ),
                body=body,
                monotonic=now,
                group=route.group if route else None,
            )
        )
        if route is not None and route.name == "create_order":
            self._count_attempt(self._peek_identifier(body))
        response = self._process(request, raw_path, route)
        self._after_response(route, now, response)
        return response

    def _count_attempt(self, identifier: str | None) -> None:
        """같은 identifier의 POST /v1/orders 두 번째는 앞 시도 결과와 상관없이 위반(INV-03)."""
        if identifier is None:
            return
        self._received[identifier] += 1
        if self._received[identifier] <= 1:
            return
        if self._attempts.get(identifier) in ("unsent", "no_response"):
            self._violate("auto_retry", "응답을 못 받은 주문을 같은 identifier로 다시 보냈다")
        self._violate("identifier", "이미 보낸 identifier를 다시 보냈다")

    @staticmethod
    def _peek_identifier(body: bytes) -> str | None:
        try:
            data = json.loads(body)
        except (ValueError, UnicodeDecodeError):
            return None
        identifier = data.get("identifier") if isinstance(data, dict) else None
        return identifier if isinstance(identifier, str) else None

    def _process(
        self, request: httpx.Request, raw_path: str, route: _Route | None
    ) -> httpx.Response:
        url = request.url
        if url.scheme != "https" or url.host != HOST or url.port not in (None, 443):
            self._violate("path", f"기본 URL은 https://{HOST} 이어야 한다")
        if not raw_path.startswith("/v1/") or "//" in raw_path or raw_path.endswith("/"):
            self._violate("path", f"경로 형식 위반(중복·끝 슬래시): {raw_path}")
        if route is None:
            self._violate("path", f"가짜가 모르는 경로: {request.method} {raw_path}")

        names = [k.decode("latin-1").lower() for k, _ in request.headers.raw]
        if "origin" in names:
            self._violate("origin", "Origin 헤더를 보냈다")
        duplicated = sorted(name for name, count in Counter(names).items() if count > 1)
        if duplicated:
            self._violate("duplicate_header", f"같은 이름 헤더가 여러 개: {duplicated}")
        params = self._check_query(route, url.query.decode("ascii"))

        group = route.group
        now = self._clock.monotonic()
        self._check_pause(group, now)
        real_seconds, real_max = REAL_LIMITS[group]
        real_count = self._window_count(group, real_seconds, now)
        over_real = real_count > real_max
        if not over_real:
            half_seconds, half_max = HALF_LIMITS[group]
            if self._window_count(group, half_seconds, now) > half_max:
                self._violate(
                    "rate_limit_half", f"{group} 그룹 한도의 절반({half_max}/{half_seconds}초) 초과"
                )
        remaining = self._remaining_header(group, real_max - real_count)
        ctx = _Ctx(request, route, params, None, remaining)

        if request.method == "POST":
            ctx.body = self._check_post_body(request)
        elif request.method == "DELETE" and request.content:
            self._violate("delete_body", "DELETE 요청에 본문이 있다")
        if route.auth:
            self._check_auth(request, ctx)
        if route.name in ("create_order", "test_order"):
            assert ctx.body is not None
            real = route.name == "create_order"
            ctx.identifier = self._check_order(ctx.body, real=real)
            if real:
                assert ctx.identifier is not None
                self._attempts[ctx.identifier] = "answered"

        # 검사를 모두 통과한 뒤에 주입된 응답을 준다.
        if over_real:
            self._note("rate_limit", f"{group} 그룹 실제 한도({real_max}/{real_seconds}초) 초과")
            return self._too_many(ctx, "json")
        if self._blocked is not None:
            until, kind, retry_after = self._blocked
            if now < until:
                return self._teapot(math.ceil(until - now), kind, retry_after)
        queued = self._rate_limited.get(group)
        if queued:
            return self._too_many(ctx, queued.pop(0))
        if route.auth and self._auth_injections:
            status, name = self._auth_injections.pop(0)
            return self._error(ctx, status, name)

        handler: Callable[[_Ctx], httpx.Response] = getattr(self, f"_on_{route.name}")
        return handler(ctx)

    def _check_query(self, route: _Route, query: str) -> list[tuple[str, str]]:
        """보낸 그대로의 쿼리 문자열을 검사하고 (키, 값) 순서대로 디코딩한다."""
        if "+" in query or " " in query:
            self._violate(
                "query_encoding", "쿼리에 인코딩하지 않은 `+`나 공백이 있다(값은 퍼센트 인코딩)"
            )
        if self._forbid_encoded_brackets:
            raw_keys = [part.partition("=")[0] for part in query.split("&")]
            if any(ENCODED_BRACKET.search(key) for key in raw_keys):
                self._violate(
                    "query_encoding",
                    "배열 키의 `[]`를 `%5B%5D`로 인코딩했다(REST 안내: 그대로 둔다)",
                )
        params = _parse_query(query)
        unknown = sorted({key for key, _ in params} - route.keys)
        if unknown:
            self._violate("query_params", f"{route.name}에 쓸 수 없는 쿼리 키: {unknown}")
        for key, value in params:
            if key in IDENTIFIER_KEYS and (" " in value or "+" in value):
                self._violate("identifier", "identifier에 공백이나 `+`가 있다")
        return params

    def _check_pause(self, group: str, now: float) -> None:
        if self._block_pause_until is not None and now < self._block_pause_until:
            self._violate("blocked_request", "418 차단이 끝나기 전에 요청을 보냈다")
        until = self._pause_until.get(group)
        if until is not None and now < until:
            self._violate(
                "rate_limit_pause", f"{group} 그룹: 429·sec=0 응답 뒤 다음 초 경계 전에 다시 보냈다"
            )

    def _after_response(self, route: _Route | None, now: float, response: httpx.Response) -> None:
        """응답에 따라 멈춰야 할 때를 적는다(INV-13, TS-03·05·143)."""
        if route is None:
            return
        if response.status_code == 418:
            assert self._blocked is not None
            until, _, retry_after = self._blocked
            # Retry-After가 없으면 앱은 5분 뒤 확인 조회 1회를 보낸다(D-078). 그 확인은 허용한다.
            self._block_pause_until = until if retry_after else min(until, now + UNKNOWN_BLOCK_WAIT)
            return
        match = SEC_FIELD.search(response.headers.get("Remaining-Req", ""))
        if response.status_code == 429 or (match is not None and int(match[1]) == 0):
            self._pause_until[route.group] = math.floor(now) + 1

    def _window_count(self, group: str, seconds: int, now: float) -> int:
        start = math.floor(now / seconds) * seconds
        count = 0
        for record in reversed(self.requests):
            if record.monotonic < start:
                break
            if record.group == group:
                count += 1
        return count

    def _remaining_header(self, group: str, sec: int) -> str:
        header_group = group
        override = self._remaining.get(group)
        if override is not None:
            sec, header_group, times = override
            if times is not None:
                if times <= 1:
                    del self._remaining[group]
                else:
                    override[2] = times - 1
        minimum = 600 if group in QUOTATION_GROUPS else MIN_FIELD[group]
        return f"group={header_group}; min={minimum}; sec={max(0, sec)}"

    # ── 위반 ─────────────────────────────────────────────

    def _note(self, rule: str, detail: str) -> FakeProtocolViolation:
        violation = FakeProtocolViolation(rule, detail)
        self.violations.append(violation)
        return violation

    def _violate(self, rule: str, detail: str) -> NoReturn:
        raise self._note(rule, detail)

    # ── 엄격 검사: 본문·인증 ─────────────────────────────

    def _check_post_body(self, request: httpx.Request) -> dict[str, Any]:
        types = [v for k, v in request.headers.multi_items() if k == "content-type"]
        if not types or types[0].split(";")[0].strip().lower() != "application/json":
            self._violate("post_body", f"POST Content-Type이 application/json이 아니다: {types}")
        try:
            data = loads_raw(request.content.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            self._violate("post_body", "POST 본문이 JSON이 아니다")
        if not isinstance(data, dict):
            self._violate("post_body", "POST 본문이 JSON 객체가 아니다")
        return data

    def _check_auth(self, request: httpx.Request, ctx: _Ctx) -> None:
        values = [v for k, v in request.headers.multi_items() if k == "authorization"]
        if not values:
            self._violate("auth", "Authorization 헤더가 없다")
        scheme, _, token = values[0].partition(" ")
        if scheme != "Bearer" or not token:
            self._violate("auth", "Authorization 값이 'Bearer <JWT>' 모양이 아니다")
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError:
            self._violate("auth", "JWT 모양이 아니다")
        if header.get("alg") != "HS512":
            self._violate("jwt_alg", f"JWT alg가 HS512가 아니다: {header.get('alg')!r}")
        try:
            with warnings.catch_warnings():
                # 업비트 Secret Key(40자)는 PyJWT 권장 길이보다 짧다. 검증만 하므로 경고를 끈다.
                warnings.simplefilter("ignore", InsecureKeyLengthWarning)
                payload = jwt.decode(token, self._creds.secret_key, algorithms=["HS512"])
        except jwt.PyJWTError:
            self._violate("auth", "서명이 가짜 비밀 키로 검증되지 않는다")
        self.jwt_payloads.append(dict(payload))

        if payload.get("access_key") != self._creds.access_key:
            self._violate("auth", "access_key가 다르다")
        extra = sorted(set(payload) - JWT_KEYS)
        if extra:
            self._violate("auth", f"JWT 페이로드에 모르는 키: {extra}")

        nonce = payload.get("nonce")
        if not isinstance(nonce, str):
            self._violate("nonce", "nonce가 없다")
        if not UUID_TEXT.fullmatch(nonce):
            self._violate("nonce", "nonce가 하이픈 있는 표준 UUID 문자열이 아니다")
        if nonce in self._nonces:
            self._violate("nonce", "이미 쓴 nonce다")
        self._nonces.add(nonce)

        if ctx.body is not None:
            expected = "&".join(f"{k}={_plain(v)}" for k, v in ctx.body.items()) or None
        else:
            expected = "&".join(f"{k}={v}" for k, v in ctx.params) or None
        query_hash = payload.get("query_hash")
        if expected is None:
            if query_hash is not None or "query_hash_alg" in payload:
                self._violate("query_hash", "파라미터가 없는데 query_hash가 있다")
            return
        if query_hash is None:
            self._violate("query_hash", "파라미터·본문이 있는데 query_hash가 없다")
        if payload.get("query_hash_alg", "SHA512") != "SHA512":
            self._violate("query_hash", "query_hash_alg가 SHA512가 아니다")
        if query_hash != _sha512(expected):
            self._violate(
                "query_hash", "query_hash가 URL 인코딩 전 쿼리(본문은 키 순서 그대로)와 다르다"
            )

    # ── 응답 ─────────────────────────────────────────────

    def _server_now(self) -> datetime:
        return self._clock.true_utc_now() + timedelta(seconds=self._server_offset)

    def _response(
        self,
        status: int,
        content: bytes,
        content_type: str | None,
        remaining: str | None,
        extra: Sequence[tuple[str, str]] = (),
    ) -> httpx.Response:
        moment = self._server_now().astimezone(UTC).replace(microsecond=0)
        headers = [("Date", format_datetime(moment, usegmt=True))]
        if content_type is not None:
            headers.append(("Content-Type", content_type))
        if remaining is not None:
            headers.append(("Remaining-Req", remaining))
        headers.extend(extra)
        return httpx.Response(status, headers=headers, content=content)

    def _ok(self, ctx: _Ctx, data: Any, status: int = 200) -> httpx.Response:
        content = dumps(data).encode("utf-8")
        return self._response(status, content, SUCCESS_CONTENT_TYPE, ctx.remaining)

    def _message(self, default: str) -> str:
        if self._random_message:
            return f"임의 문구 {self._message_rng.getrandbits(48):012x}"
        return default

    def _error(
        self, ctx: _Ctx, status: int, name: str, message: str | None = None
    ) -> httpx.Response:
        text = self._message(message or ERROR_MESSAGES.get(name, name))
        content = dumps({"error": {"name": name, "message": text}}).encode("utf-8")
        return self._response(status, content, ERROR_CONTENT_TYPE, ctx.remaining)

    def _quotation_error(self, ctx: _Ctx, status: int) -> httpx.Response:
        """시세 API 오류: name이 정수(상태 코드)다."""
        text = self._message(QUOTATION_MESSAGES.get(status, "Error"))
        content = dumps({"error": {"name": status, "message": text}}).encode("utf-8")
        return self._response(status, content, ERROR_CONTENT_TYPE, ctx.remaining)

    def _too_many(self, ctx: _Ctx, kind: str) -> httpx.Response:
        if ctx.remaining is not None:
            ctx.remaining = SEC_FIELD.sub("sec=0", ctx.remaining)  # 429는 그 창에 남은 수가 없다
        if kind == "empty":
            return self._response(429, b"", None, ctx.remaining)
        if kind == "text":
            return self._response(429, b"Too Many Requests", "text/plain", ctx.remaining)
        return self._error(ctx, 429, "too_many_requests")

    def _teapot(self, seconds: int, kind: str, retry_after: bool) -> httpx.Response:
        extra = [("Retry-After", str(seconds))] if retry_after else []
        if kind == "empty":
            return self._response(418, b"", None, None, extra)
        if kind == "text":
            return self._response(
                418, b"Blocked by request limit policy", "text/plain", None, extra
            )
        # 418에는 error.name이 없다(REST API 안내). 차단 시간을 본문 문구에 담는다.
        text = f"요청 수 제한 위반으로 {seconds}초 동안 차단되었습니다."
        content = dumps({"error": {"message": text}}).encode("utf-8")
        return self._response(418, content, ERROR_CONTENT_TYPE, None, extra)

    # ── 시세 API ─────────────────────────────────────────

    def _market_item(self, market: str) -> dict[str, Any]:
        for item in self._markets:
            if item["market"] == market:
                return item
        raise KeyError(f"종목 목록에 없는 마켓: {market}")

    def _known(self, market: str) -> bool:
        return market not in self._removed and any(m["market"] == market for m in self._markets)

    def _on_market_all(self, ctx: _Ctx) -> httpx.Response:
        items = [m for m in self._markets if m["market"] not in self._removed]
        if _first(ctx.params, "is_details") != "true":
            items = [{k: v for k, v in m.items() if k != "market_event"} for m in items]
        return self._ok(ctx, items)

    def _on_candles(self, ctx: _Ctx) -> httpx.Response:
        market = _first(ctx.params, "market")
        if not market:
            return self._quotation_error(ctx, 400)
        if not self._known(market):
            return self._quotation_error(ctx, 404)
        try:
            count = int(_first(ctx.params, "count") or "1")
            to_text = _first(ctx.params, "to")
            to = _parse_time(to_text) if to_text else None
        except ValueError:
            return self._quotation_error(ctx, 400)
        if not 1 <= count <= 200:
            return self._quotation_error(ctx, 400)
        assert ctx.route.unit is not None
        series = self._candles.get((market, ctx.route.unit), [])
        if to is not None:
            series = [c for c in series if self._candle_start(c) < to]
        return self._ok(ctx, series[:count])

    @staticmethod
    def _candle_start(candle: Mapping[str, Any]) -> datetime:
        return datetime.fromisoformat(str(candle["candle_date_time_utc"])).replace(tzinfo=UTC)

    def _markets_param(self, ctx: _Ctx) -> list[str] | httpx.Response:
        markets = _split(_first(ctx.params, "markets"))
        if not markets:
            return self._quotation_error(ctx, 400)
        if not all(self._known(m) for m in markets):
            # 하나라도 없으면 있는 마켓 값도 없이 전체가 404다(녹화).
            return self._quotation_error(ctx, 404)
        return markets

    def _on_ticker(self, ctx: _Ctx) -> httpx.Response:
        markets = self._markets_param(ctx)
        if isinstance(markets, httpx.Response):
            return markets
        return self._ok(
            ctx, [self._tickers.get(m) or {**self._ticker_template, "market": m} for m in markets]
        )

    def _on_orderbook(self, ctx: _Ctx) -> httpx.Response:
        markets = self._markets_param(ctx)
        if isinstance(markets, httpx.Response):
            return markets
        return self._ok(ctx, [self._orderbooks.get(m) or self._book(m, []) for m in markets])

    def _on_instruments(self, ctx: _Ctx) -> httpx.Response:
        markets = _split(_first(ctx.params, "markets"))
        if not markets:
            return self._quotation_error(ctx, 400)
        if not all(m in self._instruments and m not in self._removed for m in markets):
            return self._quotation_error(ctx, 404)
        return self._ok(ctx, [self._instruments[m] for m in markets])

    def _book(self, market: str, rows: list[dict[str, Decimal]]) -> dict[str, Any]:
        moment = self._server_now()
        return {
            "market": market,
            "timestamp": int(moment.timestamp() * 1000),
            "total_ask_size": sum((r["ask_size"] for r in rows), Decimal(0)),
            "total_bid_size": sum((r["bid_size"] for r in rows), Decimal(0)),
            "orderbook_units": [
                {
                    "bid_price": r["bid_price"],
                    "bid_size": r["bid_size"],
                    "ask_price": r["ask_price"],
                    "ask_size": r["ask_size"],
                }
                for r in rows
            ],
            "level": 0,
        }

    def _levels(self, market: str) -> tuple[list[Level], list[Level]]:
        book = self._orderbooks.get(market)
        units = book["orderbook_units"] if book else []
        asks = [Level(to_decimal(u["ask_price"]), to_decimal(u["ask_size"])) for u in units]
        bids = [Level(to_decimal(u["bid_price"]), to_decimal(u["bid_size"])) for u in units]
        return asks, bids

    # ── 거래 API: 잔고·주문 가능 정보·키 ──────────────────

    def _on_accounts(self, ctx: _Ctx) -> httpx.Response:
        return self._ok(ctx, self._accounts)

    def _account(self, currency: str) -> dict[str, Any]:
        for item in self._accounts:
            if item.get("currency") == currency:
                return dict(item)
        return {
            "currency": currency,
            "balance": "0",
            "locked": "0",
            "avg_buy_price": "0",
            "avg_buy_price_modified": False,
            "unit_currency": "KRW",
        }

    def _chance_for(self, market: str) -> dict[str, Any]:
        quote, _, base = market.partition("-")
        data = copy.deepcopy(self._chance_template)
        info = data["market"]
        info["id"] = market
        info["name"] = f"{base}/{quote}"
        info["bid"]["currency"] = quote
        info["ask"]["currency"] = base
        data["bid_account"] = self._account(quote)
        data["ask_account"] = self._account(base)
        for key, value in self._chance_overrides.get(market, {}).items():
            text = fmt_decimal(value) if isinstance(value, Decimal) else value
            if isinstance(text, list | tuple):
                text = [str(item) for item in text]
            if key in CHANCE_TOP_FIELDS:
                data[key] = text
            elif key == "bid_min_total":
                info["bid"]["min_total"] = text
            elif key == "ask_min_total":
                info["ask"]["min_total"] = text
            else:
                info[key] = text
        return data

    def _fee_rate(self, market: str, side: str) -> Decimal:
        chance = self._chance_for(market)
        return to_decimal(chance["bid_fee" if side == "bid" else "ask_fee"])

    def _on_chance(self, ctx: _Ctx) -> httpx.Response:
        market = _first(ctx.params, "market")
        if not market:
            return self._error(ctx, 400, "invalid_parameter")
        if not self._known(market):
            return self._not_found_market(ctx, market)
        return self._ok(ctx, self._chance_for(market))

    def _not_found_market(self, ctx: _Ctx, market: str) -> httpx.Response:
        return self._error(ctx, 400, "notfoundmarket", f"다음 마켓에 없는 종목입니다: {market}")

    def _on_api_keys(self, ctx: _Ctx) -> httpx.Response:
        if self._api_keys_result == "error":
            status = self._api_keys_status
            return self._error(ctx, status, "server_error" if status >= 500 else "bad_request")
        if self._api_keys_result == "absent":
            return self._ok(ctx, [])
        return self._ok(
            ctx, [{"access_key": self._creds.access_key, "expire_at": self._api_keys_expire}]
        )

    # ── 거래 API: 주문 생성·검증 ─────────────────────────

    def _check_order(self, body: dict[str, Any], *, real: bool) -> str | None:
        unknown = sorted(set(body) - ORDER_KEYS)
        if unknown:
            self._violate("order_params", f"주문에 모르는 필드: {unknown}")
        for key, value in body.items():
            if type(value) is not str:  # JSON 숫자(RawNumber)·bool·null 거부
                self._violate("order_params", f"{key} 값은 JSON 문자열이어야 한다")

        smp_type = body.get("smp_type")
        if smp_type is None:
            self._violate("smp_type", "smp_type이 없다(2026-11-09부터 생략하면 cancel_maker)")
        if smp_type != APP_SMP_TYPE:
            if smp_type in DOCUMENTED_SMP_TYPES:
                self._violate(
                    "smp_type", f"앱 정책 위반(D-047): smp_type은 cancel_maker만 쓴다: {smp_type!r}"
                )
            self._violate("smp_type", f"문서에 없는 smp_type: {smp_type!r}")

        identifier = body.get("identifier")
        if real or identifier is not None:
            if not identifier:
                self._violate("identifier", "identifier가 없다")
            if len(identifier) > 64:
                self._violate("identifier", "identifier가 64자를 넘는다")
            if " " in identifier or "+" in identifier:
                self._violate("identifier", "identifier에 공백이나 `+`가 있다")
        if real:
            assert identifier is not None
            if identifier in self._reserved:
                self._violate("identifier", "주문 검증에 쓴 identifier를 다시 썼다")
            if self._identifier_saved is not None and not self._identifier_saved(identifier):
                self._violate("identifier_not_saved", "identifier를 DB에 저장하기 전에 보냈다")
        self._check_order_params(body)
        if body.get("time_in_force") == "post_only":
            # post_only는 cancel_maker·cancel_taker·reduce와 함께 쓸 수 없다(매매 로직 명세 6장).
            self._violate("smp_type", "post_only와 smp_type을 함께 썼다")
        return identifier

    def _check_order_params(self, body: dict[str, str]) -> None:
        def bad(detail: str) -> NoReturn:
            self._violate("order_params", detail)

        market, side, ord_type = body.get("market"), body.get("side"), body.get("ord_type")
        has_price, has_volume = "price" in body, "volume" in body
        tif = body.get("time_in_force")
        if not market or "-" not in market:
            bad("market이 없다")
        if side not in ("bid", "ask"):
            bad(f"side가 bid·ask가 아니다: {side!r}")
        for key in ("price", "volume"):
            if key in body:
                text = body[key]
                if not NUMBER_TEXT.fullmatch(text):
                    bad(f"{key}는 지수·부호·공백 없는 숫자 문자열이어야 한다: {text!r}")
                if Decimal(text) <= 0:
                    bad(f"{key}는 0보다 커야 한다")
        if has_volume and len(body["volume"].partition(".")[2]) > VOLUME_DECIMALS:
            bad(f"volume은 소수 {VOLUME_DECIMALS}자리까지다")
        if tif is not None and tif not in ("ioc", "fok", "post_only"):
            bad(f"time_in_force가 ioc·fok·post_only가 아니다: {tif!r}")

        if ord_type == "limit":
            if not (has_price and has_volume):
                bad("지정가는 price와 volume이 모두 있어야 한다")
        elif ord_type == "price":
            if side != "bid" or not has_price or has_volume or tif is not None:
                bad("시장가 매수(price)는 side=bid, price만 있어야 한다")
        elif ord_type == "market":
            if side != "ask" or not has_volume or has_price or tif is not None:
                bad("시장가 매도(market)는 side=ask, volume만 있어야 한다")
        elif ord_type == "best":
            if tif not in ("ioc", "fok"):
                bad("최유리(best)는 time_in_force가 ioc·fok여야 한다(post_only는 지정가 전용)")
            if side == "bid" and (not has_price or has_volume):
                bad("최유리 매수는 price(총액)만 있어야 한다")
            if side == "ask" and (not has_volume or has_price):
                bad("최유리 매도는 volume만 있어야 한다")
        else:
            bad(f"모르는 ord_type: {ord_type!r}")

    def _new_order(self, body: dict[str, Any], identifier: str | None) -> FakeOrder:
        self._seq += 1
        price, volume = body.get("price"), body.get("volume")
        return FakeOrder(
            uuid=self._new_uuid(),
            identifier=identifier,
            market=body["market"],
            side=body["side"],
            ord_type=body["ord_type"],
            price_text=price,
            volume_text=volume,
            time_in_force=body.get("time_in_force"),
            smp_type=body.get("smp_type"),
            fee_rate=self._fee_rate(body["market"], body["side"]),
            created_at=self._server_now(),
            seq=self._seq,
        )

    def _best_price(self, order: FakeOrder) -> Decimal | None:
        asks, bids = self._levels(order.market)
        top = asks if order.side == "bid" else bids
        return top[0].price if top else None

    def _create_order(self, body: dict[str, Any], identifier: str) -> FakeOrder:
        order = self._new_order(body, identifier)
        plan = self._fill_plans.pop(identifier, None)
        if plan is not None:
            fills, state = plan_fills(order, plan, self._best_price(order))
        else:
            fills, state = match_book(order, *self._levels(order.market))
        apply_fills(order, fills, state, now=order.created_at, new_uuid=self._new_uuid)
        self._orders[order.uuid] = order
        self._by_identifier[identifier] = order
        return order

    def _on_create_order(self, ctx: _Ctx) -> httpx.Response:
        assert ctx.body is not None
        identifier = ctx.identifier
        assert identifier is not None
        if not self._known(ctx.body["market"]):
            return self._not_found_market(ctx, ctx.body["market"])
        injection = self._order_injections.pop(0) if self._order_injections else None
        kind = injection.kind if injection else None
        request = ctx.request

        if injection is not None and kind == "timeout_before_send":
            self._attempts[identifier] = "unsent"
            raise httpx.ConnectTimeout("가짜: 요청이 서버에 닿지 않았다", request=request)
        if injection is not None and kind == "reject":
            return self._error(ctx, injection.status, injection.name)

        create = injection.created if injection is not None else True
        order = self._create_order(ctx.body, identifier) if create else None
        if injection is None:
            assert order is not None
            data = order.snapshot(at_creation=True, omit_optional=self._omit_optional)
            return self._ok(ctx, data, status=201)

        self._attempts[identifier] = "no_response"  # 5xx도 결과를 모르는 응답이다(UNKNOWN)
        if kind == "timeout_after_accept":
            raise httpx.ReadTimeout("가짜: 주문은 받았지만 응답이 오지 않는다", request=request)
        if kind == "connection_reset":
            raise httpx.ReadError("가짜: 연결이 끊겼다", request=request)
        return self._error(ctx, injection.status, "server_error")

    def _on_test_order(self, ctx: _Ctx) -> httpx.Response:
        assert ctx.body is not None
        identifier = ctx.identifier
        if not self._known(ctx.body["market"]):
            return self._not_found_market(ctx, ctx.body["market"])
        if self._order_test_reserves and identifier is not None:
            self._reserved.add(identifier)
        if self._validate_injections:
            status, name = self._validate_injections.pop(0)
            return self._error(ctx, status, name)
        # 주문장에 넣지 않는다. 돌려준 uuid·identifier로 조회·취소하면 404다.
        order = self._new_order(ctx.body, identifier)
        data = order.snapshot(at_creation=True, omit_optional=self._omit_optional)
        return self._ok(ctx, data, status=201)

    # ── 거래 API: 조회·취소 ──────────────────────────────

    def _consume_hidden(self, identifier: str | None) -> bool:
        """not_found_for 예약이 남았으면 하나 쓰고 True(없는 것처럼 답한다)."""
        if identifier is None:
            return False
        left = self._hidden.get(identifier, 0)
        if left <= 0:
            return False
        self._hidden[identifier] = left - 1
        return True

    def _find(self, order_uuid: str | None, identifier: str | None) -> FakeOrder | None:
        if order_uuid is not None:
            return self._orders.get(order_uuid)
        return self._by_identifier.get(identifier) if identifier is not None else None

    def _lookup(self, order_uuid: str | None, identifier: str | None) -> FakeOrder | None:
        order = self._find(order_uuid, identifier)
        target = identifier if order_uuid is None else (order.identifier if order else None)
        if self._consume_hidden(target):
            return None
        return order

    @staticmethod
    def _sorted(orders: Iterable[FakeOrder], order_by: str) -> list[FakeOrder]:
        return sorted(orders, key=lambda o: (o.created_at, o.seq), reverse=order_by != "asc")

    def _snapshots(self, orders: Iterable[FakeOrder]) -> list[dict[str, Any]]:
        return [o.snapshot(omit_optional=self._omit_optional) for o in orders]

    def _on_get_order(self, ctx: _Ctx) -> httpx.Response:
        order_uuid, identifier = _first(ctx.params, "uuid"), _first(ctx.params, "identifier")
        if (order_uuid is None) == (identifier is None):
            return self._error(ctx, 400, "invalid_parameter")
        order = self._lookup(order_uuid, identifier)
        if order is None:
            return self._error(ctx, 404, "order_not_found")
        data = order.snapshot(include_trades=True, omit_optional=self._omit_optional)
        return self._ok(ctx, data)

    def _on_orders_by_ids(self, ctx: _Ctx) -> httpx.Response:
        uuids, identifiers = _all(ctx.params, "uuids[]"), _all(ctx.params, "identifiers[]")
        order_by = _first(ctx.params, "order_by") or "desc"
        if bool(uuids) == bool(identifiers) or len(uuids or identifiers) > 100:
            return self._error(ctx, 400, "invalid_parameter")
        if order_by not in ("asc", "desc"):
            return self._error(ctx, 400, "invalid_parameter")
        found: dict[str, FakeOrder] = {}
        for value in uuids:
            order = self._lookup(value, None)
            if order is not None:
                found[order.uuid] = order
        for value in identifiers:
            order = self._lookup(None, value)
            if order is not None:
                found[order.uuid] = order
        return self._ok(ctx, self._snapshots(self._sorted(found.values(), order_by)))

    def _states_param(self, ctx: _Ctx, allowed: tuple[str, ...]) -> list[str] | None:
        state, states = _first(ctx.params, "state"), _all(ctx.params, "states[]")
        if state is not None and states:
            return None  # state와 states[]는 함께 쓸 수 없다
        wanted = states or ([state] if state is not None else list(allowed))
        return wanted if all(s in allowed for s in wanted) else None

    def _visible(self, market: str | None, states: Sequence[str]) -> list[FakeOrder]:
        return [
            o
            for o in self._orders.values()
            if o.state in states
            and market in (None, o.market)
            and self._hidden.get(o.identifier or "", 0) <= 0
        ]

    def _on_open_orders(self, ctx: _Ctx) -> httpx.Response:
        states = self._states_param(ctx, OPEN_STATES)
        order_by = _first(ctx.params, "order_by") or "desc"
        try:
            limit = int(_first(ctx.params, "limit") or "100")
            page = int(_first(ctx.params, "page") or "1")
        except ValueError:
            return self._error(ctx, 400, "invalid_parameter")
        if states is None or not 1 <= limit <= 100 or page < 1 or order_by not in ("asc", "desc"):
            return self._error(ctx, 400, "invalid_parameter")
        orders = self._sorted(self._visible(_first(ctx.params, "market"), states), order_by)
        return self._ok(ctx, self._snapshots(orders[(page - 1) * limit : page * limit]))

    def _on_closed_orders(self, ctx: _Ctx) -> httpx.Response:
        states = self._states_param(ctx, CLOSED_STATES)
        order_by = _first(ctx.params, "order_by") or "desc"
        try:
            limit = int(_first(ctx.params, "limit") or "100")
            start_text, end_text = _first(ctx.params, "start_time"), _first(ctx.params, "end_time")
            start = _parse_time(start_text) if start_text else None
            end = _parse_time(end_text) if end_text else None
        except ValueError:
            return self._error(ctx, 400, "invalid_parameter")
        if states is None or not 1 <= limit <= 1000 or order_by not in ("asc", "desc"):
            return self._error(ctx, 400, "invalid_parameter")
        # 구간이 없으면 요청 시각 이전 7일, 한쪽만 있으면 그쪽에서 7일. 최대 7일.
        if start is None and end is None:
            end = self._server_now()
        if start is None:
            assert end is not None
            start = end - SEVEN_DAYS
        if end is None:
            end = start + SEVEN_DAYS
        if end < start or end - start > SEVEN_DAYS:
            return self._error(ctx, 400, "invalid_parameter")
        orders = [
            o
            for o in self._visible(_first(ctx.params, "market"), states)
            if start <= o.created_at <= end
        ]
        return self._ok(ctx, self._snapshots(self._sorted(orders, order_by)[:limit]))

    def _on_cancel_order(self, ctx: _Ctx) -> httpx.Response:
        order_uuid, identifier = _first(ctx.params, "uuid"), _first(ctx.params, "identifier")
        if (order_uuid is None) == (identifier is None):
            return self._error(ctx, 400, "invalid_parameter")
        order = self._find(order_uuid, identifier)
        if order is None or not order.is_open:
            return self._error(ctx, 404, "order_not_found")
        # 응답은 취소 접수 시점의 모습(wait)이다. 조회하면 cancel.
        data = order.snapshot(omit_optional=self._omit_optional)
        order.state = "cancel"
        return self._ok(ctx, data)

    def _on_batch_cancel(self, ctx: _Ctx) -> httpx.Response:
        if self._forbid_batch_cancel:
            self._violate("batch_cancel", "일괄 취소(DELETE /v1/orders/open)는 쓰지 않는다(D-069)")
        pairs = _split(_first(ctx.params, "pairs"))
        excluded = set(_split(_first(ctx.params, "excluded_pairs")))
        quotes = _split(_first(ctx.params, "quote_currencies"))
        side = _first(ctx.params, "cancel_side") or "all"
        try:
            count = int(_first(ctx.params, "count") or "20")
        except ValueError:
            return self._error(ctx, 400, "invalid_parameter")
        if (pairs and quotes) or side not in ("all", "bid", "ask") or not 1 <= count <= 300:
            return self._error(ctx, 400, "invalid_parameter")
        targets = [
            o
            for o in self._sorted(self._orders.values(), _first(ctx.params, "order_by") or "desc")
            if o.is_open
            and (not pairs or o.market in pairs)
            and (not quotes or o.market.partition("-")[0] in quotes)
            and o.market not in excluded
            and side in ("all", o.side)
        ][:count]
        for order in targets:
            order.state = "cancel"
        return self._ok(
            ctx,
            {
                "success": {
                    "count": len(targets),
                    "orders": [{"uuid": o.uuid, "market": o.market} for o in targets],
                },
                "failed": {"count": 0, "orders": []},
            },
        )


__all__ = ["FakeProtocolViolation", "FakeUpbitServer", "RecordedRequest"]
