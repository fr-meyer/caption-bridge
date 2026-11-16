"""Socket restrictions for software fixtures, including Windows asyncio IPC."""

from __future__ import annotations

import _socket
import socket
from collections.abc import Callable
from weakref import WeakKeyDictionary

_NATIVE_SOCKETPAIR = socket.socketpair if hasattr(_socket, "socketpair") else None


def _owned_tcp_pair(family=None, type=socket.SOCK_STREAM, proto=0):
    """Build one private pair; the destination comes only from its own listener."""
    if family not in (None, socket.AF_INET) or type != socket.SOCK_STREAM or proto != 0:
        raise ValueError("software_fixture_socketpair_requires_ipv4_stream")
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client = server = None
    try:
        listener.settimeout(1)
        _socket.socket.bind(listener, ("127.0.0.1", 0))
        _socket.socket.listen(listener, 1)
        destination = listener.getsockname()
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.settimeout(1)
        # Only this newly owned listener is reachable through the captured
        # primitive; public connect/connect_ex remain denied throughout.
        _socket.socket.connect(client, destination)
        server, _ = listener.accept()
        if (client.getpeername() != server.getsockname()
                or server.getpeername() != client.getsockname()):
            raise RuntimeError("software_fixture_socketpair_peer_mismatch")
        client.settimeout(None)
        server.settimeout(None)
        return server, client
    except BaseException:
        if client is not None:
            client.close()
        if server is not None:
            server.close()
        raise
    finally:
        listener.close()


class SoftwareNetworkGuard:
    """Deny public network APIs; admit only private IPC and owned listeners."""

    def __init__(self, deny: Callable) -> None:
        self._deny = deny
        self._listeners: WeakKeyDictionary = WeakKeyDictionary()
        self._previous = None
        self.fallback_pairs_created = 0

    def create_listener(self, port: int) -> socket.socket:
        """Create an owned IPv4 loopback listener, never a general bind exemption."""
        if type(port) is not int or not 0 <= port <= 65535:
            raise ValueError("software_fixture_listener_port_invalid")
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            _socket.socket.bind(listener, ("127.0.0.1", port))
            _socket.socket.listen(listener, 128)
            self._listeners[listener] = (listener.fileno(), listener.getsockname())
            return listener
        except BaseException:
            listener.close()
            raise

    def socketpair(self, family=None, type=socket.SOCK_STREAM, proto=0):
        if _NATIVE_SOCKETPAIR is not None:
            return _NATIVE_SOCKETPAIR(family, type, proto)
        pair = _owned_tcp_pair(family, type, proto)
        self.fallback_pairs_created += 1
        return pair

    def install(self):
        if self._previous is not None:
            raise RuntimeError("software_fixture_guard_already_installed")
        methods = ("connect", "connect_ex", "sendto", "bind", "listen")
        if hasattr(socket.socket, "sendmsg"):
            methods += ("sendmsg",)
        self._previous = {
            "methods": {name: getattr(socket.socket, name) for name in methods},
            "socketpair": socket.socketpair,
            "getaddrinfo": socket.getaddrinfo,
        }

        def listen(sock, backlog=128):
            try:
                owned = self._listeners.get(sock) == (sock.fileno(), sock.getsockname())
            except OSError:
                owned = False
            if not owned:
                return self._deny(sock, backlog)
            return _socket.socket.listen(sock, backlog)

        for name in methods:
            setattr(socket.socket, name, self._deny)
        socket.socket.listen = listen
        socket.socketpair = self.socketpair
        socket.getaddrinfo = self._deny
        return self

    def close(self):
        for listener in list(self._listeners):
            listener.close()
        self._listeners.clear()
        if self._previous is not None:
            for name, method in self._previous["methods"].items():
                setattr(socket.socket, name, method)
            socket.socketpair = self._previous["socketpair"]
            socket.getaddrinfo = self._previous["getaddrinfo"]
            self._previous = None
