
import ipaddress

from shared.constants import Role, Location, Category


VALID_ROLES = {role.value for role in Role}


def handle_register(state, msg, addr, send_response, persist=None):
    """Validate and register a new client."""

    rq_num = msg["rq"]
    data = msg["data"]

    required_fields = (
        "Name", "Role", "IP", "UDP_Port", "TCP_Port"
    )

    if any(field not in data for field in required_fields):
        send_response(
            addr, "REGISTER-DENIED", rq_num,
            {"Reason": "Malformed_Request"}
        )
        return

    name = data["Name"]
    role = data["Role"]
    ip = data["IP"]
    udp_port = data["UDP_Port"]
    tcp_port = data["TCP_Port"]

    # Validate field types and values
    if (
        not isinstance(name, str)
        or not name
        or name != name.strip()
        or len(name) > 64
        or any(ch.isspace() for ch in name)
        or not isinstance(role, str)
        or not isinstance(ip, str)
        or type(udp_port) is not int
        or type(tcp_port) is not int
        or not (1 <= udp_port <= 65535)
        or not (0 <= tcp_port <= 65535)
    ):
        send_response(
            addr, "REGISTER-DENIED", rq_num,
            {"Reason": "Malformed_Request"}
        )
        return

    # Validate role
    if role not in VALID_ROLES:
        send_response(
            addr, "REGISTER-DENIED", rq_num,
            {"Reason": "Invalid_Role"}
        )
        return

    # Validate IP address
    try:
        ipaddress.IPv4Address(ip)
    except ipaddress.AddressValueError:
        send_response(
            addr, "REGISTER-DENIED", rq_num,
            {"Reason": "Invalid_IP"}
        )
        return

    # Check that sender matches the claimed UDP endpoint
    if (ip, udp_port) != addr:
        send_response(
            addr, "REGISTER-DENIED", rq_num,
            {"Reason": "Endpoint_Mismatch"}
        )
        return

    # Publisher roles must specify a TCP port
    if role in ("PUBLISHER", "BOTH") and tcp_port == 0:
        send_response(
            addr, "REGISTER-DENIED", rq_num,
            {"Reason": "Invalid_TCP_Port"}
        )
        return

    # Protect shared state from concurrent access
    with state.lock:
        if name in state.users:
            error = "Name_Already_Exists"
        else:
            state.users[name] = {
                "role": role,
                "ip": ip,
                "udp_port": udp_port,
                "tcp_port": tcp_port,
                "subscriptions": set()
            }

            # Optional integration hook for teammate
            if persist is not None:
                persist(state)

            error = None

    if error is not None:
        send_response(
            addr, "REGISTER-DENIED", rq_num,
            {"Reason": error}
        )
        return

    print(f"[REGISTER] Registered {name} ({role})")

    send_response(
        addr, "REGISTERED", rq_num,
        {
            "Location_List": [
                location.value for location in Location
            ],
            "Category_List": [
                category.value for category in Category
            ]
        }
    )


def handle_deregister(state, msg, addr, send_response, persist=None):
    """Remove a previously registered client."""

    rq_num = msg["rq"]
    data = msg["data"]

    name = data.get("Name")

    if not isinstance(name, str) or not name:
        send_response(
            addr, "DEREGISTER-DENIED", rq_num,
            {"Reason": "Malformed_Request"}
        )
        return

    with state.lock:
        user = state.users.get(name)

        # Per the assignment: silently ignore unknown names
        if user is None:
            print(f"[DE-REGISTER] Unknown user: {name}")
            return

        # Prevent a different client endpoint from
        # removing another user's registration
        if (user["ip"], user["udp_port"]) != addr:
            error = "Endpoint_Mismatch"
        else:
            del state.users[name]

            # Optional integration hook for teammate
            if persist is not None:
                persist(state)

            error = None

    if error is not None:
        send_response(
            addr, "DEREGISTER-DENIED", rq_num,
            {"Reason": error}
        )
        return

    print(f"[DE-REGISTER] Removed {name}")

    # Team-defined confirmation extension
    send_response(
        addr, "DE-REGISTERED", rq_num, {}
    )
