"""TLS 테스트 공용 도우미: certifi 묶음을 직접 읽어 세고 자르고 복사한다. 네트워크는 쓰지 않는다.

- certifi_cert_count(): 묶음 파일의 인증서 수(문맥과 상관없이 파일을 직접 센다).
- first_certifi_pem(): 묶음의 첫 PEM 인증서 블록(끝 줄바꿈 포함).
- write_one_cert_bundle(path): 첫 인증서 하나만 든 임시 묶음을 쓴다.
- copy_certifi_bundle(target): 묶음 파일을 그대로 복사한다(상위 폴더를 만든다).
- block_os_store(monkeypatch): 운영체제 CA 저장소를 읽는 길을 막는다(부르면 AssertionError).
"""

import re
import shutil
import ssl
from pathlib import Path

import certifi
import pytest

BEGIN_CERTIFICATE = "-----BEGIN CERTIFICATE-----"
END_CERTIFICATE = "-----END CERTIFICATE-----"
PEM_BLOCK = re.compile(
    r"-----BEGIN CERTIFICATE-----\r?\n.+?\r?\n-----END CERTIFICATE-----\r?\n", re.DOTALL
)


def certifi_text() -> str:
    return Path(certifi.where()).read_text(encoding="utf-8")


def certifi_cert_count() -> int:
    """certifi 묶음 파일의 인증서 수."""
    return certifi_text().count(BEGIN_CERTIFICATE)


def first_certifi_pem() -> str:
    match = PEM_BLOCK.search(certifi_text())
    assert match is not None, "certifi 묶음에서 PEM 인증서를 찾지 못했다"
    return match.group(0)


def write_one_cert_bundle(path: Path) -> Path:
    """certifi 묶음의 첫 인증서 하나만 든 임시 묶음."""
    path.write_text(first_certifi_pem(), encoding="ascii")
    return path


def copy_certifi_bundle(target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(certifi.where(), target)
    return target


def block_os_store(monkeypatch: pytest.MonkeyPatch) -> None:
    """운영체제 저장소(load_default_certs, set_default_verify_paths)와 기본 경로 조회를 막는다."""

    def forbidden(*args, **kwargs):
        raise AssertionError("운영체제 CA 저장소를 읽으려 했다")

    monkeypatch.setattr(ssl.SSLContext, "load_default_certs", forbidden)
    monkeypatch.setattr(ssl.SSLContext, "set_default_verify_paths", forbidden)
    monkeypatch.setattr(ssl, "get_default_verify_paths", forbidden)
