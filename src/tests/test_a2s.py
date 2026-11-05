"""Tests for the advisory A2S probe."""

import socket
import threading
from typing import Any

from enshctl.config import QueryEndpoint
from enshctl.lifecycle.a2s import A2SProbe, UdpA2STransport, parse_player_count


def _info(players: int) -> bytes:
    return b"\xff\xff\xff\xffI\x11Server\x00World\x00enshrouded\x00Enshrouded\x00\x01\x02" + bytes(
        [players, 6, 0, ord("d"), ord("l"), 1, 0]
    )


class _Transport:
    def __init__(self, responses: list[bytes | None], ports: list[int] | None = None) -> None:
        self.responses = responses
        self.ports = ports or [50000]
        self.payloads: list[bytes] = []
        self.last_local_address: tuple[str, int] | None = None

    def exchange(self, payload: bytes) -> bytes | None:
        self.payloads.append(payload)
        port = self.ports[min(len(self.payloads) - 1, len(self.ports) - 1)]
        self.last_local_address = ("127.0.0.1", port)
        if not self.responses:
            return None
        return self.responses.pop(0)


def test_probe_reads_player_count() -> None:
    # GIVEN a server that answers A2S_INFO without a challenge
    transport = _Transport([_info(1)])

    # WHEN the probe runs
    result = A2SProbe(transport).players()

    # THEN the reported player count is returned
    assert result == 1
    assert len(transport.payloads) == 1


def test_probe_completes_challenge_handshake() -> None:
    # GIVEN a server that returns a challenge before the info response
    challenge = b"\x01\x02\x03\x04"
    transport = _Transport([b"\xff\xff\xff\xffA" + challenge, _info(0)], ports=[50001, 50002])

    # WHEN the probe runs
    probe = A2SProbe(transport)
    result = probe.players()

    # THEN the challenge is echoed in the second request
    assert result == 0
    assert transport.payloads[1].endswith(challenge)

    # AND both probe source endpoints are exposed for wake filtering
    assert probe.last_local_endpoints == frozenset({("127.0.0.1", 50001), ("127.0.0.1", 50002)})


def test_probe_returns_none_after_timeout_and_retry() -> None:
    # GIVEN a server that never answers
    transport = _Transport([None, None])

    # WHEN the probe runs
    result = A2SProbe(transport, retries=1).players()

    # THEN the timeout is neutral and exactly one retry was attempted
    assert result is None
    assert len(transport.payloads) == 2


def test_probe_returns_none_for_malformed_response() -> None:
    # GIVEN a malformed A2S response
    transport = _Transport([b"\xff\xff\xff\xffIbroken", b"\xff\xff\xff\xffIbroken"])

    # WHEN the probe runs
    result = A2SProbe(transport, retries=1).players()

    # THEN the malformed reply is neutral
    assert result is None


def test_parse_player_count_rejects_wrong_header() -> None:
    assert parse_player_count(b"not a2s") is None


def test_parse_player_count_rejects_missing_string() -> None:
    assert parse_player_count(b"\xff\xff\xff\xffI\x11onestring\x00") is None


def test_udp_transport_returns_none_when_resolution_fails() -> None:
    # GIVEN a transport whose resolver fails
    def _resolve(_host: str, _port: int) -> list[Any]:
        message = "no dns"
        raise OSError(message)

    transport = UdpA2STransport(QueryEndpoint("example.invalid", 15637), resolve=_resolve)

    # WHEN exchanging
    result = transport.exchange(b"payload")

    # THEN no reply is reported
    assert result is None


def test_udp_transport_binds_source_to_endpoint_address() -> None:
    # GIVEN a local UDP server
    server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server.bind(("127.0.0.1", 0))
    port = server.getsockname()[1]

    def _serve() -> None:
        _payload, address = server.recvfrom(65535)
        server.sendto(b"reply", address)

    thread = threading.Thread(target=_serve)
    thread.start()
    transport = UdpA2STransport(QueryEndpoint("127.0.0.1", port), timeout=1.0)

    try:
        # WHEN the transport exchanges a datagram
        result = transport.exchange(b"payload")
    finally:
        thread.join(timeout=1)
        server.close()

    # THEN the probe source address matches the endpoint, not the wildcard bind
    assert result == b"reply"
    assert transport.last_local_address is not None
    assert transport.last_local_address[0] == "127.0.0.1"
