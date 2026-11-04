import threading
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

