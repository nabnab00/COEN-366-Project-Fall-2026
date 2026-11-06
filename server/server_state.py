import threading
import json
import os

from server.incidents import Incident, IncidentIDGenerator


class ServerState:
    def __init__(self, filename="server_state.json"):
        self.users = {}  # name -> user profile and subscriptions
        self.incidents = {}  # Incident_ID -> Incident
        self.incident_ids = IncidentIDGenerator()
        self.lock = threading.Lock()
        self.filename = "server_states/" + filename

        # Restore saved users when the server state is created
        self.load_from_file()

        # Continue incident numbering after any restored incidents so IDs are never reused
        # (incidents are restored once they are saved to the state file, see P2-11)
        self.incident_ids.seed(self.incidents.keys())

    def create_incident(self, publisher, category, location, severity, title, description, attachment="NONE") -> Incident:
        """Creates a new ACTIVE incident at version 1 with a fresh Incident_ID and stores it.
        The caller must hold self.lock, the same way handlers modify self.users."""
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
        """Returns (name, user) for the registered client whose IP and UDP port match addr, or (None, None).
        PUBLISH_ALERT, UPDATE_ALERT and CLOSE_ALERT carry no Name field, so the server identifies
        the sender by the endpoint it registered with. The caller must hold self.lock."""
        ip, udp_port = addr
        for name, user in self.users.items():
            if user["ip"] == ip and user["udp_port"] == udp_port:
                return name, user
        return None, None

    def get_incident(self, incident_id) -> Incident | None:
        """Returns the incident with this ID, or None if it doesn't exist. The caller must hold self.lock."""
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