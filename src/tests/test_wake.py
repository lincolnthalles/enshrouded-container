"""Tests for Auto Pause wake sources."""

import threading
from typing import TYPE_CHECKING, override
from unittest.mock import patch

from enshctl.config import QueryEndpoint
from enshctl.lifecycle.wake import (
    FallbackWake,
    PacketWake,
    QueueWake,
    WakeEvent,
    WakeSource,
    _PacketSocket,
    classify_udp_packet,
)

if TYPE_CHECKING:
    from pathlib import Path


def _ipv4_frame(payload: bytes, *, destination_port: int, source_port: int = 40000) -> bytes:
    udp_length = 8 + len(payload)
    udp = (
        source_port.to_bytes(2, "big")
        + destination_port.to_bytes(2, "big")
        + udp_length.to_bytes(2, "big")
        + b"\x00\x00"
        + payload
    )
    total_length = 20 + len(udp)
    ipv4 = (
        b"\x45\x00"
        + total_length.to_bytes(2, "big")
        + b"\x00\x01\x00\x00"
        + b"\x40\x11\x00\x00"
        + bytes([192, 0, 2, 1])
        + bytes([192, 0, 2, 2])
        + udp
    )
    return b"\x00" * 12 + b"\x08\x00" + ipv4


def _ipv6_frame(payload: bytes, *, destination_port: int) -> bytes:
    udp_length = 8 + len(payload)
    udp = (
        (40000).to_bytes(2, "big")
        + destination_port.to_bytes(2, "big")
        + udp_length.to_bytes(2, "big")
        + b"\x00\x00"
        + payload
    )
    ipv6 = (
        b"\x60\x00\x00\x00"
        + len(udp).to_bytes(2, "big")
        + b"\x11\x40"
        + bytes.fromhex("20010db8000000000000000000000001")
        + bytes.fromhex("20010db8000000000000000000000002")
        + udp
    )
    return b"\x00" * 12 + b"\x86\xdd" + ipv6


def test_classify_ipv4_udp_wake() -> None:
    # GIVEN an IPv4 UDP packet to the query port
    frame = _ipv4_frame(b"hello", destination_port=15637)

    # WHEN classified
    event = classify_udp_packet(frame, 15637)

    # THEN the source and length are reported
    assert event == WakeEvent("192.0.2.1", 40000, 5, "udp")


def test_classify_ipv6_udp_wake() -> None:
    # GIVEN an IPv6 UDP packet to the query port
    frame = _ipv6_frame(b"hello", destination_port=15637)

    # WHEN classified
    event = classify_udp_packet(frame, 15637)

    # THEN the source and length are reported
    assert event == WakeEvent("2001:db8::1", 40000, 5, "udp")


def test_classify_a2s_request() -> None:
    # GIVEN an A2S_INFO request to the query port
    frame = _ipv4_frame(b"\xff\xff\xff\xffTSource Engine Query\x00", destination_port=15637)

    # WHEN classified
    event = classify_udp_packet(frame, 15637)

    # THEN the packet is classified as A2S
    assert event is not None
    assert event.classification == "a2s"


def test_classify_ignores_other_destination_port() -> None:
    frame = _ipv4_frame(b"hello", destination_port=15636)
    assert classify_udp_packet(frame, 15637) is None


class _FakePacketSocket(_PacketSocket):
    def __init__(self, frames: list[bytes]) -> None:
        self.frames = frames
        self.closed = False
        self.bound: tuple[str, int] | None = None

    @override
    def bind(self, address: tuple[str, int]) -> None:
        self.bound = address

    @override
    def recvfrom(self, size: int) -> tuple[bytes, tuple[object, ...]]:
        del size
        return self.frames.pop(0), ("eth0", 0, 0, 1, b"")

    @override
    def setblocking(self, flag: bool, /) -> None:
        del flag

    @override
    def fileno(self) -> int:
        return 1

    @override
    def close(self) -> None:
        self.closed = True


def test_packet_wake_arms_on_interfaces(tmp_path: Path) -> None:
    # GIVEN two network interfaces and fake sockets
    (tmp_path / "eth0").mkdir()
    (tmp_path / "eth1").mkdir()
    sockets = [_FakePacketSocket([]), _FakePacketSocket([])]

    def _factory(_interface: str) -> _FakePacketSocket:
        return sockets.pop(0)

    source = PacketWake(QueryEndpoint("127.0.0.1", 15637), interface_root=tmp_path, socket_factory=_factory)

    # WHEN the source arms
    assert source.arm() is True

    # THEN both sockets are retained and close is clean
    source.close()
    assert all(sock.closed for sock in sockets)


def test_packet_wake_ignores_outgoing_frames(tmp_path: Path) -> None:
    # GIVEN an interface whose only frame is outgoing
    (tmp_path / "eth0").mkdir()
    frame = _ipv4_frame(b"hello", destination_port=15637)
    stop = threading.Event()

    class _OutgoingSocket(_FakePacketSocket):
        @override
        def recvfrom(self, size: int) -> tuple[bytes, tuple[object, ...]]:
            del size
            stop.set()
            return frame, ("eth0", 0, 4, 1, b"")

    source = PacketWake(
        QueryEndpoint("127.0.0.1", 15637),
        interface_root=tmp_path,
        socket_factory=lambda _interface: _OutgoingSocket([]),
    )
    assert source.arm() is True

    # WHEN polling
    with patch("enshctl.lifecycle.wake.select.select", return_value=([source._sockets[0]], [], [])):
        event = source.wait(stop, timeout=1)

    # THEN the outgoing frame does not wake the server
    assert event is None


def test_packet_wake_ignores_probe_source_endpoints(tmp_path: Path) -> None:
    # GIVEN an armed source and two client frames, one from the probe endpoint
    (tmp_path / "eth0").mkdir()
    frames = [
        _ipv4_frame(b"\xff\xff\xff\xffTSource Engine Query\x00", destination_port=15637, source_port=50000),
        _ipv4_frame(b"hello", destination_port=15637, source_port=40001),
    ]
    packet_socket = _FakePacketSocket(frames)
    source = PacketWake(
        QueryEndpoint("127.0.0.1", 15637),
        interface_root=tmp_path,
        socket_factory=lambda _interface: packet_socket,
    )
    assert source.arm() is True
    source.ignore_source_endpoints(frozenset({("192.0.2.1", 50000)}))

    # WHEN polling
    with patch("enshctl.lifecycle.wake.select.select", return_value=([packet_socket], [], [])):
        event = source.wait(threading.Event(), timeout=1)

    # THEN the probe packet is skipped and the client packet wakes
    assert event == WakeEvent("192.0.2.1", 40001, 5, "udp")


def test_queue_wake_detects_growth(tmp_path: Path) -> None:
    # GIVEN a query-port queue with a baseline
    udp = tmp_path / "udp"
    udp.write_text(
        "  sl  local_address rem_address   st tx_queue:rx_queue tr:tm->when retrnsmt   uid  timeout inode\n"
        "   0: 0100007F:3D15 00000000:0000 07 00000000:00000000 00:00000000 00000000  1000        0 1\n"
    )
    source = QueueWake(QueryEndpoint("127.0.0.1", 15637), proc_net_root=tmp_path, poll_interval=0.01)
    assert source.arm() is True

    # WHEN the receive queue grows
    udp.write_text(
        "  sl  local_address rem_address   st tx_queue:rx_queue tr:tm->when retrnsmt   uid  timeout inode\n"
        "   0: 0100007F:3D15 00000000:0000 07 00000000:00000064 00:00000000 00000000  1000        0 1\n"
    )
    event = source.wait(threading.Event(), timeout=1)

    # THEN queue growth is reported as a wake event
    assert event == WakeEvent("queue", 0, 100, "udp")


class _FakeWake(WakeSource):
    def __init__(self, armed: bool) -> None:
        self.armed = armed
        self.arm_called = False
        self.closed = False

    @override
    def arm(self) -> bool:
        self.arm_called = True
        return self.armed

    @override
    def ignore_source_endpoints(self, endpoints: frozenset[tuple[str, int]] | None) -> None:
        del endpoints

    @override
    def wait(self, stop_event: threading.Event, timeout: float) -> WakeEvent | None:
        del stop_event, timeout
        return None

    @override
    def close(self) -> None:
        self.closed = True


def test_fallback_wake_uses_queue_when_packet_unavailable() -> None:
    # GIVEN packet capture unavailable and queue fallback available
    packet = _FakeWake(armed=False)
    queue = _FakeWake(armed=True)
    source = FallbackWake(packet, queue)

    # WHEN arming
    assert source.arm() is True

    # THEN the queue fallback is active
    assert queue.arm_called is True
