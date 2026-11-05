"""TLS 설정 하나(D-093): 업비트 REST(httpx)와 웹소켓(websockets)이 같은 문맥을 쓴다.

정한 인터페이스(`autotrader.adapters.tls`):

- `CA_SOURCE = "certifi"`: CA 인증서 출처. D-093은 사용자 결정 A(2026-11-05, certifi 묶음)다.
  출처는 이 모듈 한 곳에서만 정한다. REST·웹소켓·자가 점검은 `create_tls_context()`를 부르기만
  한다.
- `create_tls_context(*, cafile: str | None = None) -> ssl.SSLContext`:
  cafile을 주지 않으면 `ca_bundle_path()`를 부를 때마다 찾아서 쓴다(모듈 상수로 미리 잡지 않는다).
  그 파일 하나만 읽는다. 운영체제 저장소(`load_default_certs`, `set_default_verify_paths`)와
  환경 변수 `SSL_CERT_FILE`·`SSL_CERT_DIR`·`SSLKEYLOGFILE`는 보지 않는다(keylog_filename은 None).
  PROTOCOL_TLS_CLIENT, 최소 TLSv1_2, check_hostname True, CERT_REQUIRED. 부를 때마다 새 문맥.
  예외: cafile이 없거나 빈 문자열이면 FileNotFoundError, 빈 파일·PEM이 아닌 파일(DER 포함)·깨진 PEM이면
  ssl.SSLError. 둘 다 OSError의 하위 타입이라 부르는 쪽은 OSError 하나로 잡을 수 있다.
- `ca_bundle_path() -> str`: `certifi.where()`.
- `ca_bundle_version() -> str`: certifi 배포 버전(예: "2026.10.23").

네트워크에 연결하지 않는다. 임시 묶음은 실제 certifi 묶음에서 첫 인증서를 잘라 만든다.
"""

import importlib.metadata
import ssl
from pathlib import Path

import certifi
import pytest
from fakes.certs import (
    BEGIN_CERTIFICATE,
    block_os_store,
    certifi_cert_count,
    first_certifi_pem,
    write_one_cert_bundle,
)

from autotrader.adapters import tls


def ca_count(context: ssl.SSLContext) -> int:
    return context.cert_store_stats()["x509_ca"]


@pytest.fixture
def one_cert_bundle(tmp_path: Path) -> Path:
    """certifi 묶음의 첫 인증서 하나만 든 임시 묶음."""
    return write_one_cert_bundle(tmp_path / "one-cert.pem")


@pytest.fixture
def forbid_os_store(monkeypatch: pytest.MonkeyPatch) -> None:
    """운영체제 저장소를 읽는 길을 막는다."""
    block_os_store(monkeypatch)


# --- 출처: certifi 묶음 하나 ------------------------------------------------------------


def test_ca_source_is_the_certifi_bundle():
    # D-093 사용자 결정 A(2026-11-05, certifi 묶음). 출처를 바꾸려면 이 모듈만 고친다.
    assert tls.CA_SOURCE == "certifi"


def test_ca_bundle_path_is_certifis_bundle_file():
    path = tls.ca_bundle_path()

    assert isinstance(path, str)
    assert path == certifi.where()
    assert Path(path).is_absolute()
    assert Path(path).is_file()


def test_ca_bundle_version_is_the_installed_certifi_release():
    version = tls.ca_bundle_version()

    assert isinstance(version, str)
    assert version == importlib.metadata.version("certifi")
    assert version == certifi.__version__


def test_default_context_loads_exactly_the_certifi_bundle():
    expected = certifi_cert_count()

    context = tls.create_tls_context()

    assert expected > 0
    assert ca_count(context) == expected
    assert context.cert_store_stats()["x509"] == expected


def test_default_context_reads_nothing_from_the_operating_system(forbid_os_store):
    context = tls.create_tls_context()

    assert ca_count(context) == certifi_cert_count()


def test_given_cafile_is_the_only_ca_source(one_cert_bundle, forbid_os_store):
    context = tls.create_tls_context(cafile=str(one_cert_bundle))

    assert ca_count(context) == 1
    assert context.get_ca_certs(binary_form=True) == [ssl.PEM_cert_to_DER_cert(first_certifi_pem())]


def test_default_bundle_is_looked_up_through_ca_bundle_path_at_call_time(
    monkeypatch, one_cert_bundle
):
    # 출처를 정하는 곳이 한 곳(ca_bundle_path)이다. 모듈을 불러온 뒤에 바꿔도 따라간다.
    monkeypatch.setattr(tls, "ca_bundle_path", lambda: str(one_cert_bundle))

    assert ca_count(tls.create_tls_context()) == 1


@pytest.mark.parametrize("variant", ["other_bundle", "missing_paths"])
def test_ssl_environment_variables_change_nothing(monkeypatch, tmp_path, one_cert_bundle, variant):
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.delenv("SSL_CERT_DIR", raising=False)
    baseline = tls.create_tls_context().get_ca_certs(binary_form=True)
    baseline_given = tls.create_tls_context(cafile=str(one_cert_bundle)).get_ca_certs(
        binary_form=True
    )

    if variant == "other_bundle":
        cert_dir = tmp_path / "cert-dir"
        cert_dir.mkdir()
        (cert_dir / "one-cert.pem").write_text(first_certifi_pem(), encoding="ascii")
        monkeypatch.setenv("SSL_CERT_FILE", str(one_cert_bundle))
        monkeypatch.setenv("SSL_CERT_DIR", str(cert_dir))
    else:
        monkeypatch.setenv("SSL_CERT_FILE", str(tmp_path / "missing.pem"))
        monkeypatch.setenv("SSL_CERT_DIR", str(tmp_path / "missing-dir"))

    assert tls.create_tls_context().get_ca_certs(binary_form=True) == baseline
    assert ca_count(tls.create_tls_context()) == certifi_cert_count()
    assert tls.create_tls_context(cafile=str(one_cert_bundle)).get_ca_certs(binary_form=True) == (
        baseline_given
    )


# --- 정책: 최소 TLS 1.2, 호스트 이름 확인, 인증서 필수 -------------------------------------


@pytest.mark.parametrize("given", [False, True], ids=["default_bundle", "given_cafile"])
def test_context_policy(one_cert_bundle, given):
    context = (
        tls.create_tls_context(cafile=str(one_cert_bundle)) if given else tls.create_tls_context()
    )

    assert isinstance(context, ssl.SSLContext)
    assert context.protocol == ssl.PROTOCOL_TLS_CLIENT
    assert context.minimum_version == ssl.TLSVersion.TLSv1_2
    assert context.check_hostname is True
    assert context.verify_mode == ssl.CERT_REQUIRED


@pytest.mark.parametrize("given", [False, True], ids=["default_bundle", "given_cafile"])
def test_sslkeylogfile_environment_variable_is_ignored(monkeypatch, tmp_path, one_cert_bundle, given):
    # ssl.create_default_context는 SSLKEYLOGFILE이 있으면 세션 키를 그 파일에 쓰도록 문맥을 맞춘다.
    # 앱 문맥은 그 설정을 지운다(파일은 문맥을 만들 때 빈 채로 생길 수 있지만 키는 쓰지 않는다).
    keylog = tmp_path / "keys.log"
    monkeypatch.setenv("SSLKEYLOGFILE", str(keylog))

    context = (
        tls.create_tls_context(cafile=str(one_cert_bundle)) if given else tls.create_tls_context()
    )

    assert context.keylog_filename is None


def test_each_call_returns_a_new_context():
    # 한쪽(예: 웹소켓)이 문맥을 고쳐도 다른 쪽(REST)에 번지지 않는다.
    first = tls.create_tls_context()
    second = tls.create_tls_context()

    assert first is not second


# --- 잘못된 묶음 ---------------------------------------------------------------------------


def _write_bad_bundle(tmp_path: Path, kind: str) -> Path:
    path = tmp_path / f"{kind}.pem"
    if kind == "empty":
        path.write_bytes(b"")
    elif kind == "text":
        path.write_text("이것은 인증서가 아니다\n", encoding="utf-8")
    elif kind == "der":  # 올바른 인증서지만 PEM이 아니다
        path.write_bytes(ssl.PEM_cert_to_DER_cert(first_certifi_pem()))
    elif kind == "broken_pem":
        path.write_text(f"{BEGIN_CERTIFICATE}\nAAAA\n-----END CERTIFICATE-----\n", encoding="ascii")
    return path


def test_empty_cafile_raises_file_not_found_without_reading_the_os_store(forbid_os_store):
    # 빈 문자열을 그대로 넘기면 ssl.create_default_context가 운영체제 저장소를 읽는다.
    with pytest.raises(FileNotFoundError):
        tls.create_tls_context(cafile="")


def test_missing_cafile_raises_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        tls.create_tls_context(cafile=str(tmp_path / "missing.pem"))


@pytest.mark.parametrize("kind", ["empty", "text", "der", "broken_pem"])
def test_cafile_without_pem_certificates_raises_ssl_error(tmp_path, kind):
    path = _write_bad_bundle(tmp_path, kind)

    with pytest.raises(ssl.SSLError):
        tls.create_tls_context(cafile=str(path))
