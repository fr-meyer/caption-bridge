"""Exercise Windows-style IPC locally without authorizing general networking."""

from __future__ import annotations

import asyncio
import socket

import pytest

from scripts import software_network_guard as network


@pytest.fixture
def guarded(monkeypatch):
    # Force CPython's Windows-style path on the local host; this is not an
    # assertion that native Windows or its Proactor loop has been executed.
    monkeypatch.setattr(network, "_NATIVE_SOCKETPAIR", None)
    denied = []

    def reject(*_args, **_kwargs):
        denied.append(True)
        raise RuntimeError("network_denied")

    guard = network.SoftwareNetworkGuard(reject).install()
    try:
        yield guard, denied
    finally:
        guard.close()


def test_owned_pair_is_bidirectional_and_does_not_open_public_connect(guarded):
    guard, denied = guarded
    left, right = socket.socketpair()
    try:
        left.settimeout(0.5)
        right.settimeout(0.5)
        left.sendall(b"left")
        assert right.recv(4) == b"left"
        right.sendall(b"right")
        assert left.recv(5) == b"right"
        assert left.getpeername() == right.getsockname()
        assert right.getpeername() == left.getsockname()
        with pytest.raises(RuntimeError, match="network_denied"):
            left.connect(right.getsockname())
    finally:
        left.close()
        right.close()
    assert guard.fallback_pairs_created == 1 and denied == [True]


@pytest.mark.parametrize("method", ["connect", "connect_ex"])
@pytest.mark.parametrize("address", [("203.0.113.20", 443), ("127.0.0.1", 9), ("::1", 9)])
def test_external_and_unowned_loopback_connections_remain_denied(guarded, method, address):
    _guard, denied = guarded
    with socket.socket() as client:
        with pytest.raises(RuntimeError, match="network_denied"):
            getattr(client, method)(address)
    assert denied == [True]


def test_only_registered_listener_can_listen_and_its_port_is_not_a_connect_exemption(guarded):
    guard, denied = guarded
    listener = guard.create_listener(0)
    assert listener.getsockname()[0] == "127.0.0.1"
    listener.listen(4)
    with socket.socket() as other:
        with pytest.raises(RuntimeError, match="network_denied"):
            other.listen(1)
        with pytest.raises(RuntimeError, match="network_denied"):
            other.bind(("127.0.0.1", 0))
        with pytest.raises(RuntimeError, match="network_denied"):
            other.bind(("0.0.0.0", 0))
        with pytest.raises(RuntimeError, match="network_denied"):
            other.connect(listener.getsockname())
    listener.close()
    with pytest.raises(RuntimeError, match="network_denied"):
        listener.listen(1)
    assert len(denied) == 5


def test_datagrams_and_dns_remain_denied(guarded):
    _guard, denied = guarded
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
        with pytest.raises(RuntimeError, match="network_denied"):
            client.sendto(b"synthetic", ("203.0.113.20", 9))
    with pytest.raises(RuntimeError, match="network_denied"):
        socket.getaddrinfo("example.invalid", 443)
    assert len(denied) == 2


@pytest.mark.parametrize("kwargs", [
    {"family": socket.AF_INET6}, {"type": socket.SOCK_DGRAM}, {"proto": 6},
])
def test_private_pair_has_no_arbitrary_destination_or_protocol(guarded, kwargs):
    _guard, denied = guarded
    with pytest.raises(ValueError, match="requires_ipv4_stream"):
        socket.socketpair(**kwargs)
    assert denied == []


def test_async_event_loop_and_owned_server_work_with_fallback_pair(guarded):
    guard, denied = guarded
    listener = guard.create_listener(0)

    async def scenario():
        server = await asyncio.get_running_loop().create_server(asyncio.Protocol, sock=listener)
        assert server.sockets[0].getsockname() == listener.getsockname()
        server.close()
        await server.wait_closed()

    asyncio.run(scenario())
    assert guard.fallback_pairs_created >= 1 and denied == []
    assert listener.fileno() == -1
