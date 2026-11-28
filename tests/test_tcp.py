import json, socket, threading, time, unittest

from shared.protocol import MalformedMessageError
from shared.tcp import TCPConnection, ConnectionClosedError, MAX_LINE_LENGTH, MAX_FILE_SIZE
from tests.helpers import ServerTestCase, SERVER


class TestFraming(unittest.TestCase):
    """shared/tcp.py over a connected socket pair."""

    def setUp(self):
        a, b = socket.socketpair()
        self.sender = TCPConnection(a, timeout=1.0)
        self.receiver = TCPConnection(b, timeout=1.0)
        self.raw = a  # to send bytes in odd pieces
        self.addCleanup(self.sender.close)
        self.addCleanup(self.receiver.close)

    def test_message_round_trip(self):
        self.sender.send_message("GET_ACTIVE_ALERTS", 22, {"Name": "Alice"})
        self.assertEqual(self.receiver.recv_message(),
                         {"type": "GET_ACTIVE_ALERTS", "rq": 22, "data": {"Name": "Alice"}})

    def test_two_messages_in_one_send(self):
        self.raw.sendall(b'{"type": "A", "rq": 1, "data": {}}\n{"type": "B", "rq": 2, "data": {}}\n')
        self.assertEqual(self.receiver.recv_message()["type"], "A")
        self.assertEqual(self.receiver.recv_message()["type"], "B")

    def test_message_split_across_sends(self):
        line = b'{"type": "ACTIVE_ALERTS", "rq": 22, "data": {"Number_Alerts": 2}}\n'
        def send_slowly():
            for i in range(0, len(line), 5):
                self.raw.sendall(line[i:i + 5])
                time.sleep(0.005)
        threading.Thread(target=send_slowly).start()
        self.assertEqual(self.receiver.recv_message()["data"], {"Number_Alerts": 2})

    def test_newline_inside_a_string_is_escaped(self):
        self.sender.send_message("X", 1, {"Description": "line one\nline two"})
        self.assertEqual(self.receiver.recv_message()["data"]["Description"], "line one\nline two")

    def test_file_bytes_after_header(self):
        # header and file arrive in the same send: the buffered start of the file must not be lost
        content = bytes(range(256)) * 1000 + b"\n\n"
        header = json.dumps({"type": "ATTACH_DATA", "rq": 94, "data": {"File_Size": len(content)}}).encode()
        threading.Thread(target=self.raw.sendall, args=(header + b"\n" + content,)).start()
        msg = self.receiver.recv_message()
        self.assertEqual(self.receiver.recv_exact(msg["data"]["File_Size"]), content)

    def test_message_after_file_bytes(self):
        self.raw.sendall(b'{"type": "ATTACH_DATA", "rq": 9, "data": {}}\nabc{"type": "ATTACH_OK", "rq": 9, "data": {}}\n')
        self.receiver.recv_message()
        self.assertEqual(self.receiver.recv_exact(3), b"abc")
        self.assertEqual(self.receiver.recv_message()["type"], "ATTACH_OK")

    def test_closed_mid_message(self):
        self.raw.sendall(b'{"type": "A", "rq"')
        self.raw.shutdown(socket.SHUT_WR)
        with self.assertRaises(ConnectionClosedError):
            self.receiver.recv_message()

    def test_closed_before_all_file_bytes(self):
        self.raw.sendall(b"only 10 b.")
        self.raw.shutdown(socket.SHUT_WR)
        with self.assertRaises(ConnectionClosedError):
            self.receiver.recv_exact(100)

    def test_recv_exact_rejects_bad_size(self):
        with self.assertRaises(ValueError):
            self.receiver.recv_exact(-5)
        with self.assertRaises(ValueError):
            self.receiver.recv_exact(True)
        with self.assertRaises(ValueError):
            self.receiver.recv_exact(3.5)
        with self.assertRaises(ValueError):
            self.receiver.recv_exact(MAX_FILE_SIZE + 1)
        self.assertEqual(self.receiver.recv_exact(0), b"")

    def test_invalid_json_line(self):
        self.raw.sendall(b"not json\n")
        with self.assertRaises(MalformedMessageError):
            self.receiver.recv_message()

    def test_line_too_long(self):
        threading.Thread(target=self.raw.sendall, args=(b"x" * (MAX_LINE_LENGTH + 10),)).start()
        with self.assertRaises(MalformedMessageError):
            self.receiver.recv_message()

    def test_line_too_long_with_newline(self):
        # newline arrives in the same chunk
        threading.Thread(target=self.raw.sendall, args=(b"x" * (MAX_LINE_LENGTH + 10) + b"\n",)).start()
        with self.assertRaises(MalformedMessageError):
            self.receiver.recv_message()

    def test_silent_peer_times_out(self):
        with self.assertRaises(socket.timeout):
            self.receiver.recv_message()


class TestServerTCP(ServerTestCase):
    """The server's TCP listener."""

    def connect(self):
        tcp = TCPConnection.connect(*SERVER, timeout=1.0)
        self.addCleanup(tcp.close)
        return tcp

    def assert_closed_by_server(self, tcp):
        with self.assertRaises(ConnectionClosedError):
            tcp.recv_message()

    def test_server_accepts_tcp(self):
        tcp = self.connect()
        tcp.send_message("NOT_A_TCP_REQUEST", 1, {})
        self.assert_closed_by_server(tcp)  # unknown request: logged, connection closed

    def test_garbage_is_dropped(self):
        tcp = self.connect()
        tcp.send_bytes(b"hello\n")
        self.assert_closed_by_server(tcp)

    def test_idle_connections_do_not_block_others(self):
        idle = [self.connect() for _ in range(5)]  # connected but never send anything
        tcp = self.connect()
        tcp.send_message("NOT_A_TCP_REQUEST", 2, {})
        self.assert_closed_by_server(tcp)  # answered while the 5 idle connections are still open
        self.assertEqual(len(idle), 5)

    def test_udp_still_works_alongside_tcp(self):
        tcp = self.connect()
        reply = self.register(self.new_client(), "Alice")
        self.assertEqual(reply["type"], "REGISTERED")
        tcp.send_message("NOT_A_TCP_REQUEST", 3, {})
        self.assert_closed_by_server(tcp)


if __name__ == "__main__":
    unittest.main()