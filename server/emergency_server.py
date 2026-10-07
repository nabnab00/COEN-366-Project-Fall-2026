import socket
import threading
from shared.protocol import ProtocolMessage
from shared.constants import RQGenerator

class EmergencyServer:
    def __init__(self, host='127.0.0.1', port=5000):
        self.host = host
        self.port = port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((self.host, self.port))
        self.rq_gen = RQGenerator()
        print(f"Emergency Server started on {self.host}:{self.port}")

    def handle_client(self, data: bytes, addr):
        """Worker thread logic for processing incoming messages."""
        msg = ProtocolMessage.decode(data)
        
        if "error" in msg:
            print(f"[{addr}] Error: {msg['error']}")
            return
            
        print(f"[{addr}] Received {msg['type']} (RQ: {msg.get('rq')}) | Payload: {msg.get('data')}")
        
        # SOutline for Epic 2 & 3
        msg_type = msg.get("type")
        if msg_type == "REGISTER":
            # Epic 2
            pass
        elif msg_type == "SUBSCRIBE":
            # Epic 3
            pass

    def listen(self):
        """Main loop continuously listening for incoming UDP datagrams."""
        while True:
            data, addr = self.sock.recvfrom(4096)
            # Dispatch to a new thread for concurrent processing
            threading.Thread(target=self.handle_client, args=(data, addr), daemon=True).start()

if __name__ == "__main__":
    server = EmergencyServer()
    server.listen()