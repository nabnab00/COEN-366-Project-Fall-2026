import logging, os

_FORMAT = "%(asctime)s.%(msecs)03d [%(name)s] %(levelname)-7s %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"

def get_logger(name, logfile):
    log = logging.getLogger(name)

    # avoid duplicate handlers
    if log.handlers:
        return log

    log.setLevel(logging.INFO)
    log.propagate = False

    folder = os.path.dirname(logfile)
    if folder:
        os.makedirs(folder, exist_ok=True)

    formatter = logging.Formatter(_FORMAT, _DATEFMT)
    for handler in (logging.StreamHandler(), logging.FileHandler(logfile, encoding="utf-8")):
        handler.setFormatter(formatter)
        log.addHandler(handler)
    return log

def _peer(addr):
    return f"{addr[0]}:{addr[1]}"

def log_send(log, addr, msg_type, rq, payload):
    log.info(f"SEND -> {_peer(addr)}  {msg_type} {rq} {payload or {}}")

def log_recv(log, addr, msg_type, rq, payload):
    log.info(f"RECV <- {_peer(addr)}  {msg_type} {rq} {payload or {}}")