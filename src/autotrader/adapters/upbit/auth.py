"""업비트 인증: 해시 입력 문자열, 전송 쿼리, query_hash, JWT(HS512).

- query_hash는 URL 인코딩 전 문자열(`k=v&k=v`, 순서 유지, 배열은 키 반복)의 SHA512다.
- 전송 쿼리는 값만 퍼센트 인코딩하고 배열 이름의 `[]`는 그대로 둔다.
- POST는 JSON 본문의 키·값을 본문 순서대로 `key=value&...`로 이어 해시한다.
- 페이로드에 시각이 없어 PC 시계 오차는 인증에 영향이 없다.
근거: docs/05-integration/upbit-api.md 3장, ADR-0006 "지킬 것", docs/08-quality/fakes-spec.md 2.7절.
"""

import hashlib
import uuid
import warnings
from collections.abc import Mapping, Sequence
from urllib.parse import quote

import jwt
from jwt.warnings import InsecureKeyLengthWarning

from autotrader.core.models import UpbitCredentials

Params = Sequence[tuple[str, str]]
Credentials = UpbitCredentials


def hash_input(params: Params) -> str:
    """해시할 문자열. 순서를 지키고 인코딩하지 않는다."""
    return "&".join(f"{key}={value}" for key, value in params)


def encode_query(params: Params) -> str:
    """전송할 쿼리 문자열. 값은 비예약 문자(A-Z a-z 0-9 - . _ ~) 밖을 모두 인코딩한다."""
    return "&".join(f"{quote(key, safe='[]')}={quote(value, safe='')}" for key, value in params)


def body_hash_input(body: Mapping[str, str]) -> str:
    """POST JSON 본문의 해시 문자열. 본문 순서대로 key=value를 잇는다."""
    return hash_input(list(body.items()))


def query_hash(text: str) -> str:
    """UTF-8 문자열의 SHA512 소문자 16진수."""
    return hashlib.sha512(text.encode("utf-8")).hexdigest()


def make_token(creds: UpbitCredentials, *, hash_input: str | None, nonce: str | None = None) -> str:
    """HS512 JWT. hash_input이 None이나 빈 문자열이면 query_hash를 넣지 않는다.

    nonce는 기본으로 매번 새 uuid4다. 비밀 키는 Base64 디코딩 없이 그대로 쓴다.
    """
    payload: dict[str, str] = {
        "access_key": creds.access_key,
        "nonce": nonce if nonce is not None else str(uuid.uuid4()),
    }
    if hash_input:
        payload["query_hash"] = query_hash(hash_input)
        payload["query_hash_alg"] = "SHA512"
    # PyJWT는 64바이트보다 짧은 HS512 키에 InsecureKeyLengthWarning을 낸다. 업비트 Secret Key
    # 길이는 거래소가 정하므로 그 범주만 여기서 무시한다. catch_warnings는 프로세스 전역 필터를
    # 잠시 바꾸지만, 서명은 코어 이벤트 루프 스레드 한 곳에서만 하고 그 범주만 무시하므로 다른
    # 경고에는 영향이 없다.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", InsecureKeyLengthWarning)
        return jwt.encode(payload, creds.secret_key, algorithm="HS512")
