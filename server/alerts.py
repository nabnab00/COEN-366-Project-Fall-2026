import logging

from shared.constants import Role, Severity
from server.subscriptions import matches

log = logging.getLogger("server")

SUBSCRIBER_ROLES = {Role.SUBSCRIBER.value, Role.BOTH.value}


def matching_subscribers(state, location, category) -> list[tuple[str, tuple[str, int]]]:
    """2.4. Returns (name, (ip, udp_port)) for every subscriber matching the alert. Caller must hold state.lock."""
    recipients = []
    for name, user in state.users.items():
        if user["role"] in SUBSCRIBER_ROLES and matches(user.get("subscriptions", ()), location, category):
            recipients.append((name, (user["ip"], user["udp_port"])))
    return recipients


def distribute_alert(state, incident, send_notification) -> list[str]:
    """2.4. Sends ALERT to every matching subscriber and returns their names."""
    # snapshot under the lock, send after releasing it
    with state.lock:
        recipients = matching_subscribers(state, incident.location, incident.category)
        payload = incident.alert_fields()
        state.alert_recipients.setdefault(incident.incident_id, set()).update(name for name, _ in recipients)

    # 2.5: CRITICAL alerts need an ALERT_ACK (P2-04)
    needs_ack = payload["Severity"] == Severity.CRITICAL.value
    for _, addr in recipients:
        send_notification(addr, "ALERT", payload, needs_ack=needs_ack)

    names = [name for name, _ in recipients]
    log.info(f"STATE  [ALERT] {payload['Incident_ID']} v{payload['Version']} sent to "
             f"{len(names)} subscriber(s): {', '.join(names) or 'none'}")
    return names


# TODO P2-07
# TODO P2-08