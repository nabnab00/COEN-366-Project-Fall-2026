import socket

from tests.helpers import ServerTestCase
from tests.test_alerts import alert_data

class TestCloseAlert(ServerTestCase):
    """CLOSE_ALERT, ALERT_CLOSED, and ALL_CLEAR messages are sent correctly."""

    server_args = ["--ack-timeout", "0.2"]

    def setUp(self):
        # every test starts with a publisher, Alice subscribed to HALL/FIRE, and one INFO alert sent to her
        super().setUp()
        self.publisher = self.new_client()
        self.register(self.publisher, "CampusSecurity", "PUBLISHER", tcp_port=7001)

        self.alice = self.new_client()
        self.register(self.alice, "Alice")
        self.subscribe(self.alice, "Alice", "HALL", "FIRE")

        reply = self.request(self.publisher, "PUBLISH_ALERT", 45, alert_data(Severity="INFO"))
        self.incident_id = reply["data"]["Incident_ID"]
        self.receive(self.alice) # the ALERT

    def close(self, sock):
        return self.request(sock, "CLOSE_ALERT", 81, {"Incident_ID": self.incident_id, "Reason": "Building_Reopened"})

    def test_close_sends_all_clear(self):
        reply = self.close(self.publisher)
        self.assertEqual(reply["type"], "ALERT_CLOSED")

        all_clear = self.receive(self.alice)
        self.assertEqual(all_clear["type"], "ALL_CLEAR")
        self.assertEqual(all_clear["data"], {"Incident_ID": self.incident_id, "Version": 2, "Message": "Building_Reopened"})

        # Alice ACKs so the server stops sending
        self.send(self.alice, "ALERT_ACK", all_clear["rq"], {"Incident_ID": self.incident_id, "Version": 2, "Name": "Alice"})
        self.alice.settimeout(2)
        with self.assertRaises(socket.timeout):
            self.receive(self.alice)

    def test_all_clear_is_sent_3_times_without_ack(self):
        self.close(self.publisher)
        copies = [self.receive(self.alice) for _ in range(3)]
        self.assertEqual(copies[0]["rq"], copies[1]["rq"])
        self.assertEqual(copies[1]["rq"], copies[2]["rq"])

    def test_all_clear_reaches_old_and_new_subscribers(self):
        self.unsubscribe(self.alice, "Alice", "HALL", "FIRE") # got the alert, no longer subscribed
        bob = self.new_client()
        self.register(bob, "Bob")
        self.subscribe(bob, "Bob", "HALL", "FIRE")

        self.close(self.publisher)
        self.assertEqual(self.receive(self.alice)["type"], "ALL_CLEAR")
        self.assertEqual(self.receive(bob)["type"], "ALL_CLEAR")

    def test_cannot_close_twice(self):
        self.close(self.publisher)
        reply = self.close(self.publisher)
        self.assertEqual(reply["data"]["Reason"], "Incident_Closed")

    def test_only_the_incident_publisher_can_close(self):
        other = self.new_client()
        self.register(other, "Facilities", "PUBLISHER", tcp_port=7002)
        self.assertEqual(self.close(other)["data"]["Reason"], "Not_Incident_Publisher")
        self.assertEqual(self.close(self.alice)["data"]["Reason"], "Unauthorized_Role")

    def test_unknown_incident(self):
        reply = self.request(self.publisher, "CLOSE_ALERT", 81, {"Incident_ID": "unknown", "Reason": "Test"})
        self.assertEqual(reply["data"]["Reason"], "Unknown_Incident")

    def test_malformed_request(self):
        bad_payloads = {
            "missing Reason": {"Incident_ID": self.incident_id},
            "missing Incident_ID": {"Reason": "Building_Reopened"},
            "empty Reason": {"Incident_ID": self.incident_id, "Reason": ""},
            "Incident_ID is a list": {"Incident_ID": [self.incident_id], "Reason": "Building_Reopened"},
            "Reason is a number": {"Incident_ID": self.incident_id, "Reason": 5},
        }
        for case, data in bad_payloads.items():
            with self.subTest(case):
                reply = self.request(self.publisher, "CLOSE_ALERT", 81, data)
                self.assertEqual(reply["type"], "ALERT_DENIED")
                self.assertEqual(reply["data"]["Reason"], "Malformed_Request")

        # the server is still running and the incident is still open
        self.assertEqual(self.close(self.publisher)["type"], "ALERT_CLOSED")

    def test_both_role_can_close_own_incident(self):
        facilities = self.new_client()
        self.register(facilities, "Facilities", "BOTH", tcp_port=7002)
        reply = self.request(facilities, "PUBLISH_ALERT", 45, alert_data(Severity="INFO", Title="Power Outage"))
        incident_id = reply["data"]["Incident_ID"]
        self.receive(self.alice) # the ALERT for Facilities' incident

        reply = self.request(facilities, "CLOSE_ALERT", 81, {"Incident_ID": incident_id, "Reason": "Power_Restored"})
        self.assertEqual(reply["type"], "ALERT_CLOSED")
        self.assertEqual(reply["data"]["Incident_ID"], incident_id)
        self.assertEqual(self.receive(self.alice)["type"], "ALL_CLEAR")

    def test_subscriber_who_got_alert_and_is_still_subscribed_gets_one_all_clear(self):
        # Alice is both an alert recipient and a current subscriber, so she must not get two separate ALL_CLEARs
        self.close(self.publisher)
        self.alice.settimeout(2)
        messages = []
        try:
            while True:
                messages.append(self.receive(self.alice))
        except socket.timeout:
            pass

        self.assertTrue(messages)
        self.assertTrue(all(m["type"] == "ALL_CLEAR" for m in messages))
        # retransmissions reuse the same RQ#, so one notification means one RQ#
        self.assertEqual(len({m["rq"] for m in messages}), 1)

    def test_unregistered_client_cannot_close(self):
        stranger = self.new_client()
        reply = self.close(stranger)
        self.assertEqual(reply["type"], "ALERT_DENIED")
        self.assertEqual(reply["data"]["Reason"], "Not_Registered")