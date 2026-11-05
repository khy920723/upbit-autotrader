"""업비트 인증(adapters/upbit/auth.py) 테스트: 해시 입력 문자열, 전송 쿼리 인코딩, query_hash, JWT.

근거: CLAUDE.md "업비트 API 주의"(JWT HS512, nonce, query_hash), 업비트 API 연동 명세 3장,
ADR-0006 "지킬 것"(서명), 가짜 구현 명세 2.7절(query_hash 알려진 값, JWT 검사 방법)과 7장(카나리아),
테스트 시나리오 TS-16·TS-116.

- 해시는 URL 인코딩 전 문자열(`k=v&k=v`)로 만든다. 전송할 때만 값을 퍼센트 인코딩하고,
  배열 이름의 `[]`는 인코딩하지 않는다.
- JWT는 토큰 문자열 전체를 상수로 비교하지 않는다(라이브러리 버전마다 직렬화가 다를 수 있다).
  헤더 alg, 페이로드 키, query_hash 값, 서명(hmac sha512)을 나눠서 본다.
- 키는 테스트 실행 중에 만든 카나리아 값만 쓴다.
"""

import base64
import hashlib
import hmac
import json
import re
import uuid
import warnings
from urllib.parse import parse_qsl, unquote

import pytest
from fakes.canary import find_canaries, make_upbit_credentials
from hypothesis import given
from hypothesis import strategies as st

# isort: split
# adapters.upbit는 아직 없어서 ruff가 서드파티로 분류한다. 구현 전후로 정렬이 바뀌지 않게 따로 둔다.
from autotrader.adapters.upbit.auth import (
    Credentials,
    body_hash_input,
    encode_query,
    hash_input,
    make_token,
    query_hash,
)

# 가짜 구현 명세 2.7절: 인증 문서의 Python 예제가 만드는 문자열과 그 표준 SHA512.
OPEN_ORDERS_INPUT = "market=KRW-BTC&states[]=wait&states[]=watch&limit=10"
OPEN_ORDERS_HASH = (
    "e3cfc649139c595e1c26a8aa2b3c8504f4b15011fc2b819081451e5e845172bd"
    "5dbbb5110ec5d7a3d1d32ff71f46a78323a040e8bedf8672021fd2206190a3a8"
)
ORDER_INPUT = "market=KRW-BTC&side=bid&volume=0.001&price=50000000&ord_type=limit"
ORDER_HASH = (
    "7a1eb1d7da6191e65ee8ae0fcb65c83f16b88bf05a9d252cd075a6c0abfcf304"
    "5e3c377378a034a11da9abf9cb00ad1435525991ddf110614b81814773499233"
)

OPEN_ORDERS_PARAMS = [
    ("market", "KRW-BTC"),
    ("states[]", "wait"),
    ("states[]", "watch"),
    ("limit", "10"),
]
ORDER_BODY = {
    "market": "KRW-BTC",
    "side": "bid",
    "volume": "0.001",
    "price": "50000000",
    "ord_type": "limit",
}


def b64url_decode(part: str) -> bytes:
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))


def verify_jwt(token: str, creds: Credentials) -> dict:
    """가짜 구현 명세 2.7절의 방법으로 토큰을 검사하고 페이로드를 돌려준다.

    헤더 alg가 HS512이고, 서명이 hmac(비밀 키 그대로, "헤더.페이로드", sha512)와 같아야 한다.
    """
    header_b64, payload_b64, signature_b64 = token.split(".")
    header = json.loads(b64url_decode(header_b64))
    assert header["alg"] == "HS512"
    expected = hmac.new(
        creds.secret_key.encode("utf-8"),
        f"{header_b64}.{payload_b64}".encode("ascii"),
        hashlib.sha512,
    ).digest()
    assert hmac.compare_digest(b64url_decode(signature_b64), expected)
    return json.loads(b64url_decode(payload_b64))


# --- query_hash ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [(OPEN_ORDERS_INPUT, OPEN_ORDERS_HASH), (ORDER_INPUT, ORDER_HASH)],
)
def test_query_hash_matches_known_sha512_values(text, expected):
    assert query_hash(text) == expected


def test_query_hash_is_lowercase_sha512_hex_of_utf8_text():
    assert query_hash("market=KRW-BTC") == hashlib.sha512(b"market=KRW-BTC").hexdigest()
    assert re.fullmatch(r"[0-9a-f]{128}", query_hash("a=b"))


# --- 해시 입력 문자열과 전송 문자열 ----------------------------------------------------------


def test_hash_input_keeps_given_order_and_repeats_array_keys():
    assert hash_input(OPEN_ORDERS_PARAMS) == OPEN_ORDERS_INPUT
    assert query_hash(hash_input(OPEN_ORDERS_PARAMS)) == OPEN_ORDERS_HASH


def test_hash_input_does_not_sort_params():
    assert hash_input([("limit", "10"), ("market", "KRW-BTC")]) == "limit=10&market=KRW-BTC"


def test_uuids_array_repeats_the_key_in_hash_and_on_the_wire():
    params = [("uuids[]", "a"), ("uuids[]", "b")]

    assert hash_input(params) == "uuids[]=a&uuids[]=b"
    assert encode_query(params) == "uuids[]=a&uuids[]=b"


def test_encode_query_keeps_brackets_of_array_names_unencoded():
    sent = encode_query(OPEN_ORDERS_PARAMS)

    assert sent == OPEN_ORDERS_INPUT
    assert "%5B" not in sent.upper()
    assert "%5D" not in sent.upper()


@pytest.mark.parametrize(
    ("params", "hashed", "sent"),
    [
        (
            [("start_time", "2026-11-05T09:00:00+09:00")],
            "start_time=2026-11-05T09:00:00+09:00",
            "start_time=2026-11-05T09%3A00%3A00%2B09%3A00",
        ),
        (
            [("pairs", "KRW-BTC,KRW-ETH")],
            "pairs=KRW-BTC,KRW-ETH",
            "pairs=KRW-BTC%2CKRW-ETH",
        ),
        (
            [
                ("market", "KRW-BTC"),
                ("states[]", "done"),
                ("states[]", "cancel"),
                ("start_time", "2026-11-05T09:00:00+09:00"),
                ("end_time", "2026-11-06T09:00:00+09:00"),
                ("limit", "1000"),
            ],
            "market=KRW-BTC&states[]=done&states[]=cancel"
            "&start_time=2026-11-05T09:00:00+09:00&end_time=2026-11-06T09:00:00+09:00&limit=1000",
            "market=KRW-BTC&states[]=done&states[]=cancel"
            "&start_time=2026-11-05T09%3A00%3A00%2B09%3A00"
            "&end_time=2026-11-06T09%3A00%3A00%2B09%3A00&limit=1000",
        ),
    ],
    ids=["start_time", "pairs", "closed_orders"],
)
def test_reserved_characters_stay_raw_in_hash_and_are_encoded_only_on_the_wire(
    params, hashed, sent
):
    # `:`·`+`·`,`는 해시 문자열에 그대로 두고, 전송 문자열에서만 값을 인코딩한다(TS-16).
    assert hash_input(params) == hashed
    assert encode_query(params) == sent
    # 서버는 받은 쿼리를 디코딩해 해시를 다시 계산한다.
    assert query_hash(unquote(sent)) == query_hash(hashed)


def test_empty_params_give_empty_strings():
    assert hash_input([]) == ""
    assert encode_query([]) == ""


PARAM_KEYS = st.sampled_from(
    [
        "market",
        "states[]",
        "uuids[]",
        "identifiers[]",
        "identifier",
        "start_time",
        "end_time",
        "pairs",
        "limit",
        "page",
        "order_by",
    ]
)
# 공백·제어 문자는 뺀다: 쿼리 값에 공백·`+` 해석 차이가 생기지 않게 HTTP 계층이 보내기 전에
# 거부한다(업비트 API 연동 명세 3장, T2 리뷰 반영 결정). 그 밖의 출력 가능한 ASCII와 한글은 넣는다.
PARAM_VALUES = st.text(
    alphabet=st.one_of(
        st.characters(min_codepoint=0x21, max_codepoint=0x7E),
        st.characters(min_codepoint=0xAC00, max_codepoint=0xD7A3),  # 한글 음절
    ),
    max_size=30,
)
PARAMS = st.lists(st.tuples(PARAM_KEYS, PARAM_VALUES), max_size=8)
ENCODED_VALUE = re.compile(r"(?:[A-Za-z0-9._~-]|%[0-9A-Fa-f]{2})*")


@given(PARAMS)
def test_wire_query_decodes_back_to_the_hashed_string(params):
    hashed = hash_input(params)
    sent = encode_query(params)

    assert hashed == "&".join(f"{key}={value}" for key, value in params)
    assert unquote(sent) == hashed
    # 서버처럼 전송 쿼리를 키·값 쌍으로 다시 해석해 이으면 해시 입력과 같다(`+`·`&`·`=` 포함).
    parsed = parse_qsl(sent, keep_blank_values=True)
    assert parsed == list(params)
    assert "&".join(f"{key}={value}" for key, value in parsed) == hashed
    if not params:
        assert sent == ""
        return
    segments = sent.split("&")
    assert len(segments) == len(params)
    for segment, (key, _value) in zip(segments, params, strict=True):
        sent_key, separator, sent_value = segment.partition("=")
        assert separator == "="
        assert sent_key == key  # 키(배열 이름의 [] 포함)는 그대로
        assert ENCODED_VALUE.fullmatch(sent_value), segment  # 값은 퍼센트 인코딩


# --- POST 본문 해시 ---------------------------------------------------------------------------


def test_body_hash_input_follows_body_order_and_matches_known_hash():
    assert body_hash_input(ORDER_BODY) == ORDER_INPUT
    assert query_hash(body_hash_input(ORDER_BODY)) == ORDER_HASH


def test_body_hash_input_does_not_encode_values():
    body = {"market": "KRW-BTC", "identifier": "uat-a:b,c+d"}

    assert body_hash_input(body) == "market=KRW-BTC&identifier=uat-a:b,c+d"


@given(st.dictionaries(PARAM_KEYS, PARAM_VALUES, max_size=8))
def test_body_hash_input_equals_hash_input_of_items_in_order(body):
    assert body_hash_input(body) == hash_input(list(body.items()))


# --- JWT -------------------------------------------------------------------------------------


def test_token_with_params_carries_known_query_hash_and_verifies_with_secret_key():
    creds = make_upbit_credentials()
    nonce = str(uuid.uuid4())

    token = make_token(creds, hash_input=OPEN_ORDERS_INPUT, nonce=nonce)

    assert verify_jwt(token, creds) == {
        "access_key": creds.access_key,
        "nonce": nonce,
        "query_hash": OPEN_ORDERS_HASH,
        "query_hash_alg": "SHA512",
    }


def test_token_for_order_body_carries_known_query_hash():
    creds = make_upbit_credentials()

    payload = verify_jwt(make_token(creds, hash_input=body_hash_input(ORDER_BODY)), creds)

    assert payload["query_hash"] == ORDER_HASH
    assert payload["query_hash_alg"] == "SHA512"


def test_token_without_params_has_no_query_hash():
    creds = make_upbit_credentials()

    payload = verify_jwt(make_token(creds, hash_input=None), creds)

    assert set(payload) == {"access_key", "nonce"}
    assert payload["access_key"] == creds.access_key


def test_each_token_gets_a_new_uuid4_nonce():
    creds = make_upbit_credentials()

    nonces = [verify_jwt(make_token(creds, hash_input=None), creds)["nonce"] for _ in range(50)]

    assert len(set(nonces)) == len(nonces)
    for nonce in nonces:
        parsed = uuid.UUID(nonce)
        assert parsed.version == 4
        assert str(parsed) == nonce


def test_signature_does_not_verify_with_another_secret():
    creds = make_upbit_credentials()
    other = make_upbit_credentials()

    token = make_token(creds, hash_input="market=KRW-BTC")

    with pytest.raises(AssertionError):
        verify_jwt(token, Credentials(access_key=creds.access_key, secret_key=other.secret_key))


def test_token_does_not_carry_the_secret_key():
    creds = make_upbit_credentials()

    token = make_token(creds, hash_input=OPEN_ORDERS_INPUT)

    header_b64, payload_b64, _signature = token.split(".")
    decoded = b64url_decode(header_b64) + b64url_decode(payload_b64)
    assert creds.secret_key.encode("utf-8") not in decoded
    assert creds.secret_key not in token


# --- Credentials -----------------------------------------------------------------------------


def test_credentials_repr_and_str_hide_both_keys():
    made = make_upbit_credentials()
    creds = Credentials(access_key=made.access_key, secret_key=made.secret_key)

    for text in (repr(creds), str(creds), f"{creds}", f"{creds!r}"):
        assert made.access_key not in text
        assert made.secret_key not in text
        assert find_canaries(text, [made.access_key, made.secret_key]) == []


# --- 경고(오케스트레이터 결정 H) -------------------------------------------------------------


def test_make_token_emits_no_warnings_for_upbit_length_secret_keys():
    # PyJWT는 64바이트보다 짧은 HS512 키에 InsecureKeyLengthWarning을 낸다. 키 길이는 거래소가
    # 정하므로 make_token 안에서 그 경고만 국소적으로 억제한다.
    creds = make_upbit_credentials()

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        make_token(creds, hash_input=OPEN_ORDERS_INPUT)
        make_token(creds, hash_input=None)

    assert [str(w.message) for w in caught] == []


def test_make_token_leaves_the_callers_warning_filters_alone():
    creds = make_upbit_credentials()
    before = list(warnings.filters)

    make_token(creds, hash_input=None)

    assert list(warnings.filters) == before
