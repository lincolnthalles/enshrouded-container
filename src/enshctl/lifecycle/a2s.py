"""Advisory A2S_INFO probe used by Auto Pause."""

import logging
import socket
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, cast

if TYPE_CHECKING:
    from collections.abc import Callable

    from enshctl.config import QueryEndpoint

logger = logging.getLogger(__name__)

_INFO_REQUEST = b"\xff\xff\xff\xffTSource Engine Query\x00"
_INFO_RESPONSE = b"\xff\xff\xff\xffI"
_CHALLENGE_RESPONSE = b"\xff\xff\xff\xffA"
_MAX_DATAGRAM = 65535

type _SocketAddress = tuple[str, int] | tuple[str, int, int, int]
type _AddrInfo = tuple[int, int, int, str, _SocketAddress]


class A2STransport(Protocol):
    """One request/reply exchange with the query endpoint."""

    last_local_address: tuple[str, int] | None

    def exchange(self, payload: bytes) -> bytes | None: ...


@dataclass
class UdpA2STransport:
    """UDP transport for one resolved A2S query endpoint."""

    endpoint: QueryEndpoint
    timeout: float = 2.0
    resolve: Callable[[str, int], list[_AddrInfo]] | None = None
    last_local_address: tuple[str, int] | None = None

    def exchange(self, payload: bytes) -> bytes | None:
        try:
            resolver = self.resolve or self._resolve
            candidates = resolver(self.endpoint.host, self.endpoint.port)
        except OSError:
            logger.warning("Could not resolve A2S endpoint %s:%d", self.endpoint.host, self.endpoint.port)
            return None
        if not candidates:
            logger.warning("No address for A2S endpoint %s:%d", self.endpoint.host, self.endpoint.port)
            return None
        family, _type, _proto, _canonname, sockaddr = candidates[0]
        try:
            with socket.socket(family, socket.SOCK_DGRAM) as query_socket:
                query_socket.settimeout(self.timeout)
                query_socket.sendto(payload, sockaddr)
                local = query_socket.getsockname()
                self.last_local_address = (str(local[0]), int(local[1]))
                response, _address = query_socket.recvfrom(_MAX_DATAGRAM)
        except OSError:
            return None
        return response

    @staticmethod
    def _resolve(host: str, port: int) -> list[_AddrInfo]:
        return [cast("_AddrInfo", item) for item in socket.getaddrinfo(host, port, type=socket.SOCK_DGRAM)]


class A2SProbe:
    """Challenge-based A2S_INFO player-count probe."""

    def __init__(self, transport: A2STransport, *, retries: int = 1) -> None:
        self._transport = transport
        self._retries = retries
        self._last_local_endpoints: set[tuple[str, int]] = set()

    @property
    def last_local_endpoints(self) -> frozenset[tuple[str, int]]:
        return frozenset(self._last_local_endpoints)

    def players(self) -> int | None:
        """Return the reported player count, or None on timeout or malformed data."""
        self._last_local_endpoints.clear()
        for _ in range(self._retries + 1):
            result = self._attempt()
            if result is not None:
                return result
        return None

    def _attempt(self) -> int | None:
        response = self._transport.exchange(_INFO_REQUEST)
        self._record_local_endpoint()
        if response is None:
            return None
        if response.startswith(_CHALLENGE_RESPONSE):
            if len(response) < 9:
                return None
            challenge = response[5:9]
            response = self._transport.exchange(_INFO_REQUEST + challenge)
            self._record_local_endpoint()
            if response is None:
                return None
        return parse_player_count(response)

    def _record_local_endpoint(self) -> None:
        endpoint = self._transport.last_local_address
        if endpoint is not None:
            self._last_local_endpoints.add(endpoint)


def parse_player_count(payload: bytes) -> int | None:
    """Parse the player byte from an A2S_INFO response."""
    if not payload.startswith(_INFO_RESPONSE):
        return None
    offset = len(_INFO_RESPONSE)
    try:
        for _ in range(4):
            offset = payload.index(b"\x00", offset) + 1
    except ValueError:
        return None
    offset += 2
    if offset >= len(payload):
        return None
    return payload[offset]
