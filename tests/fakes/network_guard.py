"""테스트 중 실제 네트워크 차단(docs/08-quality/fakes-spec.md 2.3절 "실제 네트워크 없음", QA R17-02).

tests/conftest.py의 autouse 픽스처 `_block_real_network`가 테스트마다 `install`을 부른다. 끄는
마커·옵션·환경 변수는 두지 않는다.

- 막는 것: `socket.socket`의 `connect`·`connect_ex`·`sendto`·`sendmsg`(AF_INET·AF_INET6),
  `socket.getaddrinfo`, `socket.create_connection`, asyncio Proactor 루프의 `sock_connect`와
  Windows의 `IocpProactor.connect`(IP 주소면 `socket.connect`를 거치지 않고 ConnectEx로 바로 연결한다).
- 허용: 루프백(127.0.0.0/8, ::1, ::ffff:127.0.0.0/104, 이름 "localhost"), 미지정 주소(0.0.0.0, ::,
  빈 문자열, None. 바인드용), AF_UNIX와 그 밖의 주소 체계, `socket.socketpair`(루프백으로 만든다).
- 막으면 `RealNetworkBlocked`(AssertionError 하위)를 낸다. OSError면 asyncio·anyio·httpcore·앱이
  "연결 실패"로 바꿔 삼켜 테스트가 통과해 버릴 수 있다. 막힌 소켓은 연결을 시도하지 않은 상태다.
- 프록시 설정을 비운다(`*_proxy` 환경 변수, Windows 레지스트리·macOS 시스템 설정 읽기). 클라우드
  세션의 프록시는 127.0.0.1에 있어 루프백 허용을 타고 밖으로 나갈 수 있다(httpx trust_env,
  websockets proxy=True 기본값).
"""

import asyncio.proactor_events
import ipaddress
import os
import socket
import sys
import urllib.request
from typing import Any

import pytest

_INET_FAMILIES = (socket.AF_INET, socket.AF_INET6)


class RealNetworkBlocked(AssertionError):
    """테스트가 실제 네트워크로 나가려 했다. 가짜 구현(tests/fakes/)을 거쳐야 한다."""


def _host_text(host: object) -> str | None:
    if host is None:
        return None
    if isinstance(host, bytes | bytearray):
        return bytes(host).decode("ascii", "replace")
    return str(host)


def is_local_host(host: object) -> bool:
    """루프백·미지정 주소·"localhost"면 True. 그 밖의 IP 주소와 이름은 False."""
    text = _host_text(host)
    if text is None or text == "":
        return True
    if text.lower().rstrip(".") == "localhost":
        return True
    try:
        address = ipaddress.ip_address(text.split("%", 1)[0])
    except ValueError:
        return False  # 이름은 해석하면 밖으로 나간다
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return address.is_loopback or address.is_unspecified


def _blocked(what: str, target: object) -> RealNetworkBlocked:
    return RealNetworkBlocked(
        f"테스트 중 실제 네트워크 {what}을 막았다: {target!r}. 가짜 구현(tests/fakes/)을 쓴다"
    )


def check_address(family: int, address: Any, what: str = "연결") -> None:
    """IP 소켓의 대상 주소가 루프백이 아니면 RealNetworkBlocked."""
    if family not in _INET_FAMILIES:
        return
    if isinstance(address, tuple) and address and not is_local_host(address[0]):
        raise _blocked(what, address)
    if isinstance(address, str | bytes) and not is_local_host(address):
        raise _blocked(what, address)


def _check_socket(sock: socket.socket, address: Any, what: str = "연결") -> None:
    check_address(sock.family, address, what)


def _without_proxies(patch: pytest.MonkeyPatch) -> None:
    for name in list(os.environ):
        if name.lower().endswith("_proxy") and name.lower() != "no_proxy":
            patch.delenv(name, raising=False)
    # 환경 변수가 비면 getproxies()는 OS 설정을 읽는다(Windows 레지스트리, macOS 시스템 설정).
    for reader in ("getproxies_registry", "getproxies_macosx_sysconf"):
        if hasattr(urllib.request, reader):
            patch.setattr(urllib.request, reader, dict)


def install(patch: pytest.MonkeyPatch) -> None:
    """차단을 건다. `patch`를 되돌리면(undo) 풀린다."""
    _without_proxies(patch)

    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    original_sendto = socket.socket.sendto
    original_sendmsg = getattr(socket.socket, "sendmsg", None)  # Windows에는 없다
    original_getaddrinfo = socket.getaddrinfo
    original_create_connection = socket.create_connection
    original_sock_connect = asyncio.proactor_events.BaseProactorEventLoop.sock_connect

    def connect(sock: socket.socket, address: Any) -> None:
        _check_socket(sock, address)
        return original_connect(sock, address)

    def connect_ex(sock: socket.socket, address: Any) -> int:
        _check_socket(sock, address)
        return original_connect_ex(sock, address)

    def sendto(sock: socket.socket, data: Any, *args: Any) -> int:
        if args:  # sendto(data, address) 또는 sendto(data, flags, address)
            _check_socket(sock, args[-1], "송신")
        return original_sendto(sock, data, *args)

    def sendmsg(sock: socket.socket, buffers: Any, *args: Any, **kwargs: Any) -> int:
        address = kwargs.get("address", args[2] if len(args) >= 3 else None)
        if address is not None:
            _check_socket(sock, address, "송신")
        return original_sendmsg(sock, buffers, *args, **kwargs)  # type: ignore[misc]

    def getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> Any:
        if not is_local_host(host):
            raise _blocked("이름 해석", _host_text(host))
        return original_getaddrinfo(host, *args, **kwargs)

    def create_connection(address: Any, *args: Any, **kwargs: Any) -> socket.socket:
        if not is_local_host(address[0]):
            raise _blocked("연결", address)
        return original_create_connection(address, *args, **kwargs)

    async def sock_connect(loop: Any, sock: socket.socket, address: Any) -> Any:
        _check_socket(sock, address)
        return await original_sock_connect(loop, sock, address)

    patch.setattr(socket.socket, "connect", connect)
    patch.setattr(socket.socket, "connect_ex", connect_ex)
    patch.setattr(socket.socket, "sendto", sendto)
    if original_sendmsg is not None:
        patch.setattr(socket.socket, "sendmsg", sendmsg)
    patch.setattr(socket, "getaddrinfo", getaddrinfo)
    patch.setattr(socket, "create_connection", create_connection)
    patch.setattr(asyncio.proactor_events.BaseProactorEventLoop, "sock_connect", sock_connect)
    if sys.platform == "win32":  # pragma: no cover - Windows 전용(CI windows 작업)
        _install_iocp(patch)


def _install_iocp(patch: pytest.MonkeyPatch) -> None:  # pragma: no cover - Windows 전용
    """Windows Proactor의 ConnectEx·WSAConnect 경로를 막는다(socket.connect를 거치지 않는다)."""
    import asyncio.windows_events as windows_events

    proactor = windows_events.IocpProactor
    original_connect = proactor.connect

    def connect(self: Any, conn: socket.socket, address: Any) -> Any:
        _check_socket(conn, address)
        return original_connect(self, conn, address)

    patch.setattr(proactor, "connect", connect)
