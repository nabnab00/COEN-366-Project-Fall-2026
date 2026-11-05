import threading
import json
import os


class ServerState:
    def __init__(self, filename="server_state.json"):
        self.users = {}  # name -> user profile and subscriptions
        self.lock = threading.Lock()
        self.filename = "server_states/" + filename

        # Restore saved users when the server state is created
        self.load_from_file()

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