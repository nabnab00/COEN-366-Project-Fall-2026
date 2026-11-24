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