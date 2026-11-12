import threading
import time
from dataclasses import dataclass, field, asdict

from shared.constants import IncidentStatus

INCIDENT_PREFIX = "INC"


class IncidentIDGenerator:

    def __init__(self):
        self._lock = threading.Lock()
        self._counter = 0

    def seed(self, existing_ids):
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
    if not isinstance(incident_id, str) or not incident_id.startswith(INCIDENT_PREFIX):
        return None
    digits = incident_id[len(INCIDENT_PREFIX):]
    if not digits.isdigit():
        return None
    return int(digits)


@dataclass
class Incident:

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
        """2.6"""
        self.severity = severity
        self.title = title
        self.description = description
        return self._bump_version()

    def close(self) -> int:
        """2.7"""
        self.status = IncidentStatus.CLOSED.value
        return self._bump_version()

    def _bump_version(self) -> int:
        self.version += 1
        self.updated_at = time.time()
        return self.version

    def alert_fields(self) -> dict:
        """2.4 and 2.10."""
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
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Incident":
        known = {name: data[name] for name in cls.__dataclass_fields__ if name in data}
        return cls(**known)
