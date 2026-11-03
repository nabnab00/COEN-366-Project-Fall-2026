import logging, os

def get_logger(name, logfile):
    os.makedirs(os.path.dirname(logfile) or ".", exist_ok=True)
    log = logging.getLogger(name)
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s.%(msecs)03d [%(name)s] %(message)s", "%Y-%m-%d %H:%M:%S")
    for h in (logging.StreamHandler(), logging.FileHandler(logfile)):
        h.setFormatter(fmt)
        log.addHandler(h)
    return log

def log_send(log, addr, msg_type, rq, payload):
    log.info(f"SEND -> {addr[0]}:{addr[1]}  {msg_type} {rq} {payload or {}}")

def log_recv(log, addr, msg_type, rq, payload):
    log.info(f"RECV <- {addr[0]}:{addr[1]}  {msg_type} {rq} {payload}")