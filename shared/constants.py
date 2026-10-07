import threading
from enum import Enum

class Role(Enum):
    SUBSCRIBER = "SUBSCRIBER"
    PUBLISHER = "PUBLISHER"
    BOTH = "BOTH"

class Location(Enum):
    HALL = "HALL"
    EV = "EV"
    JMSB = "JMSB"
    LOYOLA = "LOYOLA"
    SGW = "SGW"
    ALL = "ALL"

class Category(Enum):
    FIRE = "FIRE"
    SECURITY = "SECURITY"
    WEATHER = "WEATHER"
    POWER = "POWER"
    BUILDING = "BUILDING"
    GENERAL = "GENERAL"
    ALL = "ALL"

class Severity(Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"

class Status(Enum):
    SAFE = "SAFE"
    NEED_HELP = "NEED_HELP"
    LEFT_AREA = "LEFT_AREA"

class RQGenerator:
    """Thread-safe request number generator."""
    def __init__(self):
        self._lock = threading.Lock()
        self._counter = 0

    def get_next(self) -> int:
        with self._lock:
            self._counter += 1
            return self._counter