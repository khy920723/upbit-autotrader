"""공지·ticker 상태로 신규 매수 막기(core/notices.py).

근거: D-079(확정), D-092(확정 A, 2026-11-07 사용자 결정), TS-26·104.

announcement_blocks(event, coins) -> frozenset[str]: 신규 매수를 막을 market.

- category가 정확히 "trade"인 공지만 본다. 다른 카테고리는 항상 빈 집합이다.
- 글 = 제목과 본문(body가 있으면). 둘은 따로 본다(이어 붙이지 않는다). 그래서 제목
  끝과 본문 앞이 붙어 티커나 키워드가 새로 생기지 않는다. 코인 언급과 키워드는 제목·본문
  어디에 있어도 같은 글로 본다.
- 비교 전에 제목·본문·코인 이름을 NFKC로 맞추고(전각 ＢＴＣ → BTC) 서식 문자(유니코드
  Cf, 예: 폭 없는 공백 U+200B)를 지운다.
- 코인 언급 = 티커 또는 한글 이름. 빈 티커·빈 한글 이름은 아무것에도 맞지 않는다.
  - 티커: ASCII 영숫자 경계로 찾고 대소문자는 무시한다. BTC는 BTCB·WBTC·BTC2
    안에서 맞지 않고 (BTC)·KRW-BTC·btc·한글에 붙은 BTC는 맞는다.
  - [D-092 A] 마켓 이름은 언급이 아니다: 티커 바로 뒤에 "마켓"이 오면(공백 허용,
    "KRW, BTC, USDT 마켓"처럼 쉼표·가운뎃점·빗금으로 이은 티커 목록 뒤도) 그 티커는
    언급이 아니다. 단 마켓 코드의 뒷부분(KRW-BTC 마켓의 BTC)은 언급이다.
  - [D-092 A] 마켓 코드의 앞부분(호가 통화, BTC-ETH의 BTC·USDT-SSX의 USDT)은
    언급이 아니다. 뒷부분(KRW-BTC의 BTC)은 언급이다.
  - 한글 이름: 부분 문자열(D-079 문구 그대로). 괄호 같은 글자도 글자 그대로
    비교한다. 그래서 "비트코인캐시" 공지는 비트코인도 막는다(오탐은 매수만 막고
    손실은 없다, D-079).
- 키워드 = "거래지원 종료" 또는 "유의".
  [D-092 A] "거래지원 종료"는 띄어쓰기 차이를 무시하고("거래 지원 종료",
  "거래지원종료"도 맞는다) 사이에 조사 을·이·은·의 하나를 허용한다("거래지원을 종료",
  "거래 지원이 종료"). 공식 문서 예시 제목이 "신규 거래 지원 안내"처럼 "거래 지원"을
  띄어 쓴다.
  [D-092 A] "유의사항"·"유의 사항"(안내 문구)은 "유의" 키워드가 아니다.
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
    """TS-104: 거래 공지에 코인과 키워드가 함께 있으면 그 코인을 막는다."""
    assert blocks(title) == expected


def test_result_is_a_frozenset_of_markets():
    """결과는 market의 frozenset이다."""
    result = blocks("[거래] 비트코인(BTC) 유의 종목 지정 안내")

    assert isinstance(result, frozenset)
    assert result == frozenset({"KRW-BTC"})


@pytest.mark.parametrize("event_type", ["CREATED", "UPDATED"])
def test_created_and_updated_notices_are_judged_the_same(event_type):
    """TS-104: 생성·수정 공지는 같게 판단한다."""
    assert blocks("[거래] 리플(XRP) 거래지원 종료 안내", event_type=event_type) == {"KRW-XRP"}


def test_release_notice_also_blocks():
    """D-092 A·TS-104·TS-155: 지정 해제 공지도 막는다(D-079 오탐 수용)."""
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
    """TS-104: 키워드가 없는 거래 공지는 아무것도 막지 않는다."""
    assert blocks(title) == frozenset()


def test_trade_notice_about_other_coins_blocks_nothing():
    """TS-104: 고르지 않은 코인의 공지는 막지 않는다."""
    assert blocks("[거래] 썸씽(SSX) 거래지원 종료 안내") == frozenset()


def test_keyword_without_any_coin_blocks_nothing():
    """TS-104: 코인 언급 없는 키워드 공지는 막지 않는다."""
    assert blocks("[거래] 유의 종목 지정 안내") == frozenset()


@pytest.mark.parametrize("category", OTHER_CATEGORIES)
def test_other_categories_block_nothing(category):
    """TS-104: 거래 외 카테고리 공지는 막지 않는다."""
    # 다른 카테고리 공지는 기록만 한다(D-079).
    title = "[입출금] 비트코인(BTC) 거래지원 종료에 따른 입출금 유의 안내"

    assert blocks(title, category=category) == frozenset()


def test_no_selected_coins_blocks_nothing():
    """TS-104: 고른 코인이 없으면 막을 것이 없다."""
    assert blocks("[거래] 비트코인(BTC) 유의 종목 지정 안내", coins=()) == frozenset()


def test_only_selected_coins_are_returned():
    """TS-104: 고른 코인의 market만 돌려준다."""
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
    """D-092 A·TS-104·TS-155: 티커는 영숫자 경계로, 대소문자 없이 찾는다."""
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
    """D-092 A·TS-104·TS-155: 한 글자 티커도 영숫자 경계로만 맞는다."""
    assert blocks(title, coins=(T,)) == ({"KRW-T"} if blocked else frozenset())


def test_korean_name_is_a_plain_substring():
    """D-092 A(B 아님)·TS-104·TS-155: 한글 이름은 부분 문자열이다."""
    # D-079 문구 그대로 부분 문자열이다. 비트코인캐시 공지는 비트코인도 막는다(받아들인 오탐).
    assert blocks("[거래] 비트코인캐시(BCH) 거래지원 종료 안내", coins=(BTC,)) == {"KRW-BTC"}


def test_korean_name_with_parentheses_is_compared_literally():
    """D-092 A·TS-104·TS-155: 한글 이름은 괄호까지 글자 그대로 비교한다."""
    # "엑스알피(리플)"의 괄호를 정규식 묶음으로 읽으면 "엑스알피리플"에만 맞는다.
    assert blocks("[거래] 엑스알피리플 유의 종목 지정 안내", coins=(XRP,)) == frozenset()
    assert blocks("[거래] 엑스알피(리플) 유의 종목 지정 안내", coins=(XRP,)) == {"KRW-XRP"}


# ── 키워드 띄어쓰기(D-092 A) ────────────────────────────


@pytest.mark.parametrize("keyword", ["거래지원 종료", "거래지원종료", "거래 지원 종료"])
def test_delisting_keyword_ignores_spacing(keyword):
    """D-092 A·TS-104·TS-155: 공백을 지운 뒤 '거래지원 종료'를 찾는다."""
    assert blocks(f"[거래] 리플(XRP) {keyword} 안내") == {"KRW-XRP"}


# ── 키워드 변형과 예외(D-092 A) ────────────────────────


@pytest.mark.parametrize(
    "phrase",
    [
        "거래지원을 종료합니다",
        "거래 지원이 종료됩니다",
        "거래지원이종료",
        "거래 지원을  종료",
        "거래지원의 종료",
        "거래지원은 종료",
        "거래\n지원 종료",
    ],
)
def test_delisting_keyword_accepts_particles_and_spacing(phrase):
    """D-092 A·TS-104·TS-155: 거래지원(을|이|은|의)?종료."""
    assert blocks(f"[거래] 비트코인(BTC) {phrase}", coins=(BTC,)) == {"KRW-BTC"}


@pytest.mark.parametrize("phrase", ["거래지원 안내", "거래지원 재개", "거래지원들 종료"])
def test_delisting_keyword_needs_the_end_word(phrase):
    """D-092 A·TS-104·TS-155: '종료'가 없거나 다른 말이 끼면 키워드가 아니다."""
    assert blocks(f"[거래] 비트코인(BTC) {phrase}", coins=(BTC,)) == frozenset()


@pytest.mark.parametrize(
    "body",
    [
        "KRW 마켓 지원\n※ 투자 유의사항: 변동성이 큽니다",
        "투자 유의 사항을 확인하세요",
        "유의\n사항",
    ],
)
def test_caution_notes_are_not_the_caution_keyword(body):
    """D-092 A·TS-104·TS-155: '유의' 뒤에 '사항'이 오면 키워드가 아니다."""
    assert blocks("[거래] 비트코인(BTC) 신규 거래지원 안내", coins=(BTC,), body=body) == frozenset()


def test_caution_keyword_still_matches_next_to_a_caution_note():
    """D-092 A·TS-104·TS-155: 유의사항 옆의 다른 '유의'는 맞는다."""
    body = "유의사항을 확인하세요. 비트코인은 유의 종목으로 지정되었습니다."

    assert blocks("[거래] 안내", coins=(BTC,), body=body) == {"KRW-BTC"}


# ── 마켓 이름은 코인 언급이 아니다(D-092 A) ─────────────

USDT = notices.CoinName(market="KRW-USDT", ticker="USDT", korean_name="테더")


@pytest.mark.parametrize(
    ("title", "body"),
    [
        ("[거래] BTC 마켓 디지털 자산 거래지원 종료 안내 (SSX)", None),
        ("[거래] BTC마켓 디지털 자산 거래지원 종료 안내", None),
        ("[거래] USDT 마켓 디지털 자산 거래지원 종료 안내", None),
        ("[거래] 썸씽(SSX) 거래지원 종료 안내", "대상 마켓: KRW, BTC, USDT 마켓"),
        ("[거래] 썸씽(SSX) 거래지원 종료 안내", "대상: BTC·USDT 마켓"),
        ("[거래] BTC-SSX, USDT-SSX 거래지원 종료 안내", None),
        ("[거래] 썸씽(SSX) 유의 종목 지정", "마켓 코드: BTC-SSX"),
    ],
)
def test_market_names_are_not_coin_mentions(title, body):
    """D-092 A·TS-104·TS-155: 마켓 이름·마켓 코드 앞부분은 언급이 아니다."""
    assert blocks(title, coins=(BTC, USDT), body=body) == frozenset()


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("[거래] KRW-BTC 마켓 유의 안내", {"KRW-BTC"}),
        ("[거래] USDT-BTC 거래지원 종료 안내", {"KRW-BTC"}),
        ("[거래] BTC-USDT 거래지원 종료 안내", {"KRW-USDT"}),
        ("[거래] 비트코인(BTC) 마켓 유의 안내", {"KRW-BTC"}),
        ("[거래] BTC 마켓 비트코인 유의 안내", {"KRW-BTC"}),
        ("[거래] BTC 마켓에서 BTC 거래지원 종료", {"KRW-BTC"}),
        ("[거래] BTC, ETH 거래지원 종료 안내", {"KRW-BTC"}),
    ],
)
def test_coin_mentions_next_to_market_names_still_match(title, expected):
    """D-092 A·TS-104·TS-155: 마켓 코드 뒷부분과 다른 자리의 티커는 언급이다."""
    assert blocks(title, coins=(BTC, USDT)) == expected


# ── 빈 이름 ───────────────────────────────────────────────


@pytest.mark.parametrize(
    ("ticker", "korean_name"), [("", ""), ("\u200b", "\u200b"), ("", "비트코인"), ("BTC", "")]
)
def test_empty_names_match_nothing_by_themselves(ticker, korean_name):
    """D-092 A·TS-104·TS-155: 빈 티커·빈 이름은 아무것에도 맞지 않는다."""
    coin = notices.CoinName(market="KRW-X", ticker=ticker, korean_name=korean_name)
    title = "[거래] 거래지원 종료 유의 안내 () - / 마켓"

    assert blocks(title, coins=(coin,)) == frozenset()


def test_empty_names_do_not_block_on_unrelated_notices():
    """D-092 A·TS-104·TS-155: 빈 이름 코인은 다른 코인 공지로 막히지 않는다."""
    empty = notices.CoinName(market="KRW-EMPTY", ticker="", korean_name="")

    assert blocks("[거래] 비트코인(BTC) 유의 종목 지정 안내", coins=(BTC, empty)) == {"KRW-BTC"}


# ── 본문 ──────────────────────────────────────────────────


def test_body_is_searched_when_present():
    """TS-104·TS-155: 본문이 있으면 본문도 찾는다."""
    body = (
        "다음 디지털 자산의 거래지원이 종료됩니다.\n대상: 비트코인(BTC)\n거래지원 종료 일시: 11/20"
    )

    assert blocks("[거래] 디지털 자산 거래지원 종료 안내", body=body) == {"KRW-BTC"}


def test_coin_in_title_and_keyword_in_body_go_together():
    """D-092 A·TS-104·TS-155: 제목의 코인과 본문의 키워드도 짝이 된다."""
    body = "해당 디지털 자산이 유의 종목으로 지정되었습니다."

    assert blocks("[거래] 이더리움(ETH) 관련 안내", body=body) == {"KRW-ETH"}


def test_missing_body_means_title_only():
    """TS-104·TS-155: 본문이 없으면 제목만 본다."""
    assert blocks("[거래] 이더리움(ETH) 관련 안내", body=None) == frozenset()


def test_title_and_body_do_not_glue_into_a_ticker():
    """D-092 A·TS-104·TS-155: 제목과 본문은 이어 붙이지 않는다(티커)."""
    # 제목 끝 "B"와 본문 앞 "TC"가 붙어 BTC가 되면 안 된다.
    assert blocks("[거래] 거래지원 종료 안내 B", body="TC 관련 공지") == frozenset()


def test_title_and_body_do_not_glue_into_a_keyword():
    """D-092 A·TS-104·TS-155: 제목과 본문은 이어 붙이지 않는다(키워드)."""
    # 제목 끝 "거래지원"과 본문 앞 "종료"가 붙어 "거래지원종료"가 되면 안 된다.
    assert blocks("[거래] 비트코인(BTC) 거래지원", body="종료 안내") == frozenset()
    assert blocks("[거래] 비트코인(BTC) 거래지원", body="\n종료 안내") == frozenset()


# ── 유니코드 정규화(NFKC)와 서식 문자 ────────────────────


@pytest.mark.parametrize(
    "title",
    [
        "[거래] ＢＴＣ 유의 종목 지정 안내",  # 전각 영문
        "[거래] （ｂｔｃ） 유의 종목 지정 안내",  # 전각 괄호·소문자
        "[거래] B\u200bTC 유의 종목 지정 안내",  # 폭 없는 공백(Cf)
        "[거래] 비트\u200d코인 유의 종목 지정 안내",  # 폭 없는 이음자(Cf)
        "[거래] 비트코인(BTC) 거래지원\u200b종료 안내",
        "[거래] 비트코인(BTC) 유\ufeff의 종목 지정 안내",  # BOM(Cf)
    ],
)
def test_compatibility_forms_and_format_characters_still_match(title):
    """D-092 A·TS-104·TS-155: 제목을 NFKC로 맞추고 서식 문자를 지운다."""
    assert blocks(title, coins=(BTC,)) == {"KRW-BTC"}


def test_full_width_coin_name_still_matches():
    """D-092 A·TS-104·TS-155: 코인 이름도 NFKC로 맞추고 서식 문자를 지운다."""
    coin = notices.CoinName(market="KRW-BTC", ticker="ＢＴＣ", korean_name="비트\u200b코인")

    assert blocks("[거래] BTC 유의 종목 지정 안내", coins=(coin,)) == {"KRW-BTC"}
    assert blocks("[거래] 비트코인 유의 종목 지정 안내", coins=(coin,)) == {"KRW-BTC"}


def test_format_characters_do_not_break_ticker_boundaries():
    """D-092 A·TS-104·TS-155: 서식 문자를 지운 뒤 티커 경계를 본다."""
    # Cf를 지우면 W와 BTC가 붙어 WBTC가 된다. 그러면 BTC 언급이 아니다.
    assert blocks("[거래] W\u200bBTC 유의 종목 지정 안내", coins=(BTC,)) == frozenset()


def test_decomposed_title_still_matches():
    """D-092 A·TS-104·TS-155: 분해형(NFD) 제목도 NFKC로 맞춘다."""
    title = unicodedata.normalize("NFD", "[거래] 비트코인 유의 종목 지정 안내")
    assert title != unicodedata.normalize("NFC", title)

    assert blocks(title, coins=(BTC,)) == {"KRW-BTC"}


def test_decomposed_coin_name_still_matches():
    """D-092 A·TS-104·TS-155: 분해형(NFD) 코인 이름도 NFKC로 맞춘다."""
    coin = notices.CoinName(
        market="KRW-BTC", ticker="BTC", korean_name=unicodedata.normalize("NFD", "비트코인")
    )

    assert blocks("[거래] 비트코인 거래지원 종료 안내", coins=(coin,)) == {"KRW-BTC"}


def test_decomposed_body_still_matches():
    """D-092 A·TS-104·TS-155: 분해형(NFD) 본문도 NFKC로 맞춘다."""
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
    """TS-104: 거래 외 카테고리는 무엇이 와도 막지 않는다."""
    event = notice(title, category=category, body=body)

    assert notices.announcement_blocks(event, POOL) == frozenset()


@given(title=texts, body=bodies, coins=coin_sets)
def test_blocked_markets_are_among_the_selected_coins(title, body, coins):
    """TS-104: 막힌 market은 항상 고른 코인 안에 있다."""
    result = notices.announcement_blocks(notice(title, body=body), coins)

    assert result <= {coin.market for coin in coins}


@given(title=texts, body=bodies, first=coin_sets, second=coin_sets)
def test_each_coin_is_judged_on_its_own(title, body, first, second):
    """TS-104: 코인마다 따로 판단한다."""
    event = notice(title, body=body)
    together = tuple(dict.fromkeys(first + second))

    assert notices.announcement_blocks(event, together) == (
        notices.announcement_blocks(event, first) | notices.announcement_blocks(event, second)
    )


@given(title=texts, body=bodies, coins=coin_sets)
def test_normalization_form_does_not_matter(title, body, coins):
    """D-092 A·TS-104·TS-155: 정규화 형식이 달라도 판단이 같다."""

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
    """TS-104: 키워드를 만들 수 없는 글은 막지 않는다."""
    assert notices.announcement_blocks(notice(title, body=body), POOL) == frozenset()


# ── ticker_blocks_buy (TS-26·104) ─────────────────────────


def test_active_market_without_delisting_date_allows_buying():
    """D-092 A·TS-26·TS-104: ACTIVE이고 delisting_date가 없을 때만 산다."""
    assert notices.ticker_blocks_buy(ticker("ACTIVE", None)) is False


@pytest.mark.parametrize("state", ["DELISTED", "PREVIEW", None, "active", "SUSPENDED", ""])
def test_market_that_is_not_active_blocks_buying(state):
    """D-092 A(C 아님)·TS-26·TS-104: PREVIEW·값 없음도 막는다."""
    # PREVIEW(입금지원)와 값이 없는 경우도 막는다(보수적 판단, D-092 A).
    assert notices.ticker_blocks_buy(ticker(state, None)) is True


@pytest.mark.parametrize("state", ["ACTIVE", "DELISTED", None])
def test_delisting_date_blocks_buying(state):
    """D-092 A·TS-26·TS-104: delisting_date가 있으면 상태와 상관없이 막는다."""
    # TS-26: delisting_date가 생기면 거래 상태와 상관없이 매수를 막는다.
    assert notices.ticker_blocks_buy(ticker(state, date(2026, 11, 20))) is True


@given(
    state=st.none() | st.sampled_from(["ACTIVE", "DELISTED", "PREVIEW"]) | st.text(max_size=12),
    delisting=st.none() | st.dates(min_value=date(2020, 1, 1), max_value=date(2035, 12, 31)),
)
def test_ticker_blocks_buy_unless_active_and_listed(state, delisting):
    """D-092 A·TS-26·TS-104: ACTIVE·날짜 없음만 허용한다."""
    expected = not (state == "ACTIVE" and delisting is None)

    assert notices.ticker_blocks_buy(ticker(state, delisting)) is expected


# ── D-092 A 확인 ──────────────────────────────────────────
# 사용자가 2026-11-07에 D-092를 "A: 제안 그대로"로 정했다. 위 구역이 이미 고정한 성질은
# docstring 첫 줄에 "D-092 A"로 표시했고, 여기에는 빠진 경우와 선택지 B·C와 갈리는 경우만 둔다.


@pytest.mark.parametrize(
    "title",
    [
        "[거래] 이더리움클래식(ETC) 거래지원 종료 안내",
        "[거래] 이더리움 클래식(ETC) 유의 종목 지정 안내",
    ],
)
def test_d092a_korean_name_inside_a_longer_name_still_blocks(title):
    """D-092 A(B 아님)·TS-104·TS-155: "이더리움 클래식" 공지가 이더리움을 막는다.

    B(한글 이름 뒤에 다른 한글이 이어지면 맞지 않음)였다면 붙여 쓴 "이더리움클래식"은
    맞지 않는다. A는 부분 문자열이라 막는다(오탐은 매수만 막는다).
    """
    assert blocks(title, coins=(ETH,)) == {"KRW-ETH"}


@pytest.mark.parametrize(
    ("title", "coin", "expected"),
    [
        ("[거래] 이더리움이 유의 종목으로 지정되었습니다", ETH, {"KRW-ETH"}),
        ("[거래] 비트코인의 거래지원 종료 안내", BTC, {"KRW-BTC"}),
        ("[거래] 비트코인은 거래지원이 종료됩니다", BTC, {"KRW-BTC"}),
    ],
)
def test_d092a_korean_name_followed_by_a_particle_blocks(title, coin, expected):
    """D-092 A(B 아님)·TS-104·TS-155: 조사가 붙은 한글 이름(티커 없음)도 막는다."""
    assert blocks(title, coins=(coin,)) == expected


def test_d092a_keyword_in_title_and_coin_in_body_go_together():
    """D-092 A·TS-104·TS-155: 제목의 키워드와 본문의 코인도 짝이 된다(반대 방향)."""
    body = "대상 디지털 자산: 이더리움(ETH)"

    assert blocks("[거래] 디지털 자산 거래지원 종료 안내", body=body) == {"KRW-ETH"}


@pytest.mark.parametrize(
    ("title", "body"),
    [
        ("[거래] 유의 종목 지정 안내", "대상: ＥＴＨ"),  # 전각 티커
        ("[거래] 유의 종목 지정 안내", "대상: 이더\u200b리움"),  # 폭 없는 공백(Cf)
        ("[거래] 이더리움(ETH) 안내", "거래지원\u200b종료 일시: 11/20"),
        ("[거래] 이더리움(ETH) 안내", "유\ufeff의 종목으로 지정되었습니다"),  # BOM(Cf)
    ],
)
def test_d092a_body_is_normalized_like_the_title(title, body):
    """D-092 A·TS-104·TS-155: 본문도 NFKC로 맞추고 서식 문자를 지운 뒤 본다."""
    assert blocks(title, coins=(ETH,), body=body) == {"KRW-ETH"}


@pytest.mark.parametrize("space", ["\t", "\u3000", "\u00a0", "\r\n"])
def test_d092a_delisting_keyword_ignores_every_kind_of_space(space):
    """D-092 A·TS-104·TS-155: 탭·전각 공백·NBSP·줄바꿈도 지운 뒤 '거래지원 종료'를 찾는다."""
    assert blocks(f"[거래] 비트코인(BTC) 거래{space}지원{space}종료", coins=(BTC,)) == {"KRW-BTC"}


@pytest.mark.parametrize(
    "phrase",
    [
        "거래지원도 종료",  # 을·이·은·의가 아닌 조사
        "거래지원과 종료",
        "거래지원을이 종료",  # 조사는 하나까지
        "거래지원 을 이 종료",
        "종료된 거래지원",  # 순서가 바뀜
    ],
)
def test_d092a_delisting_keyword_allows_only_one_of_the_four_particles(phrase):
    """D-092 A·TS-104·TS-155: '거래지원'과 '종료' 사이는 을·이·은·의 하나까지만 허용한다."""
    assert blocks(f"[거래] 비트코인(BTC) {phrase}", coins=(BTC,)) == frozenset()


def test_d092a_caution_note_with_a_format_character_is_still_a_note():
    """D-092 A·TS-104·TS-155: 서식 문자를 지운 뒤 "유의사항"이 되면 키워드가 아니다."""
    body = "투자 유의\u200b사항을 확인하세요"

    assert blocks("[거래] 비트코인(BTC) 신규 거래지원 안내", coins=(BTC,), body=body) == frozenset()


@pytest.mark.parametrize(
    ("title", "blocked"),
    [
        ("[거래] krw-btc 거래지원 종료 안내", True),  # 마켓 코드 뒷부분(소문자)
        ("[거래] Krw-Btc 유의 종목 지정 안내", True),
        ("[거래] btc-ssx 거래지원 종료 안내", False),  # 마켓 코드 앞부분(소문자)
        ("[거래] btc 마켓 디지털 자산 거래지원 종료 안내", False),  # 마켓 이름(소문자)
        ("[거래] krw, btc, usdt 마켓 거래지원 종료 안내 (SSX)", False),
    ],
)
def test_d092a_market_rules_ignore_case_like_the_ticker(title, blocked):
    """D-092 A·TS-104·TS-155: 대소문자가 달라도 마켓 코드·마켓 이름 규칙이 똑같이 적용된다."""
    assert blocks(title, coins=(BTC,)) == ({"KRW-BTC"} if blocked else frozenset())


def test_d092a_delisting_withdrawal_notice_also_blocks():
    """D-092 A·TS-104·TS-155: '거래지원 종료' 철회 공지도 막는다(D-079 오탐 수용).

    "유의" 지정 해제 쪽은 test_release_notice_also_blocks가 고정한다.
    """
    assert blocks("[거래] 리플(XRP) 거래지원 종료 결정 철회 안내", coins=(XRP,)) == {"KRW-XRP"}


# 시세 상태(2)에서 C와 갈리는 경우(PREVIEW·값 없음도 막음)는 위의
# test_market_that_is_not_active_blocks_buying이, delisting_date는
# test_delisting_date_blocks_buying과 test_ticker_blocks_buy_unless_active_and_listed가
# 이미 고정한다(docstring에 D-092 A 표시).
