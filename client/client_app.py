import socket
import threading
import time
from shared.protocol import ProtocolMessage
from shared.constants import RQGenerator, Role

class CENRSClient:
    def __init__(self, server_host='127.0.0.1', server_port=5000):
        self.server_addr = (server_host, server_port)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # leave it at 0 to let the OS assign a free port
        self.sock.bind(('', 0)) 
        self.local_udp_port = self.sock.getsockname()[1]
        self.rq_gen = RQGenerator()
        print(f"Client initialized. Listening on UDP port {self.local_udp_port}")

    def listen_for_alerts(self):
        """Background thread to continuously listen for server responses and alerts."""
        while True:
            try:
                data, addr = self.sock.recvfrom(4096)
                msg = ProtocolMessage.decode(data)
                print(f"\n[INCOMING] {msg}")
            except Exception as e:
                print(f"Error receiving data: {e}")

    def send_message(self, msg_type: str, payload: dict):
        """Encodes and sends a datagram to the Emergency Server."""
        rq_num = self.rq_gen.get_next()
        data = ProtocolMessage.encode(msg_type, rq_num, payload)
        self.sock.sendto(data, self.server_addr)
        print(f"Sent {msg_type} (RQ: {rq_num}) to {self.server_addr}")

    def start(self):
        # Start the background listening thread
        threading.Thread(target=self.listen_for_alerts, daemon=True).start()

if __name__ == "__main__":
    client = CENRSClient()
    client.start()
    
    time.sleep(0.5)
    
    # message for epic 2
    client.send_message("REGISTER", {
        "Name": "Alice",
        "Role": Role.SUBSCRIBER.value,
        "IP": "127.0.0.1",
        "UDP_Port": client.local_udp_port,
        "TCP_Port": 0
    })
    
    while True:
        time.sleep(1)