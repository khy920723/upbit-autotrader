"""카나리아: 가짜 업비트 키 만들기와 숨은 비밀 찾기(docs/08-quality/fakes-spec.md 7장).

키는 실행 중에 만든다. 실제 형식 키 문자열을 상수로 적지 않는다.
find_canaries는 원문, URL 인코딩, base64·base64url(시작 위치 3가지) 모양으로 숨은 값을 찾는다.
"""

import base64
import secrets
import string
from collections.abc import Iterable
from urllib.parse import quote, quote_plus

from autotrader.core.models import UpbitCredentials

_ALNUM = string.ascii_letters + string.digits
_KEY_LENGTH = 40  # 업비트 문서 예시 access_key 길이


def _random_key(marker: str | None) -> str:
    if marker is None:
        return "".join(secrets.choice(_ALNUM) for _ in range(_KEY_LENGTH))
    filler = _KEY_LENGTH - len(marker)
    if filler < 0:
        raise ValueError("표식이 키 길이보다 길다")
    head = secrets.randbelow(filler + 1)
    return (
        "".join(secrets.choice(_ALNUM) for _ in range(head))
        + marker
        + "".join(secrets.choice(_ALNUM) for _ in range(filler - head))
    )


def make_upbit_credentials(marker: str | None = None) -> UpbitCredentials:
    """영숫자 40자 access_key와 secret_key. marker가 있으면 두 값 모두에 넣는다."""
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


def _shapes(value: str) -> set[str]:
    return {value, quote(value, safe=""), quote_plus(value), *_base64_shapes(value)}


def find_canaries(text: str, values: Iterable[str]) -> list[str]:
    """text에서 발견된 값을 values 순서대로, 한 번씩 돌려준다."""
    found: list[str] = []
    for value in values:
        if value and value not in found and any(shape in text for shape in _shapes(value)):
            found.append(value)
    return found
