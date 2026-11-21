import os, tempfile, time, unittest
from types import SimpleNamespace

from server import acks
from server.emergency_server import EmergencyServer
from server.retransmission import RetransmissionManager
from server.server_state import ServerState

ADDRESS = ("127.0.0.1", 6000)
PAYLOAD = {"Incident_ID": "INC001", "Version": 1}


class TestLateAck(unittest.TestCase):
    """Test the late ACK handling logic."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        old_cwd = os.getcwd()
        os.chdir(tmp.name)
        self.addCleanup(os.chdir, old_cwd)

        self.state = ServerState("state.json")
        # mark_unconfirmed only uses self.state, so a stand-in object is enough (no real server or socket)
        fake_server = SimpleNamespace(state=self.state)
        self.retransmitter = RetransmissionManager(
            resend=lambda *args: None,
            base_timeout=0.05,  # gives up after about 0.35 s
            max_random_delay=0,
            on_unconfirmed=lambda notification: EmergencyServer.mark_unconfirmed(fake_server, notification),
        )
        self.addCleanup(self.retransmitter.stop)

    def ack(self, rq_num, version=1, name="Alice", addr=ADDRESS):
        msg = {"rq": rq_num, "data": {"Incident_ID": "INC001", "Version": version, "Name": name}}
        acks.handle_alert_ack(self.state, self.retransmitter, msg, addr)

    def status(self):
        return self.state.delivery_status["INC001"]["Alice"]["status"]

    def wait_until_unconfirmed(self):
        deadline = time.monotonic() + 2
        while self.state.delivery_status.get("INC001", {}).get("Alice", {}).get("status") != "UNCONFIRMED":
            if time.monotonic() > deadline:
                self.fail("the server never gave up on the ALERT")
            time.sleep(0.01)

    def test_ack_in_time_confirms(self):
        self.retransmitter.track(1, ADDRESS, "ALERT", PAYLOAD, "Alice")
        self.ack(1)
        self.assertEqual(self.status(), "CONFIRMED")

    def test_late_ack_confirms(self):
        self.retransmitter.track(1, ADDRESS, "ALERT", PAYLOAD, "Alice")
        self.wait_until_unconfirmed()
        self.ack(1)
        self.assertEqual(self.status(), "CONFIRMED")

    def test_wrong_late_ack_is_ignored_and_right_one_still_works(self):
        self.retransmitter.track(1, ADDRESS, "ALERT", PAYLOAD, "Alice")
        self.wait_until_unconfirmed()

        self.ack(1, version=2)
        self.assertEqual(self.status(), "UNCONFIRMED")
        self.ack(1, addr=("127.0.0.1", 7000))
        self.assertEqual(self.status(), "UNCONFIRMED")

        self.ack(1)
        self.assertEqual(self.status(), "CONFIRMED")

    def test_second_late_ack_is_duplicate(self):
        self.retransmitter.track(1, ADDRESS, "ALERT", PAYLOAD, "Alice")
        self.wait_until_unconfirmed()
        self.ack(1)
        self.ack(1)
        self.assertEqual(self.status(), "CONFIRMED")
        self.assertEqual(self.retransmitter.unconfirmed, {})


class TestMarkUnconfirmed(unittest.TestCase):
    """Test the mark_unconfirmed logic."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        old_cwd = os.getcwd()
        os.chdir(tmp.name)
        self.addCleanup(os.chdir, old_cwd)

        self.state = ServerState("state.json")
        self.fake_server = SimpleNamespace(state=self.state)
        self.notification = SimpleNamespace(payload=PAYLOAD, name="Alice")

    def test_keeps_confirmed_for_same_version(self):
        self.state.record_delivery("INC001", 1, "Alice", "CONFIRMED")
        EmergencyServer.mark_unconfirmed(self.fake_server, self.notification)
        self.assertEqual(self.state.delivery_status["INC001"]["Alice"]["status"], "CONFIRMED")

    def test_overwrites_confirmed_for_older_version(self):
        self.state.record_delivery("INC001", 1, "Alice", "CONFIRMED")
        version_2 = SimpleNamespace(payload={"Incident_ID": "INC001", "Version": 2}, name="Alice")
        EmergencyServer.mark_unconfirmed(self.fake_server, version_2)
        self.assertEqual(self.state.delivery_status["INC001"]["Alice"],
                         {"version": 2, "status": "UNCONFIRMED"})


if __name__ == "__main__":
    unittest.main()
