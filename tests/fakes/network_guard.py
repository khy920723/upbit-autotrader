"""테스트 중 실제 네트워크 차단(fakes-spec 2.3절 "실제 네트워크 없음", QA R17-02).

tests/conftest.py의 hook이 `pytest_configure`에서 `install`을 부르고 `pytest_unconfigure`에서 푼다.
수집(모듈 import), session·module 범위 픽스처, 모든 테스트가 그 안에서 돈다. 끄는 마커·옵션·환경
변수는 두지 않는다.

- 막는 것: `socket.socket`의 `connect`·`connect_ex`·`sendto`·`sendmsg`(AF_INET·AF_INET6의 대상
  주소, TCP·UDP, `MSG_FASTOPEN` 포함), 이름 해석 `socket.getaddrinfo`·`gethostbyname`·
  `gethostbyname_ex`, 역방향 조회 `socket.gethostbyaddr`·`getnameinfo`, `socket.create_connection`,
  Windows의 `IocpProactor.connect`·`sendto`(Proactor 루프는 `socket.connect`·`sendto`를 거치지 않고
  ConnectEx·WSASendTo를 바로 부른다. `BaseProactorEventLoop.sock_connect`·`sock_sendto`와 데이터그램
  transport도 이 둘을 거친다).
- 허용: 루프백(127.0.0.0/8, ::1, ::ffff:127.0.0.0/104, scope가 붙은 IPv6 루프백 ::1%lo, 이름
  "localhost"), 미지정 주소(0.0.0.0, ::, ::ffff:0.0.0.0, 빈 문자열, None. 바인드용), AF_UNIX와
  그 밖의 주소 체계, `socket.socketpair`. 역방향 조회는 루프백과 이 PC 이름
  (`socket.gethostname()`)만.
  "127.0.0.1%lo"처럼 IPv4에 %를 붙인 값은 주소가 아니므로 이름으로 보고 막는다.
  단 비우기 전 프록시 주소로의 루프백 연결은 허용에서 뺀다.
- 막으면 `RealNetworkBlocked`(AssertionError 하위)를 낸다. OSError면 asyncio·anyio·httpcore·앱이
  "연결 실패"로 바꿔 삼켜 테스트가 통과해 버릴 수 있다. 막힌 소켓은 연결을 시도하지 않은 상태다.
- 막을 때마다 기록한다. conftest의 hook이 테스트의 정리 단계에서 기록이 남아 있으면 그 테스트를
  실패로 만든다(넓은 `except Exception`이나 asyncio의 `_fatal_error`가 예외를 삼켜도). 일부러 막는
  테스트는 `expect_blocked()`로 감싼다.
- 프록시 설정을 비운다(`*_proxy` 환경 변수, Windows 레지스트리·macOS 시스템 설정 읽기). 클라우드
  세션의 프록시는 127.0.0.1에 있어 루프백 허용을 타고 밖으로 나갈 수 있다(httpx trust_env,
  websockets proxy=True 기본값). 비우기 전 프록시 주소(호스트, 포트)를 기록해 두고
  (`blocked_proxy_endpoints()`) 그 주소로의 루프백 연결도 막는다(QA R22-06). 같은 루프백의 다른
  포트는 허용한다.

한계(막지 못하는 것): C 타입 `_socket.socket`(= `socket.SocketType`)을 직접 만들어 쓰는 코드,
Python `socket`을 거치지 않는 확장 모듈(예: QtNetwork. 앱은 쓰지 않는다, test_architecture),
자식 프로세스, 테스트 코드가 일부러 원래 함수를 되돌려 놓는 경우.
"""

import ipaddress
import os
import socket
import sys
import threading
import urllib.request
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from typing import Any
from urllib.parse import urlsplit

import pytest

_INET_FAMILIES = (socket.AF_INET, socket.AF_INET6)
_REPORT_LIMIT = 10  # 보고 문구에 적는 시도 수

_lock = threading.Lock()
_attempts: list[str] = []  # 막은 시도(문구). 정리 단계에서 비운다
_installed: dict[tuple[object, str], object] = {}  # install이 바꿔 놓은 (대상, 이름) → 감싼 함수
# install이 비우기 전에 읽은 프록시 주소(호스트, 포트). 자격 증명은 담지 않는다.
# patch.setattr로 바꾸므로 patch를 되돌리면 비워진다.
_proxy_endpoints: frozenset[tuple[str, int]] = frozenset()
_DEFAULT_PROXY_PORTS = {"http": 80, "https": 443, "socks5": 1080, "socks5h": 1080}


class RealNetworkBlocked(AssertionError):
    """테스트가 실제 네트워크로 나가려 했다. 가짜 구현(tests/fakes/)을 거쳐야 한다."""


def _host_text(host: object) -> str | None:
    if host is None:
        return None
    if isinstance(host, bytes | bytearray):
        return bytes(host).decode("ascii", "replace")
    return str(host)


def _ip(text: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """IP 주소면 그 값(::ffff: IPv4 대응 주소는 IPv4로), 아니면 None. scope(%)는 IPv6만 받는다."""
    try:
        address = ipaddress.ip_address(text)
    except ValueError:
        return None
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return address.ipv4_mapped
    return address


def _is_localhost_name(text: str) -> bool:
    return text.lower().rstrip(".") == "localhost"


def is_local_host(host: object) -> bool:
    """루프백·미지정 주소·"localhost"면 True. 그 밖의 IP 주소와 이름은 False."""
    text = _host_text(host)
    if text is None or text == "" or _is_localhost_name(text):
        return True
    address = _ip(text)
    if address is None:
        return False  # 이름은 해석하면 밖으로 나간다
    return address.is_loopback or address.is_unspecified


def is_reverse_lookup_allowed(host: object) -> bool:
    """역방향 조회(gethostbyaddr·getnameinfo) 대상이 루프백·"localhost"·이 PC 이름이면 True."""
    text = _host_text(host)
    if not text:
        return False
    if _is_localhost_name(text) or text.lower() == _hostname().lower():
        return True
    address = _ip(text)
    return address is not None and address.is_loopback


def _hostname() -> str:
    return socket.gethostname()


def _blocked(what: str, target: object) -> RealNetworkBlocked:
    return RealNetworkBlocked(
        f"테스트 중 실제 네트워크 {what}을 막았다: {target!r}. 가짜 구현(tests/fakes/)을 쓴다"
    )


def _endpoint(value: str) -> tuple[str, int] | None:
    """프록시 URL의 (호스트, 포트). 자격 증명은 버린다. 주소가 아니면 예외 없이 None."""
    text = value.strip()
    if not text:
        return None
    if "://" not in text:
        text = "http://" + text  # 스킴이 없으면 http(curl·requests와 같다)
    try:
        parts = urlsplit(text)
        port = parts.port
        host = parts.hostname  # 소문자, IPv6는 대괄호 없이
    except ValueError:
        return None
    if not host:
        return None
    if port is None:
        port = _DEFAULT_PROXY_PORTS.get(parts.scheme.lower())
    if port is None or not 0 < port < 65536:
        return None
    return host, port


def proxy_endpoints(env: Mapping[str, str]) -> frozenset[tuple[str, int]]:
    """환경 변수 모양의 매핑에서 프록시 주소 (호스트, 포트)를 읽는다.

    install이 지우는 변수(이름이 `_proxy`로 끝남, `no_proxy`류 제외)를 모두 읽고,
    `CLOUDSDK_PROXY_ADDRESS`·`CLOUDSDK_PROXY_PORT`가 둘 다 있으면 그 쌍도 읽는다(gcloud).
    """
    found: set[tuple[str, int]] = set()
    cloudsdk: dict[str, str] = {}
    for name, value in env.items():
        lower = name.lower()
        if lower in ("cloudsdk_proxy_address", "cloudsdk_proxy_port"):
            cloudsdk[lower] = value
            continue
        if not lower.endswith("_proxy") or lower.endswith("no_proxy"):
            continue
        endpoint = _endpoint(value)
        if endpoint is not None:
            found.add(endpoint)
    if len(cloudsdk) == 2:
        port_text = cloudsdk["cloudsdk_proxy_port"].strip()
        if port_text.isascii() and port_text.isdigit():
            endpoint = _endpoint(f"{cloudsdk['cloudsdk_proxy_address'].strip()}:{port_text}")
            if endpoint is not None:
                found.add(endpoint)
    return frozenset(found)


def is_proxy_target(address: Any, endpoints: Iterable[tuple[str, int]]) -> bool:
    """루프백 프록시의 포트로 가는 루프백 대상이면 True. 외부 프록시는 외부 차단 몫이다."""
    if not isinstance(address, tuple) or len(address) < 2 or not is_local_host(address[0]):
        return False
    return any(port == address[1] and is_local_host(host) for host, port in endpoints)


def blocked_proxy_endpoints() -> frozenset[tuple[str, int]]:
    """install이 비우기 전에 읽어 둔 프록시 주소 (호스트, 포트). 자격 증명은 없다."""
    return _proxy_endpoints


def check_address(family: int, address: Any, what: str = "연결") -> None:
    """IP 소켓의 대상 주소가 루프백·미지정 주소가 아니거나 기록된 프록시면 RealNetworkBlocked.

    기록하지 않는다.
    """
    if family not in _INET_FAMILIES:
        return
    if is_proxy_target(address, _proxy_endpoints):
        raise RealNetworkBlocked(
            f"테스트 중 프록시(포트 {address[1]}) 주소로의 {what}을 막았다: {address[0]!r}."
            " 가짜 구현(tests/fakes/)을 쓴다"
        )
    if isinstance(address, tuple) and address and not is_local_host(address[0]):
        raise _blocked(what, address)
    if isinstance(address, str | bytes) and not is_local_host(address):
        raise _blocked(what, address)


def sendto_address(args: tuple[Any, ...]) -> Any:
    """`sendto(data, address)`·`sendto(data, flags, address)`에서 data를 뺀 인자의 대상 주소."""
    return args[-1] if args else None


def sendmsg_address(args: tuple[Any, ...], kwargs: Mapping[str, Any]) -> Any:
    """`sendmsg(buffers, ancdata, flags, address)`에서 buffers를 뺀 인자의 대상 주소.

    대상이 없으면 None.
    """
    if "address" in kwargs:
        return kwargs["address"]
    return args[2] if len(args) >= 3 else None


# --- 기록 ------------------------------------------------------------------------------------


def _enforce(blocked: RealNetworkBlocked | None) -> None:
    """막아야 하면 기록하고 던진다."""
    if blocked is None:
        return
    with _lock:
        _attempts.append(str(blocked))
    raise blocked


def _address_problem(family: int, address: Any, what: str = "연결") -> RealNetworkBlocked | None:
    try:
        check_address(family, address, what)
    except RealNetworkBlocked as exc:
        return exc
    return None


def take_blocked_report() -> str | None:
    """막은 시도를 비우고 보고 문구를 돌려준다. 없으면 None."""
    with _lock:
        taken = list(_attempts)
        _attempts.clear()
    if not taken:
        return None
    lines = [f"- {item}" for item in taken[:_REPORT_LIMIT]]
    if len(taken) > _REPORT_LIMIT:
        lines.append(f"- 외 {len(taken) - _REPORT_LIMIT}건")
    return (
        f"실제 네트워크 시도를 {len(taken)}번 막았다. 예외가 삼켜졌어도 실패로 본다"
        " (일부러 막는 테스트는 network_guard.expect_blocked()로 감싼다):\n" + "\n".join(lines)
    )


@contextmanager
def expect_blocked() -> Iterator[list[str]]:
    """안에서 막힌 시도를 기대한 것으로 보고 기록에서 비운다. 받은 목록에 그 문구를 채운다.

    안에서 막힌 것이 하나도 없으면(정상 종료일 때) AssertionError.
    """
    with _lock:
        start = len(_attempts)
    caught: list[str] = []
    try:
        yield caught
    finally:
        with _lock:
            caught.extend(_attempts[start:])
            del _attempts[start:]
    if not caught:
        raise AssertionError("expect_blocked() 안에서 막힌 시도가 없었다")


# --- 설치 ------------------------------------------------------------------------------------


def is_installed() -> bool:
    """install이 바꿔 놓은 함수가 모두 그대로 있으면 True."""
    return bool(_installed) and all(
        getattr(owner, name, None) is wrapper for (owner, name), wrapper in _installed.items()
    )


def _set(patch: pytest.MonkeyPatch, owner: object, name: str, wrapper: Any, track: bool) -> None:
    patch.setattr(owner, name, wrapper)
    if track:
        _installed[(owner, name)] = wrapper


def _without_proxies(patch: pytest.MonkeyPatch) -> None:
    # 비우기 전에 기록한다. OS 설정은 환경 변수가 있어도 따로 읽는다.
    endpoints = set(proxy_endpoints(os.environ))
    for reader in ("getproxies_registry", "getproxies_macosx_sysconf"):
        read = getattr(urllib.request, reader, None)
        if read is not None:
            settings = {f"{key}_proxy": str(value) for key, value in read().items()}
            endpoints |= proxy_endpoints(settings)
    patch.setattr(sys.modules[__name__], "_proxy_endpoints", frozenset(endpoints))
    for name in list(os.environ):
        if name.lower().endswith("_proxy") and name.lower() != "no_proxy":
            patch.delenv(name, raising=False)
    # 환경 변수가 비면 getproxies()는 OS 설정을 읽는다(Windows 레지스트리, macOS 시스템 설정).
    for reader in ("getproxies_registry", "getproxies_macosx_sysconf"):
        if hasattr(urllib.request, reader):
            patch.setattr(urllib.request, reader, dict)


def install(patch: pytest.MonkeyPatch) -> None:
    """차단을 건다. `patch`를 되돌리면(undo) 풀린다."""
    _installed.clear()
    _without_proxies(patch)

    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    original_sendto = socket.socket.sendto
    original_sendmsg = getattr(socket.socket, "sendmsg", None)  # Windows에는 없다
    original_getaddrinfo = socket.getaddrinfo
    original_gethostbyname = socket.gethostbyname
    original_gethostbyname_ex = socket.gethostbyname_ex
    original_gethostbyaddr = socket.gethostbyaddr
    original_getnameinfo = socket.getnameinfo
    original_create_connection = socket.create_connection

    def connect(sock: socket.socket, address: Any) -> None:
        _enforce(_address_problem(sock.family, address))
        return original_connect(sock, address)

    def connect_ex(sock: socket.socket, address: Any) -> int:
        _enforce(_address_problem(sock.family, address))
        return original_connect_ex(sock, address)

    def sendto(sock: socket.socket, data: Any, *args: Any) -> int:
        _enforce(_address_problem(sock.family, sendto_address(args), "송신"))
        return original_sendto(sock, data, *args)

    def sendmsg(sock: socket.socket, buffers: Any, *args: Any, **kwargs: Any) -> int:
        address = sendmsg_address(args, kwargs)
        if address is not None:
            _enforce(_address_problem(sock.family, address, "송신"))
        return original_sendmsg(sock, buffers, *args, **kwargs)  # type: ignore[misc]

    def name_check(host: Any) -> None:
        if not is_local_host(host):
            _enforce(_blocked("이름 해석", _host_text(host)))

    def reverse_check(host: Any) -> None:
        if not is_reverse_lookup_allowed(host):
            _enforce(_blocked("역방향 조회", _host_text(host)))

    def getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> Any:
        name_check(host)
        return original_getaddrinfo(host, *args, **kwargs)

    def gethostbyname(host: Any) -> str:
        name_check(host)
        return original_gethostbyname(host)

    def gethostbyname_ex(host: Any) -> Any:
        name_check(host)
        return original_gethostbyname_ex(host)

    def gethostbyaddr(host: Any) -> Any:
        reverse_check(host)
        return original_gethostbyaddr(host)

    def getnameinfo(sockaddr: Any, flags: int) -> Any:
        reverse_check(sockaddr[0] if isinstance(sockaddr, tuple) and sockaddr else sockaddr)
        return original_getnameinfo(sockaddr, flags)

    def create_connection(address: Any, *args: Any, **kwargs: Any) -> socket.socket:
        if not is_local_host(address[0]):
            _enforce(_blocked("연결", address))
        _enforce(
            _address_problem(socket.AF_INET, address)
        )  # 기록된 프록시면 소켓을 만들기 전에 막는다
        return original_create_connection(address, *args, **kwargs)

    _set(patch, socket.socket, "connect", connect, True)
    _set(patch, socket.socket, "connect_ex", connect_ex, True)
    _set(patch, socket.socket, "sendto", sendto, True)
    if original_sendmsg is not None:
        _set(patch, socket.socket, "sendmsg", sendmsg, True)
    _set(patch, socket, "getaddrinfo", getaddrinfo, True)
    _set(patch, socket, "gethostbyname", gethostbyname, True)
    _set(patch, socket, "gethostbyname_ex", gethostbyname_ex, True)
    _set(patch, socket, "gethostbyaddr", gethostbyaddr, True)
    _set(patch, socket, "getnameinfo", getnameinfo, True)
    _set(patch, socket, "create_connection", create_connection, True)
    if sys.platform == "win32":  # pragma: no cover - Windows 전용(CI windows 작업)
        import asyncio.windows_events as windows_events

        wrap_proactor(patch, windows_events.IocpProactor, track=True)


def wrap_proactor(patch: pytest.MonkeyPatch, proactor: type, *, track: bool = False) -> None:
    """Proactor 클래스(Windows `IocpProactor`)의 `connect`·`sendto`를 감싼다.

    Proactor 루프의 `sock_connect`·`sock_sendto`와 데이터그램 transport는 이 둘만 거친다. 리눅스
    테스트는 같은 모양의 대역 클래스로 감싸기를 확인한다.
    """
    original_connect = proactor.connect  # type: ignore[attr-defined]
    original_sendto = proactor.sendto  # type: ignore[attr-defined]

    def connect(self: Any, conn: socket.socket, address: Any) -> Any:
        _enforce(_address_problem(conn.family, address))
        return original_connect(self, conn, address)

    def sendto(self: Any, conn: socket.socket, buf: Any, flags: int = 0, addr: Any = None) -> Any:
        if addr is not None:  # None이면 연결된 소켓이다(대상은 connect가 봤다)
            _enforce(_address_problem(conn.family, addr, "송신"))
        return original_sendto(self, conn, buf, flags, addr)

    _set(patch, proactor, "connect", connect, track)
    _set(patch, proactor, "sendto", sendto, track)
