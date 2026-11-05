"""카나리아(가짜 구현 명세 7장): 가짜 업비트 키 만들기와 숨은 비밀 찾기.

카나리아는 INV-07(비밀이 keyring 밖에 없음)을 증명하는 도구다. 도구가 놓치면 유출 시험이
헛돌므로, 비밀이 어떤 모양으로 숨어도 찾는지 여기서 확인한다.

키 형식: 업비트 공식 문서는 키 길이를 규정하지 않는다. 인증 문서(docs.upbit.com/kr/reference/auth,
2026-09-22 갱신)와 API Key 목록 조회 문서(docs.upbit.com/kr/reference/list-api-keys)의 예시
access_key가 둘 다 영문 대소문자·숫자 40자다. Secret Key 예시는 문서에 없어 길이를 범위로 본다.
"""

import base64
import hashlib
import hmac
import json
import re
import secrets
import string
import uuid
from urllib.parse import quote, quote_plus

import pytest
from fakes.canary import find_canaries, find_secret_shapes, make_upbit_credentials
from hypothesis import given, settings
from hypothesis import strategies as st

ALNUM = set(string.ascii_letters + string.digits)
ACCESS_KEY_LENGTH = 40
SECRET_KEY_LENGTH_RANGE = range(32, 65)  # 문서에 없음. 느슨하게 32~64자


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def make_jwt(payload: dict, secret: str) -> str:
    """업비트 인증 문서 모양의 HS512 JWT를 직접 만든다(어댑터 코드에 기대지 않는다)."""
    header = b64url(json.dumps({"alg": "HS512", "typ": "JWT"}, separators=(",", ":")).encode())
    body = b64url(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{header}.{body}".encode("ascii")
    signature = hmac.new(secret.encode(), signing_input, hashlib.sha512).digest()
    return f"{header}.{body}.{b64url(signature)}"


def special_secret() -> str:
    """URL 인코딩으로 모양이 바뀌는 문자가 섞인 가짜 비밀(웹후크 주소·Client Secret 대용).

    영숫자만으로 된 값은 base64로 바꿔도 '+', '/'가 나오지 않아 base64와 base64url이 같아진다.
    '?'(0x3F)가 6개 이어지면 시작 위치와 상관없이 base64에 '/'가, base64url에 '_'가 생긴다.
    """
    return f"{secrets.token_hex(8)}/+=&?# :??????{secrets.token_hex(8)}"


# ── make_upbit_credentials ────────────────────────────────


def test_access_key_has_the_upbit_shape():
    creds = make_upbit_credentials()

    assert len(creds.access_key) == ACCESS_KEY_LENGTH
    assert set(creds.access_key) <= ALNUM


def test_secret_key_has_the_upbit_shape():
    creds = make_upbit_credentials()

    assert len(creds.secret_key) in SECRET_KEY_LENGTH_RANGE
    assert set(creds.secret_key) <= ALNUM


def test_access_and_secret_keys_differ():
    creds = make_upbit_credentials()

    assert creds.access_key != creds.secret_key


def test_every_call_makes_new_values():
    made = [make_upbit_credentials() for _ in range(20)]

    values = [c.access_key for c in made] + [c.secret_key for c in made]
    assert len(set(values)) == len(values)


def test_given_marker_is_inside_both_keys():
    marker = "Cnry" + secrets.token_hex(3)  # 실행마다 다른 영숫자 표식

    creds = make_upbit_credentials(marker=marker)

    assert marker in creds.access_key
    assert marker in creds.secret_key
    assert len(creds.access_key) == ACCESS_KEY_LENGTH
    assert set(creds.access_key) <= ALNUM
    assert set(creds.secret_key) <= ALNUM


def test_made_keys_are_found_by_find_canaries():
    creds = make_upbit_credentials()
    line = f"2026-11-05T09:00:00.000+09:00 | INFO | x | - | {creds.access_key} {creds.secret_key}"

    assert find_canaries(line, [creds.access_key, creds.secret_key]) == [
        creds.access_key,
        creds.secret_key,
    ]


# ── find_canaries: 찾을 모양 ─────────────────────────────


def test_finds_the_raw_value():
    value = make_upbit_credentials().access_key

    assert find_canaries(f"주문 실패: key={value}; 다시 시도", [value]) == [value]


@pytest.mark.parametrize("encode", [lambda v: quote(v, safe=""), quote_plus], ids=["quote", "plus"])
def test_finds_url_encoded_value(encode):
    value = special_secret()
    encoded = encode(value)
    assert encoded != value  # 인코딩으로 모양이 바뀌는 값이어야 시험이 된다

    text = f"GET https://example.invalid/hook?token={encoded}&wait=true 실패"

    assert find_canaries(text, [value]) == [value]


@settings(deadline=None)
@given(prefix=st.binary(max_size=8), suffix=st.binary(max_size=8))
def test_finds_value_inside_standard_base64(prefix, suffix):
    # 앞뒤에 무엇이 붙어 있든(base64 시작 위치 3가지) 찾는다.
    value = make_upbit_credentials().secret_key
    blob = base64.b64encode(prefix + value.encode() + suffix).decode("ascii")

    assert find_canaries(f"payload={blob}", [value]) == [value]


@settings(deadline=None)
@given(prefix=st.binary(max_size=8), suffix=st.binary(max_size=8))
def test_finds_value_inside_base64url_without_padding(prefix, suffix):
    value = make_upbit_credentials().secret_key
    blob = b64url(prefix + value.encode() + suffix)

    assert find_canaries(f"state={blob}", [value]) == [value]


@settings(deadline=None)
@given(prefix=st.binary(max_size=8), suffix=st.binary(max_size=8))
def test_finds_special_value_inside_base64(prefix, suffix):
    # 특수 문자가 섞인 비밀도 base64 안에서 찾는다.
    value = special_secret()
    blob = base64.b64encode(prefix + value.encode() + suffix).decode("ascii")
    assert "/" in blob  # 표준 알파벳 문자가 실제로 나오는 경우를 시험한다

    assert find_canaries(blob, [value]) == [value]


@settings(deadline=None)
@given(prefix=st.binary(max_size=8), suffix=st.binary(max_size=8))
def test_finds_special_value_inside_base64url(prefix, suffix):
    # base64url은 '+', '/' 대신 '-', '_'를 쓴다. 표준 base64만 보면 놓친다.
    value = special_secret()
    blob = b64url(prefix + value.encode() + suffix)
    assert "_" in blob

    assert find_canaries(blob, [value]) == [value]


def test_finds_access_key_inside_a_jwt():
    creds = make_upbit_credentials()
    token = make_jwt({"access_key": creds.access_key, "nonce": str(uuid.uuid4())}, creds.secret_key)

    assert find_canaries(token, [creds.access_key]) == [creds.access_key]


def test_finds_access_key_inside_an_authorization_header_with_query_hash():
    creds = make_upbit_credentials()
    payload = {
        "access_key": creds.access_key,
        "nonce": str(uuid.uuid4()),
        "query_hash": hashlib.sha512(b"market=KRW-BTC").hexdigest(),
        "query_hash_alg": "SHA512",
    }
    line = f"headers={{'Authorization': 'Bearer {make_jwt(payload, creds.secret_key)}'}}"

    assert find_canaries(line, [creds.access_key, creds.secret_key]) == [creds.access_key]


# ── find_canaries: 결과 모양 ─────────────────────────────


def test_returns_empty_list_for_clean_text():
    creds = make_upbit_credentials()
    text = "2026-11-05T09:00:00.000+09:00 | INFO | autotrader.core | APP_START | 앱 시작"

    assert find_canaries(text, [creds.access_key, creds.secret_key]) == []


def test_returns_empty_list_without_values():
    assert find_canaries("아무 글", []) == []


def test_returns_only_the_values_that_were_found_in_given_order():
    a, b, c = (make_upbit_credentials().access_key for _ in range(3))
    text = f"{c} ... {base64.b64encode(a.encode()).decode()}"

    assert find_canaries(text, [a, b, c]) == [a, c]


def test_reports_each_value_once_even_if_found_in_many_shapes():
    value = make_upbit_credentials().access_key
    text = f"{value} {value} {base64.b64encode(value.encode()).decode()} {b64url(value.encode())}"

    assert find_canaries(text, [value]) == [value]


@settings(deadline=None)
@given(text=st.text(max_size=300))
def test_never_finds_a_fresh_canary_in_unrelated_text(text):
    creds = make_upbit_credentials()

    assert find_canaries(text, [creds.access_key, creds.secret_key]) == []


# ── make_upbit_credentials: 표식 검사 ────────────────────


@pytest.mark.parametrize("marker", ["x" * 40, "x" * 41, "x" * 100])
def test_marker_of_key_length_or_longer_is_rejected(marker):
    # 키 전체가 표식이면 access와 secret이 같아져 끝없이 다시 만들었다.
    with pytest.raises(ValueError):  # noqa: PT011 (문구는 정하지 않는다)
        make_upbit_credentials(marker=marker)


@pytest.mark.parametrize("marker", ["has space", "dash-ed", "한글표식", "under_score", ""])
def test_non_alphanumeric_marker_is_rejected(marker):
    # 업비트 키 모양(영숫자)을 깨는 표식은 받지 않는다.
    with pytest.raises(ValueError):  # noqa: PT011
        make_upbit_credentials(marker=marker)


def test_marker_of_39_chars_still_makes_different_keys():
    marker = "M" + secrets.token_hex(19)  # 39자

    creds = make_upbit_credentials(marker=marker)

    assert marker in creds.access_key
    assert creds.access_key != creds.secret_key


# ── find_canaries: 더 찾을 모양 ──────────────────────────


def test_finds_value_encoded_with_quote_default_safe_slash():
    # quote(v)의 기본 safe="/"는 '/'를 그대로 둔다. safe=""만 보면 놓친다.
    value = special_secret()
    encoded = quote(value)
    assert "/" in encoded
    assert encoded != quote(value, safe="")

    assert find_canaries(f"url=https://example.invalid/{encoded}", [value]) == [value]


def test_finds_lowercase_percent_encoding():
    # 일부 라이브러리는 %2F 대신 %2f를 쓴다. 퍼센트 뒤 16진수만 소문자로 바꾼다.
    value = special_secret()
    upper = quote(value, safe="")
    hex_lowered = re.sub(r"%[0-9A-F]{2}", lambda m: m.group(0).lower(), upper)
    assert hex_lowered != upper

    assert find_canaries(f"q={hex_lowered}", [value]) == [value]


def test_finds_json_escaped_slash():
    value = special_secret()
    escaped = json.dumps(value).replace("/", "\\/")[1:-1]
    assert "\\/" in escaped

    assert find_canaries(f'{{"hook":"{escaped}"}}', [value]) == [value]


@pytest.mark.parametrize(("start", "length"), [(0, 8), (10, 8), (32, 8), (5, 20)])
def test_finds_a_raw_fragment_of_eight_or_more_chars(start, length):
    # 잘린 로그나 앞뒤가 가려진 값도 8자 이상 남으면 유출이다.
    value = make_upbit_credentials().secret_key
    fragment = value[start : start + length]

    assert find_canaries(f"...{fragment}...", [value]) == [value]


def test_does_not_flag_a_seven_char_fragment():
    value = make_upbit_credentials().secret_key

    assert find_canaries(f"...{value[3:10]}...", [value]) == []


@pytest.mark.parametrize("value", ["", "short", "1234567"])
def test_values_shorter_than_eight_chars_are_rejected(value):
    # 짧은 값은 우연히 겹쳐 검사가 의미 없다.
    with pytest.raises(ValueError):  # noqa: PT011
        find_canaries("아무 글", [value])


# ── find_secret_shapes: 값과 무관한 모양 ─────────────────


def test_find_secret_shapes_finds_a_jwt():
    creds = make_upbit_credentials()
    token = make_jwt({"access_key": creds.access_key, "nonce": str(uuid.uuid4())}, creds.secret_key)

    shapes = find_secret_shapes(f"token={token} end")

    assert token in shapes


@pytest.mark.parametrize(
    "text",
    [
        "headers={'Authorization': '...'}",
        "authorization: x",  # 헤더 이름은 대소문자를 가리지 않는다(httpx는 소문자로 보여 준다)
        "Bearer abc.def",
        "posting to https://discord.com/api/webhooks/123/abc",
    ],
)
def test_find_secret_shapes_finds_header_and_webhook_shapes(text):
    assert find_secret_shapes(text) != []


def test_find_secret_shapes_returns_empty_for_clean_text():
    # 오류 이름(no_authorization_ip 등)은 비밀 모양이 아니다.
    text = (
        "2026-11-05T09:00:00.000+09:00 | WARNING | autotrader.core | AUTH | "
        "error_name=no_authorization_ip eyJ만"
    )

    assert find_secret_shapes(text) == []


def test_find_secret_shapes_ignores_a_single_dot_eyj_string():
    assert find_secret_shapes("eyJhbGciOi.only_one_dot") == []


@settings(deadline=None)
@given(text=st.text(alphabet=st.characters(blacklist_characters="aAeE"), max_size=300))
def test_find_secret_shapes_is_empty_for_text_without_a_and_e(text):
    # 'a'·'e'가 없으면 eyJ·Bearer·Authorization·discord.com/api/webhooks 모두 나올 수 없다.
    assert find_secret_shapes(text) == []
