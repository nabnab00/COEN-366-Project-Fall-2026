from tests.helpers import ServerTestCase


class TestStatusReports(ServerTestCase):
    def test_valid_status_report(self):
        # Register a publisher.
        publisher = self.new_client()
        self.assertEqual(
            self.register(
                publisher, "CampusSecurity", "PUBLISHER", tcp_port=7001
            )["type"],
            "REGISTERED",
        )

        # Register a subscriber.
        subscriber = self.new_client()
        self.assertEqual(
            self.register(subscriber, "Alice")["type"],
            "REGISTERED",
        )

        # Create an active incident.
        reply = self.request(
            publisher,
            "PUBLISH_ALERT",
            10,
            {
                "Category": "FIRE",
                "Location": "HALL",
                "Severity": "WARNING",
                "Title": "Fire alarm",
                "Description": "Leave the building",
                "Attachment": "NONE",
            },
        )
        self.assertEqual(reply["type"], "ALERT_ACCEPTED")
        incident_id = reply["data"]["Incident_ID"]

        # Alice reports that she is safe.
        reply = self.request(
            subscriber,
            "STATUS_REPORT",
            20,
            {
                "Incident_ID": incident_id,
                "Name": "Alice",
                "Status": "SAFE",
            },
        )

        # Check the reply and the saved report.
        self.assertEqual(reply["type"], "STATUS_RECORDED")
        self.assertEqual(reply["rq"], 20)

        saved = self.saved_full_state()
        self.assertEqual(
            saved["status_reports"][incident_id]["Alice"],
            "SAFE",
        )