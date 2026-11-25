import socket, subprocess, sys, unittest
from tests.helpers import REPO, ServerTestCase
from tests.test_alerts import alert_data

class TestLostAcks(ServerTestCase):
    """every ALERT_ACK is dropped, so the server acts as if the subscriber never answered."""

    server_args = ["--ack-timeout", "0.2", "--drop-rate", "1"]

    def subscriber(self, name):
        sock = self.new_client()
        self.register(sock, name)
        self.assertEqual(self.subscribe(sock, name, "HALL", "FIRE")["type"], "SUBSCRIBED")
        return sock

    def publish(self):
        publisher = self.new_client()
        self.register(publisher, "CampusSecurity", "PUBLISHER", tcp_port=7001)
        reply = self.request(publisher, "PUBLISH_ALERT", 45, alert_data())
        self.assertEqual(reply["type"], "ALERT_ACCEPTED")

    def receive_and_ack(self, sock, name):
        alert = self.receive(sock)
        self.assertEqual(alert["type"], "ALERT")
        data = {"Incident_ID": alert["data"]["Incident_ID"], "Version": alert["data"]["Version"], "Name": name}
        self.send(sock, "ALERT_ACK", alert["rq"], data)
        return alert

    def assert_nothing_received(self, sock):
        sock.settimeout(2)
        with self.assertRaises(socket.timeout):
            sock.recvfrom(4096)

    def test_lost_acks_cause_three_copies_then_stop(self):
        alice = self.subscriber("Alice")
        self.publish()
        alerts = [self.receive_and_ack(alice, "Alice") for _ in range(3)]
        self.assertEqual({alert["rq"] for alert in alerts}, {alerts[0]["rq"]}) # same alert same rq #
        self.assertEqual({alert["data"]["Version"] for alert in alerts}, {1}) # duplicate not a new version
        self.assert_nothing_received(alice) # the server gave up and marked Alice UNCONFIRMED

    def test_server_keeps_answering_while_acks_are_lost(self):
        names = ["Alice", "Bob", "Carol"]
        subscribers = {name: self.subscriber(name) for name in names}
        self.publish()
        for name in names:
            self.receive_and_ack(subscribers[name], name)

        # several retransmission timers are running now, other requests must still be answered
        dave = self.new_client()
        self.assertEqual(self.register(dave, "Dave")["type"], "REGISTERED")

        for name in names:
            # each subscriber still gets its own 2 retransmissions
            for _ in range(2):
                self.receive_and_ack(subscribers[name], name)


class TestDefaultDropRate(ServerTestCase):
    """without --drop-rate no ACK is dropped, so the ALERT is sent only once."""

    server_args = ["--ack-timeout", "0.2"]

    def test_ack_is_not_dropped(self):
        alice = self.new_client()
        self.register(alice, "Alice")
        self.subscribe(alice, "Alice", "HALL", "FIRE")
        publisher = self.new_client()
        self.register(publisher, "CampusSecurity", "PUBLISHER", tcp_port=7001)
        self.request(publisher, "PUBLISH_ALERT", 45, alert_data())

        alert = self.receive(alice)
        self.send(alice, "ALERT_ACK", alert["rq"], {"Incident_ID": alert["data"]["Incident_ID"], "Version": 1, "Name": "Alice"})
        alice.settimeout(2)
        with self.assertRaises(socket.timeout):
            self.receive(alice) # no retransmission


class TestInvalidDropRate(unittest.TestCase):
    """a drop rate outside 0 to 1 makes the server refuse to start."""

    def test_server_refuses_to_start(self):
        for rate in ["1.5", "-0.1"]:
            result = subprocess.run([sys.executable, "-m", "server.emergency_server", "--drop-rate", rate],
                                    cwd=REPO, capture_output=True, timeout=5)
            self.assertNotEqual(result.returncode, 0)
