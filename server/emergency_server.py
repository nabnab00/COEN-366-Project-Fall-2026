import socket
import threading
from shared.protocol import ProtocolMessage, MalformedMessageError
from shared.constants import RQGenerator
from server.server_state import ServerState
from server import subscriptions

class EmergencyServer:
    def __init__(self, host='127.0.0.1', port=5000):
        self.host = host
        self.port = port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((self.host, self.port))
        self.rq_gen = RQGenerator()
        self.state = ServerState()
        print(f"Emergency Server started on {self.host}:{self.port}")

    def handle_client(self, data: bytes, addr):
        """Worker thread logic for processing incoming messages."""
        try:
            msg = ProtocolMessage.decode(data)
        except MalformedMessageError as e:
            print(f"[{addr}] Error: {e}")
            return

        print(f"[{addr}] Received {msg['type']} (RQ: {msg['rq']}) | Payload: {msg['data']}")

        # Outline for Epic 2 & 3
        msg_type = msg["type"]
        if msg_type == "REGISTER":
            # Epic 2
            pass
        elif msg_type == "SUBSCRIBE":
            subscriptions.handle_subscribe(self.state, msg, addr, self.send_response)
        elif msg_type == "UNSUBSCRIBE":
            subscriptions.handle_unsubscribe(self.state, msg, addr, self.send_response)

    def send_response(self, addr, msg_type: str, rq_num: int, payload: dict = None):
        """Sends a reply to a client. rq_num must be the RQ# of the request being answered."""
        data = ProtocolMessage.encode(msg_type, rq_num, payload)
        self.sock.sendto(data, addr)
        print(f"[{addr}] Sent {msg_type} (RQ: {rq_num}) | Payload: {payload or {}}")

    def listen(self):
        """Main loop continuously listening for incoming UDP datagrams."""
        while True:
            data, addr = self.sock.recvfrom(4096)
            # Dispatch to a new thread for concurrent processing
            threading.Thread(target=self.handle_client, args=(data, addr), daemon=True).start()

if __name__ == "__main__":
    server = EmergencyServer()
    server.listen()