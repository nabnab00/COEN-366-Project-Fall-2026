import threading, time, unittest

from server.retransmission import RetransmissionManager
from shared.constants import DeliveryStatus

ADDRESS = ("127.0.0.1", 5999)
PAYLOAD = {"Incident_ID": "INC001", "Version": 1}

TIMEOUT = 0.05

# With base_timeout = 0.05, the waits are 0.05, 0.1 and 0.2 s, so a message is UNCONFIRMED after 0.35 s
ALL_ATTEMPTS = 0.5  # long enough for every attempt to time out
ONE_TIMEOUT = 0.08  # long enough for the first timeout only


class TestRetransmissionManager(unittest.TestCase):

    def setUp(self):
        self.sent = []         # one (address, msg_type, rq_num, payload) per resend
        self.unconfirmed = []  # one PendingNotification per unconfirmed notification
        self.manager = RetransmissionManager(
            resend=self.fake_resend,
            base_timeout=TIMEOUT,
            max_random_delay=0,
            on_unconfirmed=self.unconfirmed.append,
        )

    def tearDown(self):
        self.manager.stop()

    def fake_resend(self, address, msg_type, rq_num, payload):
        self.sent.append((address, msg_type, rq_num, payload))

    # Helper function to wait until a list has 'length' items, fails the test after 'timeout' seconds
    def wait_for_length(self, items, length, timeout=2.0):
        deadline = time.monotonic() + timeout
        while len(items) < length:
            if time.monotonic() > deadline:
                self.fail(f"expected {length} items, got {len(items)}")
            time.sleep(0.01)

    def test_unconfirmed_after_3_attempts(self):
        self.manager.track(1, ADDRESS, "ALERT", PAYLOAD, "Alice")
        self.wait_for_length(self.unconfirmed, 1)
        self.assertEqual(len(self.sent), 2)  # 3 transmissions = the first send (done by the server) + 2 resends
        self.assertEqual(self.unconfirmed[0].name, "Alice")
        self.assertEqual(self.unconfirmed[0].attempts, 3)
        self.assertEqual(self.manager.pending, {})

    def test_resend_using_same_rq_and_payload(self):
        self.manager.track(7, ADDRESS, "ALERT", PAYLOAD, "Alice")
        self.wait_for_length(self.sent, 2)
        for resend in self.sent:
            self.assertEqual(resend, (ADDRESS, "ALERT", 7, PAYLOAD))

    def test_ack_before_timeout(self):
        self.manager.track(1, ADDRESS, "ALERT", PAYLOAD, "Alice")
        self.manager.acknowledge(1)
        time.sleep(ALL_ATTEMPTS)
        self.assertEqual(self.sent, [])
        self.assertEqual(self.unconfirmed, [])

    def test_ack_after_first_resend(self):
        self.manager.track(1, ADDRESS, "ALERT", PAYLOAD, "Alice")
        self.wait_for_length(self.sent, 1)
        self.manager.acknowledge(1)
        time.sleep(ALL_ATTEMPTS)
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.unconfirmed, [])

    def test_duplicate_ack(self):
        self.manager.track(1, ADDRESS, "ALERT", PAYLOAD, "Alice")
        self.assertIsNotNone(self.manager.acknowledge(1))
        self.assertIsNone(self.manager.acknowledge(1))

    def test_peek_does_not_remove(self):
        self.manager.track(1, ADDRESS, "ALERT", PAYLOAD, "Alice")
        self.assertEqual(self.manager.peek(1).name, "Alice")
        self.assertIn(1, self.manager.pending)
        self.assertIsNone(self.manager.peek(2))

    def test_late_ack_after_unconfirmed(self):
        self.manager.track(1, ADDRESS, "ALERT", PAYLOAD, "Alice")
        self.wait_for_length(self.unconfirmed, 1)
        self.assertIsNone(self.manager.acknowledge(1))
        self.assertEqual(self.manager.peek(1, DeliveryStatus.UNCONFIRMED).name, "Alice")  # kept for the late ACK
        self.assertIsNotNone(self.manager.acknowledge(1, DeliveryStatus.UNCONFIRMED))
        self.assertIsNone(self.manager.peek(1, DeliveryStatus.UNCONFIRMED))  # a second late ACK is a duplicate

    def test_wait_time_doubles_each_attempt(self):
        self.assertAlmostEqual(self.manager._wait_for(1), TIMEOUT)
        self.assertAlmostEqual(self.manager._wait_for(2), TIMEOUT * 2)
        self.assertAlmostEqual(self.manager._wait_for(3), TIMEOUT * 4)

    def test_random_delay_stays_in_range(self):
        self.manager.max_random_delay = 0.2
        for i in range(100):
            wait = self.manager._wait_for(1)
            self.assertGreaterEqual(wait, TIMEOUT)
            self.assertLessEqual(wait, TIMEOUT + 0.2)

    def test_new_earlier_deadline_wakes_scheduler(self):
        self.manager.base_timeout = 5
        self.manager.track(1, ADDRESS, "ALERT", PAYLOAD, "Alice")
        self.manager.base_timeout = TIMEOUT
        self.manager.track(2, ADDRESS, "ALERT", PAYLOAD, "Bob")
        self.wait_for_length(self.sent, 1, timeout=1)  # must not wait for rq-1's 5 second timeout deadline
        self.assertEqual(self.sent[0][2], 2)

    def test_resend_error_does_not_stop_scheduler(self):
        calls = []

        def failing_resend(address, msg_type, rq_num, payload):
            calls.append(rq_num)
            if len(calls) == 1:
                raise OSError("simulated send failure")
            self.sent.append((address, msg_type, rq_num, payload))

        manager = RetransmissionManager(
            resend=failing_resend,
            base_timeout=TIMEOUT,
            max_random_delay=0,
        )
        self.addCleanup(manager.stop)
        manager.track(1, ADDRESS, "ALERT", PAYLOAD, "Alice")
        self.wait_for_length(self.sent, 1)  # the first resend failed, the second still arrives
        self.assertEqual(self.sent[0][2], 1)

    def test_many_notifications_use_one_thread(self):
        initial_count = threading.active_count()
        for i in range(1000):
            self.manager.track(i, ADDRESS, "ALERT", PAYLOAD, "Alice")
        self.assertEqual(threading.active_count(), initial_count)
        self.wait_for_length(self.unconfirmed, 1000)
        self.assertEqual(len(self.sent), 2000)


if __name__ == "__main__":
    unittest.main()
