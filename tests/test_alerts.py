import os, socket, tempfile, unittest

from server.alerts import matching_subscribers, distribute_alert
from server.server_state import ServerState
from tests.helpers import ServerTestCase


def alert_data(**overrides):
    data = {"Category": "FIRE", "Location": "HALL", "Severity": "CRITICAL",
            "Title": "Fire Alarm", "Description": "Evacuate the building now",
            "Attachment": "evacuation_map.pdf"}
    data.update(overrides)
    return data


class TestDistribution(unittest.TestCase):
    """Calls the distribution code directly with a fake send function."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        old_cwd = os.getcwd()
        os.chdir(tmp.name)
        self.addCleanup(os.chdir, old_cwd)
        self.state = ServerState("state.json")
        self.sent = []

        port = iter(range(6001, 6100))
        def add(name, role, *subs):
            self.state.users[name] = {"role": role, "ip": "127.0.0.1", "udp_port": next(port),
                                      "tcp_port": 0, "subscriptions": set(subs)}
        add("Exact", "SUBSCRIBER", ("HALL", "FIRE"))
        add("AnyPlace", "SUBSCRIBER", ("ALL", "FIRE"))
        add("AnyCategory", "BOTH", ("HALL", "ALL"))
        add("Everything", "SUBSCRIBER", ("ALL", "ALL"))
        add("OtherPlace", "SUBSCRIBER", ("EV", "FIRE"))
        add("OtherCategory", "SUBSCRIBER", ("HALL", "POWER"))
        add("NoSubs", "SUBSCRIBER")
        add("Publisher", "PUBLISHER", ("HALL", "FIRE"))  # can't really subscribe; must still be skipped

    def fake_send(self, addr, msg_type, payload, needs_ack=False):
        self.sent.append((addr, msg_type, payload, needs_ack))
        return len(self.sent)

    def new_incident(self, **overrides):
        fields = dict(publisher="Publisher", category="FIRE", location="HALL", severity="CRITICAL",
                      title="Fire Alarm", description="Evacuate", attachment="evacuation_map.pdf")
        fields.update(overrides)
        with self.state.lock:
            return self.state.create_incident(**fields)

    def test_wildcards_and_roles(self):
        with self.state.lock:
            names = {name for name, _ in matching_subscribers(self.state, "HALL", "FIRE")}
        self.assertEqual(names, {"Exact", "AnyPlace", "AnyCategory", "Everything"})

    def test_alert_sent_to_each_match_with_incident_fields(self):
        incident = self.new_incident()
        names = distribute_alert(self.state, incident, self.fake_send)

        self.assertEqual(set(names), {"Exact", "AnyPlace", "AnyCategory", "Everything"})
        self.assertEqual(len(self.sent), 4)
        for addr, msg_type, payload, needs_ack in self.sent:
            self.assertEqual(msg_type, "ALERT")
            self.assertEqual(payload, {"Incident_ID": "INC001", "Version": 1, "Category": "FIRE",
                                       "Location": "HALL", "Severity": "CRITICAL", "Title": "Fire Alarm",
                                       "Description": "Evacuate", "Attachment": "evacuation_map.pdf"})
            self.assertTrue(needs_ack)
        self.assertEqual(len({addr for addr, *_ in self.sent}), 4)  # one ALERT per subscriber

    def test_only_critical_needs_ack(self):
        for severity in ("INFO", "WARNING"):
            self.sent.clear()
            distribute_alert(self.state, self.new_incident(severity=severity), self.fake_send)
            with self.subTest(severity=severity):
                self.assertTrue(self.sent)
                self.assertFalse(any(needs_ack for *_, needs_ack in self.sent))

    def test_recipients_are_recorded_for_all_clear(self):
        incident = self.new_incident()
        distribute_alert(self.state, incident, self.fake_send)
        self.assertEqual(self.state.alert_recipients[incident.incident_id],
                         {"Exact", "AnyPlace", "AnyCategory", "Everything"})

    def test_no_match_sends_nothing(self):
        incident = self.new_incident(location="LOYOLA", category="WEATHER")
        self.assertEqual(distribute_alert(self.state, incident, self.fake_send), ["Everything"])
        self.state.users["Everything"]["subscriptions"] = {("SGW", "ALL")}
        self.sent.clear()
        self.assertEqual(distribute_alert(self.state, incident, self.fake_send), [])
        self.assertEqual(self.sent, [])


class TestAlertsOverUDP(ServerTestCase):
    """End-to-end: publish through a real server and check which subscribers receive the ALERT."""

    def subscriber(self, name, location, category):
        sock = self.new_client()
        self.register(sock, name)
        self.assertEqual(self.subscribe(sock, name, location, category)["type"], "SUBSCRIBED")
        return sock

    def assert_nothing_received(self, sock):
        sock.settimeout(0.5)
        with self.assertRaises(socket.timeout):
            sock.recvfrom(4096)

    def test_matching_subscribers_receive_alert(self):
        publisher = self.new_client()
        self.register(publisher, "CampusSecurity", "PUBLISHER", tcp_port=7001)
        alice = self.subscriber("Alice", "HALL", "FIRE")
        bob = self.subscriber("Bob", "ALL", "FIRE")
        carol = self.subscriber("Carol", "EV", "POWER")

        reply = self.request(publisher, "PUBLISH_ALERT", 45, alert_data())
        self.assertEqual(reply["type"], "ALERT_ACCEPTED")

        alerts = [self.receive(alice), self.receive(bob)]
        for alert in alerts:
            self.assertEqual(alert["type"], "ALERT")
            self.assertEqual(alert["data"]["Incident_ID"], reply["data"]["Incident_ID"])
            self.assertEqual(alert["data"]["Version"], 1)
            self.assertEqual(alert["data"]["Title"], "Fire Alarm")
            self.assertEqual(alert["data"]["Attachment"], "evacuation_map.pdf")
        self.assertNotEqual(alerts[0]["rq"], alerts[1]["rq"])  # each notification gets its own server RQ#
        self.assert_nothing_received(carol)
        self.assert_nothing_received(publisher)  # PUBLISHER role never receives alerts

    def test_denied_publish_sends_no_alert(self):
        alice = self.subscriber("Alice", "HALL", "FIRE")
        reply = self.request(alice, "PUBLISH_ALERT", 45, alert_data())  # a subscriber can't publish
        self.assertEqual(reply["data"], {"Reason": "Unauthorized_Role"})
        self.assert_nothing_received(alice)

    def test_both_role_receives_its_own_matching_alert(self):
        facilities = self.new_client()
        self.register(facilities, "Facilities", "BOTH", tcp_port=7002)
        self.subscribe(facilities, "Facilities", "HALL", "ALL")
        reply = self.request(facilities, "PUBLISH_ALERT", 45, alert_data(Severity="INFO"))
        self.assertEqual(reply["type"], "ALERT_ACCEPTED")
        alert = self.receive(facilities)
        self.assertEqual((alert["type"], alert["data"]["Severity"]), ("ALERT", "INFO"))


if __name__ == "__main__":
    unittest.main()
