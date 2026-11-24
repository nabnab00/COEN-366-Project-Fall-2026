import socket
import threading
import json
import argparse
from shared.protocol import ProtocolMessage, MalformedMessageError
from shared.constants import RQGenerator, DeliveryStatus
from shared.logger import get_logger, log_recv, log_send
from server.server_state import ServerState
from server import subscriptions, registration, publish, alerts, acks
from server import status_reports
from server.retransmission import RetransmissionManager

class EmergencyServer:
    
    def __init__(self, host='127.0.0.1', port=5000, state_file="server_state.json", ack_timeout=2.0):
        self.host = host
        self.port = port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((self.host, self.port))
        self.rq_gen = RQGenerator()
        self.state = ServerState(state_file)
        self.log = get_logger("server", "logs/server.log")
        self.log.info(f"STATE Restored users from {self.state.filename}:\n{json.dumps(self.state.users, indent=2, default=list)}")
        self.log.info(f"Emergency Server started on {self.host}:{self.port}")
        self.retransmitter = RetransmissionManager(
            resend=self.send_response,
            base_timeout=ack_timeout,
            on_unconfirmed=self.mark_unconfirmed
        )

    def handle_client(self, data: bytes, addr):
        """Worker thread logic for processing incoming messages."""
        try:
            msg = ProtocolMessage.decode(data)
        except MalformedMessageError as e:
            self.log.warning(f"[{addr}] Error: {e}")
            return

        log_recv(self.log, addr, msg['type'], msg['rq'], msg['data'])        

        # Outline for Epic 2 & 3
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
     
        elif msg_type == "ALERT_ACK":
            acks.handle_alert_ack(self.state, self.retransmitter, msg, addr)

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

        # TODO P2-08
    


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
        # TODO P2-08: send ALL_CLEAR with send_notification(addr, "ALL_CLEAR", payload, ...)
        rq_num = self.rq_gen.get_next()
        if needs_ack:
            with self.state.lock:
                self.state.record_delivery(payload["Incident_ID"], payload["Version"], name, DeliveryStatus.PENDING.value)
            self.state.save_to_file()
            self.retransmitter.track(rq_num, addr, msg_type, payload, name)
        self.send_response(addr, msg_type, rq_num, payload)
        return rq_num

    def listen(self):
        """Main loop continuously listening for incoming UDP datagrams."""
        while True:
            data, addr = self.sock.recvfrom(4096)
            # Dispatch to a new thread for concurrent processing
            threading.Thread(target=self.handle_client, args=(data, addr), daemon=True).start()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CENRS Emergency Server")
    parser.add_argument("port", nargs="?", type=int, default=5000, help="UDP port to listen on (default: 5000")
    parser.add_argument("state_file", nargs="?", default="server_state.json", help="file used to save and restore server state")
    parser.add_argument("--ack-timeout", type=float, default=2.0, help="seconds to wait for the first ALERT_ACK; doubles on each retry (default: 2.0)")
    # TODO P2-12
    args = parser.parse_args()
    server = EmergencyServer(port=args.port, state_file=args.state_file, ack_timeout=args.ack_timeout)
    server.listen()