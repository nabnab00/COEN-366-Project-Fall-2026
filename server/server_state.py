import threading
import json
import os

from server.incidents import Incident, IncidentIDGenerator
from shared.constants import DeliveryStatus


class ServerState:
    def __init__(self, filename="server_state.json"):
        self.users = {}  # name -> user profile and subscriptions
        self.incidents = {}  # Incident_ID -> Incident
        self.incident_ids = IncidentIDGenerator()
        self.alert_recipients = {}  # Incident_ID -> names that were sent the incident (ALL_CLEAR goes to them, 2.7)
        self.status_reports = {}  # incident ID -> {client name: latest status}
        self.delivery_status = {}   # Incident_ID -> {name: {"version": int, "status": PENDING/CONFIRMED/UNCONFIRMED}} (2.5)
        self.lock = threading.Lock()
        self.filename = "server_states/" + filename

        # Restore saved users when the server state is created
        self.load_from_file()

        # Continue incident numbering after any restored incidents so IDs are never reused
        # (incidents are restored once they are saved to the state file, see P2-11)
        self.incident_ids.seed(self.incidents.keys())

    def create_incident(self, publisher, category, location, severity, title, description, attachment="NONE") -> Incident:

        incident = Incident(
            incident_id=self.incident_ids.get_next(),
            publisher=publisher,
            category=category,
            location=location,
            severity=severity,
            title=title,
            description=description,
            attachment=attachment or "NONE",
        )
        self.incidents[incident.incident_id] = incident
        return incident

    def find_user_by_endpoint(self, addr) -> tuple[str, dict] | tuple[None, None]:
        ip, udp_port = addr
        for name, user in self.users.items():
            if user["ip"] == ip and user["udp_port"] == udp_port:
                return name, user
        return None, None

    def get_incident(self, incident_id) -> Incident | None:
        return self.incidents.get(incident_id)

    def record_delivery(self, incident_id, version, name, status):
        """Caller must hold self.lock. Ignored if a newer version of ALERT is already recorded for this subscriber."""
        current = self.delivery_status.get(incident_id, {}).get(name)
        # An older version can still be retrying (or get a late ACK) after an ALERT_UPDATE was sent
        if current is not None and current["version"] > version:
            return
        self.delivery_status.setdefault(incident_id, {})[name] = {"version": version, "status": status}

    def save_to_file(self):
        with self.lock:
            users_to_save = {}

            # JSON cannot store sets, so convert subscriptions to lists.
            for name, user in self.users.items():
                users_to_save[name] = user.copy()
                users_to_save[name]["subscriptions"] = [
                    list(sub) for sub in user["subscriptions"]
                ]

            state_to_save = {
                "schema_version": 2,
                "users": users_to_save,

                # Convert Incident objects into dictionaries.
                "incidents": {
                    incident_id: incident.to_dict()
                    for incident_id, incident in self.incidents.items()
                },

                "status_reports": self.status_reports,

                "delivery_status": self.delivery_status,

                # Convert recipient sets into lists.
                "alert_recipients": {
                    incident_id: list(names)
                    for incident_id, names in self.alert_recipients.items()
                },
            }

            os.makedirs(os.path.dirname(self.filename), exist_ok=True)

            # Write a temporary file first, then replace the old save.
            temp_filename = self.filename + ".tmp"

            with open(temp_filename, "w", encoding="utf-8") as f:
                json.dump(state_to_save, f, indent=4)
                f.flush()
                os.fsync(f.fileno())

            os.replace(temp_filename, self.filename)

    def load_from_file(self):
        if not os.path.exists(self.filename):
            return

        with open(self.filename, "r", encoding="utf-8") as f:
            saved_state = json.load(f)

        # Also load the Phase 1 format, which saved only users.
        if saved_state.get("schema_version") == 2:
            self.users = saved_state["users"]

            self.incidents = {
                incident_id: Incident.from_dict(incident_data)
                for incident_id, incident_data
                in saved_state.get("incidents", {}).items()
            }

            self.status_reports = saved_state.get("status_reports", {})

            self.delivery_status = saved_state.get("delivery_status", {})

            # Retransmission timers are not saved, so a delivery that was still PENDING
            # when the server stopped can never be confirmed: mark it UNCONFIRMED.
            for deliveries in self.delivery_status.values():
                for delivery in deliveries.values():
                    if delivery["status"] == DeliveryStatus.PENDING.value:
                        delivery["status"] = DeliveryStatus.UNCONFIRMED.value

            self.alert_recipients = {
                incident_id: set(names)
                for incident_id, names
                in saved_state.get("alert_recipients", {}).items()
            }

        else:
            # The previous format stored users directly at the top level.
            self.users = saved_state

        # Restore subscription lists to sets of tuples.
        for user in self.users.values():
            user["subscriptions"] = {
                tuple(sub) for sub in user["subscriptions"]
            }
