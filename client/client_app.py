import socket
import threading
import time
import os, json, sys
import argparse
from shared.protocol import MalformedMessageError, ProtocolMessage
from shared.constants import RQGenerator, Role
from shared.logger import get_logger, log_recv, log_send
from client.commands import run_menu_commands

class CENRSClient:

    def __init__(self, server_host='127.0.0.1', server_port=5000, local_port=0, profile_path="client_profile.json"):
        self.server_addr = (server_host, server_port)
        self.profile_path = profile_path
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        try:
            self.sock.bind(('', local_port))
        except OSError:
            raise SystemExit(f"UDP port {local_port} is already in use. Choose another port.")

        self.local_udp_port = self.sock.getsockname()[1]
        self.log = get_logger(f"CLIENT:{self.local_udp_port}", f"logs/client_{self.local_udp_port}.log")
        self.rq_gen = RQGenerator()

        self.name = None
        self.role = None
        self.subscriptions = set()   # subscribed (location, category) pairs
        self.pending = {}                 # rq_num -> (msg_type, payload) of requests waiting for a server reply
        self.lock = threading.Lock()      # guards subscriptions and pending lists
        self.log.info(f"Client initialized. Listening on UDP port {self.local_udp_port}")


    def listen_for_alerts(self):
        """Background thread to continuously listen for server responses and alerts."""
        while True:
            try:
                data, addr = self.sock.recvfrom(4096)
            except OSError as e:
                self.log.error(f"Socket error while receiving data: {e}")
                continue

            try:
                msg = ProtocolMessage.decode(data)
            except MalformedMessageError as e:
                self.log.warning(f"[{addr[0]}:{addr[1]}] MALFORMED ({e}) raw={data[:200]!r}")
                continue

            log_recv(self.log, addr, msg['type'], msg['rq'], msg['data'])
            try:
                self.handle_incoming_message(msg)
            except Exception:
                self.log.exception(f"Handler for {msg['type']} (RQ: {msg['rq']}) crashed.")


    def handle_incoming_message(self, msg: dict):
        """Routes an incoming message to the right handler based on its type."""
        msg_type = msg["type"]
        if msg_type in ("REGISTERED", "REGISTER-DENIED", "DE-REGISTERED", "DEREGISTER-DENIED"):
            self.handle_registration_reply(msg)
        elif msg_type in ("SUBSCRIBED", "SUBSCRIPTION-DENIED", "UNSUBSCRIBED", "UNSUBSCRIPTION-DENIED"):
            self.handle_subscription_reply(msg)
        else:
            self.log.warning(f"Unknown message type: {msg_type!r} (RQ: {msg['rq']}), ignored.")

    def handle_registration_reply(self, msg: dict):
        """Handles registration-related replies from the server."""
        msg_type = msg["type"]
        rq_num = msg["rq"]

        with self.lock:
            pending_request = self.pending.get(rq_num)

            if pending_request is None:
                self.log.warning("No matching pending request.")
                return

            sent_type, payload = pending_request

            if sent_type == "REGISTER":
                valid_replies = ("REGISTERED", "REGISTER-DENIED")
            elif sent_type == "DE-REGISTER":
                valid_replies = ("DE-REGISTERED", "DEREGISTER-DENIED")
            else:
                valid_replies = ()

            if msg_type not in valid_replies:
                self.log.warning("Unexpected registration response.")
                return

            self.pending.pop(rq_num)

            if msg_type == "REGISTERED":
                self.name = payload["Name"]
                self.role = payload["Role"]
                self.subscriptions.clear()
                self.save_profile()
                print(f"Registered successfully as {self.name} ({self.role})")
                print("Locations:", msg["data"].get("Location_List", []))
                print("Categories:", msg["data"].get("Category_List", []))

            elif msg_type == "REGISTER-DENIED":
                print("Registration denied:", msg["data"].get("Reason"))

            elif msg_type == "DE-REGISTERED":
                print(f"De-registration successful: {self.name}")
                self.delete_profile()
                self.name = None
                self.role = None
                self.subscriptions.clear()

                self.pending = {
                    rq: request
                    for rq, request in self.pending.items()
                    if request[0] not in ("SUBSCRIBE", "UNSUBSCRIBE")
                }

            elif msg_type == "DEREGISTER-DENIED":
                print("De-registration denied:", msg["data"].get("Reason"))

    def handle_subscription_reply(self, msg: dict):
        """Updates the local subscription list once the server answers SUBSCRIBED/UNSUBSCRIBED."""
        msg_type = msg["type"]
        rq_num = msg["rq"]

        with self.lock:
            pending_request = self.pending.pop(rq_num, None)
            if pending_request is None:
                self.log.warning(f"Reply {msg_type} (RQ: {rq_num}) does not match any pending request, ignoring.")
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
                return

            self.save_profile()


    def send_message(self, msg_type: str, payload: dict, expect_reply: bool = True) -> int:
        """Encodes and sends a datagram to the server. If expect_reply, 
        stores the sent message so the reply can be matched by RQ#."""
        with self.lock:
            rq_num = self.rq_gen.get_next()
            data = ProtocolMessage.encode(msg_type, rq_num, payload)
            if expect_reply:
                self.pending[rq_num] = (msg_type, payload)
            try:
                self.sock.sendto(data, self.server_addr)
            except OSError as e:
                self.pending.pop(rq_num, None)
                self.log.error(f"SEND -> {self.server_addr[0]}:{self.server_addr[1]}  {msg_type} rq={rq_num} FAILED: {e}")
                raise
        log_send(self.log, self.server_addr, msg_type, rq_num, payload)
        return rq_num

    def register(self, name: str, role: str, tcp_port: int = 0):
        
        if self.name is not None:
            print("Already registered.")
            return

        self.send_message("REGISTER", {
            "Name": name.strip(),
            "Role": role.strip().upper(),
            "IP": "127.0.0.1",
            "UDP_Port": self.local_udp_port,
            "TCP_Port": tcp_port
        })

    def deregister(self):
        if self.name is None:
            print("You must register first.")
            return

        self.send_message("DE-REGISTER", {
            "Name": self.name
        })

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

    # Helper functions to save client profile locally
    def save_profile(self):
        folder = os.path.dirname(self.profile_path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        with open(self.profile_path, "w") as f:
            json.dump({
                "name": self.name,
                "role": self.role,
                "udp_port": self.local_udp_port,
                "subscriptions": list(self.subscriptions),
            }, f)

    # Helper function to delete the client profile locally
    def delete_profile(self):
        if os.path.exists(self.profile_path):
            os.remove(self.profile_path)

    def start(self):
        # Start the background listening thread
        threading.Thread(target=self.listen_for_alerts, daemon=True).start()


# Helper function to load a previously registered client profile from a file
def load_profile(path):
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CENRS Client")
    parser.add_argument("local_port", nargs="?", type=int, default=None, help="this client's UDP port (1024-65535, not 5000)")
    parser.add_argument("--server-port", type=int, default=5000, help="Emergency server UDP port (default: 5000)")
    args = parser.parse_args()

    if args.local_port is None:
        profile_path = "client_profile.json"
        profile = load_profile(profile_path)
        local_port = profile["udp_port"] if profile else 0
    else:
        local_port = args.local_port
        if not 1024 <= local_port <= 65535 or local_port == args.server_port:
            raise SystemExit(f"Use a port from 1024 to 65535, other than {args.server_port}.")
        profile_path = f"profiles/{local_port}.json"
        profile = load_profile(profile_path)

    client = CENRSClient(server_port=args.server_port, local_port=local_port, profile_path=profile_path)
    if profile is not None:
        client.name = profile["name"]
        client.role = profile["role"]
        client.subscriptions = {
            tuple(pair) for pair in profile.get("subscriptions", [])
        }
        print(f"Restored {client.name} on UDP port {client.local_udp_port}")
        
    client.start()
    
    time.sleep(0.5)
    
    """
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

    """

    run_menu_commands(client)
