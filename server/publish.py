import logging

from shared.constants import Role, Location, Category, Severity
from server.incidents import Incident

log = logging.getLogger("server")

PUBLISHER_ROLES = {Role.PUBLISHER.value, Role.BOTH.value}
# ALL is a subscription wildcard (spec 2.2), not a real place or category, so an incident can't use it
INCIDENT_LOCATIONS = {loc.value for loc in Location if loc is not Location.ALL}
INCIDENT_CATEGORIES = {cat.value for cat in Category if cat is not Category.ALL}
SEVERITIES = {sev.value for sev in Severity}

# Limits keep every ALERT for the incident inside one UDP datagram (the receivers read 4096 bytes)
MAX_TITLE_LENGTH = 100
MAX_DESCRIPTION_LENGTH = 1000
MAX_ATTACHMENT_LENGTH = 255

REQUIRED_FIELDS = ("Category", "Location", "Severity", "Title", "Description")


def _validate_publish_request(data: dict) -> str | None:
    """Checks the PUBLISH_ALERT payload. Returns a denial reason, or None if the payload is valid."""
    if any(field not in data for field in REQUIRED_FIELDS):
        return "Malformed_Request"

    for field in ("Category", "Location", "Severity"):
        if not isinstance(data[field], str):
            return "Malformed_Request"

    # Title and Description are JSON strings, so spaces are allowed (spec 2.3 encoding requirement)
    title = data["Title"]
    description = data["Description"]
    if not isinstance(title, str) or not title.strip() or len(title) > MAX_TITLE_LENGTH:
        return "Malformed_Request"
    if not isinstance(description, str) or not description.strip() or len(description) > MAX_DESCRIPTION_LENGTH:
        return "Malformed_Request"

    name = data.get("Name")
    if name is not None and not isinstance(name, str):
        return "Malformed_Request"

    if data["Category"] not in INCIDENT_CATEGORIES:
        return "Invalid_Category"
    if data["Location"] not in INCIDENT_LOCATIONS:
        return "Invalid_Location"
    if data["Severity"] not in SEVERITIES:
        return "Invalid_Severity"

    if not _valid_attachment(data.get("Attachment", "NONE")):
        return "Invalid_Attachment"
    return None


def _valid_attachment(attachment) -> bool:
    """Attachment is NONE or a plain file name the publisher keeps locally (spec 2.3).
    Paths are refused so a subscriber can never ask a publisher for a file outside its shared folder."""
    if attachment == "NONE":
        return True
    return (
        isinstance(attachment, str)
        and 0 < len(attachment) <= MAX_ATTACHMENT_LENGTH
        and attachment == attachment.strip()
        and "/" not in attachment
        and "\\" not in attachment
        and attachment not in (".", "..")
    )


def handle_publish_alert(state, msg, addr, send_response, persist=None) -> Incident | None:
    """Handles a PUBLISH_ALERT request (spec 2.3).

    The sender is identified by its registered IP and UDP port, since PUBLISH_ALERT has no Name field.
    If the client also sends a Name, it must be the name registered at that endpoint.
    On success, replies ALERT_ACCEPTED with the new Incident_ID and returns the incident
    so the server can distribute it (P2-03). On failure, replies ALERT_DENIED and returns None.
    """
    rq_num = msg["rq"]
    data = msg["data"]

    error = _validate_publish_request(data)
    if error is not None:
        send_response(addr, "ALERT_DENIED", rq_num, {"Reason": error})
        return None

    incident = None
    with state.lock:
        name, user = state.find_user_by_endpoint(addr)
        claimed_name = data.get("Name")

        if name is None:
            error = "Not_Registered"
        elif claimed_name is not None and claimed_name != name:
            error = "Endpoint_Mismatch"
        elif user["role"] not in PUBLISHER_ROLES:
            error = "Unauthorized_Role"
        else:
            incident = state.create_incident(
                publisher=name,
                category=data["Category"],
                location=data["Location"],
                severity=data["Severity"],
                title=data["Title"],
                description=data["Description"],
                attachment=data.get("Attachment", "NONE"),
            )

    if error is not None:
        send_response(addr, "ALERT_DENIED", rq_num, {"Reason": error})
        return None

    # save after a successful publish, outside the lock (incidents are written once P2-11 extends the state file)
    if persist is not None:
        persist()

    log.info(f"STATE  [PUBLISH_ALERT] {name} created {incident.incident_id} "
             f"({incident.severity} {incident.category} at {incident.location})")

    send_response(addr, "ALERT_ACCEPTED", rq_num, {"Incident_ID": incident.incident_id})
    return incident
