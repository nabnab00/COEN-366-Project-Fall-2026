import socket
from tests.helpers import ServerTestCase


# =============================== TEST REGISTRATION ===============================
class TestRegister(ServerTestCase):

    # test that a client can register successfully and if found in the saved state
    def test_register_success(self):
        client = self.new_client()
        reply = self.register(client, "Alice") 
        self.assertEqual(reply["type"], "REGISTERED")
        self.assertIn("Alice", self.saved_state())

    # test that a client with a duplicate name is denied
    def test_duplicate_name_denied(self):
        self.register(self.new_client(), "Alice")
        reply = self.register(self.new_client(), "Alice")
        self.assertEqual(reply["type"], "REGISTER-DENIED")
        self.assertEqual(reply["data"]["Reason"], "Name_Already_Exists")

    # test that a client with an invalid role is denied
    def test_invalid_role_denied(self):
        reply = self.register(self.new_client(), "Alice", role="ADMIN")
        self.assertEqual(reply["type"], "REGISTER-DENIED")
        self.assertEqual(reply["data"]["Reason"], "Invalid_Role")

    # test that a client with a malformed request is denied
    def test_malformed_request_denied(self):
        client = self.new_client()
        reply = self.request(client, "REGISTER", 1, {"Name": "Alice"}) # missing other fields
        self.assertEqual(reply["type"], "REGISTER-DENIED")
        self.assertEqual(reply["data"]["Reason"], "Malformed_Request")

# =============================== TEST DEREGISTRATION ===============================
class TestDeregister(ServerTestCase):

    # test that a client can deregister successfully and if not found in the saved state
    def test_deregister_success(self):
        client = self.new_client()
        self.register(client, "Alice")
        reply = self.request(client, "DE-REGISTER", 2, {"Name": "Alice"})
        self.assertEqual(reply["type"], "DE-REGISTERED")
        self.assertNotIn("Alice", self.saved_state())

    # test that a client with an unknown name is ignored
    def test_deregister_unknown_name_ignored(self):
        client = self.new_client()
        self.send(client, "DE-REGISTER", 1, {"Name": "Applesauce"})
        with self.assertRaises(socket.timeout):
            self.receive(client)