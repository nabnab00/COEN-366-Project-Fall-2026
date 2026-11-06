# COEN-366-Project-Fall-2026
Campus Emergency Notification and Response System (CENRS)

## Table of contents
- [Project structure](#project-structure)
- [Running the system](#running-the-system)
  - [Requirements](#requirements)
  - [Commands for your operating system](#commands-for-your-operating-system)
  - [Starting the server](#starting-the-server)
  - [Starting a client](#starting-a-client)
  - [Example session](#example-session)
  - [Resetting everything](#resetting-everything)
  - [Current limitations](#current-limitations)
- [Protocol decisions](#protocol-decisions)
  - [PUBLISH_ALERT](#publish_alert)
- [Logging](#logging)
  - [Log line format](#log-line-format)
  - [Logger or print?](#logger-or-print)
  - [Log levels](#log-levels)
  - [How to log in your code](#how-to-log-in-your-code)
- [Running the tests](#running-the-tests)
  - [How the tests work](#how-the-tests-work)
  - [Adding a test](#adding-a-test)
  - [If a test fails](#if-a-test-fails)

## Project structure

```
COEN-366-Project-Fall-2026/
├── server/
│   ├── emergency_server.py   UDP listener: decodes each message and hands it to a handler (one thread per message)
│   ├── registration.py       REGISTER / DE-REGISTER
│   ├── subscriptions.py      SUBSCRIBE / UNSUBSCRIBE, and matches() for alert matching
│   ├── incidents.py          Incident model (version, ACTIVE/CLOSED) and the Incident_ID generator
│   ├── publish.py            PUBLISH_ALERT
│   └── server_state.py       users, subscriptions and incidents in memory; users saved to and loaded from a JSON file
├── client/
│   ├── client_app.py         CENRSClient: sends requests, receives replies on a background thread, saves its profile
│   └── commands.py           the terminal menu
├── shared/                   code used by both server and client
│   ├── protocol.py           message encoding and decoding
│   ├── constants.py          roles, locations, categories, severities, user and incident statuses, and the RQ# generator
│   └── logger.py             logger setup and the SEND/RECV log helpers
└── tests/                    automated tests (see Running the tests)
```

---
Created when the system runs (all in `.gitignore`):

| Folder | Contents |
|--------|----------|
| `server_states/` | the server's saved users and subscriptions |
| `profiles/` | each client's saved profile (name, role, subscriptions) |
| `logs/` | log files for the server and each client |

Every message is a JSON object with the same three fields:
```json
{"type": "REGISTER", "rq": 1, "data": {"Name": "Alice", "Role": "SUBSCRIBER", "IP": "127.0.0.1", "UDP_Port": 6001, "TCP_Port": 0}}
```
`type` is the message type, `rq` is the RQ# (request number), and `data` holds the message's fields.
A reply carries the same `rq` as the request it answers.

## Running the system

Run every command from the repository root, one terminal per process.

### Requirements
- Python 3.10 or later
- No packages to install: the code only uses Python's standard library

### Commands for your operating system
The rest of this README writes commands with `python3`, as on macOS and Linux.
**On Windows, type `py` instead of `python3`** (or `python` if `py` isn't found). Everything after it is the same.

Open a separate terminal window or tab for the server and for each client, and `cd` into the repository folder in each one.

#### macOS
Terminal app: **Cmd + T** opens a new tab.
```bash
python3 --version                                # check Python is installed (3.10 or later)
python3 -m server.emergency_server               # start the server
python3 -m client.client_app 6001                # start a client
python3 -m unittest -v                           # run the tests
rm -rf server_states profiles logs               # reset everything
```

#### Linux
Most terminals: **Ctrl + Shift + T** opens a new tab.
```bash
python3 --version
python3 -m server.emergency_server
python3 -m client.client_app 6001
python3 -m unittest -v
rm -rf server_states profiles logs
```

#### Windows (PowerShell)
Windows Terminal: **Ctrl + Shift + T** opens a new tab.
```powershell
py --version
py -m server.emergency_server
py -m client.client_app 6001
py -m unittest -v
Remove-Item -Recurse -Force server_states, profiles, logs
```
If Windows Defender Firewall asks whether to allow Python on the network, allow it on private networks.

### Starting the server
```bash
python3 -m server.emergency_server
```
The server listens on UDP `127.0.0.1:5000` and saves its state to `server_states/server_state.json`.
On startup it restores the saved users and subscriptions, so a restarted server remembers everyone.

Optional arguments (only needed for testing; the demo uses the defaults):

| Argument | Default | Meaning |
|----------|---------|---------|
| `port` | `5000` | UDP port the server listens on |
| `state_file` | `server_state.json` | state file name, inside `server_states/` |

```bash
python3 -m server.emergency_server 5099 test.json     # test server: port 5099, server_states/test.json
```

### Starting a client
Start each client in its own terminal, with its own UDP port:
```bash
python3 -m client.client_app 6001
python3 -m client.client_app 6002
```
- Use a port from 1024 to 65535, other than the server's port.
- The client saves its profile in `profiles/`. Starting it again on the same port restores that profile.
- With no port, the client picks a free port the first time and saves it in `profiles/client_profile.json`.

Optional argument (only needed for testing):

| Argument | Default | Meaning |
|----------|---------|---------|
| `--server-port` | `5000` | UDP port of the server to talk to |

```bash
python3 -m client.client_app 6101 --server-port 5099   # talk to the test server
```
When switching to a different server, use a client port you haven't used before.
Otherwise the client restores a profile that the other server has never heard of.

#### Menu

| Option | Action | You are asked for |
|--------|--------|-------------------|
| `1` | Register | name, role (`SUBSCRIBER`, `PUBLISHER` or `BOTH`), TCP port (`0` for a subscriber; publishers need a real port) |
| `2` | De-register | — |
| `3` | Subscribe | location, category |
| `4` | Unsubscribe | location, category |
| `5` | List subscriptions | — |
| `q` | Quit | — |

Locations: `HALL`, `EV`, `JMSB`, `LOYOLA`, `SGW`, `ALL`
Categories: `FIRE`, `SECURITY`, `WEATHER`, `POWER`, `BUILDING`, `GENERAL`, `ALL`
`ALL` is a wildcard: `ALL/FIRE` matches a fire alert at any location.

### Example session
```bash
# Terminal 1
python3 -m server.emergency_server

# Terminal 2: Alice
python3 -m client.client_app 6001      # 1 → Alice, SUBSCRIBER, 0    then 3 → HALL, FIRE

# Terminal 3: Bob
python3 -m client.client_app 6002      # 1 → Bob, SUBSCRIBER, 0      then 3 → ALL, ALL
```
Each terminal shows the messages sent and received; the same lines are written to `logs/`.

### Resetting everything
Delete the generated folders to start from scratch
(on Windows, use the PowerShell command in [Commands for your operating system](#commands-for-your-operating-system)):
```bash
rm -rf server_states profiles logs
```
Reset `server_states/` and `profiles/` **together**. If only the server is reset, clients still believe
they are registered, and the server ignores their DE-REGISTER because it has no record of them.

### Current limitations
- The server listens on `127.0.0.1` and clients register with IP `127.0.0.1`, so everything must run on the same machine.
- A client gets no feedback if the server never replies (for example, DE-REGISTER for a name the server doesn't know).
  A reply timeout is planned for Phase 2.

## Protocol decisions
Choices the spec leaves to the team. Copy these into the report's design and assumptions sections.IDK what to write so I let Ai do it. Reminder to delete after !!!!

### PUBLISH_ALERT
Request payload: `Category`, `Location`, `Severity`, `Title`, `Description`, and optionally `Attachment` (missing means `NONE`) and `Name`.

- **Identifying the publisher.** The spec's PUBLISH_ALERT has no Name field, so the server finds the sender by the IP and UDP port it registered with (`ServerState.find_user_by_endpoint`). If the client also sends `Name`, it must be the name registered at that endpoint. UPDATE_ALERT and CLOSE_ALERT should use the same lookup.
- **Title and Description** are JSON strings, so spaces need no special encoding. Both must be non-empty; Title is limited to 100 characters and Description to 1000, so every ALERT fits in one UDP datagram.
- **ALL is only a subscription wildcard.** An incident must name a real location and category.
- **Attachment** is `NONE` or a plain file name. Paths (`/`, `\`, `..`) are refused so a subscriber can never ask a publisher for a file outside its shared folder.

| Reply | When |
|-------|------|
| `ALERT_ACCEPTED {Incident_ID}` | incident created at version 1, status ACTIVE |
| `ALERT_DENIED Malformed_Request` | a required field is missing, the wrong type, empty, or too long |
| `ALERT_DENIED Invalid_Category` / `Invalid_Location` / `Invalid_Severity` | value not in the list (or `ALL`) |
| `ALERT_DENIED Invalid_Attachment` | attachment is a path or not a valid file name |
| `ALERT_DENIED Not_Registered` | no client is registered at the sender's IP and UDP port |
| `ALERT_DENIED Endpoint_Mismatch` | `Name` was sent but belongs to a different client |
| `ALERT_DENIED Unauthorized_Role` | the sender is registered as SUBSCRIBER |

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
| `tests/test_publish.py` | PUBLISH_ALERT: who may publish, every denial reason, unique IDs under concurrent publishes, and the reply over UDP |
| `tests/test_incidents.py` | Incident model, version and status changes, and unique Incident_IDs (unit tests, no server process) |

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
