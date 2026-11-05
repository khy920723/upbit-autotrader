"""공지·ticker 상태로 신규 매수 막기(core/notices.py).

근거: D-079(확정), D-092(대기, 제안 A), TS-26·104.

announcement_blocks(event, coins) -> frozenset[str]: 신규 매수를 막을 market.

- category가 정확히 "trade"인 공지만 본다. 다른 카테고리는 항상 빈 집합이다.
- 글 = 제목, 본문(body)이 있으면 제목 + 줄바꿈 + 본문. 제목 끝과 본문 앞이 붙어
  티커가 새로 생기지 않는다. 비교 전에 제목·본문·코인 이름을 모두 NFC로 맞춘다.
- 코인 언급 = 티커 또는 한글 이름.
  - 티커: ASCII 영숫자 경계로 찾고 대소문자는 무시한다. BTC는 BTCB·WBTC·BTC2
    안에서 맞지 않고 (BTC)·KRW-BTC·btc·한글에 붙은 BTC는 맞는다.
  - 한글 이름: 부분 문자열(D-079 문구 그대로). 괄호 같은 글자도 글자 그대로
    비교한다. 그래서 "비트코인캐시" 공지는 비트코인도 막는다(오탐은 매수만 막고
    손실은 없다, D-079).
- 키워드 = "거래지원 종료" 또는 "유의".
  [제안 추가] "거래지원 종료"는 띄어쓰기 차이를 무시한다("거래 지원 종료",
  "거래지원종료"도 맞는다). 공식 문서 예시 제목이 "신규 거래 지원 안내"처럼
  "거래 지원"을 띄어 쓴다.
- 같은 글 안에 코인 언급과 키워드가 함께 있으면 그 코인의 market을 넣는다.
  여러 코인이 함께 나오면 모두 넣는다. event_type(CREATED·UPDATED)은 상관없다.

ticker_blocks_buy(event) -> bool: market_state가 "ACTIVE"이고 delisting_date가
None일 때만 False다. 그 밖(DELISTED, PREVIEW, None, 모르는 값, 소문자 active,
delisting_date 있음)은 True다(보수적 판단).
"""

import unicodedata
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from autotrader.core import models, notices

KST = timezone(timedelta(hours=9))

# 녹화 응답(tests/fixtures/upbit/market_all_details.json)의 한글 이름을 쓴다.
BTC = notices.CoinName(market="KRW-BTC", ticker="BTC", korean_name="비트코인")
ETH = notices.CoinName(market="KRW-ETH", ticker="ETH", korean_name="이더리움")
XRP = notices.CoinName(market="KRW-XRP", ticker="XRP", korean_name="엑스알피(리플)")
# 한 글자 티커(업비트 KRW-T). 다른 단어 안의 T에 맞으면 안 된다.
T = notices.CoinName(market="KRW-T", ticker="T", korean_name="쓰레스홀드")
COINS = (BTC, ETH, XRP)

OTHER_CATEGORIES = ["notice", "wallet", "maintenance", "digital_asset", "nft", "service", "event"]


def notice(
    title: str, *, category: str = "trade", body: str | None = None, event_type: str = "CREATED"
) -> models.AnnouncementEvent:
    when = datetime(2026, 11, 5, 9, 0, tzinfo=KST)
    return models.AnnouncementEvent(
        uuid="562593104",
        title=title,
        category=category,
        url="https://www.upbit.com/service_center/notice?id=562593104&view=share",
        event_type=event_type,
        listed_at=when,
        first_listed_at=when,
        body=body,
        timestamp_ms=1752566400123,
    )


def blocks(title: str, coins=COINS, **kwargs) -> frozenset[str]:
    return notices.announcement_blocks(notice(title, **kwargs), coins)


def ticker(market_state: str | None, delisting_date: date | None) -> models.TickerEvent:
    return models.TickerEvent(
        market="KRW-BTC",
        trade_price=Decimal("109868000.0"),
        signed_change_rate=Decimal("0.006439793"),
        acc_trade_price_24h=Decimal("198189163442.74924"),
        acc_trade_volume_24h=Decimal("1807.38027625"),
        market_state=market_state,
        delisting_date=delisting_date,
        timestamp_ms=1787729042606,
        stream_type="REALTIME",
    )


# ── CoinName ──────────────────────────────────────────────


def test_coin_name_is_an_immutable_hashable_value():
    assert (BTC.market, BTC.ticker, BTC.korean_name) == ("KRW-BTC", "BTC", "비트코인")
    assert {BTC, notices.CoinName(market="KRW-BTC", ticker="BTC", korean_name="비트코인")} == {BTC}
    with pytest.raises(AttributeError):
        BTC.ticker = "ETH"  # type: ignore[misc]


# ── announcement_blocks: 막는 공지 ────────────────────────


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("[거래지원종료] 리플(XRP) 거래지원 종료 안내 (11/20 15:00)", {"KRW-XRP"}),
        ("[거래] 비트코인(BTC) 유의 종목 지정 안내", {"KRW-BTC"}),
        ("[거래] 이더리움(ETH) 투자유의 촉구 안내", {"KRW-ETH"}),
        ("[거래] 유의 종목 지정 기간 연장 안내 (XRP)", {"KRW-XRP"}),
        ("[거래] 엑스알피(리플) 유의 종목 지정 안내", {"KRW-XRP"}),
        ("[거래] BTC, ETH 거래지원 종료 안내", {"KRW-BTC", "KRW-ETH"}),
        ("[거래] 비트코인·이더리움 유의 종목 지정 안내", {"KRW-BTC", "KRW-ETH"}),
    ],
)
def test_trade_notice_with_coin_and_keyword_blocks_that_coin(title, expected):
    assert blocks(title) == expected


def test_result_is_a_frozenset_of_markets():
    result = blocks("[거래] 비트코인(BTC) 유의 종목 지정 안내")

    assert isinstance(result, frozenset)
    assert result == frozenset({"KRW-BTC"})


@pytest.mark.parametrize("event_type", ["CREATED", "UPDATED"])
def test_created_and_updated_notices_are_judged_the_same(event_type):
    assert blocks("[거래] 리플(XRP) 거래지원 종료 안내", event_type=event_type) == {"KRW-XRP"}


def test_release_notice_also_blocks():
    # "유의"만 보므로 지정 해제 공지도 막는다. 해제는 종목 목록 API·시세 웹소켓 값으로
    # 확인되거나 사용자가 직접 한다(D-079). 오탐은 매수만 막는다.
    assert blocks("[거래] 이더리움(ETH) 유의 종목 지정 해제 안내") == {"KRW-ETH"}


# ── announcement_blocks: 막지 않는 공지 ───────────────────


@pytest.mark.parametrize(
    "title",
    [
        "[거래] 신규 거래 지원 안내 ...",  # 공식 문서 예시 제목
        "[거래] 비트코인(BTC) 원화 마켓 추가 안내",
        "[거래] 이더리움(ETH) 신규 거래지원 안내",
    ],
)
def test_trade_notice_without_keyword_blocks_nothing(title):
    assert blocks(title) == frozenset()


def test_trade_notice_about_other_coins_blocks_nothing():
    assert blocks("[거래] 썸씽(SSX) 거래지원 종료 안내") == frozenset()


def test_keyword_without_any_coin_blocks_nothing():
    assert blocks("[거래] 유의 종목 지정 안내") == frozenset()


@pytest.mark.parametrize("category", OTHER_CATEGORIES)
def test_other_categories_block_nothing(category):
    # 다른 카테고리 공지는 기록만 한다(D-079).
    title = "[입출금] 비트코인(BTC) 거래지원 종료에 따른 입출금 유의 안내"

    assert blocks(title, category=category) == frozenset()


def test_no_selected_coins_blocks_nothing():
    assert blocks("[거래] 비트코인(BTC) 유의 종목 지정 안내", coins=()) == frozenset()


def test_only_selected_coins_are_returned():
    title = "[거래] 비트코인(BTC), 이더리움(ETH) 유의 종목 지정 안내"

    assert blocks(title, coins=(ETH, XRP)) == {"KRW-ETH"}


# ── 티커 경계와 대소문자 ──────────────────────────────────


@pytest.mark.parametrize(
    ("title", "blocked"),
    [
        ("[거래] WBTC 거래지원 종료 안내", False),
        ("[거래] BTCB 유의 종목 지정 안내", False),
        ("[거래] BTC2 유의 종목 지정 안내", False),
        ("[거래] (BTC) 유의 종목 지정 안내", True),
        ("[거래] KRW-BTC 마켓 유의 안내", True),
        ("[거래] BTC/KRW 유의 안내", True),
        ("[거래] btc 유의 종목 지정 안내", True),
        ("[거래] Btc 유의 종목 지정 안내", True),
        ("[거래]BTC유의종목지정", True),
    ],
)
def test_ticker_matches_only_on_alphanumeric_boundaries(title, blocked):
    assert blocks(title, coins=(BTC,)) == ({"KRW-BTC"} if blocked else frozenset())


@pytest.mark.parametrize(
    ("title", "blocked"),
    [
        ("[거래] NFT 마켓 유의 안내", False),
        ("[거래] ETH 유의 종목 지정 안내", False),
        ("[거래] 쓰레스홀드(T) 유의 종목 지정 안내", True),
        ("[거래] T 거래지원 종료 안내", True),
    ],
)
def test_one_letter_ticker_does_not_match_inside_words(title, blocked):
    assert blocks(title, coins=(T,)) == ({"KRW-T"} if blocked else frozenset())


def test_korean_name_is_a_plain_substring():
    # D-079 문구 그대로 부분 문자열이다. 비트코인캐시 공지는 비트코인도 막는다(받아들인 오탐).
    assert blocks("[거래] 비트코인캐시(BCH) 거래지원 종료 안내", coins=(BTC,)) == {"KRW-BTC"}


def test_korean_name_with_parentheses_is_compared_literally():
    # "엑스알피(리플)"의 괄호를 정규식 묶음으로 읽으면 "엑스알피리플"에만 맞는다.
    assert blocks("[거래] 엑스알피리플 유의 종목 지정 안내", coins=(XRP,)) == frozenset()
    assert blocks("[거래] 엑스알피(리플) 유의 종목 지정 안내", coins=(XRP,)) == {"KRW-XRP"}


# ── 키워드 띄어쓰기(제안 추가) ────────────────────────────


@pytest.mark.parametrize("keyword", ["거래지원 종료", "거래지원종료", "거래 지원 종료"])
def test_delisting_keyword_ignores_spacing(keyword):
    assert blocks(f"[거래] 리플(XRP) {keyword} 안내") == {"KRW-XRP"}


# ── 본문 ──────────────────────────────────────────────────


def test_body_is_searched_when_present():
    body = (
        "다음 디지털 자산의 거래지원이 종료됩니다.\n대상: 비트코인(BTC)\n거래지원 종료 일시: 11/20"
    )

    assert blocks("[거래] 디지털 자산 거래지원 종료 안내", body=body) == {"KRW-BTC"}


def test_coin_in_title_and_keyword_in_body_go_together():
    body = "해당 디지털 자산이 유의 종목으로 지정되었습니다."

    assert blocks("[거래] 이더리움(ETH) 관련 안내", body=body) == {"KRW-ETH"}


def test_missing_body_means_title_only():
    assert blocks("[거래] 이더리움(ETH) 관련 안내", body=None) == frozenset()


def test_title_and_body_do_not_glue_into_a_ticker():
    # 제목 끝 "B"와 본문 앞 "TC"가 붙어 BTC가 되면 안 된다.
    assert blocks("[거래] 거래지원 종료 안내 B", body="TC 관련 공지") == frozenset()


# ── 유니코드 정규화(NFC) ──────────────────────────────────


def test_decomposed_title_still_matches():
    title = unicodedata.normalize("NFD", "[거래] 비트코인 유의 종목 지정 안내")
    assert title != unicodedata.normalize("NFC", title)

    assert blocks(title, coins=(BTC,)) == {"KRW-BTC"}


def test_decomposed_coin_name_still_matches():
    coin = notices.CoinName(
        market="KRW-BTC", ticker="BTC", korean_name=unicodedata.normalize("NFD", "비트코인")
    )

    assert blocks("[거래] 비트코인 거래지원 종료 안내", coins=(coin,)) == {"KRW-BTC"}


def test_decomposed_body_still_matches():
    body = unicodedata.normalize("NFD", "대상: 이더리움, 거래지원 종료")

    assert blocks("[거래] 안내", body=body) == {"KRW-ETH"}


# ── 속성(hypothesis) ──────────────────────────────────────

PIECES = [
    "[거래]",
    "BTC",
    "btc",
    "WBTC",
    "BTCB",
    "ETH",
    "XRP",
    "T",
    "NFT",
    "비트코인",
    "비트코인캐시",
    "이더리움",
    "엑스알피(리플)",
    "리플",
    "쓰레스홀드",
    "거래지원 종료",
    "거래 지원 종료",
    "유의",
    "투자유의",
    "신규",
    "안내",
    "(",
    ")",
    "-",
    "/",
    " ",
    "\n",
]
POOL = (BTC, ETH, XRP, T)

texts = st.lists(st.sampled_from(PIECES), max_size=12).map("".join)
bodies = st.none() | texts
coin_sets = st.lists(st.sampled_from(POOL), unique=True, max_size=len(POOL)).map(tuple)


@given(
    category=st.sampled_from(OTHER_CATEGORIES) | st.text().filter(lambda c: c != "trade"),
    title=st.text() | texts,
    body=st.none() | st.text() | texts,
)
def test_non_trade_categories_never_block(category, title, body):
    event = notice(title, category=category, body=body)

    assert notices.announcement_blocks(event, POOL) == frozenset()


@given(title=texts, body=bodies, coins=coin_sets)
def test_blocked_markets_are_among_the_selected_coins(title, body, coins):
    result = notices.announcement_blocks(notice(title, body=body), coins)

    assert result <= {coin.market for coin in coins}


@given(title=texts, body=bodies, first=coin_sets, second=coin_sets)
def test_each_coin_is_judged_on_its_own(title, body, first, second):
    event = notice(title, body=body)
    together = tuple(dict.fromkeys(first + second))

    assert notices.announcement_blocks(event, together) == (
        notices.announcement_blocks(event, first) | notices.announcement_blocks(event, second)
    )


@given(title=texts, body=bodies, coins=coin_sets)
def test_normalization_form_does_not_matter(title, body, coins):
    def nfd(text):
        return None if text is None else unicodedata.normalize("NFD", text)

    nfc = notices.announcement_blocks(notice(title, body=body), coins)

    assert notices.announcement_blocks(notice(nfd(title), body=nfd(body)), coins) == nfc


# "유"와 "종"이 없으면 "유의"도 "거래지원 종료"도 만들 수 없다(완성형 음절만 쓰므로 NFC로도
# 새로 생기지 않는다).
NO_KEYWORD_ALPHABET = list(
    "BTCETHXRPbtc0123 ()-[]/,.\n비트코인이더리움엑스알피리플거래지원안내신규마켓"
)


@given(
    title=st.text(alphabet=NO_KEYWORD_ALPHABET, max_size=60),
    body=st.none() | st.text(alphabet=NO_KEYWORD_ALPHABET, max_size=60),
)
def test_without_keywords_nothing_is_blocked(title, body):
    assert notices.announcement_blocks(notice(title, body=body), POOL) == frozenset()


# ── ticker_blocks_buy (TS-26·104) ─────────────────────────


def test_active_market_without_delisting_date_allows_buying():
    assert notices.ticker_blocks_buy(ticker("ACTIVE", None)) is False


@pytest.mark.parametrize("state", ["DELISTED", "PREVIEW", None, "active", "SUSPENDED", ""])
def test_market_that_is_not_active_blocks_buying(state):
    # PREVIEW(입금지원)와 값이 없는 경우도 막는다(보수적 판단, D-092 제안).
    assert notices.ticker_blocks_buy(ticker(state, None)) is True


@pytest.mark.parametrize("state", ["ACTIVE", "DELISTED", None])
def test_delisting_date_blocks_buying(state):
    # TS-26: delisting_date가 생기면 거래 상태와 상관없이 매수를 막는다.
    assert notices.ticker_blocks_buy(ticker(state, date(2026, 11, 20))) is True


@given(
    state=st.none() | st.sampled_from(["ACTIVE", "DELISTED", "PREVIEW"]) | st.text(max_size=12),
    delisting=st.none() | st.dates(min_value=date(2020, 1, 1), max_value=date(2035, 12, 31)),
)
def test_ticker_blocks_buy_unless_active_and_listed(state, delisting):
    expected = not (state == "ACTIVE" and delisting is None)

    assert notices.ticker_blocks_buy(ticker(state, delisting)) is expected
