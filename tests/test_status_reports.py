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


def create_status_data(incident_id, name="Alice", status="SAFE", **overrides):
    data = {
        "Incident_ID": incident_id,
        "Name": name,
        "Status": status,
    }
    data.update(overrides)
    return data


class TestStatusReports(ServerTestCase):
    """Test STATUS_REPORT over a real UDP server."""

    def publisher(self, name="CampusSecurity", tcp_port=7001):
        sock = self.new_client()
        self.assertEqual(
            self.register(sock, name, "PUBLISHER", tcp_port=tcp_port)["type"],
            "REGISTERED",
        )
        return sock

    def subscriber(self, name="Alice"):
        sock = self.new_client()
        self.assertEqual(self.register(sock, name)["type"], "REGISTERED")
        return sock

    def publish(self, publisher):
        reply = self.request(publisher, "PUBLISH_ALERT", 10, alert_data())
        self.assertEqual(reply["type"], "ALERT_ACCEPTED")
        return reply["data"]["Incident_ID"]

    def report(self, sock, incident_id, rq=20, **overrides):
        return self.request(sock, "STATUS_REPORT", rq, create_status_data(incident_id, **overrides))

    def assert_rejected(self, reply, reason, rq=20):
        self.assertEqual(reply["type"], "STATUS_REJECTED")
        self.assertEqual(reply["rq"], rq)
        self.assertEqual(reply["data"]["Reason"], reason)


    def test_valid_status_report(self):
        publisher = self.publisher()
        alice = self.subscriber("Alice")
        incident_id = self.publish(publisher)
        reply = self.report(alice, incident_id, Name="Alice", Status="SAFE")
        self.assertEqual(reply["type"], "STATUS_RECORDED")
        self.assertEqual(reply["rq"], 20)
        saved = self.saved_full_state()
        self.assertEqual(saved["status_reports"][incident_id]["Alice"], "SAFE")


    def test_publisher_cannot_report(self):
        publisher = self.publisher()
        incident_id = self.publish(publisher)
        reply = self.report(publisher, incident_id, Name="CampusSecurity", Status="SAFE")
        self.assert_rejected(reply, "Unauthorized_Role")


    def test_unknown_incident_denied(self):
        alice = self.subscriber("Alice")
        reply = self.report(alice, "INC999", Name="Alice")
        self.assert_rejected(reply, "Unknown_Incident")


    def test_invalid_status_denied(self):
        publisher = self.publisher()
        alice = self.subscriber("Alice")
        incident_id = self.publish(publisher)
        reply = self.report(alice, incident_id, Name="Alice", Status="FINE")
        self.assert_rejected(reply, "Invalid_Status")


    def test_unregistered_client_denied(self):
        stranger = self.new_client()
        reply = self.report(stranger, "INC001", Name="Ghost")
        self.assert_rejected(reply, "Not_Registered")


    def test_wrong_name_denied(self):
        publisher = self.publisher()
        alice = self.subscriber("Alice")
        bob = self.subscriber("Bob")
        incident_id = self.publish(publisher)
        reply = self.report(alice, incident_id, Name="Bob") # Alice's socket, but Bob's name
        self.assert_rejected(reply, "Endpoint_Mismatch")


    def test_missing_field_denied(self):
        publisher = self.publisher()
        alice = self.subscriber("Alice")
        incident_id = self.publish(publisher)
        reply = self.request(alice, "STATUS_REPORT", 20, {"Incident_ID": incident_id, "Name": "Alice"}) # no Status
        self.assert_rejected(reply, "Malformed_Request")


    def test_closed_incident_denied(self):
        publisher = self.publisher()
        alice = self.subscriber("Alice")
        incident_id = self.publish(publisher)
        self.request(publisher, "CLOSE_ALERT", 15, {"Incident_ID": incident_id, "Reason": "Resolved"})
        reply = self.report(alice, incident_id, Name="Alice")
        self.assert_rejected(reply, "Incident_Closed")


    def test_both_role_can_report(self):
        publisher = self.publisher()
        incident_id = self.publish(publisher)
        facilities = self.new_client()
        self.register(facilities, "Facilities", "BOTH", tcp_port=7002)
        reply = self.report(facilities, incident_id, Name="Facilities", Status="LEFT_AREA")
        self.assertEqual(reply["type"], "STATUS_RECORDED")
