import socket
import threading
import time
from shared.protocol import ProtocolMessage
from shared.constants import RQGenerator, Role
from client.commands import run_menu_commands

class CENRSClient:

    def __init__(self, server_host='127.0.0.1', server_port=5000):
        self.server_addr = (server_host, server_port)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # leave it at 0 to let the OS assign a free port
        self.sock.bind(('', 0)) 
        self.local_udp_port = self.sock.getsockname()[1]
        self.rq_gen = RQGenerator()

        self.name = None
        self.subscriptions = set()   # subscribed (location, category) pairs
        self.pending = {}                 # rq_num -> (msg_type, payload) of requests waiting for a server reply
        self.lock = threading.Lock()      # guards subscriptions and pending lists
        print(f"Client initialized. Listening on UDP port {self.local_udp_port}")


    def listen_for_alerts(self):
        """Background thread to continuously listen for server responses and alerts."""
        while True:
            try:
                data, addr = self.sock.recvfrom(4096)
                msg = ProtocolMessage.decode(data)
                print(f"\n[INCOMING] {msg}")
                self.handle_incoming_message(msg)
            except Exception as e:
                print(f"Error receiving data: {e}")


    def handle_incoming_message(self, msg: dict):
        """Routes an incoming message to the right handler based on its type."""
        msg_type = msg["type"]
        if msg_type in ("REGISTERED", "REGISTER-DENIED", "DE-REGISTERED", "DEREGISTER-DENIED"):
            # TODO: Patricia: Add routing in this function for Register/Deregister message
            pass
        elif msg_type in ("SUBSCRIBED", "SUBSCRIPTION-DENIED", "UNSUBSCRIBED", "UNSUBSCRIPTION-DENIED"):
            self.handle_subscription_reply(msg)


    def handle_subscription_reply(self, msg: dict):
        """Updates the local subscription list once the server answers SUBSCRIBED/UNSUBSCRIBED."""
        msg_type = msg["type"]
        rq_num = msg["rq"]

        with self.lock:
            pending_request = self.pending.pop(rq_num, None)
            if pending_request is None:
                print(f"Reply {msg_type} (RQ: {rq_num}) does not match any pending request, ignoring.")
                return

            sent_msg_type, payload = pending_request
            subscription = (payload["Location"], payload["Category"])
            error_reason = msg["data"].get("Reason")

            location, category = subscription

            if msg_type == "SUBSCRIBED":
                self.subscriptions.add(subscription)
                print(f"Subscribed to {location}/{category}.")
            elif msg_type == "UNSUBSCRIBED":
                self.subscriptions.discard(subscription)
                print(f"Unsubscribed from {location}/{category}.")
            elif error_reason == "Already_Subscribed":
                # Adding a duplicate item to a set still maintains one instance of it
                self.subscriptions.add(subscription)
                print(f"Already subscribed to {location}/{category}.")
            elif error_reason == "Not_Subscribed":
                self.subscriptions.discard(subscription)
                print(f"Not subscribed to {location}/{category}.")
            else:
                print(f"{sent_msg_type} {location}/{category} denied: {error_reason}")


    def send_message(self, msg_type: str, payload: dict, expect_reply: bool = True) -> int:
        """Encodes and sends a datagram to the server. If expect_reply, 
        stores the sent message so the reply can be matched by RQ#."""
        with self.lock:
            rq_num = self.rq_gen.get_next()
            data = ProtocolMessage.encode(msg_type, rq_num, payload)
            self.sock.sendto(data, self.server_addr)
            if expect_reply:
                self.pending[rq_num] = (msg_type, payload)
        print(f"Sent {msg_type} (RQ: {rq_num}) to {self.server_addr}")
        return rq_num


    def subscribe(self, location: str, category: str):
        if self.name is None:
            print("You must register before subscribing.")
            return
        self.send_message("SUBSCRIBE", {
            "Name": self.name,
            "Location": location.strip().upper(),
            "Category": category.strip().upper(),
        })


    def unsubscribe(self, location: str, category: str):
        if self.name is None:
            print("You must register first.")
            return
        self.send_message("UNSUBSCRIBE", {
            "Name": self.name,
            "Location": location.strip().upper(),
            "Category": category.strip().upper(),
        })


    def list_subscriptions(self):
        with self.lock:
            subscriptions = sorted(self.subscriptions)
        if not subscriptions:
            print("You have no subscriptions.")
            return
        print("Your subscriptions:")
        for location, category in subscriptions:
            print(f" - {location} / {category}")


    def start(self):
        # Start the background listening thread
        threading.Thread(target=self.listen_for_alerts, daemon=True).start()


if __name__ == "__main__":
    client = CENRSClient()
    client.start()
    
    time.sleep(0.5)
    
    # For testing purposes
    client.name = "Alice"

    # Test Registration - This should be done by the user through the menu
    client.send_message("REGISTER", {
        "Name": client.name,
        "Role": Role.SUBSCRIBER.value,
        "IP": "127.0.0.1",
        "UDP_Port": client.local_udp_port,
        "TCP_Port": 0
    })
    
    run_menu_commands(client)
