import logging

from shared.constants import Status

log = logging.getLogger("server")

VALID_STATUSES = {status.value for status in Status}


def handle_status_report(state, msg, addr, send_response, persist=None):
    rq_num = msg["rq"]
    data = msg["data"]
    error = None

    # 1. Check that all required fields contain non-empty strings.
    required_fields = ("Incident_ID", "Name", "Status")

    if not isinstance(data, dict) or any(
        not isinstance(data.get(field), str) or not data[field].strip()
        for field in required_fields
    ):
        error = "Malformed_Request"

    # 2. Check that the reported status is allowed.
    elif data["Status"] not in VALID_STATUSES:
        error = "Invalid_Status"

    if error is None:
        # 3. Protect shared data while checking and updating it, mutex is used
        with state.lock:
            name = data["Name"]
            incident_id = data["Incident_ID"]

            sender_name, _ = state.find_user_by_endpoint(addr)
            incident = state.get_incident(incident_id)

            if name not in state.users or sender_name is None:
                error = "Not_Registered"

            elif sender_name != name:
                error = "Endpoint_Mismatch"

            elif incident is None:
                error = "Unknown_Incident"

            elif not incident.is_active:
                error = "Incident_Closed"

            else:
                # 4. Create the incident's status dictionary if needed.
                reports = state.status_reports.setdefault(incident_id, {})

                # Store this client's latest status.
                reports[name] = data["Status"]

    # 5. Reject an invalid report.
    if error is not None:
        log.warning(f"STATUS_REPORT rejected from {addr}: {error}")
        send_response(
            addr,
            "STATUS_REJECTED",
            rq_num,
            {"Reason": error},
        )
        return

    # 6. Save after releasing the lock.
    if persist is not None:
        persist()

    log.info(
        f"STATUS_REPORT recorded: {name} -> "
        f"{incident_id}: {data['Status']}"
    )

    # 7. Confirm the report using the original request number.
    send_response(addr, "STATUS_RECORDED", rq_num, {})