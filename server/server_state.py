import threading
import json
import os

from server.incidents import Incident, IncidentIDGenerator


class ServerState:
    def __init__(self, filename="server_state.json"):
        self.users = {}  # name -> user profile and subscriptions
        self.incidents = {}  # Incident_ID -> Incident
        self.incident_ids = IncidentIDGenerator()
        self.alert_recipients = {}  # Incident_ID -> names that were sent the incident (ALL_CLEAR goes to them, 2.7)
        # TODO P2-09: store the latest status report per (name, Incident_ID) (2.8)
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

    def save_to_file(self):
        # locked the shared state while we save
        with self.lock:
            users_to_save = {}

            # Convert subscriptions into a JSON-compatible format
            for name, user in self.users.items():
                users_to_save[name] = user.copy()
                users_to_save[name]["subscriptions"] = [
                    list(sub) for sub in user["subscriptions"]
                ]

            # Write while still holding the lock so two threads never write the file at the same time
            # (create server_states/ if it doesn't exist yet)
            os.makedirs(os.path.dirname(self.filename), exist_ok=True)
            # TODO P2-11: also save incidents (Incident.to_dict()), status reports and delivery state
            with open(self.filename, "w") as f:
                json.dump(users_to_save, f, indent=4)

    def load_from_file(self):
        # Only load data if the file exists
        if os.path.exists(self.filename):
            with open(self.filename, "r") as f:
                self.users = json.load(f)

            # Convert subscriptions back into sets of tuples
            for user in self.users.values():
                user["subscriptions"] = {
                    tuple(sub) for sub in user["subscriptions"]
                }
            # TODO P2-11: restore incidents with Incident.from_dict(), plus status reports and delivery state
