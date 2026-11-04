import json, os, socket, subprocess, sys, tempfile, time, unittest
from shared.protocol import ProtocolMessage

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 5999 # test-only server port
SERVER = ("127.0.0.1", PORT)
STATE_FILE = "server_states/state.json" # ServerState puts the file inside server_states/


class ServerTestCase(unittest.TestCase):
    """Each test gets a fresh server with an empty state file in a temporary folder."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = tmp.name
        self.start_server()
        # cleanups run in reverse: the server stops first, then the folder is deleted
        self.addCleanup(self.stop_server)

    # =============================== SERVER CONTROL ===============================
    def start_server(self):
        self.server = subprocess.Popen(
            [sys.executable, "-m", "server.emergency_server", str(PORT), "state.json"],
            cwd=self.folder, # state file and logs/ go in the temp folder
            env={**os.environ, "PYTHONPATH": REPO}, # so "server" and "shared" can be imported
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        time.sleep(0.5) # give it time to bind the port

    def stop_server(self):
        if self.server.poll() is None:                 
            self.server.kill()
            self.server.wait()

    def new_client(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("127.0.0.1", 0)) # 127.0.0.1 so the server's Endpoint_Mismatch check passes
        sock.settimeout(1.0) # if no response within 1 second, the test fails
        self.addCleanup(sock.close) # make sure the socket is closed after the test
        return sock

    # =============================== MESSAGE SENDING ===============================
    # send a message to the server with no response expected
    def send(self, sock, msg_type, rq, data):
        sock.sendto(ProtocolMessage.encode(msg_type, rq, data), SERVER)

    # receive a message from the server
    def receive(self, sock):
        return ProtocolMessage.decode(sock.recvfrom(4096)[0])

    # send a message to the server with a response expected
    def request(self, sock, msg_type, rq, data):
        self.send(sock, msg_type, rq, data)
        return self.receive(sock)

    # =============================== REGISTRATION ===============================
    # generate the payload for a REGISTER message
    def register_data(self, sock, name, role="SUBSCRIBER", tcp_port=0):
        ip, port = sock.getsockname()
        return {"Name": name, "Role": role, "IP": ip, "UDP_Port": port, "TCP_Port": tcp_port}

    # register a client with the server
    def register(self, sock, name, role="SUBSCRIBER", tcp_port=0):
        return self.request(sock, "REGISTER", 1, self.register_data(sock, name, role, tcp_port))

    # subscribe a client to a location and category
    def subscribe(self, sock, name, location, category, rq=2):
        return self.request(sock, "SUBSCRIBE", rq, {"Name": name, "Location": location, "Category": category})

    # unsubscribe a client from a location and category
    def unsubscribe(self, sock, name, location, category, rq=3):
        return self.request(sock, "UNSUBSCRIBE", rq, {"Name": name, "Location": location, "Category": category})

    # =============================== HELPER FUNCTIONS ===============================
    # get the saved state from the server
    def saved_state(self):
        with open(os.path.join(self.folder, STATE_FILE)) as f:
            return json.load(f)
