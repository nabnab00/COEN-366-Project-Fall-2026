import threading
import time

from tests.helpers import ServerTestCase

class TestPersistence(ServerTestCase):

    def test_users_and_subscriptions_are_persisted_after_server_crash(self):
        client = self.new_client()
        self.register(client, "Alice")
        self.subscribe(client, "Alice", "HALL", "FIRE")

        # crash the server
        self.stop_server()
        # restart the server
        self.start_server()

        reply = self.register(self.new_client(), "Alice")
        self.assertEqual(reply["type"], "REGISTER-DENIED")
        self.assertEqual(reply["data"]["Reason"], "Name_Already_Exists")
        reply = self.unsubscribe(client, "Alice", "HALL", "FIRE")
        self.assertEqual(reply["type"], "UNSUBSCRIBED")

    def test_deregistration_persisted_after_server_crash(self):
        client = self.new_client()
        self.register(client, "Alice")
        self.request(client, "DE-REGISTER", 2, {"Name": "Alice"})

        # crash the server
        self.stop_server()
        # restart the server
        self.start_server()

        reply = self.register(self.new_client(), "Alice")
        self.assertEqual(reply["type"], "REGISTERED")
        
        
    def test_concurrent_registrations_all_saved(self):
        clients = [self.new_client() for _ in range(10)]

        replies = [None] * 10

        def register_one(i):
            replies[i] = self.register(clients[i], f"User{i}")

        threads = [threading.Thread(target=register_one, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertTrue(all(reply["type"] == "REGISTERED" for reply in replies))
        self.assertEqual(len(self.saved_state()), 10)


    def test_incidents_and_status_reports_survive_restart(self):
        publisher = self.new_client()
        self.register(publisher, "CampusSecurity", "PUBLISHER", tcp_port=7001)

        alice = self.new_client()
        self.register(alice, "Alice")
        self.subscribe(alice, "Alice", "HALL", "FIRE")

        # Publish an alert and record Alice's status
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
        self.receive(alice)  # discard the ALERT

        reply = self.request(
            alice,
            "STATUS_REPORT",
            20,
            {"Incident_ID": incident_id, "Name": "Alice", "Status": "SAFE"},
        )
        self.assertEqual(reply["type"], "STATUS_RECORDED")

        # Crash and restart
        self.stop_server()
        self.start_server()

        # Incident IDs should keep counting from where they left off
        reply = self.request(
            publisher,
            "PUBLISH_ALERT",
            30,
            {
                "Category": "FIRE",
                "Location": "HALL",
                "Severity": "INFO",
                "Title": "Update",
                "Description": "Still ongoing",
                "Attachment": "NONE",
            },
        )
        self.assertEqual(reply["type"], "ALERT_ACCEPTED")
        self.assertEqual(reply["data"]["Incident_ID"], "INC002")
        self.receive(alice)  # discard the new ALERT so it doesn't hide the next reply

        # The old incident and status report should still be there
        reply = self.request(
            alice,
            "STATUS_REPORT",
            40,
            {"Incident_ID": incident_id, "Name": "Alice", "Status": "NEED_HELP"},
        )
        self.assertEqual(reply["type"], "STATUS_RECORDED")

        saved = self.saved_full_state()
        self.assertEqual(saved["schema_version"], 2)
        self.assertIn(incident_id, saved["incidents"])
        self.assertEqual(saved["status_reports"][incident_id]["Alice"], "NEED_HELP")
        self.assertIn("Alice", saved["alert_recipients"][incident_id])

    def test_pending_delivery_becomes_unconfirmed_after_restart(self):
        publisher = self.new_client()
        self.register(publisher, "CampusSecurity", "PUBLISHER", tcp_port=7001)
        alice = self.new_client()
        self.register(alice, "Alice")
        self.subscribe(alice, "Alice", "HALL", "FIRE")

        reply = self.request(publisher, "PUBLISH_ALERT", 10, {
            "Category": "FIRE", "Location": "HALL", "Severity": "CRITICAL",
            "Title": "Fire alarm", "Description": "Evacuate now", "Attachment": "NONE"})
        incident_id = reply["data"]["Incident_ID"]
        self.receive(alice) # the ALERT, deliberately not ACKed

        # Crash while the server is still waiting for Alice's ACK
        self.stop_server()
        self.assertEqual(self.saved_full_state()["delivery_status"][incident_id]["Alice"]["status"], "PENDING")
        self.start_server()

        # Register someone so the restarted server writes its loaded state back to the file
        self.register(self.new_client(), "Bob")
        self.assertEqual(self.saved_full_state()["delivery_status"][incident_id]["Alice"],
                         {"version": 1, "status": "UNCONFIRMED"})


class TestDeliveryStatusPersistence(ServerTestCase):
    """Test that CRITICAL alerts write delivery_status and it survives a restart."""

    server_args = ["--ack-timeout", "0.2"]

    def test_delivery_status_survives_restart(self):
        publisher = self.new_client()
        self.register(publisher, "CampusSecurity", "PUBLISHER", tcp_port=7001)

        alice = self.new_client()
        self.register(alice, "Alice")
        self.subscribe(alice, "Alice", "HALL", "FIRE")

        reply = self.request(
            publisher,
            "PUBLISH_ALERT",
            10,
            {
                "Category": "FIRE",
                "Location": "HALL",
                "Severity": "CRITICAL",
                "Title": "Fire alarm",
                "Description": "Evacuate now",
                "Attachment": "NONE",
            },
        )
        self.assertEqual(reply["type"], "ALERT_ACCEPTED")
        incident_id = reply["data"]["Incident_ID"]

        # Alice ACKs the alert so delivery is CONFIRMED.
        alert = self.receive(alice)
        self.send(
            alice,
            "ALERT_ACK",
            alert["rq"],
            {
                "Incident_ID": alert["data"]["Incident_ID"],
                "Version": alert["data"]["Version"],
                "Name": "Alice",
            },
        )

        # Give the server some time to save the ACK
        time.sleep(0.3)

        saved = self.saved_full_state()
        self.assertEqual(
            saved["delivery_status"][incident_id]["Alice"],
            {"version": 1, "status": "CONFIRMED"},
        )

        # Crash and restart (CONFIRMED should still be on disk after restart)
        self.stop_server()
        self.start_server()

        saved = self.saved_full_state()
        self.assertEqual(
            saved["delivery_status"][incident_id]["Alice"],
            {"version": 1, "status": "CONFIRMED"},
        )
