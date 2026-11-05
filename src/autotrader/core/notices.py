"""공지·시세 상태로 신규 매수 막기 판단(D-079 확정, D-092 대기·제안 A).

- announcement_blocks: trade 카테고리 공지의 글(제목, 본문이 있으면 본문)에 선택 코인의 티커나
  한글 이름과 막는 낱말("거래지원 종료"·"유의")이 함께 있으면 그 코인의 market을 돌려준다.
  공지에는 종목 코드 필드가 없어 글자로만 판단한다. 오탐은 매수만 막고 손실은 없다(D-079).
- ticker_blocks_buy: 시세 웹소켓의 market_state·delisting_date로 매수를 막을지(TS-26·104).

D-092는 사용자 선택 대기다. 판단 규칙은 아래 "판단 규칙" 절의 상수와 작은 함수에 모았다.
선택이 바뀌면 그 절만 고친다(예: B안은 _mentions_korean_name, C안은 BUYABLE_MARKET_STATES).
"""

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass

from autotrader.core.models import AnnouncementEvent, TickerEvent

# ── 판단 규칙(D-092 제안 A) ───────────────────────────────

BLOCKING_CATEGORIES = frozenset({"trade"})
"""매수 막기를 판단하는 공지 카테고리(정확히 같은 값만). 다른 카테고리는 기록만 한다(D-079)."""

SPACING_INSENSITIVE_KEYWORDS = ("거래지원 종료",)
"""띄어쓰기(공백·줄바꿈) 차이를 무시하고 찾는 낱말. "거래 지원 종료", "거래지원종료"도 맞는다."""

EXACT_KEYWORDS = ("유의",)
"""글자 그대로 찾는 낱말. "투자유의", 지정 해제 공지의 "유의"도 맞는다(D-079 오탐 수용)."""

UNICODE_FORM = "NFC"
"""비교 전에 제목·본문·코인 이름을 맞추는 유니코드 정규화 형식."""

TICKER_BOUNDARY = "A-Za-z0-9"
"""티커 앞뒤에 오면 안 되는 글자(ASCII 영숫자). BTC가 WBTC·BTCB·BTC2 안에서 맞지 않게 한다.
한글·괄호·하이픈·공백에 붙은 티커는 맞는다."""

BUYABLE_MARKET_STATES = frozenset({"ACTIVE"})
"""매수를 허용하는 market_state(대소문자 그대로). 그 밖(DELISTED, PREVIEW, 없음, 모르는 값)은 막는다."""


def _normalize(text: str) -> str:
    return unicodedata.normalize(UNICODE_FORM, text)


def _without_spaces(text: str) -> str:
    return "".join(text.split())


def _has_keyword(part: str) -> bool:
    """글 한 부분(제목 또는 본문)에 막는 낱말이 있는지."""
    if any(keyword in part for keyword in EXACT_KEYWORDS):
        return True
    squashed = _without_spaces(part)
    return any(_without_spaces(keyword) in squashed for keyword in SPACING_INSENSITIVE_KEYWORDS)


def _mentions_ticker(part: str, ticker: str) -> bool:
    """ASCII 영숫자 경계로, 대소문자 없이 찾는다. 빈 티커는 맞지 않는다."""
    if not ticker:
        return False
    pattern = rf"(?<![{TICKER_BOUNDARY}]){re.escape(ticker)}(?![{TICKER_BOUNDARY}])"
    return re.search(pattern, part, re.IGNORECASE | re.ASCII) is not None


def _mentions_korean_name(part: str, korean_name: str) -> bool:
    """부분 문자열(D-079 문구 그대로, 괄호도 글자 그대로). 빈 이름은 맞지 않는다.

    "비트코인"은 "비트코인캐시" 공지에도 맞는다(받아들인 오탐).
    """
    return bool(korean_name) and korean_name in part


# ── 공지 ──────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class CoinName:
    """판단에 쓰는 코인 이름. market은 KRW-BTC, ticker는 BTC, korean_name은 종목 목록 API 값."""

    market: str
    ticker: str
    korean_name: str


def _parts(event: AnnouncementEvent) -> tuple[str, ...]:
    """정규화한 제목과 본문(있으면). 따로 두어 제목 끝과 본문 앞이 붙어 낱말·티커가 생기지 않게 한다."""
    if event.body is None:
        return (_normalize(event.title),)
    return (_normalize(event.title), _normalize(event.body))


def _mentions(parts: tuple[str, ...], coin: CoinName) -> bool:
    ticker = _normalize(coin.ticker)
    korean_name = _normalize(coin.korean_name)
    return any(
        _mentions_ticker(part, ticker) or _mentions_korean_name(part, korean_name)
        for part in parts
    )


def announcement_blocks(event: AnnouncementEvent, coins: Sequence[CoinName]) -> frozenset[str]:
    """신규 매수를 막을 market 집합. 막을 것이 없으면 빈 집합.

    같은 글(제목·본문 어디든) 안에 코인 언급과 막는 낱말이 함께 있으면 그 코인을 넣는다.
    event_type(CREATED·UPDATED)은 상관없다. 코인마다 따로 판단한다.
    """
    if event.category not in BLOCKING_CATEGORIES:
        return frozenset()
    parts = _parts(event)
    if not any(_has_keyword(part) for part in parts):
        return frozenset()
    return frozenset(coin.market for coin in coins if _mentions(parts, coin))


# ── 시세 상태 ─────────────────────────────────────────────


def ticker_blocks_buy(event: TickerEvent) -> bool:
    """market_state가 매수 허용 상태이고 delisting_date가 없을 때만 False(보수적 판단)."""
    return event.market_state not in BUYABLE_MARKET_STATES or event.delisting_date is not None
