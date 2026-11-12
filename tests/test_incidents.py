import os, tempfile, threading, unittest

from server.incidents import Incident, IncidentIDGenerator, parse_incident_number
from server.server_state import ServerState


class TestIncidentIDGenerator(unittest.TestCase):

    def test_ids_are_sequential_and_formatted(self):
        gen = IncidentIDGenerator()
        self.assertEqual([gen.get_next() for _ in range(3)], ["INC001", "INC002", "INC003"])

    def test_numbers_past_999_keep_growing(self):
        gen = IncidentIDGenerator()
        gen.seed(["INC999"])
        self.assertEqual(gen.get_next(), "INC1000")

    def test_seed_continues_after_highest_restored_id(self):
        # after a server restart, IDs must not repeat ones already handed out
        gen = IncidentIDGenerator()
        gen.seed(["INC004", "INC102", "INC017", "BAD_ID", None])
        self.assertEqual(gen.get_next(), "INC103")

    def test_concurrent_ids_are_unique(self):
        gen = IncidentIDGenerator()
        ids = []
        ids_lock = threading.Lock()

        def worker():
            for _ in range(200):
                new_id = gen.get_next()
                with ids_lock:
                    ids.append(new_id)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(ids), 1600)
        self.assertEqual(len(set(ids)), 1600)

    def test_parse_incident_number(self):
        self.assertEqual(parse_incident_number("INC102"), 102)
        self.assertIsNone(parse_incident_number("INC"))
        self.assertIsNone(parse_incident_number("INCabc"))
        self.assertIsNone(parse_incident_number("XYZ102"))
        self.assertIsNone(parse_incident_number(102))


class TestIncident(unittest.TestCase):

    def make_incident(self, **overrides):
        fields = dict(incident_id="INC102", publisher="CampusSecurity", category="FIRE", location="HALL",
                      severity="CRITICAL", title="Fire Alarm", description="Evacuate the building",
                      attachment="evacuation_map.pdf")
        fields.update(overrides)
        return Incident(**fields)

    def test_new_incident_is_active_at_version_1(self):
        incident = self.make_incident()
        self.assertEqual(incident.version, 1)
        self.assertEqual(incident.status, "ACTIVE")
        self.assertTrue(incident.is_active)
        self.assertTrue(incident.has_attachment)

    def test_update_changes_fields_and_increments_version(self):
        incident = self.make_incident()
        new_version = incident.apply_update("WARNING", "Fire Controlled", "Remain outside the building")
        self.assertEqual(new_version, 2)
        self.assertEqual(incident.severity, "WARNING")
        self.assertEqual(incident.title, "Fire Controlled")
        self.assertTrue(incident.is_active)

    def test_close_marks_closed_and_increments_version(self):
        incident = self.make_incident()
        incident.apply_update("WARNING", "Fire Controlled", "Remain outside the building")
        self.assertEqual(incident.close(), 3)  # matches the spec example: ALL_CLEAR ... INC102 3
        self.assertEqual(incident.status, "CLOSED")
        self.assertFalse(incident.is_active)

    def test_alert_fields_match_alert_message(self):
        fields = self.make_incident().alert_fields()
        self.assertEqual(list(fields), ["Incident_ID", "Version", "Category", "Location",
                                        "Severity", "Title", "Description", "Attachment"])
        self.assertEqual(fields["Incident_ID"], "INC102")
        self.assertEqual(fields["Version"], 1)

    def test_dict_round_trip(self):
        incident = self.make_incident()
        incident.close()
        restored = Incident.from_dict(incident.to_dict())
        self.assertEqual(restored, incident)

    def test_no_attachment(self):
        self.assertFalse(self.make_incident(attachment="NONE").has_attachment)


class TestServerStateIncidents(unittest.TestCase):

    def setUp(self):
        # run in an empty temp folder so no real server_states/ file is read
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        old_cwd = os.getcwd()
        os.chdir(tmp.name)
        self.addCleanup(os.chdir, old_cwd)
        self.state = ServerState("state.json")

    def test_create_incident_stores_and_returns_it(self):
        with self.state.lock:
            incident = self.state.create_incident("CampusSecurity", "FIRE", "HALL", "CRITICAL",
                                                  "Fire Alarm", "Evacuate the building", "evacuation_map.pdf")
            self.assertIs(self.state.get_incident(incident.incident_id), incident)
        self.assertEqual(incident.incident_id, "INC001")
        self.assertEqual(incident.publisher, "CampusSecurity")
        self.assertEqual(incident.version, 1)
        self.assertTrue(incident.is_active)

    def test_each_incident_gets_a_new_id(self):
        with self.state.lock:
            first = self.state.create_incident("A", "FIRE", "HALL", "INFO", "t", "d")
            second = self.state.create_incident("A", "POWER", "EV", "WARNING", "t", "d")
        self.assertNotEqual(first.incident_id, second.incident_id)
        self.assertEqual(len(self.state.incidents), 2)

    def test_missing_attachment_becomes_none(self):
        with self.state.lock:
            incident = self.state.create_incident("A", "FIRE", "HALL", "INFO", "t", "d", attachment=None)
        self.assertEqual(incident.attachment, "NONE")

    def test_unknown_incident_returns_none(self):
        with self.state.lock:
            self.assertIsNone(self.state.get_incident("INC999"))


if __name__ == "__main__":
    unittest.main()
