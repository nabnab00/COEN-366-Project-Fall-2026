import logging

from server.alerts import matching_subscribers

log = logging.getLogger("server")

def handle_close_alert(state, msg, addr, send_response, send_notification, persist=None):
    """Close an incident, reply ALERT_CLOSED, then send ALL_CLEAR to its subscribers"""
    rq_num = msg["rq"]
    data = msg.get("data")
    if not isinstance(data, dict):
        data = {}
    incident_id = data.get("Incident_ID")
    reason = data.get("Reason")

    # Check types before using incident_id as a dict key, since a list or dict would raise TypeError
    if not isinstance(incident_id, str) or not incident_id or not isinstance(reason, str) or not reason:
        log.warning(f"CLOSE_ALERT from {addr} denied: Malformed_Request")
        send_response(addr, "ALERT_DENIED", rq_num, {"Reason": "Malformed_Request"})
        return

    with state.lock:
        name, user = state.find_user_by_endpoint(addr)
        incident = state.get_incident(incident_id)

        if name is None:
            error = "Not_Registered"
        elif user["role"] == "SUBSCRIBER":
            error = "Unauthorized_Role"
        elif incident is None:
            error = "Unknown_Incident"
        elif not incident.is_active:
            error = "Incident_Closed"
        elif incident.publisher != name:
            error = "Not_Incident_Publisher"
        else:
            error = None
            incident.close() # status becomes CLOSED and Version goes up by 1
            payload = {"Incident_ID": incident_id, "Version": incident.version, "Message": reason}

            # ALL_CLEAR goes to everyone who got the alert, plus everyone subscribed to it now
            recipients = {} # name -> (ip, udp_port)
            for sub_name in state.alert_recipients.get(incident_id, set()):
                if sub_name in state.users: # skip anyone who has since de-registered
                    recipients[sub_name] = (state.users[sub_name]["ip"], state.users[sub_name]["udp_port"])

            for sub_name, sub_addr in matching_subscribers(state, incident.location, incident.category):
                recipients[sub_name] = sub_addr

    if error:
        log.warning(f"CLOSE_ALERT from {addr} denied: {error}")
        send_response(addr, "ALERT_DENIED", rq_num, {"Reason": error})
        return
    
    if persist:
        persist()

    send_response(addr, "ALERT_CLOSED", rq_num, {"Incident_ID": incident_id})

    # ALL_CLEAR always needs an ACK no matter the severity
    for sub_name, sub_addr in recipients.items():
        send_notification(sub_addr, "ALL_CLEAR", payload, needs_ack=True, name=sub_name)

    log.info(f"STATE  [CLOSE_ALERT] {incident_id} closed by {name}, ALL_CLEAR sent to {len(recipients)} subscribers")
