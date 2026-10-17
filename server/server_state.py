import threading

class ServerState:
    def __init__(self):
        self.users = {}  # name -> {"role", "ip", "udp_port", "tcp_port", "subscriptions": set()}
        self.lock = threading.Lock()