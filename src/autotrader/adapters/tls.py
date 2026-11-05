"""앱의 TLS 설정 하나(D-093): 업비트 REST(httpx)와 웹소켓(websockets), 자가 점검이 함께 쓴다.

- 믿을 CA 인증서는 앱에 묶은 certifi 묶음 파일 하나다(`CA_SOURCE`). 운영체제 저장소
  (`load_default_certs`, `set_default_verify_paths`)와 환경 변수 `SSL_CERT_FILE`·`SSL_CERT_DIR`는
  보지 않는다. PC마다 같은 결과를 내기 위해서다. 출처를 바꾸려면 이 모듈만 고친다.
- 최소 TLS 1.2, 호스트 이름 확인, 인증서 필수.
- 문맥은 부를 때마다 새로 만든다. 한쪽이 고쳐도 다른 쪽에 번지지 않는다.
- 네트워크에 연결하지 않는다(파일만 읽는다).
근거: docs/10-management/decision-log.md D-093, ADR-0006.
"""

import ssl

import certifi

CA_SOURCE = "certifi"


def ca_bundle_path() -> str:
    """CA 인증서 묶음 파일의 절대 경로. exe에서는 번들 폴더 안의 certifi/cacert.pem이다."""
    return certifi.where()


def ca_bundle_version() -> str:
    """certifi 배포 버전(예: "2026.10.23").

    exe에는 배포 메타데이터(dist-info)가 없을 수 있어 모듈의 `__version__`을 읽는다.
    """
    return certifi.__version__


def create_tls_context(*, cafile: str | None = None) -> ssl.SSLContext:
    """CA 인증서 묶음 하나만 믿는 클라이언트 TLS 문맥.

    cafile을 주지 않으면 부를 때마다 `ca_bundle_path()`로 찾는다.
    예외: 파일이 없으면 FileNotFoundError, PEM 인증서가 없거나 깨졌으면 ssl.SSLError
    (둘 다 OSError의 하위 타입).
    """
    path = ca_bundle_path() if cafile is None else cafile
    if not path:
        # 빈 문자열을 넘기면 ssl.create_default_context가 운영체제 저장소를 읽는다. 막는다.
        raise FileNotFoundError("CA 인증서 묶음 경로가 비어 있다")
    # cafile을 주면 create_default_context는 그 파일만 읽고 운영체제 저장소는 읽지 않는다.
    context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=path)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    return context
