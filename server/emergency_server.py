import socket
import threading
import json
import argparse
import random
import os
from shared.protocol import ProtocolMessage, MalformedMessageError
from shared.constants import RQGenerator, DeliveryStatus
from shared.logger import get_logger, log_recv, log_send
from shared.tcp import TCPConnection, ConnectionClosedError
from server.server_state import ServerState
from server import subscriptions, registration, publish, alerts, acks, close_alert, status_reports
from server.retransmission import RetransmissionManager

# the denial each request gets if its handler crashes
DENIAL_TYPES = {
    "REGISTER": "REGISTER-DENIED",
    "DE-REGISTER": "DEREGISTER-DENIED",
    "SUBSCRIBE": "SUBSCRIPTION-DENIED",
    "UNSUBSCRIBE": "UNSUBSCRIPTION-DENIED",
    "PUBLISH_ALERT": "ALERT_DENIED",
    "UPDATE_ALERT": "ALERT_DENIED",
    "CLOSE_ALERT": "ALERT_DENIED",
    "STATUS_REPORT": "STATUS_REJECTED",
}

class EmergencyServer:
    
    def __init__(self, host='127.0.0.1', port=5000, state_file="server_state.json", ack_timeout=2.0, drop_rate=0.0, tcp_port=None):
        self.host = host
        self.port = port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((self.host, self.port))
        self.tcp_port = port if tcp_port is None else tcp_port
        self.tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if os.name != "nt":
            self.tcp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.tcp_sock.bind((self.host, self.tcp_port))
        self.tcp_sock.listen()
        self.rq_gen = RQGenerator()
        self.state = ServerState(state_file)
        self.log = get_logger("server", "logs/server.log")
        self.log.info(f"STATE Restored users from {self.state.filename}:\n{json.dumps(self.state.users, indent=2, default=list)}")
        self.log.info(f"Emergency Server started on {self.host}:{self.port}")
        self.log.info(f"TCP listening on {self.host}:{self.tcp_port}")
        self.retransmitter = RetransmissionManager(
            resend=self.send_response,
            base_timeout=ack_timeout,
            on_unconfirmed=self.mark_unconfirmed
        )
        self.drop_rate = drop_rate # set drop rate for simulated packet loss

    def handle_client(self, data: bytes, addr):
        """Worker thread logic for processing incoming messages."""
        try:
            msg = ProtocolMessage.decode(data)
        except MalformedMessageError as e:
            self.log.warning(f"[{addr}] Error: {e}")
            return

        # simulated packet loss, the ACK is treated as if it never arrived
        if msg["type"] == "ALERT_ACK" and random.random() < self.drop_rate:
            self.log.warning(f"[{addr}] DROPPED ALERT_ACK rq={msg['rq']} {msg['data']} (simulated packet loss)")
            return

        log_recv(self.log, addr, msg['type'], msg['rq'], msg['data'])        

        try:
            self.dispatch(msg, addr)
        except Exception:
            self.log.exception(f"Handler for {msg['type']} (RQ: {msg['rq']}) from {addr} crashed.")
            # tell the client instead of leaving it to time out (ALERT_ACK never gets a reply)
            denial = DENIAL_TYPES.get(msg["type"])
            if denial:
                self.send_response(addr, denial, msg["rq"], {"Reason": "Server_Error"})

    def dispatch(self, msg, addr):
        """Routes a decoded message to the right handler."""
        msg_type = msg["type"]

        if msg_type == "REGISTER":
            registration.handle_register(
                self.state,
                msg,
                addr,
                self.send_response,
                persist=self.state.save_to_file
            )

        elif msg_type == "DE-REGISTER":
            registration.handle_deregister(
                self.state,
                msg,
                addr,
                self.send_response,
                persist=self.state.save_to_file
            )
            
        elif msg_type == "SUBSCRIBE":
            subscriptions.handle_subscribe(
                self.state,
                msg,
                addr,
                self.send_response,
                persist=self.state.save_to_file
            )

        elif msg_type == "UNSUBSCRIBE":
            subscriptions.handle_unsubscribe(
                self.state,
                msg,
                addr,
                self.send_response,
                persist=self.state.save_to_file
            )

        elif msg_type == "PUBLISH_ALERT":
            incident = publish.handle_publish_alert(
                self.state,
                msg,
                addr,
                self.send_response,
                persist=self.state.save_to_file
            )

            if incident is not None:
                alerts.distribute_alert(self.state, incident, self.send_notification)
                self.state.save_to_file()

        elif msg_type == "ALERT_ACK":
            acks.handle_alert_ack(self.state, self.retransmitter, msg, addr)
        elif msg_type == "CLOSE_ALERT":
            close_alert.handle_close_alert(self.state, msg, addr, self.send_response, self.send_notification, persist=self.state.save_to_file)

        elif msg_type == "UPDATE_ALERT":
            alerts.handle_update_alert(
                self.state,
                msg,
                addr,
                self.send_response,
                self.send_notification,
                persist=self.state.save_to_file,
            )

        elif msg_type == "STATUS_REPORT":
            status_reports.handle_status_report(
                self.state,
                msg,
                addr,
                self.send_response,
                persist=self.state.save_to_file
            )

        else:
            self.log.warning(f"Unknown message type from {addr}: {msg_type} (rq={msg['rq']})")


    def mark_unconfirmed(self, notification):
        """Called by the RetransmissionManager after the last attempt times out for the alert."""
        incident_id = notification.payload["Incident_ID"]
        version = notification.payload["Version"]
        with self.state.lock:
            # A late ALERT_ACK can be processed between the give-up and this callback
            # So we need to check if the ALERT_ACK is already confirmed, if so, ignore it.
            current = self.state.delivery_status.get(incident_id, {}).get(notification.name)
            if current == {"version": version, "status": DeliveryStatus.CONFIRMED.value}:
                return
            # record the delivery status as unconfirmed
            self.state.record_delivery(incident_id, version, notification.name, DeliveryStatus.UNCONFIRMED.value)
        self.state.save_to_file()


    def send_response(self, addr, msg_type: str, rq_num: int, payload: dict = None):
        """Sends a reply to a client. rq_num must be the RQ# of the request being answered."""
        data = ProtocolMessage.encode(msg_type, rq_num, payload)
        self.sock.sendto(data, addr)
        log_send(self.log, addr, msg_type, rq_num, payload)

    def send_notification(self, addr, msg_type: str, payload: dict, needs_ack: bool = False, name: str = None) -> int:
        """2.4. Server-initiated message (ALERT, ALERT_UPDATE, ALL_CLEAR) with a new RQ#. Returns the RQ#."""
        rq_num = self.rq_gen.get_next()
        if needs_ack:
            with self.state.lock:
                self.state.record_delivery(payload["Incident_ID"], payload["Version"], name, DeliveryStatus.PENDING.value)
            self.state.save_to_file()
            self.retransmitter.track(rq_num, addr, msg_type, payload, name)
        self.send_response(addr, msg_type, rq_num, payload)
        return rq_num
    
    def listen_tcp(self):
        """Accepts TCP connections and handles each one on its own thread, so a slow client never blocks the others."""
        while True:
            try:
                conn, addr = self.tcp_sock.accept()
            except OSError as e:
                if self.tcp_sock.fileno() == -1:
                    break  # listening socket was closed
                self.log.error(f"TCP accept failed: {e}")
                continue
            threading.Thread(target=self.handle_tcp_client, args=(conn, addr), daemon=True).start()

    def handle_tcp_client(self, conn, addr):
        """Handles one TCP connection: read one request, reply, then close."""
        with TCPConnection(conn) as tcp:
            try:
                msg = tcp.recv_message()
            except (MalformedMessageError, ConnectionClosedError, socket.timeout) as e:
                self.log.warning(f"[TCP {addr}] Error: {e}")
                return

            log_recv(self.log, addr, msg["type"], msg["rq"], msg["data"], tcp=True)
            try:
                self.dispatch_tcp(msg, tcp, addr)
            except Exception:
                self.log.exception(f"TCP handler for {msg['type']} (RQ: {msg['rq']}) from {addr} crashed.")

    def dispatch_tcp(self, msg, tcp, addr):
        """Routes a TCP request to its handler."""
        msg_type = msg["type"]

        # TODO P3-02

        self.log.warning(f"Unknown TCP message type from {addr}: {msg_type} (rq={msg['rq']})")

    def send_tcp(self, tcp, addr, msg_type, rq_num, payload=None):
        """Sends one message on a TCP connection and logs it."""
        tcp.send_message(msg_type, rq_num, payload)
        log_send(self.log, addr, msg_type, rq_num, payload, tcp=True)

    def listen(self):
        """Main loop continuously listening for incoming UDP datagrams."""
        threading.Thread(target=self.listen_tcp, daemon=True).start()
        while True:
            try:
                data, addr = self.sock.recvfrom(4096)
            except ConnectionResetError:
                # On Windows, sending UDP to a client that has closed its socket can make
                # the next recvfrom() raise this error. Ignore the error so the server keeps running.
                self.log.warning("ConnectionResetError: A client likely closed its socket. Continuing...")
                continue
            # Dispatch to a new thread for concurrent processing
            threading.Thread(target=self.handle_client, args=(data, addr), daemon=True).start()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CENRS Emergency Server")
    parser.add_argument("port", nargs="?", type=int, default=5000, help="UDP port to listen on (default: 5000)")
    parser.add_argument("state_file", nargs="?", default="server_state.json", help="file used to save and restore server state")
    parser.add_argument("--tcp-port", type=int, default=None, help="TCP port for GET_ACTIVE_ALERTS (default: same number as the UDP port)")
    parser.add_argument("--ack-timeout", type=float, default=2.0, help="seconds to wait for the first ALERT_ACK; doubles on each retry (default: 2.0)")
    parser.add_argument("--drop-rate", type=float, default=0.0, help="chance (0 to 1) of ignoring a received ALERT_ACK, to simulate packet loss (default: 0.0)")
    args = parser.parse_args()

    # validate drop rate
    if not 0 <= args.drop_rate <= 1:
        parser.error("drop-rate must be between 0 and 1")

    server = EmergencyServer(port=args.port, state_file=args.state_file, ack_timeout=args.ack_timeout, drop_rate=args.drop_rate, tcp_port=args.tcp_port)
    server.listen()