# COEN-366-Project-Fall-2026
Campus Emergency Notification and Response System (CENRS)

## Table of contents
- [Logging](#logging)
  - [Log line format](#log-line-format)
  - [Logger or print?](#logger-or-print)
  - [Log levels](#log-levels)
  - [How to log in your code](#how-to-log-in-your-code)
- [Running the tests](#running-the-tests)
  - [How the tests work](#how-the-tests-work)
  - [Adding a test](#adding-a-test)
  - [If a test fails](#if-a-test-fails)

## Logging

The spec requires that the marker can see every message sent and received, plus progress and failures.
The server and every client write a log both **on screen** and **to a file**:

| Process | Log file |
|---------|----------|
| Server  | `logs/server.log` |
| Client  | `logs/client_<udp_port>.log` |

`logs/` is in `.gitignore`. Delete it any time to start with empty logs.

### Log line format
```
2026-11-04 16:23:40.317 [server] INFO    RECV <- 127.0.0.1:63009  REGISTER 1 {'Name': 'Jake', ...}
2026-11-04 16:23:40.321 [server] INFO    STATE  [REGISTER] Registered Jake (SUBSCRIBER)
2026-11-04 16:23:40.321 [server] INFO    SEND -> 127.0.0.1:63009  REGISTERED 1 {...}
```
timestamp · process · level · message

| Tag | Meaning |
|-----|---------|
| `SEND ->` | this process sent a message; the address is who it went **to** |
| `RECV <-` | this process received a message; the address is who it came **from** |
| `STATE` | the stored state changed (user registered, removed, subscribed…) |

Every request appears twice across the logs: `SEND` in the sender's log and `RECV` in the receiver's,
with the same RQ# (request number). A `SEND` with no matching `RECV` means the datagram was lost.

### Logger or print?

**Logs record what happened on the network. Prints are the user interface.**

| Use | When | Examples |
|-----|------|----------|
| `log` | anything about the protocol or the system's state | messages sent/received, state changes, malformed messages, unknown message types, replies with no matching request, errors, crashes |
| `print` | text meant only for the person using the client menu | the menu, prompts, "Registered successfully as Alice", "Your subscriptions:", "You must register first." |

Ask: *would the marker need this to follow what happened on the network?* If yes, log it. If it's only feedback for the user at the menu, print it.

The server has no user interface, so it should only use `log`, never `print`.

### Log levels

| Level | Use for | Example |
|-------|---------|---------|
| `log.info` | normal events | SEND/RECV, STATE changes, server started |
| `log.warning` | something unexpected that was handled | malformed message, unknown message type, reply with no pending request |
| `log.error` | an operation failed | socket error, send failed |
| `log.exception` | inside an `except` block, when something crashed; includes the traceback | a handler raised an exception |

### How to log in your code

**Sending or receiving a message.** Always use the shared helpers, so every line has the same format:
```python
from shared.logger import log_send, log_recv

log_send(self.log, addr, msg_type, rq_num, payload)
log_recv(self.log, addr, msg["type"], msg["rq"], msg["data"])
```
The server already logs every message in `handle_client()` and `send_response()`, and the client in
`send_message()` and `listen_for_alerts()`. Handlers don't need to log messages again.

**In a server module** (e.g. `server/registration.py`). Get the server's logger by name; no setup needed:
```python
import logging
log = logging.getLogger("server")

log.info(f"STATE  [REGISTER] Registered {name} ({role})")
```
The name must be exactly `"server"`. A different name creates a separate logger that writes nowhere.

**In the client.** Use `self.log`, created in `CENRSClient.__init__`.

## Running the tests

Run every command from the repository root.

```bash
python3 -m unittest -v                                   # all tests
python3 -m unittest tests.test_registration -v           # one file
python3 -m unittest tests.test_registration.TestRegister.test_register_success   # one test
```

Run the tests **before every push / pull request**.

### How the tests work
- Each test starts a **real server** as a separate process on port **5999**, inside a temporary folder
  with an empty state file. Your real `server_states/` and `logs/` are never touched.
- Fake clients are plain UDP sockets (see `tests/helpers.py`). They send messages and check the server's replies and saved state.
- The persistence tests kill the server mid-test to simulate a crash, then restart it on the same state file.

| File | Covers |
|------|--------|
| `tests/helpers.py` | shared setup: start/stop server, fake clients, `register`, `subscribe`, `unsubscribe`, `saved_state` |
| `tests/test_registration.py` | REGISTER and DE-REGISTER, including denial reasons |
| `tests/test_subscriptions.py` | SUBSCRIBE, UNSUBSCRIBE, and wildcard matching |
| `tests/test_persistence.py` | recovery after a crash, and concurrent clients |

### Adding a test
Add a method whose name starts with `test_` to a class that inherits from `ServerTestCase`:
```python
def test_something(self):
    client = self.new_client() # 1. set up
    reply = self.register(client, "Alice") # 2. do one thing
    self.assertEqual(reply["type"], "REGISTERED") # 3. check the result
```
Keep one behaviour per test, and name the test after what it checks.

### If a test fails
- **FAIL**: the server answered differently than expected. Compare the expected and actual values in the output.
- **ERROR with `TimeoutError`**: the server never replied. It may have crashed handling the message.
  Test output hides the server's logs, so reproduce the steps by hand against `python3 -m server.emergency_server 5999` to see them.
- **`Ran 0 tests`**: you're not in the repository root, or a test file isn't directly in `tests/`.