import heapq
import logging
import random
import threading
import time
from dataclasses import dataclass

from shared.constants import DeliveryStatus

log = logging.getLogger("server")


@dataclass
class PendingNotification:
    """A server-sent notification (ALERT, ALL_CLEAR) still waiting for its ACK."""
    rq_num: int
    address: tuple[str, int]  # IP:port
    msg_type: str  # ALERT, ALL_CLEAR
    payload: dict
    name: str | None # subscriber/client name
    attempts: int = 1


class RetransmissionManager:
    """Retransmits unacknowledged server notifications using one scheduler thread."""

    def __init__(self, resend, base_timeout=2.0, max_attempts=3, max_random_delay=0.2, on_unconfirmed=None):
        self.resend = resend                  # resend(address, msg_type, rq_num, payload), same RQ# as the original
        self.base_timeout = base_timeout      # base wait time after the first transmission (in seconds); doubles after each retry
        self.max_attempts = max_attempts      # total transmission attempts
        self.max_random_delay = max_random_delay    # up to this many random seconds are added to each wait so notif retries don't all fire together
        self.on_unconfirmed = on_unconfirmed        # callback for unconfirmed notifications after the last attempt times out

        self.pending: dict[int, PendingNotification] = {}        # RQ# -> PendingNotification for retransmitting notifications
        self.heap: list[tuple[float, int, int]] = []             # a min-heap of (deadline, rq_num, attempt) tuples for retransmitting notifications
        self.condition = threading.Condition()                   # for synchronizing the scheduler thread
        self.unconfirmed: dict[int, PendingNotification] = {}    # RQ# -> PendingNotification marked as unconfirmed, kept so a late ACK can still be verified
        self.running = True
        self.thread = threading.Thread(target=self._run, name="retransmission", daemon=True)
        self.thread.start()


    def _wait_for(self, attempt: int) -> float:
        """Seconds to wait for an ACK after transmission attempt."""
        # Wait times: about 2 s after attempt 1, 4 s after attempt 2, 8 s after attempt 3 (with default timeout=2.0)
        return self.base_timeout * (2 ** (attempt - 1)) + random.uniform(0, self.max_random_delay)


    # TODO P2-07, P2-08: don't call track() directly; use EmergencyServer.send_notification(..., needs_ack=True, name=name),
    #                    which also records PENDING in delivery_status and sends the first copy
    def track(self, rq_num, address, msg_type, payload, name=None):
        """Adds a critical notification to the pending list and its timeout deadline to the heap after attempt 1."""
        with self.condition:
            self.pending[rq_num] = PendingNotification(rq_num, address, msg_type, payload, name)
            deadline = time.monotonic() + self._wait_for(1)
            heapq.heappush(self.heap, (deadline, rq_num, 1))
            self.condition.notify()


    def get_notifications(self, status: DeliveryStatus) -> dict[int, PendingNotification]:
        """Returns the notifications for the given status. Caller must hold self.condition."""
        if status == DeliveryStatus.PENDING:
            return self.pending
        if status == DeliveryStatus.UNCONFIRMED:
            return self.unconfirmed
        raise ValueError(f"No notifications are kept with status {status}")


    def peek(self, rq_num, status=DeliveryStatus.PENDING) -> PendingNotification | None:
        """Returns the notification for rq_num without removing it so that the ACK can be verified."""
        with self.condition:
            return self.get_notifications(status).get(rq_num)


    def acknowledge(self, rq_num, status=DeliveryStatus.PENDING) -> PendingNotification | None:
        """Stops retransmitting pending notifications and removes it from the pending list. 
        For unconfirmed status, deletes the notification copy kept for verifying late ACKs."""
        with self.condition:
            return self.get_notifications(status).pop(rq_num, None)


    def stop(self):
        """Ends the scheduler thread."""
        with self.condition:
            self.running = False
            self.condition.notify()
        self.thread.join()


    def _collect_pending_notifs(self) -> tuple[list[PendingNotification], list[PendingNotification]] | tuple[None, None]:
        """Waits until at least one deadline has passed and sorts the pending entries."""
        
        while self.running:
            if not self.heap:
                self.condition.wait()
                continue

            now = time.monotonic()
            if self.heap[0][0] > now:
                self.condition.wait(self.heap[0][0] - now)
                continue

            resend_list = []
            unconfirmed_list = []

            while self.heap and self.heap[0][0] <= now:
                deadline, rq_num, attempt = heapq.heappop(self.heap)
                notification = self.pending.get(rq_num)
                if notification is None or notification.attempts != attempt: # stale notification
                    continue
                if notification.attempts < self.max_attempts: # retransmit
                    notification.attempts += 1
                    deadline = now + self._wait_for(notification.attempts)
                    heapq.heappush(self.heap, (deadline, rq_num, notification.attempts))
                    resend_list.append(notification)
                else:
                    del self.pending[rq_num]
                    self.unconfirmed[rq_num] = notification
                    unconfirmed_list.append(notification)

            return resend_list, unconfirmed_list

        return None, None


    def _run(self):
        """Main scheduler thread to manage pending notifications and retransmit them until they are acknowledged."""
        while True:
            with self.condition:
                resend_list, unconfirmed_list = self._collect_pending_notifs()
                if resend_list is None:
                    return

            for notification in resend_list:
                log.info(f"STATE  [RETRANSMIT] {notification.msg_type} rq={notification.rq_num} to {notification.name} "
                         f"(attempt {notification.attempts}/{self.max_attempts})")
                try:
                    self.resend(notification.address, notification.msg_type, notification.rq_num, notification.payload)
                except OSError as e:
                    log.error(f"Retransmission of rq={notification.rq_num} to {notification.address} failed: {e}")

            for notification in unconfirmed_list:
                log.warning(f"STATE  [UNCONFIRMED] {notification.msg_type} rq={notification.rq_num} to {notification.name} "
                            f"after {self.max_attempts} attempts")
                if self.on_unconfirmed:
                    try:
                        self.on_unconfirmed(notification)
                    except Exception:
                        log.exception(f"on_unconfirmed for rq={notification.rq_num} crashed")
