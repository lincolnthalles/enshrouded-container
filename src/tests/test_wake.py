"""Tests for Auto Pause wake sources."""

import threading
from ipaddress import IPv4Network, IPv6Network
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
    build_wake_source,
    classify_udp_packet,
)

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def _ipv4_frame(
    payload: bytes,
    *,
    destination_port: int,
    source_port: int = 40000,
    source: bytes = bytes([192, 0, 2, 1]),
) -> bytes:
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
        + source
        + bytes([192, 0, 2, 2])
        + udp
    )
    return b"\x00" * 12 + b"\x08\x00" + ipv4


def _ipv6_frame(
    payload: bytes,
    *,
    destination_port: int,
    source: bytes = bytes.fromhex("20010db8000000000000000000000001"),
) -> bytes:
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
        + source
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


class _ExhaustibleSocket(_FakePacketSocket):
    def __init__(self, frames: list[bytes], stop: threading.Event) -> None:
        super().__init__(frames)
        self._stop = stop

    @override
    def recvfrom(self, size: int) -> tuple[bytes, tuple[object, ...]]:
        if not self.frames:
            self._stop.set()
            raise OSError
        return super().recvfrom(size)


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


def test_packet_wake_drops_denied_sources(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # GIVEN a denied IPv4 block, a denied IPv6 block, and one allowed source
    (tmp_path / "eth0").mkdir()
    stop = threading.Event()
    denied_a2s = _ipv4_frame(
        b"\xff\xff\xff\xffTSource Engine Query\x00",
        destination_port=15637,
        source=bytes([192, 0, 2, 1]),
    )
    denied_ipv4 = _ipv4_frame(b"hello", destination_port=15637, source=bytes([192, 0, 2, 1]))
    denied_ipv6 = _ipv6_frame(
        b"hello",
        destination_port=15637,
        source=bytes.fromhex("20010db8000000000000000000000001"),
    )
    allowed = _ipv4_frame(b"hello", destination_port=15637, source=bytes([198, 51, 100, 1]))

    packet_socket = _ExhaustibleSocket([denied_a2s, denied_ipv4, denied_ipv6, allowed], stop)
    source = PacketWake(
        QueryEndpoint("127.0.0.1", 15637),
        interface_root=tmp_path,
        socket_factory=lambda _interface: packet_socket,
        deny_sources=(IPv4Network("192.0.2.0/24"), IPv6Network("2001:db8::/32")),
    )
    assert source.arm() is True

    # WHEN polling
    with (
        patch("enshctl.lifecycle.wake.select.select", return_value=([packet_socket], [], [])),
        caplog.at_level("INFO", logger="enshctl.lifecycle.wake"),
    ):
        event = source.wait(stop, timeout=1)

    # THEN every denied packet is skipped, the allowed packet wakes, and each source logs once
    assert event == WakeEvent("198.51.100.1", 40000, 5, "udp")
    denied_records = [record for record in caplog.records if "denied source" in record.message]
    assert len(denied_records) == 2
    assert all(record.levelname == "INFO" for record in denied_records)
    assert {record.message.rsplit(" ", maxsplit=1)[-1] for record in denied_records} == {
        "192.0.2.1",
        "2001:db8::1",
    }


def test_packet_wake_can_arm_false_when_no_interface_opens(tmp_path: Path) -> None:
    # GIVEN an interface that cannot open a packet socket
    (tmp_path / "eth0").mkdir()

    def _factory(_interface: str) -> _FakePacketSocket:
        raise OSError

    source = PacketWake(QueryEndpoint("127.0.0.1", 15637), interface_root=tmp_path, socket_factory=_factory)

    # WHEN checking availability
    # THEN the source cannot arm
    assert source.can_arm() is False


def test_packet_wake_logs_denied_source_after_rearm(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # GIVEN one denied packet per arm
    (tmp_path / "eth0").mkdir()
    denied = _ipv4_frame(b"hello", destination_port=15637)
    stops = [threading.Event(), threading.Event()]
    sockets = [_ExhaustibleSocket([denied], stops[0]), _ExhaustibleSocket([denied], stops[1])]
    source = PacketWake(
        QueryEndpoint("127.0.0.1", 15637),
        interface_root=tmp_path,
        socket_factory=lambda _interface: sockets.pop(0),
        deny_sources=(IPv4Network("192.0.2.0/24"),),
    )

    # WHEN the source is armed, denied, closed, and armed again
    with caplog.at_level("INFO", logger="enshctl.lifecycle.wake"):
        for stop in stops:
            assert source.arm() is True
            with patch("enshctl.lifecycle.wake.select.select", return_value=([source._sockets[0]], [], [])):
                assert source.wait(stop, timeout=0.01) is None
            source.close()

    # THEN each arm logs the denied source once
    denied_records = [record for record in caplog.records if "denied source" in record.message]
    assert len(denied_records) == 2


def test_packet_wake_bounds_denied_source_logging(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # GIVEN more distinct denied sources than the logging bound
    (tmp_path / "eth0").mkdir()
    stop = threading.Event()
    frames = [_ipv4_frame(b"hello", destination_port=15637, source=bytes([192, 0, 2, index])) for index in range(1, 66)]
    allowed = _ipv4_frame(b"hello", destination_port=15637, source=bytes([198, 51, 100, 1]))
    packet_socket = _ExhaustibleSocket([*frames, allowed], stop)
    source = PacketWake(
        QueryEndpoint("127.0.0.1", 15637),
        interface_root=tmp_path,
        socket_factory=lambda _interface: packet_socket,
        deny_sources=(IPv4Network("192.0.2.0/24"),),
    )
    assert source.arm() is True

    # WHEN polling all frames
    with (
        patch("enshctl.lifecycle.wake.select.select", return_value=([packet_socket], [], [])),
        caplog.at_level("INFO", logger="enshctl.lifecycle.wake"),
    ):
        event = source.wait(stop, timeout=1)

    # THEN the allowed source wakes and denied logging stops at the bound
    assert event == WakeEvent("198.51.100.1", 40000, 5, "udp")
    denied_records = [record for record in caplog.records if "denied source" in record.message]
    assert len(denied_records) == 64


def test_packet_wake_denied_source_does_not_wake(tmp_path: Path) -> None:
    # GIVEN an armed source whose only packet is a denied A2S query
    (tmp_path / "eth0").mkdir()
    stop = threading.Event()
    packet_socket = _ExhaustibleSocket(
        [_ipv4_frame(b"\xff\xff\xff\xffTSource Engine Query\x00", destination_port=15637)],
        stop,
    )
    source = PacketWake(
        QueryEndpoint("127.0.0.1", 15637),
        interface_root=tmp_path,
        socket_factory=lambda _interface: packet_socket,
        deny_sources=(IPv4Network("192.0.2.1/32"),),
    )
    assert source.arm() is True

    # WHEN polling only the denied packet
    with patch("enshctl.lifecycle.wake.select.select", return_value=([packet_socket], [], [])):
        event = source.wait(stop, timeout=0.01)

    # THEN no wake event is reported
    assert event is None


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
    def can_arm(self) -> bool:
        return self.armed

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


def test_fallback_wake_can_arm_refuses_queue_when_source_filtering_is_required() -> None:
    # GIVEN packet capture unavailable and a deny list that queue polling cannot enforce
    packet = _FakeWake(armed=False)
    queue = _FakeWake(armed=True)
    source = FallbackWake(packet, queue, requires_packet_capture=True)

    # WHEN checking availability
    # THEN the queue fallback is not considered
    assert source.can_arm() is False


def test_fallback_wake_refuses_queue_when_source_filtering_is_required() -> None:
    # GIVEN packet capture unavailable and a deny list that queue polling cannot enforce
    packet = _FakeWake(armed=False)
    queue = _FakeWake(armed=True)
    source = FallbackWake(packet, queue, requires_packet_capture=True)

    # WHEN arming
    armed = source.arm()

    # THEN the wake source is unavailable and the queue fallback is not armed
    assert armed is False
    assert queue.arm_called is False


def test_build_wake_source_refuses_a_configured_all_invalid_deny_list() -> None:
    # GIVEN a configured list with no valid networks
    source = build_wake_source(
        QueryEndpoint("127.0.0.1", 15637),
        deny_sources=(),
        deny_configured=True,
    )

    # WHEN checking availability
    # THEN no wake source can be armed
    assert source.can_arm() is False
    assert source.arm() is False
