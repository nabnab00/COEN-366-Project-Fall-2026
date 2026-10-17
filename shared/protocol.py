import json


class MalformedMessageError(Exception):
    """Raised when received bytes are not a valid protocol message."""


class ProtocolMessage:
    @staticmethod
    def encode(msg_type: str, rq_num: int, payload: dict = None) -> bytes:
        """encodes a message type, request number, and optional payload into JSON bytes."""
        message = {
            "type": msg_type,
            "rq": rq_num,
            "data": payload or {}
        }
        return json.dumps(message).encode('utf-8')

    @staticmethod
    def decode(data: bytes) -> dict:
        """decodes JSON bytes into a message dict with keys "type" (str), "rq" (int) and "data" (dict).
        Raises MalformedMessageError if the bytes are not valid JSON or the message has the wrong shape."""
        try:
            message = json.loads(data.decode('utf-8'))
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise MalformedMessageError("Invalid UTF-8 JSON")

        if not isinstance(message, dict):
            raise MalformedMessageError("Message is not a JSON object")

        msg_type = message.get("type")
        if not isinstance(msg_type, str) or not msg_type:
            raise MalformedMessageError("Missing or invalid 'type'")

        rq = message.get("rq")
        # bool is a subclass of int in Python, so it has to be excluded explicitly
        if not isinstance(rq, int) or isinstance(rq, bool):
            raise MalformedMessageError("Missing or invalid 'rq'")

        if not isinstance(message.get("data"), dict):
            raise MalformedMessageError("Missing or invalid 'data'")

        return message
