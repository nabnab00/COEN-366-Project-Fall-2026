import socket
from shared.protocol import ProtocolMessage, MalformedMessageError

DEFAULT_TIMEOUT = 10.0
MAX_LINE_LENGTH = 64*1024
CHUNK_SIZE = 64*1024

class ConnectionClosedError(Exception):
    """The other side closed the connection before the expected data arrived."""

class TCPConnection:

    def __init__(self, sock, timeout=DEFAULT_TIMEOUT):
        self.sock = sock
        self.sock.settimeout(timeout)
        self._buffer = bytearray()

    @classmethod
    def connect(cls, host, port, timeout=DEFAULT_TIMEOUT):
        return cls(socket.create_connection((host, port), timeout=timeout), timeout)

    def send_message(self, msg_type, rq_num, payload=None):
        self.sock.sendall(ProtocolMessage.encode(msg_type, rq_num, payload) + b"\n")

    def send_bytes(self, data: bytes):
        self.sock.sendall(data)

    def recv_message(self) -> dict:
        return ProtocolMessage.decode(self._recv_line())

    def recv_exact(self, size: int) -> bytes:
        while len(self._buffer) < size:
            self._fill()
        data = bytes(self._buffer[:size])
        del self._buffer[:size]
        return data

    def _recv_line(self) -> bytes:
        while True:
            end = self._buffer.find(b"\n")
            if end != -1:
                if end > MAX_LINE_LENGTH:
                    raise MalformedMessageError("Message line too long")
                line = bytes(self._buffer[:end])
                del self._buffer[:end + 1]
                return line
            if len(self._buffer) > MAX_LINE_LENGTH:
                raise MalformedMessageError("Message line too long")
            self._fill()

    def _fill(self):
        chunk = self.sock.recv(CHUNK_SIZE)
        if not chunk:
            raise ConnectionClosedError("Connection closed by the other side")
        self._buffer.extend(chunk)

    def close(self):
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass  # already closed by the other side
        self.sock.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()