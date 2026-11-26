import socket

from tests.helpers import ServerTestCase


def alert_data(**overrides):
    data = {
        "Category": "FIRE",
        "Location": "HALL",
        "Severity": "WARNING",
        "Title": "Fire alarm",
        "Description": "Leave the building",
        "Attachment": "NONE",
    }
    data.update(overrides)
    return data


def update_data(incident_id, **overrides):
    data = {
        "Incident_ID": incident_id,
        "Severity": "CRITICAL",
        "Title": "Fire spreading",
        "Description": "Evacuate now",
    }
    data.update(overrides)
    return data


class TestUpdateAlert(ServerTestCase):
    """Test UPDATE_ALERT over a real UDP server."""

    server_args = ["--ack-timeout", "0.2"]

    def publisher(self, name="CampusSecurity", tcp_port=7001):
        sock = self.new_client()
        self.assertEqual(
            self.register(sock, name, "PUBLISHER", tcp_port=tcp_port)["type"],
            "REGISTERED",
        )
        return sock

    def subscriber(self, name, location="HALL", category="FIRE"):
        sock = self.new_client()
        self.assertEqual(self.register(sock, name)["type"], "REGISTERED")
        self.assertEqual(
            self.subscribe(sock, name, location, category)["type"],
            "SUBSCRIBED",
        )
        return sock

    def publish(self, publisher, **overrides):
        reply = self.request(publisher, "PUBLISH_ALERT", 10, alert_data(**overrides))
        self.assertEqual(reply["type"], "ALERT_ACCEPTED")
        return reply["data"]["Incident_ID"]

    def update(self, publisher, incident_id, rq=20, **overrides):
        return self.request(publisher, "UPDATE_ALERT", rq, update_data(incident_id, **overrides))

    def assert_nothing_received(self, sock, timeout=0.5):
        sock.settimeout(timeout)
        with self.assertRaises(socket.timeout):
            sock.recvfrom(4096)

    def ack(self, sock, notification, name):
        self.send(
            sock,
            "ALERT_ACK",
            notification["rq"],
            {
                "Incident_ID": notification["data"]["Incident_ID"],
                "Version": notification["data"]["Version"],
                "Name": name,
            },
        )


    def test_owner_can_update(self):
        publisher = self.publisher()
        incident_id = self.publish(publisher)
        reply = self.update(publisher, incident_id)
        self.assertEqual(reply["type"], "ALERT_UPDATED")
        self.assertEqual(reply["rq"], 20)
        self.assertEqual(
            reply["data"],
            {"Incident_ID": incident_id, "Version": 2},
        )


    def test_matching_subscriber_gets_alert_update(self):
        publisher = self.publisher()
        alice = self.subscriber("Alice")
        incident_id = self.publish(publisher)
        self.receive(alice)  # initial ALERT
        self.update(publisher, incident_id)
        update = self.receive(alice) # updated ALERT
        self.assertEqual(update["type"], "ALERT_UPDATE")
        self.assertEqual(update["data"]["Incident_ID"], incident_id)
        self.assertEqual(update["data"]["Version"], 2)
        self.assertEqual(update["data"]["Severity"], "CRITICAL")
        self.assertEqual(update["data"]["Title"], "Fire spreading")
        self.assertEqual(update["data"]["Description"], "Evacuate now")


    def test_non_matching_subscriber_gets_nothing(self):
        publisher = self.publisher()
        alice = self.subscriber("Alice", "HALL", "FIRE")
        bob = self.subscriber("Bob", "EV", "POWER")
        incident_id = self.publish(publisher)
        self.receive(alice)  # Alice gets the first ALERT
        self.assert_nothing_received(bob) # Bob gets nothing

        self.update(publisher, incident_id)
        self.receive(alice)  # Alice also gets the update
        self.assert_nothing_received(bob) # Bob gets nothing


    def test_critical_update_ack_stops_retransmission(self):
        # Without name=subscriber_name on send_notification, this ACK is ignored.
        publisher = self.publisher()
        alice = self.subscriber("Alice")
        incident_id = self.publish(publisher)
        self.receive(alice)  # WARNING alert - no ACK needed

        self.update(publisher, incident_id)
        update = self.receive(alice)
        self.assertEqual(update["type"], "ALERT_UPDATE")
        self.assertEqual(update["data"]["Severity"], "CRITICAL")
        self.ack(alice, update, "Alice")
        self.assert_nothing_received(alice, timeout=1.0)


    def test_other_publisher_cannot_update(self):
        owner = self.publisher("CampusSecurity", tcp_port=7001)
        other = self.publisher("OtherSecurity", tcp_port=7002)
        incident_id = self.publish(owner)
        reply = self.update(other, incident_id)
        self.assertEqual(reply["type"], "ALERT_DENIED")
        self.assertEqual(reply["data"]["Reason"], "Not_Incident_Publisher")


    def test_subscriber_cannot_update(self):
        publisher = self.publisher()
        alice = self.subscriber("Alice")
        incident_id = self.publish(publisher)
        self.receive(alice)
        reply = self.update(alice, incident_id)
        self.assertEqual(reply["type"], "ALERT_DENIED")
        self.assertEqual(reply["data"]["Reason"], "Unauthorized_Role")


    def test_unknown_incident_denied(self):
        publisher = self.publisher()
        reply = self.update(publisher, "INC999")
        self.assertEqual(reply["type"], "ALERT_DENIED")
        self.assertEqual(reply["data"]["Reason"], "Unknown_Incident")


    def test_invalid_severity_denied(self):
        publisher = self.publisher()
        incident_id = self.publish(publisher)
        reply = self.update(publisher, incident_id, Severity="URGENT")
        self.assertEqual(reply["type"], "ALERT_DENIED")
        self.assertEqual(reply["data"]["Reason"], "Invalid_Severity")


    def test_closed_incident_denied(self):
        publisher = self.publisher()
        incident_id = self.publish(publisher)
        self.request(publisher, "CLOSE_ALERT", 15, {"Incident_ID": incident_id, "Reason": "Resolved"})
        reply = self.update(publisher, incident_id)
        self.assertEqual(reply["type"], "ALERT_DENIED")
        self.assertEqual(reply["data"]["Reason"], "Incident_Closed")


    def test_malformed_update_denied(self):
        publisher = self.publisher()
        incident_id = self.publish(publisher)
        reply = self.request(publisher, "UPDATE_ALERT", 20, {"Incident_ID": incident_id, "Severity": "INFO"}) # no Title or Description
        self.assertEqual(reply["type"], "ALERT_DENIED")
        self.assertEqual(reply["data"]["Reason"], "Malformed_Request")
