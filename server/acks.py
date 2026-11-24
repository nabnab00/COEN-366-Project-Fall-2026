import logging

from shared.constants import DeliveryStatus

log = logging.getLogger("server")


def valid_ack(data: dict) -> bool:
    """Checks if the ALERT_ACK payload has Incident_ID (str), Version (int) and Name (str)."""
    if not isinstance(data, dict):
        return False
    return(isinstance(data.get("Incident_ID"), str) 
        and type(data.get("Version")) is int 
        and isinstance(data.get("Name"), str))


def matches(notification, data: dict, addr) -> bool:
    """True if the ACK comes from the subscriber the ALERT was sent to, for the same incident version."""
    return (notification.address == addr
            and notification.name == data["Name"]
            and notification.payload["Incident_ID"] == data["Incident_ID"]
            and notification.payload["Version"] == data["Version"])


def confirm(state, notification):
    """Confirms the delivery status of the ALERT."""
    with state.lock:
        state.record_delivery(notification.payload["Incident_ID"], notification.payload["Version"],
                              notification.name, DeliveryStatus.CONFIRMED.value)
    # TODO P2-11: save delivery_status here


def handle_alert_ack(state, retransmitter, msg, addr):
    """Stops retransmitting an ALERT once its subscriber acknowledges it with an ALERT_ACK"""
    rq_num = msg["rq"]
    data = msg["data"]

    if not valid_ack(data):
        log.warning(f"ALERT_ACK from {addr} has invalid payload: {data}")
        return
    
    notification = retransmitter.peek(rq_num)
    if notification is None:
        handle_late_ack(state, retransmitter, rq_num, data, addr)
        return

    if not matches(notification, data, addr):
        log.warning(f"ALERT_ACK rq={rq_num} from {addr} does not match the original ALERT. Ignoring...")
        return

    if retransmitter.acknowledge(rq_num) is None:
        # The server gave up between the peek(rq_num) and now, 
        # so the ALERT is already marked unconfirmed, so we need to handle it.
        handle_late_ack(state, retransmitter, rq_num, data, addr)
        return

    confirm(state, notification)
    log.info(f"STATE  [ALERT_ACK] {data['Incident_ID']} v{data['Version']} received and confirmed by {notification.name} (rq={rq_num})")


def handle_late_ack(state, retransmitter, rq_num, data, addr):
    """A late ACK after the server gave up turns the subscriber from UNCONFIRMED back to CONFIRMED."""
    notification = retransmitter.peek(rq_num, DeliveryStatus.UNCONFIRMED)
    if notification is None:
        log.info(f"ALERT_ACK rq={rq_num} from {addr} is a duplicate ACK. Ignoring...")
        return

    if not matches(notification, data, addr):
        log.warning(f"Late ALERT_ACK rq={rq_num} from {addr} does not match the original ALERT. Ignoring...")
        return

    if retransmitter.acknowledge(rq_num, DeliveryStatus.UNCONFIRMED) is None:
        log.info(f"ALERT_ACK rq={rq_num} from {addr} is a duplicate ACK. Ignoring...")
        return

    confirm(state, notification)
    log.info(f"STATE  [LATE ACK] {data['Incident_ID']} v{data['Version']} received and confirmed by {notification.name} "
             f"(rq={rq_num}) after the server gave up")