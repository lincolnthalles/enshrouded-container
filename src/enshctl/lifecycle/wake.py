"""Wake-source adapters for a paused Enshrouded server."""

import logging
import select
import socket
from dataclasses import dataclass
from ipaddress import IPv4Address, IPv6Address
from pathlib import Path
from time import monotonic
from typing import TYPE_CHECKING, Protocol, cast

if TYPE_CHECKING:
    import threading
    from collections.abc import Callable

    from enshctl.config import QueryEndpoint

logger = logging.getLogger(__name__)

_ETHERTYPE_IPV4 = 0x0800
_ETHERTYPE_IPV6 = 0x86DD
_ETHERTYPE_VLAN = 0x8100
_ETHERTYPE_QINQ = 0x88A8
_UDP_PROTOCOL = 17
_PACKET_OUTGOING_CLASS = 4
_A2S_SIGNATURE = b"\xff\xff\xff\xff"
_A2S_REQUEST_TYPES = (b"T", b"U", b"V", b"W")
_WAKE_POLL_INTERVAL = 1.0


@dataclass(frozen=True)
class WakeEvent:
    """One accepted client packet or queue growth."""

    source: str
    source_port: int
    length: int
    classification: str


class WakeSource(Protocol):
    """A wake source that can be armed before suspension and polled while paused."""

    def arm(self) -> bool: ...

    def ignore_source_endpoints(self, endpoints: frozenset[tuple[str, int]] | None) -> None: ...

    def wait(self, stop_event: threading.Event, timeout: float) -> WakeEvent | None: ...

    def close(self) -> None: ...


class _PacketSocket(Protocol):
    def bind(self, address: tuple[str, int]) -> None: ...

    def recvfrom(self, size: int) -> tuple[bytes, tuple[object, ...]]: ...

    def setblocking(self, flag: bool, /) -> None: ...

    def fileno(self) -> int: ...

    def close(self) -> None: ...


class _NoWake:
    def arm(self) -> bool:
        return False

    def ignore_source_endpoints(self, endpoints: frozenset[tuple[str, int]] | None) -> None:
        del endpoints

    def wait(self, stop_event: threading.Event, timeout: float) -> WakeEvent | None:
        del stop_event, timeout
        return None

    def close(self) -> None:
        return None


class PacketWake:
    """AF_PACKET wake source bound to every network interface."""

    def __init__(
        self,
        endpoint: QueryEndpoint,
        *,
        interface_root: Path,
        socket_factory: Callable[[str], _PacketSocket] | None = None,
    ) -> None:
        self._endpoint = endpoint
        self._interface_root = interface_root
        self._socket_factory = socket_factory or self._open_socket
        self._sockets: list[_PacketSocket] = []
        self._source_label = "packet"
        self._ignored_source_endpoints: frozenset[tuple[str, int]] = frozenset()

    def arm(self) -> bool:
        self.close()
        try:
            interfaces = sorted(self._interface_root.iterdir())
        except OSError:
            return False
        for interface in interfaces:
            try:
                packet_socket = self._socket_factory(interface.name)
                packet_socket.setblocking(False)  # noqa: FBT003 - socket API is positional-only
            except OSError:
                logger.warning("Could not open AF_PACKET on interface %s", interface.name)
                continue
            self._sockets.append(packet_socket)
        if not self._sockets:
            return False
        logger.info("Auto Pause wake source armed on %d interface(s)", len(self._sockets))
        return True

    def ignore_source_endpoints(self, endpoints: frozenset[tuple[str, int]] | None) -> None:
        self._ignored_source_endpoints = frozenset() if endpoints is None else endpoints

    def wait(self, stop_event: threading.Event, timeout: float) -> WakeEvent | None:
        deadline = monotonic() + timeout
        while not stop_event.is_set():
            remaining = deadline - monotonic()
            if remaining <= 0:
                return None
            try:
                empty_read: list[int] = []
                empty_write: list[int] = []
                readable, _, _ = select.select(self._sockets, empty_read, empty_write, remaining)
            except OSError:
                logger.warning("AF_PACKET wake poll failed")
                return None
            for candidate in readable:
                packet_socket = cast("_PacketSocket", candidate)
                try:
                    data, address = packet_socket.recvfrom(65535)
                except OSError:
                    continue
                if len(address) >= 3 and address[2] == _PACKET_OUTGOING_CLASS:
                    continue
                event = classify_udp_packet(data, self._endpoint.port)
                if event is None:
                    continue
                if (event.source, event.source_port) in self._ignored_source_endpoints:
                    continue
                return event
        return None

    def close(self) -> None:
        for packet_socket in self._sockets:
            try:
                packet_socket.close()
            except OSError:
                continue
        self._sockets.clear()

    @staticmethod
    def _open_socket(interface: str) -> _PacketSocket:
        packet_socket = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(0x0003))
        packet_socket.bind((interface, 0))
        return cast("_PacketSocket", packet_socket)


class QueueWake:
    """Queue-growth fallback for containers without CAP_NET_RAW."""

    def __init__(
        self,
        endpoint: QueryEndpoint,
        *,
        proc_net_root: Path,
        poll_interval: float = _WAKE_POLL_INTERVAL,
    ) -> None:
        self._endpoint = endpoint
        self._proc_net_root = proc_net_root
        self._poll_interval = poll_interval
        self._baseline = 0
        self._armed = False

    def arm(self) -> bool:
        readable = self._readable_files()
        if not readable:
            return False
        self._baseline = self._read_rx_queue()
        self._armed = True
        logger.warning("AF_PACKET unavailable; falling back to query-port queue polling")
        return True

    def ignore_source_endpoints(self, endpoints: frozenset[tuple[str, int]] | None) -> None:
        del endpoints

    def wait(self, stop_event: threading.Event, timeout: float) -> WakeEvent | None:
        if not self._armed:
            return None
        deadline = monotonic() + timeout
        while not stop_event.is_set():
            remaining = deadline - monotonic()
            if remaining <= 0:
                return None
            if stop_event.wait(min(self._poll_interval, remaining)):
                return None
            current = self._read_rx_queue()
            if current > self._baseline:
                growth = current - self._baseline
                self._baseline = current
                return WakeEvent("queue", 0, growth, "udp")
        return None

    def close(self) -> None:
        self._armed = False

    def _readable_files(self) -> list[Path]:
        files: list[Path] = []
        for name in ("udp", "udp6"):
            path = self._proc_net_root / name
            if path.exists():
                files.append(path)
        return files

    def _read_rx_queue(self) -> int:
        total = 0
        port = f"{self._endpoint.port:04X}"
        for path in self._readable_files():
            try:
                lines = path.read_text().splitlines()
            except OSError:
                continue
            for line in lines[1:]:
                fields = line.split()
                if len(fields) < 5 or not fields[1].endswith(f":{port}"):
                    continue
                try:
                    total += int(fields[4].split(":", maxsplit=1)[1], 16)
                except ValueError, IndexError:
                    continue
        return total


class FallbackWake:
    """Prefer packet capture and fall back to queue polling."""

    def __init__(self, packet: WakeSource, queue: WakeSource) -> None:
        self._packet = packet
        self._queue = queue
        self._active: WakeSource | None = None

    def arm(self) -> bool:
        if self._packet.arm():
            self._active = self._packet
            return True
        if self._queue.arm():
            self._active = self._queue
            return True
        return False

    def ignore_source_endpoints(self, endpoints: frozenset[tuple[str, int]] | None) -> None:
        self._packet.ignore_source_endpoints(endpoints)
        self._queue.ignore_source_endpoints(endpoints)

    def wait(self, stop_event: threading.Event, timeout: float) -> WakeEvent | None:
        if self._active is None:
            return None
        return self._active.wait(stop_event, timeout)

    def close(self) -> None:
        self._packet.close()
        self._queue.close()
        self._active = None


def build_wake_source(endpoint: QueryEndpoint | None) -> WakeSource:
    """Build the production wake source for one resolved endpoint."""
    if endpoint is None:
        return _NoWake()
    return FallbackWake(
        PacketWake(endpoint, interface_root=Path("/sys/class/net")),
        QueueWake(endpoint, proc_net_root=Path("/proc/net")),
    )


def classify_udp_packet(frame: bytes, query_port: int) -> WakeEvent | None:
    """Classify one Ethernet frame as a wake event when it is UDP to the query port."""
    if len(frame) < 14:
        return None
    ethertype = int.from_bytes(frame[12:14], "big")
    offset = 14
    while ethertype in (_ETHERTYPE_VLAN, _ETHERTYPE_QINQ):
        if len(frame) < offset + 4:
            return None
        ethertype = int.from_bytes(frame[offset + 2 : offset + 4], "big")
        offset += 4
    if ethertype == _ETHERTYPE_IPV4:
        return _classify_ipv4(frame[offset:], query_port)
    if ethertype == _ETHERTYPE_IPV6:
        return _classify_ipv6(frame[offset:], query_port)
    return None


def _classify_ipv4(packet: bytes, query_port: int) -> WakeEvent | None:
    if len(packet) < 20 or packet[0] >> 4 != 4 or packet[9] != _UDP_PROTOCOL:
        return None
    header_length = (packet[0] & 0x0F) * 4
    if len(packet) < header_length + 8:
        return None
    source = str(IPv4Address(packet[12:16]))
    source_port = int.from_bytes(packet[header_length : header_length + 2], "big")
    destination_port = int.from_bytes(packet[header_length + 2 : header_length + 4], "big")
    if destination_port != query_port:
        return None
    return _wake_event(source, source_port, packet[header_length + 8 :])


def _classify_ipv6(packet: bytes, query_port: int) -> WakeEvent | None:
    if len(packet) < 48 or packet[0] >> 4 != 6 or packet[6] != _UDP_PROTOCOL:
        return None
    source = str(IPv6Address(packet[8:24]))
    source_port = int.from_bytes(packet[40:42], "big")
    destination_port = int.from_bytes(packet[42:44], "big")
    if destination_port != query_port:
        return None
    return _wake_event(source, source_port, packet[48:])


def _wake_event(source: str, source_port: int, payload: bytes) -> WakeEvent:
    classification = "a2s" if payload.startswith(_A2S_SIGNATURE) and payload[4:5] in _A2S_REQUEST_TYPES else "udp"
    return WakeEvent(source, source_port, len(payload), classification)
