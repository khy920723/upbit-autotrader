"""카나리아: 가짜 업비트 키 만들기와 숨은 비밀 찾기(docs/08-quality/fakes-spec.md 7장).

키는 실행 중에 만든다. 실제 형식 키 문자열을 상수로 적지 않는다.

- find_canaries(text, values): 알고 있는 값을 찾는다. 원문과 원문의 8자 이상 조각, URL 인코딩
  (quote 기본 safe="/", safe="", quote_plus, 퍼센트 뒤 16진수 소문자), JSON 이스케이프(`\\/` 포함),
  base64·base64url(시작 위치 3가지) 모양을 본다. 8자 미만 값은 우연히 겹치므로 받지 않는다.
- find_secret_shapes(text): 값을 몰라도 비밀로 보이는 모양을 찾는다. JWT(`eyJ`로 시작하는 점 2개
  문자열), `Authorization`(헤더 이름, 대소문자 무시), `Bearer `, 디스코드 웹후크 주소.
"""

import base64
import json
import re
import secrets
import string
from collections.abc import Iterable
from urllib.parse import quote, quote_plus

from autotrader.core.models import UpbitCredentials

_ALNUM = string.ascii_letters + string.digits
_KEY_LENGTH = 40  # 업비트 문서 예시 access_key 길이
MIN_CANARY_LENGTH = 8
"""find_canaries가 받는 값의 최소 길이이자 원문 조각 검사의 창 크기."""

_PERCENT_HEX = re.compile(r"%[0-9A-F]{2}")
_SECRET_SHAPES = re.compile(
    r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*"  # JWT(서명이 빈 alg=none 포함)
    r"|(?<![A-Za-z0-9_])authorization(?![A-Za-z0-9_])"  # 헤더 이름. no_authorization_ip는 제외
    r"|(?<![A-Za-z0-9_])bearer\s"
    r"|discord(?:app)?\.com(?:/|\\/|%2f)api(?:/|\\/|%2f)webhooks",
    re.IGNORECASE,
)


def _random_key(marker: str | None) -> str:
    if marker is None:
        return "".join(secrets.choice(_ALNUM) for _ in range(_KEY_LENGTH))
    filler = _KEY_LENGTH - len(marker)
    head = secrets.randbelow(filler + 1)
    return (
        "".join(secrets.choice(_ALNUM) for _ in range(head))
        + marker
        + "".join(secrets.choice(_ALNUM) for _ in range(filler - head))
    )


def make_upbit_credentials(marker: str | None = None) -> UpbitCredentials:
    """영숫자 40자 access_key와 secret_key. marker가 있으면 두 값 모두에 넣는다.

    marker는 1~39자의 ASCII 영숫자여야 한다(40자 이상이면 두 키가 같아질 수밖에 없다).
    """
    if marker is not None:
        if not marker or len(marker) >= _KEY_LENGTH:
            raise ValueError(f"표식은 1~{_KEY_LENGTH - 1}자여야 한다")
        if not set(marker) <= set(_ALNUM):
            raise ValueError("표식은 ASCII 영숫자만 쓴다(업비트 키 모양)")
    while True:
        access, secret = _random_key(marker), _random_key(marker)
        if access != secret:
            return UpbitCredentials(access_key=access, secret_key=secret)


def _base64_shapes(value: str) -> set[str]:
    """base64 안에서 value가 놓일 수 있는 시작 위치 3가지에서 값만으로 정해지는 글자들."""
    raw = value.encode("utf-8")
    shapes: set[str] = set()
    for pad in range(3):
        data = b"\x00" * pad + raw
        start = -(-8 * pad // 6)  # ceil
        end = 8 * len(data) // 6
        for encoded in (base64.b64encode(data), base64.urlsafe_b64encode(data)):
            text = encoded.decode("ascii").rstrip("=")
            shapes.add(text[start:end])
    return {s for s in shapes if s}


def _url_shapes(value: str) -> set[str]:
    encoded = {quote(value), quote(value, safe=""), quote_plus(value), quote_plus(value, safe="/")}
    lowered = {_PERCENT_HEX.sub(lambda m: m.group(0).lower(), s) for s in encoded}
    return encoded | lowered


def _json_shapes(value: str) -> set[str]:
    shapes = {json.dumps(value)[1:-1], json.dumps(value, ensure_ascii=False)[1:-1]}
    return shapes | {s.replace("/", "\\/") for s in shapes}


def _shapes(value: str) -> set[str]:
    return {value, *_url_shapes(value), *_json_shapes(value), *_base64_shapes(value)}


def _windows(value: str) -> set[str]:
    return {
        value[i : i + MIN_CANARY_LENGTH] for i in range(len(value) - MIN_CANARY_LENGTH + 1)
    }


def find_canaries(text: str, values: Iterable[str]) -> list[str]:
    """text에서 발견된 값을 values 순서대로, 한 번씩 돌려준다.

    값이 8자 미만이면 ValueError(짧은 값은 우연히 겹쳐 검사가 의미 없다).
    """
    values = list(values)
    for value in values:
        if len(value) < MIN_CANARY_LENGTH:
            raise ValueError(f"검사 값은 {MIN_CANARY_LENGTH}자 이상이어야 한다")
    found: list[str] = []
    for value in values:
        if value in found:
            continue
        if any(shape in text for shape in _shapes(value)) or any(
            window in text for window in _windows(value)
        ):
            found.append(value)
    return found


def find_secret_shapes(text: str) -> list[str]:
    """값과 상관없이 비밀로 보이는 모양을 나온 순서대로 돌려준다(없으면 빈 목록)."""
    return [match.group(0) for match in _SECRET_SHAPES.finditer(text)]
