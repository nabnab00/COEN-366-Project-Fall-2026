import unittest
from server.subscriptions import matches
from tests.helpers import ServerTestCase

# =============================== TEST SUBSCRIPTIONS ===============================
class TestSubscriptions(ServerTestCase):

    def test_subscribe_success(self):
        client = self.new_client()
        self.register(client, "Alice")
        reply = self.subscribe(client, "Alice", "HALL", "FIRE")
        self.assertEqual(reply["type"], "SUBSCRIBED")
        self.assertIn(["HALL", "FIRE"], self.saved_state()["Alice"]["subscriptions"]) 

    def test_multiple_subscriptions(self):
        client = self.new_client()
        self.register(client, "Alice")
        self.subscribe(client, "Alice", "HALL", "FIRE", rq=2)
        self.subscribe(client, "Alice", "ALL", "WEATHER", rq=3)
        self.assertEqual(len(self.saved_state()["Alice"]["subscriptions"]), 2)
        self.assertIn(["HALL", "FIRE"], self.saved_state()["Alice"]["subscriptions"])
        self.assertIn(["ALL", "WEATHER"], self.saved_state()["Alice"]["subscriptions"])

    def test_invalid_category_denied(self):
        client = self.new_client()
        self.register(client, "Alice")
        reply = self.subscribe(client, "Alice", "HALL", "APPLES-ON-FIRE")
        self.assertEqual(reply["type"], "SUBSCRIPTION-DENIED")
        self.assertEqual(reply["data"]["Reason"], "Invalid_Category")

    def test_unregisted_client_denied(self):
        reply = self.subscribe(self.new_client(), "Apple", "HALL", "FIRE")
        self.assertEqual(reply["type"], "SUBSCRIPTION-DENIED")
        self.assertEqual(reply["data"]["Reason"], "Not_Registered")

# =============================== TEST UNSUBSCRIPTIONS ===============================
class TestUnsubscriptions(ServerTestCase):

    def test_unsubscribe_success(self):
        client = self.new_client()
        self.register(client, "Alice")
        self.subscribe(client, "Alice", "HALL", "FIRE", rq=2)
        self.subscribe(client, "Alice", "ALL", "WEATHER", rq=3)
        reply = self.unsubscribe(client, "Alice", "HALL", "FIRE", rq=4)
        self.assertEqual(reply["type"], "UNSUBSCRIBED")
        self.assertNotIn(["HALL", "FIRE"], self.saved_state()["Alice"]["subscriptions"])
        self.assertIn(["ALL", "WEATHER"], self.saved_state()["Alice"]["subscriptions"])

# =============================== TEST MATCHING ===============================
class TestMatching(ServerTestCase):

    def test_alert_matching(self):
        self.assertTrue(matches({("HALL", "FIRE")}, "HALL", "FIRE"))
        self.assertTrue(matches({("ALL", "FIRE")}, "HALL", "FIRE"))
        self.assertTrue(matches({("HALL", "ALL")}, "HALL", "FIRE"))
        self.assertTrue(matches({("ALL", "ALL")}, "HALL", "FIRE"))
        self.assertFalse(matches({("EV", "FIRE")}, "HALL", "FIRE"))