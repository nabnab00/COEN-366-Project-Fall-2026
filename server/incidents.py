import threading
import time
from dataclasses import dataclass, field, asdict

from shared.constants import IncidentStatus

INCIDENT_PREFIX = "INC"


class IncidentIDGenerator:
    """Thread-safe generator of globally unique incident IDs (INC001, INC002, ...).

    Unlike RQ#, an Incident_ID must never be reused, even after a server restart.
    Call seed() with the IDs restored from disk so numbering continues after the
    highest one instead of starting again at 1.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._counter = 0

    def seed(self, existing_ids):
        """Continue numbering after the highest existing ID. IDs that don't follow the INC### format are ignored."""
        with self._lock:
            for incident_id in existing_ids:
                number = parse_incident_number(incident_id)
                if number is not None and number > self._counter:
                    self._counter = number

    def get_next(self) -> str:
        with self._lock:
            self._counter += 1
            return f"{INCIDENT_PREFIX}{self._counter:03d}"


def parse_incident_number(incident_id) -> int | None:
    """Returns 102 for "INC102", or None if the ID is not in the INC### format."""
    if not isinstance(incident_id, str) or not incident_id.startswith(INCIDENT_PREFIX):
        return None
    digits = incident_id[len(INCIDENT_PREFIX):]
    if not digits.isdigit():
        return None
    return int(digits)


@dataclass
class Incident:
    """One emergency incident as the server stores it.

    A new incident starts at version 1 and ACTIVE (spec 2.3). UPDATE_ALERT and
    CLOSE_ALERT each increment the version (spec 2.6, 2.7), and (Incident_ID, Version)
    is the pair clients use to detect duplicate alerts (spec 2.5).
    The server only keeps the attachment's file name; the file stays with the publisher (spec 2.9).
    """
    incident_id: str
    publisher: str
    category: str
    location: str
    severity: str
    title: str
    description: str
    attachment: str = "NONE"
    version: int = 1
    status: str = IncidentStatus.ACTIVE.value
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    @property
    def is_active(self) -> bool:
        return self.status == IncidentStatus.ACTIVE.value

    @property
    def has_attachment(self) -> bool:
        return self.attachment != "NONE"

    def apply_update(self, severity: str, title: str, description: str) -> int:
        """Applies an UPDATE_ALERT and returns the new version. Caller must check the incident is active and owned by the sender."""
        self.severity = severity
        self.title = title
        self.description = description
        return self._bump_version()

    def close(self) -> int:
        """Marks the incident CLOSED and returns the new version (spec 2.7)."""
        self.status = IncidentStatus.CLOSED.value
        return self._bump_version()

    def _bump_version(self) -> int:
        self.version += 1
        self.updated_at = time.time()
        return self.version

    def alert_fields(self) -> dict:
        """Payload fields shared by ALERT (spec 2.4) and the GET_ACTIVE_ALERTS records (spec 2.10)."""
        return {
            "Incident_ID": self.incident_id,
            "Version": self.version,
            "Category": self.category,
            "Location": self.location,
            "Severity": self.severity,
            "Title": self.title,
            "Description": self.description,
            "Attachment": self.attachment,
        }

    def to_dict(self) -> dict:
        """JSON-compatible form for saving to the state file."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Incident":
        """Rebuilds an incident read from the state file. Unknown keys are ignored."""
        known = {name: data[name] for name in cls.__dataclass_fields__ if name in data}
        return cls(**known)
