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
    for name, addr in recipients:
        send_notification(addr, "ALERT", payload, needs_ack=needs_ack, name=name)

    names = [name for name, _ in recipients]
    log.info(f"STATE  [ALERT] {payload['Incident_ID']} v{payload['Version']} sent to "
             f"{len(names)} subscriber(s): {', '.join(names) or 'none'}")
    return names


PUBLISHER_ROLES = {Role.PUBLISHER.value, Role.BOTH.value}
SEVERITIES = {severity.value for severity in Severity}


def handle_update_alert(
    state,
    msg,
    addr,
    send_response,
    send_notification,
    persist=None,
):
    rq_num = msg["rq"]
    data = msg["data"]
    error = None

    # 1. Validate the required fields.
    required_fields = ("Incident_ID", "Severity", "Title", "Description")

    if not isinstance(data, dict) or any(
        not isinstance(data.get(field), str) or not data[field].strip()
        for field in required_fields
    ):
        error = "Malformed_Request"
    

    elif data["Severity"] not in SEVERITIES:
        error = "Invalid_Severity"

    elif len(data["Title"]) > 100 or len(data["Description"]) > 1000:
        error = "Malformed_Request"

    elif "Name" in data and not isinstance(data["Name"], str):
        error = "Malformed_Request"

    if error is None:
        # 2. Check permission and update shared data under the lock.
        with state.lock:
            name, user = state.find_user_by_endpoint(addr)
            incident = state.get_incident(data["Incident_ID"])

            if name is None:
                error = "Not_Registered"

            elif data.get("Name") is not None and data["Name"] != name:
                error = "Endpoint_Mismatch"

            elif user["role"] not in PUBLISHER_ROLES:
                error = "Unauthorized_Role"

            elif incident is None:
                error = "Unknown_Incident"

            elif not incident.is_active:
                error = "Incident_Closed"

            elif incident.publisher != name:
                error = "Not_Incident_Publisher"

            else:
                # This method also increments Version.
                incident.apply_update(
                    severity=data["Severity"],
                    title=data["Title"],
                    description=data["Description"],
                )

                # Snapshot this version before releasing the lock.
                payload = {
                    "Incident_ID": incident.incident_id,
                    "Version": incident.version,
                    "Severity": incident.severity,
                    "Title": incident.title,
                    "Description": incident.description,
                }

                recipients = matching_subscribers(
                    state,
                    incident.location,
                    incident.category,
                )

                # Remember recipients for a future ALL_CLEAR.
                state.alert_recipients.setdefault(
                    incident.incident_id, set()
                ).update(
                    subscriber_name
                    for subscriber_name, _ in recipients
                )

    # 3. Reject without changing anything if a check failed.
    if error is not None:
        log.warning(f"UPDATE_ALERT rejected from {addr}: {error}")

        send_response(
            addr,
            "ALERT_DENIED",
            rq_num,
            {"Reason": error},
        )
        return

    # 4. Save after releasing the lock.
    if persist is not None:
        persist()

    # 5. Confirm the update to the publisher.
    send_response(
        addr,
        "ALERT_UPDATED",
        rq_num,
        {
            "Incident_ID": payload["Incident_ID"],
            "Version": payload["Version"],
        },
    )

    # 6. Send the update to matching subscribers.
    needs_ack = payload["Severity"] == Severity.CRITICAL.value

    for _, subscriber_addr in recipients:
        send_notification(
            subscriber_addr,
            "ALERT_UPDATE",
            payload,
            needs_ack=needs_ack,
        )

    log.info(
        f"STATE [ALERT_UPDATE] {payload['Incident_ID']} "
        f"v{payload['Version']} updated by {name}; "
        f"sent to {len(recipients)} subscriber(s)"
    )
# TODO P2-08