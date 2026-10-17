from server.server_state import ServerState
from shared.constants import Location, Category, Role

VALID_LOCATIONS = {loc.value for loc in Location}
VALID_CATEGORIES = {cat.value for cat in Category}
SUBSCRIBER_ROLES = {Role.SUBSCRIBER.value, Role.BOTH.value}


def _validate_request(data: dict) -> str | None:
    """Validates the client's request payload fields."""
    name = data.get("Name")
    location = data.get("Location")
    category = data.get("Category")

    if not isinstance(name, str) or not isinstance(location, str) or not isinstance(category, str):
        return "Malformed_Request"
    if location not in VALID_LOCATIONS:
        return "Invalid_Location"
    if category not in VALID_CATEGORIES:
        return "Invalid_Category"
    return None



def _validate_client(state: ServerState, name: str) -> str | None:
    """Checks if the user is registered and allowed to subscribe."""
    user = state.users.get(name)
    if user is None:
        return "Not_Registered"
    if user.get("role") not in SUBSCRIBER_ROLES:
        return "Invalid_Role"
    return None



# TODO: Resham: Pass the persist function once it is implemented
def handle_subscribe(state: ServerState, msg: dict, addr: tuple[str, int], send_response, persist=None):
    """Handles a SUBSCRIBE request."""
    rq_num = msg["rq"]
    data = msg["data"]

    error = _validate_request(data)
    if error is not None:
        send_response(addr, "SUBSCRIPTION-DENIED", rq_num, {"Reason": error})
        return

    name = data["Name"]
    subscription = (data["Location"], data["Category"])

    with state.lock:
        error = _validate_client(state, name)
        if error is None:
            user = state.users[name]
            if "subscriptions" not in user:
                user["subscriptions"] = set() # if subscriptions are not already created, initialize it to an empty set
            if subscription in user["subscriptions"]:
                error = "Already_Subscribed"
            else:
                user["subscriptions"].add(subscription)
                if persist is not None:
                    persist(state)

    if error is not None:
        send_response(addr, "SUBSCRIPTION-DENIED", rq_num, {"Reason": error})
        return

    send_response(addr, "SUBSCRIBED", rq_num)



def handle_unsubscribe(state: ServerState, msg: dict, addr: tuple[str, int], send_response, persist=None):
    """Handles an UNSUBSCRIBE request. Only exact (Location, Category) pairs are removed."""
    rq_num = msg["rq"]
    data = msg["data"]

    error = _validate_request(data)
    if error is not None:
        send_response(addr, "UNSUBSCRIPTION-DENIED", rq_num, {"Reason": error})
        return

    name = data["Name"]
    subscription = (data["Location"], data["Category"])

    with state.lock:
        error = _validate_client(state, name)
        if error is None:
            user = state.users[name]
            subscriptions = user.get("subscriptions", set())
            if subscription not in subscriptions:
                error = "Not_Subscribed"
            else:
                subscriptions.remove(subscription)
                if persist is not None:
                    persist(state)

    if error is not None:
        send_response(addr, "UNSUBSCRIPTION-DENIED", rq_num, {"Reason": error})
        return

    send_response(addr, "UNSUBSCRIBED", rq_num)



# TODO: Use this function in phase 2 for handling alerts and sending notifs to clients
def matches(subscriptions, location, category):
    """Checks if an alert at (location, category) matches any of the user's subscriptions."""
    for sub_location, sub_category in subscriptions:
        location_ok = sub_location == location or sub_location == "ALL"
        category_ok = sub_category == category or sub_category == "ALL"
        if location_ok and category_ok:
            return True
    return False
