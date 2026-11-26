import json, os, subprocess, sys, tempfile, time, unittest
from tests.helpers import REPO, ServerTestCase


class TestUnknownMessageType(ServerTestCase):
    """an unknown message type is logged and the server keeps running."""

    def test_unknown_type_is_logged_and_server_keeps_running(self):
        client = self.new_client()
        self.send(client, "FOO", 1, {})
        self.assertEqual(self.register(client, "Alice")["type"], "REGISTERED")

        # each message is handled on its own thread, so wait (up to 2s) for the warning
        log_file = os.path.join(self.folder, "logs", "server.log")
        deadline = time.time() + 2
        while "Unknown message type" not in self.read(log_file):
            self.assertLess(time.time(), deadline, "no warning logged for the unknown message type")
            time.sleep(0.05)

    def read(self, path):
        with open(path) as f:
            return f.read()


class TestClientProfileReload(unittest.TestCase):
    """a restarted client finds the profile it saved in profiles/."""

    def test_client_restores_saved_profile(self):
        with tempfile.TemporaryDirectory() as folder:
            os.makedirs(os.path.join(folder, "profiles"))
            with open(os.path.join(folder, "profiles", "6123.json"), "w") as f:
                json.dump({"name": "Alice", "role": "SUBSCRIBER", "udp_port": 6123, "subscriptions": []}, f)

            result = subprocess.run(
                [sys.executable, "-m", "client.client_app", "6123", "--server-port", "5999"],
                cwd=folder, env={**os.environ, "PYTHONPATH": REPO},
                input="q\n", capture_output=True, text=True, timeout=5,
            )
            self.assertIn("Restored Alice on UDP port 6123", result.stdout)
