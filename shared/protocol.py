import json

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
        """decodes JSON bytes into a dictionary. Returns an error dictionary if the message is malformed."""
        try:
            return json.loads(data.decode('utf-8'))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {"error": "Malformed message"}