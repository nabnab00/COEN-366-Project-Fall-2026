import os, tempfile, threading, unittest

from server.publish import handle_publish_alert
from server.server_state import ServerState
from tests.helpers import ServerTestCase

PUBLISHER_ADDR = ("127.0.0.1", 6001)
SUBSCRIBER_ADDR = ("127.0.0.1", 6002)
BOTH_ADDR = ("127.0.0.1", 6003)
UNKNOWN_ADDR = ("127.0.0.1", 6999)


def alert_data(**overrides):
    data = {"Category": "FIRE", "Location": "HALL", "Severity": "CRITICAL",
            "Title": "Fire Alarm", "Description": "Evacuate the building now",
            "Attachment": "evacuation_map.pdf"}
    data.update(overrides)
    return data


class TestPublishHandler(unittest.TestCase):
    """Calls handle_publish_alert directly with a fake send function, so the stored incident can be inspected."""

    def setUp(self):
        # run in an empty temp folder so no real server_states/ file is read or written
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        old_cwd = os.getcwd()
        os.chdir(tmp.name)
        self.addCleanup(os.chdir, old_cwd)

        self.state = ServerState("state.json")
        self.add_user("CampusSecurity", "PUBLISHER", PUBLISHER_ADDR)
        self.add_user("Alice", "SUBSCRIBER", SUBSCRIBER_ADDR)
        self.add_user("Facilities", "BOTH", BOTH_ADDR)
        self.replies = []

    def add_user(self, name, role, addr):
        self.state.users[name] = {"role": role, "ip": addr[0], "udp_port": addr[1],
                                  "tcp_port": 7000 if role != "SUBSCRIBER" else 0, "subscriptions": set()}

    def send(self, addr, msg_type, rq, payload=None):
        self.replies.append((addr, msg_type, rq, payload or {}))

    def publish(self, data, addr=PUBLISHER_ADDR, rq=45):
        incident = handle_publish_alert(self.state, {"type": "PUBLISH_ALERT", "rq": rq, "data": data},
                                        addr, self.send)
        return incident, self.replies[-1]

    def assert_denied(self, data, reason, addr=PUBLISHER_ADDR):
        incident, (_, msg_type, rq, payload) = self.publish(data, addr)
        self.assertIsNone(incident)
        self.assertEqual((msg_type, rq, payload), ("ALERT_DENIED", 45, {"Reason": reason}))
        self.assertEqual(self.state.incidents, {})

    # ---------- accepted ----------
    def test_publisher_creates_incident(self):
        incident, reply = self.publish(alert_data())
        self.assertEqual(reply, (PUBLISHER_ADDR, "ALERT_ACCEPTED", 45, {"Incident_ID": "INC001"}))
        self.assertIs(self.state.incidents["INC001"], incident)
        self.assertEqual(incident.publisher, "CampusSecurity")
        self.assertEqual((incident.version, incident.status), (1, "ACTIVE"))
        self.assertEqual(incident.title, "Fire Alarm")
        self.assertEqual(incident.attachment, "evacuation_map.pdf")

    def test_both_role_can_publish(self):
        incident, reply = self.publish(alert_data(), addr=BOTH_ADDR)
        self.assertEqual(reply[1], "ALERT_ACCEPTED")
        self.assertEqual(incident.publisher, "Facilities")

    def test_each_publish_gets_a_new_incident_id(self):
        ids = [self.publish(alert_data(), rq=rq)[1][3]["Incident_ID"] for rq in (1, 2, 3)]
        self.assertEqual(ids, ["INC001", "INC002", "INC003"])

    def test_missing_attachment_means_none(self):
        data = alert_data()
        del data["Attachment"]
        incident, _ = self.publish(data)
        self.assertEqual(incident.attachment, "NONE")

    def test_matching_name_is_accepted(self):
        incident, reply = self.publish(alert_data(Name="CampusSecurity"))
        self.assertEqual(reply[1], "ALERT_ACCEPTED")

    # ---------- who may publish ----------
    def test_subscriber_is_unauthorized(self):
        self.assert_denied(alert_data(), "Unauthorized_Role", addr=SUBSCRIBER_ADDR)

    def test_unregistered_endpoint_denied(self):
        self.assert_denied(alert_data(), "Not_Registered", addr=UNKNOWN_ADDR)

    def test_name_of_another_user_denied(self):
        # a client can't publish in another publisher's name
        self.assert_denied(alert_data(Name="Facilities"), "Endpoint_Mismatch")

    # ---------- payload checks ----------
    def test_missing_field_is_malformed(self):
        for field in ("Category", "Location", "Severity", "Title", "Description"):
            data = alert_data()
            del data[field]
            with self.subTest(field=field):
                self.assert_denied(data, "Malformed_Request")

    def test_bad_title_or_description_is_malformed(self):
        for data in (alert_data(Title=""), alert_data(Title="   "), alert_data(Title=5),
                     alert_data(Description=""), alert_data(Title="x" * 101),
                     alert_data(Description="x" * 1001), alert_data(Severity=None)):
            with self.subTest(data=data):
                self.assert_denied(data, "Malformed_Request")

    def test_invalid_values(self):
        self.assert_denied(alert_data(Category="FLOOD"), "Invalid_Category")
        self.assert_denied(alert_data(Location="MOON"), "Invalid_Location")
        self.assert_denied(alert_data(Severity="URGENT"), "Invalid_Severity")

    def test_all_wildcard_is_not_an_incident_value(self):
        self.assert_denied(alert_data(Location="ALL"), "Invalid_Location")
        self.assert_denied(alert_data(Category="ALL"), "Invalid_Category")

    def test_attachment_paths_refused(self):
        for attachment in ("../secret.txt", "C:\\Users\\a.pdf", "maps/hall.pdf", "", " map.pdf", 7):
            with self.subTest(attachment=attachment):
                self.assert_denied(alert_data(Attachment=attachment), "Invalid_Attachment")

    # ---------- concurrency ----------
    def test_concurrent_publishes_get_unique_ids(self):
        threads = [threading.Thread(target=self.publish, args=(alert_data(),), kwargs={"rq": i}) for i in range(40)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        accepted = [r[3]["Incident_ID"] for r in self.replies if r[1] == "ALERT_ACCEPTED"]
        self.assertEqual(len(accepted), 40)
        self.assertEqual(len(set(accepted)), 40)
        self.assertEqual(len(self.state.incidents), 40)


class TestPublishOverUDP(ServerTestCase):
    """End-to-end: real server process and UDP sockets, to check PUBLISH_ALERT is wired into the server."""

    def test_publisher_gets_alert_accepted(self):
        publisher = self.new_client()
        self.assertEqual(self.register(publisher, "CampusSecurity", "PUBLISHER", tcp_port=7001)["type"], "REGISTERED")
        reply = self.request(publisher, "PUBLISH_ALERT", 45, alert_data())
        self.assertEqual(reply, {"type": "ALERT_ACCEPTED", "rq": 45, "data": {"Incident_ID": "INC001"}})

    def test_subscriber_gets_alert_denied(self):
        subscriber = self.new_client()
        self.register(subscriber, "Alice")
        reply = self.request(subscriber, "PUBLISH_ALERT", 45, alert_data())
        self.assertEqual(reply, {"type": "ALERT_DENIED", "rq": 45, "data": {"Reason": "Unauthorized_Role"}})

    def test_unregistered_client_gets_alert_denied(self):
        reply = self.request(self.new_client(), "PUBLISH_ALERT", 45, alert_data())
        self.assertEqual(reply["data"], {"Reason": "Not_Registered"})


if __name__ == "__main__":
    unittest.main()
